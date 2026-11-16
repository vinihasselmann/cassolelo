"""Trilha de auditoria. TODO serviço de escrita chama `record` na mesma transação.

Uso:
    before = snapshot(obj)
    ... altera obj ...
    await session.flush()
    await audit.record(session, "mark", obj.id, "update", before, snapshot(obj), user)
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from sqlalchemy import insert
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, Base, User

JsonDict = dict[str, Any]


def _json_safe(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, uuid.UUID | Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(v) for v in value]
    return value


def snapshot(obj: Base, exclude: tuple[str, ...] = ()) -> JsonDict:
    """Colunas já carregadas do objeto, prontas para JSON.

    Não dispara lazy-load (seguro em sessão async): colunas expiradas, como
    updated_at depois de um flush, ficam de fora.
    """
    state = sa_inspect(obj)
    loaded = state.dict
    return {
        attr.key: _json_safe(loaded[attr.key])
        for attr in state.mapper.column_attrs
        if attr.key in loaded and attr.key not in exclude
    }


async def record(
    session: AsyncSession,
    entity: str,
    entity_id: int | str,
    action: str,
    before: JsonDict | None,
    after: JsonDict | None,
    user: User | None,
    batch_id: uuid.UUID | None = None,
) -> AuditLog:
    """Registra uma alteração. `user=None` significa ação do sistema."""
    entry = AuditLog(
        entity=entity,
        entity_id=str(entity_id),
        action=action,
        before=_json_safe(before) if before is not None else None,
        after=_json_safe(after) if after is not None else None,
        user_id=user.id if user is not None else None,
        batch_id=batch_id,
    )
    session.add(entry)
    await session.flush()
    return entry


async def record_many(
    session: AsyncSession,
    entity: str,
    action: str,
    changes: list[tuple[int | str, JsonDict | None, JsonDict | None]],
    user: User | None,
    batch_id: uuid.UUID | None = None,
    chunk_size: int = 1000,
) -> None:
    """Igual a `record`, para muitas linhas de uma vez: (entity_id, before, after)."""
    rows = [
        {
            "entity": entity,
            "entity_id": str(entity_id),
            "action": action,
            "before": _json_safe(before) if before is not None else None,
            "after": _json_safe(after) if after is not None else None,
            "user_id": user.id if user is not None else None,
            "batch_id": batch_id,
        }
        for entity_id, before, after in changes
    ]
    for i in range(0, len(rows), chunk_size):
        await session.execute(insert(AuditLog), rows[i : i + chunk_size])
