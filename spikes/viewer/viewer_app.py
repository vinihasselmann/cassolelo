"""Spike 0.4 - Servidor mínimo para abrir um URN no Autodesk Viewer v7.

GET /token   token 2-legged SOMENTE com viewables:read, em cache até expirar
GET /config  nomes do parâmetro de marca (MARK_PROPERTY_NAMES) para a página
GET /        index.html (abre ?urn=<urn base64>)

Rodar (a partir da raiz do repositório):
    spikes/.venv/Scripts/python spikes/viewer/viewer_app.py
e abrir http://localhost:8000/?urn=<URN>   (veja spikes/viewer/README.md)
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse

BASE_URL = "https://developer.api.autodesk.com"
TOKEN_PATH = "/authentication/v2/token"
VIEWER_SCOPE = "viewables:read"
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
INDEX_HTML = Path(__file__).resolve().parent / "index.html"


class TokenError(Exception):
    pass


def fetch_viewer_token(
    client_id: str, client_secret: str, http: httpx.Client | None = None
) -> tuple[str, int]:
    own = http is None
    http = http or httpx.Client(base_url=BASE_URL, timeout=30.0)
    try:
        resp = http.post(
            TOKEN_PATH,
            auth=(client_id, client_secret),
            data={"grant_type": "client_credentials", "scope": VIEWER_SCOPE},
            headers={"Accept": "application/json"},
        )
    finally:
        if own:
            http.close()
    if resp.status_code in (400, 401):
        raise TokenError("credenciais APS inválidas (verifique spikes/.env)")
    if resp.status_code == 403:
        raise TokenError("app não liberado em Custom Integrations")
    if resp.is_error:
        raise TokenError(f"erro HTTP {resp.status_code} ao obter token")
    body = resp.json()
    return str(body["access_token"]), int(body.get("expires_in", 3599))


class TokenCache:
    """Reaproveita o token até `margin` segundos antes de expirar."""

    def __init__(
        self,
        fetch: Callable[[], tuple[str, int]],
        clock: Callable[[], float] = time.monotonic,
        margin: float = 60.0,
    ) -> None:
        self._fetch = fetch
        self._clock = clock
        self._margin = margin
        self._lock = threading.Lock()
        self._token: str | None = None
        self._expires_at = 0.0

    def get(self) -> tuple[str, int]:
        with self._lock:
            now = self._clock()
            if self._token is None or now >= self._expires_at - self._margin:
                token, ttl = self._fetch()
                self._token, self._expires_at = token, now + ttl
            return self._token, int(self._expires_at - now)


def mark_names_from_env() -> list[str]:
    raw = os.getenv("MARK_PROPERTY_NAMES", "Marca,Mark")
    return [s.strip() for s in raw.split(",") if s.strip()]


def create_app(cache: TokenCache | None = None, mark_names: list[str] | None = None) -> FastAPI:
    load_dotenv(ENV_FILE)
    if cache is None:
        client_id = os.getenv("APS_CLIENT_ID", "").strip()
        client_secret = os.getenv("APS_CLIENT_SECRET", "").strip()
        cache = TokenCache(lambda: fetch_viewer_token(client_id, client_secret))
    names = mark_names if mark_names is not None else mark_names_from_env()
    region = os.getenv("APS_REGION", "US").strip().upper() or "US"
    token_cache = cache

    app = FastAPI(title="Spike Viewer")

    @app.get("/token")
    def token() -> JSONResponse:
        try:
            access_token, expires_in = token_cache.get()
        except TokenError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        body: dict[str, Any] = {
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": expires_in,
        }
        return JSONResponse(body, headers={"Cache-Control": "no-store"})

    @app.get("/config")
    def config() -> dict[str, Any]:
        return {"mark_property_names": names, "region": region}

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(INDEX_HTML, media_type="text/html")

    return app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(create_app(), host="127.0.0.1", port=8000)
