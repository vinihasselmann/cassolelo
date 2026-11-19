"""Tela "Usuários" (11.2): só admin. Regras em app/services/user_admin.py."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field

from app.auth import Role, require_role
from app.config import Settings
from app.db import SessionDep
from app.models import User
from app.services import user_admin
from app.services.user_admin import RoleSource, UserInfo, UserPatch

router = APIRouter(
    prefix="/users", tags=["users"], dependencies=[Depends(require_role(Role.ADMIN))]
)

Admin = Annotated[User, Depends(require_role(Role.ADMIN))]


class UserAdminOut(BaseModel):
    id: int
    name: str
    email: str
    role: Role
    active: bool
    all_obras: bool  # admin vê todas mesmo com false
    obra_ids: list[int]  # as obras que vê quando all_obras = false
    # de onde vem o papel: table (esta tela), bootstrap (admin fixo), groups (Entra)
    role_source: RoleSource
    created_at: datetime
    updated_at: datetime


class UserCreateIn(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    name: str | None = Field(default=None, max_length=200)  # vazio: o login preenche
    role: Role = Role.LEITURA
    all_obras: bool = True
    obra_ids: list[int] = Field(default_factory=list)


class UserUpdateIn(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    role: Role | None = None
    active: bool | None = None
    all_obras: bool | None = None
    obra_ids: list[int] | None = None


def _settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def _out(info: UserInfo) -> UserAdminOut:
    u = info.user
    return UserAdminOut(
        id=u.id,
        name=u.name,
        email=u.email,
        role=Role(u.role),
        active=u.active,
        all_obras=u.all_obras,
        obra_ids=info.obra_ids,
        role_source=info.role_source,
        created_at=u.created_at,
        updated_at=u.updated_at,
    )


@router.get("", response_model=list[UserAdminOut])
async def list_users(request: Request, session: SessionDep) -> list[UserAdminOut]:
    return [_out(i) for i in await user_admin.list_users(session, _settings(request))]


@router.post("", response_model=UserAdminOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreateIn, request: Request, session: SessionDep, admin: Admin
) -> UserAdminOut:
    settings = _settings(request)
    info = await user_admin.create_user(
        session,
        settings,
        email=body.email,
        name=body.name,
        role=body.role,
        all_obras=body.all_obras,
        obra_ids=body.obra_ids,
        actor=admin,
    )
    await session.commit()
    await session.refresh(info.user)  # created_at/updated_at vêm do banco
    return _out(info)


@router.patch("/{user_id}", response_model=UserAdminOut)
async def update_user(
    user_id: int, body: UserUpdateIn, request: Request, session: SessionDep, admin: Admin
) -> UserAdminOut:
    settings = _settings(request)
    patch = UserPatch(**body.model_dump(exclude_unset=True))
    info = await user_admin.update_user(session, settings, user_id, patch, admin)
    await session.commit()
    await session.refresh(info.user)
    return _out(info)
