from __future__ import annotations

import httpx
import pytest
import respx

from app.models import User
from app.models.enums import Role
from tests.apsfakes import BASE, FOLDER, HUB, PROJECT, fixture, mock_token
from tests.conftest import as_user


@pytest.mark.parametrize("role", [Role.FABRICA, Role.LEITURA])
async def test_only_projetos_and_admin_browse_docs(
    client: httpx.AsyncClient, users: dict[Role, User], role: Role
) -> None:
    r = await client.get("/api/acc/hubs", headers=as_user(users[role]))
    assert r.status_code == 403
    assert r.json()["detail"] == "Seu papel não permite esta ação."


@respx.mock
async def test_hubs_and_projects(client: httpx.AsyncClient, users: dict[Role, User]) -> None:
    mock_token()
    respx.get(f"{BASE}/project/v1/hubs").respond(200, json=fixture("hubs.json"))
    url = f"{BASE}/project/v1/hubs/{HUB}/projects"
    respx.get(url, params={"page[number]": "1"}).respond(200, json=fixture("projects_page2.json"))
    respx.get(url).respond(200, json=fixture("projects_page1.json"))
    h = as_user(users[Role.PROJETOS])

    hubs = (await client.get("/api/acc/hubs", headers=h)).json()
    assert hubs == [{"id": HUB, "name": "Cassol (sanitizado)"}]
    projects = (await client.get(f"/api/acc/hubs/{HUB}/projects", headers=h)).json()
    assert [p["name"] for p in projects] == ["OBRA TESTE 001", "OBRA TESTE 002"]


@respx.mock
async def test_top_folders_and_folder_contents(
    client: httpx.AsyncClient, users: dict[Role, User]
) -> None:
    mock_token()
    respx.get(f"{BASE}/project/v1/hubs/{HUB}/projects/{PROJECT}/topFolders").respond(
        200, json=fixture("top_folders.json")
    )
    respx.get(f"{BASE}/data/v1/projects/{PROJECT}/folders/{FOLDER}/contents").respond(
        200, json=fixture("folder_contents.json")
    )
    h = as_user(users[Role.ADMIN])

    tops = await client.get(f"/api/acc/hubs/{HUB}/projects/{PROJECT}/top-folders", headers=h)
    assert [f["name"] for f in tops.json()] == ["Project Files", "Plans"]

    r = await client.get(f"/api/acc/projects/{PROJECT}/folders/{FOLDER}", headers=h)
    entries = r.json()
    assert [(e["kind"], e["name"], e["supported"]) for e in entries] == [
        ("folder", "Modelos", False),
        ("item", "OBRA-001-PRE.rvt", True),
        ("item", "OBRA-001.ifc", True),
        ("item", "Prancha-01.pdf", False),
    ]


@respx.mock
async def test_folder_id_with_colons_url_encoded(
    client: httpx.AsyncClient, users: dict[Role, User]
) -> None:
    mock_token()
    route = respx.get(f"{BASE}/data/v1/projects/{PROJECT}/folders/{FOLDER}/contents").respond(
        200, json={"data": []}
    )
    encoded = FOLDER.replace(":", "%3A")
    r = await client.get(
        f"/api/acc/projects/{PROJECT}/folders/{encoded}", headers=as_user(users[Role.ADMIN])
    )
    assert r.status_code == 200 and r.json() == []
    assert route.called


@pytest.mark.parametrize(
    ("aps_status", "status", "code", "text"),
    [
        (403, 403, "aps_forbidden", "Custom Integrations"),
        (404, 404, "aps_not_found", "Não encontrado"),
        (400, 502, "aps_error", "Falha ao consultar"),
    ],
)
@respx.mock
async def test_aps_errors_become_clear_messages(
    client: httpx.AsyncClient,
    users: dict[Role, User],
    aps_status: int,
    status: int,
    code: str,
    text: str,
) -> None:
    mock_token()
    respx.get(f"{BASE}/project/v1/hubs").respond(aps_status)
    r = await client.get("/api/acc/hubs", headers=as_user(users[Role.PROJETOS]))
    assert r.status_code == status
    assert r.json()["code"] == code
    assert text in r.json()["detail"]
    assert "FAKE-ACCESS-TOKEN" not in r.text
