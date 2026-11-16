"""Testes de migração: upgrade, downgrade e equivalência modelos x migração."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.models import Base
from tests import dbutil

TABLES = {
    "users",
    "obras",
    "model_versions",
    "elements",
    "version_reports",
    "version_diffs",
    "version_property_names",
    "marks",
    "param_defs",
    "param_values",
    "obra_params",
    "piece_props",
    "saved_filters",
    "color_schemes",
    "orphans",
    "audit_log",
    "webhook_events",
}


@pytest.fixture
def empty_db(postgres_base_url: str) -> Iterator[str]:
    url = dbutil.create_temp_database(postgres_base_url)
    try:
        yield url
    finally:
        dbutil.drop_database(url)


def _run_sync(url: str, fn: Any) -> Any:
    async def go() -> Any:
        engine = create_async_engine(url)
        try:
            async with engine.connect() as conn:
                return await conn.run_sync(fn)
        finally:
            await engine.dispose()

    return asyncio.run(go())


def _tables(conn: Connection) -> set[str]:
    return set(inspect(conn).get_table_names())


def _diff(conn: Connection) -> list[Any]:
    ctx = MigrationContext.configure(conn, opts={"compare_type": True})
    return list(compare_metadata(ctx, Base.metadata))


def test_upgrade_downgrade_upgrade(empty_db: str) -> None:
    dbutil.upgrade(empty_db)
    assert _run_sync(empty_db, _tables) == TABLES | {"alembic_version"}

    dbutil.downgrade(empty_db, "base")
    assert _run_sync(empty_db, _tables) == {"alembic_version"}

    dbutil.upgrade(empty_db)
    assert TABLES <= _run_sync(empty_db, _tables)


def test_models_match_migrations(empty_db: str) -> None:
    dbutil.upgrade(empty_db)
    diff = _run_sync(empty_db, _diff)
    assert diff == [], f"modelos e migração divergem (crie uma migração): {diff}"
