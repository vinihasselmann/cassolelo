"""2.4 · Versão sem conversão: os três casos do manifest + falha + timeout de 2 h."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import respx
from sqlalchemy.ext.asyncio import AsyncSession

from app.aps.client import ApsClient
from app.models import ModelVersion, Obra
from app.services.translation import (
    NO_TRANSLATION_MSG,
    PROCESS_VERSION_JOB,
    Outcome,
    check_translation,
    recheck_translating,
)
from app.services.versions import sync_versions
from tests.apsfakes import (
    BASE,
    FOLDER,
    HUB,
    ITEM,
    PROJECT,
    FakeQueue,
    fixture,
    mock_manifest,
    mock_token,
)

VERSIONS_URL = f"{BASE}/data/v1/projects/{PROJECT}/items/{ITEM}/versions"


async def _obra(session: AsyncSession) -> Obra:
    obra = Obra(
        code="OB-T",
        name="Obra tradução",
        acc_hub_id=HUB,
        acc_project_id=PROJECT,
        acc_folder_id=FOLDER,
        acc_item_id=ITEM,
    )
    session.add(obra)
    await session.flush()
    return obra


async def _version(
    session: AsyncSession, urn: str | None = "dXJu", status: str = "pending"
) -> ModelVersion:
    obra = await _obra(session)
    v = ModelVersion(
        obra_id=obra.id, acc_version_id=f"urn:v:{urn}", version_number=1, urn=urn, status=status
    )
    session.add(v)
    await session.flush()
    return v


@respx.mock
async def test_success_goes_to_processing(session: AsyncSession, aps: ApsClient) -> None:
    mock_token()
    mock_manifest("manifest_success.json")
    v = await _version(session)
    assert await check_translation(session, aps, v) is Outcome.READY
    assert v.status == "pending" and v.error is None


@respx.mock
async def test_in_progress_becomes_translating(session: AsyncSession, aps: ApsClient) -> None:
    mock_token()
    mock_manifest("manifest_inprogress.json")
    v = await _version(session)
    assert await check_translation(session, aps, v) is Outcome.IN_PROGRESS
    assert v.status == "translating"


@respx.mock  # sem rotas: qualquer chamada ao APS falharia com "not mocked"
async def test_without_derivative_is_no_translation(session: AsyncSession, aps: ApsClient) -> None:
    v = await _version(session, urn=None)
    assert await check_translation(session, aps, v) is Outcome.NO_TRANSLATION
    assert v.status == "no_translation"


@respx.mock
async def test_manifest_404_is_no_translation(session: AsyncSession, aps: ApsClient) -> None:
    mock_token()
    mock_manifest(status=404)
    v = await _version(session)
    assert await check_translation(session, aps, v) is Outcome.NO_TRANSLATION
    assert v.status == "no_translation"


@respx.mock
async def test_success_without_svf_is_no_translation(session: AsyncSession, aps: ApsClient) -> None:
    mock_token()
    body = fixture("manifest_success.json")
    body["derivatives"] = [{"outputType": "thumbnail"}]
    respx.get(url__regex=r".*/manifest$").respond(200, json=body)
    v = await _version(session)
    assert await check_translation(session, aps, v) is Outcome.NO_TRANSLATION


@respx.mock
async def test_failed_manifest_keeps_messages(session: AsyncSession, aps: ApsClient) -> None:
    mock_token()
    body = fixture("manifest_inprogress.json")
    body["status"] = "failed"
    body["derivatives"] = [{"outputType": "svf2", "messages": [{"message": "Arquivo corrompido"}]}]
    respx.get(url__regex=r".*/manifest$").respond(200, json=body)
    v = await _version(session)
    assert await check_translation(session, aps, v) is Outcome.FAILED
    assert v.status == "failed" and v.error is not None and "Arquivo corrompido" in v.error


@respx.mock
async def test_aps_error_keeps_translating_for_retry(session: AsyncSession, aps: ApsClient) -> None:
    mock_token()
    mock_manifest(status=503)
    v = await _version(session)
    assert await check_translation(session, aps, v) is Outcome.CHECK_ERROR
    assert v.status == "translating" and v.error is not None


@respx.mock
async def test_sync_three_cases_and_only_ready_is_enqueued(
    session: AsyncSession, aps: ApsClient, queue: FakeQueue
) -> None:
    mock_token()
    body = fixture("versions.json")  # v1 sem derivativo, v2 com derivativo
    v3 = {**body["data"][1], "id": body["data"][1]["id"].replace("version=2", "version=3")}
    v3["attributes"] = {**v3["attributes"], "versionNumber": 3}
    v3["relationships"] = {"derivatives": {"data": {"id": "VjM"}}}
    body["data"].append(v3)
    respx.get(VERSIONS_URL).respond(200, json=body)
    respx.get(url__regex=r".*/designdata/VjM/manifest$").respond(
        200, json=fixture("manifest_inprogress.json")
    )
    mock_manifest("manifest_success.json")
    obra = await _obra(session)

    result = await sync_versions(session, aps, queue, obra.id)
    assert (result.ready, result.translating, result.no_translation) == (1, 1, 1)
    statuses = {}
    for version_id in result.created_ids:
        v = await session.get(ModelVersion, version_id)
        assert v is not None
        statuses[v.version_number] = v.status
    assert statuses == {1: "no_translation", 2: "pending", 3: "translating"}
    v2_id = result.created_ids[1]
    assert queue.jobs == [(PROCESS_VERSION_JOB, (v2_id,), f"{PROCESS_VERSION_JOB}:{v2_id}")]


@respx.mock
async def test_recheck_moves_translating_to_ready(
    session: AsyncSession, aps: ApsClient, queue: FakeQueue
) -> None:
    mock_token()
    mock_manifest("manifest_success.json")
    v = await _version(session, status="translating")
    counts = await recheck_translating(session, aps, queue)
    assert counts["ready"] == 1
    assert v.status == "pending"
    assert [j[1] for j in queue.jobs] == [(v.id,)]


@respx.mock
async def test_recheck_gives_up_after_two_hours(
    session: AsyncSession, aps: ApsClient, queue: FakeQueue
) -> None:
    mock_token()
    mock_manifest("manifest_inprogress.json")
    v = await _version(session, status="translating")
    later = datetime.now(UTC) + timedelta(hours=2, minutes=1)
    counts = await recheck_translating(session, aps, queue, now=later)
    assert counts["timeout"] == 1
    assert v.status == "failed" and v.error == "A conversão do Docs não terminou em 2 horas."
    assert queue.jobs == []


@respx.mock
async def test_recheck_within_two_hours_keeps_waiting(
    session: AsyncSession, aps: ApsClient, queue: FakeQueue
) -> None:
    mock_token()
    mock_manifest("manifest_inprogress.json")
    v = await _version(session, status="translating")
    counts = await recheck_translating(session, aps, queue)
    assert counts["in_progress"] == 1 and v.status == "translating"


def test_no_translation_message_text() -> None:
    assert NO_TRANSLATION_MSG == (
        "Este arquivo não foi convertido pelo Docs. Abra-o no Autodesk Docs e inicie o "
        "processamento, ou publique pelo site do Docs ou pela publicação em nuvem do Revit."
    )


# --------------------------------------------------------------------------- RUNBOOK (10.3)


@respx.mock
async def test_cli_versions_retry_rechecks_manifest_and_enqueues(
    session: AsyncSession, aps: ApsClient, capsys: pytest.CaptureFixture[str]
) -> None:
    from app.cli import run as cli_run
    from tests.conftest import make_settings

    mock_token()
    manifest = mock_manifest()
    v = await _version(session, status="failed")
    queue = FakeQueue()
    code = await cli_run(
        ["versions", "retry", "--version", str(v.id)], make_settings(), session, aps, queue
    )
    assert code == 0 and manifest.called
    [(fn, args, job_id)] = queue.jobs
    assert fn == "process_version" and args == (v.id,)
    assert job_id is not None and job_id.startswith(f"process_version:{v.id}:retry:")
    await session.refresh(v)
    assert v.status == "pending"
    assert "reprocessamento enfileirado" in capsys.readouterr().out


@respx.mock
async def test_cli_versions_retry_reports_when_docs_still_failed(
    session: AsyncSession, aps: ApsClient, capsys: pytest.CaptureFixture[str]
) -> None:
    from app.cli import run as cli_run
    from tests.conftest import make_settings

    mock_token()
    mock_manifest(status=404)  # o Docs ainda não tem a conversão
    v = await _version(session, status="no_translation")
    queue = FakeQueue()
    code = await cli_run(
        ["versions", "retry", "--version", str(v.id)], make_settings(), session, aps, queue
    )
    assert code == 1 and queue.jobs == []
    assert "Republique o arquivo" in capsys.readouterr().out


async def test_cli_versions_retry_only_failed_or_no_translation(
    session: AsyncSession, aps: ApsClient, capsys: pytest.CaptureFixture[str]
) -> None:
    from app.cli import run as cli_run
    from tests.conftest import make_settings

    v = await _version(session, status="ready")
    queue = FakeQueue()
    settings = make_settings()
    assert (
        await cli_run(["versions", "retry", "--version", str(v.id)], settings, session, aps, queue)
        == 2
    )
    assert (
        await cli_run(["versions", "retry", "--version", "999999"], settings, session, aps, queue)
        == 2
    )
    assert queue.jobs == []
    assert "só failed/no_translation" in capsys.readouterr().err


@respx.mock
async def test_cli_sync_obra_and_all(
    session: AsyncSession, aps: ApsClient, capsys: pytest.CaptureFixture[str]
) -> None:
    from app.cli import run as cli_run
    from tests.conftest import make_settings

    mock_token()
    respx.get(VERSIONS_URL).respond(200, json=fixture("versions.json"))
    mock_manifest("manifest_success.json")
    obra = await _obra(session)
    queue = FakeQueue()
    settings = make_settings()

    assert await cli_run(["sync", "--obra", str(obra.id)], settings, session, aps, queue) == 0
    out = capsys.readouterr().out
    assert f"obra {obra.id}: 2 no Docs, 2 nova(s), 1 para processar" in out
    assert len(queue.jobs) == 1

    # de novo, todas: nada novo (idempotente)
    assert await cli_run(["sync", "--all"], settings, session, aps, queue) == 0
    assert f"obra {obra.id}: 2 no Docs, 0 nova(s)" in capsys.readouterr().out
    assert len(queue.jobs) == 1
