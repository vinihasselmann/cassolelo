"""Usuários do teste de carga (10.2): "Carga 01".."Carga NN", papel fábrica.

O limite de escritas é por usuário (120/min); com usuários próprios, cada usuário do
Locust tem a sua conta, como na fábrica. Tudo passa pela auditoria.

    uv run python -m tests.load_users up 30    # cria/reativa e imprime os ids (JSON)
    uv run python -m tests.load_users down     # desativa (somem do seletor de usuário)
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid

from sqlalchemy import select

from app.config import get_settings
from app.db import create_engine, create_sessionmaker
from app.models import User
from app.models.enums import Role
from app.services import audit
from app.services.users import upsert_user

DOMAIN = "@carga.dev.local"


async def up(count: int) -> list[int]:
    engine = create_engine(get_settings().database_url)
    batch = uuid.uuid4()
    try:
        async with create_sessionmaker(engine)() as session, session.begin():
            ids = []
            for n in range(1, count + 1):
                user = await upsert_user(
                    session,
                    name=f"Carga {n:02d}",
                    email=f"carga{n:02d}{DOMAIN}",
                    role=Role.FABRICA,
                    actor=None,
                    batch_id=batch,
                )
                ids.append(user.id)
            return ids
    finally:
        await engine.dispose()


async def down() -> int:
    engine = create_engine(get_settings().database_url)
    batch = uuid.uuid4()
    try:
        async with create_sessionmaker(engine)() as session, session.begin():
            users = await session.scalars(
                select(User).where(User.email.like(f"%{DOMAIN}"), User.active.is_(True))
            )
            n = 0
            for user in users:
                before = audit.snapshot(user)
                user.active = False
                await session.flush()
                await audit.record(
                    session, "user", user.id, "update", before, audit.snapshot(user), None, batch
                )
                n += 1
            return n
    finally:
        await engine.dispose()


def main(argv: list[str]) -> int:
    if argv[:1] == ["up"]:
        print(json.dumps(asyncio.run(up(int(argv[1]) if len(argv) > 1 else 30))))
        return 0
    if argv[:1] == ["down"]:
        print(f"{asyncio.run(down())} usuários de carga desativados.")
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
