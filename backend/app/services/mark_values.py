"""Valores dos parâmetros da fábrica por MARCA (Fase 6.2).

- Só os parâmetros ativos que se aplicam à marca (escopo global ou da obra da marca,
  categoria compatível).
- Validação/normalização por tipo: número aceita vírgula decimal; lista só aceita as
  opções (grava a forma do catálogo); data ISO (AAAA-MM-DD), completa e com ano entre
  1900 e 2100 (docs/bugs/data-por-peca.md); sim/não booleano; texto
  limpo. Vazio/nulo apaga o valor (a linha fica com value nulo, para o histórico).
- Concorrência otimista por row_version: o cliente manda a versão que leu (nula se
  não havia valor). Se outro usuário salvou antes: ConflictError 409 com quem/quando,
  e NADA é gravado.
- Cada campo alterado vira um registro de auditoria (entity "mark_value", id = marca),
  com um batch_id por salvamento. Campos sem mudança são ignorados.
"""

from __future__ import annotations

import math
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from app.models import AuditLog, Mark, ParamDef, ParamValue, User
from app.models.enums import ParamType
from app.services import audit, events, piece_props, review
from app.services.errors import ConflictError, NotFoundError, ValidationError
from app.services.param_defs import in_obra as param_in_obra

MAX_TEXT = 1000
AUDIT_ENTITY = "mark_value"
_NUMBER = re.compile(r"^[+-]?(\d+([.,]\d*)?|[.,]\d+)$")


class StaleValuesError(ConflictError):
    code = "stale"


@dataclass(frozen=True)
class FieldValue:
    param: ParamDef
    value: Any
    row_version: int | None
    updated_at: datetime | None
    updated_by_name: str | None


@dataclass(frozen=True)
class MarkValues:
    mark: Mark
    fields: list[FieldValue]
    last_change_by: str | None
    last_change_at: datetime | None


@dataclass(frozen=True)
class Change:
    def_id: int
    value: Any
    row_version: int | None  # versão lida pelo cliente (None = não havia valor)


# --------------------------------------------------------------------------- normalização


def _is_empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


DATE_MIN_YEAR = 1900
DATE_MAX_YEAR = 2100
DATE_INVALID = "Data inválida: use dd/mm/aaaa"
_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")


def valid_date(raw: Any) -> str | None:
    """'AAAA-MM-DD' completa, existente e com ano entre 1900 e 2100 → a data ISO; senão None.
    Aceita um sufixo de hora ('2026-05-05T00:00'), que é descartado."""
    m = _ISO_DATE.match(str(raw).strip())
    if not m:
        return None
    try:
        d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None
    return d.isoformat() if DATE_MIN_YEAR <= d.year <= DATE_MAX_YEAR else None


def normalize_date(raw: Any, param: ParamDef) -> str:
    """Data do parâmetro ou 422 com "Data inválida: use dd/mm/aaaa" (o campo vai no corpo)."""
    iso = valid_date(raw)
    if iso is None:
        raise ValidationError(DATE_INVALID, def_id=param.id, param=param.name, value=str(raw))
    return iso


