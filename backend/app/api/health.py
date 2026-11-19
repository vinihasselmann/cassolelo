"""Saúde e métricas (Fase 10.1).

- GET /api/health: o processo está vivo (sem dependências; para o orquestrador).
- GET /api/ready: banco, Redis e APS acessíveis → 200; senão 503 com o detalhe de cada
  checagem (sem segredos). APS sem credenciais: "skipped" em dev, falha fora de dev.
- GET /api/metrics: contadores/tempos do Redis + números calculados do banco + fila do
  Arq. JSON (padrão) ou ?format=prometheus. Acesso: admin ou Bearer METRICS_TOKEN.
"""

from __future__ import annotations

import asyncio
import secrets
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from sqlalchemy import func, select, text

from app.auth import Role, current_user
from app.db import SessionDep
from app.models import ModelVersion, WebhookEvent
from app.models.enums import VersionStatus
from app.observability.logging import redact
from app.observability.metrics import MetricsStore
from app.services.errors import DomainError

router = APIRouter(tags=["health"])

CHECK_TIMEOUT = 5.0
WEBHOOK_LATE_AFTER = timedelta(minutes=10)

ReadyCheck = Callable[[], Awaitable[str | None]]  # devolve uma observação ou levanta erro


@router.get("/health")
async def health(request: Request) -> dict[str, str]:
    return {"status": "ok", "env": request.app.state.settings.app_env}


def _error(exc: BaseException) -> str:
    detail = redact(str(exc))[:200]
    return f"{exc.__class__.__name__}: {detail}" if detail else exc.__class__.__name__


async def _run(check: ReadyCheck) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        note = await asyncio.wait_for(check(), CHECK_TIMEOUT)
        out: dict[str, Any] = {"ok": True}
        if note:
            out["note"] = note
    except Exception as exc:  # cada checagem é independente
        out = {"ok": False, "error": _error(exc)}
    out["ms"] = round((time.perf_counter() - started) * 1000, 1)
    return out


@router.get("/ready")
async def ready(request: Request, session: SessionDep) -> JSONResponse:
    async def database() -> None:
        await session.execute(text("SELECT 1"))

    checks: dict[str, ReadyCheck] = {"database": database, **request.app.state.ready_checks}
    results = {name: await _run(check) for name, check in checks.items()}
    ok = all(r["ok"] for r in results.values())
    return JSONResponse(
        {"status": "ready" if ok else "not_ready", "checks": results},
        status_code=200 if ok else 503,
        headers={"Cache-Control": "no-store"},
    )


# --------------------------------------------------------------------------- métricas


class MetricsForbiddenError(DomainError):
    status_code = 403
    code = "forbidden"


async def _authorize(request: Request, session: SessionDep) -> None:
    configured = request.app.state.settings.metrics_token.get_secret_value()
    auth = request.headers.get("authorization", "")
    # um JWT (login Microsoft do admin, Fase 11) segue para current_user
    is_jwt = auth[7:].strip().count(".") == 2
    if configured and auth.lower().startswith("bearer ") and not is_jwt:
        if secrets.compare_digest(auth[7:].strip(), configured):
            return
        raise MetricsForbiddenError("Token de métricas inválido.")
    user = await current_user(request, session)
    if user.role != Role.ADMIN.value:
        raise MetricsForbiddenError("Só o admin (ou o coletor com METRICS_TOKEN) vê as métricas.")


async def collect(request: Request, session: SessionDep) -> dict[str, Any]:
    store: MetricsStore = request.app.state.metrics
    snap = await store.snapshot()
    now = datetime.now(UTC)
    rows = await session.execute(
        select(ModelVersion.status, func.count()).group_by(ModelVersion.status)
    )
    by_status: dict[str, int] = {status: n for status, n in rows}
    stuck = await session.scalar(
        select(func.count()).where(
            ModelVersion.status == VersionStatus.NO_TRANSLATION.value,
            ModelVersion.updated_at <= now - timedelta(hours=2),
        )
    )
    late = await session.scalar(
        select(func.count()).where(
            WebhookEvent.processed_at.is_(None),
            WebhookEvent.obra_id.is_not(None),
            WebhookEvent.received_at <= now - WEBHOOK_LATE_AFTER,
        )
    )
    last_webhook = await session.scalar(select(func.max(WebhookEvent.received_at)))
    timings = {
        name: {**t, "avg": round(t["sum"] / t["count"], 3) if t.get("count") else 0.0}
        for name, t in snap.timings.items()
    }
    return {
        "at": now.isoformat(),
        "counters": dict(sorted(snap.counters.items())),
        "timings": timings,
        "marks": {
            k: datetime.fromtimestamp(v, UTC).isoformat() for k, v in sorted(snap.marks.items())
        },
        "gauges": {
            "versions_by_status": {s.value: int(by_status.get(s.value, 0)) for s in VersionStatus},
            "versions_no_translation_over_2h": int(stuck or 0),
            "webhooks_late": int(late or 0),
            "webhook_last_received_at": last_webhook.isoformat() if last_webhook else None,
            "arq_queue_length": await store.queue_length(),
        },
    }


def _prometheus(data: dict[str, Any]) -> str:
    lines: list[str] = []
    seen: set[str] = set()

    def emit(name: str, value: float, kind: str) -> None:
        base = name.split("{", 1)[0]
        if base not in seen:
            seen.add(base)
            lines.append(f"# TYPE bim_{base} {kind}")
        lines.append(f"bim_{name} {value}")

    for name, value in data["counters"].items():
        emit(name, value, "counter")
    for name, t in data["timings"].items():
        for part in ("count", "sum", "max"):
            emit(f"{name}_{part}", t.get(part, 0), "gauge")
    for name, iso in data["marks"].items():
        emit(f"{name}_timestamp_seconds", datetime.fromisoformat(iso).timestamp(), "gauge")
    g = data["gauges"]
    for status, n in g["versions_by_status"].items():
        emit(f'versions{{status="{status}"}}', n, "gauge")
    emit("versions_no_translation_over_2h", g["versions_no_translation_over_2h"], "gauge")
    emit("webhooks_late", g["webhooks_late"], "gauge")
    if g["arq_queue_length"] is not None:
        emit("arq_queue_length", g["arq_queue_length"], "gauge")
    if g["webhook_last_received_at"]:
        last = datetime.fromisoformat(g["webhook_last_received_at"]).timestamp()
        emit("webhook_last_received_timestamp_seconds", last, "gauge")
    return "\n".join(lines) + "\n"


@router.get("/metrics", response_model=None)
async def metrics(
    request: Request, session: SessionDep, format: Literal["json", "prometheus"] = "json"
) -> Response | dict[str, Any]:
    await _authorize(request, session)
    data = await collect(request, session)
    if format == "prometheus":
        return PlainTextResponse(_prometheus(data), media_type="text/plain; version=0.0.4")
    return data
