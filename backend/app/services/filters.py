"""Motor de filtros (docs/filtros/plano.md): campos, valores e avaliação sobre `piece_props`.

Formato do filtro:

    {"mode": "isolate|hide|highlight", "logic": "and|or",
     "rules": [{"field": {"source": "model|factory|system", "key": "..."},
                "op": "...", "value": ...}]}

- Cada regra vira `elements.id IN (SELECT piece_id FROM piece_props WHERE ...)`, com
  TODOS os valores do usuário como parâmetros ligados (nunca texto concatenado no SQL).
- Operadores negativos (diferente de, não contém) e "está vazio" valem também para as
  peças SEM valor no campo: "não é igual a X" = tudo que não bate em "é igual a X".
- Texto sem diferenciar maiúsculas nem acentos (`f_unaccent`, migração 0009).
- Datas relativas (mês atual, mês anterior, últimos N dias) usam o "hoje" passado pelo
  chamador (a API usa DISPLAY_TIMEZONE; os testes, uma data fixa).
- Cada regra tem um modo (Isolar, Ocultar ou Destacar); sem modo, vale o do filtro.
  Combinação, como no Dalux (F3, decisão de 2026-11-16):
    * visíveis = peças que batem nas regras Isolar (E/OU conforme `logic`; sem regras
      Isolar, todas) MENOS as que batem em QUALQUER regra Ocultar;
    * resultado = visíveis que batem nas regras Destacar (E/OU; sem elas, todas as
      visíveis) e no texto livre ("Pesquisar por objetos");
    * no 3D: resultado normal; visíveis fora do resultado esmaecidas; o resto oculto.
  É o resultado que a lista, as cores e a exportação usam.
"""

from __future__ import annotations

