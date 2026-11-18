from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Request, status
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import EDITOR_ROLES, SYNC_ROLES, ApsDep, QueueDep
from app.api.obra_guard import require_file_available
from app.api.schemas import ModelVersionOut, ObraCreate, ObraOut, ObraUpdate, SyncOut
from app.aps.client import ApsClient
from app.aps.errors import ApsError
from app.auth import CurrentUser, Role, require_role
from app.config import Settings
from app.db import SessionDep
from app.models import ModelVersion, Obra, User
from app.models.enums import AccFileState, OrphanStatus, ParamType, VersionStatus
from app.services import mark_batch, mark_rule, mark_values, review
from app.services import obras as obras_service
from app.services import param_defs as param_defs_service
from app.services import versions as versions_service
from app.services import webhooks as webhooks_service
from app.services.obras import AccLink

log = logging.getLogger("app.api.obras")

# Obra com o arquivo excluído no Docs fica bloqueada (só editar/excluir).
router = APIRouter(prefix="/obras", tags=["obras"], dependencies=[Depends(require_file_available)])

Editor = Annotated[User, Depends(require_role(*EDITOR_ROLES))]
Syncer = Annotated[User, Depends(require_role(*SYNC_ROLES))]
ParamEditor = Annotated[User, Depends(require_role(Role.FABRICA, Role.ADMIN))]


@router.get("", response_model=list[ObraOut])
async def list_obras(session: SessionDep, _user: CurrentUser) -> list[Obra]:
    return list(await session.scalars(select(Obra).order_by(Obra.code)))


@router.get("/{obra_id}", response_model=ObraOut)
async def get_obra(obra_id: int, session: SessionDep, _user: CurrentUser) -> Obra:
    return await obras_service.get_obra(session, obra_id)


@router.post("", response_model=ObraOut, status_code=status.HTTP_201_CREATED)
async def create_obra(
    body: ObraCreate,
    request: Request,
    session: SessionDep,
    aps: ApsDep,
    user: Editor,
    background: BackgroundTasks,
) -> Obra:
    obra = await obras_service.create_obra(
        session,
        aps,
        code=body.code,
        name=body.name,
        link=AccLink(**body.acc.model_dump()),
        actor=user,
    )
    await session.commit()
    settings: Settings = request.app.state.settings
    if settings.webhook_callback_url:
        background.add_task(_register_hooks, aps, obra, settings.webhook_callback_url)
    return obra


async def _register_hooks(aps: ApsClient, obra: Obra, callback_url: str) -> None:
    """Registro automático dos webhooks da obra (falha não desfaz o cadastro:
    a verificação periódica cobre, e dá para registrar depois pelo CLI)."""
    try:
        await webhooks_service.register_obra_hooks(aps, obra, callback_url)
        log.info("Webhooks registrados para a obra %s", obra.id)
    except (ApsError, ValueError):
        log.exception("Falha ao registrar webhooks da obra %s", obra.id)


@router.patch("/{obra_id}", response_model=ObraOut)
async def update_obra(
    obra_id: int, body: ObraUpdate, session: SessionDep, aps: ApsDep, user: Editor
) -> Obra:
    obra = await obras_service.get_obra(session, obra_id)
    await obras_service.update_obra(
        session,
        aps,
        obra,
        actor=user,
        code=body.code,
        name=body.name,
        link=AccLink(**body.acc.model_dump()) if body.acc else None,
        active=body.active,
    )
    await session.commit()
    await session.refresh(obra)
    return obra


class DeletePreviewOut(BaseModel):
    versions: int
    marks: int
    units: int
    filled_values: int
    admin_only: bool  # com valores preenchidos, só o admin exclui


def _preview_out(p: obras_service.DeletePreview) -> DeletePreviewOut:
    return DeletePreviewOut(
        versions=p.versions,
        marks=p.marks,
        units=p.units,
        filled_values=p.filled_values,
        admin_only=p.has_values,
    )


@router.get("/{obra_id}/delete-preview", response_model=DeletePreviewOut)
async def delete_preview(obra_id: int, session: SessionDep, _user: Editor) -> DeletePreviewOut:
    obra = await obras_service.get_obra(session, obra_id)
    return _preview_out(await obras_service.delete_preview(session, obra))


