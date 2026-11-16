"""Spike 0.5 - Criar, listar e apagar webhooks do sistema "data" (APS Webhooks).

Eventos: dm.version.added e dm.version.modified, com scope numa pasta.

USO (a partir da raiz do repositório, com spikes/.env preenchido):

    # 1) registrar o secret de assinatura (APS_WEBHOOK_SECRET) - faça ANTES de criar
    spikes/.venv/Scripts/python spikes/webhooks/manage_webhooks.py set-secret

    # 2) criar os dois hooks na pasta do projeto de teste
    spikes/.venv/Scripts/python spikes/webhooks/manage_webhooks.py create \
        --folder urn:adsk.wipprod:fs.folder:co.xxxx \
        --callback https://<seu-tunel>/hooks/aps --obra-id OBRA-TESTE

    # 3) listar / apagar
    spikes/.venv/Scripts/python spikes/webhooks/manage_webhooks.py list
    spikes/.venv/Scripts/python spikes/webhooks/manage_webhooks.py delete \
        --event dm.version.added --hook-id <id>
    spikes/.venv/Scripts/python spikes/webhooks/manage_webhooks.py delete --all

Usa token 2-legged com data:read. O token e o secret nunca são impressos.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

BASE_URL = "https://developer.api.autodesk.com"
TOKEN_PATH = "/authentication/v2/token"
SCOPES = "data:read"
WH = "/webhooks/v1"
SYSTEM = "data"
EVENTS = ("dm.version.added", "dm.version.modified")
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class WebhookError(Exception):
    pass


def get_token(http: httpx.Client, client_id: str, client_secret: str) -> str:
    resp = http.post(
        TOKEN_PATH,
        auth=(client_id, client_secret),
        data={"grant_type": "client_credentials", "scope": SCOPES},
        headers={"Accept": "application/json"},
    )
    if resp.status_code in (400, 401):
        raise WebhookError("credenciais APS inválidas (verifique spikes/.env)")
    if resp.is_error:
        raise WebhookError(f"erro HTTP {resp.status_code} ao obter token")
    return str(resp.json()["access_token"])


class WebhooksClient:
    def __init__(self, http: httpx.Client, token: str, region: str = "US") -> None:
        self._http = http
        self._headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        if region and region != "US":
            self._headers["x-ads-region"] = region

    def _check(self, resp: httpx.Response) -> None:
        if resp.status_code in (401, 403):
            raise WebhookError(
                f"Acesso negado (HTTP {resp.status_code}) em {resp.request.url.path}: "
                "app não liberado em Custom Integrations ou sem acesso à pasta."
            )
        if resp.is_error:
            raise WebhookError(
                f"Erro HTTP {resp.status_code} em {resp.request.url.path}: {resp.text[:300]}"
            )

    def create(self, event: str, folder: str, callback: str, obra_id: str) -> str | None:
        """Cria o hook e devolve o hookId (None se já existia)."""
        body = {
            "callbackUrl": callback,
            "scope": {"folder": folder},
            "hookAttribute": {"obra_id": obra_id},
        }
        resp = self._http.post(
            f"{WH}/systems/{SYSTEM}/events/{event}/hooks", headers=self._headers, json=body
        )
        if resp.status_code == 409:
            return None
        self._check(resp)
        location = resp.headers.get("location", "")
        return location.rstrip("/").rsplit("/", 1)[-1] or None

    def list(self) -> list[dict[str, Any]]:
        hooks: list[dict[str, Any]] = []
        url: str | None = f"{WH}/systems/{SYSTEM}/hooks"
        while url:
            resp = self._http.get(url, headers=self._headers)
            self._check(resp)
            body = resp.json()
            hooks.extend(body.get("data") or [])
            nxt = (body.get("links") or {}).get("next")
            if isinstance(nxt, dict):
                nxt = nxt.get("href")
            url = str(nxt) if nxt else None
        return hooks

    def delete(self, event: str, hook_id: str) -> None:
        resp = self._http.delete(
            f"{WH}/systems/{SYSTEM}/events/{event}/hooks/{hook_id}", headers=self._headers
        )
        self._check(resp)

    def set_secret(self, secret: str) -> str:
        """Registra o secret de assinatura do app; se já existir, atualiza."""
        resp = self._http.post(f"{WH}/tokens", headers=self._headers, json={"token": secret})
        if resp.status_code in (400, 409):
            resp = self._http.put(f"{WH}/tokens/@me", headers=self._headers, json={"token": secret})
            self._check(resp)
            return "atualizado"
        self._check(resp)
        return "criado"


def format_hook(h: dict[str, Any]) -> str:
    scope = (h.get("scope") or {}).get("folder", h.get("scope"))
    attr = h.get("hookAttribute") or {}
    return (
        f"{h.get('hookId')}  {h.get('event'):<22} {h.get('status', '?'):<9} "
        f"obra={attr.get('obra_id', '-')}  {h.get('callbackUrl')}  scope={scope}"
    )


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Gerencia webhooks APS do sistema data.")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create", help="cria hooks dm.version.added e dm.version.modified")
    c.add_argument("--folder", required=True, help="urn da pasta (scope)")
    c.add_argument("--callback", required=True, help="https://<túnel>/hooks/aps")
    c.add_argument("--obra-id", required=True, help="id da obra (vai no hookAttribute)")
    sub.add_parser("list", help="lista os hooks do sistema data deste app")
    d = sub.add_parser("delete", help="apaga um hook (ou todos com --all)")
    d.add_argument("--event", choices=EVENTS)
    d.add_argument("--hook-id")
    d.add_argument("--all", action="store_true")
    sub.add_parser("set-secret", help="registra APS_WEBHOOK_SECRET para assinatura")
    args = p.parse_args(argv)
    if args.cmd == "delete" and not args.all and not (args.event and args.hook_id):
        p.error("delete exige --event e --hook-id, ou --all")
    if args.cmd == "create" and not args.callback.endswith("/hooks/aps"):
        print("AVISO: o callback normalmente termina em /hooks/aps", file=sys.stderr)
    return args


def run(args: argparse.Namespace, wh: WebhooksClient) -> None:
    if args.cmd == "set-secret":
        secret = os.getenv("APS_WEBHOOK_SECRET", "").strip()
        if len(secret) < 16:
            raise WebhookError("Defina APS_WEBHOOK_SECRET (16+ caracteres) em spikes/.env")
        print(f"Secret de assinatura {wh.set_secret(secret)}.")
    elif args.cmd == "create":
        for event in EVENTS:
            hook_id = wh.create(event, args.folder, args.callback, args.obra_id)
            print(f"{event}: {'criado ' + hook_id if hook_id else 'já existia'}")
    elif args.cmd == "list":
        hooks = wh.list()
        print("\n".join(format_hook(h) for h in hooks) if hooks else "(nenhum hook)")
    elif args.cmd == "delete":
        targets = (
            [(str(h["event"]), str(h["hookId"])) for h in wh.list() if h.get("event") in EVENTS]
            if args.all
            else [(args.event, args.hook_id)]
        )
        for event, hook_id in targets:
            wh.delete(event, hook_id)
            print(f"apagado {hook_id} ({event})")
        if not targets:
            print("(nenhum hook para apagar)")


def main(argv: list[str] | None = None, http: httpx.Client | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args(argv)
    load_dotenv(ENV_FILE)
    client_id = os.getenv("APS_CLIENT_ID", "").strip()
    client_secret = os.getenv("APS_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        print(f"Defina APS_CLIENT_ID e APS_CLIENT_SECRET em {ENV_FILE}", file=sys.stderr)
        return 2
    region = os.getenv("APS_REGION", "US").strip().upper() or "US"
    own = http is None
    http = http or httpx.Client(base_url=BASE_URL, timeout=30.0)
    try:
        run(args, WebhooksClient(http, get_token(http, client_id, client_secret), region))
    except WebhookError as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 1
    except httpx.HTTPError as exc:
        print(f"ERRO de rede: {exc.__class__.__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        if own:
            http.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
