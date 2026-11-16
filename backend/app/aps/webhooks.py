"""APS Webhooks (sistema "data"): criar, listar e apagar hooks; secret de assinatura.

Baseado em spikes/webhooks/. Usa o mesmo token 2-legged (data:read).
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Any

from app.aps.client import ApsClient

WH = "/webhooks/v1"
SYSTEM = "data"
VERSION_EVENTS = ("dm.version.added", "dm.version.modified")
SIGNATURE_HEADER = "x-adsk-signature"
SIGNATURE_PREFIX = "sha1hash="


# --------------------------------------------------------------------------- assinatura


def compute_signature(secret: str, body: bytes) -> str:
    return SIGNATURE_PREFIX + hmac.new(secret.encode("utf-8"), body, hashlib.sha1).hexdigest()


def verify_signature(secret: str, body: bytes, header: str | None) -> bool:
    """HMAC-SHA1 do corpo bruto com o secret registrado no APS."""
    if not secret or not header:
        return False
    received = header.strip().lower()
    if not received.startswith(SIGNATURE_PREFIX):
        received = SIGNATURE_PREFIX + received
    return hmac.compare_digest(received, compute_signature(secret, body))


# --------------------------------------------------------------------------- API


def _region_headers(c: ApsClient) -> dict[str, str]:
    return {"x-ads-region": c.region} if c.region != "US" else {}


async def create_hook(
    c: ApsClient, event: str, folder_id: str, callback_url: str, attributes: dict[str, Any]
) -> str | None:
    """Cria o hook. Devolve o hookId, ou None se já existia (409)."""
    resp = await c.request(
        "POST",
        f"{WH}/systems/{SYSTEM}/events/{event}/hooks",
        json={
            "callbackUrl": callback_url,
            "scope": {"folder": folder_id},
            "hookAttribute": attributes,
            "autoReactivateHook": True,
        },
        headers=_region_headers(c),
        allow_status=(409,),
    )
    if resp.status_code == 409:
        return None
    location = resp.headers.get("location", "")
    return location.rstrip("/").rsplit("/", 1)[-1] or None


async def list_hooks(c: ApsClient) -> list[dict[str, Any]]:
    hooks: list[dict[str, Any]] = []
    async for hook in _paginate(c, f"{WH}/systems/{SYSTEM}/hooks"):
        hooks.append(hook)
    return hooks


async def _paginate(c: ApsClient, path: str) -> Any:
    url: str | None = path
    while url:
        resp = await c.request("GET", url, headers=_region_headers(c))
        body = resp.json()
        for item in body.get("data") or []:
            yield item
        nxt = (body.get("links") or {}).get("next")
        url = nxt.get("href") if isinstance(nxt, dict) else nxt


async def delete_hook(c: ApsClient, event: str, hook_id: str) -> None:
    await c.request(
        "DELETE",
        f"{WH}/systems/{SYSTEM}/events/{event}/hooks/{hook_id}",
        headers=_region_headers(c),
    )


async def set_secret(c: ApsClient, secret: str) -> str:
    """Registra o secret de assinatura do app (ou atualiza, se já existir)."""
    resp = await c.request(
        "POST",
        f"{WH}/tokens",
        json={"token": secret},
        headers=_region_headers(c),
        allow_status=(400, 409),
    )
    if resp.status_code in (400, 409):
        await c.request(
            "PUT", f"{WH}/tokens/@me", json={"token": secret}, headers=_region_headers(c)
        )
        return "atualizado"
    return "criado"
