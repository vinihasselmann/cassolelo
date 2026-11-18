"""Modelos Pydantic das respostas do APS usadas pelo app."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ApsModel(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


def _attrs(d: dict[str, Any]) -> dict[str, Any]:
    attrs: dict[str, Any] = d.get("attributes") or {}
    return attrs


def _display_name(d: dict[str, Any]) -> str:
    a = _attrs(d)
    return str(a.get("displayName") or a.get("name") or d.get("id") or "")


def _extension_type(d: dict[str, Any]) -> str | None:
    ext = _attrs(d).get("extension") or {}
    value = ext.get("type")
    return str(value) if value else None


def _file_type(name: str) -> str | None:
    return name.rsplit(".", 1)[-1].lower() if "." in name else None


# --------------------------------------------------------------------------- Data Management


class Hub(ApsModel):
    id: str
    name: str
    region: str | None = None
    extension_type: str | None = None

    @classmethod
    def from_api(cls, d: dict[str, Any]) -> Hub:
        return cls(
            id=d["id"],
            name=_display_name(d),
            region=_attrs(d).get("region"),
            extension_type=_extension_type(d),
        )


class Project(ApsModel):
    id: str
    name: str
    extension_type: str | None = None

    @classmethod
    def from_api(cls, d: dict[str, Any]) -> Project:
        return cls(id=d["id"], name=_display_name(d), extension_type=_extension_type(d))


class Folder(ApsModel):
    kind: Literal["folder"] = "folder"
    id: str
    name: str
    hidden: bool = False

    @classmethod
    def from_api(cls, d: dict[str, Any]) -> Folder:
        return cls(id=d["id"], name=_display_name(d), hidden=bool(_attrs(d).get("hidden", False)))


class Item(ApsModel):
    kind: Literal["item"] = "item"
    id: str
    name: str
    file_type: str | None = None
    extension_type: str | None = None
    hidden: bool = False  # True = arquivo na lixeira do Docs (excluído)

    @classmethod
    def from_api(cls, d: dict[str, Any]) -> Item:
        name = _display_name(d)
        return cls(
            id=d["id"],
            name=name,
            file_type=_file_type(name),
            extension_type=_extension_type(d),
            hidden=bool(_attrs(d).get("hidden", False)),
        )


FolderEntry = Folder | Item


DELETED_VERSION_TYPE = "versions:autodesk.core:Deleted"


class Version(ApsModel):
    id: str
    number: int
    name: str
    file_type: str | None = None
    create_user_name: str | None = None
    create_time: datetime | None = None
    derivative_id: str | None = None
    comment: str | None = None
    # Excluir um arquivo no Docs cria uma versão do tipo "Deleted", sem derivativo, cujo
    # displayName é um GUID; o nome do arquivo fica em extension.data.originalName.
    is_deleted: bool = False

    @classmethod
    def from_api(cls, d: dict[str, Any]) -> Version:
        a = _attrs(d)
        rel = d.get("relationships") or {}
        deriv = ((rel.get("derivatives") or {}).get("data") or {}).get("id")
        is_deleted = _extension_type(d) == DELETED_VERSION_TYPE
        data = (a.get("extension") or {}).get("data") or {}
        original = data.get("originalName") if is_deleted else None
        name = str(original or a.get("displayName") or a.get("name") or "")
        return cls(
            id=d["id"],
            number=int(a.get("versionNumber") or 0),
            name=name,
            file_type=_file_type(name),
            create_user_name=a.get("createUserName") or a.get("lastModifiedUserName"),
            create_time=a.get("createTime") or a.get("lastModifiedTime"),
            derivative_id=deriv,
            comment=_version_comment(a),
            is_deleted=is_deleted,
        )


def _version_comment(attrs: dict[str, Any]) -> str | None:
    """Comentário da revisão. A chave exata no ACC ainda precisa ser confirmada
    com respostas reais (Fase 0); procuramos nos lugares conhecidos."""
    data = (attrs.get("extension") or {}).get("data") or {}
    for value in (data.get("versionComment"), data.get("comment"), attrs.get("comment")):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


# --------------------------------------------------------------------------- Model Derivative


class ManifestDerivative(ApsModel):
    output_type: str | None = Field(default=None, alias="outputType")
    status: str | None = None
    progress: str | None = None
    messages: list[dict[str, Any]] = Field(default_factory=list)


class Manifest(ApsModel):
    urn: str | None = None
    status: str
    progress: str | None = None
    region: str | None = None
    derivatives: list[ManifestDerivative] = Field(default_factory=list)

    @property
    def has_viewable(self) -> bool:
        return any((d.output_type or "").lower() in ("svf", "svf2") for d in self.derivatives)

    @property
    def is_ready(self) -> bool:
        return self.status == "success" and self.has_viewable

    @property
    def in_progress(self) -> bool:
        return self.status in ("pending", "inprogress")

    @property
    def messages(self) -> list[str]:
        return [str(m.get("message", "")) for d in self.derivatives for m in d.messages]


class ViewMeta(ApsModel):
    guid: str
    name: str | None = None
    role: str | None = None
    is_master_view: bool = Field(default=False, alias="isMasterView")


class PropertyObject(ApsModel):
    objectid: int
    name: str | None = None
    external_id: str | None = Field(default=None, alias="externalId")
    properties: dict[str, Any] = Field(default_factory=dict)


class TreeNode(ApsModel):
    objectid: int
    name: str | None = None
    objects: list[TreeNode] = Field(default_factory=list)
