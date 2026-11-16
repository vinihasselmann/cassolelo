"""POST /api/webhooks/aps: recebe eventos do APS (sem usuário; autenticado pela assinatura)."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status

from app.api.deps import QueueDep
from app.aps.webhooks import SIGNATURE_HEADER, verify_signature
from app.config import Settings
from app.db import SessionDep
from app.observability import metrics
from app.services import webhooks as service

log = logging.getLogger("app.api.webhooks")

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/aps")
async def aps_webhook(
    request: Request, session: SessionDep, queue: QueueDep, background: BackgroundTasks
) -> dict[str, str]:
    settings: Settings = request.app.state.settings
    secret = settings.aps_webhook_secret.get_secret_value()
    if not secret:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "APS_WEBHOOK_SECRET não configurado."
        )

    body = await request.body()
    if not verify_signature(secret, body, request.headers.get(SIGNATURE_HEADER)):
        log.warning("Webhook rejeitado: assinatura inválida")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Assinatura inválida.")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "JSON inválido.") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "O corpo deve ser um objeto JSON.")

    await metrics.incr("webhooks_received_total")
    await metrics.mark("webhook_received")
    event, obra = await service.record_event(
        session, body, payload, request.headers.get(service.DELIVERY_ID_HEADER)
    )
    if event is None:
        return {"status": "duplicate"}
    await session.commit()

    if obra is None:
        log.warning("Webhook %s sem obra correspondente; evento guardado.", event.id)
        return {"status": "no_obra"}
    # Enfileira depois de responder: a resposta não espera o Redis.
    background.add_task(service.enqueue_sync, queue, obra.id, event.id)
    return {"status": "queued"}
