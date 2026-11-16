"""Regra de identificação das peças, por obra.

Cada obra diz quais parâmetros do modelo dão a MARCA (e, opcionalmente, a categoria),
em ordem de prioridade: ex. ["Nome da montagem", "Marca"] numa obra detalhada pela
equipe (montagens) ou ["PILAR_ID"] num modelo de terceiros. Sem regra própria vale o
padrão do servidor (MARK_PROPERTY_NAMES / CATEGORY_PROPERTY_NAMES).

Trocar a regra muda os códigos das marcas. Por isso a versão ativa é reprocessada
com `orphan_missing=True`: toda marca da obra que tem valores e ficou sem peças vira
órfã, mesmo quando a obra só tem uma versão (nunca apagar dados em silêncio).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import Element, Mark, ModelVersion, Obra, Orphan, User
from app.models.enums import OrphanStatus, VersionStatus
from app.services import audit, review
from app.services.errors import ValidationError
from app.services.obras import get_obra
from app.services.translation import PROCESS_VERSION_JOB
from app.services.version_reconcile import marks_with_values
from app.workers.queue import JobQueue

log = logging.getLogger("app.services.mark_rule")

MAX_NAMES = 10
MAX_NAME_LENGTH = 255


@dataclass(frozen=True)
class MarkRule:
    mark_names: list[str]
    category_names: list[str]
    custom_marks: bool  # False = padrão do servidor
    custom_categories: bool
    # montagens (.nwd/.rvt com vínculos): categorias do corpo; None = modo desligado
    piece_categories: list[str] | None = None


def clean_names(names: list[str] | None, label: str) -> list[str] | None:
    """Tira espaços, vazios e repetidos (sem diferenciar maiúsculas), mantendo a ordem.
    None = voltar ao padrão do servidor."""
    if names is None:
        return None
    out: list[str] = []
    seen: set[str] = set()
    for raw in names:
        name = raw.strip()
        if not name or name.casefold() in seen:
            continue
        if len(name) > MAX_NAME_LENGTH:
            raise ValidationError(f"Nome de parâmetro longo demais em {label}: {name[:40]}…")
        seen.add(name.casefold())
        out.append(name)
    if not out:
        raise ValidationError(f"Informe pelo menos um parâmetro em {label}.")
    if len(out) > MAX_NAMES:
        raise ValidationError(f"No máximo {MAX_NAMES} parâmetros em {label}.")
    return out


def effective_rule(obra: Obra, settings: Settings) -> MarkRule:
    return MarkRule(
        mark_names=obra.mark_property_names or settings.mark_property_list,
        category_names=obra.category_property_names or settings.category_property_list,
        custom_marks=bool(obra.mark_property_names),
        custom_categories=bool(obra.category_property_names),
        piece_categories=obra.piece_category_names or None,
    )


@dataclass(frozen=True)
class RuleUpdate:
    obra: Obra
    changed: bool


async def update_rule(
    session: AsyncSession,
    obra_id: int,
    mark_names: list[str] | None,
    category_names: list[str] | None,
    actor: User,
    piece_categories: list[str] | None = None,
) -> RuleUpdate:
    """Grava a regra (com auditoria). Sem commit."""
    obra = await get_obra(session, obra_id)
    marks = clean_names(mark_names, "parâmetros da marca")
    categories = clean_names(category_names, "parâmetros da categoria")
    pieces = clean_names(piece_categories, "categorias do corpo da peça")
    before = {
        "mark_property_names": obra.mark_property_names,
        "category_property_names": obra.category_property_names,
        "piece_category_names": obra.piece_category_names,
    }
    after = {
        "mark_property_names": marks,
        "category_property_names": categories,
        "piece_category_names": pieces,
    }
    if before == after:
        return RuleUpdate(obra, changed=False)
    obra.mark_property_names = marks
    obra.category_property_names = categories
    obra.piece_category_names = pieces
    obra.updated_by = actor.id
    await session.flush()
    await audit.record(session, "obra", obra.id, "mark_rule", before, after, actor)
    return RuleUpdate(obra, changed=True)


async def latest_ready_version(session: AsyncSession, obra_id: int) -> ModelVersion | None:
    version: ModelVersion | None = await session.scalar(
        select(ModelVersion)
        .where(
            ModelVersion.obra_id == obra_id,
            ModelVersion.status == VersionStatus.READY.value,
        )
        .order_by(ModelVersion.version_number.desc())
        .limit(1)
    )
    return version


async def piece_marks(session: AsyncSession, version_id: int) -> dict[str, int]:
    """externalId da peça -> marca, na versão (fotografia antes de reprocessar)."""
    rows = await session.execute(
        select(Element.external_id, Element.mark_id).where(
            Element.version_id == version_id,
            Element.external_id.is_not(None),
            Element.mark_id.is_not(None),
        )
    )
    return {str(ext): mark_id for ext, mark_id in rows if mark_id is not None}


@dataclass(frozen=True)
class RuleOrphans:
    """Resultado da troca de regra para as marcas antigas com valores."""

    relinked: list[dict[str, object]]  # valores levados para a marca nova
    orphans: list[dict[str, object]]  # ficaram órfãs (sem destino único ou com conflito)


def _single_target(old_pieces: list[str], new_map: dict[str, int]) -> int | None:
    """A marca nova, se TODAS as peças da antiga foram para UMA marca só."""
    targets = {new_map.get(ext) for ext in old_pieces}
    if len(targets) != 1:
        return None
    return next(iter(targets))


async def _why_not(session: AsyncSession, source: Mark, target: Mark | None) -> str | None:
    """Por que NÃO levar os valores automaticamente (None = pode levar)."""
    if target is None:
        return "as peças foram para mais de uma marca, ou ficaram sem marca"
    target_open = await session.scalar(
        select(Orphan.id).where(
            Orphan.mark_id == target.id, Orphan.status == OrphanStatus.OPEN.value
        )
    )
    if target_open is not None:
        return f"a marca {target.code} também está órfã"
    plan = await review.plan_relink(session, source, target)
    if plan.conflicts:
        names = ", ".join(str(c["name"]) for c in plan.conflicts)
        return f"a marca {target.code} já tem outro valor em: {names}"
    if plan.skipped:
        return f"parâmetros que não se aplicam a {target.code}: {', '.join(plan.skipped)}"
    return None


async def orphan_missing_marks(
    session: AsyncSession,
    version: ModelVersion,
    before: dict[str, int] | None = None,
    actor: User | None = None,
) -> RuleOrphans:
    """Marcas da obra COM valores que não têm peças em `version`. Sem commit.

    Migração assistida: com a fotografia `before` (externalId -> marca antiga, tirada
    antes de reprocessar), se TODAS as peças de uma marca antiga foram para UMA marca
    nova, os valores vão juntos (religação automática, auditada com
    `source: mark_rule`), desde que o destino não tenha outro valor no mesmo parâmetro
    e todos os parâmetros se apliquem a ele. O resto vira órfã aberta (decisão manual).
    Ignora marcas que já têm órfã aberta ou arquivada (decisão já tomada)."""
    present = select(Element.mark_id).where(
        Element.version_id == version.id, Element.mark_id.is_not(None)
    )
    decided = exists(
        select(Orphan.id).where(
            Orphan.mark_id == Mark.id,
            Orphan.status.in_([OrphanStatus.OPEN.value, OrphanStatus.ARCHIVED.value]),
        )
    )
    missing = list(
        await session.scalars(
            select(Mark)
            .where(Mark.obra_id == version.obra_id, Mark.id.not_in(present), ~decided)
            .order_by(Mark.code, Mark.category)
        )
    )
    filled = await marks_with_values(session, [m.id for m in missing])
    new_map = await piece_marks(session, version.id) if before else {}
    old_pieces: dict[int, list[str]] = {}
    for ext, mark_id in (before or {}).items():
        old_pieces.setdefault(mark_id, []).append(ext)

    batch = uuid.uuid4()
    relinked: list[dict[str, object]] = []
    orphaned: list[dict[str, object]] = []
    for mark in missing:
        if mark.id not in filled:
            continue
        orphan = Orphan(
            mark_id=mark.id,
            since_version_id=version.id,
            status=OrphanStatus.OPEN.value,
            created_by=actor.id if actor else None,
            updated_by=actor.id if actor else None,
        )
        session.add(orphan)
        await session.flush()
        await audit.record(
            session,
            "orphan",
            orphan.id,
            "create",
            None,
            {
                "mark_id": mark.id,
                "mark": mark.code,
                "since_version_id": version.id,
                "reason": "mark_rule",
            },
            actor,
            batch,
        )
        entry: dict[str, object] = {"mark_id": mark.id, "mark": mark.code}
        pieces = old_pieces.get(mark.id, [])
        target_id = _single_target(pieces, new_map) if pieces else None
        target = await session.get(Mark, target_id) if target_id else None
        reason = await _why_not(session, mark, target)
        if target is not None and reason is None:
            result = await review.relink(
                session,
                orphan.id,
                target.id,
                overwrite=False,
                actor=actor,
                source_tag="mark_rule",
            )
            relinked.append({**entry, "target": target.code, "copied": result.copied})
        else:
            orphaned.append({**entry, "reason": reason})
    return RuleOrphans(relinked, orphaned)


async def enqueue_reprocess(queue: JobQueue, version_id: int, actor_id: int | None = None) -> bool:
    """Reprocessa a versão com a regra nova (id de job novo: o anterior pode estar
    guardado no Redis). Falha ao enfileirar não desfaz a regra: devolve False."""
    try:
        await queue.enqueue(
            PROCESS_VERSION_JOB,
            version_id,
            True,  # orphan_missing
            actor_id,  # quem trocou a regra (autoria da migração dos valores)
            job_id=f"{PROCESS_VERSION_JOB}:{version_id}:rule:{uuid.uuid4().hex}",
        )
        return True
    except Exception:
        log.exception("Falha ao enfileirar o reprocessamento da versão %s", version_id)
        return False
