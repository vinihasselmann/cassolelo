"""Sequência de montagem: ordem das peças pelas coordenadas do centro de gravidade.

Decisão de 2026-11-19 (volta à proposta inicial de 2026-11-18): Z, depois X, depois Y,
crescente — de baixo para cima e, na mesma altura, por X e depois por Y. Em cada eixo,
peças a até `tol` (0,10 m) do início da faixa contam como a mesma posição, e decide o
eixo seguinte. Assim, duas peças com 2 mm de diferença em Z ficam na mesma altura,
ordenadas por X.

Cada obra guarda em `obras.sequence_axes` a ordem com que os números das peças foram dados
(`zxy`; `xyz` nas obras numeradas antes de 2026-11-19, pela ordem que vigorou um dia). A
ligação pela ordem (NWD) de uma obra `sequence` usa a ordem DELA, senão uma versão nova
trocaria as peças de lugar dentro da marca, com os valores juntos. O Excel usa sempre a
ordem atual.

Função pura: a ordem dentro de uma posição idêntica é a de entrada (sort estável).
"""

from __future__ import annotations

from collections.abc import Sequence

Point = tuple[float, float, float]

TOLERANCE_M = 0.10
CURRENT = "zxy"  # Z, X, Y (decisão de 2026-11-19)
LEGACY = "xyz"  # X, Y, Z: obras numeradas entre 2026-11-18 e 2026-11-19
ORDERS = (CURRENT, LEGACY)
_INDEX = {"x": 0, "y": 1, "z": 2}


def axis_names(order: str = CURRENT) -> str:
    """'zxy' -> 'Z → X → Y'."""
    return " → ".join(c.upper() for c in order)


AXIS_NAMES = axis_names()


def sequence[T](
    items: Sequence[tuple[T, Point]], tol: float = TOLERANCE_M, order: str = CURRENT
) -> list[T]:
    """Itens [(chave, (x, y, z) em metros)] na sequência de montagem `order`."""
    if order not in ORDERS:
        raise ValueError(f"ordem desconhecida: {order}")
    axes = tuple(_INDEX[c] for c in order)

    def go(group: list[tuple[T, Point]], depth: int) -> list[tuple[T, Point]]:
        if depth == len(axes) or len(group) <= 1:
            return group
        axis = axes[depth]
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
