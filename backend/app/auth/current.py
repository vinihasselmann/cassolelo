"""Quem está chamando a API.

1. `Authorization: Bearer <access token do Entra>`: login Microsoft (Fase 11).
2. Só com APP_ENV=dev, sem Bearer: `X-Dev-User: <id>` (usuário simulado).
3. Nada disso: 401.
"""

from __future__ import annotations

from fastapi import HTTPException, Request, status
from starlette.datastructures import State

from app.auth.dev import DEV_USER_HEADER, dev_user
from app.auth.entra import EntraVerifier, LoginUnavailableError, TokenError
from app.auth.users import resolve_user
from app.config import Settings
from app.db import SessionDep
from app.models import User
from app.observability.logging import bind
from app.security.rate_limit import enforce_write_limit


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def entra_verifier(state: State, settings: Settings) -> EntraVerifier:
    verifier: EntraVerifier | None = getattr(state, "entra", None)
    if verifier is None:
        verifier = EntraVerifier(settings)
        state.entra = verifier
    return verifier


def bearer_token(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    scheme, _, token = auth.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


async def _entra_user(request: Request, session: SessionDep, token: str) -> User:
    settings: Settings = request.app.state.settings
    if not settings.entra_configured:
        raise _unauthorized("Login Microsoft não configurado neste servidor.")
    verifier = entra_verifier(request.app.state, settings)
    try:
        identity = await verifier.verify(token)
    except TokenError as exc:
        raise _unauthorized(str(exc)) from None
    except LoginUnavailableError as exc:
        detail = str(exc)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail) from None
    return await resolve_user(session, settings, identity)


async def current_user(request: Request, session: SessionDep) -> User:
    settings: Settings = request.app.state.settings
    token = bearer_token(request)
    if token is not None:
        user = await _entra_user(request, session, token)
    elif settings.dev_users_allowed:
        raw = request.headers.get(DEV_USER_HEADER, "").strip()
        if not raw:
            raise _unauthorized(f"Selecione um usuário (cabeçalho {DEV_USER_HEADER} ausente).")
        user = await dev_user(session, raw)
    else:
        raise _unauthorized("Entre com sua conta Microsoft.")
    bind(user=user)  # logs desta requisição levam o usuário
    await enforce_write_limit(request, user.id)  # 429 nas escritas acima do limite (10.2)
    return user