@router.delete("/{obra_id}", response_model=DeletePreviewOut)
async def delete_obra(
    obra_id: int,
    request: Request,
    session: SessionDep,
    aps: ApsDep,
    user: Editor,
    background: BackgroundTasks,
) -> DeletePreviewOut:
    obra = await obras_service.get_obra(session, obra_id)
    hooks_ref = Obra(id=obra.id)  # só o id importa para achar os hooks
    folder = obra.acc_folder_id
    preview = await obras_service.delete_obra(session, obra, actor=user)
    await session.commit()
    settings: Settings = request.app.state.settings
    # Obras da mesma pasta dividem o hook (find_obra resolve pela pasta + arquivo):
    # só remove quando nenhuma outra obra usa a pasta.
    folder_in_use = folder is not None and (
        await session.scalar(select(Obra.id).where(Obra.acc_folder_id == folder).limit(1))
        is not None
    )
    if settings.webhook_callback_url and not folder_in_use:
        background.add_task(_delete_hooks, aps, hooks_ref)
    return _preview_out(preview)


async def _delete_hooks(aps: ApsClient, obra: Obra) -> None:
    """Remove os webhooks da obra excluída. Falha não desfaz a exclusão: o webhook
    órfão chega sem obra e é ignorado; o CLI reregistra/limpa depois."""
    try:
        deleted = await webhooks_service.delete_obra_hooks(aps, obra)
        log.info("Webhooks da obra excluída %s removidos: %d", obra.id, len(deleted))
    except ApsError:
        log.exception("Falha ao remover webhooks da obra excluída %s", obra.id)


class MarkRuleOut(BaseModel):
    """Regra de identificação das peças da obra (o que vale agora)."""

    mark_property_names: list[str]
    category_property_names: list[str]
    custom_marks: bool  # False = padrão do servidor
    custom_categories: bool
    default_mark_property_names: list[str]
    default_category_property_names: list[str]
    # montagens (.nwd/.rvt com vínculos): categorias do corpo; null = modo desligado
    piece_category_names: list[str] | None
    default_piece_category_names: list[str]


class MarkRuleIn(BaseModel):
    """null = voltar ao padrão do servidor."""

    mark_property_names: list[str] | None
    category_property_names: list[str] | None = None
    piece_category_names: list[str] | None = None  # null = sem modo montagens


class MarkRuleUpdateOut(MarkRuleOut):
    changed: bool
    reprocess_version_id: int | None  # versão ativa reprocessada com a regra nova
    reprocess_version_number: int | None
    enqueued: bool


def _rule_out(obra: Obra, settings: Settings) -> dict[str, Any]:
    rule = mark_rule.effective_rule(obra, settings)
    return {
        "mark_property_names": rule.mark_names,
        "category_property_names": rule.category_names,
        "custom_marks": rule.custom_marks,
        "custom_categories": rule.custom_categories,
        "default_mark_property_names": settings.mark_property_list,
        "default_category_property_names": settings.category_property_list,
        "piece_category_names": rule.piece_categories,
        "default_piece_category_names": settings.piece_category_list,
    }


@router.get("/{obra_id}/mark-rule", response_model=MarkRuleOut)
async def get_mark_rule(
    obra_id: int, request: Request, session: SessionDep, _user: CurrentUser
) -> MarkRuleOut:
    obra = await obras_service.get_obra(session, obra_id)
    return MarkRuleOut(**_rule_out(obra, request.app.state.settings))


@router.put("/{obra_id}/mark-rule", response_model=MarkRuleUpdateOut)
async def put_mark_rule(
    obra_id: int,
    body: MarkRuleIn,
    request: Request,
    session: SessionDep,
    queue: QueueDep,
    user: CurrentUser,
) -> MarkRuleUpdateOut:
    """Todos os papéis podem definir a regra (decisão de 2026-11-13). Se mudou, a versão
    ativa é reprocessada; marcas com valores que somem viram órfãs."""
    update = await mark_rule.update_rule(
        session,
        obra_id,
        body.mark_property_names,
        body.category_property_names,
        user,
        piece_categories=body.piece_category_names,
    )
    version = await mark_rule.latest_ready_version(session, obra_id) if update.changed else None
    await session.commit()
    enqueued = await mark_rule.enqueue_reprocess(queue, version.id, user.id) if version else False
    return MarkRuleUpdateOut(
        **_rule_out(update.obra, request.app.state.settings),
        changed=update.changed,
        reprocess_version_id=version.id if version else None,
        reprocess_version_number=version.version_number if version else None,
        enqueued=enqueued,
    )


class ObraParamOut(BaseModel):
    obra_id: int
    def_id: int
    in_obra: bool
    changed: bool  # False: já estava assim


@router.post("/{obra_id}/params/{def_id}", response_model=ObraParamOut)
async def include_obra_param(
    obra_id: int, def_id: int, session: SessionDep, user: ParamEditor
) -> ObraParamOut:
    """Inclui um parâmetro da biblioteca nesta obra (os valores antigos, se houver, voltam)."""
    changed = await param_defs_service.include_param(session, obra_id, def_id, user)
    await session.commit()
    return ObraParamOut(obra_id=obra_id, def_id=def_id, in_obra=True, changed=changed)


