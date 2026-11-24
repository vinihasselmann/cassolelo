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
    DELETED = "deleted"  # versão "Deleted" do Docs: o arquivo foi excluído (vai à lixeira)


class AccFileState(StrEnum):
    """Situação do arquivo da obra no Autodesk Docs (vista no último sync)."""

    OK = "ok"
    DELETED = "deleted"  # na lixeira do Docs (item oculto / última versão "Deleted")
    MISSING = "missing"  # o Docs não acha mais o item (404/403): sai da verificação periódica


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


class UnitNumbering(StrEnum):
    """Como as unidades de peça da obra foram numeradas (decisão de 2026-11-18)."""

    # ordem estável (nível, nome, id), à espera dos centros de gravidade do 3D
    PROVISIONAL = "provisional"
    SEQUENCE = "sequence"  # renumeradas pela sequência de montagem (Z → X → Y)
    FIXED = "fixed"  # travada na ordem estável (valores por peça antes dos centros)


def check_in(column: str, enum: type[StrEnum]) -> str:
    values = ", ".join(f"'{m.value}'" for m in enum)
    return f"{column} IN ({values})"


class ParamLevel(StrEnum):
    """Parâmetro da fábrica por MARCA (um valor para todas as peças da marca) ou por PEÇA
    (um valor por unidade de peça). Decisão de 2026-11-16 (docs/pecas/verificacao.md)."""

    MARK = "mark"
    PIECE = "piece"


class UnitStatus(StrEnum):
    """Situação da unidade de peça na versão mais recente processada da obra."""

    LINKED = "linked"  # ligada a um elemento
    UNLINKED = "unlinked"  # sem elemento e sem valores (só fica registrada)
    ORPHAN = "orphan"  # sem elemento e COM valores (nunca apagar em silêncio)
    # órfã arquivada pela fábrica (P5): valores guardados; só volta se a chave reaparecer
    ARCHIVED = "archived"


class LinkMethod(StrEnum):
    """Como a unidade foi ligada ao elemento numa versão."""

    KEY = "key"  # pelo externalId (UniqueId no Revit, GlobalId no IFC)
    ORDER = "order"  # pela ordem estável dentro da marca: "conferir"
    NEW = "new"  # unidade criada nesta versão para um elemento a mais
    MANUAL = "manual"  # religada à mão a esta peça (fila de unidades órfãs, P5)
