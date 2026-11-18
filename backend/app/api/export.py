"""/api/obras/{id}/export.xlsx: marcas e peças da obra em Excel (Fase 9.1).

GET recebe os filtros da busca antiga; POST (F3) recebe o filtro da tela (regras do
motor + texto), para o Excel trazer a mesma lista."""

from __future__ import annotations

from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict

from app.api.obra_guard import require_file_available
from app.api.versions import parse_prop
from app.auth import CurrentUser
from app.db import SessionDep
from app.models import User
from app.services import export, filters, search

# Obra com o arquivo excluído no Docs fica bloqueada (só editar/excluir).
router = APIRouter(prefix="/obras", tags=["export"], dependencies=[Depends(require_file_available)])


@router.get("/{obra_id}/export.xlsx", response_class=Response)
async def export_xlsx(
    obra_id: int,
    request: Request,
    session: SessionDep,
    user: CurrentUser,
    version_id: int | None = None,
    q: str = "",
    category: Annotated[list[str], Query()] = [],  # noqa: B006 (padrão do FastAPI)
    level: Annotated[list[str], Query()] = [],  # noqa: B006
    prop: Annotated[list[str], Query(description="Nome=valor")] = [],  # noqa: B006
    missing: Annotated[str | None, Query(description="sem <parâmetro>")] = None,
    shortcut: search.Shortcut = search.Shortcut.ALL,
    order: Literal["asc", "desc"] = "asc",
) -> Response:
    """Uma linha por marca (mesmos filtros da busca; sem `version_id`, a versão ativa) e
    a lista de peças. Todos os papéis podem exportar."""
    params = search.SearchParams(
        q=q.strip(),
        categories=category,
        levels=level,
        props=[parse_prop(p) for p in prop],
        missing=missing.strip() if missing and missing.strip() else None,
        shortcut=shortcut,
        order=order,
    )
    return await _respond(request, session, obra_id, version_id, params, user)


class ExportInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version_id: int | None = None
    filter: filters.FilterDef | None = None  # regras e texto ("q") do filtro da tela
    order: Literal["asc", "desc"] = "asc"


@router.post("/{obra_id}/export.xlsx", response_class=Response)
async def export_xlsx_filtered(
    obra_id: int, body: ExportInput, request: Request, session: SessionDep, user: CurrentUser
) -> Response:
    """Excel com o filtro da tela: as marcas do resultado (como a lista à esquerda)."""
    timezone = request.app.state.settings.display_timezone
    params = search.SearchParams(
        order=body.order, definition=body.filter, today=filters.today(timezone)
    )
    return await _respond(request, session, obra_id, body.version_id, params, user)


async def _respond(
    request: Request,
    session: SessionDep,
    obra_id: int,
    version_id: int | None,
    params: search.SearchParams,
    user: User,
) -> Response:
    file = await export.build_workbook(
        session,
        obra_id,
        version_id,
        params,
        user,
        timezone=request.app.state.settings.display_timezone,
    )
    disposition = (
        f"attachment; filename=\"{file.filename}\"; filename*=UTF-8''{quote(file.filename)}"
    )
    return Response(
        content=file.content,
        media_type=export.XLSX,
        headers={
            "Content-Disposition": disposition,
            "Cache-Control": "no-store",
            "X-Export-Marks": str(file.marks),
            "X-Export-Pieces": str(file.pieces),
        },
    )
