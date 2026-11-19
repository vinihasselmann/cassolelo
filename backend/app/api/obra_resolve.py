"""De qual obra é a requisição: pelos parâmetros da rota (e, nas listas, pela query).

Usado pelo bloqueio de arquivo excluído (`obra_guard`) e pelo acesso por obra
(`obra_access`). None = a rota não é de uma obra (ou o id não existe: a rota responde o
próprio 404/422).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AuditLog,
    ColorScheme,
    Mark,
    ModelVersion,
    Orphan,
    ParamDef,
    PieceUnit,
    SavedFilter,
)

# Lotes de valores: entity_id da auditoria é a marca (mark_value) ou a unidade (piece_value).
_BATCH_ENTITIES = ("mark_value", "piece_value")


def _int(params: Mapping[str, Any], name: str) -> int | None:
    raw = params.get(name)
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None  # a validação da própria rota responde 422


async def _batch_obra(session: AsyncSession, raw: Any) -> int | None:
    try:
        batch_id = uuid.UUID(str(raw))
    except ValueError:
        return None
    entry = (
        await session.execute(
            select(AuditLog.entity, AuditLog.entity_id)
            .where(AuditLog.batch_id == batch_id, AuditLog.entity.in_(_BATCH_ENTITIES))
            .order_by(AuditLog.id)
            .limit(1)
        )
    ).first()
    if entry is None or not entry.entity_id.isdigit():
        return None
    cls = Mark if entry.entity == "mark_value" else PieceUnit
    return await session.scalar(select(cls.obra_id).where(cls.id == int(entry.entity_id)))


async def obra_id_from_path(session: AsyncSession, params: Mapping[str, Any]) -> int | None:
    if (obra_id := _int(params, "obra_id")) is not None:
        return obra_id
    if (version_id := _int(params, "version_id")) is not None:
        return await session.scalar(
            select(ModelVersion.obra_id).where(ModelVersion.id == version_id)
        )
    if (mark_id := _int(params, "mark_id")) is not None:
        return await session.scalar(select(Mark.obra_id).where(Mark.id == mark_id))
    if (orphan_id := _int(params, "orphan_id")) is not None:
        return await session.scalar(
            select(Mark.obra_id)
            .join(Orphan, Orphan.mark_id == Mark.id)
            .where(Orphan.id == orphan_id)
        )
    if (filter_id := _int(params, "filter_id")) is not None:
        return await session.scalar(select(SavedFilter.obra_id).where(SavedFilter.id == filter_id))
    if (scheme_id := _int(params, "scheme_id")) is not None:
        return await session.scalar(select(ColorScheme.obra_id).where(ColorScheme.id == scheme_id))
    if (def_id := _int(params, "def_id")) is not None:
        return await session.scalar(select(ParamDef.obra_id).where(ParamDef.id == def_id))
    if "batch_id" in params:
        return await _batch_obra(session, params["batch_id"])
    return None


def obra_ids_from_query(query: Mapping[str, Any]) -> list[int]:
    """Obras citadas na query das listas (?obra_id=, ?include_in_obra_id=)."""
    return [i for name in ("obra_id", "include_in_obra_id") if (i := _int(query, name)) is not None]
