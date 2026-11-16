"""Token 2-legged (client_credentials) com cache em memória.

Escopos permitidos até a Fase 10: data:read e viewables:read (CLAUDE.md).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass

import httpx
from pydantic import SecretStr

from app.aps.errors import ApsAuthError, ApsError, ApsForbiddenError

TOKEN_PATH = "/authentication/v2/token"  # noqa: S105 (caminho, não senha)
ALLOWED_SCOPES = frozenset({"data:read", "viewables:read"})
READ_SCOPES: tuple[str, ...] = ("data:read", "viewables:read")
VIEWER_SCOPES: tuple[str, ...] = ("viewables:read",)


@dataclass(frozen=True)
class AccessToken:
    value: str
    expires_at: float  # relógio monotônico

    def __repr__(self) -> str:  # nunca expor o token em logs/tracebacks
        return f"AccessToken(expires_at={self.expires_at:.0f})"


def scope_key(scopes: Iterable[str]) -> str:
    unique = sorted(set(scopes))
    if not unique:
        raise ValueError("informe ao menos um escopo")
    invalid = set(unique) - ALLOWED_SCOPES
    if invalid:
        raise ValueError(f"escopos não permitidos: {sorted(invalid)}")
    return " ".join(unique)


class TokenProvider:
    def __init__(
        self,
        *,
        client_id: str,
        client_secret: SecretStr,
        http: httpx.AsyncClient,
        clock: Callable[[], float] = time.monotonic,
        margin_seconds: float = 60.0,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._http = http
        self._clock = clock
        self._margin = margin_seconds
        self._cache: dict[str, AccessToken] = {}
        self._lock = asyncio.Lock()

    async def get_token(self, scopes: Iterable[str] = READ_SCOPES) -> str:
        token, _ttl = await self.get_token_with_ttl(scopes)
        return token

    async def get_token_with_ttl(self, scopes: Iterable[str] = READ_SCOPES) -> tuple[str, int]:
        key = scope_key(scopes)
        async with self._lock:
            now = self._clock()
            cached = self._cache.get(key)
            if cached is None or now >= cached.expires_at - self._margin:
                cached = await self._fetch(key, now)
                self._cache[key] = cached
            return cached.value, int(cached.expires_at - now)

    def invalidate(self, scopes: Iterable[str] = READ_SCOPES) -> None:
        self._cache.pop(scope_key(scopes), None)

    async def _fetch(self, scope: str, now: float) -> AccessToken:
        if not self._client_id or not self._client_secret.get_secret_value():
            raise ApsAuthError("APS_CLIENT_ID/APS_CLIENT_SECRET não configurados.")
        resp = await self._http.post(
            TOKEN_PATH,
            auth=(self._client_id, self._client_secret.get_secret_value()),
            data={"grant_type": "client_credentials", "scope": scope},
            headers={"Accept": "application/json"},
        )
        if resp.status_code in (400, 401):
            raise ApsAuthError(f"Falha na autenticação APS (HTTP {resp.status_code}).")
        if resp.status_code == 403:
            raise ApsForbiddenError("App APS sem permissão para obter token (HTTP 403).")
        if resp.is_error:
            raise ApsError(f"Erro HTTP {resp.status_code} ao obter token APS.")
        body = resp.json()
        value = body.get("access_token")
        if not isinstance(value, str) or not value:
            raise ApsError("Resposta de token APS sem access_token.")
        return AccessToken(value=value, expires_at=now + float(body.get("expires_in", 3599)))
