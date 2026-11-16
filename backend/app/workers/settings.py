"""Configuração do worker:  uv run arq app.workers.settings.WorkerSettings  (make worker)"""

from __future__ import annotations

from typing import Any, ClassVar

from arq import cron

from app.aps import build_aps_client
from app.config import get_settings
from app.db import create_engine, create_sessionmaker
from app.observability import metrics
from app.observability.logging import configure_logging
from app.services import events
from app.workers.queue import PoolQueue, redis_settings
from app.workers.tasks import (
    check_alerts,
    check_translations,
    process_version,
    sync_all_obras,
    sync_obra,
)

EVERY_10_MIN = set(range(0, 60, 10))
EVERY_2_MIN = set(range(0, 60, 2))
EVERY_5_MIN = set(range(0, 60, 5))


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    engine = create_engine(settings.database_url)
    ctx["settings"] = settings
    ctx["engine"] = engine
    ctx["sessionmaker"] = create_sessionmaker(engine)
    ctx["aps"] = build_aps_client(settings)
    ctx["queue"] = PoolQueue(ctx["redis"])
    ctx["events"] = events.RedisEventBus(settings.redis_url)
    events.configure(ctx["events"])  # version_ready/failed chegam às telas abertas
    ctx["metrics"] = metrics.RedisMetricsStore(settings.redis_url)
    metrics.configure(ctx["metrics"])


async def shutdown(ctx: dict[str, Any]) -> None:
    await events.drain()
    await ctx["events"].close()
    await ctx["metrics"].close()
    await ctx["aps"].http.aclose()
    await ctx["engine"].dispose()


class WorkerSettings:
    functions: ClassVar[list[Any]] = [process_version, sync_obra]
    cron_jobs: ClassVar[list[Any]] = [
        cron(sync_all_obras, minute=EVERY_10_MIN, unique=True, run_at_startup=True),
        cron(check_translations, minute=EVERY_2_MIN, unique=True),
        cron(check_alerts, minute=EVERY_5_MIN, unique=True),
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = redis_settings(get_settings().redis_url)
    max_tries = 3
