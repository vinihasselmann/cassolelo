"""Relatório de validação de marcas de uma versão (gerado ao fim de process_version).

- peças sem Marca;
- marcas inconsistentes: mesma marca + categoria com dimensões diferentes
- peças com identificadores divergentes: a regra da obra tem mais de um parâmetro
  (ex.: Nome da montagem e Marca) e a peça traz valores DIFERENTES neles; vale o
  primeiro da lista, o outro fica como apelido (também entra na busca);
  (DIMENSION_PROPERTY_NAMES, tolerância DIMENSION_TOLERANCE_MM);
- totais: peças, marcas e por categoria.

`build_report` é puro (recebe os elementos já extraídos); `save_report` grava em
version_reports (uma linha por versão, substituída a cada reprocessamento).
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import VersionReport
from app.services.extraction import ExtractedElement, find_prop, normalize_mark

Report = dict[str, Any]

_LENGTH = re.compile(r"^\s*(-?\d+(?:[.,]\d+)?)\s*(mm|cm|m)?\s*$", re.IGNORECASE)
_TO_MM = {"mm": 1.0, "cm": 10.0, "m": 1000.0}


def to_mm(value: str) -> float | None:
    """ "600.0 cm" -> 6000.0; "0,6 m" -> 600.0; "250" -> 250.0 (sem unidade = mm).
    Outros formatos (pés/polegadas, texto) -> None (comparados como texto)."""
    m = _LENGTH.match(value)
    if not m:
        return None
    number = float(m.group(1).replace(",", "."))
    return number * _TO_MM[(m.group(2) or "mm").lower()]


def difference(
    name: str, values: list[tuple[ExtractedElement, str]], tolerance_mm: float
) -> dict[str, Any] | None:
    """Diferença numa dimensão entre as peças de uma marca, ou None se coerente."""
    mm = [to_mm(v) for _, v in values]
    numeric = all(x is not None for x in mm)
    diff_mm: float | None = None
    if numeric:
        nums = [x for x in mm if x is not None]
        diff_mm = round(max(nums) - min(nums), 3)
        if diff_mm <= tolerance_mm:
            return None
    elif len({v.strip().casefold() for _, v in values}) <= 1:
        return None

    by_value: dict[str, list[int]] = defaultdict(list)
    for el, v in values:
        by_value[v.strip()].append(el.dbid)
    return {
        "property": name,
        "diff_mm": diff_mm,
        "values": [
            {"value": v, "mm": to_mm(v), "count": len(ids), "dbids": sorted(ids)}
            for v, ids in sorted(by_value.items(), key=lambda kv: (-len(kv[1]), kv[0]))
        ],
    }


def build_report(
    version_id: int,
    elements: list[ExtractedElement],
    dimension_names: list[str],
    tolerance_mm: float,
    mark_names: list[str] | None = None,
) -> Report:
    by_mark: dict[tuple[str, str], list[ExtractedElement]] = defaultdict(list)
    without_mark: list[ExtractedElement] = []
    cats: dict[str, dict[str, Any]] = {}
    for e in elements:
        c = cats.setdefault(e.category, {"pieces": 0, "marks": set(), "without_mark": 0})
        c["pieces"] += 1
        if e.mark_code:
            by_mark[(e.mark_code, e.category)].append(e)
            c["marks"].add(e.mark_code)
        else:
            without_mark.append(e)
            c["without_mark"] += 1

    inconsistent: list[dict[str, Any]] = []
    for (code, category), pieces in sorted(by_mark.items()):
        if len(pieces) < 2:
            continue
        diffs = []
        for name in dimension_names:
            values = [(p, v) for p in pieces if (v := find_prop(p.props, [name])) is not None]
            if len(values) >= 2 and (d := difference(name, values, tolerance_mm)):
                diffs.append(d)
        if diffs:
            inconsistent.append(
                {"mark": code, "category": category, "pieces": len(pieces), "differences": diffs}
            )

    divergent = divergent_pieces(elements, mark_names or [])

    return {
        "version_id": version_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "config": {"dimension_property_names": dimension_names, "tolerance_mm": tolerance_mm},
        "totals": {
            "pieces": len(elements),
            "marks": len(by_mark),
            "without_mark": len(without_mark),
            "inconsistent_marks": len(inconsistent),
            "divergent_pieces": len(divergent),
            "by_category": [
                {
                    "category": cat,
                    "pieces": c["pieces"],
                    "marks": len(c["marks"]),
                    "without_mark": c["without_mark"],
                }
                for cat, c in sorted(cats.items(), key=lambda kv: (-kv[1]["pieces"], kv[0]))
            ],
        },
        "without_mark": [
            {"dbid": e.dbid, "external_id": e.external_id, "category": e.category, "name": e.name}
            for e in sorted(without_mark, key=lambda e: (e.category, e.dbid))
        ],
        "inconsistent": inconsistent,
        "divergent": divergent,
    }


def mark_values(props: dict[str, Any], mark_names: list[str]) -> list[tuple[str, str]]:
    """(parâmetro, valor) de cada nome da regra que a peça tem, na ordem da regra."""
    out: list[tuple[str, str]] = []
    for name in mark_names:
        value = find_prop(props, [name])
        if value is not None:
            out.append((name, value.strip()))
    return out


def mark_origin(
    props: dict[str, Any], mark_names: list[str], mark_code: str | None
) -> tuple[str | None, list[list[str]]]:
    """De qual parâmetro da regra veio o nome da peça e os outros preenchidos.

    Origem = o primeiro da regra cujo valor dá a marca da peça (vale o primeiro: os outros
    são apelidos). Secundários = [[parâmetro, valor], ...] dos demais nomes da regra que a
    peça tem, na ordem da regra (lista, porque o JSONB não guarda a ordem das chaves).
    Peça sem marca: sem origem e sem secundários."""
    if not mark_code:
        return None, []
    values = mark_values(props, mark_names)
    source = next((n for n, v in values if normalize_mark(v) == mark_code), None)
    alt = [[n, v[:255]] for n, v in values if n != source and v]
    return source, alt


def divergent_pieces(
    elements: list[ExtractedElement], mark_names: list[str]
) -> list[dict[str, Any]]:
    """Peças em que os parâmetros da regra têm valores diferentes (ex.: Marca P12 e
    Nome da montagem PP012). Vale o primeiro; os outros são apelidos."""
    if len(mark_names) < 2:
        return []
    out: list[dict[str, Any]] = []
    for e in sorted(elements, key=lambda e: (e.category, e.dbid)):
        values = mark_values(e.props, mark_names)
        if len({normalize_mark(v) for _, v in values}) < 2:
            continue
        out.append(
            {
                "dbid": e.dbid,
                "external_id": e.external_id,
                "category": e.category,
                "name": e.name,
                "mark": e.mark_code,
                "values": [{"property": n, "value": v} for n, v in values],
            }
        )
    return out


async def save_report(session: AsyncSession, version_id: int, report: Report) -> None:
    stmt = pg_insert(VersionReport).values(version_id=version_id, report=report)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_version_reports_version_id",
        set_={"report": stmt.excluded.report, "updated_at": datetime.now(UTC)},
    )
    await session.execute(stmt)


async def get_report(session: AsyncSession, version_id: int) -> VersionReport | None:
    result: VersionReport | None = await session.scalar(
        select(VersionReport).where(VersionReport.version_id == version_id)
    )
    return result
