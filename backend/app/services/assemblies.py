"""Peças em modelos com MONTAGENS (.nwd / .rvt com vínculos), docs/montagens.md.

No Navisworks (e no .rvt central) não existe um nó "montagem": cada instância do Revit
traz o parâmetro da regra (ex.: `Element > Nome da montagem = PP312`) e os membros de
uma montagem ficam espalhados por categoria. O modelo da Cassol é um .rvt central com
um VÍNCULO por peça (`9480-E1312.rvt : 148 : localização Interno`).

Regra (ativada quando a obra informa as categorias de "corpo" da peça):
- agrupa as instâncias por (vínculo, marca). Sem vínculo, o modelo inteiro é um grupo
  só por marca;
- **corpo** = instância de uma das `piece_categories` (padrão: Pilares estruturais e
  Quadro estrutural, ou seja, pilares, vigas e lajes alveolares). Cada corpo é uma peça
  física. Os outros membros (consolos, alças, esperas, neoprene...) pertencem à peça;
- grupo sem corpo (escadas, lajes maciças: "Conexões estruturais") = 1 peça;
- vínculo com uma montagem só: a peça é o NÓ DO VÍNCULO (no 3D destaca a peça inteira,
  com consolos); as propriedades (dimensões, tipo, nível) vêm do corpo;
- instância de categoria de corpo SEM marca = peça sem marca (aparece no relatório);
- o resto (níveis do modelo central, ambientes, vínculos sem montagem) não é peça.

Função pura: recebe a árvore e as propriedades do derivativo.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.aps.schemas import PropertyObject, TreeNode
from app.services.extraction import (
    NO_CATEGORY,
    ExtractedElement,
    clean_category,
    find_prop,
    ifc_class,
    normalize_mark,
    subtree_dbids,
)

# "9480-E1312.rvt : 148 : localização Interno" (instância de vínculo no Navisworks)
LINK_RE = re.compile(r"\.(rvt|nwc|nwd|ifc|dwg)\s*:", re.IGNORECASE)


@dataclass
class _Instance:
    node: TreeNode
    props: dict[str, Any]
    category: str
    external_id: str | None
    name: str | None


@dataclass
class _Group:
    container: TreeNode | None  # nó do vínculo (None = modelo sem vínculos)
    mark_raw: str
    instances: list[_Instance] = field(default_factory=list)  # as de cima (não aninhadas)
    all_dbids: set[int] = field(default_factory=set)


def is_ifc(properties: list[PropertyObject]) -> bool:
    return any(ifc_class(p.properties) for p in properties[:200])


def _category(props: dict[str, Any], category_names: list[str]) -> str | None:
    """Categoria da instância: `Element > Category` do Navisworks, senão a regra."""
    element = props.get("Element")
    if isinstance(element, dict) and element.get("Category"):
        return str(element["Category"])
    return find_prop(props, category_names)


def _element_id(props: dict[str, Any]) -> str | None:
    element = props.get("Element")
    if isinstance(element, dict) and element.get("Id") is not None:
        return str(element["Id"])
    return None


def extract_assemblies(
    tree: list[TreeNode],
    properties: list[PropertyObject],
    mark_names: list[str],
    category_names: list[str],
    piece_categories: list[str],
) -> list[ExtractedElement]:
    by_id = {p.objectid: p for p in properties}
    bodies = {c.casefold() for c in piece_categories}
    groups: dict[tuple[int, str], _Group] = {}
    unmarked: list[_Instance] = []
    groups_in_container: dict[int, set[str]] = {}

    # pilha: (nó, vínculo, marca da instância de cima, Element.Id de cima)
    stack: list[tuple[TreeNode, TreeNode | None, str | None, str | None]] = [
        (n, None, None, None) for n in reversed(tree)
    ]
    while stack:
        node, link, mark_above, id_above = stack.pop()
        info = by_id.get(node.objectid)
        props = info.properties if info else {}
        if link is None and node.name and LINK_RE.search(node.name):
            # o nó do vínculo não é instância (a "Marca" dele é a do vínculo, ex.: "28")
            link = node
            stack.extend((c, link, None, None) for c in reversed(node.objects))
            continue
        raw = find_prop(props, mark_names)
        code = normalize_mark(raw)
        element_id = _element_id(props)
        new_instance = element_id is not None and element_id != id_above
        category = _category(props, category_names) if new_instance or code else None

        if code and raw:
            key = (link.objectid if link else 0, code)
            group = groups.get(key)
            if group is None:
                group = groups[key] = _Group(container=link, mark_raw=raw.strip())
                groups_in_container.setdefault(key[0], set()).add(code)
            group.all_dbids.add(node.objectid)
            if code != mark_above:  # instância de cima (não aninhada na mesma marca)
                group.instances.append(
                    _Instance(
                        node,
                        props,
                        clean_category(category or NO_CATEGORY),
                        info.external_id if info else None,
                        (info.name if info else None) or node.name,
                    )
                )
        elif new_instance and category and category.casefold() in bodies and not mark_above:
            unmarked.append(
                _Instance(
                    node,
                    props,
                    clean_category(category),
                    info.external_id if info else None,
                    (info.name if info else None) or node.name,
                )
            )
            continue  # a geometria abaixo é dela

        next_mark = code or mark_above
        next_id = element_id or id_above
        stack.extend((c, link, next_mark, next_id) for c in reversed(node.objects))

    out: list[ExtractedElement] = []
    for (container_id, code), group in groups.items():
        piece_bodies = [i for i in group.instances if i.category.casefold() in bodies]
        alone = container_id != 0 and len(groups_in_container[container_id]) == 1
        if piece_bodies:
            if len(piece_bodies) == 1 and alone and group.container is not None:
                out.append(_piece(group.container, piece_bodies[0], group, code))
            else:
                members = len(piece_bodies) == 1
                out.extend(_piece(b.node, b, group, code, members) for b in piece_bodies)
        else:
            # montagem sem corpo de pilar/viga/laje (escada, laje maciça): 1 peça, com a
            # categoria mais comum entre os membros e as propriedades do maior deles
            counts: dict[str, int] = {}
            for inst in group.instances:
                counts[inst.category] = counts.get(inst.category, 0) + 1
            common = max(counts, key=lambda c: (counts[c], c))
            main = max(
                (i for i in group.instances if i.category == common), key=lambda i: _size(i.props)
            )
            node = group.container if alone and group.container is not None else main.node
            out.append(_piece(node, main, group, code))
    out.extend(
        ExtractedElement(
            dbid=i.node.objectid,
            external_id=i.external_id,
            name=i.name,
            category=i.category,
            mark_raw=None,
            mark_code=None,
            props=i.props,
            member_dbids=subtree_dbids(i.node),
        )
        for i in unmarked
    )
    out.sort(key=lambda e: e.dbid)
    return out


def _size(props: dict[str, Any]) -> int:
    return sum(len(g) for g in props.values() if isinstance(g, dict))


def _piece(
    node: TreeNode, body: _Instance, group: _Group, code: str, with_members: bool = True
) -> ExtractedElement:
    members = set(subtree_dbids(node))
    if with_members:  # membros da montagem espalhados fora do nó (mesmo vínculo)
        members |= group.all_dbids
        for inst in group.instances:
            members |= set(subtree_dbids(inst.node))
    members.discard(node.objectid)
    return ExtractedElement(
        dbid=node.objectid,
        external_id=body.external_id,
        name=body.name,
        category=body.category,
        mark_raw=group.mark_raw,
        mark_code=code,
        props=body.props,
        member_dbids=tuple(sorted(members)),
    )
