"""8.1 · Eventos em tempo real: emissão depois do commit, SSE, reconexão e dois clientes."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import respx
import uvicorn
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.events import stream_events
from app.aps.client import ApsClient
from app.models import Mark, ModelVersion, Obra, ParamDef, ParamValue, User
from app.models.enums import Role
from app.services import events
from app.services.events import Event, MemoryEventBus, RedisEventBus
from app.services.processing import ProcessingConfig, process_version
from tests.apsfakes import Sleeps, mock_model, mock_token
from tests.conftest import as_user, build_app
from tests.factories import ready_version


@pytest.fixture
async def ctx(session: AsyncSession, users: dict[Role, User]) -> dict[str, Any]:
    obra = Obra(code="OB-EV", name="Obra eventos")
    other = Obra(code="OB-EV2", name="Outra")
    session.add_all([obra, other])
    await session.flush()
    _, marks = await ready_version(session, obra, [(f"PP{i:03d}", "Pilar", 1) for i in range(1, 4)])
    forma = ParamDef(
        name="Tipo de forma",
        type="list",
        options=["F-11", "F-12"],
        scope="obra",
        obra_id=obra.id,
    )
    session.add(forma)
    await session.flush()
    return {
        "obra": obra,
        "other": other,
        "marks": marks,
        "forma": forma,
        "users": users,
        "fab": as_user(users[Role.FABRICA]),
    }


async def _events(bus: MemoryEventBus, obra_id: int) -> list[Event]:
    await events.drain()
    return list(bus.history[obra_id])


async def _put(
    client: httpx.AsyncClient, ctx: dict[str, Any], code: str, value: str
) -> httpx.Response:
    mark = ctx["marks"][code]
    return await client.put(
        f"/api/obras/{ctx['obra'].id}/marks/{mark.id}/values",
        json={"changes": [{"def_id": ctx["forma"].id, "value": value, "row_version": None}]},
        headers=ctx["fab"],
    )


# --------------------------------------------------------------------------- emissão


async def test_values_changed_after_commit_with_mark_fields_and_who(
    client: httpx.AsyncClient, ctx: dict[str, Any], event_bus: MemoryEventBus
) -> None:
    r = await _put(client, ctx, "PP003", "F-12")
    assert r.status_code == 200, r.text
    [ev] = await _events(event_bus, ctx["obra"].id)
    assert ev.type == "values_changed"
    assert ev.data["mark"] == "PP003" and ev.data["fields"] == ["Tipo de forma"]
    assert ev.data["changes"][0] | {"def_id": 0} == {
        "def_id": 0,
        "param": "Tipo de forma",
        "before": None,
        "after": "F-12",
    }
    assert ev.data["actor"] == {
        "id": ctx["users"][Role.FABRICA].id,
        "name": ctx["users"][Role.FABRICA].name,
    }
    assert event_bus.history[ctx["other"].id] == []  # só a obra da marca


async def test_nothing_is_published_without_commit(
    session: AsyncSession, ctx: dict[str, Any], event_bus: MemoryEventBus
) -> None:
    events.emit(session, ctx["obra"].id, "values_changed", {"mark": "X"})
    await session.rollback()
    assert await _events(event_bus, ctx["obra"].id) == []
    with pytest.raises(ValueError, match="desconhecido"):
        events.emit(session, ctx["obra"].id, "qualquer", {})


async def test_failed_save_publishes_nothing(
    client: httpx.AsyncClient, ctx: dict[str, Any], event_bus: MemoryEventBus
) -> None:
    r = await _put(client, ctx, "PP001", "F-99")
    assert r.status_code == 422
    assert await _events(event_bus, ctx["obra"].id) == []


async def test_batch_applied_and_undone(
    client: httpx.AsyncClient, ctx: dict[str, Any], event_bus: MemoryEventBus
) -> None:
    ids = [m.id for m in ctx["marks"].values()]
    r = await client.post(
        f"/api/obras/{ctx['obra'].id}/marks/batch-apply",
        json={"mark_ids": ids, "changes": {str(ctx["forma"].id): "F-11"}, "mode": "overwrite"},
        headers=ctx["fab"],
    )
    batch = r.json()["batch_id"]
    await client.post(f"/api/batches/{batch}/undo", headers=ctx["fab"])
    applied, undone = await _events(event_bus, ctx["obra"].id)
    assert (applied.type, applied.data["marks"], applied.data["fields"]) == (
        "batch_applied",
        3,
        ["Tipo de forma"],
    )
    assert applied.data["mark_codes"] == ["PP001", "PP002", "PP003"]
    assert (undone.type, undone.data["batch_id"], undone.data["restored"]) == (
        "batch_undone",
        batch,
        3,
    )


async def test_param_def_changed_obra_and_global(
    client: httpx.AsyncClient, ctx: dict[str, Any], event_bus: MemoryEventBus
) -> None:
    r = await client.post(
        "/api/param-defs",
        json={"name": "Obs", "type": "text", "scope": "obra", "obra_id": ctx["obra"].id},
        headers=ctx["fab"],
    )
    assert r.status_code == 201, r.text
    r = await client.post(
        "/api/param-defs", json={"name": "Ciclo", "type": "number"}, headers=ctx["fab"]
    )
    def_id = r.json()["id"]
    await client.delete(f"/api/param-defs/{def_id}", headers=ctx["fab"])
    mine = [(e.data["name"], e.data["action"]) for e in await _events(event_bus, ctx["obra"].id)]
    assert mine == [("Obs", "created"), ("Ciclo", "created"), ("Ciclo", "deleted")]
    other = [(e.data["name"], e.data["action"]) for e in event_bus.history[ctx["other"].id]]
    assert other == [("Ciclo", "created"), ("Ciclo", "deleted")]  # global vai a todas


async def test_orphan_changed_and_review_kept(
    client: httpx.AsyncClient,
    session: AsyncSession,
    ctx: dict[str, Any],
    event_bus: MemoryEventBus,
) -> None:
    from app.models import Orphan

    v = (
        await session.scalars(select(ModelVersion).where(ModelVersion.obra_id == ctx["obra"].id))
    ).one()
    gone = Mark(obra_id=ctx["obra"].id, code="PP009", category="Pilar")
    session.add(gone)
    await session.flush()
    session.add(ParamValue(mark_id=gone.id, def_id=ctx["forma"].id, value="F-12"))
    orphan = Orphan(mark_id=gone.id, since_version_id=v.id)
    pp1 = ctx["marks"]["PP001"]
    pp1.review_status, pp1.review_note = "review", "Seção: 40x60 → 40x80"
    session.add(orphan)
    await session.flush()
    r = await client.post(
        f"/api/orphans/{orphan.id}/relink", json={"target_mark_id": pp1.id}, headers=ctx["fab"]
    )
    assert r.status_code == 200, r.text
    await client.post(f"/api/marks/{pp1.id}/review/keep", headers=ctx["fab"])
    got = [
        (e.type, e.data.get("mark"), e.data.get("status") or e.data.get("review"))
        for e in await _events(event_bus, ctx["obra"].id)
    ]
    assert got == [
        ("orphan_changed", "PP009", "relinked"),
        ("values_changed", "PP001", None),  # valores copiados para o destino
        ("values_changed", "PP001", "kept"),
    ]


async def test_version_ready_and_failed_from_processing(
    session: AsyncSession, aps: ApsClient, sleeps: Sleeps, event_bus: MemoryEventBus
) -> None:
    obra = Obra(code="OB-EV3", name="Processamento")
    session.add(obra)
    await session.flush()
    ok = ModelVersion(obra_id=obra.id, acc_version_id="urn:ev:1", version_number=1, urn="dXJuZXYx")
    bad = ModelVersion(obra_id=obra.id, acc_version_id="urn:ev:2", version_number=2, urn="dXJuZXYy")
    session.add_all([ok, bad])
    await session.flush()
    config = ProcessingConfig(mark_names=["Marca"], category_names=["Category"])
    with respx.mock:
        mock_token()
        mock_model("validacao", "dXJuZXYx")
        respx.get(url__regex=r".*/dXJuZXYy/metadata$").respond(500)
        await process_version(session, aps, ok.id, config, sleep=sleeps)
        await process_version(session, aps, bad.id, config, sleep=sleeps)
    ready, failed = await _events(event_bus, obra.id)
    assert (ready.type, ready.data["version_number"], ready.data["marks"]) == (
        "version_ready",
        1,
        3,
    )
    assert ready.data["diff"]["new"] == 3 and ready.data["actor"] is None
    assert (failed.type, failed.data["version_number"], failed.data["status"]) == (
        "version_failed",
        2,
        "failed",
    )


# --------------------------------------------------------------------------- SSE


class _FakeRequest:
    def __init__(self, polls: int) -> None:
        self.polls = polls

    async def is_disconnected(self) -> bool:
        self.polls -= 1
        return self.polls < 0


async def _collect(gen: AsyncIterator[str]) -> list[str]:
    return [chunk async for chunk in gen]


async def test_stream_replays_after_last_event_id_then_heartbeats() -> None:
    bus = MemoryEventBus()
    first = await bus.publish(1, "values_changed", {"mark": "PP001"})
    second = await bus.publish(1, "values_changed", {"mark": "PP002"})
    await bus.publish(2, "values_changed", {"mark": "OUTRA"})
    chunks = await _collect(stream_events(_FakeRequest(polls=1), bus, 1, first.id, 0.01))  # type: ignore[arg-type]
    assert chunks[0] == "retry: 3000\n\n"
    assert chunks[1] == second.sse()  # só o que veio depois do Last-Event-ID
    assert chunks[1].startswith(f"id: {second.id}\nevent: values_changed\ndata: ")
    assert chunks[2:] == [": conectado\n\n", ": heartbeat\n\n"]


async def test_stream_skips_live_duplicates_of_replayed_events() -> None:
    bus = MemoryEventBus()
    first = await bus.publish(1, "values_changed", {"mark": "A"})
    gen = stream_events(_FakeRequest(polls=3), bus, 1, "0-0", 0.05)  # type: ignore[arg-type]
    assert await anext(gen) == "retry: 3000\n\n"
    assert await anext(gen) == first.sse()
    assert await anext(gen) == ": conectado\n\n"
    # entregue de novo pelo canal ao vivo (ex.: corrida entre assinar e repor) → ignorado
    sub = next(iter(bus.subscribers[1]))
    sub.queue.put_nowait(first)
    live = await bus.publish(1, "values_changed", {"mark": "B"})
    assert await anext(gen) == live.sse()
    await gen.aclose()


async def test_events_endpoint_requires_user_and_obra(
    client: httpx.AsyncClient, ctx: dict[str, Any]
) -> None:
    assert (await client.get(f"/api/obras/{ctx['obra'].id}/events")).status_code == 401
    r = await client.get("/api/obras/999999/events", headers=ctx["fab"])
    assert r.status_code == 404


# --------------------------------------------------------------------------- dois clientes


_SERVER_APPS: list[Any] = []


@contextlib.asynccontextmanager
async def _server(session: AsyncSession, aps: ApsClient) -> AsyncIterator[str]:
    """Servidor HTTP de verdade (uvicorn) no loop do teste, com a sessão do teste."""
    app = build_app(session, aps=aps, sse_heartbeat_seconds=0.2)
    _SERVER_APPS.append(app)
    config = uvicorn.Config(app, host="127.0.0.1", port=0, lifespan="off", log_level="warning")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    while not server.started:  # noqa: ASYNC110 - o uvicorn só expõe a flag
        await asyncio.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await task


async def _read_events(
    response: httpx.Response, wanted: int, wait_seconds: float = 5.0
) -> tuple[list[dict[str, Any]], int]:
    """Lê o SSE até `wanted` eventos; devolve (eventos, nº de heartbeats vistos)."""
    out: list[dict[str, Any]] = []
    beats = 0
    current: dict[str, Any] = {}

    async def read() -> None:
        nonlocal beats, current
        async for line in response.aiter_lines():
            if line.startswith(": heartbeat"):
                beats += 1
            elif line.startswith("id: "):
                current["id"] = line[4:]
            elif line.startswith("event: "):
                current["event"] = line[7:]
            elif line.startswith("data: "):
                current["data"] = json.loads(line[6:])
            elif line == "" and "event" in current:
                out.append(current)
                current = {}
                if len(out) >= wanted:
                    return

    await asyncio.wait_for(read(), wait_seconds)
    return out, beats


async def test_two_clients_an_edit_in_one_reaches_the_other(
    session: AsyncSession, aps: ApsClient, ctx: dict[str, Any]
) -> None:
    url = f"/api/obras/{ctx['obra'].id}/events"
    mark = ctx["marks"]["PP003"]
    leitor = as_user(ctx["users"][Role.LEITURA])
    async with (
        _server(session, aps) as base,
        httpx.AsyncClient(base_url=base) as a,
        httpx.AsyncClient(base_url=base) as b,
    ):
        async with a.stream("GET", url, headers=leitor) as stream:
            assert stream.status_code == 200
            assert stream.headers["content-type"].startswith("text/event-stream")
            await asyncio.sleep(0.3)  # A conectado (e pelo menos um heartbeat)
            # cliente B edita
            r = await b.put(
                f"/api/obras/{ctx['obra'].id}/marks/{mark.id}/values",
                json={
                    "changes": [{"def_id": ctx["forma"].id, "value": "F-11", "row_version": None}]
                },
                headers=ctx["fab"],
            )
            assert r.status_code == 200, r.text
            [ev], beats = await _read_events(stream, 1)
        assert ev["event"] == "values_changed"
        assert ev["data"]["mark"] == "PP003" and ev["data"]["fields"] == ["Tipo de forma"]
        assert ev["data"]["actor"]["name"] == ctx["users"][Role.FABRICA].name
        assert beats >= 1

        # A cai e volta com Last-Event-ID: recebe o que perdeu nesse meio tempo
        r = await b.put(
            f"/api/obras/{ctx['obra'].id}/marks/{ctx['marks']['PP001'].id}/values",
            json={"changes": [{"def_id": ctx["forma"].id, "value": "F-12", "row_version": None}]},
            headers=ctx["fab"],
        )
        await events.drain()
        async with a.stream("GET", url, headers={**leitor, "Last-Event-ID": ev["id"]}) as stream:
            [missed], _ = await _read_events(stream, 1)
        assert missed["data"]["mark"] == "PP001" and missed["id"] > ev["id"]


# --------------------------------------------------------------------------- Redis


@pytest.fixture
async def redis_bus() -> AsyncIterator[RedisEventBus]:
    from app.config import get_settings

    url = os.environ.get("REDIS_URL") or get_settings().redis_url
    bus = RedisEventBus(url)
    try:
        await bus.redis.ping()
    except Exception:
        await bus.close()
        if os.environ.get("REQUIRE_REDIS"):
            raise
        pytest.skip("Redis indisponível (defina REQUIRE_REDIS=1 para exigir)")
    yield bus
    await bus.redis.delete(bus.stream_key(987654321))
    await bus.close()


async def test_redis_bus_pubsub_and_replay(redis_bus: RedisEventBus) -> None:
    obra_id = 987654321  # canal de teste
    await redis_bus.redis.delete(redis_bus.stream_key(obra_id))
    async with redis_bus.subscribe(obra_id) as sub:
        first = await redis_bus.publish(obra_id, "values_changed", {"mark": "PP001"})
        live = await sub.get(2.0)
        assert live is not None and (live.id, live.data) == (first.id, {"mark": "PP001"})
        second = await redis_bus.publish(obra_id, "version_ready", {"version_number": 2})
        assert (await sub.get(2.0)) is not None
        assert await sub.get(0.2) is None  # nada mais: heartbeat no SSE
    replay = await redis_bus.replay(obra_id, first.id)
    assert [(e.id, e.type) for e in replay] == [(second.id, "version_ready")]


async def test_stream_does_not_hold_a_database_session(
    session: AsyncSession, aps: ApsClient, ctx: dict[str, Any]
) -> None:
    """A sessão é devolvida antes do fluxo: abas abertas não esgotam o pool do Postgres."""
    from app.db import get_session

    state = {"open": 0, "max": 0}

    async def tracked() -> AsyncIterator[AsyncSession]:
        state["open"] += 1
        state["max"] = max(state["max"], state["open"])
        try:
            yield session
        finally:
            state["open"] -= 1

    async with _server(session, aps) as base, httpx.AsyncClient(base_url=base) as c:
        app = _SERVER_APPS[-1]
        app.dependency_overrides[get_session] = tracked
        url = f"/api/obras/{ctx['obra'].id}/events"
        headers = as_user(ctx["users"][Role.LEITURA])
        async with (
            c.stream("GET", url, headers=headers) as s1,
            c.stream("GET", url, headers=headers) as s2,
        ):
            assert s1.status_code == s2.status_code == 200
            await asyncio.sleep(0.3)  # fluxos abertos, com heartbeat
            assert state == {"open": 0, "max": 1}
