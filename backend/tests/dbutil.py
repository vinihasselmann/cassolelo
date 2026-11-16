"""Bancos de teste isolados: um banco temporário por sessão (ou por teste de migração)."""

from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

BACKEND_DIR = Path(__file__).resolve().parents[1]


def base_database_url() -> str | None:
    url = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")
    if url:
        return url
    try:
        from app.config import Settings

        return Settings().database_url
    except Exception:
        return None


def _render(url: str, database: str) -> str:
    return make_url(url).set(database=database).render_as_string(hide_password=False)


async def _server_ok(url: str) -> bool:
    engine = create_async_engine(_render(url, "postgres"), connect_args={"timeout": 3})
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
    finally:
        await engine.dispose()


def server_available(url: str) -> bool:
    return asyncio.run(_server_ok(url))


async def _admin(url: str, sql: str) -> None:
    engine = create_async_engine(_render(url, "postgres"), isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            await conn.execute(text(sql))
    finally:
        await engine.dispose()


def create_temp_database(base_url: str) -> str:
    name = f"bim_test_{uuid.uuid4().hex[:10]}"
    asyncio.run(_admin(base_url, f'CREATE DATABASE "{name}"'))
    return _render(base_url, name)


def drop_database(url: str) -> None:
    name = make_url(url).database
    asyncio.run(_admin(url, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


def alembic_config(url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.attributes["database_url"] = url
    cfg.attributes["configure_logger"] = False
    return cfg


def upgrade(url: str, target: str = "head") -> None:
    command.upgrade(alembic_config(url), target)


def downgrade(url: str, target: str = "base") -> None:
    command.downgrade(alembic_config(url), target)
