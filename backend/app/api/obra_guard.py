"""Bloqueio de obras cujo arquivo foi excluído no Docs.

Com o arquivo excluído (ou sumido) a obra fica bloqueada: só se lista, edita, exclui e
sincroniza (para perceber uma restauração). O resto responde 409. Os avisos em tempo real
(/events) continuam, para as telas abertas saberem que a obra foi bloqueada.

Aplicado como dependência de router: acha a obra pelo parâmetro da rota.
"""

from __future__ import annotations

import re

from fastapi import Request
from sqlalchemy import select

from app.api.obra_resolve import obra_id_from_path
from app.db import SessionDep
from app.models import Obra
from app.models.enums import AccFileState
from app.services.errors import ObraFileDeletedError

BLOCKED_MSG = {
    AccFileState.DELETED.value: (
        "O arquivo desta obra foi excluído do Autodesk Docs. A obra fica bloqueada: só é "
        "possível editá-la ou excluí-la. Se o arquivo for restaurado no Docs, ela é liberada."
    ),
    AccFileState.MISSING.value: (
        "O arquivo desta obra não foi encontrado no Autodesk Docs. A obra fica bloqueada: "
        "só é possível editá-la ou excluí-la."
    ),
}

# Rotas de /obras que continuam liberadas com o arquivo excluído: listar, ver, editar,
# excluir (e a prévia da exclusão) e "Sincronizar agora" (percebe a restauração).
ALLOWED = re.compile(r"^/api/obras(/[^/]+(/(delete-preview|sync))?)?/?$")


async def require_file_available(request: Request, session: SessionDep) -> None:
    if ALLOWED.match(request.url.path):
        return
    obra_id = await obra_id_from_path(session, request.path_params)
    if obra_id is None:
        return  # a rota responde o próprio 404
    state = await session.scalar(select(Obra.acc_file_state).where(Obra.id == obra_id))
    if state is not None and state != AccFileState.OK.value:
        raise ObraFileDeletedError(BLOCKED_MSG[state], file_state=state)
