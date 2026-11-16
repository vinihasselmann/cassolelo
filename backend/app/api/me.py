from __future__ import annotations

from fastapi import APIRouter, Request

from app.api.schemas import UserOut
from app.auth import CurrentUser

router = APIRouter(tags=["auth"])


class MeOut(UserOut):
    # o papel pode criar e editar filtros e esquemas de cores compartilhados
    # (SHARED_FILTER_ROLES); a tela esconde o "Compartilhar" sem isso
    can_share_filters: bool = False


@router.get("/me", response_model=MeOut)
async def me(user: CurrentUser, request: Request) -> MeOut:
    out = MeOut.model_validate(user)
    out.can_share_filters = user.role in request.app.state.settings.shared_filter_role_list
    return out
