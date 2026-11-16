"""Assistente "Qual parâmetro identifica as peças?" (análise de uma versão pronta).

Para cada propriedade presente nas peças da versão, simula que ela fosse a marca:
- `pieces_with_value`: peças com valor (cobertura);
- `marks`: quantas marcas sairiam (valor normalizado + categoria);
- `inconsistent_marks` / `inconsistent_pieces`: marcas com peças de dimensões diferentes
  (mesma regra do relatório de validação), a melhor pista de que a propriedade NÃO
  identifica a peça. Só dá para conferir se o modelo tem as propriedades de
  DIMENSION_PROPERTY_NAMES (`dimensions_checked`);
- sinais ruins (vão para o fim da lista):
  - `unique_per_piece`: quase um valor por peça (≥ 90%): id, GUID...;
  - `constant`: um valor só para todas;
  - `measure`: todos os valores são número + unidade (volume, comprimento...).

A ordem favorece cobertura alta e poucas peças inconsistentes. Só lê o que já está no
banco (elements.props): nenhuma chamada ao APS. Peças = as da regra atual; ao trocar a
regra, o reprocessamento extrai de novo a partir do modelo.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Element
from app.services.extraction import ExtractedElement, find_prop, normalize_mark
from app.services.mark_validation import difference
from app.services.version_data import get_ready_version

MAX_EXAMPLES = 5
MAX_VALUE_LENGTH = 100  # marks.code
NEAR_UNIQUE = 0.9
# número + unidade (valores já normalizados em maiúsculas): "940.730 CM", "2.376 M^3"
_MEASURE = re.compile(r"^-?\d+(?:[.,]\d+)?\s*[A-Z][A-Z^²³/0-9]*$")


@dataclass
class Candidate:
    name: str
    groups: set[str] = field(default_factory=set)  # grupos onde a propriedade aparece
    values: dict[int, str] = field(default_factory=dict)  # dbid -> valor normalizado
    pieces_with_value: int = 0
    marks: int = 0
    inconsistent_marks: int = 0
    inconsistent_pieces: int = 0
    unique_per_piece: bool = False
    constant: bool = False
    measure: bool = False
    current: bool = False
    examples: list[tuple[str, int]] = field(default_factory=list)  # (valor, peças)

    @property
    def bad_signal(self) -> bool:
        return self.unique_per_piece or self.constant or self.measure

    @property
    def score(self) -> int:
        return self.pieces_with_value - self.inconsistent_pieces


@dataclass(frozen=True)
class Analysis:
    candidates: list[Candidate]
    dimensions_checked: bool  # alguma peça tem as propriedades de dimensão


@dataclass(frozen=True)
class CandidatesResult:
    version_id: int
    pieces: int
    candidates: list[Candidate]
    dimensions_checked: bool


def _scalar(value: Any) -> str | None:
    if isinstance(value, list):
        value = value[0] if value else None
    if value is None or isinstance(value, dict | bool):
        return None
    text = str(value).strip()
    return text or None


def _collect(elements: list[ExtractedElement], excluded: set[str]) -> dict[str, Candidate]:
    by_key: dict[str, Candidate] = {}
    for el in elements:
        seen: set[str] = set()
        for group, content in el.props.items():
            if not isinstance(content, dict):
                continue
            for name, raw in content.items():
                key = name.casefold()
                if key in excluded or key in seen:
                    continue
                code = normalize_mark(_scalar(raw))
                if code is None or len(code) > MAX_VALUE_LENGTH:
                    continue
                seen.add(key)
                cand = by_key.setdefault(key, Candidate(name=name))
                cand.groups.add(group)
                cand.values[el.dbid] = code
    return by_key


def analyze(
    elements: list[ExtractedElement],
    dimension_names: list[str],
    tolerance_mm: float,
    current_names: list[str],
    limit: int = 20,
    excluded_names: list[str] | None = None,
) -> Analysis:
    """Função pura: candidatos ordenados (o melhor primeiro). Dimensões e
    `excluded_names` (ex.: as propriedades de categoria) não são candidatas."""
    excluded = {n.casefold() for n in [*dimension_names, *(excluded_names or [])]}
    by_key = _collect(elements, excluded)

    by_dbid = {el.dbid: el for el in elements}
    dim_values = {
        el.dbid: {n: v for n in dimension_names if (v := find_prop(el.props, [n])) is not None}
        for el in elements
    }
    current = {n.casefold() for n in current_names}
    out: list[Candidate] = []
    for key, cand in by_key.items():
        groups: dict[tuple[str, str], list[int]] = defaultdict(list)
        for dbid, code in cand.values.items():
            groups[(code, by_dbid[dbid].category)].append(dbid)
        n = cand.pieces_with_value = len(cand.values)
        cand.marks = len(groups)
        cand.unique_per_piece = n > 1 and cand.marks >= NEAR_UNIQUE * n
        distinct = set(cand.values.values())
        cand.constant = n > 1 and len(distinct) == 1
        cand.measure = all(_MEASURE.match(v) for v in distinct)
        cand.current = key in current
        for dbids in groups.values():
            if len(dbids) < 2:
                continue
            for name in dimension_names:
                values = [
                    (by_dbid[d], v) for d in dbids if (v := dim_values[d].get(name)) is not None
                ]
                if len(values) >= 2 and difference(name, values, tolerance_mm):
                    cand.inconsistent_marks += 1
                    cand.inconsistent_pieces += len(dbids)
                    break
        counts: dict[str, int] = defaultdict(int)
        for code in cand.values.values():
            counts[code] += 1
        cand.examples = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:MAX_EXAMPLES]
        cand.values = {}  # não precisa mais (libera memória)
        out.append(cand)

    out.sort(key=lambda c: (c.bad_signal, -c.score, c.inconsistent_marks, c.name.casefold()))
    top = out[:limit]
    top += [c for c in out[limit:] if c.current]  # a regra atual sempre aparece
    return Analysis(top, dimensions_checked=any(dim_values.values()))


async def candidates(
    session: AsyncSession,
    version_id: int,
    dimension_names: list[str],
    tolerance_mm: float,
    current_names: list[str],
    limit: int = 20,
    excluded_names: list[str] | None = None,
) -> CandidatesResult:
    await get_ready_version(session, version_id)
    rows = await session.execute(
        select(Element.dbid, Element.external_id, Element.name, Element.category, Element.props)
        .where(Element.version_id == version_id)
        .order_by(Element.dbid)
    )
    elements = [
        ExtractedElement(
            dbid=dbid,
            external_id=ext,
            name=name,
            category=category or "",
            mark_raw=None,
            mark_code=None,
            props=props or {},
        )
        for dbid, ext, name, category, props in rows
    ]
    result = analyze(elements, dimension_names, tolerance_mm, current_names, limit, excluded_names)
    return CandidatesResult(
        version_id=version_id,
        pieces=len(elements),
        candidates=result.candidates,
        dimensions_checked=result.dimensions_checked,
    )
