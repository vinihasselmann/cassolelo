"""Bloqueio de obras cujo arquivo foi excluído no Docs.

Com o arquivo excluído (ou sumido) a obra fica bloqueada: só se lista, edita, exclui e
sincroniza (para perceber uma restauração). O resto responde 409. Os avisos em tempo real
(/events) continuam, para as telas abertas saberem que a obra foi bloqueada.

Aplicado como dependência de router: acha a obra pelo parâmetro da rota.
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import Request
from sqlalchemy import select

from app.db import SessionDep
from app.models import Mark, ModelVersion, Obra, Orphan
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


def _int(params: dict[str, Any], name: str) -> int | None:
    raw = params.get(name)
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None  # a validação da própria rota responde 422


async def _obra_id(session: SessionDep, params: dict[str, Any]) -> int | None:
    if (obra_id := _int(params, "obra_id")) is not None:
        return obra_id
    if (version_id := _int(params, "version_id")) is not None:
        return await session.scalar(
            select(ModelVersion.obra_id).where(ModelVersion.id == version_id)
        )
    if (mark_id := _int(params, "mark_id")) is not None:
        return await session.scalar(select(Mark.obra_id).where(Mark.id == mark_id))
    if (orphan_id := _int(params, "orphan_id")) is not None:
        return await session.scalar(
            select(Mark.obra_id)
            .join(Orphan, Orphan.mark_id == Mark.id)
            .where(Orphan.id == orphan_id)
        )
    return None


async def require_file_available(request: Request, session: SessionDep) -> None:
    if ALLOWED.match(request.url.path):
        return
    obra_id = await _obra_id(session, dict(request.path_params))
    if obra_id is None:
        return  # a rota responde o próprio 404
    state = await session.scalar(select(Obra.acc_file_state).where(Obra.id == obra_id))
    if state is not None and state != AccFileState.OK.value:
        raise ObraFileDeletedError(BLOCKED_MSG[state], file_state=state)
