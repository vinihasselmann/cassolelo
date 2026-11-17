"""Processamento de uma versão: propriedades do derivativo -> elements + marks.

Fluxo: status `processing` (commit) -> metadata (vista 3D) -> árvore + propriedades
(só GET; 202 = espera, 413 = forceget) -> substitui os elementos da versão e cria ou
reaproveita as marcas (obra, código, categoria) -> relatório de validação
(mark_validation, na mesma transação) -> `ready` (commit).
Qualquer erro: desfaz, status `failed` com a mensagem.

Idempotente: reprocessar apaga e regrava os elementos daquela versão; as marcas são
reaproveitadas pela unicidade (obra_id, code, category), nunca duplicadas.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from typing import Any

from sqlalchemy import delete, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.aps import derivatives as md
from app.aps.client import ApsClient
from app.aps.errors import ApsError
from app.config import Settings
from app.models import Element, Mark, ModelVersion, Obra, User, VersionPropertyName
from app.models.enums import VersionStatus
from app.observability import metrics
from app.services import (
    assemblies,
    audit,
    events,
    mark_rule,
    mark_validation,
    piece_props,
    piece_units,
    version_reconcile,
)
from app.services.extraction import ExtractedElement, extract_elements, find_prop
from app.services.reconcile import ReconcileConfig

log = logging.getLogger("app.services.processing")

# Versões que ainda não têm conversão pronta não são processadas.
PROCESSABLE = {
    VersionStatus.PENDING.value,
    VersionStatus.PROCESSING.value,  # job anterior interrompido
    VersionStatus.READY.value,  # reprocessamento
    VersionStatus.FAILED.value,
}
CHUNK = 1000
MAX_CODE = 100  # marks.code
MAX_ERROR = 1000
UNEXPECTED_MSG = "Erro inesperado ao processar a versão. Veja o log do worker."


@dataclass(frozen=True)
class ProcessingConfig:
    mark_names: list[str]
    category_names: list[str]
    dimension_names: list[str] = field(default_factory=list)
    tolerance_mm: float = 5.0
    level_names: list[str] = field(default_factory=list)
    search_names: list[str] = field(default_factory=list)
    review_names: list[str] = field(default_factory=list)  # REVIEW_PROPERTY_NAMES (7.2)
    # montagens (.nwd/.rvt): categorias do corpo da peça; vazio = regra antiga
    piece_categories: list[str] = field(default_factory=list)

    @property
    def reconcile(self) -> ReconcileConfig:
        return ReconcileConfig(self.dimension_names, self.review_names, self.tolerance_mm)

    @classmethod
    def from_settings(cls, s: Settings) -> ProcessingConfig:
        return cls(
            mark_names=s.mark_property_list,
            category_names=s.category_property_list,
            dimension_names=s.dimension_property_list,
            tolerance_mm=s.dimension_tolerance_mm,
            level_names=s.level_property_list,
            search_names=s.search_property_list,
            review_names=s.review_property_list,
        )

    def for_obra(self, obra: Obra | None) -> ProcessingConfig:
        """A regra de identificação da obra (se houver) no lugar do padrão do servidor."""
        if obra is None:
            return self
        return replace(
            self,
            mark_names=obra.mark_property_names or self.mark_names,
            category_names=obra.category_property_names or self.category_names,
            piece_categories=obra.piece_category_names or [],
        )


@dataclass(frozen=True)
class ProcessResult:
    version_id: int
    status: str
    elements: int = 0
    without_mark: int = 0
    marks: int = 0
    marks_created: int = 0
    seconds: float = 0.0
    error: str | None = None


def _cut(value: str | None, size: int) -> str | None:
    return value[:size] if value is not None else None


async def process_version(
    session: AsyncSession,
    aps: ApsClient,
    version_id: int,
    config: ProcessingConfig,
    *,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    poll_seconds: float = 5.0,
    orphan_missing: bool = False,
    actor_id: int | None = None,
) -> ProcessResult | None:
    """Processa a versão e faz commit. Devolve None se ela não existe ou não está pronta.

    `orphan_missing` (troca da regra de identificação): além da reconciliação, toda
    marca da obra com valores que ficou sem peças nesta versão vira órfã."""
    started = time.perf_counter()
    version = await session.get(ModelVersion, version_id)
    if version is None:
        log.warning("process_version(%s): versão não existe", version_id)
        return None
    if version.status not in PROCESSABLE or not version.urn:
        log.info("process_version(%s): ignorada (status %s)", version_id, version.status)
        return None
    urn = version.urn
    config = config.for_obra(await session.get(Obra, version.obra_id))

    await _set_status(session, version, VersionStatus.PROCESSING, None, "process_start")
    await session.commit()

    try:
        view = md.choose_3d_view(await md.get_metadata(aps, urn))
        tree = await md.get_object_tree(aps, urn, view.guid, sleep=sleep, poll_seconds=poll_seconds)
        props = await md.get_properties(aps, urn, view.guid, sleep=sleep, poll_seconds=poll_seconds)
        if config.piece_categories and not assemblies.is_ifc(props):
            extracted = assemblies.extract_assemblies(
                tree, props, config.mark_names, config.category_names, config.piece_categories
            )
        else:
            extracted = extract_elements(tree, props, config.mark_names, config.category_names)
        # troca de regra: fotografia peça -> marca antiga, para levar os valores
        before = await mark_rule.piece_marks(session, version.id) if orphan_missing else None
        elements, counts = await _store(session, version, extracted, config)
        report = mark_validation.build_report(
            version.id,
            elements,
            config.dimension_names,
            config.tolerance_mm,
            config.mark_names,
        )
        await mark_validation.save_report(session, version.id, report)
        # Reconciliação com a versão anterior (7.2): review, órfãs e diff, mesma transação.
        diff = await version_reconcile.apply(session, version, elements, config.reconcile)
        rule_result = None
        if orphan_missing:
            actor = await session.get(User, actor_id) if actor_id else None
            rule_result = await mark_rule.orphan_missing_marks(session, version, before, actor)
        # Unidades de peça (parâmetros por peça): ligadas aos elementos desta versão.
        actor_user = await session.get(User, actor_id) if actor_id else None
        units = await piece_units.link_version(session, version, actor_user)
        # Motor de filtros: valores das peças (modelo + sistema) e, para a obra toda,
        # fábrica + status (a reconciliação pode ter mudado o "a revisar").
        await piece_props.build_version(session, version.id)
        await piece_props.sync_factory(session, version.obra_id)
        seconds = round(time.perf_counter() - started, 3)
        totals = report["totals"]
        await _set_status(
            session,
            version,
            VersionStatus.READY,
            None,
            "process_ready",
            extra={
                **counts,
                "inconsistent_marks": totals["inconsistent_marks"],
                "diff": {**diff.totals, "review": diff.review, "orphans": diff.orphans},
                "rule_orphans": rule_result.orphans if rule_result else [],
                "rule_relinked": rule_result.relinked if rule_result else [],
                "units": units.as_dict(),
                "mark_names": config.mark_names,
                "view_guid": view.guid,
                "seconds": seconds,
            },
        )
        events.emit(
            session,
            version.obra_id,
            "version_ready",
            {
                "version_id": version.id,
                "version_number": version.version_number,
                "status": VersionStatus.READY.value,
                "elements": counts["elements"],
                "marks": counts["marks"],
                "diff": {**diff.totals, "review": diff.review, "orphans": diff.orphans},
            },
        )
        await session.commit()
    except Exception as exc:
        await session.rollback()
        await session.refresh(version)
        message = str(exc) if isinstance(exc, ApsError) else UNEXPECTED_MSG
        log.exception("process_version(%s) falhou", version_id)
        await _set_status(
            session, version, VersionStatus.FAILED, message[:MAX_ERROR], "process_failed"
        )
        events.emit(
            session,
            version.obra_id,
            "version_failed",
            {
                "version_id": version.id,
                "version_number": version.version_number,
                "status": VersionStatus.FAILED.value,
                "error": version.error,
            },
        )
        await session.commit()
        await metrics.incr("versions_processed_total", status=VersionStatus.FAILED.value)
        return ProcessResult(
            version_id,
            VersionStatus.FAILED.value,
            seconds=round(time.perf_counter() - started, 3),
            error=version.error,
        )

    log.info("process_version(%s): %s em %.2fs", version_id, counts, seconds)
    await metrics.incr("versions_processed_total", status=VersionStatus.READY.value)
    await metrics.observe("processing_seconds", seconds)
    return ProcessResult(
        version_id,
        VersionStatus.READY.value,
        elements=counts["elements"],
        without_mark=counts["without_mark"],
        marks=counts["marks"],
        marks_created=counts["marks_created"],
        seconds=seconds,
    )


async def _set_status(
    session: AsyncSession,
    version: ModelVersion,
    status: VersionStatus,
    error: str | None,
    action: str,
    extra: dict[str, Any] | None = None,
) -> None:
    before = audit.snapshot(version)
    version.status = status.value
    version.error = error
    await session.flush()
    after = audit.snapshot(version) | (extra or {})
    await audit.record(session, "model_version", version.id, action, before, after, None)


def search_text(e: ExtractedElement, level: str | None, names: list[str]) -> str:
    """Texto da busca livre: nome, categoria, marca, nível e valores de `names`."""
    parts = [e.name, e.category, e.mark_raw, e.mark_code, level]
    parts += [find_prop(e.props, [n]) for n in names]
    seen: list[str] = []
    for p in parts:
        if p and p.strip() and p.strip() not in seen:
            seen.append(p.strip())
    return " | ".join(seen)


async def _store(
    session: AsyncSession,
    version: ModelVersion,
    extracted: list[ExtractedElement],
    config: ProcessingConfig,
) -> tuple[list[ExtractedElement], dict[str, int]]:
    """Grava e devolve os elementos como ficaram no banco (sem dbid repetido; marca
    longa demais conta como sem marca) e as contagens."""
    deleted = await session.execute(delete(Element).where(Element.version_id == version.id))

    # Um dbid por versão (a árvore não deveria repetir, mas a unicidade exige).
    unique: dict[int, ExtractedElement] = {}
    for e in extracted:
        if e.mark_code and len(e.mark_code) > MAX_CODE:
            log.warning("Marca com mais de %s caracteres ignorada: dbid %s", MAX_CODE, e.dbid)
            e = replace(e, mark_code=None)
        unique.setdefault(e.dbid, e)
    elements = list(unique.values())

    keys = {(e.mark_code, e.category[:255]) for e in elements if e.mark_code}
    mark_ids, created = await _upsert_marks(session, version.obra_id, keys)

    levels: dict[int, str | None] = {}
    for e in elements:
        level = find_prop(e.props, config.level_names)
        levels[e.dbid] = level.strip() if level else None
    rows = [
        {
            "version_id": version.id,
            "dbid": e.dbid,
            "external_id": _cut(e.external_id, 255),
            "name": _cut(e.name, 512),
            "category": e.category[:255],
            "mark_raw": _cut(e.mark_raw, 255),
            "props": e.props,
            "member_dbids": list(e.member_dbids),
            "level": _cut(levels[e.dbid], 255),
            # apelidos: os outros parâmetros da regra também entram na busca
            "search_text": search_text(
                e, levels[e.dbid], [*config.search_names, *config.mark_names]
            ),
            "mark_id": mark_ids.get((e.mark_code, e.category[:255])) if e.mark_code else None,
        }
        for e in elements
    ]
    for i in range(0, len(rows), CHUNK):
        await session.execute(insert(Element), rows[i : i + CHUNK])

    # (grupo, propriedade) da versão: base do filtro "Nome=valor" com o índice GIN.
    await session.execute(
        delete(VersionPropertyName).where(VersionPropertyName.version_id == version.id)
    )
    names = sorted(
        {
            (g[:255], n[:255])
            for e in elements
            for g, content in e.props.items()
            if isinstance(content, dict)
            for n in content
        }
    )
    pn_rows = [{"version_id": version.id, "group_name": g, "prop_name": n} for g, n in names]
    for i in range(0, len(pn_rows), CHUNK):
        await session.execute(insert(VersionPropertyName), pn_rows[i : i + CHUNK])

    return elements, {
        "elements": len(rows),
        "elements_deleted": int(getattr(deleted, "rowcount", 0) or 0),
        "without_mark": sum(1 for r in rows if r["mark_id"] is None),
        "marks": len(keys),
        "marks_created": created,
    }


async def _upsert_marks(
    session: AsyncSession, obra_id: int, keys: set[tuple[str, str]]
) -> tuple[dict[tuple[str, str], int], int]:
    """Cria as marcas que faltam (ON CONFLICT DO NOTHING) e devolve {(code, cat): id}."""
    batch_id = uuid.uuid4()
    ordered = sorted(keys)  # ordem fixa: evita deadlock entre duas versões da mesma obra
    created: list[tuple[int, dict[str, Any]]] = []
    for i in range(0, len(ordered), CHUNK):
        chunk = ordered[i : i + CHUNK]
        stmt = (
            pg_insert(Mark)
            .values([{"obra_id": obra_id, "code": c, "category": cat} for c, cat in chunk])
            .on_conflict_do_nothing(constraint="uq_marks_obra_id_code_category")
            .returning(Mark.id, Mark.code, Mark.category)
        )
        for row in await session.execute(stmt):
            after = {"id": row.id, "obra_id": obra_id, "code": row.code, "category": row.category}
            created.append((row.id, after))
    if created:
        await audit.record_many(
            session, "mark", "create", [(i, None, a) for i, a in created], None, batch_id
        )

    result = await session.execute(
        select(Mark.id, Mark.code, Mark.category).where(Mark.obra_id == obra_id)
    )
    ids = {(r.code, r.category): r.id for r in result if (r.code, r.category) in keys}
    return ids, len(created)
