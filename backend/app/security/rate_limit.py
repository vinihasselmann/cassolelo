"""Limite de taxa por usuário nas escritas (POST/PUT/PATCH/DELETE).

Janela fixa de 60 s por usuário, contada no Redis (compartilhada entre instâncias da
API). Chamado por `current_user` (app/auth/dev.py): na Fase 11 o login muda e o limite
continua no mesmo lugar. O webhook do APS não tem usuário e fica fora (assinatura).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Protocol

from fastapi import HTTPException, Request, status

from app.observability import metrics

log = logging.getLogger("app.security")

WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
WINDOW_SECONDS = 60


class RateLimiter(Protocol):
    async def hit(self, key: str, window_seconds: int) -> tuple[int, int]:
        """Conta uma requisição; devolve (total na janela, segundos até ela acabar)."""
        ...

    async def close(self) -> None: ...


class MemoryRateLimiter:
    def __init__(self, clock: Callable[[], float] | None = None) -> None:
        self._counts: dict[str, int] = {}
        self._clock = clock or time.time

    async def hit(self, key: str, window_seconds: int) -> tuple[int, int]:
        now = self._clock()
        window = int(now // window_seconds)
        bucket = f"{key}:{window}"
        self._counts[bucket] = self._counts.get(bucket, 0) + 1
        return self._counts[bucket], max(1, int((window + 1) * window_seconds - now))

    async def close(self) -> None:
        return None


class RedisRateLimiter:
    def __init__(self, url: str) -> None:
        from redis.asyncio import Redis

        self.redis = Redis.from_url(url, decode_responses=True)

    async def hit(self, key: str, window_seconds: int) -> tuple[int, int]:
        now = time.time()
        window = int(now // window_seconds)
        bucket = f"bim:ratelimit:{key}:{window}"
        pipe = self.redis.pipeline()
        pipe.incr(bucket)
        pipe.expire(bucket, window_seconds + 5)
        count, _ = await pipe.execute()
        return int(count), max(1, int((window + 1) * window_seconds - now))

    async def close(self) -> None:
        await self.redis.aclose()


async def enforce_write_limit(request: Request, user_id: int) -> None:
    """429 com Retry-After quando o usuário passa do limite de escritas por minuto."""
    if request.method not in WRITE_METHODS:
        return
    limit: int = request.app.state.settings.rate_limit_writes_per_min
    limiter: RateLimiter | None = getattr(request.app.state, "rate_limiter", None)
    if limit <= 0 or limiter is None:
        return
    try:
        count, retry_after = await limiter.hit(f"w:{user_id}", WINDOW_SECONDS)
    except Exception:  # Redis fora do ar não derruba as escritas
        log.warning("Limite de taxa indisponível; requisição liberada.", exc_info=True)
        return
    if count <= limit:
        return
    log.warning(
        "Limite de escritas excedido",
        extra={"limit": limit, "count": count, "path": request.url.path},
    )
    await metrics.incr("rate_limited_total")
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=(
            f"Muitas alterações em pouco tempo (limite de {limit} por minuto). "
            f"Aguarde {retry_after} s e tente de novo."
        ),
        headers={"Retry-After": str(retry_after)},
    )
