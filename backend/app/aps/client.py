"""Cliente HTTP do APS: retentativas, timeout, log sem tokens e chamadas proibidas.

Regras do projeto aplicadas aqui (não negociáveis):
- NUNCA POST /modelderivative/v2/designdata/job (pago e bloqueado no Docs).
- NUNCA AEC Data Model API (paga).
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Collection, Iterable
from typing import Any

import httpx

from app.aps.auth import READ_SCOPES, TokenProvider
from app.aps.errors import (
    NOT_PROVISIONED_MSG,
    ApsError,
    ApsForbiddenError,
    ApsForbiddenOperationError,
    ApsHttpError,
    ApsNotFoundError,
)

log = logging.getLogger("app.aps")

_FORBIDDEN: tuple[tuple[str | None, re.Pattern[str], str], ...] = (
    (
        "POST",
        re.compile(r"/modelderivative/v2/(regions/[^/]+/)?designdata/job/?$", re.IGNORECASE),
        "POST /designdata/job é proibido: o Docs converte os modelos (CLAUDE.md).",
    ),
    (
        None,
        re.compile(r"^/aec/", re.IGNORECASE),
        "AEC Data Model API é proibida (paga) (CLAUDE.md).",
    ),
)

MD_PREFIX = {
    "US": "/modelderivative/v2/designdata",
    "EMEA": "/modelderivative/v2/regions/eu/designdata",
    "AUS": "/modelderivative/v2/regions/aus/designdata",
}


def check_allowed(method: str, path: str) -> None:
    url_path = httpx.URL(path).path
    for verb, pattern, msg in _FORBIDDEN:
        if (verb is None or method.upper() == verb) and pattern.search(url_path):
            raise ApsForbiddenOperationError(msg)


class ApsClient:
    def __init__(
        self,
        *,
        http: httpx.AsyncClient,
        tokens: TokenProvider,
        region: str = "US",
        max_retries: int = 4,
        backoff_base: float = 0.5,
        backoff_max: float = 30.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if region not in MD_PREFIX:
            raise ValueError(f"região APS inválida: {region}")
        self.http = http
        self.tokens = tokens
        self.region = region
        self.md_prefix = MD_PREFIX[region]
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._backoff_max = backoff_max
        self._sleep = sleep
        # Chamados com cada erro do APS antes de propagar (métricas/alertas, Fase 10.1).
        self.error_hooks: list[Callable[[ApsError], Awaitable[None]]] = []

    def _delay(self, attempt: int, retry_after: str | None) -> float:
        if retry_after:
            try:
                return min(float(retry_after), self._backoff_max)
            except ValueError:
                pass
        exp = self._backoff_base * float(2**attempt)
        return min(exp + random.uniform(0, self._backoff_base), self._backoff_max)  # noqa: S311

    async def request(
        self,
        method: str,
        path: str,
        *,
        scopes: Iterable[str] = READ_SCOPES,
        params: dict[str, str] | None = None,
        json: Any = None,
        allow_status: Collection[int] = (),
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        try:
            return await self._request(
                method,
                path,
                scopes=scopes,
                params=params,
                json=json,
                allow_status=allow_status,
                headers=headers,
            )
        except ApsError as exc:
            for hook in self.error_hooks:
                try:
                    await hook(exc)
                except Exception:  # gancho de observabilidade nunca derruba a chamada
                    log.warning("Gancho de erro do APS falhou", exc_info=True)
            raise

    async def _request(
        self,
        method: str,
        path: str,
        *,
        scopes: Iterable[str] = READ_SCOPES,
        params: dict[str, str] | None = None,
        json: Any = None,
        allow_status: Collection[int] = (),
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        """Faz a chamada e devolve a resposta 2xx (ou um status em `allow_status`).

        Repete com backoff exponencial em 429, 5xx e falhas de rede. Em 401
        renova o token uma vez. Mapeia 401/403/404 para exceções claras.
        """
        check_allowed(method, path)
        scopes = tuple(scopes)
        attempt = 0
        renewed = False
        while True:
            token = await self.tokens.get_token(scopes)
            started = time.perf_counter()
            try:
                resp = await self.http.request(
                    method,
                    path,
                    params=params,
                    json=json,
                    headers={**(headers or {}), "Authorization": f"Bearer {token}"},
                )
            except httpx.TransportError as exc:
                if attempt >= self._max_retries:
                    raise ApsError(f"Falha de rede no APS: {exc.__class__.__name__}") from exc
                delay = self._delay(attempt, None)
                log.warning("APS %s %s falha de rede; nova tentativa em %.1fs", method, path, delay)
                await self._sleep(delay)
                attempt += 1
                continue

            url_path = resp.request.url.path
            elapsed_ms = (time.perf_counter() - started) * 1000
            log.info("APS %s %s -> %s (%.0f ms)", method, url_path, resp.status_code, elapsed_ms)

            status = resp.status_code
            if status in allow_status:
                return resp
            if status == 429 or status >= 500:
                if attempt >= self._max_retries:
                    raise ApsHttpError(status, url_path, "esgotadas as tentativas")
                delay = self._delay(attempt, resp.headers.get("Retry-After"))
                log.warning(
                    "APS %s %s -> %s; nova tentativa em %.1fs", method, url_path, status, delay
                )
                await self._sleep(delay)
                attempt += 1
                continue
            if status == 401 and not renewed:
                self.tokens.invalidate(scopes)
                renewed = True
                continue
            if status in (401, 403):
                raise ApsForbiddenError(NOT_PROVISIONED_MSG.format(status=status, path=url_path))
            if status == 404:
                raise ApsNotFoundError(f"Não encontrado no APS: {url_path}")
            if resp.is_error:
                raise ApsHttpError(status, url_path, resp.text[:300])
            return resp

    async def get_json(self, path: str, **kwargs: Any) -> dict[str, Any]:
        resp = await self.request("GET", path, **kwargs)
        body: dict[str, Any] = resp.json()
        return body

    async def paginate(
        self, path: str, params: dict[str, str] | None = None
    ) -> AsyncIterator[dict[str, Any]]:
        """Itera `data` de respostas JSON:API seguindo links.next.href."""
        url: str | None = path
        while url:
            body = await self.get_json(url, params=params)
            params = None  # o link "next" já traz a querystring
            for item in body.get("data") or []:
                yield item
            nxt = (body.get("links") or {}).get("next")
            url = nxt.get("href") if isinstance(nxt, dict) else nxt
