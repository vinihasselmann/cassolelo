"""Ligação das unidades de peça aos elementos de uma versão, DENTRO de uma marca.

Função pura (sem banco): usada pelo processamento da versão e pela migração 0015.
Regra (docs/pecas/verificacao.md, decisão de 2026-11-16):

1. **Pela chave:** unidade cujo externalId existe na versão continua no mesmo elemento
   (UniqueId no Revit, GlobalId no IFC; o dbId do Viewer nunca serve).
2. **Pela ordem:** unidades e elementos que sobraram são ligados numa ordem ESTÁVEL e
   sem relação com o Viewer: unidades com valores primeiro (para não deixar sem peça um
   dado que existe), depois pelo número; elementos por nível, nome e externalId. Marcada
   "conferir" (método `order`); a unidade passa a ter a chave do novo elemento.
3. **Sobrou elemento:** vira unidade NOVA, vazia, com o próximo número (os números nunca
   são reaproveitados: o próximo vem do maior número que a marca já teve).
4. **Sobrou unidade:** com valores, ÓRFÃ; sem valores, só fica registrada (`unlinked`).
5. **Arquivada (P5):** só participa do passo 1. Volta se a chave dela reaparecer; nunca é
   ligada pela ordem a outra peça (a fábrica decidiu que ela não vale mais).

Em NWD não há chave estável (o id é um caminho na árvore): só o passo 2.
Numa versão ANTERIOR à mais recente (consulta), só se liga: nada é criado nem muda de
situação.
"""

from __future__ import annotations

from dataclasses import dataclass, field

KEY = "key"
ORDER = "order"
NEW = "new"


@dataclass(frozen=True)
class UnitIn:
    id: int
    number: int
    external_id: str | None
    has_values: bool
    key_only: bool = False  # arquivada: só volta pela chave (nunca pela ordem)


@dataclass(frozen=True)
class ElementIn:
    id: int
    external_id: str | None
    level: str | None
    name: str | None


@dataclass(frozen=True)
class Link:
    unit_id: int | None  # None = unidade nova (ver new_number)
    element_id: int
    method: str
    new_number: int | None = None
    external_id: str | None = None  # chave do elemento (vira a chave da unidade)


@dataclass
class MatchResult:
    links: list[Link] = field(default_factory=list)
    # unidades sem elemento nesta versão (as arquivadas que não voltaram ficam de fora)
    leftover: list[UnitIn] = field(default_factory=list)


def element_order(e: ElementIn) -> tuple[bool, str, str, str]:
    """Ordem estável dos elementos (nível, nome, externalId); sem nível vai por último."""
    return (e.level is None, e.level or "", e.name or "", e.external_id or "")


def match(
    units: list[UnitIn],
    elements: list[ElementIn],
    *,
    use_key: bool = True,
    create: bool = True,
    next_number: int | None = None,
) -> MatchResult:
    """Liga as unidades de UMA marca aos elementos dela numa versão.

    `next_number`: primeiro número livre da marca (padrão: maior número + 1).
    `create=False` (versão antiga): não cria unidades novas."""
    result = MatchResult()
    free_units = list(units)
    free_elems = list(elements)

    if use_key:
        by_key: dict[str, UnitIn] = {}
        for unit in units:
            if unit.external_id:
                by_key.setdefault(unit.external_id, unit)
        taken: set[int] = set()
        rest: list[ElementIn] = []
        for e in elements:
            hit = by_key.get(e.external_id) if e.external_id else None
            if hit is not None and hit.id not in taken:
                taken.add(hit.id)
                result.links.append(Link(hit.id, e.id, KEY, external_id=e.external_id))
            else:
                rest.append(e)
        free_units = [u for u in units if u.id not in taken]
        free_elems = rest

    free_units = [u for u in free_units if not u.key_only]

    free_units.sort(key=lambda u: (not u.has_values, u.number))
    free_elems.sort(key=element_order)
    pairs = min(len(free_units), len(free_elems))
    for u, e in zip(free_units[:pairs], free_elems[:pairs], strict=True):
        result.links.append(Link(u.id, e.id, ORDER, external_id=e.external_id))
    result.leftover = sorted(free_units[pairs:], key=lambda u: u.number)

    if create:
        number = next_number or (max((u.number for u in units), default=0) + 1)
        for e in free_elems[pairs:]:
            result.links.append(Link(None, e.id, NEW, new_number=number, external_id=e.external_id))
            number += 1
    return result
