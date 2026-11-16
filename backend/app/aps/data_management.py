"""Data Management API (somente leitura)."""

from __future__ import annotations

from urllib.parse import quote

from app.aps.client import ApsClient
from app.aps.schemas import Folder, FolderEntry, Hub, Item, Project, Version


def seg(value: str) -> str:
    """Codifica um id para uso em segmento de caminho (mantém ':')."""
    return quote(value, safe=":")


async def list_hubs(c: ApsClient) -> list[Hub]:
    return [Hub.from_api(d) async for d in c.paginate("/project/v1/hubs")]


async def list_projects(c: ApsClient, hub_id: str) -> list[Project]:
    url = f"/project/v1/hubs/{seg(hub_id)}/projects"
    return [Project.from_api(d) async for d in c.paginate(url)]


async def list_top_folders(c: ApsClient, hub_id: str, project_id: str) -> list[Folder]:
    url = f"/project/v1/hubs/{seg(hub_id)}/projects/{seg(project_id)}/topFolders"
    return [Folder.from_api(d) async for d in c.paginate(url)]


async def list_folder_contents(c: ApsClient, project_id: str, folder_id: str) -> list[FolderEntry]:
    url = f"/data/v1/projects/{seg(project_id)}/folders/{seg(folder_id)}/contents"
    out: list[FolderEntry] = []
    async for d in c.paginate(url):
        if d.get("type") == "folders":
            out.append(Folder.from_api(d))
        elif d.get("type") == "items":
            out.append(Item.from_api(d))
    return out


async def get_item(c: ApsClient, project_id: str, item_id: str) -> Item:
    body = await c.get_json(f"/data/v1/projects/{seg(project_id)}/items/{seg(item_id)}")
    return Item.from_api(body["data"])


async def list_versions(c: ApsClient, project_id: str, item_id: str) -> list[Version]:
    """Versões do item, da mais recente para a mais antiga."""
    url = f"/data/v1/projects/{seg(project_id)}/items/{seg(item_id)}/versions"
    versions = [Version.from_api(d) async for d in c.paginate(url)]
    return sorted(versions, key=lambda v: v.number, reverse=True)
