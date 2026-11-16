"""4.2 · GET /api/versions/{id}/marks e /elements/{dbid}."""

from __future__ import annotations

import httpx
import respx
from sqlalchemy.ext.asyncio import AsyncSession

from app.aps.client import ApsClient
from app.models import ModelVersion, Obra, User
from app.models.enums import Role
from app.services.processing import ProcessingConfig, process_version
from app.services.version_data import group_properties
from tests.apsfakes import Sleeps, mock_model, mock_token
from tests.conftest import as_user

CONFIG = ProcessingConfig(mark_names=["Marca", "Mark"], category_names=["Category"])


async def _processed(session: AsyncSession, aps: ApsClient, sleeps: Sleeps) -> ModelVersion:
    mock_token()
    mock_model("validacao", "dXJu")
    obra = Obra(code="OB-VD", name="Obra dados")
    session.add(obra)
    await session.flush()
    v = ModelVersion(obra_id=obra.id, acc_version_id="urn:v:vd", version_number=1, urn="dXJu")
    session.add(v)
    await session.flush()
    result = await process_version(session, aps, v.id, CONFIG, sleep=sleeps)
    assert result is not None and result.status == "ready"
    return v


@respx.mock
async def test_marks_with_counts_and_dbids(
    session: AsyncSession,
    aps: ApsClient,
    sleeps: Sleeps,
    client: httpx.AsyncClient,
    users: dict[Role, User],
) -> None:
    v = await _processed(session, aps, sleeps)
    r = await client.get(f"/api/versions/{v.id}/marks", headers=as_user(users[Role.FABRICA]))
    assert r.status_code == 200
    marks = [(m["code"], m["category"], m["count"], m["dbids"]) for m in r.json()]
    # ordenado por categoria e código; a peça sem Marca (30) não aparece
    assert marks == [
        ("PP001", "Structural Columns", 2, [10, 11]),
        ("PP002", "Structural Columns", 2, [12, 13]),
        ("V-01", "Structural Framing", 2, [20, 21]),
    ]
    assert all(isinstance(m["mark_id"], int) for m in r.json())


@respx.mock
async def test_element_with_mark_and_grouped_properties(
    session: AsyncSession,
    aps: ApsClient,
    sleeps: Sleeps,
    client: httpx.AsyncClient,
    users: dict[Role, User],
) -> None:
    v = await _processed(session, aps, sleeps)
    r = await client.get(f"/api/versions/{v.id}/elements/11", headers=as_user(users[Role.LEITURA]))
    assert r.status_code == 200
    body = r.json()
    assert (body["dbid"], body["external_id"], body["name"]) == (
        11,
        "val-0011",
        "Pilar pré-moldado [11]",
    )
    assert body["mark"]["code"] == "PP001" and body["mark"]["count"] == 2
    assert body["mark"]["dbids"] == [10, 11]
    assert [g["name"] for g in body["groups"]] == [
        "Dados de identidade",
        "Dimensões",
        "Other",
        "Restrições",
    ]
    dims = body["groups"][1]["properties"]
    assert dims == [
        {"name": "Altura", "value": "50.0 cm"},
        {"name": "Comprimento", "value": "600.0 cm"},
        {"name": "Largura", "value": "40.0 cm"},
    ]


@respx.mock
async def test_element_without_mark(
    session: AsyncSession,
    aps: ApsClient,
    sleeps: Sleeps,
    client: httpx.AsyncClient,
    users: dict[Role, User],
) -> None:
    v = await _processed(session, aps, sleeps)
    r = await client.get(f"/api/versions/{v.id}/elements/30", headers=as_user(users[Role.FABRICA]))
    assert r.status_code == 200
    assert r.json()["mark"] is None and r.json()["mark_raw"] is None


@respx.mock
async def test_missing_element_and_version(
    session: AsyncSession,
    aps: ApsClient,
    sleeps: Sleeps,
    client: httpx.AsyncClient,
    users: dict[Role, User],
) -> None:
    v = await _processed(session, aps, sleeps)
    h = as_user(users[Role.FABRICA])
    r = await client.get(f"/api/versions/{v.id}/elements/99999", headers=h)
    assert r.status_code == 404 and r.json()["code"] == "not_found"
    r = await client.get("/api/versions/987654321/marks", headers=h)
    assert r.status_code == 404


async def test_version_not_ready_is_409(
    session: AsyncSession, client: httpx.AsyncClient, users: dict[Role, User]
) -> None:
    obra = Obra(code="OB-NR2", name="x")
    session.add(obra)
    await session.flush()
    v = ModelVersion(
        obra_id=obra.id, acc_version_id="urn:v:nr2", version_number=1, status="processing"
    )
    session.add(v)
    await session.flush()
    h = as_user(users[Role.FABRICA])
    for path in (f"/api/versions/{v.id}/marks", f"/api/versions/{v.id}/elements/1"):
        r = await client.get(path, headers=h)
        assert r.status_code == 409 and r.json()["code"] == "version_not_ready"


async def test_endpoints_require_user(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/versions/1/marks")).status_code == 401
    assert (await client.get("/api/versions/1/elements/1")).status_code == 401


def test_group_properties_sorts_and_handles_loose_values() -> None:
    groups = group_properties(
        {"b": {"z": 1, "A": 2}, "Avulsa": "x", "a": {"k": [1, 2]}, "vazio": {}}
    )
    assert groups == [
        {"name": "a", "properties": [{"name": "k", "value": [1, 2]}]},
        {"name": "b", "properties": [{"name": "A", "value": 2}, {"name": "z", "value": 1}]},
        {"name": "Outros", "properties": [{"name": "Avulsa", "value": "x"}]},
    ]
