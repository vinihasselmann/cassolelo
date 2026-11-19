"""Quais obras cada usuário vê (11.2).

- Admin vê todas, sempre.
- `users.all_obras = true` (padrão): todas, inclusive as criadas depois.
- `all_obras = false`: só as de `user_obras`. Obra nova não entra sozinha na lista, salvo
  a que o próprio usuário cria (`grant_creator`).

Obra que o usuário não vê responde 404 (não revela que existe).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, UserObra
from app.models.enums import Role
from app.services import audit
from app.services.errors import NotFoundError, ValidationError

OBRA_NOT_FOUND = "Obra não encontrada."


def sees_all(user: User) -> bool:
    return user.role == Role.ADMIN.value or user.all_obras


async def granted_obra_ids(session: AsyncSession, user_id: int) -> set[int]:
    rows = await session.scalars(select(UserObra.obra_id).where(UserObra.user_id == user_id))
    return set(rows)


async def visible_obra_ids(session: AsyncSession, user: User) -> set[int] | None:
    """None = todas as obras."""
    if sees_all(user):
        return None
    return await granted_obra_ids(session, user.id)


async def can_see(session: AsyncSession, user: User, obra_id: int) -> bool:
    if sees_all(user):
        return True
    found = await session.scalar(
        select(UserObra.obra_id).where(UserObra.user_id == user.id, UserObra.obra_id == obra_id)
    )
    return found is not None


async def ensure_visible(session: AsyncSession, user: User, obra_id: int) -> None:
    """404 se o usuário não vê a obra (rotas com a obra no caminho)."""
    if not await can_see(session, user, obra_id):
        raise NotFoundError(OBRA_NOT_FOUND)


async def ensure_body_obra(session: AsyncSession, user: User, obra_id: int | None) -> None:
    """422 se o corpo da requisição aponta para uma obra que o usuário não vê (o mesmo
    erro de obra inexistente)."""
    if obra_id is not None and not await can_see(session, user, obra_id):
        raise ValidationError(OBRA_NOT_FOUND)


async def grant_creator(session: AsyncSession, user: User, obra_id: int) -> None:
    """Quem cria uma obra passa a vê-la, mesmo restrito."""
    if sees_all(user):
        return
    row = UserObra(user_id=user.id, obra_id=obra_id, created_by=user.id, updated_by=user.id)
    session.add(row)
    await session.flush()
    await audit.record(session, "user", user.id, "grant_obra", None, {"obra_id": obra_id}, user)
