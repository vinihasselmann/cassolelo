"""Esquemas de cores: /api/color-schemes (CRUD). Mesmas regras dos filtros salvos.

A avaliação numa versão fica em /api/versions/{id}/color-scheme/evaluate.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel

from app.api.obra_access import require_obra_access
from app.api.saved_filters import can_edit, roles
from app.auth import CurrentUser
from app.db import SessionDep
from app.models import ColorScheme, User
from app.services import obra_access
from app.services import saved_filters as service

# Acesso por obra (11.2): 404 nas obras que o usuário não vê.
router = APIRouter(
    prefix="/color-schemes", tags=["color-schemes"], dependencies=[Depends(require_obra_access)]
)


class ColorSchemeOut(BaseModel):
    id: int
    name: str
    scope: str
    owner_id: int | None
    obra_id: int | None
    rules: list[dict[str, Any]]  # [{filter: id | definição, color, label}], em ordem
    editable: bool
    created_at: datetime
    updated_at: datetime
    created_by: int | None
    updated_by: int | None


def _out(item: ColorScheme, user: User, allowed: list[str]) -> ColorSchemeOut:
    return ColorSchemeOut(
        id=item.id,
        name=item.name,
        scope=item.scope,
        owner_id=item.owner_id,
        obra_id=item.obra_id,
        rules=item.rules,
        editable=can_edit(item, user, allowed),
        created_at=item.created_at,
        updated_at=item.updated_at,
        created_by=item.created_by,
        updated_by=item.updated_by,
    )


@router.get("", response_model=list[ColorSchemeOut])
async def list_color_schemes(
    request: Request, session: SessionDep, user: CurrentUser, obra_id: int | None = None
) -> list[ColorSchemeOut]:
    allowed = roles(request)
    visible = await obra_access.visible_obra_ids(session, user)  # 11.2
    items = await service.list_schemes(session, user, obra_id, visible)
    return [_out(s, user, allowed) for s in items]


@router.get("/{scheme_id}", response_model=ColorSchemeOut)
async def get_color_scheme(
    scheme_id: int, request: Request, session: SessionDep, user: CurrentUser
) -> ColorSchemeOut:
    return _out(await service.get_scheme(session, scheme_id, user), user, roles(request))


@router.post("", response_model=ColorSchemeOut, status_code=status.HTTP_201_CREATED)
async def create_color_scheme(
    body: service.ColorSchemeInput, request: Request, session: SessionDep, user: CurrentUser
) -> ColorSchemeOut:
    await obra_access.ensure_body_obra(session, user, body.obra_id)
    allowed = roles(request)
    item = await service.create_scheme(session, body, user, allowed)
    await session.commit()
    await session.refresh(item)
    return _out(item, user, allowed)


@router.patch("/{scheme_id}", response_model=ColorSchemeOut)
async def update_color_scheme(
    scheme_id: int,
    body: service.ColorSchemePatch,
    request: Request,
    session: SessionDep,
    user: CurrentUser,
) -> ColorSchemeOut:
    await obra_access.ensure_body_obra(session, user, body.obra_id)
    allowed = roles(request)
    item = await service.update_scheme(session, scheme_id, body, user, allowed)
    await session.commit()
    await session.refresh(item)
    return _out(item, user, allowed)


@router.delete("/{scheme_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_color_scheme(
    scheme_id: int, request: Request, session: SessionDep, user: CurrentUser
) -> None:
    await service.delete_scheme(session, scheme_id, user, roles(request))
    await session.commit()
