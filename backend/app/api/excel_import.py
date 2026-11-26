"""Importar valores pelo Excel (fábrica e admin). Regras em app/services/excel_import.py.

O arquivo vai no corpo da requisição (binário, sem multipart), nas duas chamadas: a prévia
não guarda nada no servidor e o apply recalcula tudo, conferindo o `fingerprint` da prévia.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from app.api.obra_access import OBRA_ROUTER_DEPS
from app.auth import Role, require_role
from app.db import SessionDep
from app.models import User
from app.services import excel_import, plannix_import
from app.services.errors import ValidationError

router = APIRouter(prefix="/obras", tags=["import"], dependencies=OBRA_ROUTER_DEPS)

Importer = Annotated[User, Depends(require_role(Role.FABRICA, Role.ADMIN))]

MAX_LISTED = 500  # linhas de detalhe devolvidas (os totais contam tudo)


class IssueOut(BaseModel):
    sheet: str
    row: int | None
    column: str | None
    message: str


class ChangeOut(BaseModel):
    sheet: str
    row: int
    target: str
    category: str
    param: str
    old: Any
    new: Any


class ParamSummaryOut(BaseModel):
    def_id: int
    name: str
    level: str
    fills: int
    changes: int


class PlannixMarkOut(BaseModel):
    code: str
    plannix: int  # linhas da marca no Plannix (sem as recusadas)
    model: int  # peças da marca na versão ativa


class PlannixOutsideOut(BaseModel):
    code: str
    rows: int


class PlannixOut(BaseModel):
    """Só na planilha do Plannix (plannix_import)."""

    rows: int  # linhas de peça lidas (sem as recusadas)
    rejected: int  # peças recusadas na produção (ignoradas)
    linked: int  # linhas ligadas a uma peça do app
    new_links: int  # Códigos do Plannix guardados agora
    leftovers: int  # linhas sem peça no modelo
    new_params: list[str]  # parâmetros a criar na biblioteca
    check_marks: list[PlannixMarkOut]  # quantidade diferente: conferir
    outside_model: list[PlannixOutsideOut]  # marcas que não estão no modelo


class ImportPreviewOut(BaseModel):
    obra_code: str
    file_version: str | None
    marks_rows: int
    pieces_rows: int
    fills: int
    changes: int
    unchanged: int
    errors: list[IssueOut]
    warnings: list[IssueOut]
    ignored_columns: list[str]
    params: list[ParamSummaryOut]
    fill_items: list[ChangeOut]  # até MAX_LISTED
    change_items: list[ChangeOut]
    fingerprint: str
    clears: int = 0  # alterações que apagam o valor (só no Plannix)
    plannix: PlannixOut | None = None


class ImportApplyOut(BaseModel):
    batch_id: UUID | None  # para o "Desfazer"
    marks_changed: int
    units_changed: int
    fields_changed: int
    skipped_changes: int  # alterações não gravadas (sem "também alterar")
    errors: int  # linhas recusadas


async def read_file(request: Request) -> bytes:
    """Corpo da requisição com limite (o nginx também limita)."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > excel_import.MAX_BYTES:
        raise ValidationError("Arquivo grande demais (máximo 5 MB).")
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > excel_import.MAX_BYTES:
            raise ValidationError("Arquivo grande demais (máximo 5 MB).")
        chunks.append(chunk)
    content = b"".join(chunks)
    if not content:
        raise ValidationError("Envie o arquivo Excel (.xlsx).")
    return content


def _issues(items: list[excel_import.Issue]) -> list[IssueOut]:
    return [IssueOut(**i.__dict__) for i in items[:MAX_LISTED]]


def _changes(items: list[excel_import.Change]) -> list[ChangeOut]:
    return [
        ChangeOut(
            sheet=c.sheet,
            row=c.row,
            target=c.target,
            category=c.category,
            param=c.param,
            old=c.old,
            new=c.new,
        )
        for c in items[:MAX_LISTED]
    ]


@router.post("/{obra_id}/import-xlsx/preview", response_model=ImportPreviewOut)
async def import_preview(
    obra_id: int, request: Request, session: SessionDep, _user: Importer
) -> ImportPreviewOut:
    """O que o arquivo muda (nada é gravado)."""
    plan = await excel_import.build_plan(session, obra_id, await read_file(request))
    return ImportPreviewOut(
        obra_code=plan.obra_code,
        file_version=plan.file_version,
        marks_rows=plan.marks_rows,
        pieces_rows=plan.pieces_rows,
        fills=len(plan.fills),
        changes=len(plan.changes),
        unchanged=plan.unchanged,
        errors=_issues(plan.errors),
        warnings=_issues(plan.warnings),
        ignored_columns=plan.ignored_columns,
        params=[ParamSummaryOut(**p.__dict__) for p in plan.params],
        fill_items=_changes(plan.fills),
        change_items=_changes(plan.changes),
        fingerprint=plan.fingerprint,
        clears=sum(1 for c in plan.changes if c.new is None),
        plannix=_plannix(plan.plannix),
    )


def _plannix(info: plannix_import.PlannixInfo | None) -> PlannixOut | None:
    if info is None:
        return None
    return PlannixOut(
        rows=info.rows,
        rejected=info.rejected,
        linked=info.linked,
        new_links=len(info.new_links),
        leftovers=info.leftovers,
        new_params=info.new_params,
        check_marks=[PlannixMarkOut(**m.__dict__) for m in info.check_marks[:MAX_LISTED]],
        outside_model=[
            PlannixOutsideOut(code=c, rows=n) for c, n in info.outside_model[:MAX_LISTED]
        ],
    )


@router.post("/{obra_id}/import-xlsx/apply", response_model=ImportApplyOut)
async def import_apply(
    obra_id: int,
    request: Request,
    session: SessionDep,
    user: Importer,
    fingerprint: Annotated[str, Query(min_length=1, max_length=64)],
    overwrite: bool = False,
) -> ImportApplyOut:
    """Grava os preenchimentos (e, com overwrite, as alterações) num lote só. A planilha do
    Plannix sempre sobrescreve (e célula vazia apaga): `overwrite` não vale para ela."""
    plan, result = await excel_import.apply(
        session,
        obra_id,
        await read_file(request),
        overwrite=overwrite,
        fingerprint=fingerprint,
        actor=user,
    )
    await session.commit()
    return ImportApplyOut(
        batch_id=result.batch_id,
        marks_changed=result.marks_changed,
        units_changed=result.units_changed,
        fields_changed=result.fields_changed,
        # o Plannix sobrescreve sempre
        skipped_changes=0 if overwrite or plan.plannix else len(plan.changes),
        errors=len(plan.errors),
    )