@router.delete("/{obra_id}/params/{def_id}", response_model=ObraParamOut)
async def exclude_obra_param(
    obra_id: int, def_id: int, session: SessionDep, user: ParamEditor
) -> ObraParamOut:
    """Retira um parâmetro da biblioteca desta obra. Os valores ficam guardados."""
    await obras_service.get_obra(session, obra_id)
    changed = await param_defs_service.exclude_param(session, obra_id, def_id, user)
    await session.commit()
    return ObraParamOut(obra_id=obra_id, def_id=def_id, in_obra=False, changed=changed)


@router.get("/{obra_id}/versions", response_model=list[ModelVersionOut])
async def list_versions(
    obra_id: int, session: SessionDep, _user: CurrentUser
) -> list[ModelVersionOut]:
    rows = await versions_service.list_versions(session, obra_id)
    return [_version_out(v) for v in rows]


def _version_out(v: ModelVersion) -> ModelVersionOut:
    return ModelVersionOut(
        id=v.id,
        version_number=v.version_number,
        status=VersionStatus(v.status),
        published_by=v.published_by,
        published_at=v.published_at,
        comment=v.comment,
        error=v.error,
        has_urn=v.urn is not None,
        urn=v.urn,
    )


@router.post("/{obra_id}/sync", response_model=SyncOut)
async def sync(
    obra_id: int, session: SessionDep, aps: ApsDep, queue: QueueDep, user: Syncer
) -> SyncOut:
    result = await versions_service.sync_versions(session, aps, queue, obra_id, user)
    return SyncOut(
        total_in_docs=result.total_in_docs,
        created=len(result.created_ids),
        ready=result.ready,
        translating=result.translating,
        no_translation=result.no_translation,
        failed=result.failed,
        enqueued=result.enqueued,
        enqueue_failed=result.enqueue_failed,
        deleted=result.deleted,
        file_state=AccFileState(result.file_state),
    )


# ------------------------------------------------------------------ valores por marca (6.2)


class FieldValueOut(BaseModel):
    def_id: int
    name: str
    type: ParamType
    unit: str | None
    required: bool
    options: list[str] | None
    value: Any
    row_version: int | None  # devolver no PUT (nulo = ainda não havia valor)
    updated_at: datetime | None
    updated_by_name: str | None


class MarkInfoOut(BaseModel):
    id: int
    code: str
    category: str
    review_status: str = "ok"  # "review": mudou na última versão (Fase 7.2)
    review_note: str | None = None


class MarkValuesOut(BaseModel):
    mark: MarkInfoOut
    values: list[FieldValueOut]
    last_change_by: str | None
    last_change_at: datetime | None


class ValueChangeIn(BaseModel):
    def_id: int
    value: Any = None
    row_version: int | None = None


class MarkValuesIn(BaseModel):
    changes: list[ValueChangeIn]


class HistoryOut(BaseModel):
    at: datetime
    user_name: str | None
    action: str
    param: str
    def_id: int | None
    before: Any
    after: Any
    batch_id: UUID | None


def _values_out(mv: mark_values.MarkValues) -> MarkValuesOut:
    return MarkValuesOut(
        mark=MarkInfoOut(
            id=mv.mark.id,
            code=mv.mark.code,
            category=mv.mark.category,
            review_status=mv.mark.review_status,
            review_note=mv.mark.review_note,
        ),
        values=[
            FieldValueOut(
                def_id=f.param.id,
                name=f.param.name,
                type=ParamType(f.param.type),
                unit=f.param.unit,
                required=f.param.required,
                options=f.param.options,
                value=f.value,
                row_version=f.row_version,
                updated_at=f.updated_at,
                updated_by_name=f.updated_by_name,
            )
            for f in mv.fields
        ],
        last_change_by=mv.last_change_by,
        last_change_at=mv.last_change_at,
    )


@router.get("/{obra_id}/marks/{mark_id}/values", response_model=MarkValuesOut)
async def get_mark_values(
    obra_id: int, mark_id: int, session: SessionDep, _user: CurrentUser
) -> MarkValuesOut:
    """Parâmetros da fábrica que se aplicam à marca, com valor e row_version."""
    return _values_out(await mark_values.get_values(session, obra_id, mark_id))


@router.put("/{obra_id}/marks/{mark_id}/values", response_model=MarkValuesOut)
async def put_mark_values(
    obra_id: int, mark_id: int, body: MarkValuesIn, session: SessionDep, user: ParamEditor
) -> MarkValuesOut:
    """Grava só os campos alterados (tudo ou nada). 409 `stale` se outro usuário salvou antes."""
    changes = [mark_values.Change(c.def_id, c.value, c.row_version) for c in body.changes]
    await mark_values.save_values(session, obra_id, mark_id, changes, user)
    await session.commit()
    return _values_out(await mark_values.get_values(session, obra_id, mark_id))


