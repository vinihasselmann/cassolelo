"""Webhooks do APS: recebimento (eventos -> obra -> job de sync) e registro por obra."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.aps import webhooks as wh
from app.aps.client import ApsClient
from app.models import Obra, WebhookEvent
from app.workers.queue import JobQueue

log = logging.getLogger("app.services.webhooks")

SYNC_OBRA_JOB = "sync_obra"
DELIVERY_ID_HEADER = "x-adsk-delivery-id"


# --------------------------------------------------------------------------- recebimento


def event_id_for(body: bytes, delivery_id: str | None) -> str:
    """Id do evento para idempotência.

    O APS não documenta um id único de entrega: usamos o header de entrega quando vier
    e, senão, o SHA-256 do corpo (reenvios do mesmo evento têm o mesmo corpo).
    """
    if delivery_id and delivery_id.strip():
        return f"delivery:{delivery_id.strip()}"[:255]
    return "sha256:" + hashlib.sha256(body).hexdigest()


def _obra_id_from_attributes(payload: dict[str, Any]) -> int | None:
    attrs = (payload.get("hook") or {}).get("hookAttribute") or {}
    raw = attrs.get("obra_id")
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


async def find_obra(session: AsyncSession, payload: dict[str, Any]) -> Obra | None:
    """Obra do evento. O ARQUIVO manda: pasta + lineage do evento identificam a obra
    (várias obras podem dividir a mesma pasta e, portanto, o mesmo hook). Sem lineage
    conclusivo, vale o hookAttribute.obra_id; por último, a única obra da pasta."""
    hook = payload.get("hook") or {}
    inner = payload.get("payload") or {}
    folder = inner.get("parentFolderUrn") or (hook.get("scope") or {}).get("folder")
    lineage = inner.get("lineageUrn")
    in_folder: list[Obra] = []
    if folder:
        in_folder = list(await session.scalars(select(Obra).where(Obra.acc_folder_id == folder)))
        if lineage:
            same_file = [o for o in in_folder if o.acc_item_id == lineage]
            if len(same_file) == 1:
                return same_file[0]
            if in_folder and not same_file:
                return None  # arquivo da pasta que não é de nenhuma obra

    obra_id = _obra_id_from_attributes(payload)
    if obra_id is not None:
        obra = await session.get(Obra, obra_id)
        if obra is not None:
            return obra
    return in_folder[0] if len(in_folder) == 1 else None


async def record_event(
    session: AsyncSession, body: bytes, payload: dict[str, Any], delivery_id: str | None
) -> tuple[WebhookEvent | None, Obra | None]:
    """Grava o evento. Devolve (None, None) se for repetido. Não faz commit."""
    obra = await find_obra(session, payload)
    stmt = (
        pg_insert(WebhookEvent)
        .values(
            event_id=event_id_for(body, delivery_id),
            payload=payload,
            obra_id=obra.id if obra else None,
        )
        .on_conflict_do_nothing(index_elements=["event_id"])
        .returning(WebhookEvent.id)
    )
    new_id = await session.scalar(stmt)
    if new_id is None:
        return None, None
    return await session.get(WebhookEvent, new_id), obra


async def enqueue_sync(queue: JobQueue, obra_id: int, event_row_id: int) -> None:
    try:
        await queue.enqueue(
            SYNC_OBRA_JOB, obra_id, event_row_id, job_id=f"{SYNC_OBRA_JOB}:{obra_id}:{event_row_id}"
        )
    except Exception:
        # A verificação periódica (10 min) encontra a versão mesmo assim.
        log.exception("Falha ao enfileirar %s para a obra %s", SYNC_OBRA_JOB, obra_id)


async def mark_processed(session: AsyncSession, event_row_id: int) -> None:
    event = await session.get(WebhookEvent, event_row_id)
    if event is not None and event.processed_at is None:
        event.processed_at = datetime.now(UTC)
        await session.commit()


# --------------------------------------------------------------------------- registro


def _hooks_of_obra(hooks: list[dict[str, Any]], obra: Obra) -> list[dict[str, Any]]:
    out = []
    for h in hooks:
        attrs = h.get("hookAttribute") or {}
        if str(attrs.get("obra_id")) == str(obra.id) and h.get("event") in wh.VERSION_EVENTS:
            out.append(h)
    return out


async def register_obra_hooks(
    aps: ApsClient, obra: Obra, callback_url: str
) -> dict[str, str | None]:
    """Registra dm.version.added e dm.version.modified na pasta da obra.

    Devolve {evento: hookId} (None = já existia)."""
    if not obra.acc_folder_id:
        raise ValueError("A obra não tem pasta do Docs vinculada.")
    return {
        event: await wh.create_hook(
            aps, event, obra.acc_folder_id, callback_url, {"obra_id": str(obra.id)}
        )
        for event in wh.VERSION_EVENTS
    }


async def list_obra_hooks(aps: ApsClient, obra: Obra | None = None) -> list[dict[str, Any]]:
    hooks = await wh.list_hooks(aps)
    return _hooks_of_obra(hooks, obra) if obra is not None else hooks


async def delete_obra_hooks(aps: ApsClient, obra: Obra) -> list[str]:
    deleted = []
    for h in await list_obra_hooks(aps, obra):
        await wh.delete_hook(aps, str(h["event"]), str(h["hookId"]))
        deleted.append(str(h["hookId"]))
    return deleted


@dataclass
class ReregisterResult:
    deleted: list[str]  # hookIds apagados (URL antiga)
    created: dict[int, dict[str, str | None]]  # obra -> {evento: hookId | None já existia}
    skipped: dict[int, str]  # obra -> motivo


async def reregister_all_hooks(
    aps: ApsClient, obras: list[Obra], callback_url: str
) -> ReregisterResult:
    """Troca de URL pública (10.3): apaga os hooks de versão que apontam para outra URL
    e registra os de todas as obras ativas com pasta. Idempotente (409 = já existia).

    A lista de hooks do APS é só deste app (client_id): nada de outros apps é apagado."""
    deleted: list[str] = []
    for h in await wh.list_hooks(aps):
        if h.get("event") in wh.VERSION_EVENTS and h.get("callbackUrl") != callback_url:
            await wh.delete_hook(aps, str(h["event"]), str(h["hookId"]))
            deleted.append(str(h["hookId"]))
    created: dict[int, dict[str, str | None]] = {}
    skipped: dict[int, str] = {}
    for obra in obras:
        if not obra.active:
            skipped[obra.id] = "inativa"
        elif not obra.acc_folder_id:
            skipped[obra.id] = "sem pasta do Docs"
        else:
            created[obra.id] = await register_obra_hooks(aps, obra, callback_url)
    return ReregisterResult(deleted, created, skipped)
