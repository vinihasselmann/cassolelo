"""Sequência de montagem: ordem das peças pelas coordenadas do centro de gravidade.

Decisão de 2026-11-18 (revista no mesmo dia): X, depois Y, depois Z, crescente — a mesma
ordem do Dynamo usado pela equipe. Em cada eixo, peças a até `tol` (0,10 m) do início da
faixa contam como a mesma posição, e decide o eixo seguinte. Assim, duas peças com 2 mm
de diferença em X ficam lado a lado, ordenadas por Y.

Função pura: a ordem dentro de uma posição idêntica é a de entrada (sort estável).
"""

from __future__ import annotations

from collections.abc import Sequence

Point = tuple[float, float, float]

TOLERANCE_M = 0.10
AXES = (0, 1, 2)  # X, Y, Z (como o Dynamo da equipe)
AXIS_NAMES = "X → Y → Z"


def sequence[T](items: Sequence[tuple[T, Point]], tol: float = TOLERANCE_M) -> list[T]:
    """Itens [(chave, (x, y, z) em metros)] na sequência de montagem."""

    def go(group: list[tuple[T, Point]], depth: int) -> list[tuple[T, Point]]:
        if depth == len(AXES) or len(group) <= 1:
            return group
        axis = AXES[depth]
        ordered = sorted(group, key=lambda it: it[1][axis])
        out: list[tuple[T, Point]] = []
        band: list[tuple[T, Point]] = []
        start = 0.0
        for it in ordered:
            value = it[1][axis]
            if band and value - start > tol:
                out += go(band, depth + 1)
                band = []
            if not band:
                start = value
            band.append(it)
        out += go(band, depth + 1)
        return out

    return [key for key, _ in go(list(items), 0)]
