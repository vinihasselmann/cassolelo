"""Origem da marca e parâmetros secundários (decisão de 2026-11-18).

Usa o modelo sintético "montagens" de test_mark_rule.py:

| dbid | Marca | Nome da montagem |
|------|-------|------------------|
| 10   | P1    | PP001            |
| 11   | P1    | PP001            |
| 12   | P1    | PP002            |
| 13   | P1    | PP002            |
| 14   | —     | PP003            |
"""

from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.aps.client import ApsClient
from app.config import Settings
from app.models import Element, ModelVersion, User
from app.models.enums import Role
from app.services import mark_origin as origin_service
from app.services import version_data
from app.services.mark_validation import mark_origin
from app.services.version_data import SecondaryValues, SourceCount, _Origin
from tests.apsfakes import Sleeps
from tests.conftest import as_user
from tests.test_mark_rule import _process
from tests.test_mark_rule import setup as setup  # fixture

RULE = ["Nome da montagem", "Marca"]


def _p(**ident: str) -> dict[str, Any]:
    return {"Dados de identidade": ident}


# ------------------------------------------------------------------ função pura


def test_origin_is_first_rule_name_with_the_mark() -> None:
    props = _p(**{"Nome da montagem": "PP001", "Marca": "P01"})
    assert mark_origin(props, RULE, "PP001") == ("Nome da montagem", [["Marca", "P01"]])


def test_origin_without_secondary() -> None:
    props = _p(**{"Nome da montagem": "PP002", "Marca": " "})
    assert mark_origin(props, RULE, "PP002") == ("Nome da montagem", [])


def test_origin_falls_back_to_next_name() -> None:
    props = _p(Marca="P05")
    assert mark_origin(props, RULE, "P05") == ("Marca", [])


def test_origin_is_case_insensitive_on_property_name() -> None:
    props = _p(**{"nome da montagem": "pp009", "MARCA": "P09"})
    assert mark_origin(props, RULE, "PP009") == ("Nome da montagem", [["Marca", "P09"]])


def test_piece_without_mark_has_no_origin() -> None:
    assert mark_origin(_p(Marca="P01"), RULE, None) == (None, [])


def test_aggregate_mixed_sources_and_divergent_secondary() -> None:
    agg = _Origin()
    agg.add("Nome da montagem", [["Marca", "P01"]])
    agg.add("Nome da montagem", [["Marca", "p01"]])  # mesmo valor (sem diferenciar caixa)
    agg.add("Marca", [["Marca", "P03"]])
    agg.add(None, [])
    assert agg.sources() == [SourceCount("Nome da montagem", 2), SourceCount("Marca", 1)]
    assert agg.secondary() == [SecondaryValues("Marca", ["P01", "P03"], 3)]


# ------------------------------------------------------------------ processamento


async def _marks(session: AsyncSession, version: ModelVersion) -> dict[str, Any]:
    marks = await version_data.list_marks(session, version.id)
    return {m.code: (m.sources, m.secondary) for m in marks}


async def test_processing_stores_origin_with_obra_rule(
    session: AsyncSession, aps: ApsClient, sleeps: Sleeps, setup: dict[str, Any]
) -> None:
    setup["obra"].mark_property_names = RULE
    await session.flush()
    await _process(session, aps, sleeps, setup["v1"])

    got = await _marks(session, setup["v1"])
    nome = "Nome da montagem"
    assert got["PP001"] == ([SourceCount(nome, 2)], [SecondaryValues("Marca", ["P1"], 2)])
    assert got["PP002"] == ([SourceCount(nome, 2)], [SecondaryValues("Marca", ["P1"], 2)])
    assert got["PP003"] == ([SourceCount(nome, 1)], [])  # sem Marca


async def test_divergent_secondary_when_rule_starts_with_marca(
    session: AsyncSession, aps: ApsClient, sleeps: Sleeps, setup: dict[str, Any]
) -> None:
    """Regra Marca > Nome da montagem: P1 junta PP001 e PP002 (vale a Marca; aviso)."""
    setup["obra"].mark_property_names = ["Marca", "Nome da montagem"]
    await session.flush()
    await _process(session, aps, sleeps, setup["v1"])

    got = await _marks(session, setup["v1"])
    assert got["P1"] == (
        [SourceCount("Marca", 4)],
        [SecondaryValues("Nome da montagem", ["PP001", "PP002"], 4)],
    )


async def test_default_rule_has_no_secondary_when_mark_param_missing(
    session: AsyncSession, setup: dict[str, Any]
) -> None:
    got = await _marks(session, setup["v1"])  # padrão do teste: Marca, Mark
    assert got == {"P1": ([SourceCount("Marca", 4)], [])}


async def test_backfill_rebuilds_origin_from_stored_props(
    session: AsyncSession, aps: ApsClient, sleeps: Sleeps, setup: dict[str, Any]
) -> None:
    setup["obra"].mark_property_names = RULE
    await session.flush()
    await _process(session, aps, sleeps, setup["v1"])
    # versão processada antes da 0018: colunas vazias
    await session.execute(
        update(Element)
        .where(Element.version_id == setup["v1"].id)
        .values(mark_source=None, mark_alt=[])
    )
    assert (await _marks(session, setup["v1"]))["PP001"] == ([], [])

    n = await origin_service.rebuild_version(session, setup["v1"], Settings())
    assert n == 5
    got = await _marks(session, setup["v1"])
    assert got["PP001"] == (
        [SourceCount("Nome da montagem", 2)],
        [SecondaryValues("Marca", ["P1"], 2)],
    )


# ------------------------------------------------------------------ API


async def test_api_marks_and_element_expose_origin(
    client: httpx.AsyncClient,
    session: AsyncSession,
    aps: ApsClient,
    sleeps: Sleeps,
    setup: dict[str, Any],
    users: dict[Role, User],
) -> None:
    setup["obra"].mark_property_names = RULE
    await session.flush()
    await _process(session, aps, sleeps, setup["v1"])
    await session.commit()
    h = as_user(users[Role.FABRICA])
    vid = setup["v1"].id

    marks = {
        m["code"]: m for m in (await client.get(f"/api/versions/{vid}/marks", headers=h)).json()
    }
    assert marks["PP001"]["sources"] == [{"name": "Nome da montagem", "pieces": 2}]
    assert marks["PP001"]["secondary"] == [{"name": "Marca", "values": ["P1"], "pieces": 2}]
    assert marks["PP003"]["secondary"] == []

    el = (await client.get(f"/api/versions/{vid}/elements/10", headers=h)).json()
    assert el["mark_source"] == "Nome da montagem"
    assert el["mark_alt"] == [{"name": "Marca", "value": "P1"}]
    el = (await client.get(f"/api/versions/{vid}/elements/14", headers=h)).json()
    assert el["mark_source"] == "Nome da montagem" and el["mark_alt"] == []


async def test_unmarked_piece_has_no_origin(session: AsyncSession, setup: dict[str, Any]) -> None:
    rows = await session.execute(
        select(Element.mark_source, Element.mark_alt).where(
            Element.version_id == setup["v1"].id, Element.dbid == 14
        )
    )
    assert rows.one() == (None, [])  # regra padrão: o dbid 14 não tem Marca
