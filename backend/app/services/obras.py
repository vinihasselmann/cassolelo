"""Cadastro de obras e vínculo com o arquivo do modelo no Docs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, delete, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.aps import data_management as dm
from app.aps.client import ApsClient
from app.models import (
    Mark,
    ModelVersion,
    Obra,
    ObraParam,
    Orphan,
    ParamDef,
    ParamValue,
    PieceUnit,
    PieceValue,
    User,
)
from app.models.enums import Role
from app.services import audit
from app.services.errors import ConflictError, ForbiddenError, NotFoundError, ValidationError

SUPPORTED_FILE_TYPES = frozenset({"rvt", "nwd", "ifc"})


@dataclass(frozen=True)
class AccLink:
    hub_id: str
    project_id: str
    folder_id: str
    item_id: str


def is_supported(file_type: str | None) -> bool:
    return (file_type or "").lower() in SUPPORTED_FILE_TYPES


async def _validated_item_name(aps: ApsClient, link: AccLink) -> str:
    """Confere no Docs que o item existe e é .rvt/.nwd/.ifc; devolve o nome do arquivo."""
    item = await dm.get_item(aps, link.project_id, link.item_id)
    if not is_supported(item.file_type):
        raise ValidationError(
            f"O arquivo '{item.name}' não é um modelo suportado (.rvt, .nwd ou .ifc)."
        )
    return item.name


async def _ensure_code_free(session: AsyncSession, code: str, exclude_id: int | None) -> None:
    stmt = select(Obra.id).where(Obra.code == code)
    if exclude_id is not None:
        stmt = stmt.where(Obra.id != exclude_id)
    if await session.scalar(stmt) is not None:
        raise ConflictError(f"Já existe uma obra com o código '{code}'.")


class FileInUseError(ConflictError):
    code = "file_in_use"


async def _ensure_file_free(session: AsyncSession, item_id: str, exclude_id: int | None) -> None:
    """Uma obra = um arquivo do Docs. As versões do Docs são únicas no app: uma segunda
    obra no mesmo arquivo ficaria sem versões, sem aviso. Vale também para obra inativa
    (as versões continuam com ela)."""
    stmt = select(Obra).where(Obra.acc_item_id == item_id)
    if exclude_id is not None:
        stmt = stmt.where(Obra.id != exclude_id)
    other = await session.scalar(stmt.limit(1))
    if other is not None:
        state = "" if other.active else " (inativa)"
        raise FileInUseError(
            f"Este arquivo do Docs já está vinculado à obra {other.code} — {other.name}"
            f"{state}. Use essa obra ou escolha outro arquivo."
        )


async def get_obra(session: AsyncSession, obra_id: int) -> Obra:
    obra = await session.get(Obra, obra_id)
    if obra is None:
        raise NotFoundError("Obra não encontrada.")
    return obra


async def create_obra(
    session: AsyncSession, aps: ApsClient, *, code: str, name: str, link: AccLink, actor: User
) -> Obra:
    code, name = code.strip(), name.strip()
    await _ensure_code_free(session, code, None)
    await _ensure_file_free(session, link.item_id, None)
    item_name = await _validated_item_name(aps, link)
    obra = Obra(
        code=code,
        name=name,
        acc_hub_id=link.hub_id,
        acc_project_id=link.project_id,
        acc_folder_id=link.folder_id,
        acc_item_id=link.item_id,
        acc_item_name=item_name,
        created_by=actor.id,
        updated_by=actor.id,
    )
    session.add(obra)
    await session.flush()
    await audit.record(session, "obra", obra.id, "create", None, audit.snapshot(obra), actor)
    return obra


async def update_obra(
    session: AsyncSession,
    aps: ApsClient,
    obra: Obra,
    *,
    actor: User,
    code: str | None = None,
    name: str | None = None,
    link: AccLink | None = None,
    active: bool | None = None,
) -> Obra:
    before = audit.snapshot(obra)
    if active is not None:
        obra.active = active
    if code is not None and code.strip() != obra.code:
        await _ensure_code_free(session, code.strip(), obra.id)
        obra.code = code.strip()
    if name is not None:
        obra.name = name.strip()
    if link is not None and link.item_id != obra.acc_item_id:
        await _ensure_file_free(session, link.item_id, obra.id)
        has_versions = await session.scalar(select(exists().where(ModelVersion.obra_id == obra.id)))
        if has_versions:
            raise ConflictError(
                "Esta obra já tem versões sincronizadas; não é possível trocar o arquivo do "
                "modelo. Crie uma nova obra para o outro arquivo."
            )
    if link is not None:
        obra.acc_item_name = await _validated_item_name(aps, link)
        obra.acc_hub_id, obra.acc_project_id = link.hub_id, link.project_id
        obra.acc_folder_id, obra.acc_item_id = link.folder_id, link.item_id
    if session.is_modified(obra):
        obra.updated_by = actor.id
        await session.flush()
        await audit.record(session, "obra", obra.id, "update", before, audit.snapshot(obra), actor)
    return obra


# --------------------------------------------------------------------------- exclusão


@dataclass(frozen=True)
class DeletePreview:
    """O que some junto com a obra. `filled_values` conta valores preenchidos pela fábrica
    (por marca e por peça; valor nulo = apagado, não conta)."""

    versions: int
    marks: int
    units: int
    filled_values: int

    @property
    def has_values(self) -> bool:
        return self.filled_values > 0


async def delete_preview(session: AsyncSession, obra: Obra) -> DeletePreview:
    marks_q = select(Mark.id).where(Mark.obra_id == obra.id)
    units_q = select(PieceUnit.id).where(PieceUnit.obra_id == obra.id)

    async def count(stmt: Select[Any]) -> int:
        return int(await session.scalar(stmt) or 0)

    def filled(col: Any) -> Any:  # JSONB: valor apagado pode ser NULL ou o null do JSON
        return col.is_not(None) & (func.jsonb_typeof(col) != "null")

    mark_values = await count(
        select(func.count())
        .select_from(ParamValue)
        .where(ParamValue.mark_id.in_(marks_q), filled(ParamValue.value))
    )
    piece_values = await count(
        select(func.count())
        .select_from(PieceValue)
        .where(PieceValue.unit_id.in_(units_q), filled(PieceValue.value))
    )
    return DeletePreview(
        versions=await count(
            select(func.count()).select_from(ModelVersion).where(ModelVersion.obra_id == obra.id)
        ),
        marks=await count(select(func.count()).select_from(Mark).where(Mark.obra_id == obra.id)),
        units=await count(
            select(func.count()).select_from(PieceUnit).where(PieceUnit.obra_id == obra.id)
        ),
        filled_values=mark_values + piece_values,
    )


async def delete_obra(session: AsyncSession, obra: Obra, *, actor: User) -> DeletePreview:
    """Exclui a obra e tudo que é dela (para corrigir um cadastro errado).

    Obra com valores preenchidos pela fábrica só o admin exclui (decisão de 2026-11-17):
    nada some em silêncio — o retrato da obra e as contagens vão para o audit_log.
    Os parâmetros da biblioteca (scope global) ficam; só sai a inclusão deles na obra."""
    preview = await delete_preview(session, obra)
    if preview.has_values and actor.role != Role.ADMIN:
        raise ForbiddenError(
            f"A obra {obra.code} tem {preview.filled_values} valor(es) preenchido(s) pela "
            "fábrica. Só um administrador pode excluí-la."
        )
    before = audit.snapshot(obra)
    marks_q = select(Mark.id).where(Mark.obra_id == obra.id)
    units_q = select(PieceUnit.id).where(PieceUnit.obra_id == obra.id)
    obra_defs_q = select(ParamDef.id).where(ParamDef.obra_id == obra.id)
    # Ordem pelas FKs RESTRICT: valores → órfãs → versões (CASCADE: elementos, props,
    # ligações, relatórios) → unidades → marcas → parâmetros da obra → obra.
    await session.execute(delete(PieceValue).where(PieceValue.unit_id.in_(units_q)))
    await session.execute(delete(ParamValue).where(ParamValue.mark_id.in_(marks_q)))
    await session.execute(delete(Orphan).where(Orphan.mark_id.in_(marks_q)))
    await session.execute(delete(ModelVersion).where(ModelVersion.obra_id == obra.id))
    await session.execute(delete(PieceUnit).where(PieceUnit.obra_id == obra.id))
    await session.execute(delete(Mark).where(Mark.obra_id == obra.id))
    await session.execute(delete(ObraParam).where(ObraParam.obra_id == obra.id))
    await session.execute(delete(ObraParam).where(ObraParam.def_id.in_(obra_defs_q)))
    await session.execute(delete(ParamDef).where(ParamDef.obra_id == obra.id))
    obra_id = obra.id
    await session.delete(obra)
    await session.flush()
    before["deleted"] = {
        "versions": preview.versions,
        "marks": preview.marks,
        "units": preview.units,
        "filled_values": preview.filled_values,
    }
    await audit.record(session, "obra", obra_id, "delete", before, None, actor)
    return preview
