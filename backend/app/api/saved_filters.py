"""Filtros salvos: /api/saved-filters (CRUD).

Pessoais: só o dono vê e edita. Compartilhados: todos veem; criar, editar e excluir exige
um papel de SHARED_FILTER_ROLES. Os de sistema (antigos atalhos) não são editáveis.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel

from app.api.obra_access import require_obra_access
from app.auth import CurrentUser
from app.db import SessionDep
from app.models import SavedFilter, User
from app.services import obra_access
from app.services import saved_filters as service

# Acesso por obra (11.2): 404 nas obras que o usuário não vê.
router = APIRouter(
    prefix="/saved-filters", tags=["saved-filters"], dependencies=[Depends(require_obra_access)]
)


class SavedFilterOut(BaseModel):
    id: int
    name: str
    scope: str
    owner_id: int | None
    obra_id: int | None  # nulo = todas as obras
    definition: dict[str, Any]
    system_key: str | None  # filtro de sistema (antigo atalho da busca)
    editable: bool  # o usuário atual pode editar e excluir
    created_at: datetime
    updated_at: datetime
    created_by: int | None
    updated_by: int | None


def roles(request: Request) -> list[str]:
    settings = request.app.state.settings
    return list(settings.shared_filter_role_list)


def can_edit(item: SavedFilter | Any, user: User, allowed: list[str]) -> bool:
    if getattr(item, "system_key", None) is not None:
        return False
    if item.scope == service.SHARED:
        return user.role in allowed
    return bool(item.owner_id == user.id)


def _out(item: SavedFilter, user: User, allowed: list[str]) -> SavedFilterOut:
    return SavedFilterOut(
        id=item.id,
        name=item.name,
        scope=item.scope,
        owner_id=item.owner_id,
        obra_id=item.obra_id,
        definition=item.definition,
        system_key=item.system_key,
        editable=can_edit(item, user, allowed),
        created_at=item.created_at,
        updated_at=item.updated_at,
        created_by=item.created_by,
        updated_by=item.updated_by,
    )


@router.get("", response_model=list[SavedFilterOut])
async def list_saved_filters(
    request: Request, session: SessionDep, user: CurrentUser, obra_id: int | None = None
) -> list[SavedFilterOut]:
    """Os que o usuário vê: compartilhados + os pessoais dele. Com obra_id, só os que
    valem na obra (os dela e os de todas as obras). Os de sistema vêm primeiro."""
    allowed = roles(request)
    visible = await obra_access.visible_obra_ids(session, user)  # 11.2
    items = await service.list_filters(session, user, obra_id, visible)
    return [_out(f, user, allowed) for f in items]


@router.get("/{filter_id}", response_model=SavedFilterOut)
async def get_saved_filter(
    filter_id: int, request: Request, session: SessionDep, user: CurrentUser
) -> SavedFilterOut:
    return _out(await service.get_filter(session, filter_id, user), user, roles(request))


@router.post("", response_model=SavedFilterOut, status_code=status.HTTP_201_CREATED)
async def create_saved_filter(
    body: service.SavedFilterInput, request: Request, session: SessionDep, user: CurrentUser
) -> SavedFilterOut:
    await obra_access.ensure_body_obra(session, user, body.obra_id)
    allowed = roles(request)
    item = await service.create_filter(session, body, user, allowed)
    await session.commit()
    await session.refresh(item)
    return _out(item, user, allowed)


@router.patch("/{filter_id}", response_model=SavedFilterOut)
async def update_saved_filter(
    filter_id: int,
    body: service.SavedFilterPatch,
    request: Request,
    session: SessionDep,
    user: CurrentUser,
) -> SavedFilterOut:
    await obra_access.ensure_body_obra(session, user, body.obra_id)
    allowed = roles(request)
    item = await service.update_filter(session, filter_id, body, user, allowed)
    await session.commit()
    await session.refresh(item)
    return _out(item, user, allowed)


@router.delete("/{filter_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_saved_filter(
    filter_id: int, request: Request, session: SessionDep, user: CurrentUser
) -> None:
    await service.delete_filter(session, filter_id, user, roles(request))
    await session.commit()