@router.get("/{obra_id}/marks/{mark_id}/history", response_model=list[HistoryOut])
async def get_mark_history(
    obra_id: int, mark_id: int, session: SessionDep, _user: CurrentUser
) -> list[HistoryOut]:
    """Alterações dos parâmetros da fábrica desta marca (mais recentes primeiro)."""
    entries = await mark_values.history(session, obra_id, mark_id)
    return [HistoryOut(**e.__dict__) for e in entries]


# ------------------------------------------------------------------ edição em lote (6.3)


class BatchIn(BaseModel):
    mark_ids: list[int]
    # def_id -> novo valor (nulo/vazio apaga no modo overwrite)
    changes: dict[int, Any] = {}
    mode: mark_batch.BatchMode = mark_batch.BatchMode.OVERWRITE


class BatchFieldOut(BaseModel):
    def_id: int
    name: str
    type: ParamType
    unit: str | None
    required: bool
    options: list[str] | None
    applies_to: int
    filled: int
    mixed: bool
    common_value: Any


class BatchChangeOut(BaseModel):
    def_id: int
    applies_to: int
    to_change: int
    other_value: int


class BatchPreviewOut(BaseModel):
    marks: int
    categories: list[str]
    fields: list[BatchFieldOut]
    changes: list[BatchChangeOut]
    marks_to_change: int
    marks_to_change_overwrite: int
    marks_to_change_only_empty: int
    marks_with_other_value: int


class BatchApplyOut(BaseModel):
    batch_id: UUID | None
    marks_changed: int
    fields_changed: int


@router.post("/{obra_id}/marks/batch-preview", response_model=BatchPreviewOut)
async def batch_preview(
    obra_id: int, body: BatchIn, session: SessionDep, _user: CurrentUser
) -> BatchPreviewOut:
    """Resumo dos campos da seleção (valor comum ou misto) e o efeito das mudanças."""
    p = await mark_batch.preview(session, obra_id, body.mark_ids, body.changes, body.mode)
    return BatchPreviewOut(
        marks=p.marks,
        categories=p.categories,
        fields=[
            BatchFieldOut(
                def_id=f.param.id,
                name=f.param.name,
                type=ParamType(f.param.type),
                unit=f.param.unit,
                required=f.param.required,
                options=f.param.options,
                applies_to=f.applies_to,
                filled=f.filled,
                mixed=f.mixed,
                common_value=f.common_value,
            )
            for f in p.fields
        ],
        changes=[BatchChangeOut(**c.__dict__) for c in p.changes],
        marks_to_change=p.marks_to_change,
        marks_to_change_overwrite=p.marks_to_change_overwrite,
        marks_to_change_only_empty=p.marks_to_change_only_empty,
        marks_with_other_value=p.marks_with_other_value,
    )


@router.post("/{obra_id}/marks/batch-apply", response_model=BatchApplyOut)
async def batch_apply(
    obra_id: int, body: BatchIn, session: SessionDep, user: ParamEditor
) -> BatchApplyOut:
    """Grava o lote numa transação (batch_id na auditoria). Desfazer: POST /batches/{id}/undo."""
    r = await mark_batch.apply(session, obra_id, body.mark_ids, body.changes, body.mode, user)
    await session.commit()
    return BatchApplyOut(**r.__dict__)


# ------------------------------------------------------------------ órfãs (7.2)


class OrphanValueOut(BaseModel):
    def_id: int
    name: str
    type: ParamType
    value: Any


class OrphanOut(BaseModel):
    id: int
    status: OrphanStatus
    mark_id: int
    code: str
    category: str
    since_version_id: int
    since_version_number: int
    relinked_to: int | None
    relinked_to_code: str | None
    created_at: datetime
    updated_at: datetime
    values: list[OrphanValueOut]


@router.get("/{obra_id}/orphans", response_model=list[OrphanOut])
async def list_orphans(
    obra_id: int,
    session: SessionDep,
    _user: CurrentUser,
    status: Literal["open", "relinked", "archived", "returned", "all"] = "open",
) -> list[OrphanOut]:
    """Marcas que sumiram do modelo com valores da fábrica (padrão: só as abertas)."""
    await obras_service.get_obra(session, obra_id)
    wanted = None if status == "all" else OrphanStatus(status)
    rows = await review.list_orphans(session, obra_id, wanted)
    return [
        OrphanOut(
            **{k: v for k, v in o.__dict__.items() if k != "values"},
            values=[OrphanValueOut(**v.__dict__) for v in o.values],
        )
        for o in rows
    ]
