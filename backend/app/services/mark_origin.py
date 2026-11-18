"""Origem da marca de cada peça (de qual parâmetro da regra veio) e parâmetros secundários.

Versões novas já saem preenchidas pelo processamento; versões antigas são preenchidas
por `python -m app.cli marks origin` a partir do `props` guardado (sem chamar o APS).
"""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import Element, Mark, ModelVersion, Obra
from app.services.mark_rule import effective_rule
from app.services.mark_validation import mark_origin


async def rebuild_version(session: AsyncSession, version: ModelVersion, settings: Settings) -> int:
    """Recalcula mark_source/mark_alt das peças com marca da versão. Sem commit."""
    obra = await session.get(Obra, version.obra_id)
    if obra is None:  # pragma: no cover
        return 0
    names = effective_rule(obra, settings).mark_names
    rows = await session.execute(
        select(Element.id, Element.props, Mark.code)
        .join(Mark, Mark.id == Element.mark_id)
        .where(Element.version_id == version.id)
    )
    changed = 0
    for element_id, props, code in rows:
        source, alt = mark_origin(props, names, code)
        await session.execute(
            update(Element)
            .where(Element.id == element_id)
            .values(mark_source=source[:255] if source else None, mark_alt=alt)
        )
        changed += 1
    return changed
