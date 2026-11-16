"""Rotas de apoio ao desenvolvimento (só existem com APP_ENV=dev)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from app.api.schemas import UserOut
from app.db import SessionDep
from app.models import User

router = APIRouter(prefix="/dev", tags=["dev"])


@router.get("/users", response_model=list[UserOut])
async def dev_users(request: Request, session: SessionDep) -> list[UserOut]:
    """Lista de usuários para o seletor de usuário simulado do frontend."""
    if not request.app.state.settings.dev_users_allowed:
        raise HTTPException(status_code=404)
    rows = await session.scalars(select(User).where(User.active.is_(True)).order_by(User.id))
    return [UserOut.model_validate(u) for u in rows]
