from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.models.enums import Role
from app.services import audit


async def upsert_user(
    session: AsyncSession,
    *,
    name: str,
    email: str,
    role: Role,
    actor: User | None,
    batch_id: uuid.UUID | None = None,
) -> User:
    """Cria ou atualiza um usuário pelo e-mail, com auditoria."""
    actor_id = actor.id if actor else None
    user = await session.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(
            name=name,
            email=email,
            role=role.value,
            active=True,
            created_by=actor_id,
            updated_by=actor_id,
        )
        session.add(user)
        await session.flush()
        await audit.record(
            session, "user", user.id, "create", None, audit.snapshot(user), actor, batch_id
        )
        return user

    if user.name == name and user.role == role.value and user.active:
        return user
    before = audit.snapshot(user)
    user.name, user.role, user.active, user.updated_by = name, role.value, True, actor_id
    await session.flush()
    await audit.record(
        session, "user", user.id, "update", before, audit.snapshot(user), actor, batch_id
    )
    return user
