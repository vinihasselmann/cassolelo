"""Cores no 3D: esquemas de cores (regras por filtro) e coloração por campo.

**Esquema:** lista ordenada de regras {filtro, cor, rótulo}. Cada peça fica com a cor da
PRIMEIRA regra que bate; os membros da peça (vínculos, montagens) recebem a mesma cor.

**Coloração por campo:**
- `distinct`: cada valor recebe uma cor de uma paleta categórica ESTÁVEL: a cor sai de
  um hash do valor (sem maiúsculas nem acentos), então o mesmo valor tem a mesma cor em
  qualquer versão, obra ou chamada. "Sem valor" fica cinza. O status de produção usa as
  cores fixas do app.
- `range` (números e datas): 5 faixas de mesma largura entre o menor e o maior valor,
  num gradiente; a última faixa inclui o limite superior.
"""

from __future__ import annotations

import zlib
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Element, PieceProp, SavedFilter, User
from app.services import filters
from app.services.errors import ValidationError
from app.services.filters import (
    BOOL,
    COMPUTED_FIELDS,
    FieldRef,
    FilterDef,
    _fold,
    resolve_field,
)
from app.services.piece_props import DATE, NUMBER, STATUS_LABELS, SYSTEM
from app.services.saved_filters import SchemeRule, get_scheme, is_visible
from app.services.version_data import get_ready_version

# Paleta categórica: 20 cores (pares escuro/claro bem separados; nenhuma é cinza). O
# índice vem de um hash do valor: dois valores PODEM cair na mesma cor (mais provável
# com muitos valores); em troca, a cor de um valor nunca muda.
PALETTE = (
    "#1F77B4",
    "#AEC7E8",
    "#FF7F0E",
    "#FFBB78",
    "#2CA02C",
    "#98DF8A",
    "#D62728",
    "#FF9896",
    "#9467BD",
    "#C5B0D5",
    "#8C564B",
    "#C49C94",
    "#E377C2",
    "#F7B6D2",
    "#BCBD22",
    "#DBDB8D",
    "#17BECF",
    "#9EDAE5",
    "#393B79",
    "#E7BA52",
)
NO_VALUE_COLOR = "#9AA0A6"
NO_VALUE_LABEL = "Sem valor"
# Gradiente das 5 faixas (claro → escuro)
RANGE_COLORS = ("#C6DBEF", "#8DB7DD", "#4F8FC9", "#2565A8", "#0B3C78")
RANGE_BANDS = len(RANGE_COLORS)
# Status de produção: as mesmas cores da tela (mockup)
STATUS_COLORS = {
    "Pendente": "#B9BEC6",
    "Parcial": "#E3B341",
    "Completa": "#33A06F",
    "Revisar": "#E8743B",
}
MAX_DISTINCT = 500


def stable_color(value: str) -> str:
    """Mesma cor para o mesmo valor, sempre (hash CRC32 do valor normalizado)."""
    key = _fold(" ".join(value.split()))
    return PALETTE[zlib.crc32(key.encode("utf-8")) % len(PALETTE)]


@dataclass(frozen=True)
class _Piece:
    id: int
    dbid: int
    mark_id: int | None
    members: list[int]


async def _pieces(session: AsyncSession, version_id: int) -> list[_Piece]:
    rows = await session.execute(
        select(Element.id, Element.dbid, Element.mark_id, Element.member_dbids)
        .where(Element.version_id == version_id)
        .order_by(Element.dbid)
    )
    return [_Piece(i, d, m, list(mem or [])) for i, d, m, mem in rows]


def _paint(colors: dict[int, str], dbid: int, members: list[int], color: str) -> None:
    for d in (dbid, *members):
        colors.setdefault(d, color)


# ------------------------------------------------------------------ esquemas


class SchemeEvaluateInput(BaseModel):
    """Um esquema salvo (`scheme_id`) ou regras ainda não salvas (`rules`, prévia)."""

    model_config = ConfigDict(extra="forbid")
    scheme_id: int | None = None
    rules: list[SchemeRule] | None = None

    @model_validator(mode="after")
    def _one(self) -> SchemeEvaluateInput:
        if (self.scheme_id is None) == (self.rules is None):
            raise ValueError("Informe scheme_id OU rules.")
        return self


@dataclass(frozen=True)
class RuleResult:
    index: int
    label: str
    color: str
    filter_id: int | None
    matched: int  # peças que batem no filtro da regra
    pieces: int  # peças que ficaram com a cor desta regra (as anteriores têm prioridade)
    dbids: list[int] = field(default_factory=list)  # essas peças (sem membros): legenda


@dataclass(frozen=True)
class SchemeResult:
    colors: dict[int, str]  # dbId (peças e membros) -> cor
    rules: list[RuleResult]
    total_pieces: int
    colored_pieces: int
    notes: list[str] = field(default_factory=list)


