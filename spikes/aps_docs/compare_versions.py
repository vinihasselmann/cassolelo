"""Spike 0.3 - Comparar duas versões do mesmo item (saídas do read_model.py).

USO (a partir da raiz do repositório):

    spikes/.venv/Scripts/python spikes/aps_docs/compare_versions.py \
        spikes/out/<item>_v1.json spikes/out/<item>_v2.json [--out spikes/out/compare.csv]

Agrupa por (Marca, categoria) e gera um CSV (separador ";", UTF-8 com BOM,
abre direto no Excel pt-BR) com uma linha por marca:

    marca; categoria; qtd_v1; qtd_v2; situacao;
    external_ids_novos; external_ids_removidos; dimensoes_divergentes

situacao: mantida | quantidade alterada | nova | removida

No terminal: resumo por situação, peças sem Marca em cada versão, marcas cujos
externalId mudaram (peças recriadas no Revit) e marcas com dimensões
diferentes dentro da mesma versão.

Env: DIMENSION_PROPERTY_NAMES (padrão "Comprimento,Largura,Altura,Length,Width,Height").
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from list_docs import ENV_FILE
from read_model import OUT_DIR, env_list, find_prop

DEFAULT_DIMENSION_NAMES = "Comprimento,Largura,Altura,Length,Width,Height"
Key = tuple[str, str]
Dims = tuple[tuple[str, str], ...]

KEPT, CHANGED, NEW, REMOVED = "mantida", "quantidade alterada", "nova", "removida"


@dataclass
class Row:
    mark: str
    category: str
    qty_v1: int
    qty_v2: int
    status: str
    ext_new: list[str] = field(default_factory=list)
    ext_removed: list[str] = field(default_factory=list)
    dims_divergent: list[str] = field(default_factory=list)  # "v1", "v2"


def load(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def group_by_mark(elements: list[dict[str, Any]]) -> dict[Key, list[dict[str, Any]]]:
    groups: dict[Key, list[dict[str, Any]]] = defaultdict(list)
    for e in elements:
        if e.get("mark"):
            groups[(str(e["mark"]), str(e.get("category") or ""))].append(e)
    return groups


def element_dims(element: dict[str, Any], names: list[str]) -> Dims:
    props = element.get("props") or {}
    pairs = []
    for n in names:
        v = find_prop(props, [n])
        if v is not None:
            pairs.append((n, v))
    return tuple(pairs)


def dimension_conflicts(
    groups: dict[Key, list[dict[str, Any]]], names: list[str]
) -> dict[Key, Counter[Dims]]:
    """Marcas cujas peças têm mais de uma combinação de dimensões."""
    out: dict[Key, Counter[Dims]] = {}
    for key, elems in groups.items():
        combos = Counter(d for d in (element_dims(e, names) for e in elems) if d)
        if len(combos) > 1:
            out[key] = combos
    return out


def compare(v1: dict[str, Any], v2: dict[str, Any], dim_names: list[str]) -> list[Row]:
    g1, g2 = group_by_mark(v1["elements"]), group_by_mark(v2["elements"])
    d1, d2 = dimension_conflicts(g1, dim_names), dimension_conflicts(g2, dim_names)
    rows: list[Row] = []
    for key in sorted(set(g1) | set(g2)):
        e1, e2 = g1.get(key, []), g2.get(key, [])
        if not e1:
            status = NEW
        elif not e2:
            status = REMOVED
        elif len(e1) == len(e2):
            status = KEPT
        else:
            status = CHANGED
        ids1 = {str(e["external_id"]) for e in e1 if e.get("external_id")}
        ids2 = {str(e["external_id"]) for e in e2 if e.get("external_id")}
        both = e1 and e2
        rows.append(
            Row(
                mark=key[0],
                category=key[1],
                qty_v1=len(e1),
                qty_v2=len(e2),
                status=status,
                ext_new=sorted(ids2 - ids1) if both else [],
                ext_removed=sorted(ids1 - ids2) if both else [],
                dims_divergent=[v for v, d in (("v1", d1), ("v2", d2)) if key in d],
            )
        )
    return rows


def write_csv(rows: list[Row], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(
            [
                "marca",
                "categoria",
                "qtd_v1",
                "qtd_v2",
                "situacao",
                "external_ids_novos",
                "external_ids_removidos",
                "dimensoes_divergentes",
            ]
        )
        for r in rows:
            w.writerow(
                [
                    r.mark,
                    r.category,
                    r.qty_v1,
                    r.qty_v2,
                    r.status,
                    len(r.ext_new),
                    len(r.ext_removed),
                    ",".join(r.dims_divergent),
                ]
            )


def summary(
    v1: dict[str, Any], v2: dict[str, Any], rows: list[Row], dim_names: list[str], limit: int = 20
) -> list[str]:
    lines: list[str] = []
    n1, n2 = v1.get("version_number"), v2.get("version_number")
    lines.append(f"Comparação {v1.get('file_name')}: v{n1} x v{n2}")
    if v1.get("item_id") != v2.get("item_id"):
        lines.append("AVISO: os dois JSON são de itens diferentes.")
    if isinstance(n1, int) and isinstance(n2, int) and n1 > n2:
        lines.append("AVISO: a primeira versão é mais nova que a segunda.")

    for label, v in (("v1", v1), ("v2", v2)):
        total = len(v["elements"])
        no_mark = sum(1 for e in v["elements"] if not e.get("mark"))
        pct = 100 * no_mark / total if total else 0.0
        lines.append(f"{label}: {total} elementos, {no_mark} sem Marca ({pct:.1f}%)")

    counts = Counter(r.status for r in rows)
    lines.append("Marcas por situação:")
    for status in (KEPT, CHANGED, NEW, REMOVED):
        lines.append(f"  {counts.get(status, 0):>6}  {status}")

    recreated = [r for r in rows if r.ext_new or r.ext_removed]
    lines.append(f"Marcas com externalId alterado (peças recriadas no Revit): {len(recreated)}")
    for r in recreated[:limit]:
        lines.append(
            f"  {r.mark} [{r.category}]: +{len(r.ext_new)} -{len(r.ext_removed)}"
            f"  novos={r.ext_new[:3]} removidos={r.ext_removed[:3]}"
        )

    for label, v in (("v1", v1), ("v2", v2)):
        conflicts = dimension_conflicts(group_by_mark(v["elements"]), dim_names)
        lines.append(f"Marcas com dimensões diferentes em {label}: {len(conflicts)}")
        for (mark, cat), combos in list(conflicts.items())[:limit]:
            variants = "; ".join(
                f"{n}x " + ", ".join(f"{k}={val}" for k, val in dims) for dims, n in combos.items()
            )
            lines.append(f"  {mark} [{cat}]: {variants}")
    if not dim_names:
        lines.append("  (DIMENSION_PROPERTY_NAMES vazio: verificação de dimensões desligada)")
    return lines


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="Compara duas versões geradas pelo read_model.py.")
    p.add_argument("v1", type=Path)
    p.add_argument("v2", type=Path)
    p.add_argument("--out", type=Path, default=OUT_DIR / "compare.csv")
    args = p.parse_args(argv)
    load_dotenv(ENV_FILE)
    dim_names = env_list("DIMENSION_PROPERTY_NAMES", DEFAULT_DIMENSION_NAMES)
    try:
        v1, v2 = load(args.v1), load(args.v2)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERRO ao ler JSON: {exc}", file=sys.stderr)
        return 1
    rows = compare(v1, v2, dim_names)
    write_csv(rows, args.out)
    print("\n".join(summary(v1, v2, rows, dim_names)))
    print(f"\nCSV salvo em {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
