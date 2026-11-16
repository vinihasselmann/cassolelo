"""Fila de órfãs (Fase 7.2): religar e arquivar. A lista fica em /obras/{id}/orphans."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth import Role, require_role
from app.db import SessionDep
from app.models import User
from app.services import review

router = APIRouter(prefix="/orphans", tags=["orphans"])

ParamEditor = Annotated[User, Depends(require_role(Role.FABRICA, Role.ADMIN))]


class RelinkIn(BaseModel):
    target_mark_id: int
    overwrite: bool = False  # sobrescrever valores diferentes já preenchidos no destino


class RelinkOut(BaseModel):
    orphan_id: int
    target_mark_id: int
    copied: list[str]
    skipped: list[str]
    batch_id: UUID


class OrphanStatusOut(BaseModel):
    id: int
    status: str


@router.post("/{orphan_id}/relink", response_model=RelinkOut)
async def relink(
    orphan_id: int, body: RelinkIn, session: SessionDep, user: ParamEditor
) -> RelinkOut:
    """Copia os valores da marca órfã para a marca de destino e fecha a órfã.
    409 `relink_conflict` (com `conflicts`) se o destino já tem outro valor."""
    r = await review.relink(session, orphan_id, body.target_mark_id, body.overwrite, user)
    await session.commit()
    return RelinkOut(**r.__dict__)


@router.post("/{orphan_id}/archive", response_model=OrphanStatusOut)
async def archive(orphan_id: int, session: SessionDep, user: ParamEditor) -> OrphanStatusOut:
    """Fecha a órfã sem copiar. Os valores continuam guardados na marca antiga."""
    orphan = await review.archive(session, orphan_id, user)
    await session.commit()
    return OrphanStatusOut(id=orphan.id, status=orphan.status)
