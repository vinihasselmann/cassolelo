"""Compara dois resultados do spike (spikes/out/coordenadas-*.json): cada peça de A com a
peça de B do mesmo tipo e mais perto (vínculos repetem ElementIds), diferença em mm.

    spikes/.venv/Scripts/python spikes/coordenadas/compare.py orc-rvt orc-ifc
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any

OUT = Path(__file__).resolve().parent.parent / "out"


def load(name: str) -> list[dict[str, Any]]:
    data = json.loads((OUT / f"coordenadas-{name}.json").read_text("utf-8"))
    pieces = []
    seen: set[int] = set()
    for p in data["pieces"]:
        if "error" in p or p["member"]["dbId"] in seen:
            continue
        seen.add(p["member"]["dbId"])
        pts = {k: v["pbp_A_mm"] or v["arquivo_mm"] for k, v in p["points"].items()}
        pieces.append({"kind": p["kind"], "name": p["member"]["name"], "points": pts})
    return pieces


def dist(a: list[float], b: list[float]) -> float:
    return math.dist(a, b)


def pair_distance(a: dict[str, Any], b: dict[str, Any]) -> tuple[float, dict[str, list[float]]]:
    """Maior distância entre os pontos correspondentes (viga: aceita início/fim trocados)."""
    keys = list(a["points"])
    orders = [keys]
    if set(keys) == {"inicio", "fim"}:
        orders.append(["fim", "inicio"])
    best: tuple[float, dict[str, list[float]]] = (math.inf, {})
    for order in orders:
        deltas = {
            k: [x - y for x, y in zip(a["points"][k], b["points"][o], strict=True)]
            for k, o in zip(keys, order, strict=True)
        }
        worst = max(math.hypot(*d) for d in deltas.values())
        if worst < best[0]:
            best = (worst, deltas)
    return best


def compare(name_a: str, name_b: str) -> str:
    a, b = load(name_a), load(name_b)
    lines = [
        f"| Peça ({name_a}) | Ponto | ΔX | ΔY | ΔZ | maior |",
        "|---|---|---|---|---|---|",
    ]
    worst_all = 0.0
    for pa in a:
        same = [pb for pb in b if pb["kind"] == pa["kind"]]
        if not same:
            continue
        worst, deltas = min((pair_distance(pa, pb) for pb in same), key=lambda r: r[0])
        worst_all = max(worst_all, worst)
        for k, d in deltas.items():
            lines.append(
                f"| {pa['kind']} {pa['name'][:40]} | {k} | {d[0]:.2f} | {d[1]:.2f} | {d[2]:.2f} "
                f"| {math.hypot(*d):.2f} |"
            )
    lines.append("")
    lines.append(f"Maior diferença: **{worst_all:.2f} mm** ({len(a)} peças).")
    return "\n".join(lines)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    print(compare(sys.argv[1], sys.argv[2]))
