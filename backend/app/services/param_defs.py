"""Catálogo de parâmetros da fábrica (Fase 6.1).

Regras:
- nome único sem diferenciar maiúsculas entre os parâmetros ATIVOS: um global não pode
  ter o nome de nenhum outro ativo; um da obra não pode repetir um global nem outro da
  mesma obra (obras diferentes podem repetir entre si);
- tipo text|number|list|date|bool; unidade só para number; opções só para list (mínimo
  2, sem repetidas); categorias: lista vazia/nula = todas;
- o tipo (e o escopo/obra) não muda se já existem valores; opções em uso não saem;
- excluir é lógico (active=false): os valores ficam no banco e a auditoria da exclusão
  guarda a lista deles.
Toda escrita passa por audit.record. Não faz commit (a rota faz).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import and_, cast, exists, func, literal, literal_column, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Mark, Obra, ObraParam, ParamDef, ParamValue, User
from app.models.enums import ParamScope, ParamType
from app.services import audit, events
from app.services.errors import ConflictError, NotFoundError, ValidationError

MAX_NAME = 200
MAX_UNIT = 30
MAX_OPTION = 200
MAX_OPTIONS = 200


class _Unset:
    pass


UNSET: Any = _Unset()


@dataclass
class ParamDefInput:
    """Campos de criação/edição. Na edição, UNSET = não alterar."""

    name: Any = UNSET
    type: Any = UNSET
    unit: Any = UNSET
    options: Any = UNSET
    required: Any = UNSET
    categories: Any = UNSET
    scope: Any = UNSET
    obra_id: Any = UNSET
    # criar um parâmetro da biblioteca de dentro de uma obra já o inclui nela
    include_in_obra_id: Any = UNSET


@dataclass(frozen=True)
class ParamDefInfo:
    param: ParamDef
    values_count: int
    created_by_name: str | None
    obra_code: str | None = None
    options_in_use: list[str] = field(default_factory=list)
    in_obra: bool | None = None  # listado para uma obra: vale nela?
    obras_count: int = 0  # obras em que o parâmetro da biblioteca está incluído


# --------------------------------------------------------------------------- valores


def in_obra(obra_id: Any) -> Any:
    """O parâmetro vale para a obra: é dela, ou é da biblioteca e foi incluído nela."""
    included = exists(
        select(ObraParam.def_id).where(
            ObraParam.obra_id == obra_id, ObraParam.def_id == ParamDef.id
        )
    )
    return or_(
        and_(ParamDef.scope == ParamScope.OBRA.value, ParamDef.obra_id == obra_id),
        and_(ParamDef.scope == ParamScope.GLOBAL.value, included),
    )


async def included_ids(session: AsyncSession, obra_id: int) -> set[int]:
    """Parâmetros da biblioteca incluídos na obra."""
    rows = await session.scalars(select(ObraParam.def_id).where(ObraParam.obra_id == obra_id))
    return set(rows)


def has_value(column: Any) -> Any:
    """Valor preenchido: não nulo, não JSON null e não texto vazio."""
    return and_(
        column.is_not(None),
        func.jsonb_typeof(column) != "null",
        column != cast(literal('""'), JSONB),
    )


async def values_count(session: AsyncSession, def_id: int) -> int:
    n = await session.scalar(
        select(func.count(func.distinct(ParamValue.mark_id))).where(
            ParamValue.def_id == def_id, has_value(ParamValue.value)
        )
    )
    return int(n or 0)


async def options_in_use(session: AsyncSession, def_id: int) -> list[str]:
    rows = await session.scalars(
        select(func.distinct(ParamValue.value.op("#>>")(literal_column("'{}'::text[]")))).where(
            ParamValue.def_id == def_id, has_value(ParamValue.value)
        )
    )
    return sorted(str(v) for v in rows if v is not None)


# --------------------------------------------------------------------------- validação


def _clean_name(raw: Any) -> str:
    name = " ".join(str(raw or "").split())
    if not name:
        raise ValidationError("Informe o nome do parâmetro.")
    if len(name) > MAX_NAME:
        raise ValidationError(f"O nome pode ter no máximo {MAX_NAME} caracteres.")
    return name


def _clean_type(raw: Any) -> ParamType:
    try:
        return ParamType(raw)
    except ValueError:
        tipos = ", ".join(t.value for t in ParamType)
        raise ValidationError(f"Tipo inválido: {raw!r} (use {tipos}).") from None


def _clean_options(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        raise ValidationError("Informe as opções da lista.")
    options = [" ".join(str(o).split()) for o in raw if str(o).strip()]
    if len(options) < 2:
        raise ValidationError("Uma lista precisa de pelo menos duas opções.")
    if len(options) > MAX_OPTIONS:
        raise ValidationError(f"Uma lista pode ter no máximo {MAX_OPTIONS} opções.")
    seen: dict[str, str] = {}
    for o in options:
        if len(o) > MAX_OPTION:
            raise ValidationError(f"Cada opção pode ter no máximo {MAX_OPTION} caracteres.")
        if o.casefold() in seen:
            raise ValidationError(f'Há opções repetidas: "{o}".')
        seen[o.casefold()] = o
    return options


def _clean_unit(raw: Any) -> str | None:
    unit = " ".join(str(raw or "").split())
    if len(unit) > MAX_UNIT:
        raise ValidationError(f"A unidade pode ter no máximo {MAX_UNIT} caracteres.")
    return unit or None


def _clean_categories(raw: Any) -> list[str] | None:
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise ValidationError("Categorias devem ser uma lista.")
    out: list[str] = []
    for c in raw:
        cat = str(c).strip()
        if cat and cat not in out:
            out.append(cat)
    return out or None  # vazio = todas


async def _check_scope(
    session: AsyncSession, scope: Any, obra_id: Any
) -> tuple[ParamScope, int | None]:
    try:
        sc = ParamScope(scope)
    except ValueError:
        raise ValidationError("Escopo inválido (use global ou obra).") from None
    if sc is ParamScope.GLOBAL:
        return sc, None
    if obra_id is None:
        raise ValidationError("Informe a obra de um parâmetro com escopo de obra.")
    if await session.get(Obra, obra_id) is None:
        raise NotFoundError("Obra não encontrada.")
    return sc, int(obra_id)


async def _ensure_name_free(
    session: AsyncSession, name: str, scope: ParamScope, obra_id: int | None, exclude_id: int | None
) -> None:
    same_name = and_(ParamDef.active.is_(True), func.lower(ParamDef.name) == name.lower())
    if scope is ParamScope.GLOBAL:
        clash = same_name  # global colide com qualquer ativo, de qualquer obra
    else:
        clash = and_(
            same_name,
            or_(ParamDef.scope == ParamScope.GLOBAL.value, ParamDef.obra_id == obra_id),
        )
    stmt = select(ParamDef).where(clash)
    if exclude_id is not None:
        stmt = stmt.where(ParamDef.id != exclude_id)
    other = await session.scalar(stmt.limit(1))
    if other is not None:
        where = "no catálogo global" if other.scope == ParamScope.GLOBAL.value else "nesta obra"
        if other.scope != ParamScope.GLOBAL.value and scope is ParamScope.GLOBAL:
            where = "em uma obra"
        raise ConflictError(f'Já existe um parâmetro "{other.name}" {where}.')


def _apply_type_fields(p: ParamDef, ptype: ParamType, data: ParamDefInput) -> None:
    """Unidade só para número; opções só para lista (campos dos outros tipos ficam nulos)."""
    if ptype is ParamType.NUMBER:
        if data.unit is not UNSET:
            p.unit = _clean_unit(data.unit)
    else:
        p.unit = None
    if ptype is ParamType.LIST:
        if data.options is not UNSET:
            p.options = _clean_options(data.options)
        elif not p.options:
            raise ValidationError("Uma lista precisa de pelo menos duas opções.")
    else:
        p.options = None


# --------------------------------------------------------------------------- consultas


async def get_param(session: AsyncSession, def_id: int, *, active_only: bool = True) -> ParamDef:
    p = await session.get(ParamDef, def_id)
    if p is None or (active_only and not p.active):
        raise NotFoundError("Parâmetro não encontrado.")
    return p


async def describe(
    session: AsyncSession, p: ParamDef, *, in_obra_flag: bool | None = None
) -> ParamDefInfo:
    creator = await session.get(User, p.created_by) if p.created_by else None
    obra = await session.get(Obra, p.obra_id) if p.obra_id else None
    in_use = await options_in_use(session, p.id) if p.type == ParamType.LIST.value else []
    obras_count = 0
    if p.scope == ParamScope.GLOBAL.value:
        obras_count = int(
            await session.scalar(
                select(func.count()).select_from(ObraParam).where(ObraParam.def_id == p.id)
            )
            or 0
        )
    return ParamDefInfo(
        param=p,
        values_count=await values_count(session, p.id),
        created_by_name=creator.name if creator else None,
        obra_code=obra.code if obra else None,
        options_in_use=in_use,
        in_obra=in_obra_flag,
        obras_count=obras_count,
    )


async def list_params(
    session: AsyncSession,
    *,
    obra_id: int | None = None,
    include_inactive: bool = False,
    library: bool = False,
) -> list[ParamDefInfo]:
    """Com obra_id: os que valem na obra (os dela + os da biblioteca incluídos nela).
    Com obra_id e library: também os da biblioteca NÃO incluídos (in_obra = False), para
    o catálogo oferecer "Incluir nesta obra". Sem obra_id: todos."""
    stmt = select(ParamDef)
    if obra_id is not None:
        visible = in_obra(obra_id)
        if library:
            visible = or_(visible, ParamDef.scope == ParamScope.GLOBAL.value)
        stmt = stmt.where(visible)
    if not include_inactive:
        stmt = stmt.where(ParamDef.active.is_(True))
    params = list(await session.scalars(stmt.order_by(func.lower(ParamDef.name), ParamDef.id)))
    included = await included_ids(session, obra_id) if obra_id is not None else set()
    out = []
    for p in params:
        flag = None
        if obra_id is not None:
            flag = p.scope == ParamScope.OBRA.value or p.id in included
        out.append(await describe(session, p, in_obra_flag=flag))
    return out


# --------------------------------------------------------------------------- escrita


async def _flush(session: AsyncSession) -> None:
    try:
        await session.flush()
    except IntegrityError as exc:  # corrida entre duas criações com o mesmo nome
        await session.rollback()
        raise ConflictError("Já existe um parâmetro com esse nome.") from exc


async def _sync_filters(session: AsyncSession, p: ParamDef) -> None:
    """Motor de filtros: refaz fábrica + status das obras em que o parâmetro vale."""
    from app.services import piece_props  # piece_props importa este módulo

    await piece_props.sync_param(session, p)


async def _sync_obra(session: AsyncSession, obra_id: int) -> None:
    from app.services import piece_props

    await piece_props.sync_factory(session, obra_id)


async def _emit_changed(session: AsyncSession, p: ParamDef, action: str, actor: User) -> None:
    """param_def_changed para a obra do parâmetro, ou para TODAS as obras (global)."""
    if p.scope == ParamScope.OBRA.value and p.obra_id is not None:
        obra_ids = [p.obra_id]
    else:
        obra_ids = list(await session.scalars(select(Obra.id).order_by(Obra.id)))
    for obra_id in obra_ids:
        events.emit(
            session,
            obra_id,
            "param_def_changed",
            {"def_id": p.id, "name": p.name, "action": action, "scope": p.scope},
            actor,
        )


async def create_param(session: AsyncSession, data: ParamDefInput, actor: User) -> ParamDef:
    name = _clean_name(data.name)
    ptype = _clean_type(data.type)
    scope, obra_id = await _check_scope(
        session,
        ParamScope.GLOBAL.value if data.scope is UNSET else data.scope,
        None if data.obra_id is UNSET else data.obra_id,
    )
    await _ensure_name_free(session, name, scope, obra_id, None)
    p = ParamDef(
        name=name,
        type=ptype.value,
        required=bool(False if data.required is UNSET else data.required),
        categories=_clean_categories(None if data.categories is UNSET else data.categories),
        scope=scope.value,
        obra_id=obra_id,
        created_by=actor.id,
        updated_by=actor.id,
    )
    _apply_type_fields(p, ptype, data)
    session.add(p)
    await _flush(session)
    await audit.record(session, "param_def", p.id, "create", None, audit.snapshot(p), actor)
    await _emit_changed(session, p, "created", actor)
    await _sync_filters(session, p)
    target = None if data.include_in_obra_id is UNSET else data.include_in_obra_id
    if scope is ParamScope.GLOBAL and target is not None:
        await include_param(session, int(target), p.id, actor)
    return p


async def _global_param(session: AsyncSession, def_id: int) -> ParamDef:
    p = await get_param(session, def_id)
    if p.scope != ParamScope.GLOBAL.value:
        raise ValidationError(
            "Este parâmetro é só desta obra: não se inclui nem se retira; exclua-o se não "
            "for mais necessário."
        )
    return p


async def include_param(session: AsyncSession, obra_id: int, def_id: int, actor: User) -> bool:
    """Inclui um parâmetro da biblioteca na obra. Devolve False se já estava. Sem commit."""
    if await session.get(Obra, obra_id) is None:
        raise NotFoundError("Obra não encontrada.")
    p = await _global_param(session, def_id)
    if await session.get(ObraParam, (obra_id, def_id)) is not None:
        return False
    session.add(ObraParam(obra_id=obra_id, def_id=def_id, created_by=actor.id))
    await session.flush()
    await audit.record(
        session,
        "obra_param",
        f"{obra_id}:{def_id}",
        "include",
        None,
        {"obra_id": obra_id, "def_id": def_id, "param": p.name},
        actor,
    )
    events.emit(
        session,
        obra_id,
        "param_def_changed",
        {"def_id": p.id, "name": p.name, "action": "included", "scope": p.scope},
        actor,
    )
    await _sync_obra(session, obra_id)
    return True


async def exclude_param(session: AsyncSession, obra_id: int, def_id: int, actor: User) -> bool:
    """Retira o parâmetro da biblioteca da obra. Os valores ficam guardados (voltam se o
    parâmetro for incluído de novo). Devolve False se não estava incluído. Sem commit."""
    p = await _global_param(session, def_id)
    row = await session.get(ObraParam, (obra_id, def_id))
    if row is None:
        return False
    kept = await session.scalar(
        select(func.count())
        .select_from(ParamValue)
        .join(Mark, Mark.id == ParamValue.mark_id)
        .where(ParamValue.def_id == def_id, Mark.obra_id == obra_id, has_value(ParamValue.value))
    )
    await session.delete(row)
    await session.flush()
    await audit.record(
        session,
        "obra_param",
        f"{obra_id}:{def_id}",
        "exclude",
        {"obra_id": obra_id, "def_id": def_id, "param": p.name},
        {"values_kept": int(kept or 0)},
        actor,
    )
    events.emit(
        session,
        obra_id,
        "param_def_changed",
        {"def_id": p.id, "name": p.name, "action": "excluded", "scope": p.scope},
        actor,
    )
    await _sync_obra(session, obra_id)
    return True


async def update_param(
    session: AsyncSession, def_id: int, data: ParamDefInput, actor: User
) -> ParamDef:
    p = await get_param(session, def_id)
    before = audit.snapshot(p)
    used = await values_count(session, p.id)

    ptype = ParamType(p.type) if data.type is UNSET else _clean_type(data.type)
    if ptype.value != p.type and used:
        raise ConflictError(
            f"O tipo não pode ser alterado: {used} marca(s) já têm valor neste parâmetro."
        )

    scope_raw = p.scope if data.scope is UNSET else data.scope
    obra_raw = (
        (p.obra_id if data.obra_id is UNSET else data.obra_id) if scope_raw == "obra" else None
    )
    scope, obra_id = await _check_scope(session, scope_raw, obra_raw)
    if (scope.value != p.scope or obra_id != p.obra_id) and used:
        raise ConflictError(
            f"O escopo não pode ser alterado: {used} marca(s) já têm valor neste parâmetro."
        )

    name = p.name if data.name is UNSET else _clean_name(data.name)
    if name.lower() != p.name.lower() or scope.value != p.scope or obra_id != p.obra_id:
        await _ensure_name_free(session, name, scope, obra_id, p.id)

    if ptype is ParamType.LIST and data.options is not UNSET:
        new_options = _clean_options(data.options)
        in_use = await options_in_use(session, p.id)
        removed = [o for o in in_use if o not in new_options]
        if removed:
            raise ConflictError(
                "Opções em uso não podem ser removidas: " + ", ".join(removed) + "."
            )

    p.name = name
    p.type = ptype.value
    p.scope = scope.value
    p.obra_id = obra_id
    if data.required is not UNSET:
        p.required = bool(data.required)
    if data.categories is not UNSET:
        p.categories = _clean_categories(data.categories)
    _apply_type_fields(p, ptype, data)
    p.updated_by = actor.id
    await _flush(session)
    await session.refresh(p)
    await audit.record(session, "param_def", p.id, "update", before, audit.snapshot(p), actor)
    await _emit_changed(session, p, "updated", actor)
    await _sync_filters(session, p)
    return p


async def delete_param(session: AsyncSession, def_id: int, actor: User) -> ParamDef:
    """Exclusão lógica. Os valores continuam no banco e vão para a auditoria."""
    p = await get_param(session, def_id)
    before = audit.snapshot(p)
    rows = await session.execute(
        select(ParamValue.mark_id, ParamValue.value)
        .where(ParamValue.def_id == p.id, has_value(ParamValue.value))
        .order_by(ParamValue.mark_id)
    )
    kept = [{"mark_id": mark_id, "value": value} for mark_id, value in rows]
    p.active = False
    p.updated_by = actor.id
    await session.flush()
    await session.refresh(p)
    after = audit.snapshot(p) | {"values": kept}
    await audit.record(session, "param_def", p.id, "delete", before, after, actor)
    await _emit_changed(session, p, "deleted", actor)
    await _sync_filters(session, p)
    return p