import unicodedata
from calendar import monthrange
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    model_serializer,
)
from sqlalchemy import (
    ColumnElement,
    Text,
    and_,
    cast,
    exists,
    false,
    func,
    literal,
    or_,
    select,
    true,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models import (
    Element,
    Mark,
    ModelVersion,
    Orphan,
    ParamDef,
    ParamValue,
    PieceProp,
    VersionPropertyName,
)
from app.models.enums import OrphanStatus, VersionStatus
from app.services.errors import ValidationError
from app.services.mark_status import version_statuses
from app.services.param_defs import in_obra
from app.services.piece_props import (
    DATE,
    FACTORY,
    MODEL,
    NUMBER,
    PARAM_FIELD_TYPE,
    STATUS_LABELS,
    SYSTEM,
    SYSTEM_FIELDS,
    TEXT,
    parse_date,
    parse_number,
)
from app.services.version_data import get_ready_version

TEXT_OPS = {"eq", "ne", "contains", "not_contains", "starts_with", "empty", "not_empty", "in"}
NUMBER_OPS = {"eq", "ne", "gt", "gte", "lt", "lte", "between", "empty", "not_empty"}
DATE_OPS = {
    "on",
    "before",
    "after",
    "between",
    "this_month",
    "last_month",
    "last_n_days",
    "empty",
    "not_empty",
}
BOOL = "bool"  # campos de sistema calculados (sim/não)
BOOL_OPS = {"eq", "ne"}
OPS_BY_TYPE = {TEXT: TEXT_OPS, NUMBER: NUMBER_OPS, DATE: DATE_OPS, BOOL: BOOL_OPS}
OP_LABELS = {
    "eq": "é igual a",
    "ne": "é diferente de",
    "contains": "contém",
    "not_contains": "não contém",
    "starts_with": "começa com",
    "empty": "está vazio",
    "not_empty": "não está vazio",
    "in": "está em",
    "gt": ">",
    "gte": "≥",
    "lt": "<",
    "lte": "≤",
    "between": "entre",
    "on": "em",
    "before": "antes de",
    "after": "depois de",
    "this_month": "no mês atual",
    "last_month": "no mês anterior",
    "last_n_days": "nos últimos N dias",
}
TYPE_LABELS = {TEXT: "texto", NUMBER: "número", DATE: "data", BOOL: "sim/não"}
# Campos de sistema CALCULADOS NA HORA (não ficam em piece_props), com as mesmas regras
# dos antigos atalhos da busca. O status também é calculado na hora (mark_status), para
# nunca depender da sincronização de piece_props.
COMPUTED_FIELDS: dict[str, tuple[str, str]] = {
    "new": ("Nova na versão", BOOL),  # marca sem peças na versão pronta anterior
    "orphan": ("Órfã", BOOL),  # marca órfã (aberta) da obra: não tem peças na versão
}
FIRST_VERSION_NOTE = "Primeira versão processada: não há versão anterior para comparar."
MAX_RULES = 50
MAX_IN = 500
MAX_TEXT_VALUE = 500

Op = Literal[
    "eq",
    "ne",
    "contains",
    "not_contains",
    "starts_with",
    "empty",
    "not_empty",
    "in",
    "gt",
    "gte",
    "lt",
    "lte",
    "between",
    "on",
    "before",
    "after",
    "this_month",
    "last_month",
    "last_n_days",
]


# ----------------------------------------------------------------- formato (Pydantic)


class FieldRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: Literal["model", "factory", "system"]
    key: str = Field(min_length=1, max_length=600)


Mode = Literal["isolate", "hide", "highlight"]
MAX_QUERY = 500


class Rule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: FieldRef
    op: Op
    value: Any = None
    mode: Mode | None = None  # sem modo: vale o do filtro

    @model_serializer(mode="wrap")
    def _drop_empty_mode(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        """Sem modo, a chave não é gravada (os filtros antigos ficam iguais)."""
        data: dict[str, Any] = handler(self)
        if data.get("mode") is None:
            data.pop("mode", None)
        return data


class FilterDef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Mode
    logic: Literal["and", "or"] = "and"
    rules: list[Rule] = Field(default_factory=list, max_length=MAX_RULES)
    q: str = Field(default="", max_length=MAX_QUERY)  # "Pesquisar por objetos"

    def rule_mode(self, rule: Rule) -> Mode:
        return rule.mode or self.mode

    @model_serializer(mode="wrap")
    def _drop_empty_query(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        """Sem texto, a chave não é gravada (os filtros antigos ficam iguais)."""
        data: dict[str, Any] = handler(self)
        if not data.get("q"):
            data.pop("q", None)
        return data


# --------------------------------------------------------------------------- campos


@dataclass(frozen=True)
class FilterField:
    source: str
    key: str
    name: str
    group: str | None
    type: str
    distinct_values: int
    pieces: int


async def _live_stats(
    session: AsyncSession, version_id: int, source: str
) -> dict[str, tuple[int, int]]:
    """chave -> (valores distintos, peças com valor), contados em piece_props."""
    rows = await session.execute(
        select(
            PieceProp.key,
            func.count(func.distinct(PieceProp.value_text)),
            func.count(func.distinct(PieceProp.piece_id)),
        )
        .where(PieceProp.version_id == version_id, PieceProp.source == source)
        .group_by(PieceProp.key)
    )
    return {key: (int(d), int(n)) for key, d, n in rows}


async def _piece_count(session: AsyncSession, version_id: int) -> int:
    n = await session.scalar(
        select(func.count()).select_from(Element).where(Element.version_id == version_id)
    )
    return int(n or 0)


async def list_fields(session: AsyncSession, version_id: int) -> list[FilterField]:
    """Campos filtráveis da versão: sistema, parâmetros da fábrica da obra e propriedades
    do modelo (tipo inferido no processamento)."""
    version = await get_ready_version(session, version_id)
    out: list[FilterField] = []
    system = await _live_stats(session, version_id, SYSTEM)
    statuses = await version_statuses(session, version_id)
    system["status"] = (
        sum(1 for n in statuses.pieces.values() if n),
        sum(statuses.pieces.values()),
    )
    for key, (name, ftype) in SYSTEM_FIELDS.items():
        distinct, pieces = system.get(key, (0, 0))
        out.append(FilterField(SYSTEM, key, name, "Sistema", ftype, distinct, pieces))
    total = await _piece_count(session, version_id)
    for key, (name, ftype) in COMPUTED_FIELDS.items():
        out.append(FilterField(SYSTEM, key, name, "Sistema", ftype, 2, total))
    factory = await _live_stats(session, version_id, FACTORY)
    for p in await session.scalars(
        select(ParamDef)
        .where(ParamDef.active.is_(True), in_obra(version.obra_id, level=None))
        .order_by(func.lower(ParamDef.name), ParamDef.id)
    ):
        distinct, pieces = factory.get(str(p.id), (0, 0))
        ftype = PARAM_FIELD_TYPE.get(p.type, TEXT)
        out.append(FilterField(FACTORY, str(p.id), p.name, "Fábrica", ftype, distinct, pieces))
    for row in await session.scalars(
        select(VersionPropertyName)
        .where(VersionPropertyName.version_id == version_id)
        .order_by(
            func.lower(VersionPropertyName.group_name), func.lower(VersionPropertyName.prop_name)
        )
    ):
        out.append(
            FilterField(
                MODEL,
                f"{row.group_name}/{row.prop_name}",
                row.prop_name,
                row.group_name,
                row.value_type or TEXT,
                row.distinct_values or 0,
                row.pieces or 0,
            )
        )
    return out


async def resolve_field(session: AsyncSession, version: ModelVersion, ref: FieldRef) -> FilterField:
    """O campo existe nesta versão? (422 com mensagem clara, se não)."""
    if ref.source == SYSTEM and ref.key in SYSTEM_FIELDS | COMPUTED_FIELDS:
        name, ftype = (SYSTEM_FIELDS | COMPUTED_FIELDS)[ref.key]
        return FilterField(SYSTEM, ref.key, name, "Sistema", ftype, 0, 0)
    if ref.source == FACTORY and ref.key.isdigit():
        param = await session.scalar(
            select(ParamDef).where(
                ParamDef.id == int(ref.key),
                ParamDef.active.is_(True),
                in_obra(version.obra_id, level=None),
            )
        )
        if param is not None:
            ftype = PARAM_FIELD_TYPE.get(param.type, TEXT)
            return FilterField(FACTORY, ref.key, param.name, "Fábrica", ftype, 0, 0)
    if ref.source == MODEL:
        row = await session.scalar(
            select(VersionPropertyName).where(
                VersionPropertyName.version_id == version.id,
                func.concat(VersionPropertyName.group_name, "/", VersionPropertyName.prop_name)
                == ref.key,
            )
        )
        if row is not None:
            return FilterField(
                MODEL, ref.key, row.prop_name, row.group_name, row.value_type or TEXT, 0, 0
            )
    raise ValidationError(f'Campo "{ref.key}" ({ref.source}) não existe nesta versão.')


@dataclass(frozen=True)
class FieldValue:
    value: str
    pieces: int


async def field_values(
    session: AsyncSession, version_id: int, ref: FieldRef, q: str = "", limit: int = 50
) -> list[FieldValue]:
    """Valores do campo para autocompletar, com o nº de peças (mais comuns primeiro)."""
    version = await get_ready_version(session, version_id)
    field = await resolve_field(session, version, ref)
    if field.type == BOOL:
        return []  # sim/não: a tela usa um seletor, sem autocompletar
    if field.source == SYSTEM and field.key == "status":  # calculado na hora
        pieces = (await version_statuses(session, version_id)).pieces
        wanted = _fold(q.strip())
        found = [
            FieldValue(STATUS_LABELS[st], n)
            for st, n in pieces.items()
            if n and wanted in _fold(STATUS_LABELS[st])
        ]
        found.sort(key=lambda v: (-v.pieces, v.value))
        return found[: max(1, min(limit, 200))]
    conds = [
        PieceProp.version_id == version_id,
        PieceProp.source == field.source,
        PieceProp.key == field.key,
    ]
    if q.strip():
        conds.append(_contains(q.strip()[:MAX_TEXT_VALUE]))
    rows = await session.execute(
        select(PieceProp.value_text, func.count(func.distinct(PieceProp.piece_id)).label("n"))
        .where(*conds)
        .group_by(PieceProp.value_text)
        .order_by(func.count(func.distinct(PieceProp.piece_id)).desc(), PieceProp.value_text)
        .limit(max(1, min(limit, 200)))
    )
    return [FieldValue(value, int(n)) for value, n in rows]


# ---------------------------------------------------------------------- avaliação


def today(timezone: str) -> date:
    """ "Hoje" no fuso da obra (DISPLAY_TIMEZONE). Separado para os testes fixarem a data."""
    return datetime.now(ZoneInfo(timezone)).date()


def _norm(value: Any) -> ColumnElement[str]:
    return func.f_unaccent(func.lower(value))


def _like(token: str) -> str:
    escaped = token.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return escaped


def _contains(token: str) -> ColumnElement[bool]:
    return func.f_unaccent(PieceProp.value_text).ilike(
        func.f_unaccent(literal(f"%{_like(token)}%")), escape="\\"
    )


class _RuleError(ValidationError):
    pass


def _fail(index: int, field: FilterField, message: str) -> _RuleError:
    return _RuleError(f'Regra {index + 1} ("{field.name}"): {message}')


def _text_value(index: int, field: FilterField, value: Any) -> str:
    if not isinstance(value, str | int | float) or isinstance(value, bool) or str(value) == "":
        raise _fail(index, field, "informe um texto.")
    return str(value)[:MAX_TEXT_VALUE]


def _number_value(index: int, field: FilterField, value: Any) -> Decimal:
    if isinstance(value, bool):
        raise _fail(index, field, "informe um número.")
    if isinstance(value, int | float):
        return Decimal(str(value))
    if isinstance(value, str) and (n := parse_number(value)) is not None:
        return n
    raise _fail(index, field, f'"{value}" não é um número.')


def _date_value(index: int, field: FilterField, value: Any) -> date:
    if isinstance(value, str) and (d := parse_date(value)) is not None:
        return d
    raise _fail(index, field, f'"{value}" não é uma data (use AAAA-MM-DD).')


def _pair(index: int, field: FilterField, value: Any) -> tuple[Any, Any]:
    if not isinstance(value, list) or len(value) != 2:
        raise _fail(index, field, '"entre" precisa de dois valores: [início, fim].')
    return value[0], value[1]


def _month(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, monthrange(year, month)[1])


def _fold(text: str) -> str:
    """Minúsculas e sem acentos, em Python (o mesmo que `f_unaccent(lower(...))`)."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _text_args(index: int, field: FilterField, rule: Rule) -> list[str]:
    """Valor(es) de uma regra de texto, validados (o "está em" aceita uma lista)."""
    if rule.op in ("empty", "not_empty"):
        return []
    if rule.op == "in":
        value = rule.value
        if not isinstance(value, list) or not value or len(value) > MAX_IN:
            raise _fail(index, field, f'"está em" precisa de uma lista (1 a {MAX_IN} itens).')
        return [_text_value(index, field, v) for v in value]
    return [_text_value(index, field, rule.value)]


def _text_matches(op: str, args: list[str], value: str | None) -> bool:
    """Regra de texto avaliada em Python (status calculado e marcas órfãs). Mesma
    semântica do SQL: sem valor, só "está vazio", "diferente de" e "não contém" batem."""
    if op == "empty":
        return value is None
    if op == "not_empty":
        return value is not None
    if value is None:
        return op in ("ne", "not_contains")
    v, wanted = _fold(value), [_fold(a) for a in args]
    if op == "in":
        return v in wanted
    checks = {
        "eq": v == wanted[0],
        "ne": v != wanted[0],
        "contains": wanted[0] in v,
        "not_contains": wanted[0] not in v,
        "starts_with": v.startswith(wanted[0]),
    }
    return checks[op]


def _bool_value(index: int, field: FilterField, rule: Rule) -> bool:
    """Regra sim/não ("é igual a" ou "é diferente de" true/false): devolve o que bate."""
    if not isinstance(rule.value, bool):
        raise _fail(index, field, "informe true (sim) ou false (não).")
    return rule.value if rule.op == "eq" else not rule.value


@dataclass
class _Context:
    """Uma avaliação: versão, "hoje" e o que é calculado na hora (uma vez só)."""

    session: AsyncSession
    version: ModelVersion
    today: date
    notes: list[str] = field(default_factory=list)
    _labels: dict[int, str] | None = None  # element_id -> status da peça
    _previous: tuple[ModelVersion | None] | None = None

    async def status_labels(self) -> dict[int, str]:
        """peça (com marca, na versão) -> status dela ("Pendente", "Parcial"...)."""
        if self._labels is None:
            result = await version_statuses(self.session, self.version.id)
            self._labels = {e: STATUS_LABELS[st] for e, st in result.piece_statuses.items()}
        return self._labels

    async def previous(self) -> ModelVersion | None:
        """Versão pronta anterior da obra (para "Nova na versão")."""
        if self._previous is None:
            prev = await self.session.scalar(
                select(ModelVersion)
                .where(
                    ModelVersion.obra_id == self.version.obra_id,
                    ModelVersion.version_number < self.version.version_number,
                    ModelVersion.status == VersionStatus.READY.value,
                )
                .order_by(ModelVersion.version_number.desc())
                .limit(1)
            )
            self._previous = (prev,)
        return self._previous[0]

    def note(self, text: str) -> None:
        if text not in self.notes:
            self.notes.append(text)


async def _computed_condition(
    ctx: _Context, index: int, rule: Rule, field: FilterField
) -> ColumnElement[bool]:
    """Campos de sistema calculados na hora: status, nova na versão e órfã."""
    if field.key == "status":
        args = _text_args(index, field, rule)
        labels = await ctx.status_labels()
        ids = [e for e, label in labels.items() if _text_matches(rule.op, args, label)]
        cond: ColumnElement[bool] = Element.id.in_(ids)
        if _text_matches(rule.op, args, None):  # peças sem marca não têm status
            cond = or_(cond, Element.mark_id.is_(None))
        return cond
    wanted = _bool_value(index, field, rule)
    if field.key == "new":
        prev = await ctx.previous()
        if prev is None:
            ctx.note(FIRST_VERSION_NOTE)
            is_new: ColumnElement[bool] = false()
        else:
            before = aliased(Element)
            is_new = and_(
                Element.mark_id.is_not(None),
                ~exists(
                    select(before.id).where(
                        before.version_id == prev.id, before.mark_id == Element.mark_id
                    )
                ),
            )
        return is_new if wanted else ~is_new
    # órfã: nenhuma PEÇA da versão é de marca órfã (as órfãs entram como marcas sem peças)
    return false() if wanted else true()


async def _condition(
    ctx: _Context, index: int, rule: Rule, field: FilterField
) -> ColumnElement[bool]:
    allowed = OPS_BY_TYPE[field.type]
    if rule.op not in allowed:
        raise _fail(
            index,
            field,
            f'o operador "{OP_LABELS[rule.op]}" não vale para {TYPE_LABELS[field.type]}.',
        )
    if field.source == SYSTEM and (field.key in COMPUTED_FIELDS or field.key == "status"):
        return await _computed_condition(ctx, index, rule, field)
    version_id, today = ctx.version.id, ctx.today

    def pieces(*conds: ColumnElement[bool]) -> Any:
        return select(PieceProp.piece_id).where(
            PieceProp.version_id == version_id,
            PieceProp.source == field.source,
            PieceProp.key == field.key,
            *conds,
        )

    def has(*conds: ColumnElement[bool]) -> ColumnElement[bool]:
        return Element.id.in_(pieces(*conds))

    def lacks(*conds: ColumnElement[bool]) -> ColumnElement[bool]:
        return ~Element.id.in_(pieces(*conds))

    op, value = rule.op, rule.value
    if op == "empty":
        return lacks()
    if op == "not_empty":
        return has()

    if field.type == TEXT:
        args = _text_args(index, field, rule)
        if op == "in":
            return has(_norm(PieceProp.value_text).in_([_norm(literal(v)) for v in args]))
        text = args[0]
        if op in ("eq", "ne"):
            cond = _norm(PieceProp.value_text) == _norm(literal(text))
            return has(cond) if op == "eq" else lacks(cond)
        if op in ("contains", "not_contains"):
            return has(_contains(text)) if op == "contains" else lacks(_contains(text))
        prefix = func.f_unaccent(literal(f"{_like(text)}%"))
        return has(func.f_unaccent(PieceProp.value_text).ilike(prefix, escape="\\"))

    if field.type == NUMBER:
        col = PieceProp.value_num
        if op == "between":
            lo, hi = sorted(_number_value(index, field, v) for v in _pair(index, field, value))
            return has(col.between(lo, hi))
        n = _number_value(index, field, value)
        if op == "ne":
            return lacks(col == n)
        cmp = {"eq": col == n, "gt": col > n, "gte": col >= n, "lt": col < n, "lte": col <= n}
        return has(cmp[op])

    col_d = PieceProp.value_date
    if op == "between":
        lo_d, hi_d = sorted(_date_value(index, field, v) for v in _pair(index, field, value))
        return has(col_d.between(lo_d, hi_d))
    if op == "this_month":
        return has(col_d.between(*_month(today.year, today.month)))
    if op == "last_month":
        prev = today.replace(day=1) - timedelta(days=1)
        return has(col_d.between(*_month(prev.year, prev.month)))
    if op == "last_n_days":
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 3650:
            raise _fail(index, field, "informe o número de dias (1 a 3650).")
        return has(col_d.between(today - timedelta(days=value - 1), today))
    d = _date_value(index, field, value)
    cmp_d = {"on": col_d == d, "before": col_d < d, "after": col_d > d}
    return has(cmp_d[op])


@dataclass(frozen=True)
class OrphanMark:
    mark_id: int
    code: str
    category: str


@dataclass(frozen=True)
class CompiledFilter:
    """Filtro pronto para consultar: condição sobre `elements` (as peças da versão), as
    marcas órfãs que batem (não têm peças) e avisos ("primeira versão...").

    `condition` é o RESULTADO; `visible`, as peças que ficam à vista no 3D (resultado
    mais as esmaecidas). `emphasis` diz se há algo esmaecido (regras Destacar ou texto)."""

    version: ModelVersion
    condition: ColumnElement[bool]
    orphan_marks: list[OrphanMark]
    notes: list[str]
    visible: ColumnElement[bool] = field(default_factory=true)
    restricts_visible: bool = False  # há regras Isolar ou Ocultar
    emphasis: bool = False


def _combine(logic: str, items: list[Any], empty: Any) -> Any:
    """E/OU de condições SQL (ou de bools); sem itens, `empty`."""
    if not items:
        return empty
    if isinstance(items[0], bool):
        return all(items) if logic == "and" else any(items)
    return and_(*items) if logic == "and" else or_(*items)


def _by_mode(definition: FilterDef, items: list[Any]) -> dict[str, list[Any]]:
    out: dict[str, list[Any]] = {"isolate": [], "hide": [], "highlight": []}
    for rule, item in zip(definition.rules, items, strict=True):
        out[definition.rule_mode(rule)].append(item)
    return out


def _orphan_text_matches(q: str, mark: OrphanMark) -> bool:
    return all(t in _fold(mark.code) or t in _fold(mark.category) for t in _fold(q).split())


def text_condition(token: str) -> ColumnElement[bool]:
    """Uma palavra do "Pesquisar por objetos" (mesma regra da busca de marcas): aparece
    no texto de busca da peça, na categoria, no código da marca ou num valor de parâmetro
    da fábrica da marca. Peças sem marca também entram (pelo texto e pela categoria)."""
    pattern = func.f_unaccent(func.lower(literal(f"%{_like(token)}%")))

    def ilike(column: Any) -> ColumnElement[bool]:
        return func.f_unaccent(func.lower(column)).like(pattern, escape="\\")

    mark = aliased(Mark)
    in_mark = exists(
        select(mark.id).where(
            mark.id == Element.mark_id,
            or_(
                ilike(mark.code),
                exists(
                    select(ParamValue.id).where(
                        ParamValue.mark_id == mark.id, ilike(cast(ParamValue.value, Text))
                    )
                ),
            ),
        )
    )
    return or_(ilike(Element.search_text), ilike(Element.category), in_mark)


def _orphan_rule_matches(rule: Rule, field: FilterField, mark: OrphanMark) -> bool:
    """Uma regra numa marca órfã: só há Nome da montagem, categoria e "órfã = sim";
    os outros campos não têm valor (só "vazio", "diferente de" e "não contém" batem)."""
    if field.source == SYSTEM and field.key == "orphan":
        return rule.value is (rule.op == "eq")
    if field.source == SYSTEM and field.key in ("mark", "category"):
        args = _text_args(0, field, rule)
        value = mark.code if field.key == "mark" else mark.category
        return _text_matches(rule.op, args, value or None)
    return rule.op in ("empty", "ne", "not_contains")


async def _orphan_marks(
    ctx: _Context, definition: FilterDef, fields: list[FilterField]
) -> list[OrphanMark]:
    """Marcas órfãs (abertas) da obra que batem no filtro. Só entram quando o filtro usa
    o campo "Órfã": um filtro comum (ex.: Categoria = Pilar) não lista marcas sem peças."""
    if not any(f.source == SYSTEM and f.key == "orphan" for f in fields):
        return []
    rows = await ctx.session.execute(
        select(Mark.id, Mark.code, Mark.category).where(
            Mark.obra_id == ctx.version.obra_id,
            exists(
                select(Orphan.id).where(
                    Orphan.mark_id == Mark.id, Orphan.status == OrphanStatus.OPEN.value
                )
            ),
        )
    )
    out = []
    for mark_id, code, category in rows:
        mark = OrphanMark(mark_id, code, category)
        hits = [
            _orphan_rule_matches(r, f, mark) for r, f in zip(definition.rules, fields, strict=True)
        ]
        groups = _by_mode(definition, hits)
        if (
            _combine(definition.logic, groups["isolate"], True)
            and not any(groups["hide"])
            and _combine(definition.logic, groups["highlight"], True)
        ):
            out.append(mark)
    return sorted(out, key=lambda m: (m.code, m.category))


async def compile_filter(
    session: AsyncSession, version_id: int, definition: FilterDef, today: date
) -> CompiledFilter:
    """Valida as regras (422 com a regra e o campo) e monta a condição SQL."""
    version = await get_ready_version(session, version_id)
    ctx = _Context(session, version, today)
    conds: list[ColumnElement[bool]] = []
    fields: list[FilterField] = []
    for i, rule in enumerate(definition.rules):
        f = await resolve_field(session, version, rule.field)
        fields.append(f)
        conds.append(await _condition(ctx, i, rule, f))
    groups = _by_mode(definition, conds)
    isolate = _combine(definition.logic, groups["isolate"], None)
    hide = or_(*groups["hide"]) if groups["hide"] else None
    highlight = _combine(definition.logic, groups["highlight"], None)
    q = definition.q.strip()
    tokens = [t[:MAX_TEXT_VALUE] for t in q.split()[:20]]

    visible: ColumnElement[bool] = and_(
        isolate if isolate is not None else true(), ~hide if hide is not None else true()
    )
    result = and_(
        visible,
        highlight if highlight is not None else true(),
        *[text_condition(t) for t in tokens],
    )
    orphans = [
        o for o in await _orphan_marks(ctx, definition, fields) if _orphan_text_matches(q, o)
    ]
    return CompiledFilter(
        version,
        result,
        orphans,
        ctx.notes,
        visible=visible,
        restricts_visible=isolate is not None or hide is not None,
        emphasis=highlight is not None or bool(tokens),
    )


@dataclass(frozen=True)
class PieceRow:
    id: int
    dbid: int
    mark_id: int | None
    category: str
    members: list[int]


async def matching_pieces(session: AsyncSession, compiled: CompiledFilter) -> list[PieceRow]:
    """Peças da versão que batem no filtro (na ordem do dbId)."""
    rows = await session.execute(
        select(Element.id, Element.dbid, Element.mark_id, Element.category, Element.member_dbids)
        .where(Element.version_id == compiled.version.id, compiled.condition)
        .order_by(Element.dbid)
    )
    return [PieceRow(i, d, m, c or "", list(mem or [])) for i, d, m, c, mem in rows]


@dataclass(frozen=True)
class MatchedPiece:
    dbid: int
    mark_id: int | None


@dataclass(frozen=True)
class MarkGroup:
    mark_id: int | None
    code: str | None  # Nome da montagem (None = peças sem marca)
    category: str
    matched: int
    total: int


@dataclass(frozen=True)
class Evaluation:
    mode: str
    logic: str
    total_pieces: int
    matched_pieces: int
    matched_marks: int
    pieces: list[MatchedPiece]
    dbids: list[int]  # peças que bateram + todos os membros delas (para o 3D)
    groups: list[MarkGroup]
    notes: list[str] = field(default_factory=list)
    # 3D: "isolate" = só o resultado à vista; "highlight" = resultado normal, o resto
    # esmaecido, e as peças de `hidden_dbids` (fora das visíveis) ocultas
    view: str = "isolate"
    hidden_dbids: list[int] = field(default_factory=list)


async def _hidden_dbids(session: AsyncSession, compiled: CompiledFilter) -> list[int]:
    """Peças fora das visíveis (+ membros): ocultas quando o resto fica esmaecido."""
    if not (compiled.emphasis and compiled.restricts_visible):
        return []
    out: set[int] = set()
    for dbid, members in await session.execute(
        select(Element.dbid, Element.member_dbids).where(
            Element.version_id == compiled.version.id, ~compiled.visible
        )
    ):
        out.add(dbid)
        out.update(members or [])
    return sorted(out)


async def evaluate(
    session: AsyncSession, version_id: int, definition: FilterDef, today: date
) -> Evaluation:
    compiled = await compile_filter(session, version_id, definition, today)
    rows = await matching_pieces(session, compiled)
    totals: dict[tuple[int | None, str], int] = {}
    for mark_id, category, n in await session.execute(
        select(Element.mark_id, Element.category, func.count())
        .where(Element.version_id == version_id)
        .group_by(Element.mark_id, Element.category)
    ):
        totals[(mark_id, category or "")] = int(n)

    matched: dict[tuple[int | None, str], int] = defaultdict(int)
    dbids: set[int] = set()
    pieces: list[MatchedPiece] = []
    for row in rows:
        pieces.append(MatchedPiece(row.dbid, row.mark_id))
        dbids.add(row.dbid)
        dbids.update(row.members)
        matched[(row.mark_id, row.category)] += 1

    mark_ids = {m for m, _ in matched if m is not None}
    marks = {
        m.id: m
        for m in (
            await session.scalars(select(Mark).where(Mark.id.in_(mark_ids))) if mark_ids else []
        )
    }
    groups: list[MarkGroup] = []
    by_mark: dict[int, int] = defaultdict(int)  # uma marca = (obra, código, categoria)
    for (mark_id, _category), n in matched.items():
        if mark_id is not None:
            by_mark[mark_id] += n
    for mark_id, n in by_mark.items():
        mark = marks[mark_id]
        total = sum(t for (m, _), t in totals.items() if m == mark_id)
        groups.append(MarkGroup(mark_id, mark.code, mark.category, n, total))
    for orphan in compiled.orphan_marks:  # órfãs: sem peças nesta versão
        if orphan.mark_id not in by_mark:
            groups.append(MarkGroup(orphan.mark_id, orphan.code, orphan.category, 0, 0))
    groups.sort(key=lambda g: (g.code or "", g.category))
    for (mark_id, category), n in sorted(matched.items(), key=lambda kv: kv[0][1]):
        if mark_id is None:
            groups.append(MarkGroup(None, None, category, n, totals.get((None, category), n)))

    return Evaluation(
        mode=definition.mode,
        logic=definition.logic,
        total_pieces=sum(totals.values()),
        matched_pieces=len(pieces),
        matched_marks=sum(1 for g in groups if g.mark_id is not None),
        pieces=pieces,
        dbids=sorted(dbids),
        groups=groups,
        notes=compiled.notes,
        view="highlight" if compiled.emphasis else "isolate",
        hidden_dbids=await _hidden_dbids(session, compiled),
    )
