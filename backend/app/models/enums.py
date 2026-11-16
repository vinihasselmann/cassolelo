from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    PROJETOS = "projetos"
    FABRICA = "fabrica"
    ADMIN = "admin"
    LEITURA = "leitura"


class VersionStatus(StrEnum):
    PENDING = "pending"
    TRANSLATING = "translating"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
    NO_TRANSLATION = "no_translation"


class ReviewStatus(StrEnum):
    OK = "ok"
    REVIEW = "review"  # mudou entre versões e tem valores da fábrica (Fase 7)


class ParamType(StrEnum):
    TEXT = "text"
    NUMBER = "number"
    LIST = "list"
    DATE = "date"
    BOOL = "bool"


class ParamScope(StrEnum):
    GLOBAL = "global"
    OBRA = "obra"


class OrphanStatus(StrEnum):
    OPEN = "open"
    RELINKED = "relinked"
    ARCHIVED = "archived"
    RETURNED = "returned"  # a marca voltou numa versão seguinte


def check_in(column: str, enum: type[StrEnum]) -> str:
    values = ", ".join(f"'{m.value}'" for m in enum)
    return f"{column} IN ({values})"
