"""Fila de unidades de peça órfãs (P5), nos moldes das marcas órfãs (Fase 7.2).

Uma unidade com valores por peça que fica sem peça numa versão nova vira ÓRFÃ
(`piece_units.link_version`). A fábrica pode:

- **Religar** a outra peça da MESMA marca na versão ativa: a unidade órfã passa a ser a
  daquela peça (fica com a chave dela, então segue ligada nas versões seguintes) e
  recupera os valores dela, que nunca saíram da unidade. A unidade que estava na peça
  sai: sem valores, fica `unlinked`; com valores, vira órfã (só com confirmação). Nada é
  apagado.
- **Arquivar**: a unidade sai da fila e não é mais ligada pela ordem a outra peça; os
  valores continuam guardados e ela volta sozinha se a chave dela reaparecer.

Tudo vai para o audit_log (entidade `piece_unit`) e gera o evento `unit_orphan_changed`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Element,
    Mark,
    ModelVersion,
    ParamDef,
    PieceUnit,
    PieceUnitLink,
    PieceValue,
    User,
)
from app.models.enums import LinkMethod, ParamLevel, UnitStatus, VersionStatus
from app.services import audit, events, piece_props
from app.services.errors import ConflictError, NotFoundError, ValidationError
from app.services.param_defs import has_value
from app.services.piece_units import units_with_values
from app.services.piece_values import get_unit, unit_label

AUDIT_ENTITY = "piece_unit"


class UnitRelinkConflictError(ConflictError):
    code = "unit_relink_conflict"


@dataclass(frozen=True)
class UnitOrphanValue:
    def_id: int
    name: str
    type: str
    value: Any


@dataclass(frozen=True)
class UnitOrphanInfo:
    id: int
    number: int
    label: str
    status: str
    mark_id: int
    code: str
    category: str
    external_id: str | None
    since_version_id: int | None
    since_version_number: int | None
    mark_in_model: bool  # a marca tem peças na versão ativa (dá para religar)
    updated_at: datetime
    values: list[UnitOrphanValue] = field(default_factory=list)


async def _latest(session: AsyncSession, obra_id: int) -> ModelVersion | None:
    return await session.scalar(
        select(ModelVersion)
        .where(ModelVersion.obra_id == obra_id, ModelVersion.status == VersionStatus.READY.value)
        .order_by(ModelVersion.version_number.desc())
        .limit(1)
    )


async def _values_of(
    session: AsyncSession, unit_ids: list[int]
) -> dict[int, list[UnitOrphanValue]]:
    out: dict[int, list[UnitOrphanValue]] = {u: [] for u in unit_ids}
    if not unit_ids:
        return out
    rows = await session.execute(
        select(PieceValue.unit_id, ParamDef.id, ParamDef.name, ParamDef.type, PieceValue.value)
        .join(ParamDef, ParamDef.id == PieceValue.def_id)
        .where(
            PieceValue.unit_id.in_(unit_ids),
            ParamDef.active.is_(True),
            ParamDef.level == ParamLevel.PIECE.value,
            has_value(PieceValue.value),
        )
        .order_by(func.lower(ParamDef.name), ParamDef.id)
    )
    for unit_id, def_id, name, ptype, value in rows:
        out[unit_id].append(UnitOrphanValue(def_id, name, ptype, value))
    return out


async def list_orphans(
    session: AsyncSession, obra_id: int, statuses: tuple[UnitStatus, ...] = (UnitStatus.ORPHAN,)
) -> list[UnitOrphanInfo]:
    """Unidades órfãs da obra (padrão: só as abertas), por marca e número."""
    latest = await _latest(session, obra_id)
    rows = list(
        await session.execute(
            select(PieceUnit, Mark, ModelVersion.version_number)
            .join(Mark, Mark.id == PieceUnit.mark_id)
            .outerjoin(ModelVersion, ModelVersion.id == PieceUnit.since_version_id)
            .where(
                PieceUnit.obra_id == obra_id,
                PieceUnit.status.in_([s.value for s in statuses]),
            )
            .order_by(Mark.code, Mark.category, PieceUnit.number)
        )
    )
    in_model: set[int] = set()
    if latest is not None and rows:
        in_model = set(
            await session.scalars(
                select(func.distinct(Element.mark_id)).where(
                    Element.version_id == latest.id,
                    Element.mark_id.in_({m.id for _, m, _ in rows}),
                )
            )
        )
    values = await _values_of(session, [u.id for u, _, _ in rows])
    return [
        UnitOrphanInfo(
            id=u.id,
            number=u.number,
            label=unit_label(m, u),
            status=u.status,
            mark_id=m.id,
            code=m.code,
            category=m.category,
            external_id=u.external_id,
            since_version_id=u.since_version_id,
            since_version_number=number,
            mark_in_model=m.id in in_model,
            updated_at=u.updated_at,
            values=values[u.id],
        )
        for u, m, number in rows
    ]


async def count_open(session: AsyncSession, obra_id: int) -> int:
    n = await session.scalar(
        select(func.count(PieceUnit.id)).where(
            PieceUnit.obra_id == obra_id, PieceUnit.status == UnitStatus.ORPHAN.value
        )
    )
    return n or 0


async def _open_orphan(session: AsyncSession, obra_id: int, unit_id: int) -> tuple[PieceUnit, Mark]:
    unit, mark = await get_unit(session, obra_id, unit_id)
    if unit.status != UnitStatus.ORPHAN.value:
        raise ConflictError(
            f"{unit_label(mark, unit)} não está órfã (já foi religada, arquivada ou voltou)."
        )
    return unit, mark


@dataclass(frozen=True)
class UnitRelinkResult:
    unit_id: int
    label: str
    element_id: int
    dbid: int
    displaced_unit_id: int
    displaced_label: str
    displaced_status: str  # unlinked | orphan


async def relink(
    session: AsyncSession,
    obra_id: int,
    unit_id: int,
    target_unit_id: int,
    confirm: bool,
    actor: User,
) -> UnitRelinkResult:
    """Religa a unidade órfã à peça (na versão ativa) da unidade `target_unit_id`, da mesma
    marca. Sem commit. A unidade de destino tem valores → 409 `unit_relink_conflict`, a
    menos que `confirm=True` (ela vira órfã; nada é apagado)."""
    unit, mark = await _open_orphan(session, obra_id, unit_id)
    target, target_mark = await get_unit(session, obra_id, target_unit_id)
    if target.mark_id != mark.id:
        raise ValidationError(
            f"Escolha uma peça da marca {mark.code}: "
            f"{unit_label(target_mark, target)} é de outra marca."
        )
    if target.id == unit.id:  # pragma: no cover - a órfã não tem peça
        raise ValidationError("Escolha outra peça.")
    latest = await _latest(session, obra_id)
    link = (
        await session.scalar(
            select(PieceUnitLink).where(
                PieceUnitLink.version_id == latest.id, PieceUnitLink.unit_id == target.id
            )
        )
        if latest is not None
        else None
    )
    if latest is None or link is None:
        raise ValidationError(
            f"{unit_label(mark, target)} não tem peça na versão ativa do modelo; escolha outra."
        )
    element = await session.get(Element, link.element_id)
    if element is None:  # pragma: no cover - FK
        raise NotFoundError("Peça não encontrada.")

    target_values = await units_with_values(session, [target.id])
    if target_values and not confirm:
        raise UnitRelinkConflictError(
            f"{unit_label(mark, target)} já tem valores. Se continuar, ela fica órfã "
            "(os valores dela continuam guardados).",
            target_label=unit_label(mark, target),
        )

    # A peça passa da unidade de destino para a órfã (só na versão ativa; as anteriores
    # guardam a ligação que tinham).
    before_unit = {"status": unit.status, "external_id": unit.external_id}
    before_target = {"status": target.status, "external_id": target.external_id}
    await session.delete(link)
    await session.flush()
    session.add(
        PieceUnitLink(
            version_id=latest.id,
            unit_id=unit.id,
            element_id=element.id,
            method=LinkMethod.MANUAL.value,
        )
    )
    unit.status = UnitStatus.LINKED.value
    unit.external_id = element.external_id
    unit.since_version_id = None
    unit.updated_by = actor.id
    displaced = UnitStatus.ORPHAN if target_values else UnitStatus.UNLINKED
    target.status = displaced.value
    target.external_id = None  # a chave agora é da unidade religada
    target.since_version_id = latest.id
    target.updated_by = actor.id
    await session.flush()

    label, target_label = unit_label(mark, unit), unit_label(mark, target)
    await audit.record(
        session,
        AUDIT_ENTITY,
        unit.id,
        "relink",
        before_unit,
        {
            "status": unit.status,
            "external_id": unit.external_id,
            "version_id": latest.id,
            "element_id": element.id,
            "from_unit": target_label,
        },
        actor,
    )
    await audit.record(
        session,
        AUDIT_ENTITY,
        target.id,
        "displaced",
        before_target,
        {"status": target.status, "external_id": None, "version_id": latest.id, "by_unit": label},
        actor,
    )
    await piece_props.sync_factory(session, obra_id, [mark.id])  # filtros, cores, status
    events.emit(
        session,
        obra_id,
        "unit_orphan_changed",
        {
            "unit_id": unit.id,
            "unit": label,
            "mark": mark.code,
            "status": "relinked",
            "target_unit": target_label,
        },
        actor,
    )
    return UnitRelinkResult(
        unit.id, label, element.id, element.dbid, target.id, target_label, target.status
    )


async def archive(
    session: AsyncSession, obra_id: int, unit_id: int, actor: User
) -> tuple[PieceUnit, str]:
    """Tira a unidade da fila sem religar. Os valores continuam guardados. Sem commit.
    Devolve a unidade e o rótulo (PP001-3)."""
    unit, mark = await _open_orphan(session, obra_id, unit_id)
    unit.status = UnitStatus.ARCHIVED.value
    unit.updated_by = actor.id
    await session.flush()
    label = unit_label(mark, unit)
    await audit.record(
        session,
        AUDIT_ENTITY,
        unit.id,
        "archive",
        {"status": UnitStatus.ORPHAN.value, "external_id": unit.external_id},
        {"status": unit.status, "external_id": unit.external_id, "unit": label},
        actor,
    )
    events.emit(
        session,
        obra_id,
        "unit_orphan_changed",
        {"unit_id": unit.id, "unit": label, "mark": mark.code, "status": "archived"},
        actor,
    )
    return unit, label
