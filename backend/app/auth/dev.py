"""Usuário simulado: header X-Dev-User com o id do usuário. Só com APP_ENV=dev."""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User

DEV_USER_HEADER = "X-Dev-User"


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


async def dev_user(session: AsyncSession, raw: str) -> User:
    try:
        user_id = int(raw)
    except ValueError:
        raise _unauthorized(f"{DEV_USER_HEADER} inválido.") from None
    user = await session.get(User, user_id)
    if user is None or not user.active:
        raise _unauthorized("Usuário simulado não encontrado ou inativo.")
    return user
