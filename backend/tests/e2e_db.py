"""Banco do E2E (Playwright): cria `bim_e2e` se não existir e aplica as migrações.

O playwright.config.ts troca o DATABASE_URL para `.../bim_e2e`; este script recusa
qualquer outro nome para nunca migrar ou semear o banco de dev por engano.

    DATABASE_URL=postgresql+asyncpg://...:5432/bim_e2e uv run python -m tests.e2e_db
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings
from tests import dbutil

E2E_DATABASE = "bim_e2e"


async def _exists(url: str, name: str) -> bool:
    engine = create_async_engine(dbutil._render(url, "postgres"))
    try:
        async with engine.connect() as conn:
            found = await conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": name}
            )
            return found.scalar() is not None
    finally:
        await engine.dispose()


def main() -> int:
    url = get_settings().database_url
    if make_url(url).database != E2E_DATABASE:
        print(f"DATABASE_URL precisa apontar para o banco {E2E_DATABASE!r}.", file=sys.stderr)
        return 2
    if not asyncio.run(_exists(url, E2E_DATABASE)):
        asyncio.run(dbutil._admin(url, f'CREATE DATABASE "{E2E_DATABASE}"'))
        print(f"Banco {E2E_DATABASE} criado.")
    dbutil.upgrade(url)
    print(f"Banco {E2E_DATABASE} migrado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
