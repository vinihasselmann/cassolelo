"""3.2 · Validação de marcas: relatório (puro), gravação no process_version e API."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.aps.client import ApsClient
from app.aps.schemas import PropertyObject, TreeNode
from app.models import ModelVersion, Obra, User, VersionReport
from app.models.enums import Role
from app.services.extraction import ExtractedElement, extract_elements
from app.services.mark_validation import build_report, to_mm
from app.services.processing import ProcessingConfig, process_version
from tests.apsfakes import Sleeps, mock_model, mock_token, model_fixture
from tests.conftest import as_user

DIMS = ["Comprimento", "Largura", "Altura"]
CONFIG = ProcessingConfig(
    mark_names=["Marca", "Mark"], category_names=["Category"], dimension_names=DIMS
)


def _el(
    dbid: int, mark: str | None, cat: str = "Structural Columns", **dims: str
) -> ExtractedElement:
    return ExtractedElement(
        dbid=dbid,
        external_id=f"ext-{dbid}",
        name=f"Peça {dbid}",
        category=cat,
        mark_raw=mark,
        mark_code=mark.upper() if mark else None,
        props={"Dimensões": dims},
    )


def _planted() -> list[ExtractedElement]:
    tree = [
        TreeNode.model_validate(o) for o in model_fixture("validacao", "tree")["data"]["objects"]
    ]
    props = [
        PropertyObject.model_validate(p)
        for p in model_fixture("validacao", "properties")["data"]["collection"]
    ]
    return extract_elements(tree, props, CONFIG.mark_names, CONFIG.category_names)


# --------------------------------------------------------------------------- relatório (puro)


def test_two_pp001_with_different_sections_raise_alert() -> None:
    report = build_report(1, _planted(), DIMS, 5.0)
    (alert,) = report["inconsistent"]
    assert (alert["mark"], alert["category"], alert["pieces"]) == ("PP001", "Structural Columns", 2)
    (diff,) = alert["differences"]  # Largura e Comprimento iguais; só a Altura diverge
    assert diff["property"] == "Altura" and diff["diff_mm"] == 100.0
    assert {(v["value"], tuple(v["dbids"])) for v in diff["values"]} == {
        ("40.0 cm", (10,)),
        ("50.0 cm", (11,)),
    }


def test_piece_without_mark_is_listed() -> None:
    report = build_report(1, _planted(), DIMS, 5.0)
    assert report["without_mark"] == [
        {
            "dbid": 30,
            "external_id": "val-0030",
            "category": "Structural Columns",
            "name": "Pilar pré-moldado [30]",
        }
    ]


def test_totals_by_category() -> None:
    totals = build_report(1, _planted(), DIMS, 5.0)["totals"]
    assert (totals["pieces"], totals["marks"], totals["without_mark"]) == (7, 3, 1)
    assert totals["inconsistent_marks"] == 1
    assert totals["by_category"] == [
        {"category": "Structural Columns", "pieces": 5, "marks": 2, "without_mark": 1},
        {"category": "Structural Framing", "pieces": 2, "marks": 1, "without_mark": 0},
    ]


def test_tolerance_is_configurable() -> None:
    # PP002: 600.0 cm x 600.3 cm = 3 mm (dentro de 5 mm; fora de 2 mm)
    pieces = [_el(1, "PP002", Comprimento="600.0 cm"), _el(2, "PP002", Comprimento="600.3 cm")]
    assert build_report(1, pieces, DIMS, 5.0)["inconsistent"] == []
    (alert,) = build_report(1, pieces, DIMS, 2.0)["inconsistent"]
    assert alert["differences"][0]["diff_mm"] == 3.0


def test_same_length_in_different_units_is_consistent() -> None:
    pieces = [
        _el(1, "V-01", Comprimento="6000 mm"),
        _el(2, "V-01", Comprimento="6,0 m"),
        _el(3, "V-01", Comprimento="600 cm"),
    ]
    assert build_report(1, pieces, DIMS, 5.0)["inconsistent"] == []


def test_non_numeric_values_compared_as_text() -> None:
    pieces = [_el(1, "P-1", Largura="2' 6\""), _el(2, "P-1", Largura="2' 8\"")]
    (alert,) = build_report(1, pieces, DIMS, 5.0)["inconsistent"]
    assert alert["differences"][0]["diff_mm"] is None
    same = [_el(1, "P-1", Largura="2' 6\""), _el(2, "P-1", Largura=" 2' 6\"")]
    assert build_report(1, same, DIMS, 5.0)["inconsistent"] == []


def test_same_mark_in_other_category_is_not_compared() -> None:
    pieces = [
        _el(1, "P-01", "Structural Columns", Altura="40 cm"),
        _el(2, "P-01", "Floors", Altura="20 cm"),
    ]
    assert build_report(1, pieces, DIMS, 5.0)["inconsistent"] == []


def test_missing_dimension_is_not_an_alert() -> None:
    pieces = [_el(1, "P-1", Altura="40 cm"), _el(2, "P-1"), _el(3, "P-1", Altura="40 cm")]
    assert build_report(1, pieces, DIMS, 5.0)["inconsistent"] == []


@pytest.mark.parametrize(
    ("value", "mm"),
    [("600.0 cm", 6000.0), ("6,0 m", 6000.0), ("250", 250.0), ("12 MM", 12.0), ("abc", None)],
)
def test_to_mm(value: str, mm: float | None) -> None:
    assert to_mm(value) == mm


# --------------------------------------------------------------------------- banco e API


async def _processed(session: AsyncSession, aps: ApsClient, sleeps: Sleeps) -> ModelVersion:
    mock_token()
    mock_model("validacao", "dXJu")
    obra = Obra(code="OB-VAL", name="Obra validação")
    session.add(obra)
    await session.flush()
    v = ModelVersion(obra_id=obra.id, acc_version_id="urn:v:val", version_number=1, urn="dXJu")
    session.add(v)
    await session.flush()
    result = await process_version(session, aps, v.id, CONFIG, sleep=sleeps)
    assert result is not None and result.status == "ready"
    return v


async def _report(session: AsyncSession, version_id: int) -> dict[str, Any]:
    row = await session.scalar(select(VersionReport).where(VersionReport.version_id == version_id))
    assert row is not None
    return row.report


@respx.mock
async def test_process_version_saves_report(
    session: AsyncSession, aps: ApsClient, sleeps: Sleeps
) -> None:
    v = await _processed(session, aps, sleeps)
    report = await _report(session, v.id)
    assert report["version_id"] == v.id
    assert report["totals"]["inconsistent_marks"] == 1
    assert [e["dbid"] for e in report["without_mark"]] == [30]
    assert report["config"] == {"dimension_property_names": DIMS, "tolerance_mm": 5.0}


@respx.mock
async def test_reprocess_replaces_report(
    session: AsyncSession, aps: ApsClient, sleeps: Sleeps
) -> None:
    v = await _processed(session, aps, sleeps)
    strict = ProcessingConfig(**{**CONFIG.__dict__, "tolerance_mm": 1.0})
    await process_version(session, aps, v.id, strict, sleep=sleeps)
    count = await session.scalar(
        select(func.count()).select_from(VersionReport).where(VersionReport.version_id == v.id)
    )
    assert count == 1
    report = await _report(session, v.id)
    assert report["totals"]["inconsistent_marks"] == 2  # PP002 (3 mm) passa a alertar


@respx.mock
async def test_get_report_endpoint(
    session: AsyncSession,
    aps: ApsClient,
    sleeps: Sleeps,
    client: httpx.AsyncClient,
    users: dict[Role, User],
) -> None:
    v = await _processed(session, aps, sleeps)
    r = await client.get(f"/api/versions/{v.id}/report", headers=as_user(users[Role.PROJETOS]))
    assert r.status_code == 200
    body = r.json()
    assert body["version_id"] == v.id and body["status"] == "ready"
    assert body["report"]["inconsistent"][0]["mark"] == "PP001"
    assert body["report"]["without_mark"][0]["dbid"] == 30


async def test_report_not_ready_and_missing_version(
    session: AsyncSession, client: httpx.AsyncClient, users: dict[Role, User]
) -> None:
    obra = Obra(code="OB-NR", name="Sem relatório")
    session.add(obra)
    await session.flush()
    v = ModelVersion(obra_id=obra.id, acc_version_id="urn:v:nr", version_number=1, urn="x")
    session.add(v)
    await session.flush()
    headers = as_user(users[Role.LEITURA])

    r = await client.get(f"/api/versions/{v.id}/report", headers=headers)
    assert r.status_code == 404 and r.json()["code"] == "report_not_ready"
    r = await client.get("/api/versions/987654321/report", headers=headers)
    assert r.status_code == 404 and r.json()["code"] == "not_found"


async def test_report_requires_user(client: httpx.AsyncClient) -> None:
    r = await client.get("/api/versions/1/report")
    assert r.status_code == 401
