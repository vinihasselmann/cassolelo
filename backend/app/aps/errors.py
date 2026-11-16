from __future__ import annotations


class ApsError(Exception):
    """Erro de integração com o APS (mensagem pronta para log/usuário, sem tokens)."""


class ApsAuthError(ApsError):
    """Credenciais do app inválidas."""


class ApsForbiddenError(ApsError):
    """401/403: app não liberado em Custom Integrations ou sem acesso ao recurso."""


class ApsNotFoundError(ApsError):
    pass


class ApsNoTranslationError(ApsError):
    """O Docs não gerou derivativo visualizável (nunca disparamos conversão)."""


class ApsHttpError(ApsError):
    def __init__(self, status_code: int, path: str, detail: str = "") -> None:
        super().__init__(f"HTTP {status_code} em {path}{': ' + detail if detail else ''}")
        self.status_code = status_code
        self.path = path


class ApsForbiddenOperationError(ApsError):
    """Chamada proibida pelas regras do projeto (POST /job, AEC Data Model)."""


NOT_PROVISIONED_MSG = (
    "Acesso negado (HTTP {status}) em {path}: app não liberado em Custom Integrations "
    "do ACC ou sem acesso a este recurso."
)
