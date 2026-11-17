"""Parâmetros POR PEÇA (P2): unidades de peça, valores, lote e histórico.

Leitura: todos os papéis. Gravação: fábrica e admin. Desfazer um lote: POST
/batches/{id}/undo (o mesmo dos lotes por marca; o serviço identifica o tipo).
Fila de unidades órfãs (P5): GET /obras/{o}/unit-orphans; religar e arquivar.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth import CurrentUser, Role, require_role
from app.db import SessionDep
from app.models import Mark, ParamDef, User
from app.models.enums import LinkMethod, ParamType, UnitStatus
from app.services import piece_values, unit_orphans
from app.services.mark_batch import BatchMode

router = APIRouter(prefix="/obras", tags=["units"])

ParamEditor = Annotated[User, Depends(require_role(Role.FABRICA, Role.ADMIN))]


class PieceParamOut(BaseModel):
    def_id: int
    name: str
    type: ParamType
    unit: str | None
    required: bool
    options: list[str] | None


class UnitValueOut(BaseModel):
    def_id: int
    value: Any
    row_version: int | None  # devolver no PUT (nulo = ainda não havia valor)
    updated_at: datetime | None
    updated_by_name: str | None


class LinkedElementOut(BaseModel):
    element_id: int
    dbid: int  # para o 3D
    external_id: str | None
    level: str | None
    name: str | None
    method: LinkMethod  # "order" = ligada pela ordem: conferir


class UnitOut(BaseModel):
    id: int
    number: int
    label: str  # PP001-3
    status: UnitStatus  # linked | unlinked | orphan
    external_id: str | None  # chave da última ligação
    since_version_id: int | None
    element: LinkedElementOut | None  # na versão aberta (nulo = sem peça nela)
    values: list[UnitValueOut]


class UnitMarkOut(BaseModel):
    id: int
    code: str
    category: str


class MarkUnitsOut(BaseModel):
    mark: UnitMarkOut
    version_id: int | None  # versão usada para o elemento ligado
    params: list[PieceParamOut]  # parâmetros por peça desta marca (colunas)
    units: list[UnitOut]


class UnitDetailOut(BaseModel):
    mark: UnitMarkOut
    params: list[PieceParamOut]
    unit: UnitOut


class UnitChangeIn(BaseModel):
    def_id: int
    value: Any = None
    row_version: int | None = None


class UnitValuesIn(BaseModel):
    changes: list[UnitChangeIn]


class UnitHistoryOut(BaseModel):
    at: datetime
    user_name: str | None
    action: str
    param: str
    def_id: int | None
    before: Any
    after: Any
    batch_id: UUID | None


class UnitBatchIn(BaseModel):
    unit_ids: list[int]
    changes: dict[int, Any] = {}  # def_id -> novo valor (vazio apaga no modo overwrite)
    mode: BatchMode = BatchMode.OVERWRITE


class UnitBatchFieldOut(PieceParamOut):
    applies_to: int
    filled: int
    mixed: bool
    common_value: Any


class UnitBatchChangeOut(BaseModel):
    def_id: int
    applies_to: int
    to_change: int
    other_value: int


class UnitBatchPreviewOut(BaseModel):
    units: int
    marks: int
    categories: list[str]
    fields: list[UnitBatchFieldOut]
    changes: list[UnitBatchChangeOut]
    units_to_change: int
    units_to_change_overwrite: int
    units_to_change_only_empty: int
    units_with_other_value: int


class UnitBatchApplyOut(BaseModel):
    batch_id: UUID | None
    units_changed: int
    fields_changed: int


class UnitOrphanValueOut(BaseModel):
    def_id: int
    name: str
    type: ParamType
    value: Any


class UnitOrphanOut(BaseModel):
    id: int
    number: int
    label: str
    status: UnitStatus
    mark_id: int
    code: str
    category: str
    external_id: str | None
    since_version_id: int | None
    since_version_number: int | None
    mark_in_model: bool
    updated_at: datetime
    values: list[UnitOrphanValueOut]


class UnitRelinkIn(BaseModel):
    target_unit_id: int
    confirm: bool = False  # destino com valores: ele fica órfão


class UnitRelinkOut(BaseModel):
    unit_id: int
    label: str
    element_id: int
    dbid: int
    displaced_unit_id: int
    displaced_label: str
    displaced_status: UnitStatus


class UnitStatusOut(BaseModel):
    id: int
    label: str
    status: UnitStatus


def _param(p: ParamDef) -> PieceParamOut:
    return PieceParamOut(
        def_id=p.id,
        name=p.name,
        type=ParamType(p.type),
        unit=p.unit,
        required=p.required,
        options=p.options,
    )


def _mark(m: Mark) -> UnitMarkOut:
    return UnitMarkOut(id=m.id, code=m.code, category=m.category)


def _unit(row: piece_values.UnitRow) -> UnitOut:
    u = row.unit
    e = row.element
    return UnitOut(
        id=u.id,
        number=u.number,
        label=row.label,
        status=UnitStatus(u.status),
        external_id=u.external_id,
        since_version_id=u.since_version_id,
        element=LinkedElementOut(
            element_id=e.element_id,
            dbid=e.dbid,
            external_id=e.external_id,
            level=e.level,
            name=e.name,
            method=LinkMethod(e.method),
        )
        if e
        else None,
        values=[UnitValueOut(**f.__dict__) for f in row.values],
    )


@router.get("/{obra_id}/marks/{mark_id}/units", response_model=MarkUnitsOut)
async def list_mark_units(
    obra_id: int,
    mark_id: int,
    session: SessionDep,
    _user: CurrentUser,
    version_id: int | None = None,
) -> MarkUnitsOut:
    """Unidades da marca (inclusive órfãs e sem peça), com os valores por peça e o elemento
    ligado na versão aberta (padrão: a pronta mais recente)."""
    r = await piece_values.list_units(session, obra_id, mark_id, version_id)
    return MarkUnitsOut(
        mark=_mark(r.mark),
        version_id=r.version.id if r.version else None,
        params=[_param(p) for p in r.params],
        units=[_unit(u) for u in r.units],
    )


async def _detail(
    session: SessionDep, obra_id: int, unit_id: int, version_id: int | None
) -> UnitDetailOut:
    mark, params, row = await piece_values.unit_detail(session, obra_id, unit_id, version_id)
    return UnitDetailOut(mark=_mark(mark), params=[_param(p) for p in params], unit=_unit(row))


@router.get("/{obra_id}/units/{unit_id}", response_model=UnitDetailOut)
async def get_unit(
    obra_id: int,
    unit_id: int,
    session: SessionDep,
    _user: CurrentUser,
    version_id: int | None = None,
) -> UnitDetailOut:
    return await _detail(session, obra_id, unit_id, version_id)


@router.put("/{obra_id}/units/{unit_id}/values", response_model=UnitDetailOut)
async def put_unit_values(
    obra_id: int,
    unit_id: int,
    body: UnitValuesIn,
    session: SessionDep,
    user: ParamEditor,
    version_id: int | None = None,
) -> UnitDetailOut:
    """Grava só os campos alterados da peça (tudo ou nada). 409 `stale` se outro usuário
    salvou antes."""
    changes = [piece_values.Change(c.def_id, c.value, c.row_version) for c in body.changes]
    await piece_values.save_values(session, obra_id, unit_id, changes, user)
    await session.commit()
    return await _detail(session, obra_id, unit_id, version_id)


@router.get("/{obra_id}/units/{unit_id}/history", response_model=list[UnitHistoryOut])
async def get_unit_history(
    obra_id: int, unit_id: int, session: SessionDep, _user: CurrentUser
) -> list[UnitHistoryOut]:
    """Valores e ligações da peça ao modelo (mais recentes primeiro)."""
    entries = await piece_values.history(session, obra_id, unit_id)
    return [UnitHistoryOut(**e.__dict__) for e in entries]


@router.post("/{obra_id}/units/batch-preview", response_model=UnitBatchPreviewOut)
async def unit_batch_preview(
    obra_id: int, body: UnitBatchIn, session: SessionDep, _user: CurrentUser
) -> UnitBatchPreviewOut:
    """Resumo dos campos da seleção (valor comum ou misto) e o efeito de cada modo."""
    p = await piece_values.preview(session, obra_id, body.unit_ids, body.changes, body.mode)
    return UnitBatchPreviewOut(
        units=p.units,
        marks=p.marks,
        categories=p.categories,
        fields=[
            UnitBatchFieldOut(
                **_param(f.param).model_dump(),
                applies_to=f.applies_to,
                filled=f.filled,
                mixed=f.mixed,
                common_value=f.common_value,
            )
            for f in p.fields
        ],
        changes=[UnitBatchChangeOut(**c.__dict__) for c in p.changes],
        units_to_change=p.units_to_change,
        units_to_change_overwrite=p.units_to_change_overwrite,
        units_to_change_only_empty=p.units_to_change_only_empty,
        units_with_other_value=p.units_with_other_value,
    )


@router.post("/{obra_id}/units/batch-apply", response_model=UnitBatchApplyOut)
async def unit_batch_apply(
    obra_id: int, body: UnitBatchIn, session: SessionDep, user: ParamEditor
) -> UnitBatchApplyOut:
    """Grava o lote numa transação. Desfazer: POST /batches/{batch_id}/undo."""
    r = await piece_values.apply(session, obra_id, body.unit_ids, body.changes, body.mode, user)
    await session.commit()
    return UnitBatchApplyOut(**r.__dict__)


# ------------------------------------------------------------------ unidades órfãs (P5)


@router.get("/{obra_id}/unit-orphans", response_model=list[UnitOrphanOut])
async def list_unit_orphans(
    obra_id: int, session: SessionDep, _user: CurrentUser, archived: bool = False
) -> list[UnitOrphanOut]:
    """Unidades com valores por peça que ficaram sem peça no modelo (padrão: as abertas;
    `archived=true` traz também as arquivadas)."""
    statuses = (UnitStatus.ORPHAN, UnitStatus.ARCHIVED) if archived else (UnitStatus.ORPHAN,)
    rows = await unit_orphans.list_orphans(session, obra_id, statuses)
    return [
        UnitOrphanOut(
            **{k: v for k, v in o.__dict__.items() if k != "values"},
            values=[UnitOrphanValueOut(**v.__dict__) for v in o.values],
        )
        for o in rows
    ]


@router.post("/{obra_id}/units/{unit_id}/relink", response_model=UnitRelinkOut)
async def relink_unit(
    obra_id: int, unit_id: int, body: UnitRelinkIn, session: SessionDep, user: ParamEditor
) -> UnitRelinkOut:
    """Religa a unidade órfã à peça de outra unidade da mesma marca (versão ativa). 409
    `unit_relink_conflict` se a de destino tem valores (reenviar com confirm=true)."""
    r = await unit_orphans.relink(
        session, obra_id, unit_id, body.target_unit_id, body.confirm, user
    )
    await session.commit()
    return UnitRelinkOut(**r.__dict__)


@router.post("/{obra_id}/units/{unit_id}/archive", response_model=UnitStatusOut)
async def archive_unit(
    obra_id: int, unit_id: int, session: SessionDep, user: ParamEditor
) -> UnitStatusOut:
    """Tira a unidade da fila de órfãs. Os valores continuam guardados."""
    unit, label = await unit_orphans.archive(session, obra_id, unit_id, user)
    await session.commit()
    return UnitStatusOut(id=unit.id, label=label, status=UnitStatus(unit.status))
