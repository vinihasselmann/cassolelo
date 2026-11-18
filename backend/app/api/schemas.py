from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import AccFileState, Role, VersionStatus


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    role: Role


# --------------------------------------------------------------------------- ACC (navegação)


class AccHubOut(BaseModel):
    id: str
    name: str


class AccProjectOut(BaseModel):
    id: str
    name: str


class AccEntryOut(BaseModel):
    kind: Literal["folder", "item"]
    id: str
    name: str
    file_type: str | None = None
    supported: bool = False  # item .rvt/.nwd/.ifc


# --------------------------------------------------------------------------- Obras


class AccLinkIn(BaseModel):
    hub_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    folder_id: str = Field(min_length=1)
    item_id: str = Field(min_length=1)


class ObraCreate(BaseModel):
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=200)
    acc: AccLinkIn


class ObraUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=50)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    acc: AccLinkIn | None = None
    active: bool | None = None


class ObraOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    acc_hub_id: str | None
    acc_project_id: str | None
    acc_folder_id: str | None
    acc_item_id: str | None
    acc_item_name: str | None
    active: bool
    # "deleted"/"missing": arquivo excluído no Docs; a obra fica bloqueada (só editar/excluir)
    acc_file_state: AccFileState
    acc_file_state_at: datetime | None
    created_at: datetime
    updated_at: datetime


# --------------------------------------------------------------------------- Versões


class ModelVersionOut(BaseModel):
    id: int
    version_number: int
    status: VersionStatus
    published_by: str | None
    published_at: datetime | None
    comment: str | None
    error: str | None
    has_urn: bool
    urn: str | None  # derivativo (base64), usado pelo Viewer; não é segredo


class SyncOut(BaseModel):
    total_in_docs: int
    created: int
    ready: int  # convertidas pelo Docs, enviadas para processamento
    translating: int
    no_translation: int
    failed: int
    enqueued: int
    enqueue_failed: int
    deleted: int = 0  # versões "Deleted" novas (arquivo excluído no Docs)
    file_state: AccFileState = AccFileState.OK