async def evaluate_scheme(
    session: AsyncSession,
    version_id: int,
    body: SchemeEvaluateInput,
    user: User,
    today: date,
) -> SchemeResult:
    version = await get_ready_version(session, version_id)
    if body.scheme_id is not None:
        scheme = await get_scheme(session, body.scheme_id, user)
        if scheme.obra_id is not None and scheme.obra_id != version.obra_id:
            raise ValidationError(f'O esquema "{scheme.name}" é de outra obra.')
        rules = [SchemeRule.model_validate(r) for r in scheme.rules]
    else:
        rules = body.rules or []

    # Compila todas as regras e avalia TODAS numa consulta só (uma coluna sim/não por
    # regra): uma passada pelas peças, em vez de uma por regra.
    notes: list[str] = []
    labels: list[tuple[str, int | None]] = []
    active: list[int] = []  # índices das regras com filtro disponível
    conds: list[Any] = []
    for i, rule in enumerate(rules):
        definition, label, filter_id = await _rule_filter(session, rule, user, version.obra_id)
        labels.append((label, filter_id))
        if definition is None:
            notes.append(f'Regra {i + 1} ("{label}"): filtro não disponível; ignorada.')
            continue
        compiled = await filters.compile_filter(session, version_id, definition, today)
        notes.extend(n for n in compiled.notes if n not in notes)
        active.append(i)
        conds.append(compiled.condition.label(f"r{i}"))
    rows = await session.execute(
        select(Element.dbid, Element.member_dbids, *conds)
        .where(Element.version_id == version_id)
        .order_by(Element.dbid)
    )
    colors: dict[int, str] = {}
    matched = dict.fromkeys(range(len(rules)), 0)
    painted = dict.fromkeys(range(len(rules)), 0)
    painted_ids: dict[int, list[int]] = defaultdict(list)
    total = colored = 0
    for row in rows:
        total += 1
        winner: int | None = None
        for pos, i in enumerate(active):
            if row[2 + pos]:
                matched[i] += 1
                if winner is None:
                    winner = i
        if winner is not None:
            colored += 1
            painted[winner] += 1
            painted_ids[winner].append(row[0])
            _paint(colors, row[0], list(row[1] or []), rules[winner].color)
    results = [
        RuleResult(
            i, labels[i][0], rule.color, labels[i][1], matched[i], painted[i], painted_ids[i]
        )
        for i, rule in enumerate(rules)
    ]
    return SchemeResult(colors, results, total, colored, notes)


async def _rule_filter(
    session: AsyncSession, rule: SchemeRule, user: User, obra_id: int
) -> tuple[FilterDef | None, str, int | None]:
    if isinstance(rule.filter, FilterDef):
        return rule.filter, rule.label or "Filtro", None
    saved = await session.get(SavedFilter, rule.filter)
    if saved is None or not is_visible(saved, user):
        return None, rule.label or f"filtro {rule.filter}", rule.filter
    label = rule.label or saved.name
    if saved.obra_id is not None and saved.obra_id != obra_id:
        return None, label, saved.id
    return FilterDef.model_validate(saved.definition), label, saved.id


# --------------------------------------------------------- coloração por campo


class ColorizeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: FieldRef
    mode: Literal["distinct", "range"] = "distinct"


@dataclass(frozen=True)
class LegendItem:
    label: str
    color: str
    pieces: int
    value: str | None = None  # distinct: o valor; None = sem valor
    min: Any = None  # range: limites da faixa (número ou data ISO)
    max: Any = None
    dbids: list[int] = field(default_factory=list)  # peças do item (sem membros): legenda


@dataclass(frozen=True)
class ColorizeResult:
    mode: str
    field_name: str
    field_type: str
    colors: dict[int, str]
    legend: list[LegendItem]
    total_pieces: int


async def _status_values(
    session: AsyncSession, version_id: int, pieces: list[_Piece]
) -> dict[int, str]:
    from app.services.mark_status import version_statuses

    statuses = (await version_statuses(session, version_id)).statuses
    labels = {m: STATUS_LABELS[s] for m, s in statuses.items()}
    return {p.id: labels[p.mark_id] for p in pieces if p.mark_id in labels}


