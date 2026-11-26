"""Edição em lote dos parâmetros da fábrica (Fase 6.3).

- Várias MARCAS da mesma obra recebem os mesmos valores. Cada parâmetro só é gravado nas
  marcas em que se aplica (escopo e categoria), mesmo que a seleção misture categorias.
- Modos: `overwrite` grava em todas (as já preenchidas com outro valor são sobrescritas);
  `only_empty` grava só nas marcas em que o campo está vazio.
- O apply grava tudo numa transação, com um `batch_id` e uma linha de auditoria por
  (marca, campo) — as mesmas ações do salvamento individual (set/update/clear), com
  `"source": "batch"`.
- Desfazer restaura o valor anterior de cada linha do lote (tudo ou nada). Recusa se o
  lote já foi desfeito ou se algum campo mudou depois dele (não apaga trabalho alheio).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from app.models import AuditLog, Mark, ParamDef, ParamValue, User
from app.models.enums import Role
from app.services import audit, events, piece_props, review
from app.services.errors import ConflictError, ForbiddenError, NotFoundError, ValidationError
from app.services.mark_values import (
    AUDIT_ENTITY,
    _filled,
    applicable_params,
    ensure_editable,
    normalize,
)

MAX_MARKS = 5000
SOURCE = "batch"


class BatchMode(StrEnum):
    OVERWRITE = "overwrite"
    ONLY_EMPTY = "only_empty"


@dataclass(frozen=True)
class FieldSummary:
    param: ParamDef
    applies_to: int  # marcas da seleção em que o parâmetro vale
    filled: int  # dessas, quantas têm valor
    mixed: bool  # valores diferentes entre as marcas (vazio conta como um valor)
    common_value: Any  # valor comum quando não é misto (None = todas vazias)


@dataclass(frozen=True)
class FieldPreview:
    def_id: int
    applies_to: int
    to_change: int  # marcas que mudam neste campo, no modo pedido
    other_value: int  # marcas com OUTRO valor já preenchido


@dataclass(frozen=True)
class BatchPreview:
    marks: int
    categories: list[str]
    fields: list[FieldSummary]
    changes: list[FieldPreview] = field(default_factory=list)
    marks_to_change: int = 0  # no modo pedido
    marks_to_change_overwrite: int = 0
    marks_to_change_only_empty: int = 0
    marks_with_other_value: int = 0


@dataclass(frozen=True)
class BatchResult:
    batch_id: uuid.UUID | None  # None = nada mudou
    marks_changed: int
    fields_changed: int


# --------------------------------------------------------------------------- leitura


@dataclass
class _Context:
    marks: list[Mark]
    params: dict[int, ParamDef]  # que valem para ao menos uma marca
    applies: dict[int, list[Mark]]  # def_id -> marcas em que vale
    values: dict[tuple[int, int], ParamValue]  # (mark_id, def_id) -> linha


async def _load(
    session: AsyncSession, obra_id: int, mark_ids: list[int], limit: int | None = MAX_MARKS
) -> _Context:
    ids = list(dict.fromkeys(mark_ids))
    if not ids:
        raise ValidationError("Selecione ao menos uma marca.")
    if limit is not None and len(ids) > limit:
        raise ValidationError(f"No máximo {MAX_MARKS} marcas por lote.")
    marks = list(
        await session.scalars(
            select(Mark).where(Mark.id.in_(ids), Mark.obra_id == obra_id).order_by(Mark.id)
        )
    )
    if len(marks) != len(ids):
        raise NotFoundError("Uma ou mais marcas não foram encontradas nesta obra.")

    params: dict[int, ParamDef] = {}
    applies: dict[int, list[Mark]] = defaultdict(list)
    by_category: dict[str, list[ParamDef]] = {}
    for mark in marks:
        if mark.category not in by_category:  # a regra só depende de obra + categoria
            by_category[mark.category] = await applicable_params(session, mark)
        for p in by_category[mark.category]:
            params.setdefault(p.id, p)
            applies[p.id].append(mark)

    values: dict[tuple[int, int], ParamValue] = {}
    if params:
        rows = await session.scalars(
            select(ParamValue).where(
                ParamValue.mark_id.in_([m.id for m in marks]),
                ParamValue.def_id.in_(list(params)),
            )
        )
        values = {(v.mark_id, v.def_id): v for v in rows}
    return _Context(marks, params, dict(applies), values)


def _current(ctx: _Context, mark: Mark, def_id: int) -> Any:
    row = ctx.values.get((mark.id, def_id))
    return row.value if row and _filled(row.value) else None


def _summaries(ctx: _Context) -> list[FieldSummary]:
    ordered = sorted(ctx.params.values(), key=lambda p: (p.name.casefold(), p.id))
    out = []
    for p in ordered:
        current = [_current(ctx, m, p.id) for m in ctx.applies[p.id]]
        distinct = {repr(v) for v in current}
        out.append(
            FieldSummary(
                param=p,
                applies_to=len(current),
                filled=sum(1 for v in current if v is not None),
                mixed=len(distinct) > 1,
                common_value=current[0] if len(distinct) == 1 else None,
            )
        )
    return out


def _normalize_changes(ctx: _Context, changes: dict[int, Any]) -> dict[int, Any]:
    out = {}
    for def_id, raw in changes.items():
        param = ctx.params.get(def_id)
        if param is None:
            raise ValidationError(
                f"O parâmetro {def_id} não existe ou não se aplica a nenhuma marca selecionada."
            )
        ensure_editable(param)
        out[def_id] = normalize(param, raw)
    return out


def _will_change(old: Any, new: Any, mode: BatchMode) -> bool:
    if old == new or (old is None and new is None):
        return False
    if mode is BatchMode.ONLY_EMPTY:
        return old is None  # só preenche vazios (apagar não faz nada neste modo)
    return True


async def preview(
    session: AsyncSession,
    obra_id: int,
    mark_ids: list[int],
    changes: dict[int, Any],
    mode: BatchMode,
) -> BatchPreview:
    """Resumo da seleção (por campo) e, se houver mudanças, o efeito de cada modo."""
    ctx = await _load(session, obra_id, mark_ids)
    normalized = _normalize_changes(ctx, changes)
    per_field = []
    touched: dict[BatchMode, set[int]] = {m: set() for m in BatchMode}
    with_other: set[int] = set()
    for def_id, new in normalized.items():
        to_change = other = 0
        for mark in ctx.applies[def_id]:
            old = _current(ctx, mark, def_id)
            for m in BatchMode:
                if _will_change(old, new, m):
                    touched[m].add(mark.id)
            if _will_change(old, new, mode):
                to_change += 1
            if old is not None and old != new:
                other += 1
                with_other.add(mark.id)
        per_field.append(FieldPreview(def_id, len(ctx.applies[def_id]), to_change, other))
    return BatchPreview(
        marks=len(ctx.marks),
        categories=sorted({m.category for m in ctx.marks}, key=str.casefold),
        fields=_summaries(ctx),
        changes=per_field,
        marks_to_change=len(touched[mode]),
        marks_to_change_overwrite=len(touched[BatchMode.OVERWRITE]),
        marks_to_change_only_empty=len(touched[BatchMode.ONLY_EMPTY]),
        marks_with_other_value=len(with_other),
    )


# --------------------------------------------------------------------------- gravação


def _action(old: Any, new: Any) -> str:
    return "set" if not _filled(old) else ("clear" if not _filled(new) else "update")


async def _flush_or_conflict(session: AsyncSession) -> None:
    try:
        await session.flush()
    except (StaleDataError, IntegrityError):
        await session.rollback()
        raise ConflictError(
            "Outro usuário alterou estas marcas agora mesmo. Recarregue e tente de novo."
        ) from None


async def apply(
    session: AsyncSession,
    obra_id: int,
    mark_ids: list[int],
    changes: dict[int, Any],
    mode: BatchMode,
    actor: User,
) -> BatchResult:
    """Grava o lote (uma transação, sem commit aqui). Auditoria com um batch_id."""
    if not changes:
        raise ValidationError("Nenhum campo alterado.")
    ctx = await _load(session, obra_id, mark_ids)
    normalized = _normalize_changes(ctx, changes)
    targets = [
        (mark, def_id, new) for def_id, new in normalized.items() for mark in ctx.applies[def_id]
    ]
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
    """Um valor por (marca, parâmetro), JÁ NORMALIZADO (importação do Excel). O mesmo
    `batch` pode ser usado com `piece_values.apply_values`: um só "Desfazer"."""
    if not values:
        return BatchResult(None, 0, 0)
    ctx = await _load(session, obra_id, list(values), limit=None)
    by_id = {m.id: m for m in ctx.marks}
    targets = []
    for mark_id, fields in values.items():
        mark = by_id[mark_id]
        for def_id, new in fields.items():
            if mark not in ctx.applies.get(def_id, []):
                raise ValidationError(f"O parâmetro {def_id} não se aplica à marca {mark.code}.")
            targets.append((mark, def_id, new))
    return await _write(session, obra_id, ctx, targets, mode, actor, source, batch)


async def _write(
    session: AsyncSession,
    obra_id: int,
    ctx: _Context,
    targets: list[tuple[Mark, int, Any]],
    mode: BatchMode,
    actor: User,
    source: str,
    batch: uuid.UUID,
) -> BatchResult:
    audits: dict[str, list[tuple[int, dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    marks_changed: set[int] = set()
    fields: dict[int, str] = {}
    for mark, def_id, new in targets:
        param = ctx.params[def_id]
        row = ctx.values.get((mark.id, def_id))
        old = _current(ctx, mark, def_id)
        if not _will_change(old, new, mode):
            continue
        if row is None:
            row = ParamValue(
                mark_id=mark.id,
                def_id=def_id,
                value=new,
                created_by=actor.id,
                updated_by=actor.id,
            )
            session.add(row)
            ctx.values[(mark.id, def_id)] = row
        else:
            row.value = new
            row.updated_by = actor.id
        base = {
            "mark_id": mark.id,
            "mark": mark.code,
            "def_id": def_id,
            "param": param.name,
            "source": source,
        }
        audits[_action(old, new)].append((mark.id, {**base, "value": old}, {**base, "value": new}))
        marks_changed.add(mark.id)
        fields[def_id] = param.name
    if not marks_changed:
        return BatchResult(None, 0, 0)
    await _flush_or_conflict(session)
    for action, rows in audits.items():
        await audit.record_many(session, AUDIT_ENTITY, action, list(rows), actor, batch)
    # Marcas em revisão que receberam valores saem da revisão (Fase 7.2).
    changed = [m for m in ctx.marks if m.id in marks_changed]
    await review.resolve_after_edit(session, changed, actor, batch)
    events.emit(
        session,
        obra_id,
        "batch_applied",
        {
            "batch_id": str(batch),
            "mode": mode.value,
            "source": source,
            "marks": len(marks_changed),
            "mark_ids": sorted(marks_changed),
            "mark_codes": sorted(m.code for m in changed),
            "fields": list(fields.values()),
        },
        actor,
    )
    await piece_props.sync_factory(session, obra_id, marks_changed)  # motor de filtros
    return BatchResult(batch, len(marks_changed), sum(len(r) for r in audits.values()))


@dataclass(frozen=True)
class UndoResult:
    batch_id: uuid.UUID  # lote do desfazer (também auditado)
    restored: int


async def has_batch(session: AsyncSession, batch_id: uuid.UUID) -> bool:
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

    keys = [(int(e.after["mark_id"]), int(e.after["def_id"])) for e in entries if e.after]
    rows = {
        (v.mark_id, v.def_id): v
        for v in await session.scalars(
            select(ParamValue).where(
                ParamValue.mark_id.in_({k[0] for k in keys}),
                ParamValue.def_id.in_({k[1] for k in keys}),
            )
        )
    }
    # Algum campo mudou depois do lote? Então não desfaz nada.
    changed_since = 0
    for e in entries:
        after = e.after or {}
        row = rows.get((int(after["mark_id"]), int(after["def_id"])))
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
        row = rows[(int(after["mark_id"]), int(after["def_id"]))]
        restored = before.get("value")
        row.value = restored
        row.updated_by = actor.id
        base = {k: after[k] for k in ("mark_id", "mark", "def_id", "param")}
        audits[_action(after.get("value"), restored)].append(
            (
                int(after["mark_id"]),
                {**base, "value": after.get("value")},
                {**base, "value": restored, "source": "undo", "undo_of": str(batch_id)},
            )
        )
    await _flush_or_conflict(session)
    for action, items in audits.items():
        await audit.record_many(session, AUDIT_ENTITY, action, list(items), actor, undo_batch)
    await _restore_reviews(session, batch_id, actor, undo_batch)
    mark_ids = sorted({int((e.after or {})["mark_id"]) for e in entries})
    obra_ids = set(await session.scalars(select(Mark.obra_id).where(Mark.id.in_(mark_ids))))
    for obra_id in obra_ids:
        await piece_props.sync_factory(session, obra_id, mark_ids)  # motor de filtros
        events.emit(
            session,
            obra_id,
            "batch_undone",
            {
                "batch_id": str(batch_id),
                "undo_batch_id": str(undo_batch),
                "restored": len(entries),
                "mark_ids": mark_ids,
                "mark_codes": sorted({str((e.after or {}).get("mark")) for e in entries}),
            },
            actor,
        )
    return UndoResult(undo_batch, len(entries))


async def _restore_reviews(
    session: AsyncSession, batch_id: uuid.UUID, actor: User, undo_batch: uuid.UUID
) -> None:
    """O lote tirou marcas de revisão (Fase 7.2)? Desfazer devolve a revisão e a nota."""
    resolved = await session.scalars(
        select(AuditLog).where(
            AuditLog.batch_id == batch_id,
            AuditLog.entity == "mark",
            AuditLog.action == "review_resolved",
        )
    )
    for entry in resolved:
        mark = await session.get(Mark, int(entry.entity_id))
        before = entry.before or {}
        if mark is None or before.get("review_status") is None:
            continue
        current = {"review_status": mark.review_status, "review_note": mark.review_note}
        mark.review_status = before["review_status"]
        mark.review_note = before.get("review_note")
        await session.flush()
        await audit.record(
            session,
            "mark",
            mark.id,
            "review_restored",
            current,
            {**before, "undo_of": str(batch_id)},
            actor,
            undo_batch,
        )
