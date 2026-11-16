"""Extração de elementos a partir da árvore e das propriedades do derivativo (funções puras).

Regra (spike 0.2, ajustada com o modelo real): elemento = nó da árvore 3D que tem Marca
(os filhos dele são componentes aninhados e não contam) ou folha sem Marca acima dela.
Exceção: um nó cujos filhos TODOS repetem a mesma marca é agrupamento (tipo/família do
Revit, com parâmetro de tipo como "Marca de tipo") e a extração desce até as instâncias.

IFC (confirmado com IFC exportado do Revit e convertido pelo Docs): a peça é o nó com
`IFC Attributes > IfcClass` de produto físico (IfcBeam, IfcColumn, IfcSlab...); os filhos
são geometria (IfcMappedItem, materiais, aberturas). Projeto/site/edifício/pavimento são
espaciais (desce); eixos, aberturas, espaços, anotações e grupos não são peças.

Montagens no IFC (obra 9480, docs/montagens.md): a instância de montagem é um
`IfcBuildingElementProxy` com `ObjectType = "Montagem <Categoria de nomenclatura>:<Nome>"`;
os membros (pilar, consolos, alças...) são filhos dele. O nome e a categoria viram a
propriedade sintética `Montagem > Nome da montagem` / `Category` (a mesma que o .nwd e o
.rvt trazem), para a regra de identificação da obra valer igual nos três formatos.

Toda peça leva `member_dbids`: os dbIds abaixo dela (membros e geometria), para um
clique no 3D em qualquer parte achar a peça.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.aps.schemas import PropertyObject, TreeNode

NO_CATEGORY = "(sem categoria)"

# Classes IFC que agrupam (a extração desce) e que nunca são peças (ignoradas com a subárvore).
IFC_SPATIAL = frozenset({"ifcproject", "ifcsite", "ifcbuilding", "ifcbuildingstorey"})
IFC_NOT_PIECES = frozenset(
    {
        "ifcgrid",
        "ifcgridaxis",
        "ifcopeningelement",
        "ifcspace",
        "ifcspatialzone",
        "ifcannotation",
        "ifcvirtualelement",
        "ifczone",
        "ifcgroup",  # "Grupo de modelos" do Revit: sem geometria própria
    }
)
ASSEMBLY_GROUP = "Montagem"
ASSEMBLY_NAME = "Nome da montagem"
_ASSEMBLY_PREFIX = "Montagem "


def ifc_class(props: dict[str, Any]) -> str | None:
    """Classe IFC da própria entidade (não a do tipo: "IFC Type Attributes" fica de fora)."""
    attrs = props.get("IFC Attributes")
    if isinstance(attrs, dict) and attrs.get("IfcClass"):
        return str(attrs["IfcClass"])
    for group, content in props.items():
        if "type" in group.casefold() or not isinstance(content, dict):
            continue
        for key, value in content.items():
            if key.casefold() == "ifcclass" and value:
                return str(value)
    return None


@dataclass(frozen=True, slots=True)
class ExtractedElement:
    dbid: int
    external_id: str | None
    name: str | None
    category: str
    mark_raw: str | None  # valor como está no modelo
    mark_code: str | None  # normalizado (trim + maiúsculas); None = sem marca
    props: dict[str, Any]
    member_dbids: tuple[int, ...] = ()  # dbIds abaixo da peça (membros, geometria)


def ifc_assembly(props: dict[str, Any]) -> tuple[str, str] | None:
    """(categoria de nomenclatura, nome da montagem) de um nó de montagem do IFC."""
    attrs = props.get("IFC Attributes")
    if not isinstance(attrs, dict):
        return None
    if str(attrs.get("IfcClass") or "").casefold() != "ifcbuildingelementproxy":
        return None
    object_type = str(attrs.get("ObjectType") or "")
    if not object_type.startswith(_ASSEMBLY_PREFIX):
        return None
    category, sep, name = object_type[len(_ASSEMBLY_PREFIX) :].rpartition(":")
    if not sep or not name.strip():
        return None
    return category.strip(), name.strip()


BODY_PREFIX = "Corpo · "
_VOLUME = re.compile(r"^\s*(\d+(?:[.,]\d+)?)")


def _volume(props: dict[str, Any]) -> float:
    quantities = props.get("BaseQuantities")
    if not isinstance(quantities, dict):
        return 0.0
    for key in ("NetVolume", "GrossVolume"):
        match = _VOLUME.match(str(quantities.get(key) or ""))
        if match:
            return float(match.group(1).replace(",", "."))
    return 0.0


def assembly_body(children: list[dict[str, Any]]) -> dict[str, Any] | None:
    """O corpo da montagem (pilar, viga, laje, escada) = o membro de maior volume."""
    best, best_volume = None, 0.0
    for props in children:
        volume = _volume(props)
        if volume > best_volume:
            best, best_volume = props, volume
    return best


def with_assembly(
    props: dict[str, Any], category: str, name: str, body: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Propriedades + grupo sintético "Montagem" (primeiro) + as do CORPO ("Corpo · ...",
    antes das do nó: o tipo, a seção e o volume da peça vêm dele; o nó da montagem só
    tem o nome)."""
    group = {ASSEMBLY_NAME: name, "Categoria de nomenclatura": category}
    if category:
        group["Category"] = category
    body_groups = {
        f"{BODY_PREFIX}{g}": content
        for g, content in (body or {}).items()
        if isinstance(content, dict)
    }
    return {ASSEMBLY_GROUP: group, **body_groups, **props}


