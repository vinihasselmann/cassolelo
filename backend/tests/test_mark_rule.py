"""Regra de identificação das peças por obra + assistente de candidatos.

Modelo sintético "montagens" (peças detalhadas pela equipe: Marca E Nome da montagem):

| dbid | Marca | Nome da montagem | Largura | Id interno | Fase |
|------|-------|------------------|---------|------------|------|
| 10   | P1    | PP001            | 40 cm   | A-10       | Nova |
| 11   | P1    | PP001            | 40 cm   | A-11       | Nova |
| 12   | P1    | PP002            | 60 cm   | A-12       | Nova |
| 13   | P1    | PP002            | 60 cm   | A-13       | Nova |
| 14   | —     | PP003            | 80 cm   | A-14       | Nova |

Pela Marca, P1 junta peças de 40 e 60 cm (inconsistente); pelo Nome da montagem as
três marcas são coerentes.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.aps.client import ApsClient
from app.models import (
    AuditLog,
    Element,
    Mark,
    ModelVersion,
    Obra,
    Orphan,
    ParamDef,
    ParamValue,
    User,
)
from app.models.enums import OrphanStatus, Role
from app.services import mark_candidates
from app.services.extraction import ExtractedElement
from app.services.processing import ProcessingConfig, process_version
from tests.apsfakes import MD, FakeQueue, Sleeps, mock_token
from tests.conftest import as_user, include_params

URN = "dXJubW9udGFnZW0"
GUID = "mont-3d-0001"
CONFIG = ProcessingConfig(
    mark_names=["Marca", "Mark"],
    category_names=["Category"],
    dimension_names=["Largura"],
)
PIECES = {
    10: ("P1", "PP001", "40.0 cm"),
    11: ("P1", "PP001", "40.0 cm"),
    12: ("P1", "PP002", "60.0 cm"),
    13: ("P1", "PP002", "60.0 cm"),
    14: (None, "PP003", "80.0 cm"),
}


def _props(dbid: int) -> dict[str, Any]:
    marca, montagem, largura = PIECES[dbid]
    ident: dict[str, Any] = {"Nome da montagem": montagem, "Id interno": f"A-{dbid}"}
    volume = {"PP001": "1.2 m^3", "PP002": "1.8 m^3", "PP003": "2.4 m^3"}[montagem]
    if marca:
        ident["Marca"] = marca
    return {
        "objectid": dbid,
        "name": f"Pilar [{dbid}]",
        "externalId": f"mont-{dbid}",
        "properties": {
            "Dados de identidade": ident,
            "Dimensões": {"Largura": largura, "Volume": volume},
            "Fases": {"Fase": "Nova"},
            "Other": {"Category": "Revit Structural Columns"},
        },
    }


def mock_montagens() -> None:
    respx.get(f"{MD}/{URN}/metadata").respond(
        200,
        json={
            "data": {
                "type": "metadata",
                "metadata": [{"name": "{3D}", "role": "3d", "guid": GUID, "isMasterView": True}],
            }
        },
    )
    leaves = [{"objectid": d, "name": f"Pilar [{d}]"} for d in PIECES]
    respx.get(f"{MD}/{URN}/metadata/{GUID}").respond(
        200,
        json={
            "data": {
                "type": "objects",
                "objects": [
                    {
                        "objectid": 1,
                        "name": "Model",
                        "objects": [
                            {"objectid": 2, "name": "Structural Columns", "objects": leaves}
                        ],
                    }
                ],
            }
        },
    )
    respx.get(f"{MD}/{URN}/metadata/{GUID}/properties").respond(
        200, json={"data": {"type": "properties", "collection": [_props(d) for d in PIECES]}}
    )


async def _process(
    session: AsyncSession, aps: ApsClient, sleeps: Sleeps, version: ModelVersion, **kw: Any
) -> None:
    with respx.mock:
        mock_token()
        mock_montagens()
        result = await process_version(session, aps, version.id, CONFIG, sleep=sleeps, **kw)
    assert result is not None and result.status == "ready", result


@pytest.fixture
async def setup(session: AsyncSession, aps: ApsClient, sleeps: Sleeps) -> dict[str, Any]:
    obra = Obra(code="OB-MONT", name="Obra montagens")
    session.add(obra)
    await session.flush()
    v1 = ModelVersion(obra_id=obra.id, acc_version_id="urn:v:mont:1", version_number=1, urn=URN)
    session.add(v1)
    await session.flush()
    await _process(session, aps, sleeps, v1)
    return {"obra": obra, "v1": v1}


async def _marks(session: AsyncSession, version: ModelVersion) -> dict[str, list[int]]:
    rows = await session.execute(
        select(Mark.code, Element.dbid)
        .join(Element, Element.mark_id == Mark.id)
        .where(Element.version_id == version.id)
        .order_by(Element.dbid)
    )
    out: dict[str, list[int]] = {}
    for code, dbid in rows:
        out.setdefault(code, []).append(dbid)
    return out


# ------------------------------------------------------------------- regra na extração


async def test_default_rule_uses_marca(session: AsyncSession, setup: dict[str, Any]) -> None:
    assert await _marks(session, setup["v1"]) == {"P1": [10, 11, 12, 13]}


async def test_obra_rule_priority_assembly_name_over_marca(
    session: AsyncSession, aps: ApsClient, sleeps: Sleeps, setup: dict[str, Any]
) -> None:
    setup["obra"].mark_property_names = ["Nome da montagem", "Marca"]
    await session.flush()
    await _process(session, aps, sleeps, setup["v1"])
    assert await _marks(session, setup["v1"]) == {
        "PP001": [10, 11],
        "PP002": [12, 13],
        "PP003": [14],
    }


async def test_rule_falls_back_to_next_name(
    session: AsyncSession, aps: ApsClient, sleeps: Sleeps, setup: dict[str, Any]
) -> None:
    """Prioridade: sem o primeiro parâmetro na peça, vale o seguinte."""
    setup["obra"].mark_property_names = ["Inexistente", "Marca"]
    await session.flush()
    await _process(session, aps, sleeps, setup["v1"])
    assert await _marks(session, setup["v1"]) == {"P1": [10, 11, 12, 13]}


async def test_rule_change_orphans_marks_with_values_even_with_one_version(
    session: AsyncSession, aps: ApsClient, sleeps: Sleeps, setup: dict[str, Any]
) -> None:
    p1 = await session.scalar(select(Mark).where(Mark.code == "P1"))
    assert p1 is not None
    pd = ParamDef(name="Liberação", type="text", scope="global")
    session.add(pd)
    await session.flush()
    await include_params(session, setup["obra"].id, pd)
    session.add(ParamValue(mark_id=p1.id, def_id=pd.id, value="ok"))
    await session.flush()

    setup["obra"].mark_property_names = ["Nome da montagem"]
    await session.flush()
    await _process(session, aps, sleeps, setup["v1"], orphan_missing=True)

    orphans = list(await session.scalars(select(Orphan).where(Orphan.mark_id == p1.id)))
    assert [(o.status, o.since_version_id) for o in orphans] == [
        (OrphanStatus.OPEN.value, setup["v1"].id)
    ]
    # o valor continua lá (nunca apagar)
    assert await session.scalar(select(ParamValue.value).where(ParamValue.mark_id == p1.id)) == "ok"
    audit = await session.scalar(
        select(AuditLog).where(
            AuditLog.entity == "orphan", AuditLog.entity_id == str(orphans[0].id)
        )
    )
    assert audit is not None and audit.after is not None and audit.after["reason"] == "mark_rule"

    # reprocessar de novo não duplica a órfã
    await _process(session, aps, sleeps, setup["v1"], orphan_missing=True)
    assert len(list(await session.scalars(select(Orphan).where(Orphan.mark_id == p1.id)))) == 1


async def _value(session: AsyncSession, code: str, def_id: int) -> Any:
    return await session.scalar(
        select(ParamValue.value)
        .join(Mark, Mark.id == ParamValue.mark_id)
        .where(Mark.code == code, ParamValue.def_id == def_id)
    )


async def test_rule_change_moves_values_when_pieces_go_to_one_new_mark(
    session: AsyncSession,
    aps: ApsClient,
    sleeps: Sleeps,
    users: dict[Role, User],
    setup: dict[str, Any],
) -> None:
    """Item 4: regra "Nome da montagem" → "Marca, Nome da montagem".

    PP001 (peças 10, 11) vai inteira para P1 → leva o valor (religação automática).
    PP002 (12, 13) também vai para P1, mas com OUTRO valor → conflito → órfã aberta.
    PP003 (14, sem Marca) continua PP003 → nada muda."""
    setup["obra"].mark_property_names = ["Nome da montagem"]
    await session.flush()
    await _process(session, aps, sleeps, setup["v1"])
    marks = {
        m.code: m
        for m in await session.scalars(select(Mark).where(Mark.obra_id == setup["obra"].id))
    }
    forma = ParamDef(name="Forma", type="text", scope="global")
    session.add(forma)
    await session.flush()
    await include_params(session, setup["obra"].id, forma)
    session.add_all(
        [
            ParamValue(mark_id=marks["PP001"].id, def_id=forma.id, value="F-1"),
            ParamValue(mark_id=marks["PP002"].id, def_id=forma.id, value="F-2"),
            ParamValue(mark_id=marks["PP003"].id, def_id=forma.id, value="F-3"),
        ]
    )
    await session.flush()

    actor = users[Role.FABRICA]
    setup["obra"].mark_property_names = ["Marca", "Nome da montagem"]
    await session.flush()
    await _process(session, aps, sleeps, setup["v1"], orphan_missing=True, actor_id=actor.id)

    assert await _marks(session, setup["v1"]) == {"P1": [10, 11, 12, 13], "PP003": [14]}
    assert await _value(session, "P1", forma.id) == "F-1"  # levado do PP001
    assert await _value(session, "PP003", forma.id) == "F-3"  # intocado
    # as marcas antigas mantêm os valores (nunca apagar)
    assert await _value(session, "PP001", forma.id) == "F-1"
    assert await _value(session, "PP002", forma.id) == "F-2"

    orphans = {
        o.mark_id: o
        for o in await session.scalars(
            select(Orphan).where(Orphan.since_version_id == setup["v1"].id)
        )
    }
    pp001, pp002 = orphans[marks["PP001"].id], orphans[marks["PP002"].id]
    p1 = await session.scalar(
        select(Mark.id).where(Mark.obra_id == setup["obra"].id, Mark.code == "P1")
    )
    assert pp001.status == OrphanStatus.RELINKED.value and pp001.relinked_to == p1
    assert pp002.status == OrphanStatus.OPEN.value  # conflito: decisão manual

    moved = await session.scalar(
        select(AuditLog).where(AuditLog.entity == "mark_value", AuditLog.user_id == actor.id)
    )
    assert moved is not None and moved.after is not None
    assert moved.after["source"] == "mark_rule" and moved.after["from_mark"] == "PP001"

    version = await session.get(ModelVersion, setup["v1"].id)
    assert version is not None
    ready = await session.scalar(
        select(AuditLog)
        .where(
            AuditLog.entity == "model_version",
            AuditLog.entity_id == str(version.id),
            AuditLog.action == "process_ready",
        )
        .order_by(AuditLog.id.desc())
        .limit(1)
    )
    assert ready is not None and ready.after is not None
    assert [r["mark"] for r in ready.after["rule_relinked"]] == ["PP001"]
    assert [(o["mark"], o["reason"]) for o in ready.after["rule_orphans"]] == [
        ("PP002", "a marca P1 já tem outro valor em: Forma")
    ]


# ------------------------------------------------------------------------- candidatos


def _el(dbid: int, category: str = "Pilares") -> ExtractedElement:
    return ExtractedElement(
        dbid=dbid,
        external_id=None,
        name=None,
        category=category,
        mark_raw=None,
        mark_code=None,
        props=_props(dbid)["properties"],
    )


def test_candidates_rank_consistent_full_coverage_first() -> None:
    analysis = mark_candidates.analyze(
        [_el(d) for d in PIECES],
        ["Largura"],
        5.0,
        current_names=["Marca"],
        excluded_names=["Category"],
    )
    assert analysis.dimensions_checked
    result = analysis.candidates
    by_name = {c.name: c for c in result}
    first = result[0]
    assert first.name == "Nome da montagem"
    assert (first.pieces_with_value, first.marks, first.inconsistent_marks) == (5, 3, 0)
    assert first.examples[0] == ("PP001", 2)

    marca = by_name["Marca"]
    assert (marca.pieces_with_value, marca.marks) == (4, 1)
    assert (marca.inconsistent_marks, marca.inconsistent_pieces) == (1, 4)
    assert marca.current

    assert by_name["Id interno"].unique_per_piece
    assert by_name["Fase"].constant
    # a dimensão configurada e a categoria não são candidatas
    assert "Largura" not in by_name and "Category" not in by_name
    assert marca.constant  # neste modelo toda Marca é "P1"
    # Volume agrupa igual ao Nome da montagem, mas é medida (número + unidade)
    assert by_name["Volume"].measure and not first.measure
    # sinais ruins (único por peça, constante, medida) vão para o fim
    assert [c.name for c in result] == [
        "Nome da montagem",
        "Id interno",
        "Volume",
        "Fase",
        "Marca",
    ]


def test_candidates_near_unique_and_without_dimensions() -> None:
    """GUID quase único (≥ 90%) é sinal ruim; sem as dimensões configuradas no modelo,
    a inconsistência não é conferida (dimensions_checked = False)."""
    els = [
        ExtractedElement(
            dbid=d,
            external_id=None,
            name=None,
            category="Pilares",
            mark_raw=None,
            mark_code=None,
            props={"IFC": {"GlobalId": f"G{min(d, 18)}", "Reference": f"R-{d % 2}"}},
        )
        for d in range(1, 21)
    ]
    analysis = mark_candidates.analyze(els, ["Largura"], 5.0, current_names=["Marca"])
    assert not analysis.dimensions_checked
    guid = next(c for c in analysis.candidates if c.name == "GlobalId")
    assert guid.marks == 18 and guid.unique_per_piece  # 18 de 20 = 90%
    assert [c.name for c in analysis.candidates] == ["Reference", "GlobalId"]


def test_candidates_limit_keeps_current_rule() -> None:
    result = mark_candidates.analyze(
        [_el(d) for d in PIECES],
        ["Largura"],
        5.0,
        current_names=["Id interno"],
        limit=1,
        excluded_names=["Category"],
    ).candidates
    assert [c.name for c in result] == ["Nome da montagem", "Id interno"]


# ------------------------------------------------------------------------------- API


async def test_api_get_and_put_rule_any_role(
    session: AsyncSession,
    client: httpx.AsyncClient,
    queue: FakeQueue,
    users: dict[Role, User],
    setup: dict[str, Any],
) -> None:
    obra_id = setup["obra"].id
    r = await client.get(f"/api/obras/{obra_id}/mark-rule", headers=as_user(users[Role.LEITURA]))
    assert r.status_code == 200
    assert r.json()["mark_property_names"] == r.json()["default_mark_property_names"]
    assert r.json()["custom_marks"] is False

    body = {"mark_property_names": [" Nome da montagem ", "marca", "Marca", ""]}
    for role in (Role.LEITURA, Role.FABRICA):  # todos os papéis podem definir
        r = await client.put(
            f"/api/obras/{obra_id}/mark-rule", json=body, headers=as_user(users[role])
        )
        assert r.status_code == 200, r.text
    out = r.json()
    assert out["mark_property_names"] == ["Nome da montagem", "marca"]  # limpo, sem repetidos
    assert out["changed"] is False  # a 2ª vez já era a mesma regra
    jobs = [j for j in queue.jobs if j[0] == "process_version"]
    assert len(jobs) == 1  # só a 1ª mudança reprocessa
    assert jobs[0][1] == (setup["v1"].id, True, users[Role.LEITURA].id)
    assert jobs[0][2] is not None and ":rule:" in jobs[0][2]

    audit = list(
        await session.scalars(
            select(AuditLog).where(AuditLog.entity == "obra", AuditLog.action == "mark_rule")
        )
    )
    assert len(audit) == 1 and audit[0].user_id == users[Role.LEITURA].id

    # null volta ao padrão
    r = await client.put(
        f"/api/obras/{obra_id}/mark-rule",
        json={"mark_property_names": None},
        headers=as_user(users[Role.PROJETOS]),
    )
    assert r.json()["custom_marks"] is False and r.json()["changed"] is True


async def test_api_put_rule_validation(
    client: httpx.AsyncClient, users: dict[Role, User], setup: dict[str, Any]
) -> None:
    url = f"/api/obras/{setup['obra'].id}/mark-rule"
    h = as_user(users[Role.FABRICA])
    r = await client.put(url, json={"mark_property_names": [" ", ""]}, headers=h)
    assert r.status_code == 422 and "pelo menos um" in r.json()["detail"]
    r = await client.put(url, json={"mark_property_names": [f"P{i}" for i in range(11)]}, headers=h)
    assert r.status_code == 422
    r = await client.put(url, json={"mark_property_names": ["Marca"]})
    assert r.status_code == 401
    r = await client.put(
        "/api/obras/999999/mark-rule", json={"mark_property_names": ["M"]}, headers=h
    )
    assert r.status_code == 404


async def test_api_put_rule_queue_down_keeps_rule(
    session: AsyncSession,
    client: httpx.AsyncClient,
    queue: FakeQueue,
    users: dict[Role, User],
    setup: dict[str, Any],
) -> None:
    queue.fail = True
    r = await client.put(
        f"/api/obras/{setup['obra'].id}/mark-rule",
        json={"mark_property_names": ["Nome da montagem"]},
        headers=as_user(users[Role.FABRICA]),
    )
    assert r.status_code == 200
    assert r.json()["enqueued"] is False and r.json()["reprocess_version_number"] == 1
    await session.refresh(setup["obra"])
    assert setup["obra"].mark_property_names == ["Nome da montagem"]


async def test_api_candidates(
    client: httpx.AsyncClient, users: dict[Role, User], setup: dict[str, Any]
) -> None:
    r = await client.get(
        f"/api/versions/{setup['v1'].id}/mark-candidates",
        headers=as_user(users[Role.LEITURA]),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["pieces"] == 5 and body["mark_property_names"][0] == "Marca"
    first = body["candidates"][0]
    assert first["name"] == "Nome da montagem" and first["groups"] == ["Dados de identidade"]
    assert first["examples"][0] == ["PP001", 2]
    r = await client.get(
        "/api/versions/999999/mark-candidates", headers=as_user(users[Role.LEITURA])
    )
    assert r.status_code == 404


# ------------------------------------------------- item 3: identificadores divergentes


async def test_report_lists_divergent_identifiers_and_search_finds_alias(
    session: AsyncSession,
    aps: ApsClient,
    sleeps: Sleeps,
    client: httpx.AsyncClient,
    users: dict[Role, User],
    setup: dict[str, Any],
) -> None:
    setup["obra"].mark_property_names = ["Nome da montagem", "Marca"]
    await session.flush()
    await _process(session, aps, sleeps, setup["v1"])

    h = as_user(users[Role.FABRICA])
    r = await client.get(f"/api/versions/{setup['v1'].id}/report", headers=h)
    report = r.json()["report"]
    # 10-13 têm Nome da montagem PP00x e Marca P1; a 14 só tem Nome da montagem
    assert report["totals"]["divergent_pieces"] == 4
    first = report["divergent"][0]
    assert first["dbid"] == 10 and first["mark"] == "PP001"
    assert first["values"] == [
        {"property": "Nome da montagem", "value": "PP001"},
        {"property": "Marca", "value": "P1"},
    ]

    # a busca acha a peça pelo apelido (Marca P1) e devolve as marcas da regra
    r = await client.get(
        f"/api/versions/{setup['v1'].id}/marks/search", params={"q": "P1"}, headers=h
    )
    assert [m["code"] for m in r.json()["items"]] == ["PP001", "PP002"]


def test_no_divergence_with_single_name_or_equal_values() -> None:
    from app.services.mark_validation import divergent_pieces

    els = [_el(d) for d in PIECES]
    assert divergent_pieces(els, ["Marca"]) == []
    # "Marca" e "Mark" com o mesmo valor (só maiúsculas diferentes) não é divergência
    same = ExtractedElement(
        dbid=1,
        external_id=None,
        name=None,
        category="Pilares",
        mark_raw=None,
        mark_code="P1",
        props={"A": {"Marca": "p1"}, "B": {"Mark": "P1 "}},
    )
    assert divergent_pieces([same], ["Marca", "Mark"]) == []


async def test_api_assembly_mode_is_part_of_the_rule(
    client: httpx.AsyncClient, queue: FakeQueue, users: dict[Role, User], setup: dict[str, Any]
) -> None:
    url = f"/api/obras/{setup['obra'].id}/mark-rule"
    h = as_user(users[Role.FABRICA])
    r = await client.get(url, headers=h)
    assert r.json()["piece_category_names"] is None  # desligado
    assert r.json()["default_piece_category_names"] == ["Pilares estruturais", "Quadro estrutural"]
    body: dict[str, Any] = {
        "mark_property_names": ["Nome da montagem"],
        "piece_category_names": ["Pilares estruturais", "Quadro estrutural"],
    }
    r = await client.put(url, json=body, headers=h)
    assert r.status_code == 200 and r.json()["changed"] is True
    assert r.json()["piece_category_names"] == ["Pilares estruturais", "Quadro estrutural"]
    # desligar o modo também é mudança de regra (reprocessa)
    body["piece_category_names"] = None
    r = await client.put(url, json=body, headers=h)
    assert r.json()["changed"] is True and r.json()["piece_category_names"] is None
    assert len([j for j in queue.jobs if j[0] == "process_version"]) == 2
