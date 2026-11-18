"""Tipo da peça para o filtro da lista: pilar, quadro estrutural, laje, escada ou outros.

Decisão de 2026-11-18 (usuário):
- **Laje**: qualquer peça com "Laje" no nome/tipo ou com a sigla LA, LAA, LP ou LM (no
  nome, no tipo ou na marca). No Revit as lajes alveolares são "Quadro estrutural"
  (`CASSOL-PREO-Laje-Alveolar_LP20`); a laje maciça LM é "Conexões estruturais".
- **Escada**: "Escada" no nome/tipo (na Cassol são "Conexões estruturais").
- **Pilar**: categoria de pilar. **Quadro estrutural**: o resto da categoria (vigas).
- Peças metálicas (`GERDAU-MET-Viga-W`) não são do escopo da fábrica: **outros**.

Onde procurar o nome do tipo: no RVT "Dados de identidade > Nome do tipo"; no NWD "Item"
e "Element" (Type, Family); no IFC "IFC Attributes > ObjectType" e "<parte> · IFC Type
Attributes > Name" (na montagem, só o corpo diz `Laje-Alveolar_LP15`). Nunca o grupo do
nível: um nível "LAJE COBERTURA" não faz do pilar uma laje.

Siglas valem só soltas e em maiúsculas: `_LP20` e `LA001` sim; "HELP" ou "Lateral" não.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Element, Mark, ModelVersion

PILAR, QUADRO, LAJE, ESCADA, OUTROS = "pilar", "quadro", "laje", "escada", "outros"
TYPES = (PILAR, QUADRO, LAJE, ESCADA, OUTROS)

_SLAB_CODE = re.compile(r"(?<![A-Z])(LAA|LA|LP|LM)(?![A-Z])")
_SLAB_WORD = re.compile(r"laje", re.IGNORECASE)
_STAIR = re.compile(r"escada", re.IGNORECASE)
_METAL = re.compile(r"(?<![A-Z])(MET|GERDAU)(?![A-Z])")

# grupos de propriedades que descrevem a própria peça (o resto é referência: nível, fase…)
_GROUPS = {"Item", "Element", "Dados de identidade", "Identity Data", "IFC Attributes", "Other"}
_GROUP_SUFFIXES = ("IFC Type Attributes", "IFC Attributes")
_KEYS = {
    "name",
    "type",
    "family",
    "objecttype",
    "tipo",
    "família",
    "nome do tipo",
    "type name",
    "family name",
}


def type_texts(name: str | None, props: dict[str, Any] | None) -> list[str]:
    """Nome da peça e os nomes de tipo/família dela nas propriedades."""
    out = [name] if name else []
    for group, values in (props or {}).items():
        if group in ("Name", "Component Name") and isinstance(values, str):
            out.append(values)
            continue
        if not isinstance(values, dict):
            continue
        if group not in _GROUPS and not group.endswith(_GROUP_SUFFIXES):
            continue
        for key, value in values.items():
            if key.casefold() in _KEYS and isinstance(value, str):
                out.append(value)
    return out


def classify(
    category: str | None, name: str | None, mark_code: str | None, props: dict[str, Any] | None
) -> str:
    texts = type_texts(name, props)
    cat = (category or "").casefold()
    if any(_METAL.search(t) for t in texts):
        return OUTROS
    if "pilar" in cat or "column" in cat:
        return PILAR
    if any(_STAIR.search(t) for t in texts):
        return ESCADA
    if any(_SLAB_WORD.search(t) or _SLAB_CODE.search(t) for t in [*texts, mark_code or ""]):
        return LAJE
    if "quadro" in cat or "framing" in cat:
        return QUADRO
    return OUTROS


async def rebuild_version(session: AsyncSession, version: ModelVersion) -> int:
    """Recalcula elements.piece_type das peças com marca da versão (sem APS). Sem commit."""
    rows = await session.execute(
        select(Element.id, Element.category, Element.name, Element.props, Mark.code)
        .join(Mark, Mark.id == Element.mark_id)
        .where(Element.version_id == version.id)
    )
    changed = 0
    for element_id, category, name, props, code in rows:
        await session.execute(
            update(Element)
            .where(Element.id == element_id)
            .values(piece_type=classify(category, name, code, props))
        )
        changed += 1
    return changed