async def colorize(session: AsyncSession, version_id: int, body: ColorizeInput) -> ColorizeResult:
    version = await get_ready_version(session, version_id)
    fdef = await resolve_field(session, version, body.field)
    if fdef.type == BOOL or (fdef.source == SYSTEM and fdef.key in COMPUTED_FIELDS):
        raise ValidationError(f'Não dá para colorir por "{fdef.name}".')
    pieces = await _pieces(session, version_id)
    is_status = fdef.source == SYSTEM and fdef.key == "status"

    if body.mode == "range":
        if fdef.type not in (NUMBER, DATE):
            raise ValidationError(
                f'"{fdef.name}" é texto: a coloração por faixas vale para números e datas.'
            )
        return await _colorize_range(session, version_id, fdef, pieces)

    if is_status:
        values = await _status_values(session, version_id, pieces)
    else:
        rows = await session.execute(
            select(PieceProp.piece_id, PieceProp.value_text).where(
                PieceProp.version_id == version_id,
                PieceProp.source == fdef.source,
                PieceProp.key == fdef.key,
            )
        )
        values = {pid: text for pid, text in rows}
    distinct = set(values.values())
    if len(distinct) > MAX_DISTINCT:
        raise ValidationError(
            f'"{fdef.name}" tem {len(distinct)} valores diferentes (o limite é {MAX_DISTINCT}). '
            "Use faixas (números e datas) ou um filtro."
        )

    def color_of(value: str) -> str:
        return STATUS_COLORS.get(value, stable_color(value)) if is_status else stable_color(value)

    colors: dict[int, str] = {}
    ids: dict[str | None, list[int]] = defaultdict(list)
    for p in pieces:
        value = values.get(p.id)
        ids[value].append(p.dbid)
        _paint(colors, p.dbid, p.members, NO_VALUE_COLOR if value is None else color_of(value))
    legend = [
        LegendItem(value, color_of(value), len(d), value=value, dbids=d)
        for value, d in sorted(
            ((v, d) for v, d in ids.items() if v is not None), key=lambda kv: (-len(kv[1]), kv[0])
        )
    ]
    if ids.get(None):
        legend.append(LegendItem(NO_VALUE_LABEL, NO_VALUE_COLOR, len(ids[None]), dbids=ids[None]))
    return ColorizeResult("distinct", fdef.name, fdef.type, colors, legend, len(pieces))


async def _colorize_range(
    session: AsyncSession, version_id: int, fdef: filters.FilterField, pieces: list[_Piece]
) -> ColorizeResult:
    col = PieceProp.value_num if fdef.type == NUMBER else PieceProp.value_date
    rows = await session.execute(
        select(PieceProp.piece_id, col).where(
            PieceProp.version_id == version_id,
            PieceProp.source == fdef.source,
            PieceProp.key == fdef.key,
            col.is_not(None),
        )
    )
    raw: dict[int, Any] = {pid: v for pid, v in rows}
    # datas viram o nº do dia (ordinal) para dividir em faixas
    nums: dict[int, Decimal] = {
        pid: Decimal(v.toordinal()) if isinstance(v, date) else Decimal(v) for pid, v in raw.items()
    }

    def out(v: Decimal) -> Any:
        if fdef.type == DATE:
            return date.fromordinal(int(v)).isoformat()
        return float(v)

    bands: list[tuple[Decimal, Decimal]] = []
    if nums:
        lo, hi = min(nums.values()), max(nums.values())
        count = 1 if lo == hi else RANGE_BANDS
        width = (hi - lo) / count
        bands = [
            (lo + width * i, hi if i == count - 1 else lo + width * (i + 1)) for i in range(count)
        ]
        if fdef.type == DATE:  # limites em dias inteiros, sem sobrepor
            bands = _whole_day_bands(lo, hi, count)

    def band_of(v: Decimal) -> int:
        for i, (_, b_hi) in enumerate(bands):
            if v <= b_hi or i == len(bands) - 1:
                return i
        return len(bands) - 1  # pragma: no cover

    def band_color(i: int) -> str:
        # com 1 faixa só, a cor do meio do gradiente
        return RANGE_COLORS[RANGE_BANDS // 2] if len(bands) == 1 else RANGE_COLORS[i]

    colors: dict[int, str] = {}
    band_ids: list[list[int]] = [[] for _ in bands]
    no_value: list[int] = []
    for p in pieces:
        if p.id in nums:
            i = band_of(nums[p.id])
            band_ids[i].append(p.dbid)
            _paint(colors, p.dbid, p.members, band_color(i))
        else:
            no_value.append(p.dbid)
            _paint(colors, p.dbid, p.members, NO_VALUE_COLOR)
    legend = [
        LegendItem(
            _band_label(out(b_lo), out(b_hi)),
            band_color(i),
            len(band_ids[i]),
            min=out(b_lo),
            max=out(b_hi),
            dbids=band_ids[i],
        )
        for i, (b_lo, b_hi) in enumerate(bands)
    ]
    if no_value:
        legend.append(LegendItem(NO_VALUE_LABEL, NO_VALUE_COLOR, len(no_value), dbids=no_value))
    return ColorizeResult("range", fdef.name, fdef.type, colors, legend, len(pieces))


def _whole_day_bands(lo: Decimal, hi: Decimal, count: int) -> list[tuple[Decimal, Decimal]]:
    """Faixas de datas em dias inteiros: [início, fim] sem sobrepor, cobrindo lo..hi."""
    span = int(hi - lo) + 1  # dias no intervalo
    count = min(count, span)
    out: list[tuple[Decimal, Decimal]] = []
    start = int(lo)
    for i in range(count):
        end = int(lo) + (span * (i + 1)) // count - 1
        out.append((Decimal(start), Decimal(end)))
        start = end + 1
    return out


def _band_label(lo: Any, hi: Any) -> str:
    def fmt(v: Any) -> str:
        if isinstance(v, float):
            return f"{v:.6g}"
        return str(v)

    return fmt(lo) if lo == hi else f"{fmt(lo)} – {fmt(hi)}"
