"""Motor de reconciliação entre versões (Fase 7.1). Funções PURAS: nada de banco aqui.

Compara as marcas da versão anterior com as da nova e classifica cada uma:

- unchanged: mesma marca (código + categoria), mesma quantidade, mesmas propriedades de
  revisão. Posição, rotação, externalId etc. NÃO contam (peça movida ou apagada e
  recriada no Revit continua a mesma marca);
- count_changed: só a quantidade de peças mudou;
- changed: alguma propriedade de revisão mudou (diff campo a campo). Tem precedência
  sobre count_changed; as duas quantidades ficam no resultado;
- new: marca só existe na nova versão (inclui renomeada: PP001 → PP001A = removed + new);
- removed: marca só existe na anterior.

Propriedades de revisão = DIMENSION_PROPERTY_NAMES (comparadas em mm, com a tolerância
DIMENSION_TOLERANCE_MM) + REVIEW_PROPERTY_NAMES (comparadas como texto, sem diferenciar
maiúsculas nem espaços). Cada propriedade guarda o CONJUNTO de valores das peças da
marca (uma marca inconsistente compara o conjunto inteiro).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.config import Settings
from app.services.extraction import find_prop, normalize_mark
from app.services.mark_validation import to_mm

EMPTY = "—"


class Change(StrEnum):
    UNCHANGED = "unchanged"
    COUNT_CHANGED = "count_changed"
    CHANGED = "changed"
    NEW = "new"
    REMOVED = "removed"


@dataclass(frozen=True)
class ReconcileConfig:
    dimension_names: list[str]
    review_names: list[str]
    tolerance_mm: float = 5.0

    @property
    def property_names(self) -> list[str]:
        """Dimensões primeiro, depois as de revisão (sem repetir), na ordem configurada."""
        seen: set[str] = set()
        out = []
        for name in [*self.dimension_names, *self.review_names]:
            if name.casefold() not in seen:
                seen.add(name.casefold())
                out.append(name)
        return out

    @classmethod
    def from_settings(cls, settings: Settings) -> ReconcileConfig:
        return cls(
            dimension_names=settings.dimension_property_list,
            review_names=settings.review_property_list,
            tolerance_mm=settings.dimension_tolerance_mm,
        )

    def is_dimension(self, name: str) -> bool:
        return name.casefold() in {n.casefold() for n in self.dimension_names}


@dataclass(frozen=True)
class ElementInput:
    """Uma peça da versão, como sai da extração (só o que a reconciliação usa)."""

    mark_code: str | None
    category: str
    external_id: str | None
    props: Mapping[str, Any]


@dataclass(frozen=True)
class MarkSnapshot:
    code: str
    category: str
    count: int
    # propriedade -> valores distintos entre as peças (vazio = a propriedade não existe)
    props: Mapping[str, tuple[str, ...]]

    @property
    def key(self) -> tuple[str, str]:
        return (self.code, self.category)


@dataclass(frozen=True)
class PropDiff:
    property: str
    before: str | None  # None = a propriedade não existia
    after: str | None

    def text(self) -> str:
        return f"{self.property}: {self.before or EMPTY} → {self.after or EMPTY}"


@dataclass(frozen=True)
class MarkResult:
    code: str
    category: str
    change: Change
    prev_count: int  # 0 quando a marca é nova
    curr_count: int  # 0 quando a marca foi removida
    diffs: tuple[PropDiff, ...] = ()

    @property
    def count_changed(self) -> bool:
        return self.prev_count != self.curr_count

    def summary(self) -> str:
        """Texto do diff para a nota de revisão (ex.: "Seção: 40x60 → 40x80")."""
        return "; ".join(d.text() for d in self.diffs)


@dataclass(frozen=True)
class ReconcileResult:
    marks: list[MarkResult]  # ordenadas por (código, categoria)

    def of(self, change: Change) -> list[MarkResult]:
        return [m for m in self.marks if m.change is change]

    @property
    def totals(self) -> dict[Change, int]:
        return {c: len(self.of(c)) for c in Change}


# --------------------------------------------------------------------------- snapshots


def build_snapshots(
    elements: Iterable[ElementInput], config: ReconcileConfig
) -> list[MarkSnapshot]:
    """Agrupa as peças por marca (código normalizado + categoria) e lê só as propriedades
    de revisão. Peças sem Marca não formam marca."""
    names = config.property_names
    count: dict[tuple[str, str], int] = defaultdict(int)
    values: dict[tuple[str, str], dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for el in elements:
        code = normalize_mark(el.mark_code)
        if code is None:
            continue
        key = (code, el.category)
        count[key] += 1
        bucket = values[key]
        for name in names:
            raw = find_prop(dict(el.props), [name])
            if raw is not None:
                bucket[name].add(" ".join(raw.split()))
    return [
        MarkSnapshot(
            code=code,
            category=category,
            count=count[(code, category)],
            props={n: tuple(sorted(v)) for n, v in values[(code, category)].items()},
        )
        for code, category in sorted(count)
    ]


# --------------------------------------------------------------------------- comparação


def _mm_set(values: tuple[str, ...], tolerance: float) -> list[float] | None:
    """Valores em mm, ordenados e sem repetir (dentro da tolerância); None se algum não
    for uma medida (aí compara como texto)."""
    mm = [to_mm(v) for v in values]
    if any(x is None for x in mm):
        return None
    merged: list[float] = []
    for x in sorted(x for x in mm if x is not None):
        if not merged or x - merged[-1] > tolerance:
            merged.append(x)
    return merged


def _text_set(values: tuple[str, ...]) -> set[str]:
    return {" ".join(v.split()).casefold() for v in values}


def _same(
    name: str, before: tuple[str, ...], after: tuple[str, ...], config: ReconcileConfig
) -> bool:
    if not before or not after:
        return not before and not after
    if config.is_dimension(name):
        a, b = _mm_set(before, config.tolerance_mm), _mm_set(after, config.tolerance_mm)
        if a is not None and b is not None:
            return len(a) == len(b) and all(
                abs(x - y) <= config.tolerance_mm for x, y in zip(a, b, strict=True)
            )
    return _text_set(before) == _text_set(after)


def _display(values: tuple[str, ...]) -> str | None:
    return " / ".join(values) if values else None


def _diffs(prev: MarkSnapshot, curr: MarkSnapshot, config: ReconcileConfig) -> tuple[PropDiff, ...]:
    out = []
    for name in config.property_names:
        before, after = prev.props.get(name, ()), curr.props.get(name, ())
        if not _same(name, before, after, config):
            out.append(PropDiff(name, _display(before), _display(after)))
    return tuple(out)


def _index(snapshots: list[MarkSnapshot], label: str) -> dict[tuple[str, str], MarkSnapshot]:
    out: dict[tuple[str, str], MarkSnapshot] = {}
    for s in snapshots:
        if s.key in out:
            raise ValueError(f"Marca repetida na versão {label}: {s.code} ({s.category}).")
        out[s.key] = s
    return out


def reconcile(
    prev: list[MarkSnapshot], curr: list[MarkSnapshot], config: ReconcileConfig
) -> ReconcileResult:
    before, after = _index(prev, "anterior"), _index(curr, "nova")
    results = []
    for key in sorted(before.keys() | after.keys()):
        p, c = before.get(key), after.get(key)
        code, category = key
        if p is None and c is not None:
            results.append(MarkResult(code, category, Change.NEW, 0, c.count))
        elif c is None and p is not None:
            results.append(MarkResult(code, category, Change.REMOVED, p.count, 0))
        elif p is not None and c is not None:
            diffs = _diffs(p, c, config)
            if diffs:
                change = Change.CHANGED
            elif p.count != c.count:
                change = Change.COUNT_CHANGED
            else:
                change = Change.UNCHANGED
            results.append(MarkResult(code, category, change, p.count, c.count, diffs))
    return ReconcileResult(results)
