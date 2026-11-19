"""Filtros salvos e esquemas de cores: CRUD, visibilidade e permissões.

- **personal:** só o dono vê, edita e exclui (nem o admin vê os pessoais dos outros).
- **shared:** todos veem; criar, editar e excluir exige um papel de SHARED_FILTER_ROLES
  (padrão fábrica e admin). Criar, editar e excluir compartilhados vai para a auditoria.
- **obra_id** nulo = vale para todas as obras.
- **Filtros de sistema** (`system_key`): os antigos atalhos da busca. Compartilhados e
  não editáveis; a busca (`shortcut=`) usa a definição guardada aqui.
- Nomes únicos por escopo, sem diferenciar maiúsculas: entre os compartilhados; entre
  os pessoais de cada dono.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ColorScheme, Obra, SavedFilter, User
from app.services import audit
from app.services.errors import ConflictError, ForbiddenError, NotFoundError, ValidationError
from app.services.filters import FilterDef

PERSONAL, SHARED = "personal", "shared"
Scope = Literal["personal", "shared"]
MAX_SCHEME_RULES = 50


def _rule(key: str, value: object) -> dict[str, Any]:
    return {"field": {"source": "system", "key": key}, "op": "eq", "value": value}


# Antigos atalhos da busca -> (nome, definição). Iguais ao seed da migração 0014.
SYSTEM_FILTERS: dict[str, tuple[str, dict[str, Any]]] = {
    key: (name, {"mode": "highlight", "logic": "and", "rules": [rule]})
    for key, name, rule in (
        ("pending", "Pendentes", _rule("status", "Pendente")),
        ("partial", "Parciais", _rule("status", "Parcial")),
        ("review", "A revisar", _rule("status", "Revisar")),
        ("new", "Novas na versão", _rule("new", True)),
        ("orphans", "Órfãs", _rule("orphan", True)),
    )
}


async def system_definition(session: AsyncSession, key: str) -> FilterDef:
    """Definição do filtro de sistema (atalho da busca), lida do banco."""
    row = await session.scalar(select(SavedFilter).where(SavedFilter.system_key == key))
    if row is None:  # pragma: no cover - criado pela migração 0014
        raise NotFoundError(f'Filtro de sistema "{key}" não encontrado.')
    return FilterDef.model_validate(row.definition)


# ------------------------------------------------------------------ permissões


Item = SavedFilter | ColorScheme


def _noun(item: Item | type[Item]) -> str:
    cls = item if isinstance(item, type) else type(item)
    return "filtro" if cls is SavedFilter else "esquema de cores"


def is_visible(item: Item, user: User) -> bool:
    return item.scope == SHARED or item.owner_id == user.id


def _check_shared_role(user: User, roles: Sequence[str], cls: type[Item]) -> None:
    if user.role not in roles:
        raise ForbiddenError(
            f"Seu papel não permite criar ou alterar {_noun(cls)}s compartilhados."
        )


def _check_editable(item: Item, user: User, roles: Sequence[str]) -> None:
    if not is_visible(item, user):
        raise NotFoundError(f"{_noun(item).capitalize()} não encontrado.")
    if isinstance(item, SavedFilter) and item.system_key is not None:
        raise ForbiddenError("Filtros do sistema não podem ser alterados nem excluídos.")
    if item.scope == SHARED:
        _check_shared_role(user, roles, type(item))
    elif item.owner_id != user.id:  # pragma: no cover - is_visible já barra
        raise NotFoundError(f"{_noun(item).capitalize()} não encontrado.")


async def _get(session: AsyncSession, cls: type[Item], item_id: int, user: User) -> Any:
    item: Item | None = await session.get(cls, item_id)
    if item is None or not is_visible(item, user):
        raise NotFoundError(f"{_noun(cls).capitalize()} não encontrado.")
    return item


def _visible(
    cls: type[Item], user: User, obra_id: int | None, visible_obras: set[int] | None = None
) -> list[Any]:
    """visible_obras: obras que o usuário vê (11.2); None = todas."""
    conds: list[Any] = [or_(cls.scope == SHARED, cls.owner_id == user.id)]
    if obra_id is not None:
        conds.append(or_(cls.obra_id.is_(None), cls.obra_id == obra_id))
    if visible_obras is not None:
        conds.append(or_(cls.obra_id.is_(None), cls.obra_id.in_(visible_obras)))
    return conds


async def _check_obra(session: AsyncSession, obra_id: int | None) -> None:
    if obra_id is not None and await session.get(Obra, obra_id) is None:
        raise ValidationError("Obra não encontrada.")


def _clean_name(name: str) -> str:
    name = " ".join(name.split())
    if not name:
        raise ValidationError("Informe um nome.")
    return name


async def _check_name(
    session: AsyncSession,
    cls: type[Item],
    name: str,
    scope: str,
    owner_id: int | None,
    exclude_id: int | None,
) -> None:
    conds: list[Any] = [func.lower(cls.name) == name.lower(), cls.scope == scope]
    if scope == PERSONAL:
        conds.append(cls.owner_id == owner_id)
    if exclude_id is not None:
        conds.append(cls.id != exclude_id)
    if await session.scalar(select(cls.id).where(*conds).limit(1)) is not None:
        where = "compartilhado" if scope == SHARED else "seu"
        raise ConflictError(f'Já existe um {_noun(cls)} {where} com o nome "{name}".')


async def _audit(
    session: AsyncSession,
    item: Item,
    action: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    user: User,
) -> None:
    """Só os compartilhados vão para a auditoria (antes ou depois da mudança)."""
    shared = any(s is not None and s.get("scope") == SHARED for s in (before, after))
    if shared:
        entity = "saved_filter" if isinstance(item, SavedFilter) else "color_scheme"
        await audit.record(session, entity, item.id, action, before, after, user)


def _snap(item: Item) -> dict[str, Any]:
    return audit.snapshot(item, exclude=("created_at", "updated_at"))


# --------------------------------------------------------------- filtros salvos


class SavedFilterInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    scope: Scope = "personal"
    obra_id: int | None = None
    definition: FilterDef


class SavedFilterPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=120)
    scope: Scope | None = None
    obra_id: int | None = None
    definition: FilterDef | None = None


async def list_filters(
    session: AsyncSession,
    user: User,
    obra_id: int | None = None,
    visible_obras: set[int] | None = None,
) -> list[SavedFilter]:
    """Os do sistema primeiro (na ordem dos atalhos), depois por nome."""
    rows = list(
        await session.scalars(
            select(SavedFilter)
            .where(*_visible(SavedFilter, user, obra_id, visible_obras))
            .order_by(func.lower(SavedFilter.name), SavedFilter.id)
        )
    )
    order = list(SYSTEM_FILTERS)
    return sorted(
        rows, key=lambda f: order.index(f.system_key) if f.system_key in order else len(order)
    )


async def get_filter(session: AsyncSession, filter_id: int, user: User) -> SavedFilter:
    item: SavedFilter = await _get(session, SavedFilter, filter_id, user)
    return item


async def create_filter(
    session: AsyncSession, data: SavedFilterInput, user: User, roles: Sequence[str]
) -> SavedFilter:
    if data.scope == SHARED:
        _check_shared_role(user, roles, SavedFilter)
    name = _clean_name(data.name)
    await _check_obra(session, data.obra_id)
    await _check_name(session, SavedFilter, name, data.scope, user.id, None)
    item = SavedFilter(
        name=name,
        scope=data.scope,
        owner_id=user.id,
        obra_id=data.obra_id,
        definition=data.definition.model_dump(mode="json"),
        created_by=user.id,
        updated_by=user.id,
    )
    session.add(item)
    await session.flush()
    await _audit(session, item, "create", None, _snap(item), user)
    return item


async def update_filter(
    session: AsyncSession,
    filter_id: int,
    patch: SavedFilterPatch,
    user: User,
    roles: Sequence[str],
) -> SavedFilter:
    item = await get_filter(session, filter_id, user)
    _check_editable(item, user, roles)
    sent = patch.model_fields_set
    scope: str = patch.scope if patch.scope is not None else item.scope
    if scope == SHARED:
        _check_shared_role(user, roles, SavedFilter)
    name = _clean_name(patch.name) if patch.name is not None else item.name
    owner = user.id if scope == PERSONAL and item.scope == SHARED else item.owner_id
    obra_id = patch.obra_id if "obra_id" in sent else item.obra_id
    await _check_obra(session, obra_id)
    await _check_name(session, SavedFilter, name, scope, owner, item.id)
    await _check_filter_still_usable(session, item, scope, owner, obra_id)

    before = _snap(item)
    item.name, item.scope, item.owner_id, item.obra_id = name, scope, owner, obra_id
    if patch.definition is not None:
        item.definition = patch.definition.model_dump(mode="json")
    item.updated_by = user.id
    await session.flush()
    await session.refresh(item)
    await _audit(session, item, "update", before, _snap(item), user)
    return item


async def delete_filter(
    session: AsyncSession, filter_id: int, user: User, roles: Sequence[str]
) -> None:
    item = await get_filter(session, filter_id, user)
    _check_editable(item, user, roles)
    users = await _schemes_using(session, item.id)
    if users:
        names = ", ".join(f'"{s.name}"' for s in users)
        raise ConflictError(
            f"O filtro é usado nos esquemas de cores {names}. Tire-o deles antes de excluir."
        )
    before = _snap(item)
    await session.delete(item)
    await session.flush()
    await _audit(session, item, "delete", before, None, user)


async def _schemes_using(session: AsyncSession, filter_id: int) -> list[ColorScheme]:
    return list(
        await session.scalars(
            select(ColorScheme)
            .where(ColorScheme.rules.contains([{"filter": filter_id}]))
            .order_by(ColorScheme.name)
        )
    )


async def _check_filter_still_usable(
    session: AsyncSession, item: SavedFilter, scope: str, owner: int | None, obra_id: int | None
) -> None:
    """Mudar escopo, dono ou obra não pode quebrar um esquema de cores que usa o filtro."""
    for scheme in await _schemes_using(session, item.id):
        if not _filter_usable_by(
            scope, owner, obra_id, scheme.scope, scheme.owner_id, scheme.obra_id
        ):
            raise ConflictError(
                f'O esquema de cores "{scheme.name}" usa este filtro: com essa mudança ele '
                "deixaria de poder usá-lo."
            )


def _filter_usable_by(
    f_scope: str,
    f_owner: int | None,
    f_obra: int | None,
    s_scope: str,
    s_owner: int | None,
    s_obra: int | None,
) -> bool:
    """Um esquema pode usar o filtro? Esquema compartilhado só usa filtro compartilhado;
    pessoal usa compartilhado ou do mesmo dono. Filtro de uma obra, só em esquema da
    mesma obra."""
    if f_scope == PERSONAL and (s_scope == SHARED or f_owner != s_owner):
        return False
    return f_obra is None or f_obra == s_obra


# ------------------------------------------------------------ esquemas de cores


class SchemeRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filter: StrictInt | FilterDef  # id de filtro salvo ou definição inline
    color: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    label: str = Field(default="", max_length=120)

    @field_validator("color")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper()


class ColorSchemeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    scope: Scope = "personal"
    obra_id: int | None = None
    rules: list[SchemeRule] = Field(min_length=1, max_length=MAX_SCHEME_RULES)


class ColorSchemePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=120)
    scope: Scope | None = None
    obra_id: int | None = None
    rules: list[SchemeRule] | None = Field(default=None, min_length=1, max_length=MAX_SCHEME_RULES)


async def _check_rules(
    session: AsyncSession,
    rules: list[SchemeRule],
    scope: str,
    owner: int | None,
    obra_id: int | None,
) -> None:
    for i, rule in enumerate(rules):
        if isinstance(rule.filter, FilterDef):
            continue
        f = await session.get(SavedFilter, rule.filter)
        if f is None or (f.scope == PERSONAL and f.owner_id != owner):
            raise ValidationError(f"Regra {i + 1}: filtro {rule.filter} não encontrado.")
        if not _filter_usable_by(f.scope, f.owner_id, f.obra_id, scope, owner, obra_id):
            why = (
                "um esquema compartilhado só pode usar filtros compartilhados"
                if f.scope == PERSONAL and scope == SHARED
                else "o filtro é de outra obra"
            )
            raise ValidationError(f'Regra {i + 1} ("{f.name}"): {why}.')


def _rules_json(rules: list[SchemeRule]) -> list[Any]:
    return [r.model_dump(mode="json") for r in rules]


async def list_schemes(
    session: AsyncSession,
    user: User,
    obra_id: int | None = None,
    visible_obras: set[int] | None = None,
) -> list[ColorScheme]:
    return list(
        await session.scalars(
            select(ColorScheme)
            .where(*_visible(ColorScheme, user, obra_id, visible_obras))
            .order_by(func.lower(ColorScheme.name), ColorScheme.id)
        )
    )


async def get_scheme(session: AsyncSession, scheme_id: int, user: User) -> ColorScheme:
    item: ColorScheme = await _get(session, ColorScheme, scheme_id, user)
    return item


async def create_scheme(
    session: AsyncSession, data: ColorSchemeInput, user: User, roles: Sequence[str]
) -> ColorScheme:
    if data.scope == SHARED:
        _check_shared_role(user, roles, ColorScheme)
    name = _clean_name(data.name)
    await _check_obra(session, data.obra_id)
    await _check_name(session, ColorScheme, name, data.scope, user.id, None)
    await _check_rules(session, data.rules, data.scope, user.id, data.obra_id)
    item = ColorScheme(
        name=name,
        scope=data.scope,
        owner_id=user.id,
        obra_id=data.obra_id,
        rules=_rules_json(data.rules),
        created_by=user.id,
        updated_by=user.id,
    )
    session.add(item)
    await session.flush()
    await _audit(session, item, "create", None, _snap(item), user)
    return item


async def update_scheme(
    session: AsyncSession,
    scheme_id: int,
    patch: ColorSchemePatch,
    user: User,
    roles: Sequence[str],
) -> ColorScheme:
    item = await get_scheme(session, scheme_id, user)
    _check_editable(item, user, roles)
    sent = patch.model_fields_set
    scope: str = patch.scope if patch.scope is not None else item.scope
    if scope == SHARED:
        _check_shared_role(user, roles, ColorScheme)
    name = _clean_name(patch.name) if patch.name is not None else item.name
    owner = user.id if scope == PERSONAL and item.scope == SHARED else item.owner_id
    obra_id = patch.obra_id if "obra_id" in sent else item.obra_id
    rules = (
        patch.rules
        if patch.rules is not None
        else [SchemeRule.model_validate(r) for r in item.rules]
    )
    await _check_obra(session, obra_id)
    await _check_name(session, ColorScheme, name, scope, owner, item.id)
    await _check_rules(session, rules, scope, owner, obra_id)

    before = _snap(item)
    item.name, item.scope, item.owner_id, item.obra_id = name, scope, owner, obra_id
    item.rules = _rules_json(rules)
    item.updated_by = user.id
    await session.flush()
    await session.refresh(item)
    await _audit(session, item, "update", before, _snap(item), user)
    return item


async def delete_scheme(
    session: AsyncSession, scheme_id: int, user: User, roles: Sequence[str]
) -> None:
    item = await get_scheme(session, scheme_id, user)
    _check_editable(item, user, roles)
    before = _snap(item)
    await session.delete(item)
    await session.flush()
    await _audit(session, item, "delete", before, None, user)
