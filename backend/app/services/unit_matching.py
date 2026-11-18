"""Ligação das unidades de peça aos elementos de uma versão, DENTRO de uma marca.

Função pura (sem banco): usada pelo processamento da versão e pela migração 0015.
Regra (docs/pecas/verificacao.md, decisão de 2026-11-16):

1. **Pela chave:** unidade cujo externalId existe na versão continua no mesmo elemento
   (UniqueId no Revit, GlobalId no IFC; o dbId do Viewer nunca serve).
2. **Pela ordem:** unidades e elementos que sobraram são ligados numa ordem ESTÁVEL e
   sem relação com o Viewer: unidades pelo número; elementos por nível, nome e externalId
   ou, nas obras numeradas pela montagem (`by_sequence`), pela sequência de montagem do
   centro de gravidade (X → Y → Z; os sem centro depois). Se há menos elementos que
   unidades, ficam com peça primeiro as unidades com valores (para não deixar sem peça um
   dado que existe); os valores não mudam o par quando há peça para todas (2026-11-18:
   antes eles iam na frente e, no NWD, um reprocessamento passava o valor da PP001-5 para
   a primeira peça da ordem). Marcada "conferir" (método `order`); a unidade passa a ter a
   chave do novo elemento.
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

from app.services.assembly_order import Point, sequence

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
    centroid: Point | None = None  # centro de gravidade (m), quando o 3D já o mandou


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


def ordered_elements(elements: list[ElementIn], by_sequence: bool = False) -> list[ElementIn]:
    """Elementos na ordem da ligação pela ordem e da numeração das unidades novas."""
    stable = sorted(elements, key=element_order)
    if not by_sequence:
        return stable
    with_xyz = [(e, e.centroid) for e in stable if e.centroid is not None]
    return sequence(with_xyz) + [e for e in stable if e.centroid is None]


def match(
    units: list[UnitIn],
    elements: list[ElementIn],
    *,
    use_key: bool = True,
    create: bool = True,
    next_number: int | None = None,
    by_sequence: bool = False,
) -> MatchResult:
    """Liga as unidades de UMA marca aos elementos dela numa versão.

    `next_number`: primeiro número livre da marca (padrão: maior número + 1).
    `create=False` (versão antiga): não cria unidades novas.
    `by_sequence`: obra numerada pela sequência de montagem (ver `ordered_elements`)."""
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

    free_elems = ordered_elements(free_elems, by_sequence)
    pairs = min(len(free_units), len(free_elems))
    # quem fica com peça: com valores primeiro; o par, pelo número
    chosen = sorted(free_units, key=lambda u: (not u.has_values, u.number))[:pairs]
    chosen_ids = {u.id for u in chosen}
    chosen.sort(key=lambda u: u.number)
    for u, e in zip(chosen, free_elems[:pairs], strict=True):
        result.links.append(Link(u.id, e.id, ORDER, external_id=e.external_id))
    result.leftover = sorted(
        (u for u in free_units if u.id not in chosen_ids), key=lambda u: u.number
    )

    if create:
        number = next_number or (max((u.number for u in units), default=0) + 1)
        for e in free_elems[pairs:]:
            result.links.append(Link(None, e.id, NEW, new_number=number, external_id=e.external_id))
            number += 1
    return result
