"""Token do Viewer para o navegador: 2-legged SOMENTE com viewables:read.

Nunca devolve o token de dados (data:read): o TokenProvider guarda cada conjunto de
escopos em cache separado. O APS não permite pedir um token 2-legged mais curto
(dura ~1 h); informamos ao navegador no máximo MAX_CLIENT_TTL segundos para que o
Viewer peça um novo com frequência.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from app.api.deps import ApsDep
from app.aps.auth import VIEWER_SCOPES
from app.auth import CurrentUser
from app.config import ApsRegion, Settings

router = APIRouter(tags=["viewer"])

MAX_CLIENT_TTL = 600


class ViewerTokenOut(BaseModel):
    access_token: str
    token_type: Literal["Bearer"] = "Bearer"  # noqa: S105 (tipo, não senha)
    expires_in: int
    region: ApsRegion


@router.get("/viewer-token", response_model=ViewerTokenOut)
async def viewer_token(
    request: Request, response: Response, aps: ApsDep, _user: CurrentUser
) -> ViewerTokenOut:
    token, ttl = await aps.tokens.get_token_with_ttl(VIEWER_SCOPES)
    response.headers["Cache-Control"] = "no-store"
    settings: Settings = request.app.state.settings
    return ViewerTokenOut(
        access_token=token,
        expires_in=max(1, min(ttl, MAX_CLIENT_TTL)),
        region=settings.aps_region,
    )


class ViewerConfigOut(BaseModel):
    """Configuração da tela do modelo (não secreta)."""

    # coordenadas do eixo: ponto de cada tipo de peça (AXIS_Z_RULE)
    axis_z_rule: dict[str, str]


@router.get("/viewer-config", response_model=ViewerConfigOut)
async def viewer_config(request: Request, _user: CurrentUser) -> ViewerConfigOut:
    settings: Settings = request.app.state.settings
    return ViewerConfigOut(axis_z_rule=settings.axis_z_rules)