def subtree_dbids(node: TreeNode) -> tuple[int, ...]:
    """dbIds abaixo de `node` (sem ele)."""
    out: list[int] = []
    stack = list(node.objects)
    while stack:
        n = stack.pop()
        out.append(n.objectid)
        stack.extend(n.objects)
    return tuple(sorted(out))


def find_named_prop(props: dict[str, Any], names: list[str]) -> tuple[str, str] | None:
    """Como find_prop, mas devolve também qual dos nomes foi encontrado."""
    for wanted in names:
        value = find_prop(props, [wanted])
        if value is not None:
            return wanted, value
    return None


def find_prop(props: dict[str, Any], names: list[str]) -> str | None:
    """Primeira propriedade com um dos nomes (sem diferenciar maiúsculas), em todos os
    grupos, na ordem de preferência de `names`. Valores vazios são ignorados."""
    for wanted in names:
        key = wanted.casefold()
        for group in props.values():
            if not isinstance(group, dict):
                continue
            for prop_name, value in group.items():
                if prop_name.casefold() != key:
                    continue
                if isinstance(value, list):
                    value = value[0] if value else None
                if value is not None and str(value).strip():
                    return str(value)
    return None


def normalize_mark(raw: str | None) -> str | None:
    if raw is None:
        return None
    code = raw.strip().upper()
    return code or None


def clean_category(value: str) -> str:
    return value.strip().removeprefix("Revit ").strip() or NO_CATEGORY


def extract_elements(
    tree: list[TreeNode],
    properties: list[PropertyObject],
    mark_names: list[str],
    category_names: list[str],
) -> list[ExtractedElement]:
    by_id = {p.objectid: p for p in properties}

    def props_of(node: TreeNode) -> dict[str, Any]:
        info = by_id.get(node.objectid)
        return info.properties if info else {}

    def is_grouping(node: TreeNode) -> bool:
        """Nó de tipo/família: a propriedade que deu a marca ao nó (ex.: "Marca de tipo")
        se repete, com o mesmo valor, em TODOS os filhos (parâmetro de tipo herdado pelas
        instâncias). Uma peça com componentes aninhados não é agrupamento: os filhos não
        têm essa propriedade ou têm outro valor."""
        source = find_named_prop(props_of(node), mark_names)
        if source is None or not node.objects:
            return False
        name, value = source
        return all(
            normalize_mark(find_prop(props_of(c), [name])) == normalize_mark(value)
            for c in node.objects
        )

    out: list[ExtractedElement] = []
    # pilha: (nó, profundidade, categoria vinda da árvore)
    stack: list[tuple[TreeNode, int, str | None]] = [(n, 0, None) for n in reversed(tree)]
    while stack:
        node, depth, tree_cat = stack.pop()
        if depth == 1:
            tree_cat = node.name or None
        info = by_id.get(node.objectid)
        props = info.properties if info else {}
        if assembly := ifc_assembly(props):
            body = assembly_body([props_of(c) for c in node.objects])
            props = with_assembly(props, *assembly, body)
        mark_raw = find_prop(props, mark_names)
        mark_code = normalize_mark(mark_raw)
        klass = ifc_class(props)
        if klass and klass.casefold() in IFC_NOT_PIECES:
            continue  # eixo, abertura, espaço...: nem a subárvore conta
        if klass and klass.casefold() in IFC_SPATIAL:
            is_piece = False
        elif klass:
            is_piece = True  # produto IFC: os filhos são a geometria dele
        else:
            is_piece = bool(mark_code and not is_grouping(node)) or not node.objects
        if depth > 0 and is_piece:
            category = find_prop(props, category_names) or klass or tree_cat or NO_CATEGORY
            out.append(
                ExtractedElement(
                    dbid=node.objectid,
                    external_id=info.external_id if info else None,
                    name=(info.name if info else None) or node.name,
                    category=clean_category(category),
                    mark_raw=mark_raw.strip() if mark_raw else None,
                    mark_code=mark_code,
                    props=props,
                    member_dbids=subtree_dbids(node),
                )
            )
            continue
        stack.extend((c, depth + 1, tree_cat) for c in reversed(node.objects))
    return out
