"""Revisão de marcas (Fase 7.2): "Manter valores"."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.obra_access import OBRA_ROUTER_DEPS
from app.auth import Role, require_role
from app.db import SessionDep
from app.models import User
from app.services import review

# Acesso por obra (11.2) e obra com o arquivo excluído no Docs bloqueada (só editar/excluir).
router = APIRouter(
    prefix="/marks",
    tags=["marks"],
    dependencies=OBRA_ROUTER_DEPS,
)

ParamEditor = Annotated[User, Depends(require_role(Role.FABRICA, Role.ADMIN))]


class MarkReviewOut(BaseModel):
    id: int
    code: str
    category: str
    review_status: str
    review_note: str | None


@router.post("/{mark_id}/review/keep", response_model=MarkReviewOut)
async def keep_values(mark_id: int, session: SessionDep, user: ParamEditor) -> MarkReviewOut:
    """ "Manter valores": a marca sai da revisão; os valores continuam. Auditado."""
    mark = await review.keep_values(session, mark_id, user)
    await session.commit()
    return MarkReviewOut(
        id=mark.id,
        code=mark.code,
        category=mark.category,
        review_status=mark.review_status,
        review_note=mark.review_note,
    )
