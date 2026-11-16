"""Logs estruturados em JSON (uma linha por evento), com contexto e sem segredos.

- Contexto por requisição/job (contextvars): request_id, user (id e nome), obra, job,
  version. O middleware HTTP preenche request_id/obra; `current_user` preenche o
  usuário; os jobs do worker preenchem job/obra/version.
- RedactFilter: remove tokens e segredos (Bearer, JWT, client_secret, access_token,
  password, Authorization...) da mensagem formatada e do traceback. Defesa em
  profundidade: o código já não loga tokens (CLAUDE.md).
- LOG_FORMAT=json (padrão) ou text (leitura humana no terminal).
"""

from __future__ import annotations

import contextvars
import json
import logging
import re
import sys
import time
import uuid
from collections.abc import Awaitable, Callable, MutableMapping
from datetime import UTC, datetime
from typing import Any

# --------------------------------------------------------------------------- contexto

_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)
_user: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar("user", default=None)
_obra: contextvars.ContextVar[int | None] = contextvars.ContextVar("obra", default=None)
_job: contextvars.ContextVar[str | None] = contextvars.ContextVar("job", default=None)
_version: contextvars.ContextVar[int | None] = contextvars.ContextVar("version", default=None)


def bind(
    *,
    request_id: str | None = None,
    user: Any = None,
    obra: int | None = None,
    job: str | None = None,
    version: int | None = None,
) -> None:
    """Acrescenta ao contexto atual (só os campos informados)."""
    if request_id is not None:
        _request_id.set(request_id)
    if user is not None:
        _user.set({"id": getattr(user, "id", None), "name": getattr(user, "name", None)})
    if obra is not None:
        _obra.set(obra)
    if job is not None:
        _job.set(job)
    if version is not None:
        _version.set(version)


def current_context() -> dict[str, Any]:
    ctx: dict[str, Any] = {}
    for key, var in (
        ("request_id", _request_id),
        ("user", _user),
        ("obra", _obra),
        ("job", _job),
        ("version", _version),
    ):
        value = var.get()
        if value is not None:
            ctx[key] = value
    return ctx


# --------------------------------------------------------------------------- segredos

_REDACTIONS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(\b[a-z][a-z0-9+.\-]*://[^:/\s@]+:)[^@\s/]+@", re.IGNORECASE), r"\1[REDACTED]@"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9\-._~+/]+=*"), "Bearer [REDACTED]"),
    (re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"), "[REDACTED]"),
    (
        re.compile(
            r"""(?ix)
            (["']?\b(?:access_token|refresh_token|client_secret|api_key|password|passwd|
                      secret|token|authorization|x-adsk-signature)\b["']?\s*[:=]\s*["']?)
            [^"'\s,&;}]+"""
        ),
        r"\1[REDACTED]",
    ),
]


def redact(text: str) -> str:
    for pattern, repl in _REDACTIONS:
        text = pattern.sub(repl, text)
    return text


# --------------------------------------------------------------------------- formatação

_STANDARD = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    """{"ts", "level", "logger", "msg", <contexto>, <extras>, "exc"} numa linha."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": redact(record.getMessage()),
        }
        entry.update(current_context())
        for key, value in record.__dict__.items():
            if key not in _STANDARD and not key.startswith("_") and key not in entry:
                entry[key] = value
        if record.exc_info:
            entry["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(entry, ensure_ascii=False, default=str)


class TextFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)s %(name)s %(message)s")

    def format(self, record: logging.LogRecord) -> str:
        ctx = current_context()
        line = redact(super().format(record))
        if ctx:
            line += " " + " ".join(f"{k}={v}" for k, v in ctx.items())
        return line


_HANDLER_NAME = "app-structured"


def configure_logging(level: str = "INFO", fmt: str = "json") -> None:
    """Um handler no root (idempotente: chamar de novo só troca o formato/nível)."""
    root = logging.getLogger()
    for h in list(root.handlers):
        if h.get_name() == _HANDLER_NAME:
            root.removeHandler(h)
    stream = sys.stdout
    reconfigure = getattr(stream, "reconfigure", None)
    if callable(reconfigure) and (getattr(stream, "encoding", "") or "").lower() != "utf-8":
        # Windows com saída redirecionada usa cp1252: os acentos virariam "?" no log.
        reconfigure(encoding="utf-8", errors="backslashreplace")
    handler = logging.StreamHandler(stream)
    handler.set_name(_HANDLER_NAME)
    handler.setFormatter(JsonFormatter() if fmt == "json" else TextFormatter())
    root.addHandler(handler)
    root.setLevel(level.upper())
    # Bibliotecas barulhentas: só avisos (o httpx logaria cada chamada; o acesso HTTP é
    # registrado pelo nosso middleware, com request_id).
    for name in ("httpx", "httpcore", "uvicorn.access", "arq.worker"):
        logging.getLogger(name).setLevel(logging.WARNING)


# --------------------------------------------------------------------------- middleware

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

_REQUEST_ID = re.compile(r"^[A-Za-z0-9._\-]{8,64}$")
_OBRA_PATH = re.compile(r"^/api/obras/(\d+)")
access_log = logging.getLogger("app.access")


class RequestContextMiddleware:
    """ASGI puro (não atrapalha respostas em fluxo/SSE): request_id (aceita um
    X-Request-ID válido do proxy), obra pelo caminho, linha de acesso ao final e o
    X-Request-ID na resposta."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {
            k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])
        }
        incoming = headers.get("x-request-id", "")
        request_id = incoming if _REQUEST_ID.match(incoming) else uuid.uuid4().hex
        path: str = scope.get("path", "")
        match = _OBRA_PATH.match(path)
        token = _request_id.set(request_id)
        user_token = _user.set(None)
        obra_token = _obra.set(int(match.group(1)) if match else None)
        started = time.perf_counter()
        status = 500

        async def send_with_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message["status"])
                message.setdefault("headers", [])
                message["headers"] = [*message["headers"], (b"x-request-id", request_id.encode())]
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            if path not in ("/api/health",):
                access_log.info(
                    "%s %s -> %s",
                    scope.get("method"),
                    path,
                    status,
                    extra={
                        "method": scope.get("method"),
                        "path": path,
                        "status": status,
                        "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                    },
                )
            _request_id.reset(token)
            _user.reset(user_token)
            _obra.reset(obra_token)
