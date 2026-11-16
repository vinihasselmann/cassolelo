"""Converte erros do APS e de regra de negócio em respostas HTTP com mensagem clara.

Corpo: {"detail": "<mensagem em português>", "code": "<código estável>"}.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app.aps.errors import (
    ApsAuthError,
    ApsError,
    ApsForbiddenError,
    ApsForbiddenOperationError,
    ApsNotFoundError,
    ApsNoTranslationError,
)
from app.services.errors import DomainError

log = logging.getLogger("app.api")

APS_FORBIDDEN_MSG = (
    "Sem permissão no Autodesk Docs: o app não foi liberado em Custom Integrations "
    "ou não tem acesso a este projeto/pasta. Fale com o administrador do ACC."
)

# (status HTTP, código, mensagem fixa ou None para usar a do erro)
_APS_MAP: list[tuple[type[ApsError], int, str, str | None]] = [
    (ApsForbiddenOperationError, 500, "aps_forbidden_operation", None),
    (ApsForbiddenError, 403, "aps_forbidden", APS_FORBIDDEN_MSG),
    (ApsNotFoundError, 404, "aps_not_found", "Não encontrado no Autodesk Docs."),
    (ApsNoTranslationError, 409, "aps_no_translation", None),
    (ApsAuthError, 502, "aps_auth", "Credenciais do app APS inválidas ou ausentes no servidor."),
    (ApsError, 502, "aps_error", "Falha ao consultar o Autodesk Docs. Tente novamente."),
]


def _body(detail: str, code: str) -> dict[str, str]:
    return {"detail": detail, "code": code}


async def _aps_handler(_request: Request, exc: Exception) -> JSONResponse:
    for exc_type, status, code, message in _APS_MAP:
        if isinstance(exc, exc_type):
            log.warning("Erro APS (%s): %s", code, exc)
            return JSONResponse(_body(message or str(exc), code), status_code=status)
    raise exc  # pragma: no cover


async def _domain_handler(_request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, DomainError):  # pragma: no cover
        raise exc
    return JSONResponse(
        jsonable_encoder({**exc.extra, **_body(exc.message, exc.code)}),
        status_code=exc.status_code,
    )


def register(app: FastAPI) -> None:
    app.add_exception_handler(ApsError, _aps_handler)
    app.add_exception_handler(DomainError, _domain_handler)
