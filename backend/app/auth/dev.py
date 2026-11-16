"""Usuário simulado (até a Fase 11): header X-Dev-User com o id do usuário.

Só funciona com APP_ENV=dev ou, no ambiente de teste com a fábrica, APP_ENV=staging +
DEV_USERS_ENABLED=true. Em qualquer outro caso responde 401.
"""

from __future__ import annotations

from fastapi import HTTPException, Request, status

from app.config import Settings
from app.db import SessionDep
from app.models import User
from app.observability.logging import bind
from app.security.rate_limit import enforce_write_limit

DEV_USER_HEADER = "X-Dev-User"


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


async def current_user(request: Request, session: SessionDep) -> User:
    settings: Settings = request.app.state.settings
    if not settings.dev_users_allowed:
        raise _unauthorized("Autenticação não configurada neste ambiente.")
    raw = request.headers.get(DEV_USER_HEADER, "").strip()
    if not raw:
        raise _unauthorized(f"Selecione um usuário (cabeçalho {DEV_USER_HEADER} ausente).")
    try:
        user_id = int(raw)
    except ValueError:
        raise _unauthorized(f"{DEV_USER_HEADER} inválido.") from None
    user = await session.get(User, user_id)
    if user is None or not user.active:
        raise _unauthorized("Usuário simulado não encontrado ou inativo.")
    bind(user=user)  # logs desta requisição levam o usuário
    await enforce_write_limit(request, user.id)  # 429 nas escritas acima do limite (10.2)
    return user
