"""Valores dos parâmetros POR PEÇA (P2, docs/pecas).

Mesmas regras dos valores por marca (`mark_values`), aplicadas à UNIDADE DE PEÇA:
- só os parâmetros por peça ativos que valem na obra e na categoria da marca da unidade;
- validação e normalização por tipo (`mark_values.normalize`); vazio apaga;
- concorrência otimista por row_version (409 `stale` com quem e quando);
- auditoria campo a campo (entity "piece_value", id = unidade), com um batch_id;
- lote em várias unidades (de marcas diferentes também), "só nas vazias" ou
  "sobrescrever", e desfazer (tudo ou nada; recusa se algo mudou depois);
- evento SSE para as outras abas.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from app.models import (
    AuditLog,
    Element,
    Mark,
    ModelVersion,
    ParamDef,
    PieceUnit,
    PieceUnitLink,
    PieceValue,
    User,
)
from app.models.enums import ParamLevel, Role, VersionStatus
from app.services import audit, events, piece_props, unit_sequence
from app.services.errors import ConflictError, ForbiddenError, NotFoundError, ValidationError
from app.services.mark_batch import BatchMode
from app.services.mark_values import StaleValuesError, _filled, ensure_editable, normalize
from app.services.param_defs import in_obra
from app.services.version_data import VersionNotReadyError

AUDIT_ENTITY = "piece_value"
MAX_UNITS = 5000
SOURCE = "batch"


def unit_label(mark: Mark, unit: PieceUnit) -> str:
    """Rótulo da unidade: PP001-3."""
    return f"{mark.code}-{unit.number}"


# --------------------------------------------------------------------------- leitura


async def piece_params(session: AsyncSession, obra_id: int, category: str) -> list[ParamDef]:
    """Parâmetros POR PEÇA ativos que valem na obra e nesta categoria."""
    params = await session.scalars(
        select(ParamDef)
        .where(ParamDef.active.is_(True), in_obra(obra_id, level=ParamLevel.PIECE.value))
        .order_by(func.lower(ParamDef.name), ParamDef.id)
    )
    return [p for p in params if not p.categories or category in p.categories]


async def _get_mark(session: AsyncSession, obra_id: int, mark_id: int) -> Mark:
    mark = await session.get(Mark, mark_id)
    if mark is None or mark.obra_id != obra_id:
        raise NotFoundError("Marca não encontrada nesta obra.")
    return mark


async def get_unit(session: AsyncSession, obra_id: int, unit_id: int) -> tuple[PieceUnit, Mark]:
    unit = await session.get(PieceUnit, unit_id)
    if unit is None or unit.obra_id != obra_id:
        raise NotFoundError("Peça não encontrada nesta obra.")
    mark = await session.get(Mark, unit.mark_id)
    if mark is None:  # pragma: no cover - FK
        raise NotFoundError("Marca não encontrada.")
    return unit, mark


async def _version(
    session: AsyncSession, obra_id: int, version_id: int | None
) -> ModelVersion | None:
    """A versão aberta (padrão: a pronta mais recente da obra)."""
    if version_id is None:
        return await session.scalar(
            select(ModelVersion)
            .where(
                ModelVersion.obra_id == obra_id, ModelVersion.status == VersionStatus.READY.value
            )
            .order_by(ModelVersion.version_number.desc())
            .limit(1)
        )
    v = await session.get(ModelVersion, version_id)
    if v is None or v.obra_id != obra_id:
        raise NotFoundError("Versão não encontrada nesta obra.")
    if v.status != VersionStatus.READY.value:
        raise VersionNotReadyError("A versão ainda não está pronta.")
    return v


@dataclass(frozen=True)
class MarkUnit:
    unit_id: int
    label: str  # PP001-3
    mark_id: int


async def units_of_marks(
    session: AsyncSession, obra_id: int, version_id: int | None, mark_ids: list[int]
) -> list[MarkUnit]:
    """Peças (unidades) das marcas ligadas a um elemento da versão aberta, para o lote por
    peça com várias marcas selecionadas (2026-11-18). Órfãs e sem peça ficam de fora."""
    if len(set(mark_ids)) > MAX_UNITS:
        raise ValidationError(f"No máximo {MAX_UNITS} marcas.")
    version = await _version(session, obra_id, version_id)
    if version is None or not mark_ids:
        return []
    found = set(
        await session.scalars(
            select(Mark.id).where(Mark.id.in_(set(mark_ids)), Mark.obra_id == obra_id)
        )
    )
    if found != set(mark_ids):
        raise NotFoundError("Marca não encontrada nesta obra.")
    rows = await session.execute(
        select(PieceUnit.id, PieceUnit.number, Mark.id, Mark.code)
        .join(Mark, Mark.id == PieceUnit.mark_id)
        .join(PieceUnitLink, PieceUnitLink.unit_id == PieceUnit.id)
        .where(PieceUnitLink.version_id == version.id, Mark.id.in_(found))
        .order_by(Mark.code, Mark.category, PieceUnit.number)
    )
    return [MarkUnit(uid, f"{code}-{number}", mid) for uid, number, mid, code in rows]


async def _user_names(session: AsyncSession, ids: set[int]) -> dict[int, str]:
    if not ids:
        return {}
    rows = await session.execute(select(User.id, User.name).where(User.id.in_(ids)))
    return {uid: name for uid, name in rows}


@dataclass(frozen=True)
class UnitField:
    def_id: int
    value: Any
    row_version: int | None
    updated_at: datetime | None
    updated_by_name: str | None


@dataclass(frozen=True)
class LinkedElement:
    element_id: int
    dbid: int
    external_id: str | None
    level: str | None
    name: str | None
    method: str  # key | order ("conferir") | new


@dataclass(frozen=True)
class UnitRow:
    unit: PieceUnit
    label: str
    element: LinkedElement | None  # na versão aberta (None = sem peça nela)
    values: list[UnitField]


@dataclass(frozen=True)
class MarkUnits:
    mark: Mark
    version: ModelVersion | None
    params: list[ParamDef]
    units: list[UnitRow]


async def _fields(
    session: AsyncSession, unit_ids: list[int], params: list[ParamDef]
) -> dict[int, list[UnitField]]:
    rows: dict[tuple[int, int], PieceValue] = {}
    if unit_ids and params:
        for found in await session.scalars(
            select(PieceValue).where(
                PieceValue.unit_id.in_(unit_ids), PieceValue.def_id.in_([p.id for p in params])
            )
        ):
            rows[(found.unit_id, found.def_id)] = found
    names = await _user_names(session, {v.updated_by for v in rows.values() if v.updated_by})
    out: dict[int, list[UnitField]] = {}
    for uid in unit_ids:
        fields = []
        for p in params:
            v = rows.get((uid, p.id))
            fields.append(
                UnitField(
                    def_id=p.id,
                    value=v.value if v else None,
                    row_version=v.row_version if v else None,
                    updated_at=v.updated_at if v else None,
                    updated_by_name=names.get(v.updated_by) if v and v.updated_by else None,
                )
            )
        out[uid] = fields
    return out


async def _links(
    session: AsyncSession, version: ModelVersion | None, unit_ids: list[int]
) -> dict[int, LinkedElement]:
    if version is None or not unit_ids:
        return {}
    rows = await session.execute(
        select(
            PieceUnitLink.unit_id,
            Element.id,
            Element.dbid,
            Element.external_id,
            Element.level,
            Element.name,
            PieceUnitLink.method,
        )
        .join(Element, Element.id == PieceUnitLink.element_id)
        .where(PieceUnitLink.version_id == version.id, PieceUnitLink.unit_id.in_(unit_ids))
    )
    return {
        uid: LinkedElement(eid, dbid, ext, lvl, name, m)
        for uid, eid, dbid, ext, lvl, name, m in rows
    }


async def list_units(
    session: AsyncSession, obra_id: int, mark_id: int, version_id: int | None = None
) -> MarkUnits:
    """Unidades da marca (todas, inclusive órfãs e sem peça), com os valores por peça e o
    elemento ligado na versão aberta."""
    mark = await _get_mark(session, obra_id, mark_id)
    version = await _version(session, obra_id, version_id)
    params = await piece_params(session, obra_id, mark.category)
    units = list(
        await session.scalars(
            select(PieceUnit).where(PieceUnit.mark_id == mark.id).order_by(PieceUnit.number)
        )
    )
    ids = [u.id for u in units]
    fields = await _fields(session, ids, params)
    links = await _links(session, version, ids)
    rows = [UnitRow(u, unit_label(mark, u), links.get(u.id), fields[u.id]) for u in units]
    return MarkUnits(mark, version, params, rows)


async def unit_detail(
    session: AsyncSession, obra_id: int, unit_id: int, version_id: int | None = None
) -> tuple[Mark, list[ParamDef], UnitRow]:
    unit, mark = await get_unit(session, obra_id, unit_id)
    version = await _version(session, obra_id, version_id)
    params = await piece_params(session, obra_id, mark.category)
    fields = await _fields(session, [unit.id], params)
    links = await _links(session, version, [unit.id])
    return mark, params, UnitRow(unit, unit_label(mark, unit), links.get(unit.id), fields[unit.id])


# --------------------------------------------------------------------------- gravação


@dataclass(frozen=True)
class Change:
    def_id: int
    value: Any
    row_version: int | None  # versão lida (None = não havia valor)


def _action(old: Any, new: Any) -> str:
    return "set" if not _filled(old) else ("clear" if not _filled(new) else "update")


def _base(unit: PieceUnit, mark: Mark, param: ParamDef) -> dict[str, Any]:
    return {
        "unit_id": unit.id,
        "unit": unit_label(mark, unit),
        "mark_id": mark.id,
        "mark": mark.code,
        "def_id": param.id,
        "param": param.name,
    }


async def save_values(
    session: AsyncSession, obra_id: int, unit_id: int, changes: list[Change], actor: User
) -> int:
    """Grava as mudanças de UMA unidade (tudo ou nada). Devolve quantos campos mudaram."""
    unit, mark = await get_unit(session, obra_id, unit_id)
    params = {p.id: p for p in await piece_params(session, obra_id, mark.category)}
    if len({c.def_id for c in changes}) != len(changes):
        raise ValidationError("O mesmo parâmetro foi enviado mais de uma vez.")
    for c in changes:
        if c.def_id not in params:
            raise ValidationError(
                f"O parâmetro {c.def_id} não é por peça ou não se aplica a esta peça "
                f"({mark.category})."
            )
    for c in changes:
        ensure_editable(params[c.def_id])
    normalized = {c.def_id: normalize(params[c.def_id], c.value) for c in changes}
    existing = {
        v.def_id: v
        for v in await session.scalars(
            select(PieceValue).where(
                PieceValue.unit_id == unit.id, PieceValue.def_id.in_(list(normalized))
            )
        )
    }
    conflicts = [
        row
        for c in changes
        if (row := existing.get(c.def_id)) is not None
        and (c.row_version is None or c.row_version != row.row_version)
    ]
    if conflicts:
        newest = max(conflicts, key=lambda v: v.updated_at)
        names = await _user_names(session, {newest.updated_by} if newest.updated_by else set())
        who = names.get(newest.updated_by or 0, "Outro usuário")
        raise StaleValuesError(
            f"{who} alterou a peça {unit_label(mark, unit)} enquanto você editava. "
            "Recarregue para ver os valores atuais.",
            changed_by_name=who,
            changed_at=newest.updated_at,
            conflict_def_ids=sorted(v.def_id for v in conflicts),
        )

    entries: list[tuple[ParamDef, Any, Any]] = []
    for c in changes:
        param, new = params[c.def_id], normalized[c.def_id]
        row = existing.get(c.def_id)
        old = row.value if row else None
        if old == new or (not _filled(old) and not _filled(new)):
            continue
        if row is None:
            session.add(
                PieceValue(
                    unit_id=unit.id,
                    def_id=param.id,
                    value=new,
                    created_by=actor.id,
                    updated_by=actor.id,
                )
            )
        else:
            row.value = new
            row.updated_by = actor.id
        entries.append((param, old, new))
    if not entries:
        return 0
    try:
        await session.flush()
    except (StaleDataError, IntegrityError):
        await session.rollback()
        raise StaleValuesError(
            "Outro usuário alterou esta peça agora mesmo. Recarregue para ver os valores atuais.",
            changed_by_name=None,
            changed_at=None,
            conflict_def_ids=[],
        ) from None

    await unit_sequence.lock_numbering(session, obra_id, actor)  # 1º valor: números fixos
    batch = uuid.uuid4()
    for param, old, new in entries:
        base = _base(unit, mark, param)
        await audit.record(
            session,
            AUDIT_ENTITY,
            unit.id,
            _action(old, new),
            {**base, "value": old},
            {**base, "value": new},
            actor,
            batch,
        )
    await piece_props.sync_factory(session, obra_id, [mark.id])  # filtros, cores, status
    events.emit(
        session,
        obra_id,
        "unit_values_changed",
        {
            "unit_id": unit.id,
            "unit": unit_label(mark, unit),
            "mark_id": mark.id,
            "mark": mark.code,
            "category": mark.category,
            "fields": [p.name for p, _, _ in entries],
            "changes": [
                {"def_id": p.id, "param": p.name, "before": o, "after": n} for p, o, n in entries
            ],
            "batch_id": str(batch),
        },
        actor,
    )
    return len(entries)


# --------------------------------------------------------------------------- lote


@dataclass
class _Ctx:
    units: list[PieceUnit]
    marks: dict[int, Mark]
    params: dict[int, ParamDef]  # que valem para ao menos uma unidade
    applies: dict[int, list[PieceUnit]]  # def_id -> unidades em que vale
    values: dict[tuple[int, int], PieceValue]  # (unit_id, def_id) -> linha


async def _load(
    session: AsyncSession, obra_id: int, unit_ids: list[int], limit: int | None = MAX_UNITS
) -> _Ctx:
    ids = list(dict.fromkeys(unit_ids))
    if not ids:
        raise ValidationError("Selecione ao menos uma peça.")
    if limit is not None and len(ids) > limit:
        raise ValidationError(f"No máximo {MAX_UNITS} peças por lote.")
    units = list(
        await session.scalars(
            select(PieceUnit)
            .where(PieceUnit.id.in_(ids), PieceUnit.obra_id == obra_id)
            .order_by(PieceUnit.mark_id, PieceUnit.number)
        )
    )
    if len(units) != len(ids):
        raise NotFoundError("Uma ou mais peças não foram encontradas nesta obra.")
    marks = {
        m.id: m
        for m in await session.scalars(select(Mark).where(Mark.id.in_({u.mark_id for u in units})))
    }
    params: dict[int, ParamDef] = {}
    applies: dict[int, list[PieceUnit]] = defaultdict(list)
    by_category: dict[str, list[ParamDef]] = {}
    for u in units:
        category = marks[u.mark_id].category
        if category not in by_category:
            by_category[category] = await piece_params(session, obra_id, category)
        for p in by_category[category]:
            params.setdefault(p.id, p)
            applies[p.id].append(u)
    values: dict[tuple[int, int], PieceValue] = {}
    if params:
        for v in await session.scalars(
            select(PieceValue).where(
                PieceValue.unit_id.in_([u.id for u in units]),
                PieceValue.def_id.in_(list(params)),
            )
        ):
            values[(v.unit_id, v.def_id)] = v
    return _Ctx(units, marks, params, dict(applies), values)


def _current(ctx: _Ctx, unit: PieceUnit, def_id: int) -> Any:
    row = ctx.values.get((unit.id, def_id))
    return row.value if row and _filled(row.value) else None


def _normalize(ctx: _Ctx, changes: dict[int, Any]) -> dict[int, Any]:
    out = {}
    for def_id, raw in changes.items():
        param = ctx.params.get(def_id)
        if param is None:
            raise ValidationError(
                f"O parâmetro {def_id} não é por peça ou não se aplica a nenhuma peça selecionada."
            )
        ensure_editable(param)
        out[def_id] = normalize(param, raw)
    return out


def _will_change(old: Any, new: Any, mode: BatchMode) -> bool:
    if old == new or (old is None and new is None):
        return False
    if mode is BatchMode.ONLY_EMPTY:
        return old is None
    return True


@dataclass(frozen=True)
class FieldSummary:
    param: ParamDef
    applies_to: int
    filled: int
    mixed: bool
    common_value: Any


@dataclass(frozen=True)
class FieldPreview:
    def_id: int
    applies_to: int
    to_change: int
    other_value: int


@dataclass(frozen=True)
class BatchPreview:
    units: int
    marks: int
    categories: list[str]
    fields: list[FieldSummary]
    changes: list[FieldPreview] = field(default_factory=list)
    units_to_change: int = 0
    units_to_change_overwrite: int = 0
    units_to_change_only_empty: int = 0
    units_with_other_value: int = 0


async def preview(
    session: AsyncSession,
    obra_id: int,
    unit_ids: list[int],
    changes: dict[int, Any],
    mode: BatchMode,
) -> BatchPreview:
    ctx = await _load(session, obra_id, unit_ids)
    normalized = _normalize(ctx, changes)
    summaries = []
    for p in sorted(ctx.params.values(), key=lambda p: (p.name.casefold(), p.id)):
        current = [_current(ctx, u, p.id) for u in ctx.applies[p.id]]
        distinct = {repr(v) for v in current}
        summaries.append(
            FieldSummary(
                p,
                len(current),
                sum(1 for v in current if v is not None),
                len(distinct) > 1,
                current[0] if len(distinct) == 1 else None,
            )
        )
    per_field = []
    touched: dict[BatchMode, set[int]] = {m: set() for m in BatchMode}
    with_other: set[int] = set()
    for def_id, new in normalized.items():
        to_change = other = 0
        for u in ctx.applies[def_id]:
            old = _current(ctx, u, def_id)
            for m in BatchMode:
                if _will_change(old, new, m):
                    touched[m].add(u.id)
            if _will_change(old, new, mode):
                to_change += 1
            if old is not None and old != new:
                other += 1
                with_other.add(u.id)
        per_field.append(FieldPreview(def_id, len(ctx.applies[def_id]), to_change, other))
    return BatchPreview(
        units=len(ctx.units),
        marks=len(ctx.marks),
        categories=sorted({m.category for m in ctx.marks.values()}, key=str.casefold),
        fields=summaries,
        changes=per_field,
        units_to_change=len(touched[mode]),
        units_to_change_overwrite=len(touched[BatchMode.OVERWRITE]),
        units_to_change_only_empty=len(touched[BatchMode.ONLY_EMPTY]),
        units_with_other_value=len(with_other),
    )


@dataclass(frozen=True)
class BatchResult:
    batch_id: uuid.UUID | None  # None = nada mudou
    units_changed: int
    fields_changed: int


async def _flush_or_conflict(session: AsyncSession) -> None:
    try:
        await session.flush()
    except (StaleDataError, IntegrityError):
        await session.rollback()
        raise ConflictError(
            "Outro usuário alterou estas peças agora mesmo. Recarregue e tente de novo."
        ) from None


async def apply(
    session: AsyncSession,
    obra_id: int,
    unit_ids: list[int],
    changes: dict[int, Any],
    mode: BatchMode,
    actor: User,
) -> BatchResult:
    """Grava o lote numa transação (sem commit aqui), com um batch_id na auditoria."""
    if not changes:
        raise ValidationError("Nenhum campo alterado.")
    ctx = await _load(session, obra_id, unit_ids)
    normalized = _normalize(ctx, changes)
    targets = [(u, def_id, new) for def_id, new in normalized.items() for u in ctx.applies[def_id]]
    return await _write(session, obra_id, ctx, targets, mode, actor, SOURCE, uuid.uuid4())


async def apply_values(
    session: AsyncSession,
    obra_id: int,
    values: dict[int, dict[int, Any]],
    mode: BatchMode,
    actor: User,
    *,
    source: str,
    batch: uuid.UUID,
) -> BatchResult:
    """Um valor por (unidade, parâmetro), JÁ NORMALIZADO (importação do Excel). O mesmo
    `batch` pode ser usado com `mark_batch.apply_values`: um só "Desfazer"."""
    if not values:
        return BatchResult(None, 0, 0)
    ctx = await _load(session, obra_id, list(values), limit=None)
    by_id = {u.id: u for u in ctx.units}
    targets = []
    for unit_id, fields in values.items():
        unit = by_id[unit_id]
        for def_id, new in fields.items():
            if unit not in ctx.applies.get(def_id, []):
                label = unit_label(ctx.marks[unit.mark_id], unit)
                raise ValidationError(f"O parâmetro {def_id} não se aplica à peça {label}.")
            targets.append((unit, def_id, new))
    return await _write(session, obra_id, ctx, targets, mode, actor, source, batch)


async def _write(
    session: AsyncSession,
    obra_id: int,
    ctx: _Ctx,
    targets: list[tuple[PieceUnit, int, Any]],
    mode: BatchMode,
    actor: User,
    source: str,
    batch: uuid.UUID,
) -> BatchResult:
    audits: dict[str, list[tuple[int, dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    changed: set[int] = set()
    fields: dict[int, str] = {}
    for u, def_id, new in targets:
        param = ctx.params[def_id]
        row = ctx.values.get((u.id, def_id))
        old = _current(ctx, u, def_id)
        if not _will_change(old, new, mode):
            continue
        if row is None:
            row = PieceValue(
                unit_id=u.id,
                def_id=def_id,
                value=new,
                created_by=actor.id,
                updated_by=actor.id,
            )
            session.add(row)
            ctx.values[(u.id, def_id)] = row
        else:
            row.value = new
            row.updated_by = actor.id
        base = {**_base(u, ctx.marks[u.mark_id], param), "source": source}
        audits[_action(old, new)].append((u.id, {**base, "value": old}, {**base, "value": new}))
        changed.add(u.id)
        fields[def_id] = param.name
    if not changed:
        return BatchResult(None, 0, 0)
    await _flush_or_conflict(session)
    await unit_sequence.lock_numbering(session, obra_id, actor)  # 1º valor: números fixos
    for action, rows in audits.items():
        await audit.record_many(session, AUDIT_ENTITY, action, list(rows), actor, batch)
    touched = [u for u in ctx.units if u.id in changed]
    await piece_props.sync_factory(session, obra_id, {u.mark_id for u in touched})
    events.emit(
        session,
        obra_id,
        "unit_batch_applied",
        {
            "batch_id": str(batch),
            "mode": mode.value,
            "source": source,
            "units": len(changed),
            "unit_ids": sorted(changed),
            "mark_ids": sorted({u.mark_id for u in touched}),
            "fields": list(fields.values()),
        },
        actor,
    )
    return BatchResult(batch, len(changed), sum(len(r) for r in audits.values()))


@dataclass(frozen=True)
class UndoResult:
    batch_id: uuid.UUID
    restored: int


async def is_piece_batch(session: AsyncSession, batch_id: uuid.UUID) -> bool:
    found = await session.scalar(
        select(AuditLog.id)
        .where(AuditLog.batch_id == batch_id, AuditLog.entity == AUDIT_ENTITY)
        .limit(1)
    )
    return found is not None


async def undo(session: AsyncSession, batch_id: uuid.UUID, actor: User) -> UndoResult:
    """Restaura os valores anteriores do lote (tudo ou nada). Sem commit aqui."""
    entries = list(
        await session.scalars(
            select(AuditLog)
            .where(AuditLog.batch_id == batch_id, AuditLog.entity == AUDIT_ENTITY)
            .order_by(AuditLog.id)
        )
    )
    if not entries:
        raise NotFoundError("Lote não encontrado.")
    if any((e.after or {}).get("undo_of") for e in entries):
        raise ValidationError("Este lote já é um desfazer; não pode ser desfeito.")
    if actor.role != Role.ADMIN.value and any(e.user_id != actor.id for e in entries):
        raise ForbiddenError("Só quem aplicou o lote (ou um admin) pode desfazê-lo.")
    already = await session.scalar(
        select(AuditLog.id)
        .where(
            AuditLog.entity == AUDIT_ENTITY,
            AuditLog.after["undo_of"].astext == str(batch_id),
        )
        .limit(1)
    )
    if already is not None:
        raise ConflictError("Este lote já foi desfeito.")

    keys = [(int(e.after["unit_id"]), int(e.after["def_id"])) for e in entries if e.after]
    rows = {
        (v.unit_id, v.def_id): v
        for v in await session.scalars(
            select(PieceValue).where(
                PieceValue.unit_id.in_({k[0] for k in keys}),
                PieceValue.def_id.in_({k[1] for k in keys}),
            )
        )
    }
    changed_since = 0
    for e in entries:
        after = e.after or {}
        row = rows.get((int(after["unit_id"]), int(after["def_id"])))
        current = row.value if row and _filled(row.value) else None
        if current != after.get("value"):
            changed_since += 1
    if changed_since:
        raise ConflictError(
            f"{changed_since} campo(s) foram alterados depois deste lote. "
            "Desfazer agora apagaria essas alterações; ajuste-os manualmente.",
            changed_since=changed_since,
        )

    undo_batch = uuid.uuid4()
    audits: dict[str, list[tuple[int, dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    for e in entries:
        after = e.after or {}
        before = e.before or {}
        row = rows[(int(after["unit_id"]), int(after["def_id"]))]
        restored = before.get("value")
        row.value = restored
        row.updated_by = actor.id
        base = {k: after[k] for k in ("unit_id", "unit", "mark_id", "mark", "def_id", "param")}
        audits[_action(after.get("value"), restored)].append(
            (
                int(after["unit_id"]),
                {**base, "value": after.get("value")},
                {**base, "value": restored, "source": "undo", "undo_of": str(batch_id)},
            )
        )
    await _flush_or_conflict(session)
    for action, items in audits.items():
        await audit.record_many(session, AUDIT_ENTITY, action, list(items), actor, undo_batch)
    unit_ids = sorted({int((e.after or {})["unit_id"]) for e in entries})
    obra_ids = set(
        await session.scalars(select(PieceUnit.obra_id).where(PieceUnit.id.in_(unit_ids)))
    )
    mark_ids = set(
        await session.scalars(select(PieceUnit.mark_id).where(PieceUnit.id.in_(unit_ids)))
    )
    for obra_id in obra_ids:
        await piece_props.sync_factory(session, obra_id, mark_ids)
        events.emit(
            session,
            obra_id,
            "unit_batch_undone",
            {
                "batch_id": str(batch_id),
                "undo_batch_id": str(undo_batch),
                "restored": len(entries),
                "unit_ids": unit_ids,
            },
            actor,
        )
    return UndoResult(undo_batch, len(entries))


# --------------------------------------------------------------------------- histórico


@dataclass(frozen=True)
class HistoryEntry:
    at: datetime
    user_name: str | None
    action: str
    param: str
    def_id: int | None
    before: Any
    after: Any
    batch_id: uuid.UUID | None


async def history(
    session: AsyncSession, obra_id: int, unit_id: int, limit: int = 200
) -> list[HistoryEntry]:
    """Alterações dos valores por peça e das ligações da unidade (mais recentes primeiro)."""
    unit, _ = await get_unit(session, obra_id, unit_id)
    rows = await session.execute(
        select(AuditLog, User.name)
        .outerjoin(User, User.id == AuditLog.user_id)
        .where(
            and_(
                AuditLog.entity.in_([AUDIT_ENTITY, "piece_unit"]),
                AuditLog.entity_id == str(unit.id),
            )
        )
        .order_by(AuditLog.at.desc(), AuditLog.id.desc())
        .limit(limit)
    )
    out = []
    for entry, user_name in rows:
        after = entry.after or {}
        before = entry.before or {}
        if entry.entity == "piece_unit":  # ligação: o "valor" é a chave do elemento
            out.append(
                HistoryEntry(
                    entry.at,
                    user_name,
                    entry.action,
                    "Peça do modelo",
                    None,
                    before.get("external_id"),
                    after.get("external_id") or after.get("status"),
                    entry.batch_id,
                )
            )
            continue
        out.append(
            HistoryEntry(
                entry.at,
                user_name,
                entry.action,
                str(after.get("param") or before.get("param") or ""),
                after.get("def_id"),
                before.get("value"),
                after.get("value"),
                entry.batch_id,
            )
        )
    return out
