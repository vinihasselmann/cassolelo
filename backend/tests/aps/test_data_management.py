from __future__ import annotations

import respx

from app.aps import data_management as dm
from app.aps.auth import TOKEN_PATH
from app.aps.client import ApsClient
from app.aps.schemas import Folder, Item
from tests.aps.conftest import BASE, fixture

HUB = "b.00000000-0000-0000-0000-000000000001"
PROJECT = "b.11111111-1111-1111-1111-111111111111"
FOLDER = "urn:adsk.wipprod:fs.folder:co.PROJECTFILES"
ITEM = "urn:adsk.wipprod:dm.lineage:LINEAGE_RVT"


def setup_token() -> None:
    respx.post(f"{BASE}{TOKEN_PATH}").respond(200, json=fixture("token.json"))


@respx.mock
async def test_list_hubs(aps: ApsClient) -> None:
    setup_token()
    respx.get(f"{BASE}/project/v1/hubs").respond(200, json=fixture("hubs.json"))
    hubs = await dm.list_hubs(aps)
    assert [(h.id, h.name, h.region) for h in hubs] == [(HUB, "Cassol (sanitizado)", "US")]


@respx.mock
async def test_list_projects_paginated(aps: ApsClient) -> None:
    setup_token()
    url = f"{BASE}/project/v1/hubs/{HUB}/projects"
    respx.get(url, params={"page[number]": "1"}).respond(200, json=fixture("projects_page2.json"))
    respx.get(url).respond(200, json=fixture("projects_page1.json"))
    projects = await dm.list_projects(aps, HUB)
    assert [p.name for p in projects] == ["OBRA TESTE 001", "OBRA TESTE 002"]


@respx.mock
async def test_top_folders_and_contents(aps: ApsClient) -> None:
    setup_token()
    respx.get(f"{BASE}/project/v1/hubs/{HUB}/projects/{PROJECT}/topFolders").respond(
        200, json=fixture("top_folders.json")
    )
    respx.get(f"{BASE}/data/v1/projects/{PROJECT}/folders/{FOLDER}/contents").respond(
        200, json=fixture("folder_contents.json")
    )
    tops = await dm.list_top_folders(aps, HUB, PROJECT)
    assert tops[0] == Folder(id=FOLDER, name="Project Files")
    entries = await dm.list_folder_contents(aps, PROJECT, FOLDER)
    assert [type(e) for e in entries] == [Folder, Item, Item, Item]
    items = [e for e in entries if isinstance(e, Item)]
    assert [i.file_type for i in items] == ["rvt", "ifc", "pdf"]


@respx.mock
async def test_get_item_and_versions_sorted_desc(aps: ApsClient) -> None:
    setup_token()
    respx.get(f"{BASE}/data/v1/projects/{PROJECT}/items/{ITEM}").respond(
        200, json=fixture("item.json")
    )
    respx.get(f"{BASE}/data/v1/projects/{PROJECT}/items/{ITEM}/versions").respond(
        200, json=fixture("versions.json")
    )
    item = await dm.get_item(aps, PROJECT, ITEM)
    assert item.name == "OBRA-001-PRE.rvt"
    versions = await dm.list_versions(aps, PROJECT, ITEM)
    assert [v.number for v in versions] == [2, 1]
    v2, v1 = versions
    assert v2.create_user_name == "Usuário Projetos"
    assert v2.create_time is not None and v2.create_time.year == 2026
    assert v2.derivative_id is not None and v1.derivative_id is None


def test_seg_encodes_query_chars_but_keeps_colons() -> None:
    assert dm.seg("urn:adsk.wipprod:fs.file:vf.X?version=2") == (
        "urn:adsk.wipprod:fs.file:vf.X%3Fversion%3D2"
    )
