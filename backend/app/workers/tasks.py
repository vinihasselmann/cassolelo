"""Jobs executados pelo worker Arq.

O contexto (`ctx`) recebe, no startup do worker: settings, sessionmaker, aps e queue.
Cada job abre a própria sessão; a lógica fica nos serviços (testados à parte).
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.aps.client import ApsClient
from app.config import Settings
from app.observability import alerts
from app.observability.logging import bind
from app.services import processing, translation, versions, webhooks
from app.workers.queue import JobQueue

log = logging.getLogger("app.workers")


def _deps(ctx: dict[str, Any]) -> tuple[async_sessionmaker[AsyncSession], ApsClient, JobQueue]:
    return ctx["sessionmaker"], ctx["aps"], ctx["queue"]


async def process_version(
    ctx: dict[str, Any],
    version_id: int,
    orphan_missing: bool = False,
    actor_id: int | None = None,
) -> str | None:
    """Propriedades do derivativo -> elements + marks; status processing -> ready/failed.
    `orphan_missing=True` quando a regra de identificação da obra mudou."""
    maker, aps, _ = _deps(ctx)
    settings: Settings = ctx["settings"]
    bind(job="process_version", version=version_id)
    async with maker() as session:
        result = await processing.process_version(
            session,
            aps,
            version_id,
            processing.ProcessingConfig.from_settings(settings),
            orphan_missing=orphan_missing,
            actor_id=actor_id,
        )
    return result.status if result else None


async def sync_obra(ctx: dict[str, Any], obra_id: int, event_row_id: int | None = None) -> None:
    """Disparado por webhook: sincroniza as versões da obra e marca o evento como processado."""
    maker, aps, queue = _deps(ctx)
    bind(job="sync_obra", obra=obra_id)
    async with maker() as session:
        result = await versions.sync_versions(session, aps, queue, obra_id)
        if event_row_id is not None:
            await webhooks.mark_processed(session, event_row_id)
    log.info("sync_obra(%s): %s versão(ões) nova(s)", obra_id, len(result.created_ids))


async def sync_all_obras(ctx: dict[str, Any]) -> None:
    """Cron a cada 10 min: reserva caso algum webhook se perca."""
    maker, aps, queue = _deps(ctx)
    async with maker() as session:
        synced = await versions.sync_all_obras(session, aps, queue)
    log.info("sync_all_obras: %s obra(s) verificada(s)", len(synced))


async def check_translations(ctx: dict[str, Any]) -> None:
    """Cron a cada 2 min: reconsulta versões em conversão no Docs (até 2 h)."""
    maker, aps, queue = _deps(ctx)
    async with maker() as session:
        counts = await translation.recheck_translating(session, aps, queue)
    if any(counts.values()):
        log.info("check_translations: %s", counts)


async def check_alerts(ctx: dict[str, Any]) -> None:
    """Cron a cada 5 min: versão failed, sem conversão > 2 h, webhooks parados, APS 401/403."""
    maker = ctx["sessionmaker"]
    settings: Settings = ctx["settings"]
    bind(job="check_alerts")
    async with maker() as session:
        sent = await alerts.run_checks(
            session, ctx["metrics"], settings, alerts.notifiers_from_settings(settings)
        )
    if sent:
        log.info("check_alerts: %s alerta(s) enviado(s)", len(sent))
