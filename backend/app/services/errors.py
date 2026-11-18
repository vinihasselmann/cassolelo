"""Erros de regra de negócio. A API converte em HTTP pelo `status_code` e `code`."""

from __future__ import annotations

from typing import Any


class DomainError(Exception):
    status_code = 400
    code = "domain_error"

    def __init__(self, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.message = message
        self.extra: dict[str, Any] = extra  # campos a mais no corpo da resposta


class NotFoundError(DomainError):
    status_code = 404
    code = "not_found"


class ForbiddenError(DomainError):
    status_code = 403
    code = "forbidden"


class ConflictError(DomainError):
    status_code = 409
    code = "conflict"


class ObraFileDeletedError(ConflictError):
    """O arquivo da obra foi excluído no Docs: a obra está bloqueada (só editar/excluir)."""

    code = "obra_file_deleted"


class ValidationError(DomainError):
    status_code = 422
    code = "validation"
