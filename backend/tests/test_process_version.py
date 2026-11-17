"""3.1 · process_version: elements + marks no banco, status, idempotência e falhas."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
import respx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.aps.client import ApsClient
from app.models import AuditLog, Element, Mark, ModelVersion, Obra, PieceUnit, PieceUnitLink
from app.services.processing import UNEXPECTED_MSG, ProcessingConfig, process_version
from app.workers import tasks
from tests.apsfakes import MD, MODEL_FORMATS, Sleeps, mock_model, mock_token, model_fixture
from tests.conftest import make_settings

CONFIG = ProcessingConfig(
    mark_names=["Marca", "Mark"],
    category_names=["Category", "Categoria", "IfcClass"],
    dimension_names=["Comprimento", "Largura", "Altura"],
)

# formato -> (elementos, sem marca, {(marca, categoria): nº de peças})
EXPECTED: dict[str, tuple[int, int, dict[tuple[str, str], int]]] = {
    "rvt": (
        7,
        1,
        {
            ("V-101", "Structural Framing"): 2,
            ("V-102", "Structural Framing"): 1,
            ("P-01", "Structural Columns"): 1,
            ("LA-01", "Floors"): 1,
            ("P-01", "Floors"): 1,
        },
    ),
    "nwd": (4, 1, {("V-101", "Structural Framing"): 2, ("P-01", "Structural Columns"): 1}),
    "ifc": (4, 1, {("V-201", "IfcBeam"): 2, ("P-201", "IfcColumn"): 1}),
}


async def _obra(session: AsyncSession, code: str = "OB-P") -> Obra:
    obra = Obra(code=code, name=f"Obra {code}")
    session.add(obra)
    await session.flush()
    return obra


async def _version(
    session: AsyncSession,
    obra: Obra,
    number: int = 1,
    urn: str = "dXJuOnJ2dA",
    status: str = "pending",
) -> ModelVersion:
    v = ModelVersion(
        obra_id=obra.id,
        acc_version_id=f"urn:v:{obra.code}:{number}:{urn}",
        version_number=number,
        urn=urn,
        status=status,
    )
    session.add(v)
    await session.flush()
    return v


async def _run(session: AsyncSession, aps: ApsClient, version_id: int, sleeps: Sleeps) -> Any:
    return await process_version(session, aps, version_id, CONFIG, sleep=sleeps)


async def _units(session: AsyncSession, obra_id: int) -> list[tuple[int, int, int]]:
    rows = await session.execute(
        select(PieceUnit.id, PieceUnit.mark_id, PieceUnit.number)
        .where(PieceUnit.obra_id == obra_id)
        .order_by(PieceUnit.id)
    )
    return [tuple(r) for r in rows]  # type: ignore[misc]


async def _marks(session: AsyncSession, obra_id: int) -> dict[tuple[str, str], int]:
    rows = await session.execute(
        select(Mark.code, Mark.category, Mark.id).where(Mark.obra_id == obra_id)
    )
    return {(r.code, r.category): r.id for r in rows}


async def _elements(session: AsyncSession, version_id: int) -> list[Element]:
    return list(
        await session.scalars(
            select(Element).where(Element.version_id == version_id).order_by(Element.dbid)
        )
    )


@pytest.mark.parametrize("fmt", MODEL_FORMATS)
@respx.mock
async def test_process_each_format(
    fmt: str, session: AsyncSession, aps: ApsClient, sleeps: Sleeps
) -> None:
    mock_token()
    urn = f"dXJu{fmt}"
    mock_model(fmt, urn)
    obra = await _obra(session)
    v = await _version(session, obra, urn=urn)

    result = await _run(session, aps, v.id, sleeps)

    n_elements, n_without, marks = EXPECTED[fmt]
    assert result.status == "ready" and result.error is None
    assert (result.elements, result.without_mark, result.marks) == (
        n_elements,
        n_without,
        len(marks),
    )
    assert result.marks_created == len(marks)
    await session.refresh(v)
    assert v.status == "ready" and v.error is None

    mark_ids = await _marks(session, obra.id)
    assert set(mark_ids) == set(marks)
    els = await _elements(session, v.id)
    assert len(els) == n_elements
    per_mark: dict[int, int] = {}
    for e in els:
        if e.mark_id is None:
            assert e.mark_raw is None
            continue
        per_mark[e.mark_id] = per_mark.get(e.mark_id, 0) + 1
    assert per_mark == {mark_ids[k]: n for k, n in marks.items()}

    # campos gravados do elemento: o primeiro da coleção de propriedades com externalId
    first = next(
        p
        for p in model_fixture(fmt, "properties")["data"]["collection"]
        if p["objectid"] == els[0].dbid
    )
    assert els[0].external_id == first["externalId"]
    assert els[0].name == first["name"]
    assert els[0].props == first["properties"]
    assert els[0].category is not None


@respx.mock
async def test_status_audit_and_mark_creation_logged(
    session: AsyncSession, aps: ApsClient, sleeps: Sleeps
) -> None:
    mock_token()
    mock_model("rvt", "dXJu")
    obra = await _obra(session)
    v = await _version(session, obra, urn="dXJu")
    await _run(session, aps, v.id, sleeps)

    actions = list(
        await session.scalars(
            select(AuditLog.action)
            .where(AuditLog.entity == "model_version", AuditLog.entity_id == str(v.id))
            .order_by(AuditLog.id)
        )
    )
    assert actions == ["process_start", "process_ready"]
    ready = await session.scalar(
        select(AuditLog).where(AuditLog.action == "process_ready", AuditLog.entity_id == str(v.id))
    )
    assert ready is not None and ready.before is not None and ready.after is not None
    assert ready.before["status"] == "processing" and ready.after["status"] == "ready"
    assert ready.after["elements"] == 7 and ready.after["marks_created"] == 5
    created = await session.scalar(
        select(func.count())
        .select_from(AuditLog)
        .where(AuditLog.entity == "mark", AuditLog.action == "create")
    )
    assert created == 5


@respx.mock
async def test_reprocess_is_idempotent(
    session: AsyncSession, aps: ApsClient, sleeps: Sleeps
) -> None:
    mock_token()
    mock_model("rvt", "dXJu")
    obra = await _obra(session)
    v = await _version(session, obra, urn="dXJu")

    await _run(session, aps, v.id, sleeps)
    marks_before = await _marks(session, obra.id)
    ids_before = {e.dbid: e.mark_id for e in await _elements(session, v.id)}
    units_before = await _units(session, obra.id)
    marked = sum(1 for m in ids_before.values() if m is not None)
    assert len(units_before) == marked  # uma unidade de peça por peça com marca

    again = await _run(session, aps, v.id, sleeps)
    assert again.status == "ready" and again.marks_created == 0
    assert await _marks(session, obra.id) == marks_before  # mesmas marcas, mesmos ids
    assert {e.dbid: e.mark_id for e in await _elements(session, v.id)} == ids_before
    total = await session.scalar(
        select(func.count()).select_from(Element).where(Element.version_id == v.id)
    )
    assert total == 7
    # reprocessar não duplica unidades nem ligações (unidades de peça, P1)
    assert await _units(session, obra.id) == units_before
    links = await session.scalar(
        select(func.count()).select_from(PieceUnitLink).where(PieceUnitLink.version_id == v.id)
    )
    assert links == marked


@respx.mock
async def test_marks_reused_across_versions_but_not_across_obras(
    session: AsyncSession, aps: ApsClient, sleeps: Sleeps
) -> None:
    mock_token()
    mock_model("rvt", "dXJu")
    obra = await _obra(session, "OB-A")
    v1 = await _version(session, obra, 1, urn="dXJu")
    v2 = await _version(session, obra, 2, urn="dXJu")
    other = await _obra(session, "OB-B")
    v_other = await _version(session, other, 1, urn="dXJu")

    await _run(session, aps, v1.id, sleeps)
    r2 = await _run(session, aps, v2.id, sleeps)
    r_other = await _run(session, aps, v_other.id, sleeps)

    assert r2.marks_created == 0  # mesma obra: reaproveita
    assert r_other.marks_created == 5  # outra obra: marcas próprias
    a, b = await _marks(session, obra.id), await _marks(session, other.id)
    assert set(a) == set(b) and not set(a.values()) & set(b.values())
    e1 = {e.dbid: e.mark_id for e in await _elements(session, v1.id)}
    e2 = {e.dbid: e.mark_id for e in await _elements(session, v2.id)}
    assert e1 == e2


@respx.mock
async def test_waits_on_202_and_uses_forceget_on_413(
    session: AsyncSession, aps: ApsClient, sleeps: Sleeps
) -> None:
    mock_token()
    routes = mock_model("ifc", "dXJu")
    props = model_fixture("ifc", "properties")
    routes["properties"].side_effect = [
        httpx.Response(202, json={"result": "success"}),
        httpx.Response(413),
        httpx.Response(200, json=props),
    ]
    obra = await _obra(session)
    v = await _version(session, obra, urn="dXJu")

    result = await _run(session, aps, v.id, sleeps)

    assert result.status == "ready" and result.elements == 4
    assert sleeps.calls  # esperou no 202
    last = routes["properties"].calls.last.request
    assert last.url.params.get("forceget") == "true"


@respx.mock
async def test_aps_failure_sets_failed_with_message(
    session: AsyncSession, aps: ApsClient, sleeps: Sleeps
) -> None:
    mock_token()
    routes = mock_model("rvt", "dXJu")
    routes["properties"].respond(404)
    obra = await _obra(session)
    v = await _version(session, obra, urn="dXJu")

    result = await _run(session, aps, v.id, sleeps)

    assert result.status == "failed"
    await session.refresh(v)
    assert v.status == "failed" and v.error is not None and "Não encontrado" in v.error
    assert await _elements(session, v.id) == []
    assert await _marks(session, obra.id) == {}
    actions = list(
        await session.scalars(
            select(AuditLog.action)
            .where(AuditLog.entity == "model_version", AuditLog.entity_id == str(v.id))
            .order_by(AuditLog.id)
        )
    )
    assert actions == ["process_start", "process_failed"]


@respx.mock
async def test_no_3d_view_fails(session: AsyncSession, aps: ApsClient, sleeps: Sleeps) -> None:
    mock_token()
    respx.get(f"{MD}/dXJu/metadata").respond(
        200, json={"data": {"metadata": [{"guid": "g", "role": "2d"}]}}
    )
    obra = await _obra(session)
    v = await _version(session, obra, urn="dXJu")
    result = await _run(session, aps, v.id, sleeps)
    assert result.status == "failed" and result.error == "O derivativo não tem vista 3D."


@respx.mock
async def test_failed_reprocess_keeps_previous_elements(
    session: AsyncSession, aps: ApsClient, sleeps: Sleeps
) -> None:
    mock_token()
    routes = mock_model("rvt", "dXJu")
    obra = await _obra(session)
    v = await _version(session, obra, urn="dXJu")
    await _run(session, aps, v.id, sleeps)

    routes["properties"].respond(404)
    result = await _run(session, aps, v.id, sleeps)
    assert result.status == "failed"
    assert len(await _elements(session, v.id)) == 7  # a falha desfaz a substituição


@respx.mock
async def test_unexpected_error_message_is_generic(
    session: AsyncSession, aps: ApsClient, sleeps: Sleeps, monkeypatch: pytest.MonkeyPatch
) -> None:
    mock_token()
    mock_model("rvt", "dXJu")
    obra = await _obra(session)
    v = await _version(session, obra, urn="dXJu")

    def boom(*_: object) -> list[object]:
        raise RuntimeError("detalhe interno")

    monkeypatch.setattr("app.services.processing.extract_elements", boom)
    result = await _run(session, aps, v.id, sleeps)
    assert result.status == "failed" and result.error == UNEXPECTED_MSG


@pytest.mark.parametrize("status", ["no_translation", "translating"])
@respx.mock  # sem rotas: qualquer chamada ao APS falharia
async def test_versions_not_ready_are_skipped(
    status: str, session: AsyncSession, aps: ApsClient, sleeps: Sleeps
) -> None:
    obra = await _obra(session)
    v = await _version(session, obra, status=status)
    assert await _run(session, aps, v.id, sleeps) is None
    await session.refresh(v)
    assert v.status == status


async def test_missing_version_is_ignored(
    session: AsyncSession, aps: ApsClient, sleeps: Sleeps
) -> None:
    assert await _run(session, aps, 987654321, sleeps) is None


@respx.mock
async def test_worker_job_uses_configured_mark_names(session: AsyncSession, aps: ApsClient) -> None:
    """O job lê MARK_PROPERTY_NAMES: com só "Mark", as marcas em "Marca" não contam."""
    mock_token()
    mock_model("rvt", "dXJu")
    obra = await _obra(session)
    v = await _version(session, obra, urn="dXJu")

    @asynccontextmanager
    async def maker() -> AsyncIterator[AsyncSession]:
        yield session

    ctx = {
        "sessionmaker": maker,
        "aps": aps,
        "queue": None,
        "settings": make_settings(mark_property_names="Mark"),
    }
    assert await tasks.process_version(ctx, v.id) == "ready"
    assert set(await _marks(session, obra.id)) == {("P-01", "Structural Columns")}
