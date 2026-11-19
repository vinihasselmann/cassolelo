"""Lotes de edição dos parâmetros da fábrica: desfazer (6.3; por peça desde o P2)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.obra_access import require_obra_access
from app.auth import Role, require_role
from app.db import SessionDep
from app.models import User
from app.services import mark_batch, piece_values
from app.services.errors import NotFoundError

# Acesso por obra (11.2): 404 nas obras que o usuário não vê.
router = APIRouter(prefix="/batches", tags=["batches"], dependencies=[Depends(require_obra_access)])

ParamEditor = Annotated[User, Depends(require_role(Role.FABRICA, Role.ADMIN))]


class UndoOut(BaseModel):
    batch_id: UUID  # lote do desfazer (também fica na auditoria)
    restored: int


@router.post("/{batch_id}/undo", response_model=UndoOut)
async def undo_batch(batch_id: UUID, session: SessionDep, user: ParamEditor) -> UndoOut:
    """Restaura os valores anteriores do lote (por marca, por peça ou os dois, como na
    importação do Excel). Tudo ou nada. 409 se já desfeito ou alterado depois."""
    results: list[mark_batch.UndoResult | piece_values.UndoResult] = []
    if await mark_batch.has_batch(session, batch_id):
        results.append(await mark_batch.undo(session, batch_id, user))
    if await piece_values.is_piece_batch(session, batch_id):
        results.append(await piece_values.undo(session, batch_id, user))
    if not results:
        raise NotFoundError("Lote não encontrado.")
    await session.commit()
    return UndoOut(batch_id=results[0].batch_id, restored=sum(r.restored for r in results))
