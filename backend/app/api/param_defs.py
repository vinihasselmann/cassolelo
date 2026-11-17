"""Catálogo de parâmetros da fábrica: GET (todos) e POST/PATCH/DELETE (fábrica e admin)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from app.auth import CurrentUser, Role, require_role
from app.db import SessionDep
from app.models import User
from app.models.enums import ParamLevel, ParamScope, ParamType
from app.services import param_defs as service
from app.services.param_defs import ParamDefInfo, ParamDefInput

router = APIRouter(prefix="/param-defs", tags=["param-defs"])

# Só a fábrica (e o admin) cria, edita e exclui parâmetros.
PARAM_EDITOR_ROLES = (Role.FABRICA, Role.ADMIN)
ParamEditor = Annotated[User, Depends(require_role(*PARAM_EDITOR_ROLES))]


class ParamDefOut(BaseModel):
    id: int
    name: str
    type: ParamType
    unit: str | None
    options: list[str] | None
    required: bool
    categories: list[str] | None  # nulo = todas
    scope: ParamScope
    level: ParamLevel  # por marca ou por peça
    obra_id: int | None
    obra_code: str | None
    active: bool
    values_count: int  # marcas (por marca) ou unidades de peça (por peça) com valor
    in_obra: bool | None = None  # listado para uma obra: vale nela?
    obras_count: int = 0  # obras em que o parâmetro da biblioteca está incluído
    options_in_use: list[str]
    created_at: datetime
    updated_at: datetime
    created_by_name: str | None


class ParamDefCreate(BaseModel):
    """Os tipos são checados aqui; as regras (com mensagens em português), no serviço."""

    name: str
    type: str
    unit: str | None = None
    options: list[str] | None = None
    required: bool = False
    categories: list[str] | None = None
    scope: str = ParamScope.GLOBAL.value
    obra_id: int | None = None
    # parâmetro da biblioteca criado de dentro de uma obra: já entra nela
    include_in_obra_id: int | None = None
    level: str = ParamLevel.MARK.value  # "mark" (por marca) | "piece" (por peça)


class ParamDefUpdate(BaseModel):
    name: str | None = None
    type: str | None = None
    unit: str | None = None
    options: list[str] | None = None
    required: bool | None = None
    categories: list[str] | None = Field(default=None, description="[] = todas")
    scope: str | None = None
    obra_id: int | None = None
    level: str | None = None  # só enquanto não houver valores


def _out(info: ParamDefInfo) -> ParamDefOut:
    p = info.param
    return ParamDefOut(
        id=p.id,
        name=p.name,
        type=ParamType(p.type),
        unit=p.unit,
        options=p.options,
        required=p.required,
        categories=p.categories,
        scope=ParamScope(p.scope),
        level=ParamLevel(p.level),
        obra_id=p.obra_id,
        obra_code=info.obra_code,
        active=p.active,
        values_count=info.values_count,
        in_obra=info.in_obra,
        obras_count=info.obras_count,
        options_in_use=info.options_in_use,
        created_at=p.created_at,
        updated_at=p.updated_at,
        created_by_name=info.created_by_name,
    )


def _input(body: BaseModel) -> ParamDefInput:
    """Só os campos enviados no corpo entram; os outros ficam UNSET (não mudam)."""
    sent: dict[str, Any] = body.model_dump(exclude_unset=True)
    data = ParamDefInput()
    for key, value in sent.items():
        setattr(data, key, value)
    return data


@router.get("", response_model=list[ParamDefOut])
async def list_param_defs(
    session: SessionDep,
    _user: CurrentUser,
    obra_id: int | None = None,
    include_inactive: bool = False,
    library: bool = False,
) -> list[ParamDefOut]:
    """Com obra_id: os que valem na obra (os dela + os da biblioteca incluídos nela); com
    library=true também os da biblioteca não incluídos (in_obra=false). Sem obra_id: todos.
    Excluídos só com include_inactive."""
    infos = await service.list_params(
        session, obra_id=obra_id, include_inactive=include_inactive, library=library
    )
    return [_out(i) for i in infos]


@router.post("", response_model=ParamDefOut, status_code=status.HTTP_201_CREATED)
async def create_param_def(
    body: ParamDefCreate, session: SessionDep, user: ParamEditor
) -> ParamDefOut:
    p = await service.create_param(session, _input(body), user)
    await session.commit()
    return _out(await service.describe(session, p))


@router.patch("/{def_id}", response_model=ParamDefOut)
async def update_param_def(
    def_id: int, body: ParamDefUpdate, session: SessionDep, user: ParamEditor
) -> ParamDefOut:
    p = await service.update_param(session, def_id, _input(body), user)
    await session.commit()
    return _out(await service.describe(session, p))


@router.delete("/{def_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_param_def(def_id: int, session: SessionDep, user: ParamEditor) -> None:
    await service.delete_param(session, def_id, user)
    await session.commit()
