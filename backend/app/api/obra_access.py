"""Acesso por obra (11.2): dependência de router.

Acha a obra pela rota (ou pela query das listas) e responde 404 se o usuário não a vê.
Vale para leitura e escrita. Corpos com `obra_id` (criar filtro, esquema, parâmetro) são
conferidos na rota com `obra_access.ensure_body_obra`; listas sem obra filtram com
`obra_access.visible_obra_ids`.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from app.api.obra_guard import require_file_available
from app.api.obra_resolve import obra_id_from_path, obra_ids_from_query
from app.auth.current import current_user
from app.db import SessionDep
from app.models import User
from app.services import obra_access


async def require_obra_access(
    request: Request, session: SessionDep, user: Annotated[User, Depends(current_user)]
) -> None:
    if obra_access.sees_all(user):
        return
    ids = obra_ids_from_query(request.query_params)
    obra_id = await obra_id_from_path(session, request.path_params)
    if obra_id is not None:
        ids.append(obra_id)
    for i in ids:
        await obra_access.ensure_visible(session, user, i)


# Routers das telas de uma obra: acesso (404) antes do bloqueio de arquivo excluído (409),
# para quem não vê a obra não saber nem que ela está bloqueada.
OBRA_ROUTER_DEPS = [Depends(require_obra_access), Depends(require_file_available)]