def normalize(param: ParamDef, raw: Any) -> Any:
    """Valor pronto para gravar (JSON), ou None para apagar. Erros em português."""
    if _is_empty(raw):
        return None
    name = param.name
    ptype = ParamType(param.type)
    if ptype is ParamType.TEXT:
        text = " ".join(str(raw).split()) if isinstance(raw, str) else str(raw)
        if len(text) > MAX_TEXT:
            raise ValidationError(f"{name}: no máximo {MAX_TEXT} caracteres.")
        return text
    if ptype is ParamType.NUMBER:
        if isinstance(raw, bool):
            raise ValidationError(f"{name}: informe um número.")
        if isinstance(raw, int | float):
            number = float(raw)
        else:
            text = str(raw).strip().replace(" ", "")
            if not _NUMBER.match(text):
                raise ValidationError(
                    f'{name}: "{raw}" não é um número (use vírgula para decimais).'
                )
            number = float(text.replace(",", "."))
        if not math.isfinite(number):
            raise ValidationError(f"{name}: informe um número.")
        return int(number) if number.is_integer() else number
    if ptype is ParamType.LIST:
        wanted = str(raw).strip().casefold()
        for option in param.options or []:
            if str(option).casefold() == wanted:
                return option
        raise ValidationError(
            f'{name}: "{raw}" não é uma das opções ({", ".join(param.options or [])}).'
        )
    if ptype is ParamType.DATE:
        return normalize_date(raw, param)
    # BOOL
    if isinstance(raw, bool):
        return raw
    text = str(raw).strip().casefold()
    if text in ("true", "sim", "s", "1"):
        return True
    if text in ("false", "não", "nao", "n", "0"):
        return False
    raise ValidationError(f"{name}: use sim ou não.")


def _filled(value: Any) -> bool:
    return not _is_empty(value)


# --------------------------------------------------------------------------- consultas


async def get_mark(session: AsyncSession, obra_id: int, mark_id: int) -> Mark:
    mark = await session.get(Mark, mark_id)
    if mark is None or mark.obra_id != obra_id:
        raise NotFoundError("Marca não encontrada nesta obra.")
    return mark


async def applicable_params(session: AsyncSession, mark: Mark) -> list[ParamDef]:
    params = await session.scalars(
        select(ParamDef)
        .where(
            ParamDef.active.is_(True),
            param_in_obra(mark.obra_id),
        )
        .order_by(func.lower(ParamDef.name), ParamDef.id)
    )
    return [p for p in params if not p.categories or mark.category in p.categories]


async def _user_names(session: AsyncSession, ids: set[int]) -> dict[int, str]:
    if not ids:
        return {}
    rows = await session.execute(select(User.id, User.name).where(User.id.in_(ids)))
    return {uid: name for uid, name in rows}


async def get_values(session: AsyncSession, obra_id: int, mark_id: int) -> MarkValues:
    mark = await get_mark(session, obra_id, mark_id)
    params = await applicable_params(session, mark)
    rows = {
        v.def_id: v
        for v in await session.scalars(
            select(ParamValue).where(
                ParamValue.mark_id == mark.id, ParamValue.def_id.in_([p.id for p in params])
            )
        )
    }
    names = await _user_names(session, {v.updated_by for v in rows.values() if v.updated_by})
    fields = []
    for p in params:
        v = rows.get(p.id)
        fields.append(
            FieldValue(
                param=p,
                value=v.value if v else None,
                row_version=v.row_version if v else None,
                updated_at=v.updated_at if v else None,
                updated_by_name=names.get(v.updated_by) if v and v.updated_by else None,
            )
        )
    last = max(
        (f for f in fields if f.updated_at),
        key=lambda f: f.updated_at or datetime.min,
        default=None,
    )
    return MarkValues(
        mark=mark,
        fields=fields,
        last_change_by=last.updated_by_name if last else None,
        last_change_at=last.updated_at if last else None,
    )


# --------------------------------------------------------------------------- gravação


async def _stale(
    session: AsyncSession, mark: Mark, conflicts: list[ParamValue]
) -> StaleValuesError:
    newest = max(conflicts, key=lambda v: v.updated_at)
    names = await _user_names(session, {newest.updated_by} if newest.updated_by else set())
    who = names.get(newest.updated_by or 0, "Outro usuário")
    return StaleValuesError(
        f"{who} alterou esta marca enquanto você editava. Recarregue para ver os valores atuais.",
        changed_by_name=who,
        changed_at=newest.updated_at,
        conflict_def_ids=sorted(v.def_id for v in conflicts),
    )


