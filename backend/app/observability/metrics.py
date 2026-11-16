"""Métricas simples, compartilhadas entre a API e o worker (Redis).

- contadores (`incr`): versões processadas por status, falhas no APS por tipo, webhooks
  recebidos, versões novas achadas pela verificação periódica;
- tempos (`observe`): quantidade, soma e máximo (tempo de processamento);
- marcos (`mark`): quando algo aconteceu por último (último webhook, último erro de
  credencial do APS, última vez que a verificação periódica achou versões);
- `claim`: trava com expiração (deduplicação dos alertas).

Registrar métrica nunca pode quebrar o fluxo: falhas viram log. Sem store configurado
(ex.: scripts), tudo vira no-op. O que se calcula do banco (versões por status, webhooks
atrasados) e a fila do Arq entram na leitura, em `app/api/health.py`.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

log = logging.getLogger("app.metrics")

PREFIX = "obs"


@dataclass
class Snapshot:
    counters: dict[str, int] = field(default_factory=dict)
    timings: dict[str, dict[str, float]] = field(default_factory=dict)  # count, sum, max
    marks: dict[str, float] = field(default_factory=dict)  # epoch (s)


class MetricsStore(Protocol):
    async def incr(self, name: str, amount: int = 1) -> None: ...
    async def observe(self, name: str, seconds: float) -> None: ...
    async def mark(self, name: str, at: float | None = None) -> None: ...
    async def claim(self, key: str, ttl_seconds: int) -> bool: ...
    async def snapshot(self) -> Snapshot: ...
    async def queue_length(self) -> int | None: ...


class MemoryMetricsStore:
    def __init__(self) -> None:
        self.data = Snapshot()
        self.claims: dict[str, float] = {}
        self.now = time.time

    async def incr(self, name: str, amount: int = 1) -> None:
        self.data.counters[name] = self.data.counters.get(name, 0) + amount

    async def observe(self, name: str, seconds: float) -> None:
        t = self.data.timings.setdefault(name, {"count": 0, "sum": 0.0, "max": 0.0})
        t["count"] += 1
        t["sum"] += seconds
        t["max"] = max(t["max"], seconds)

    async def mark(self, name: str, at: float | None = None) -> None:
        self.data.marks[name] = at if at is not None else self.now()

    async def claim(self, key: str, ttl_seconds: int) -> bool:
        until = self.claims.get(key)
        if until is not None and until > self.now():
            return False
        self.claims[key] = self.now() + ttl_seconds
        return True

    async def snapshot(self) -> Snapshot:
        return Snapshot(
            dict(self.data.counters),
            {k: dict(v) for k, v in self.data.timings.items()},
            dict(self.data.marks),
        )

    async def queue_length(self) -> int | None:
        return None


class RedisMetricsStore:
    def __init__(self, url: str, queue_key: str = "arq:queue") -> None:
        from redis.asyncio import Redis

        self.redis = Redis.from_url(url, decode_responses=True)
        self.queue_key = queue_key

    async def incr(self, name: str, amount: int = 1) -> None:
        await self.redis.hincrby(f"{PREFIX}:counters", name, amount)

    async def observe(self, name: str, seconds: float) -> None:
        key = f"{PREFIX}:timings"
        pipe = self.redis.pipeline()
        pipe.hincrby(key, f"{name}:count", 1)
        pipe.hincrbyfloat(key, f"{name}:sum", seconds)
        pipe.hget(key, f"{name}:max")
        _, _, current = await pipe.execute()
        if current is None or float(current) < seconds:
            await self.redis.hset(key, f"{name}:max", seconds)

    async def mark(self, name: str, at: float | None = None) -> None:
        await self.redis.hset(f"{PREFIX}:marks", name, at if at is not None else time.time())

    async def claim(self, key: str, ttl_seconds: int) -> bool:
        return bool(await self.redis.set(f"{PREFIX}:alert:{key}", "1", nx=True, ex=ttl_seconds))

    async def snapshot(self) -> Snapshot:
        counters = await self.redis.hgetall(f"{PREFIX}:counters")
        timings_raw = await self.redis.hgetall(f"{PREFIX}:timings")
        marks = await self.redis.hgetall(f"{PREFIX}:marks")
        timings: dict[str, dict[str, float]] = {}
        for field_name, value in timings_raw.items():
            name, _, part = field_name.rpartition(":")
            timings.setdefault(name, {})[part] = float(value)
        return Snapshot(
            {k: int(v) for k, v in counters.items()},
            timings,
            {k: float(v) for k, v in marks.items()},
        )

    async def queue_length(self) -> int | None:
        return int(await self.redis.zcard(self.queue_key))

    async def ping(self) -> bool:
        return bool(await self.redis.ping())

    async def close(self) -> None:
        await self.redis.aclose()


# --------------------------------------------------------------------------- global

_store: MetricsStore | None = None


def configure(store: MetricsStore | None) -> None:
    global _store
    _store = store


def current_store() -> MetricsStore | None:
    return _store


def key(name: str, **labels: Any) -> str:
    """Nome no estilo Prometheus: aps_errors_total{kind="auth"}."""
    if not labels:
        return name
    inner = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
    return f"{name}{{{inner}}}"


async def incr(name: str, amount: int = 1, **labels: Any) -> None:
    if _store is None:
        return
    try:
        await _store.incr(key(name, **labels), amount)
    except Exception:
        log.warning("Falha ao registrar a métrica %s", name, exc_info=True)


async def observe(name: str, seconds: float) -> None:
    if _store is None:
        return
    try:
        await _store.observe(name, seconds)
    except Exception:
        log.warning("Falha ao registrar a métrica %s", name, exc_info=True)


async def mark(name: str, at: float | None = None) -> None:
    if _store is None:
        return
    try:
        await _store.mark(name, at)
    except Exception:
        log.warning("Falha ao registrar a métrica %s", name, exc_info=True)


# --------------------------------------------------------------------------- APS


def aps_error_kind(exc: BaseException) -> str:
    from app.aps.errors import (
        ApsAuthError,
        ApsForbiddenError,
        ApsForbiddenOperationError,
        ApsHttpError,
        ApsNotFoundError,
        ApsNoTranslationError,
    )

    for cls, kind in (
        (ApsForbiddenOperationError, "forbidden_operation"),
        (ApsAuthError, "auth"),
        (ApsForbiddenError, "forbidden"),
        (ApsNotFoundError, "not_found"),
        (ApsNoTranslationError, "no_translation"),
        (ApsHttpError, "http"),
    ):
        if isinstance(exc, cls):
            return kind
    return "network"


async def record_aps_error(exc: BaseException) -> None:
    """Gancho do ApsClient: conta a falha e marca erro de credencial (401/403)."""
    kind = aps_error_kind(exc)
    await incr("aps_errors_total", kind=kind)
    if kind in ("auth", "forbidden"):
        await mark("aps_auth_error")
