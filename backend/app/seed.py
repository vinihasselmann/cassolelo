"""Seed de desenvolvimento: um usuário por papel. Idempotente.

uv run python -m app.seed
"""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import create_engine, create_sessionmaker
from app.models import User
from app.models.enums import Role
from app.services.users import upsert_user

SEED_USERS: tuple[tuple[str, str, Role], ...] = (
    ("Paula Projetos", "projetos@dev.local", Role.PROJETOS),
    ("Fábio Fábrica", "fabrica@dev.local", Role.FABRICA),
    ("Ana Admin", "admin@dev.local", Role.ADMIN),
    ("Lia Leitura", "leitura@dev.local", Role.LEITURA),
)


async def seed_users(session: AsyncSession) -> dict[Role, User]:
    batch = uuid.uuid4()
    out: dict[Role, User] = {}
    for name, email, role in SEED_USERS:
        out[role] = await upsert_user(
            session, name=name, email=email, role=role, actor=None, batch_id=batch
        )
    return out


async def main() -> None:
    engine = create_engine(get_settings().database_url)
    try:
        async with create_sessionmaker(engine)() as session, session.begin():
            users = await seed_users(session)
        for role, user in users.items():
            print(f"  {user.id:>3}  {role.value:<9} {user.name}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
