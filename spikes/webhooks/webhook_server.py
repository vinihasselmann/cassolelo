"""Spike 0.5 - Receptor de webhooks do APS.

POST /hooks/aps
    Valida x-adsk-signature (HMAC-SHA1 do corpo bruto com APS_WEBHOOK_SECRET),
    responde 200 imediatamente e grava o payload em spikes/out/webhooks.log
    (uma linha JSON por evento) em segundo plano.
    Assinatura ausente/inválida -> 401. Secret não configurado -> 503.

Rodar (a partir da raiz do repositório):
    spikes/.venv/Scripts/python spikes/webhooks/webhook_server.py
Veja spikes/webhooks/README.md para expor a porta com ngrok ou Cloudflare Tunnel.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
LOG_FILE = Path(__file__).resolve().parent.parent / "out" / "webhooks.log"
SIGNATURE_HEADER = "x-adsk-signature"
SIGNATURE_PREFIX = "sha1hash="

_log_lock = threading.Lock()


def compute_signature(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha1).hexdigest()
    return SIGNATURE_PREFIX + digest


def verify_signature(secret: str, body: bytes, header: str | None) -> bool:
    if not header:
        return False
    received = header.strip().lower()
    if not received.startswith(SIGNATURE_PREFIX):
        received = SIGNATURE_PREFIX + received
    return hmac.compare_digest(received, compute_signature(secret, body))


def append_log(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False)
    with _log_lock, path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def summarize(payload: dict[str, Any]) -> dict[str, Any]:
    hook = payload.get("hook") or {}
    inner = payload.get("payload") or {}
    return {
        "event": hook.get("event"),
        "hook_id": hook.get("hookId"),
        "obra_id": (hook.get("hookAttribute") or {}).get("obra_id"),
        "resource_urn": payload.get("resourceUrn"),
        "name": inner.get("name"),
        "version": inner.get("version"),
    }


def create_app(secret: str | None = None, log_path: Path | None = None) -> FastAPI:
    load_dotenv(ENV_FILE)
    hook_secret = secret if secret is not None else os.getenv("APS_WEBHOOK_SECRET", "").strip()
    target = log_path or LOG_FILE
    app = FastAPI(title="Spike Webhooks")

    @app.get("/health")
    def health() -> dict[str, bool]:
        return {"ok": True, "secret_configured": bool(hook_secret)}

    @app.post("/hooks/aps")
    async def hooks_aps(request: Request, background: BackgroundTasks) -> dict[str, bool]:
        if not hook_secret:
            raise HTTPException(503, "APS_WEBHOOK_SECRET não configurado")
        body = await request.body()
        if not verify_signature(hook_secret, body, request.headers.get(SIGNATURE_HEADER)):
            print("webhook rejeitado: assinatura inválida", file=sys.stderr)
            raise HTTPException(401, "assinatura inválida")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise HTTPException(400, "JSON inválido") from exc
        if not isinstance(payload, dict):
            raise HTTPException(400, "payload deve ser um objeto JSON")
        record = {
            "received_at": datetime.now(UTC).isoformat(),
            **summarize(payload),
            "payload": payload,
        }
        background.add_task(append_log, target, record)
        return {"ok": True}

    return app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(create_app(), host="127.0.0.1", port=8001)
