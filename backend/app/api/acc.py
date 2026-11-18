"""Navegação no Autodesk Docs para vincular obras (somente leitura, via app/aps)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import EDITOR_ROLES, ApsDep
from app.api.schemas import AccEntryOut, AccHubOut, AccProjectOut
from app.aps import data_management as dm
from app.aps.schemas import Folder
from app.auth import require_role
from app.services.obras import is_supported

router = APIRouter(prefix="/acc", tags=["acc"], dependencies=[Depends(require_role(*EDITOR_ROLES))])


@router.get("/hubs", response_model=list[AccHubOut])
async def hubs(aps: ApsDep) -> list[AccHubOut]:
    return [AccHubOut(id=h.id, name=h.name) for h in await dm.list_hubs(aps)]


@router.get("/hubs/{hub_id}/projects", response_model=list[AccProjectOut])
async def projects(hub_id: str, aps: ApsDep) -> list[AccProjectOut]:
    items = await dm.list_projects(aps, hub_id)
    return sorted((AccProjectOut(id=p.id, name=p.name) for p in items), key=lambda p: p.name)


@router.get("/hubs/{hub_id}/projects/{project_id}/top-folders", response_model=list[AccEntryOut])
async def top_folders(hub_id: str, project_id: str, aps: ApsDep) -> list[AccEntryOut]:
    folders = await dm.list_top_folders(aps, hub_id, project_id)
    return [AccEntryOut(kind="folder", id=f.id, name=f.name) for f in folders if not f.hidden]


@router.get("/projects/{project_id}/folders/{folder_id}", response_model=list[AccEntryOut])
async def folder_contents(project_id: str, folder_id: str, aps: ApsDep) -> list[AccEntryOut]:
    entries = await dm.list_folder_contents(aps, project_id, folder_id)
    out = [
        AccEntryOut(kind="folder", id=e.id, name=e.name)
        if isinstance(e, Folder)
        else AccEntryOut(
            kind="item",
            id=e.id,
            name=e.name,
            file_type=e.file_type,
            supported=is_supported(e.file_type),
        )
        for e in entries
        if not e.hidden  # pasta oculta ou arquivo na lixeira do Docs
    ]
    return sorted(out, key=lambda e: (e.kind != "folder", e.name.casefold()))
