"""Fila de jobs (Arq/Redis) atrás de uma interface pequena, fácil de trocar nos testes."""

from __future__ import annotations

import asyncio
from typing import Any, Protocol

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings


class JobQueue(Protocol):
    async def enqueue(self, function: str, *args: Any, job_id: str | None = None) -> None: ...


def redis_settings(redis_url: str) -> RedisSettings:
    settings = RedisSettings.from_dsn(redis_url)
    settings.conn_retries = 1
    settings.conn_timeout = 2
    return settings


class ArqQueue:
    """Abre a conexão com o Redis só no primeiro uso (API)."""

    def __init__(self, redis_url: str) -> None:
        self._settings = redis_settings(redis_url)
        self._pool: ArqRedis | None = None
        self._lock = asyncio.Lock()

    async def _get_pool(self) -> ArqRedis:
        async with self._lock:
            if self._pool is None:
                self._pool = await create_pool(self._settings)
            return self._pool

    async def enqueue(self, function: str, *args: Any, job_id: str | None = None) -> None:
        pool = await self._get_pool()
        await pool.enqueue_job(function, *args, _job_id=job_id)

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.aclose()
            self._pool = None


class PoolQueue:
    """Usa a conexão que o próprio worker Arq já mantém (ctx["redis"])."""

    def __init__(self, pool: ArqRedis) -> None:
        self._pool = pool

    async def enqueue(self, function: str, *args: Any, job_id: str | None = None) -> None:
        await self._pool.enqueue_job(function, *args, _job_id=job_id)
