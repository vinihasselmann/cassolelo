"""Lotes de edição dos parâmetros da fábrica: desfazer (6.3)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth import Role, require_role
from app.db import SessionDep
from app.models import User
from app.services import mark_batch

router = APIRouter(prefix="/batches", tags=["batches"])

ParamEditor = Annotated[User, Depends(require_role(Role.FABRICA, Role.ADMIN))]


class UndoOut(BaseModel):
    batch_id: UUID  # lote do desfazer (também fica na auditoria)
    restored: int


@router.post("/{batch_id}/undo", response_model=UndoOut)
async def undo_batch(batch_id: UUID, session: SessionDep, user: ParamEditor) -> UndoOut:
    """Restaura os valores anteriores do lote. 409 se já desfeito ou alterado depois."""
    r = await mark_batch.undo(session, batch_id, user)
    await session.commit()
    return UndoOut(batch_id=r.batch_id, restored=r.restored)
