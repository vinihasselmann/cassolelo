"""GET /api/obras/{id}/events: eventos da obra em tempo real (Server-Sent Events, 8.1).

- Assina o canal da obra ANTES de repor o histórico, para não perder nada no meio.
- Reconexão: o cliente manda o último id recebido (cabeçalho Last-Event-ID ou
  ?last_event_id=) e recebe o que perdeu (até 1000 eventos guardados por obra).
- Heartbeat (comentário SSE) a cada SSE_HEARTBEAT_SECONDS (20 s): mantém a conexão viva
  em proxies e deixa o cliente perceber uma conexão morta.
- `retry: 3000`: um EventSource reconecta sozinho depois de 3 s.
- A sessão do banco só existe para checar usuário e obra (dependência com
  scope="function"): ela é devolvida ao pool ANTES de o fluxo começar. Sem isso cada
  aba aberta prenderia uma conexão do Postgres enquanto o SSE durasse.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import current_user
from app.db import get_session
from app.services import obras as obras_service
from app.services.events import EVENT_ID, EventBus, id_key

router = APIRouter(prefix="/obras", tags=["events"])

RETRY_MS = 3000


async def stream_events(
    request: Request, bus: EventBus, obra_id: int, last_id: str | None, heartbeat: float
) -> AsyncGenerator[str, None]:
    yield f"retry: {RETRY_MS}\n\n"
    async with bus.subscribe(obra_id) as sub:
        if last_id:
            for missed in await bus.replay(obra_id, last_id):
                yield missed.sse()
                last_id = missed.id
        yield ": conectado\n\n"
        while not await request.is_disconnected():
            ev = await sub.get(heartbeat)
            if ev is None:
                yield ": heartbeat\n\n"
                continue
            if last_id and id_key(ev.id) <= id_key(last_id):
                continue  # já entregue pela reposição
            yield ev.sse()
            last_id = ev.id


# Sessão curta: fechada quando a função da rota termina, antes do corpo em fluxo.
ShortSession = Annotated[AsyncSession, Depends(get_session, scope="function")]


async def authorize(obra_id: int, request: Request, session: ShortSession) -> None:
    """Usuário válido e obra existente (401/404), sem prender a conexão do banco."""
    await current_user(request, session)
    await obras_service.get_obra(session, obra_id)


@router.get("/{obra_id}/events", dependencies=[Depends(authorize, scope="function")])
async def obra_events(
    obra_id: int,
    request: Request,
    last_event_id: str | None = Query(default=None),
) -> StreamingResponse:
    """Eventos: version_ready, version_failed, values_changed, batch_applied,
    batch_undone, orphan_changed, param_def_changed (JSON em `data`)."""
    last = request.headers.get("last-event-id") or last_event_id
    if last and not EVENT_ID.match(last):
        last = None
    settings = request.app.state.settings
    return StreamingResponse(
        stream_events(
            request, request.app.state.events, obra_id, last, settings.sse_heartbeat_seconds
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
