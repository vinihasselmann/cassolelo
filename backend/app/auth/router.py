"""GET /api/auth/config: o que o frontend precisa para o login (público, sem segredo)."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.config import Settings

router = APIRouter(prefix="/auth", tags=["auth"])


class AuthConfigOut(BaseModel):
    # vazios quando o login Microsoft não está configurado
    client_id: str
    tenant_id: str
    scope: str
    # usuário simulado (X-Dev-User) disponível: só com APP_ENV=dev
    dev_login: bool


@router.get("/config", response_model=AuthConfigOut)
async def auth_config(request: Request) -> AuthConfigOut:
    s: Settings = request.app.state.settings
    configured = s.entra_configured
    return AuthConfigOut(
        client_id=s.entra_client_id.strip() if configured else "",
        tenant_id=s.entra_tenant_id.strip() if configured else "",
        scope=s.entra_scope if configured else "",
        dev_login=s.dev_users_allowed,
    )
