"""Eventos em tempo real por obra (Fase 8.1).

Uso nos serviços (dentro da transação, antes do commit):

    events.emit(session, obra_id, "values_changed", {...}, actor)

O evento só é PUBLICADO depois do COMMIT (gancho after_commit da sessão); num rollback
ele é descartado. Assim ninguém recebe aviso de algo que não foi gravado.

Barramento:
- RedisEventBus: XADD num stream por obra (histórico curto, para a reconexão com
  Last-Event-ID) + PUBLISH no canal da obra (entrega ao vivo). O id do evento é o id do
  stream ("1731350000000-0"), crescente.
- MemoryEventBus: o mesmo contrato em memória (testes e desenvolvimento sem Redis).

Tipos: version_ready, version_failed, values_changed, batch_applied, batch_undone,
orphan_changed, param_def_changed e, por peça (P2), unit_values_changed,
unit_batch_applied, unit_batch_undone.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
from collections import defaultdict
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import event as sa_event
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models import User

log = logging.getLogger("app.events")

EVENT_TYPES = frozenset(
    {
        "version_ready",
        "version_failed",
        "values_changed",
        "batch_applied",
        "batch_undone",
        "orphan_changed",
        "param_def_changed",
        # parâmetros por peça (P2)
        "unit_values_changed",
        "unit_batch_applied",
        "unit_batch_undone",
        "unit_orphan_changed",  # P5: unidade órfã religada ou arquivada
        "obra_file_state",  # arquivo da obra excluído / restaurado / sumiu do Docs
        "units_renumbered",  # numeração pela sequência de montagem / ligações refeitas
    }
)
EVENT_ID = re.compile(r"^\d{1,20}-\d{1,20}$")
_PENDING = "pending_events"


@dataclass(frozen=True)
class Event:
    id: str
    obra_id: int
    type: str
    data: dict[str, Any]  # inclui "type", "obra_id", "at" e "actor" ({id, name} ou None)

    def sse(self) -> str:
        body = json.dumps(self.data, ensure_ascii=False, separators=(",", ":"), default=str)
        return f"id: {self.id}\nevent: {self.type}\ndata: {body}\n\n"


def id_key(event_id: str) -> tuple[int, int]:
    ms, seq = event_id.split("-")
    return int(ms), int(seq)


class Subscription(Protocol):
    async def get(self, wait_seconds: float) -> Event | None:
        """Próximo evento ao vivo, ou None se nada chegou em `wait_seconds` segundos."""


class EventBus(Protocol):
    async def publish(self, obra_id: int, type_: str, data: dict[str, Any]) -> Event: ...

    async def replay(self, obra_id: int, after_id: str) -> list[Event]: ...

    def subscribe(self, obra_id: int) -> contextlib.AbstractAsyncContextManager[Subscription]: ...

    async def close(self) -> None: ...


# --------------------------------------------------------------------------- memória


class _MemorySubscription:
    def __init__(self) -> None:
        self.queue: asyncio.Queue[Event] = asyncio.Queue()

    async def get(self, wait_seconds: float) -> Event | None:
        try:
            return await asyncio.wait_for(self.queue.get(), wait_seconds)
        except TimeoutError:
            return None


class MemoryEventBus:
    """Mesmo contrato do Redis, em memória (um processo)."""

    def __init__(self, maxlen: int = 1000) -> None:
        self.maxlen = maxlen
        self.history: dict[int, list[Event]] = defaultdict(list)
        self.subscribers: dict[int, set[_MemorySubscription]] = defaultdict(set)
        self._ms = 0
        self._seq = 0

    def _next_id(self) -> str:
        now = int(datetime.now(UTC).timestamp() * 1000)
        if now > self._ms:
            self._ms, self._seq = now, 0
        else:
            self._seq += 1
        return f"{self._ms}-{self._seq}"

    async def publish(self, obra_id: int, type_: str, data: dict[str, Any]) -> Event:
        ev = Event(self._next_id(), obra_id, type_, data)
        hist = self.history[obra_id]
        hist.append(ev)
        del hist[: max(0, len(hist) - self.maxlen)]
        for sub in list(self.subscribers[obra_id]):
            sub.queue.put_nowait(ev)
        return ev

    async def replay(self, obra_id: int, after_id: str) -> list[Event]:
        after = id_key(after_id)
        return [e for e in self.history[obra_id] if id_key(e.id) > after]

    @contextlib.asynccontextmanager
    async def subscribe(self, obra_id: int) -> AsyncIterator[Subscription]:
        sub = _MemorySubscription()
        self.subscribers[obra_id].add(sub)
        try:
            yield sub
        finally:
            self.subscribers[obra_id].discard(sub)

    async def close(self) -> None:
        return None


# --------------------------------------------------------------------------- Redis


class _RedisSubscription:
    def __init__(self, pubsub: Any, obra_id: int) -> None:
        self.pubsub = pubsub
        self.obra_id = obra_id

    async def get(self, wait_seconds: float) -> Event | None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + wait_seconds
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                return None
            msg = await self.pubsub.get_message(
                ignore_subscribe_messages=True, timeout=min(remaining, 1.0)
            )
            if msg is None or msg.get("type") != "message":
                continue
            raw = json.loads(msg["data"])
            return Event(raw["id"], self.obra_id, raw["type"], raw["data"])


class RedisEventBus:
    def __init__(self, url: str, maxlen: int = 1000, ttl_seconds: int = 7 * 24 * 3600) -> None:
        from redis.asyncio import Redis

        self.redis = Redis.from_url(url, decode_responses=True)
        self.maxlen = maxlen
        self.ttl = ttl_seconds

    @staticmethod
    def stream_key(obra_id: int) -> str:
        return f"obra:{obra_id}:events"

    @staticmethod
    def channel(obra_id: int) -> str:
        return f"obra:{obra_id}:live"

    async def publish(self, obra_id: int, type_: str, data: dict[str, Any]) -> Event:
        body = json.dumps(data, ensure_ascii=False, default=str)
        key = self.stream_key(obra_id)
        event_id = await self.redis.xadd(
            key, {"type": type_, "data": body}, maxlen=self.maxlen, approximate=True
        )
        await self.redis.expire(key, self.ttl)
        payload = json.dumps({"id": event_id, "type": type_, "data": json.loads(body)})
        await self.redis.publish(self.channel(obra_id), payload)
        return Event(event_id, obra_id, type_, json.loads(body))

    async def replay(self, obra_id: int, after_id: str) -> list[Event]:
        rows = await self.redis.xrange(self.stream_key(obra_id), min=f"({after_id}", max="+")
        return [
            Event(event_id, obra_id, fields["type"], json.loads(fields["data"]))
            for event_id, fields in rows
        ]

    @contextlib.asynccontextmanager
    async def subscribe(self, obra_id: int) -> AsyncIterator[Subscription]:
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(self.channel(obra_id))
        try:
            yield _RedisSubscription(pubsub, obra_id)
        finally:
            await pubsub.unsubscribe(self.channel(obra_id))
            await pubsub.aclose()

    async def close(self) -> None:
        await self.redis.aclose()


# --------------------------------------------------------------------------- emissão


_bus: EventBus | None = None
_tasks: set[asyncio.Task[Any]] = set()


def configure(bus: EventBus | None) -> None:
    """Barramento usado na publicação (API e worker configuram na inicialização)."""
    global _bus
    _bus = bus


def current_bus() -> EventBus | None:
    return _bus


def actor_info(actor: User | None) -> dict[str, Any] | None:
    return {"id": actor.id, "name": actor.name} if actor is not None else None


def emit(
    session: AsyncSession | Session,
    obra_id: int,
    type_: str,
    data: dict[str, Any],
    actor: User | None = None,
) -> None:
    """Agenda um evento para depois do commit desta sessão."""
    if type_ not in EVENT_TYPES:
        raise ValueError(f"Tipo de evento desconhecido: {type_}")
    sync = session.sync_session if isinstance(session, AsyncSession) else session
    payload = {
        "type": type_,
        "obra_id": obra_id,
        "at": datetime.now(UTC).isoformat(),
        "actor": actor_info(actor),
        **data,
    }
    sync.info.setdefault(_PENDING, []).append((obra_id, type_, payload))


async def _publish_all(bus: EventBus, items: list[tuple[int, str, dict[str, Any]]]) -> None:
    for obra_id, type_, payload in items:
        try:
            await bus.publish(obra_id, type_, payload)
        except Exception:  # aviso em tempo real não pode derrubar a gravação
            log.exception("Falha ao publicar o evento %s da obra %s", type_, obra_id)


@sa_event.listens_for(Session, "after_commit")
def _after_commit(session: Session) -> None:
    items = session.info.pop(_PENDING, None)
    if not items or _bus is None:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:  # pragma: no cover - sessão síncrona fora de um loop
        return
    task = loop.create_task(_publish_all(_bus, items))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


@sa_event.listens_for(Session, "after_rollback")
def _after_rollback(session: Session) -> None:
    session.info.pop(_PENDING, None)


async def drain() -> None:
    """Espera as publicações pendentes (testes e desligamento)."""
    while _tasks:
        await asyncio.gather(*list(_tasks), return_exceptions=True)