async def save_values(
    session: AsyncSession, obra_id: int, mark_id: int, changes: list[Change], actor: User
) -> int:
    """Grava as mudanças (tudo ou nada). Devolve quantos campos mudaram. Não faz commit."""
    mark = await get_mark(session, obra_id, mark_id)
    params = {p.id: p for p in await applicable_params(session, mark)}
    if len({c.def_id for c in changes}) != len(changes):
        raise ValidationError("O mesmo parâmetro foi enviado mais de uma vez.")
    for c in changes:
        if c.def_id not in params:
            raise ValidationError(
                f"O parâmetro {c.def_id} não existe ou não se aplica a esta marca "
                f"({mark.category})."
            )
    normalized = {c.def_id: normalize(params[c.def_id], c.value) for c in changes}

    existing = {
        v.def_id: v
        for v in await session.scalars(
            select(ParamValue).where(
                ParamValue.mark_id == mark.id, ParamValue.def_id.in_(list(normalized))
            )
        )
    }
    # Concorrência: a versão lida pelo cliente precisa ser a atual.
    conflicts = []
    for c in changes:
        row = existing.get(c.def_id)
        if row is None:
            continue
        if c.row_version is None or c.row_version != row.row_version:
            conflicts.append(row)
    if conflicts:
        raise await _stale(session, mark, conflicts)

    batch = uuid.uuid4()
    entries: list[tuple[ParamDef, Any, Any]] = []
    for c in changes:
        param, new = params[c.def_id], normalized[c.def_id]
        row = existing.get(c.def_id)
        old = row.value if row else None
        if old == new or (not _filled(old) and not _filled(new)):
            continue  # sem mudança: nada a gravar
        if row is None:
            session.add(
                ParamValue(
                    mark_id=mark.id,
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
        await session.flush()  # UPDATE ... WHERE row_version = <lido>
    except (StaleDataError, IntegrityError):
        await session.rollback()
        raise StaleValuesError(
            "Outro usuário alterou esta marca agora mesmo. Recarregue para ver os valores atuais.",
            changed_by_name=None,
            changed_at=None,
            conflict_def_ids=[],
        ) from None

    for param, old, new in entries:
        base = {"mark_id": mark.id, "mark": mark.code, "def_id": param.id, "param": param.name}
        action = "set" if not _filled(old) else ("clear" if not _filled(new) else "update")
        await audit.record(
            session,
            AUDIT_ENTITY,
            mark.id,
            action,
            {**base, "value": old},
            {**base, "value": new},
            actor,
            batch,
        )
    # Editar uma marca em revisão (Fase 7.2) resolve a revisão.
    await review.resolve_after_edit(session, [mark], actor, batch)
    await piece_props.sync_factory(session, mark.obra_id, [mark.id])  # motor de filtros
    events.emit(
        session,
        mark.obra_id,
        "values_changed",
        {
            "mark_id": mark.id,
            "mark": mark.code,
            "category": mark.category,
            "fields": [param.name for param, _, _ in entries],
            "changes": [
                {"def_id": param.id, "param": param.name, "before": old, "after": new}
                for param, old, new in entries
            ],
            "batch_id": str(batch),
        },
        actor,
    )
    return len(entries)


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
    session: AsyncSession, obra_id: int, mark_id: int, limit: int = 200
) -> list[HistoryEntry]:
    mark = await get_mark(session, obra_id, mark_id)
    rows = await session.execute(
        select(AuditLog, User.name)
        .outerjoin(User, User.id == AuditLog.user_id)
        .where(and_(AuditLog.entity == AUDIT_ENTITY, AuditLog.entity_id == str(mark.id)))
        .order_by(AuditLog.at.desc(), AuditLog.id.desc())
        .limit(limit)
    )
    out = []
    for entry, user_name in rows:
        after = entry.after or {}
        before = entry.before or {}
        out.append(
            HistoryEntry(
                at=entry.at,
                user_name=user_name,
                action=entry.action,
                param=str(after.get("param") or before.get("param") or ""),
                def_id=after.get("def_id"),
                before=before.get("value"),
                after=after.get("value"),
                batch_id=entry.batch_id,
            )
        )
    return out
