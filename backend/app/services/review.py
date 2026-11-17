"""Revisão de marcas e fila de órfãs (Fase 7.2).

- Diff da versão (gravado pelo process_version) + contagens atuais (a revisar, órfãs).
- "Manter valores": a marca sai de review (valores continuam valendo), auditado.
- Editar e salvar valores de uma marca em review também resolve a revisão.
- Órfãs: listar; RELIGAR copia os valores para a marca de destino (auditado, a órfã
  fecha como relinked); ARQUIVAR fecha sem copiar. Em nenhum caso os valores somem:
  continuam na marca antiga (param_values) e na auditoria.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Element,
    Mark,
    ModelVersion,
    Orphan,
    ParamDef,
    ParamValue,
    PieceUnit,
    User,
    VersionDiff,
)
from app.models.enums import OrphanStatus, ParamScope, ReviewStatus, UnitStatus
from app.services import audit, events, param_defs, piece_props
from app.services.errors import ConflictError, NotFoundError, ValidationError
from app.services.param_defs import has_value

AUDIT_ENTITY = "mark_value"  # o mesmo de mark_values (valores copiados no religar)


class DiffNotReadyError(NotFoundError):
    code = "diff_not_ready"


class RelinkConflictError(ConflictError):
    code = "relink_conflict"


# --------------------------------------------------------------------------- diff


@dataclass(frozen=True)
class DiffView:
    version_id: int
    version_number: int
    diff: dict[str, Any]
    review_open: int  # marcas desta versão ainda em revisão (agora)
    orphans_open: int  # órfãs abertas da obra (agora)
    unit_orphans_open: int = 0  # unidades de peça órfãs abertas da obra (agora, P5)


async def get_diff(session: AsyncSession, version_id: int) -> DiffView:
    version = await session.get(ModelVersion, version_id)
    if version is None:
        raise NotFoundError("Versão não encontrada.")
    row = await session.scalar(select(VersionDiff).where(VersionDiff.version_id == version_id))
    if row is None:
        raise DiffNotReadyError(
            "A comparação com a versão anterior ainda não foi gerada "
            "(ela sai quando o processamento termina)."
        )
    review_open = await session.scalar(
        select(func.count(func.distinct(Mark.id)))
        .join(Element, Element.mark_id == Mark.id)
        .where(Element.version_id == version_id, Mark.review_status == ReviewStatus.REVIEW.value)
    )
    orphans_open = await session.scalar(
        select(func.count(Orphan.id))
        .join(Mark, Mark.id == Orphan.mark_id)
        .where(Mark.obra_id == version.obra_id, Orphan.status == OrphanStatus.OPEN.value)
    )
    unit_orphans_open = await session.scalar(
        select(func.count(PieceUnit.id)).where(
            PieceUnit.obra_id == version.obra_id, PieceUnit.status == UnitStatus.ORPHAN.value
        )
    )
    return DiffView(
        version.id,
        version.version_number,
        row.diff,
        review_open or 0,
        orphans_open or 0,
        unit_orphans_open or 0,
    )


# --------------------------------------------------------------------------- revisão


async def _mark(session: AsyncSession, mark_id: int) -> Mark:
    mark = await session.get(Mark, mark_id)
    if mark is None:
        raise NotFoundError("Marca não encontrada.")
    return mark


async def keep_values(session: AsyncSession, mark_id: int, actor: User) -> Mark:
    """ "Manter valores": a marca deixa de estar em revisão. Sem commit."""
    mark = await _mark(session, mark_id)
    if mark.review_status != ReviewStatus.REVIEW.value:
        raise ConflictError("Esta marca não está em revisão.")
    await _clear(session, mark, actor, "review_keep", None)
    await piece_props.sync_factory(session, mark.obra_id, [mark.id])  # motor de filtros
    events.emit(
        session,
        mark.obra_id,
        "values_changed",
        {
            "mark_id": mark.id,
            "mark": mark.code,
            "category": mark.category,
            "fields": [],
            "review": "kept",
        },
        actor,
    )
    return mark


async def resolve_after_edit(
    session: AsyncSession, marks: list[Mark], actor: User, batch_id: uuid.UUID | None
) -> int:
    """Salvar valores numa marca em revisão resolve a revisão (auditado)."""
    n = 0
    for mark in marks:
        if mark.review_status == ReviewStatus.REVIEW.value:
            await _clear(session, mark, actor, "review_resolved", batch_id)
            n += 1
    return n


async def _clear(
    session: AsyncSession, mark: Mark, actor: User, action: str, batch_id: uuid.UUID | None
) -> None:
    before = {"review_status": mark.review_status, "review_note": mark.review_note}
    mark.review_status = ReviewStatus.OK.value
    mark.review_note = None
    mark.updated_by = actor.id
    await session.flush()
    after = {"review_status": mark.review_status, "review_note": None, "code": mark.code}
    await audit.record(session, "mark", mark.id, action, before, after, actor, batch_id)


# --------------------------------------------------------------------------- órfãs


@dataclass(frozen=True)
class OrphanValue:
    def_id: int
    name: str
    type: str
    value: Any


@dataclass(frozen=True)
class OrphanInfo:
    id: int
    status: str
    mark_id: int
    code: str
    category: str
    since_version_id: int
    since_version_number: int
    relinked_to: int | None
    relinked_to_code: str | None
    created_at: datetime
    updated_at: datetime
    values: list[OrphanValue] = field(default_factory=list)


async def _values_of(session: AsyncSession, mark_ids: list[int]) -> dict[int, list[OrphanValue]]:
    out: dict[int, list[OrphanValue]] = {m: [] for m in mark_ids}
    if not mark_ids:
        return out
    rows = await session.execute(
        select(ParamValue.mark_id, ParamDef.id, ParamDef.name, ParamDef.type, ParamValue.value)
        .join(ParamDef, ParamDef.id == ParamValue.def_id)
        .where(
            ParamValue.mark_id.in_(mark_ids),
            ParamDef.active.is_(True),
            has_value(ParamValue.value),
        )
        .order_by(func.lower(ParamDef.name), ParamDef.id)
    )
    for mark_id, def_id, name, ptype, value in rows:
        out[mark_id].append(OrphanValue(def_id, name, ptype, value))
    return out


async def list_orphans(
    session: AsyncSession, obra_id: int, status: OrphanStatus | None = OrphanStatus.OPEN
) -> list[OrphanInfo]:
    target = Mark.__table__.alias("target")
    query = (
        select(Orphan, Mark, ModelVersion.version_number, target.c.code)
        .join(Mark, Mark.id == Orphan.mark_id)
        .join(ModelVersion, ModelVersion.id == Orphan.since_version_id)
        .outerjoin(target, target.c.id == Orphan.relinked_to)
        .where(Mark.obra_id == obra_id)
        .order_by(Mark.code, Mark.category, Orphan.id)
    )
    if status is not None:
        query = query.where(Orphan.status == status.value)
    rows = list(await session.execute(query))
    values = await _values_of(session, [mark.id for _, mark, _, _ in rows])
    return [
        OrphanInfo(
            id=o.id,
            status=o.status,
            mark_id=mark.id,
            code=mark.code,
            category=mark.category,
            since_version_id=o.since_version_id,
            since_version_number=number,
            relinked_to=o.relinked_to,
            relinked_to_code=target_code,
            created_at=o.created_at,
            updated_at=o.updated_at,
            values=values[mark.id],
        )
        for o, mark, number, target_code in rows
    ]


async def _open_orphan(session: AsyncSession, orphan_id: int) -> tuple[Orphan, Mark]:
    orphan = await session.get(Orphan, orphan_id)
    if orphan is None:
        raise NotFoundError("Órfã não encontrada.")
    if orphan.status != OrphanStatus.OPEN.value:
        raise ConflictError("Esta órfã já foi resolvida (religada, arquivada ou a marca voltou).")
    return orphan, await _mark(session, orphan.mark_id)


@dataclass(frozen=True)
class RelinkResult:
    orphan_id: int
    target_mark_id: int
    copied: list[str]  # nomes dos parâmetros copiados
    skipped: list[str]  # não se aplicam à categoria do destino (ficam na marca antiga)
    batch_id: uuid.UUID


def _applies(param: ParamDef, mark: Mark, included: set[int]) -> bool:
    """Vale para a marca: é da obra dela ou da biblioteca incluído nela, e a categoria
    bate."""
    if param.scope == ParamScope.GLOBAL.value:
        scope_ok = param.id in included
    else:
        scope_ok = param.obra_id == mark.obra_id
    return scope_ok and (not param.categories or mark.category in param.categories)


@dataclass
class RelinkPlan:
    """O que religar `source` → `target` faria (sem gravar nada)."""

    copy: list[tuple[ParamValue, ParamDef, ParamValue | None]]
    skipped: list[str]  # não se aplicam à categoria/obra do destino
    conflicts: list[dict[str, Any]]  # destino já tem OUTRO valor


async def plan_relink(session: AsyncSession, source: Mark, target: Mark) -> RelinkPlan:
    rows = list(
        await session.execute(
            select(ParamValue, ParamDef)
            .join(ParamDef, ParamDef.id == ParamValue.def_id)
            .where(
                ParamValue.mark_id == source.id,
                ParamDef.active.is_(True),
                has_value(ParamValue.value),
            )
            .order_by(func.lower(ParamDef.name))
        )
    )
    existing = {
        v.def_id: v
        for v in await session.scalars(
            select(ParamValue).where(
                ParamValue.mark_id == target.id,
                ParamValue.def_id.in_([p.id for _, p in rows]),
            )
        )
    }
    included = await param_defs.included_ids(session, target.obra_id)
    copy, skipped, conflicts = [], [], []
    for value, param in rows:
        if not _applies(param, target, included):
            skipped.append(param.name)
            continue
        current = existing.get(param.id)
        filled = current is not None and current.value not in (None, "")
        if filled and current is not None and current.value != value.value:
            conflicts.append(
                {
                    "def_id": param.id,
                    "name": param.name,
                    "orphan_value": value.value,
                    "target_value": current.value,
                }
            )
        copy.append((value, param, current))
    return RelinkPlan(copy, skipped, conflicts)


async def relink(
    session: AsyncSession,
    orphan_id: int,
    target_mark_id: int,
    overwrite: bool,
    actor: User | None,
    source_tag: str = "relink",
) -> RelinkResult:
    """Copia os valores da marca órfã para a marca de destino e fecha a órfã. Sem commit.

    Destino com OUTRO valor no mesmo parâmetro → 409 relink_conflict (com a lista), a
    menos que overwrite=True. Os valores continuam também na marca antiga.
    `actor=None` = ação do sistema; `source_tag` vai para a auditoria dos valores
    ("relink" manual; "mark_rule" na migração automática da troca de regra)."""
    orphan, source = await _open_orphan(session, orphan_id)
    target = await session.get(Mark, target_mark_id)
    if target is None or target.obra_id != source.obra_id:
        raise NotFoundError("Marca de destino não encontrada nesta obra.")
    if target.id == source.id:
        raise ValidationError("Escolha outra marca: a de destino é a própria marca órfã.")
    target_orphan = await session.scalar(
        select(Orphan.id).where(
            Orphan.mark_id == target.id, Orphan.status == OrphanStatus.OPEN.value
        )
    )
    if target_orphan is not None:
        raise ValidationError(
            f"A marca {target.code} também está órfã; escolha uma marca do modelo."
        )

    plan = await plan_relink(session, source, target)
    copy, skipped, conflicts = plan.copy, plan.skipped, plan.conflicts
    if conflicts and not overwrite:
        raise RelinkConflictError(
            f"A marca {target.code} já tem outro valor em: "
            + ", ".join(c["name"] for c in conflicts)
            + ". Confirme para sobrescrever.",
            conflicts=conflicts,
        )

    actor_id = actor.id if actor else None
    batch = uuid.uuid4()
    copied = []
    for value, param, current in copy:
        old = current.value if current is not None else None
        if old == value.value:
            continue
        if current is None:
            session.add(
                ParamValue(
                    mark_id=target.id,
                    def_id=param.id,
                    value=value.value,
                    created_by=actor_id,
                    updated_by=actor_id,
                )
            )
        else:
            current.value = value.value
            current.updated_by = actor_id
        base = {
            "mark_id": target.id,
            "mark": target.code,
            "def_id": param.id,
            "param": param.name,
            "source": source_tag,
            "from_mark": source.code,
            "orphan_id": orphan.id,
        }
        action = "set" if old in (None, "") else "update"
        await audit.record(
            session,
            AUDIT_ENTITY,
            target.id,
            action,
            {**base, "value": old},
            {**base, "value": value.value},
            actor,
            batch,
        )
        copied.append(param.name)
    await session.flush()

    await piece_props.sync_factory(session, target.obra_id, [target.id])  # motor de filtros
    orphan.status = OrphanStatus.RELINKED.value
    orphan.relinked_to = target.id
    orphan.updated_by = actor_id
    await session.flush()
    await audit.record(
        session,
        "orphan",
        orphan.id,
        "relink",
        {"status": OrphanStatus.OPEN.value, "mark": source.code},
        {
            "status": orphan.status,
            "mark": source.code,
            "relinked_to": target.id,
            "target": target.code,
            "copied": copied,
            "skipped": skipped,
        },
        actor,
        batch,
    )
    events.emit(
        session,
        target.obra_id,
        "orphan_changed",
        {
            "orphan_id": orphan.id,
            "mark": source.code,
            "status": orphan.status,
            "target_mark_id": target.id,
            "target": target.code,
        },
        actor,
    )
    if copied:
        events.emit(
            session,
            target.obra_id,
            "values_changed",
            {
                "mark_id": target.id,
                "mark": target.code,
                "category": target.category,
                "fields": copied,
                "source": source_tag,
                "from_mark": source.code,
            },
            actor,
        )
    return RelinkResult(orphan.id, target.id, copied, skipped, batch)


async def archive(session: AsyncSession, orphan_id: int, actor: User) -> Orphan:
    """Fecha a órfã sem copiar nada. Os valores continuam na marca antiga. Sem commit."""
    orphan, mark = await _open_orphan(session, orphan_id)
    orphan.status = OrphanStatus.ARCHIVED.value
    orphan.updated_by = actor.id
    await session.flush()
    await audit.record(
        session,
        "orphan",
        orphan.id,
        "archive",
        {"status": OrphanStatus.OPEN.value, "mark": mark.code},
        {"status": orphan.status, "mark": mark.code},
        actor,
    )
    events.emit(
        session,
        mark.obra_id,
        "orphan_changed",
        {"orphan_id": orphan.id, "mark": mark.code, "status": orphan.status},
        actor,
    )
    return orphan
