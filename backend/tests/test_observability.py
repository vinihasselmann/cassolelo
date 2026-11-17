"""10.1 · Logs estruturados, /health e /ready, métricas e alertas."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import respx
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from app.aps import webhooks as wh
from app.aps.client import ApsClient
from app.aps.errors import ApsForbiddenError
from app.models import ModelVersion, Obra, User, WebhookEvent
from app.models.enums import Role
from app.observability import alerts
from app.observability.logging import JsonFormatter, RequestContextMiddleware, bind, redact
from app.observability.metrics import MemoryMetricsStore, record_aps_error
from app.services.processing import ProcessingConfig, process_version
from app.workers import tasks
from tests.apsfakes import BASE, Sleeps, mock_model, mock_token
from tests.conftest import as_user, build_app, make_settings

# --------------------------------------------------------------------------- logs


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.setFormatter(JsonFormatter())
        self.lines: list[dict[str, Any]] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(json.loads(self.format(record)))


@pytest.fixture
def captured() -> Any:
    handler = _Capture()
    root = logging.getLogger()
    root.addHandler(handler)
    old = root.level
    root.setLevel(logging.INFO)
    yield handler
    root.removeHandler(handler)
    root.setLevel(old)


@pytest.mark.parametrize(
    ("raw", "leak"),
    [
        ("Authorization: Bearer eyJhbGciOi.abc123", "abc123"),
        ('{"access_token": "tok-123", "expires_in": 3599}', "tok-123"),
        ("client_secret=s3cr3t&grant_type=client_credentials", "s3cr3t"),
        ("password: hunter2", "hunter2"),
        ("conexão redis://app:s3nh4@redis:6379/0 recusada", "s3nh4"),
        ("x-adsk-signature: sha1hash=deadbeef", "deadbeef"),
        ("jwt eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiIxMjM0In0.c2lnbmF0dXJlLXZhbGlk", "c2lnbmF0dXJl"),
    ],
)
def test_redact_removes_secrets(raw: str, leak: str) -> None:
    assert leak not in redact(raw)
    assert "[REDACTED]" in redact(raw)


def test_json_line_with_context_extras_and_redacted_exception(captured: Any) -> None:
    log = logging.getLogger("app.teste")
    bind(request_id="req-12345678", obra=7, job="process_version", version=3)
    bind(user=User(id=2, name="Fábio Fábrica", email="f@x", role="fabrica"))
    try:
        raise RuntimeError("falhou com Bearer abc.def.ghi")
    except RuntimeError:
        log.exception("erro ao processar token=%s", "segredo", extra={"elements": 359})
    line = captured.lines[-1]
    assert line["level"] == "ERROR" and line["logger"] == "app.teste"
    assert line["msg"] == "erro ao processar token=[REDACTED]"
    assert (line["request_id"], line["obra"], line["job"], line["version"]) == (
        "req-12345678",
        7,
        "process_version",
        3,
    )
    assert line["user"] == {"id": 2, "name": "Fábio Fábrica"}
    assert line["elements"] == 359
    assert "abc.def.ghi" not in line["exc"] and "Bearer [REDACTED]" in line["exc"]
    assert datetime.fromisoformat(line["ts"]).tzinfo is not None


async def test_request_id_obra_user_and_access_line(
    client: httpx.AsyncClient, session: AsyncSession, users: dict[Role, User], captured: Any
) -> None:
    obra = Obra(code="OB-LOG", name="Logs")
    session.add(obra)
    await session.flush()
    r = await client.get(f"/api/obras/{obra.id}/versions", headers=as_user(users[Role.FABRICA]))
    assert r.status_code == 200
    rid = r.headers["x-request-id"]
    assert len(rid) == 32
    access = [x for x in captured.lines if x["logger"] == "app.access"]
    assert access[-1]["request_id"] == rid
    assert (access[-1]["path"], access[-1]["status"], access[-1]["obra"]) == (
        f"/api/obras/{obra.id}/versions",
        200,
        obra.id,
    )
    assert access[-1]["user"]["name"] == users[Role.FABRICA].name
    assert access[-1]["duration_ms"] >= 0
    # X-Request-ID do proxy é aproveitado; um inválido é trocado
    r = await client.get(
        "/api/obras", headers={**as_user(users[Role.FABRICA]), "X-Request-ID": "proxy-abc-123"}
    )
    assert r.headers["x-request-id"] == "proxy-abc-123"
    r = await client.get(
        "/api/obras", headers={**as_user(users[Role.FABRICA]), "X-Request-ID": "<script>"}
    )
    assert r.headers["x-request-id"] != "<script>"


async def test_middleware_does_not_break_streaming() -> None:
    from fastapi.responses import StreamingResponse

    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)

    @app.get("/stream")
    async def stream() -> StreamingResponse:
        async def gen() -> Any:
            for i in range(3):
                yield f"data: {i}\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream")

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/stream")
    assert r.text == "data: 0\n\ndata: 1\n\ndata: 2\n\n" and "x-request-id" in r.headers


# --------------------------------------------------------------------------- health / ready


async def test_health_and_ready(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/health")).json()["status"] == "ok"
    r = await client.get("/api/ready")
    assert r.status_code == 200, r.text
    checks = r.json()["checks"]
    assert checks["database"]["ok"] and checks["redis"]["ok"]
    assert checks["aps"]["note"].startswith("skipped")  # dev sem credenciais


async def test_ready_503_with_reasons_and_no_secrets(session: AsyncSession) -> None:
    app = build_app(session)

    async def redis_down() -> None:
        raise ConnectionError("conexão redis://app:s3nh4@redis:6379 recusada")

    async def aps_ok() -> None:
        return None

    app.state.ready_checks = {"redis": redis_down, "aps": aps_ok}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/ready")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["redis"]["ok"] is False
    assert "ConnectionError" in body["checks"]["redis"]["error"] and "s3nh4" not in r.text
    assert body["checks"]["aps"]["ok"] and body["checks"]["database"]["ok"]


async def test_ready_aps_without_credentials_fails_outside_dev(session: AsyncSession) -> None:
    app = build_app(session, app_env="staging")
    check = app.state.ready_checks["aps"]
    with pytest.raises(RuntimeError, match="APS_CLIENT_ID"):
        await check()


@respx.mock
async def test_ready_aps_checks_the_token(session: AsyncSession) -> None:
    app = build_app(session, aps_client_id="cid", aps_client_secret="sec")
    route = respx.post(f"{BASE}/authentication/v2/token").respond(401, json={})
    with pytest.raises(Exception, match="autenticação APS"):
        await app.state.ready_checks["aps"]()
    route.respond(200, json={"access_token": "t", "expires_in": 3599, "token_type": "Bearer"})
    assert await app.state.ready_checks["aps"]() is None


# --------------------------------------------------------------------------- métricas


async def test_processing_metrics(
    session: AsyncSession, aps: ApsClient, sleeps: Sleeps, metrics_store: MemoryMetricsStore
) -> None:
    obra = Obra(code="OB-MET", name="Métricas")
    session.add(obra)
    await session.flush()
    ok = ModelVersion(obra_id=obra.id, acc_version_id="urn:m:1", version_number=1, urn="dXJubTE")
    bad = ModelVersion(obra_id=obra.id, acc_version_id="urn:m:2", version_number=2, urn="dXJubTI")
    session.add_all([ok, bad])
    await session.flush()
    config = ProcessingConfig(mark_names=["Marca"], category_names=["Category"])
    with respx.mock:
        mock_token()
        mock_model("validacao", "dXJubTE")
        respx.get(url__regex=r".*/dXJubTI/metadata$").respond(500)
        await process_version(session, aps, ok.id, config, sleep=sleeps)
        await process_version(session, aps, bad.id, config, sleep=sleeps)
    snap = await metrics_store.snapshot()
    assert snap.counters['versions_processed_total{status="ready"}'] == 1
    assert snap.counters['versions_processed_total{status="failed"}'] == 1
    assert snap.timings["processing_seconds"]["count"] == 1


@respx.mock
async def test_aps_errors_are_counted_and_auth_errors_marked(
    aps: ApsClient, metrics_store: MemoryMetricsStore
) -> None:
    aps.error_hooks.append(record_aps_error)
    mock_token()
    respx.get(url__regex=r".*/project/v1/hubs$").respond(403, json={})
    with pytest.raises(ApsForbiddenError):
        await aps.get_json("/project/v1/hubs")
    respx.get(url__regex=r".*/data/v1/projects/p/items/i$").respond(404, json={})
    with pytest.raises(Exception):  # noqa: B017
        await aps.get_json("/data/v1/projects/p/items/i")
    snap = await metrics_store.snapshot()
    assert snap.counters['aps_errors_total{kind="forbidden"}'] == 1
    assert snap.counters['aps_errors_total{kind="not_found"}'] == 1
    assert "aps_auth_error" in snap.marks


async def test_webhook_received_is_counted(
    session: AsyncSession, metrics_store: MemoryMetricsStore
) -> None:
    app = build_app(session, aps_webhook_secret="0123456789abcdef")
    body = json.dumps({"hook": {"event": "dm.version.added"}, "payload": {}}).encode()
    headers = {wh.SIGNATURE_HEADER: wh.compute_signature("0123456789abcdef", body)}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/webhooks/aps", content=body, headers=headers)
    assert r.status_code == 200, r.text
    snap = await metrics_store.snapshot()
    assert snap.counters["webhooks_received_total"] == 1 and "webhook_received" in snap.marks


async def test_metrics_endpoint_json_prometheus_and_access(
    session: AsyncSession, users: dict[Role, User], metrics_store: MemoryMetricsStore
) -> None:
    obra = Obra(code="OB-MET2", name="Métricas")
    session.add(obra)
    await session.flush()
    old = datetime.now(UTC) - timedelta(hours=3)
    session.add_all(
        [
            ModelVersion(obra_id=obra.id, acc_version_id="u:1", version_number=1, status="ready"),
            ModelVersion(
                obra_id=obra.id,
                acc_version_id="u:2",
                version_number=2,
                status="no_translation",
                updated_at=old,
            ),
            WebhookEvent(event_id="e1", payload={}, obra_id=obra.id, received_at=old),  # atrasado
            WebhookEvent(event_id="e2", payload={}, obra_id=obra.id),  # recente
        ]
    )
    await session.flush()
    await metrics_store.incr('versions_processed_total{status="ready"}', 4)
    await metrics_store.observe("processing_seconds", 2.0)
    await metrics_store.observe("processing_seconds", 4.0)
    app = build_app(session, metrics_token="coletor-123")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        assert (
            await c.get("/api/metrics", headers=as_user(users[Role.FABRICA]))
        ).status_code == 403
        assert (
            await c.get("/api/metrics", headers={"Authorization": "Bearer errado"})
        ).status_code == 403
        r = await c.get("/api/metrics", headers=as_user(users[Role.ADMIN]))
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["counters"]['versions_processed_total{status="ready"}'] == 4
        assert data["timings"]["processing_seconds"] == {
            "count": 2,
            "sum": 6.0,
            "max": 4.0,
            "avg": 3.0,
        }
        g = data["gauges"]
        assert (
            g["versions_by_status"]["no_translation"] == 1 and g["versions_by_status"]["ready"] == 1
        )
        assert (g["versions_no_translation_over_2h"], g["webhooks_late"]) == (1, 1)
        assert g["webhook_last_received_at"] is not None
        prom = await c.get(
            "/api/metrics",
            params={"format": "prometheus"},
            headers={"Authorization": "Bearer coletor-123"},
        )
    assert prom.status_code == 200
    assert "# TYPE bim_versions_processed_total counter" in prom.text
    assert 'bim_versions_processed_total{status="ready"} 4' in prom.text
    assert "bim_processing_seconds_max 4.0" in prom.text
    assert 'bim_versions{status="no_translation"} 1' in prom.text


# --------------------------------------------------------------------------- alertas


class _FakeNotifier:
    name = "fake"

    def __init__(self, fail: bool = False) -> None:
        self.sent: list[alerts.Alert] = []
        self.fail = fail

    async def send(self, alert: alerts.Alert) -> None:
        if self.fail:
            raise RuntimeError("canal fora do ar")
        self.sent.append(alert)


async def _versions(session: AsyncSession) -> Obra:
    obra = Obra(code="OB-AL", name="Alertas")
    session.add(obra)
    await session.flush()
    now = datetime.now(UTC)
    session.add_all(
        [
            ModelVersion(
                obra_id=obra.id,
                acc_version_id="a:1",
                version_number=1,
                status="failed",
                error="Erro inesperado",
                updated_at=now - timedelta(minutes=5),
            ),
            ModelVersion(
                obra_id=obra.id,
                acc_version_id="a:2",
                version_number=2,
                status="failed",
                updated_at=now - timedelta(days=10),
            ),
            ModelVersion(
                obra_id=obra.id,
                acc_version_id="a:3",
                version_number=3,
                status="no_translation",
                updated_at=now - timedelta(hours=3),
            ),
            ModelVersion(
                obra_id=obra.id,
                acc_version_id="a:4",
                version_number=4,
                status="no_translation",
                updated_at=now - timedelta(hours=1),
            ),
        ]
    )
    await session.flush()
    return obra


async def test_alerts_failed_and_no_translation_once(
    session: AsyncSession, metrics_store: MemoryMetricsStore
) -> None:
    await _versions(session)
    settings = make_settings(app_base_url="https://bim.cassol.local")
    fake, broken = _FakeNotifier(), _FakeNotifier(fail=True)
    sent = await alerts.run_checks(session, metrics_store, settings, [broken, fake])
    titles = [a.title for a in sent]
    assert titles == ["Versão com falha: OB-AL V1", "Sem conversão há 3 h: OB-AL V3"]
    assert "Erro inesperado" in sent[0].text and "https://bim.cassol.local/obras/" in sent[0].text
    assert [a.key for a in fake.sent] == [a.key for a in sent]  # um canal fora não impede o outro
    # deduplicação: nada de novo na próxima rodada
    assert await alerts.run_checks(session, metrics_store, settings, [fake]) == []


async def test_alert_webhook_silence_only_when_webhooks_configured(
    session: AsyncSession, metrics_store: MemoryMetricsStore
) -> None:
    await metrics_store.mark("periodic_found_versions")
    without = await alerts.evaluate(session, metrics_store, make_settings())
    assert [a.key for a in without] == []  # webhooks não configurados (dev/teste)
    settings = make_settings(public_base_url="https://bim.cassol.com.br")
    keys = [a.key for a in await alerts.evaluate(session, metrics_store, settings)]
    assert keys == ["webhook_silence"]
    # com webhook recebido nas últimas 24 h, não alerta
    obra = Obra(code="OB-WH", name="x")
    session.add(obra)
    await session.flush()
    session.add(WebhookEvent(event_id="w1", payload={}, obra_id=obra.id))
    await session.flush()
    assert await alerts.evaluate(session, metrics_store, settings) == []
    # verificação periódica sem versões novas há mais de 24 h: não alerta
    store = MemoryMetricsStore()
    await store.mark(
        "periodic_found_versions", (datetime.now(UTC) - timedelta(hours=30)).timestamp()
    )
    assert await alerts.evaluate(session, store, settings) == []


async def test_alert_aps_credentials(
    session: AsyncSession, metrics_store: MemoryMetricsStore
) -> None:
    await metrics_store.mark("aps_auth_error", (datetime.now(UTC) - timedelta(hours=1)).timestamp())
    assert await alerts.evaluate(session, metrics_store, make_settings()) == []  # antigo
    await metrics_store.mark("aps_auth_error")
    [alert] = await alerts.evaluate(session, metrics_store, make_settings())
    assert alert.key == "aps_auth" and "Custom Integrations" in alert.text


async def test_alert_backup_late_and_failed(
    session: AsyncSession, metrics_store: MemoryMetricsStore
) -> None:
    """10.3: o script de backup marca backup_last_ok / backup_last_failed no Redis."""
    now = datetime.now(UTC)
    on = make_settings(backup_max_age_hours=26)
    # desligado (dev): nenhum alerta mesmo sem backup
    assert await alerts.evaluate(session, metrics_store, make_settings()) == []
    # ligado e nenhum backup ainda
    [late] = await alerts.evaluate(session, metrics_store, on)
    assert late.key == "backup_late" and "nenhum registrado" in late.text
    # backup recente: nada
    await metrics_store.mark("backup_last_ok", (now - timedelta(hours=3)).timestamp())
    assert await alerts.evaluate(session, metrics_store, on) == []
    # passou de 26 h
    await metrics_store.mark("backup_last_ok", (now - timedelta(hours=27)).timestamp())
    [late] = await alerts.evaluate(session, metrics_store, on)
    assert late.key == "backup_late" and "últimas 26 h" in late.text
    # falha depois do último sucesso: alerta de falha (um por falha)
    failed_at = (now - timedelta(minutes=5)).timestamp()
    await metrics_store.mark("backup_last_failed", failed_at)
    [failed] = await alerts.evaluate(session, metrics_store, on)
    assert failed.key == f"backup_failed:{int(failed_at)}" and failed.severity == "error"
    # sucesso depois da falha: tudo certo de novo
    await metrics_store.mark("backup_last_ok", now.timestamp())
    assert await alerts.evaluate(session, metrics_store, on) == []


@respx.mock
async def test_teams_notifier_posts_adaptive_card() -> None:
    route = respx.post("https://prod.westus.logic.azure.com/workflows/x").respond(202)
    alert = alerts.Alert("k", "Versão com falha: OB V2", "detalhe", 60)
    await alerts.TeamsNotifier("https://prod.westus.logic.azure.com/workflows/x").send(alert)
    body = json.loads(route.calls.last.request.content)
    card = body["attachments"][0]
    assert card["contentType"] == "application/vnd.microsoft.card.adaptive"
    assert "Versão com falha: OB V2" in card["content"]["body"][0]["text"]
    assert card["content"]["body"][1]["text"] == "detalhe"


async def test_email_notifier_uses_smtp(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, Any]] = []

    class FakeSMTP:
        def __init__(self, host: str, port: int, timeout: int) -> None:
            calls.append(("connect", (host, port)))

        def __enter__(self) -> FakeSMTP:
            return self

        def __exit__(self, *_: Any) -> None:
            calls.append(("quit", None))

        def starttls(self, context: Any) -> None:
            calls.append(("starttls", None))

        def login(self, user: str, password: str) -> None:
            calls.append(("login", (user, password)))

        def send_message(self, msg: Any) -> None:
            calls.append(("send", (msg["To"], msg["Subject"], msg.get_content())))

    monkeypatch.setattr("app.observability.alerts.smtplib.SMTP", FakeSMTP)
    settings = make_settings(
        smtp_host="smtp.cassol.local",
        smtp_user="bim",
        smtp_password="pw",
        smtp_from="bim@cassol.com.br",
        alert_email_to="ti@cassol.com.br, pcp@cassol.com.br",
    )
    [notifier] = alerts.notifiers_from_settings(settings)
    await notifier.send(alerts.Alert("k", "Teste", "texto do alerta", 60))
    assert calls[0] == ("connect", ("smtp.cassol.local", 587))
    assert ("starttls", None) in calls and ("login", ("bim", "pw")) in calls
    sent = next(c[1] for c in calls if c[0] == "send")
    assert sent[0] == "ti@cassol.com.br, pcp@cassol.com.br" and sent[1] == "[Cassol Elo] Teste"
    assert "texto do alerta" in sent[2]


def test_notifiers_from_settings() -> None:
    assert alerts.notifiers_from_settings(make_settings()) == []
    both = alerts.notifiers_from_settings(
        make_settings(alert_teams_webhook_url="https://x", smtp_host="h", alert_email_to="a@b")
    )
    assert [n.name for n in both] == ["teams", "email"]


async def test_worker_check_alerts_job(
    session: AsyncSession, metrics_store: MemoryMetricsStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _versions(session)
    fake = _FakeNotifier()
    monkeypatch.setattr(alerts, "notifiers_from_settings", lambda _s: [fake])

    class _Maker:
        def __call__(self) -> Any:
            return self

        async def __aenter__(self) -> AsyncSession:
            return session

        async def __aexit__(self, *_: Any) -> None:
            return None

    ctx = {"sessionmaker": _Maker(), "settings": make_settings(), "metrics": metrics_store}
    await tasks.check_alerts(ctx)
    assert len(fake.sent) == 2
