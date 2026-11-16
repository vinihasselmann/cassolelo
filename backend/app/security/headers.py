"""Cabeçalhos de segurança e CORS.

A API só devolve JSON, SSE e Excel: a CSP dela é a mais fechada possível
(`default-src 'none'`). A CSP da página do app (compatível com o Viewer da Autodesk)
fica no frontend (`frontend/security-headers.ts`) e é aplicada por quem serve os
arquivos estáticos (Vite em dev/preview; o proxy da TI em produção).
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import Settings

API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
# Swagger/ReDoc (só em dev) carregam scripts de CDN: ficam sem a CSP da API.
_DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")


def security_headers(settings: Settings, path: str) -> list[tuple[bytes, bytes]]:
    headers = [
        (b"x-content-type-options", b"nosniff"),
        (b"x-frame-options", b"DENY"),
        (b"referrer-policy", b"no-referrer"),
        (b"cross-origin-resource-policy", b"same-origin"),
    ]
    if not path.startswith(_DOCS_PATHS):
        headers.append((b"content-security-policy", API_CSP.encode()))
    if not settings.is_dev and settings.hsts_max_age > 0:
        value = f"max-age={settings.hsts_max_age}; includeSubDomains"
        headers.append((b"strict-transport-security", value.encode()))
    return headers


class SecurityHeadersMiddleware:
    """ASGI puro (não atrapalha o SSE). Não sobrescreve um cabeçalho já definido."""

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        extra = security_headers(self.settings, scope.get("path", ""))

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                current = list(message.get("headers", []))
                present = {k.lower() for k, _ in current}
                message["headers"] = current + [(k, v) for k, v in extra if k not in present]
            await send(message)

        await self.app(scope, receive, send_with_headers)


def add_cors(app: FastAPI, settings: Settings) -> None:
    """CORS só para o domínio do app. Sem origens configuradas, nenhum cabeçalho CORS
    é enviado (o navegador bloqueia chamadas de outras origens)."""
    origins = settings.cors_origin_list
    if not origins:
        return
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "X-Dev-User", "X-Request-ID", "Authorization"],
        expose_headers=["X-Request-ID", "Retry-After", "Content-Disposition"],
        max_age=600,
    )
