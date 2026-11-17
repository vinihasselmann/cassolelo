"""Esquemas de cores (/api/color-schemes, /color-scheme/evaluate) e coloração por campo
(/colorize): prioridade das regras, estabilidade das cores, faixas e permissões.

Obra sintética de test_filters.py (v1). Largura: 10 e 11 = 40, 12 = 60, 20 = 25,5;
21 e 30 sem valor. Datas: 10 = 05/11, 11 = 10/11, 12 = 20/10, 20 = 30/09 (2026).
Membros: a peça N tem os membros N*100+1 e N*100+2.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, Element, ModelVersion, Obra, User, VersionPropertyName
from app.models.enums import Role
from app.services import colors, piece_props
from tests.conftest import as_user
from tests.test_filters import build_ctx

SCHEMES = "/api/color-schemes"
FILTERS = "/api/saved-filters"
RED, BLUE, GRAY = "#D62728", "#1F77B4", "#9AA0A6"


def F(source: str, key: str) -> dict[str, str]:
    return {"source": source, "key": key}


def definition(*rules: dict[str, Any]) -> dict[str, Any]:
    return {"mode": "highlight", "logic": "and", "rules": list(rules)}


PILAR = definition({"field": F("system", "category"), "op": "eq", "value": "Pilar"})
TERREO = definition({"field": F("system", "level"), "op": "eq", "value": "TÉRREO"})
EVERYTHING = definition()


@pytest.fixture
async def ctx(session: AsyncSession, users: dict[Role, User]) -> dict[str, Any]:
    c = await build_ctx(session, users)
    c["h"] = {role: as_user(u) for role, u in users.items()}
    c["url"] = f"/api/versions/{c['v'].id}"
    return c


def members(dbid: int) -> list[int]:
    return [dbid, dbid * 100 + 1, dbid * 100 + 2]


# --------------------------------------------------------------- esquemas: regras


async def _evaluate(client: httpx.AsyncClient, ctx: dict[str, Any], body: dict[str, Any]) -> Any:
    r = await client.post(
        f"{ctx['url']}/color-scheme/evaluate", json=body, headers=ctx["h"][Role.LEITURA]
    )
    assert r.status_code == 200, r.text
    return r.json()


async def test_first_matching_rule_wins(client: httpx.AsyncClient, ctx: dict[str, Any]) -> None:
    rules = [
        {"filter": PILAR, "color": RED, "label": "Pilares"},
        {"filter": TERREO, "color": BLUE, "label": "Térreo"},
        {"filter": EVERYTHING, "color": "#cccccc", "label": "Resto"},
    ]
    body = await _evaluate(client, ctx, {"rules": rules})
    c = body["colors"]
    for dbid in (10, 11, 12):
        assert all(c[str(d)] == RED for d in members(dbid)), dbid  # peça e membros
    for dbid in (20, 30):
        assert c[str(dbid)] == BLUE
    assert c["21"] == "#CCCCCC"  # cor normalizada em maiúsculas
    counts = [(r["label"], r["matched"], r["pieces"]) for r in body["rules"]]
    assert counts == [("Pilares", 3, 3), ("Térreo", 4, 2), ("Resto", 6, 1)]
    # peças que ficaram com a cor de cada regra (sem membros): a legenda seleciona por elas
    assert [r["dbids"] for r in body["rules"]] == [[10, 11, 12], [20, 30], [21]]
    assert (body["total_pieces"], body["colored_pieces"]) == (6, 6)

    # trocando a ordem, a prioridade muda
    body = await _evaluate(client, ctx, {"rules": [rules[1], rules[0]]})
    assert body["colors"]["10"] == BLUE and body["colors"]["12"] == RED
    assert [(r["matched"], r["pieces"]) for r in body["rules"]] == [(4, 4), (3, 1)]
    assert body["colored_pieces"] == 5 and "21" not in body["colors"]


async def test_saved_scheme_with_saved_filter(
    client: httpx.AsyncClient, ctx: dict[str, Any]
) -> None:
    fab = ctx["h"][Role.FABRICA]
    f = await client.post(
        FILTERS, json={"name": "Pilares", "scope": "shared", "definition": PILAR}, headers=fab
    )
    fid = f.json()["id"]
    s = await client.post(
        SCHEMES,
        json={
            "name": "Fábrica",
            "scope": "shared",
            "rules": [{"filter": fid, "color": RED}, {"filter": TERREO, "color": BLUE}],
        },
        headers=fab,
    )
    assert s.status_code == 201, s.text
    body = await _evaluate(client, ctx, {"scheme_id": s.json()["id"]})
    assert body["rules"][0]["label"] == "Pilares"  # sem rótulo: o nome do filtro
    assert body["rules"][0]["filter_id"] == fid
    assert body["colors"]["12"] == RED and body["colors"]["20"] == BLUE

    # o filtro em uso não pode ser excluído nem virar pessoal
    r = await client.delete(f"{FILTERS}/{fid}", headers=fab)
    assert r.status_code == 409 and "Fábrica" in r.json()["detail"]
    r = await client.patch(f"{FILTERS}/{fid}", json={"scope": "personal"}, headers=fab)
    assert r.status_code == 409
    # tirando-o do esquema, pode
    r = await client.patch(
        f"{SCHEMES}/{s.json()['id']}",
        json={"rules": [{"filter": TERREO, "color": BLUE}]},
        headers=fab,
    )
    assert r.status_code == 200, r.text
    assert (await client.delete(f"{FILTERS}/{fid}", headers=fab)).status_code == 204


async def test_scheme_rules_validated(client: httpx.AsyncClient, ctx: dict[str, Any]) -> None:
    fab, lei = ctx["h"][Role.FABRICA], ctx["h"][Role.LEITURA]
    personal = await client.post(FILTERS, json={"name": "Meu", "definition": PILAR}, headers=fab)
    pid = personal.json()["id"]
    others = await client.post(FILTERS, json={"name": "Do outro", "definition": PILAR}, headers=lei)
    bad: list[dict[str, Any]] = [
        {"name": "x", "rules": []},
        {"name": "x", "rules": [{"filter": PILAR, "color": "red"}]},
        {"name": "x", "rules": [{"filter": PILAR, "color": "#12345"}]},
        {"name": "x", "rules": [{"filter": True, "color": RED}]},
        {"name": "x", "rules": [{"filter": 999999, "color": RED}]},
        {"name": "x", "rules": [{"filter": others.json()["id"], "color": RED}]},  # de outro
        {"name": "x", "scope": "shared", "rules": [{"filter": pid, "color": RED}]},  # pessoal
    ]
    for body in bad:
        r = await client.post(SCHEMES, json=body, headers=fab)
        assert r.status_code == 422, (body, r.text)
    ok = await client.post(
        SCHEMES, json={"name": "x", "rules": [{"filter": pid, "color": RED}]}, headers=fab
    )
    assert ok.status_code == 201, ok.text  # esquema pessoal usa filtro pessoal do dono
    r = await client.post(
        f"{ctx['url']}/color-scheme/evaluate",
        json={"scheme_id": ok.json()["id"], "rules": []},
        headers=fab,
    )
    assert r.status_code == 422


async def test_scheme_obra_rules(
    client: httpx.AsyncClient, session: AsyncSession, ctx: dict[str, Any]
) -> None:
    other = Obra(code="OB-C2", name="Outra")
    session.add(other)
    await session.flush()
    fab = ctx["h"][Role.FABRICA]
    f = await client.post(
        FILTERS, json={"name": "Da outra", "obra_id": other.id, "definition": PILAR}, headers=fab
    )
    # filtro de uma obra num esquema de todas as obras: não
    r = await client.post(
        SCHEMES,
        json={"name": "x", "rules": [{"filter": f.json()["id"], "color": RED}]},
        headers=fab,
    )
    assert r.status_code == 422 and "outra obra" in r.json()["detail"]
    s = await client.post(
        SCHEMES,
        json={"name": "Da outra", "obra_id": other.id, "rules": [{"filter": PILAR, "color": RED}]},
        headers=fab,
    )
    r = await client.post(
        f"{ctx['url']}/color-scheme/evaluate", json={"scheme_id": s.json()["id"]}, headers=fab
    )
    assert r.status_code == 422 and "outra obra" in r.json()["detail"]


async def test_scheme_permissions_and_audit(
    client: httpx.AsyncClient, session: AsyncSession, ctx: dict[str, Any]
) -> None:
    fab, lei, adm = ctx["h"][Role.FABRICA], ctx["h"][Role.LEITURA], ctx["h"][Role.ADMIN]
    body = {"name": "Comp", "scope": "shared", "rules": [{"filter": PILAR, "color": RED}]}
    assert (await client.post(SCHEMES, json=body, headers=lei)).status_code == 403
    shared = await client.post(SCHEMES, json=body, headers=fab)
    sid = shared.json()["id"]
    assert (
        await client.post(SCHEMES, json={**body, "name": "COMP"}, headers=adm)
    ).status_code == 409
    listed = {s["id"]: s for s in (await client.get(SCHEMES, headers=lei)).json()}
    assert listed[sid]["editable"] is False  # leitura vê, mas não edita
    assert (
        await client.patch(f"{SCHEMES}/{sid}", json={"name": "Y"}, headers=lei)
    ).status_code == 403
    assert (
        await client.patch(f"{SCHEMES}/{sid}", json={"name": "Y"}, headers=adm)
    ).status_code == 200
    assert (await client.delete(f"{SCHEMES}/{sid}", headers=adm)).status_code == 204

    mine = await client.post(
        SCHEMES, json={**body, "scope": "personal", "name": "Meu"}, headers=lei
    )
    mid = mine.json()["id"]
    assert (await client.get(f"{SCHEMES}/{mid}", headers=adm)).status_code == 404
    r = await client.post(
        f"{ctx['url']}/color-scheme/evaluate", json={"scheme_id": mid}, headers=adm
    )
    assert r.status_code == 404
    assert (await client.delete(f"{SCHEMES}/{mid}", headers=lei)).status_code == 204

    rows = list(
        await session.scalars(
            select(AuditLog).where(AuditLog.entity == "color_scheme").order_by(AuditLog.id)
        )
    )
    assert [(r.entity_id, r.action) for r in rows] == [
        (str(sid), "create"),
        (str(sid), "update"),
        (str(sid), "delete"),
    ]
    assert rows[1].before is not None and rows[1].after is not None
    assert (rows[1].before["name"], rows[1].after["name"]) == ("Comp", "Y")


# ------------------------------------------------------------ coloração por campo


async def _colorize(
    client: httpx.AsyncClient, ctx: dict[str, Any], field: dict[str, str], mode: str, url: str = ""
) -> httpx.Response:
    return await client.post(
        f"{url or ctx['url']}/colorize",
        json={"field": field, "mode": mode},
        headers=ctx["h"][Role.LEITURA],
    )


def test_stable_color_is_fixed_and_ignores_case_and_accents() -> None:
    assert colors.stable_color("Junta EPS") == "#C49C94"
    assert colors.stable_color("Pilar Térreo") == "#FF7F0E"
    assert colors.stable_color("PILAR TERREO") == colors.stable_color(" pilar  térreo ")
    assert colors.NO_VALUE_COLOR not in colors.PALETTE


async def test_distinct_colors_are_stable(
    client: httpx.AsyncClient, session: AsyncSession, ctx: dict[str, Any]
) -> None:
    tipo = F("model", "Dados/Tipo")
    first = await _colorize(client, ctx, tipo, "distinct")
    assert first.status_code == 200, first.text
    body = first.json()
    legend = [(i["value"], i["color"], i["pieces"]) for i in body["legend"]]
    assert legend == [
        ("Pilar Térreo", "#FF7F0E", 2),
        ("Viga 25x60", colors.stable_color("Viga 25x60"), 2),
        ("Junta EPS", "#C49C94", 1),
        ("Pilar alto", colors.stable_color("Pilar alto"), 1),
    ]
    assert all(body["colors"][str(d)] == "#FF7F0E" for d in members(10))
    again = (await _colorize(client, ctx, tipo, "distinct")).json()
    assert again["colors"] == body["colors"]

    # outra versão, com outros valores: o mesmo valor mantém a cor
    v2 = ModelVersion(
        obra_id=ctx["obra"].id, acc_version_id="urn:f:2", version_number=2, status="ready"
    )
    session.add(v2)
    await session.flush()
    for dbid, tipo_value in ((50, "Junta EPS"), (51, "Laje alveolar")):
        session.add(
            Element(
                version_id=v2.id,
                dbid=dbid,
                external_id=f"x{dbid}",
                name="x",
                category="Outros",
                props={"Dados": {"Tipo": tipo_value}},
                member_dbids=[],
            )
        )
    session.add(VersionPropertyName(version_id=v2.id, group_name="Dados", prop_name="Tipo"))
    await session.flush()
    await piece_props.rebuild_version(session, v2.id)
    other = (await _colorize(client, ctx, tipo, "distinct", f"/api/versions/{v2.id}")).json()
    assert other["colors"]["50"] == "#C49C94"


async def test_distinct_without_value_is_gray(
    client: httpx.AsyncClient, ctx: dict[str, Any]
) -> None:
    body = (await _colorize(client, ctx, F("model", "Mix/Código"), "distinct")).json()
    assert body["legend"][-1] == {
        "label": "Sem valor",
        "color": colors.NO_VALUE_COLOR,
        "pieces": 3,
        "value": None,
        "min": None,
        "max": None,
        "dbids": [20, 21, 30],
    }
    for dbid in (20, 21, 30):
        assert body["colors"][str(dbid)] == colors.NO_VALUE_COLOR
    assert sum(i["pieces"] for i in body["legend"]) == body["total_pieces"] == 6


async def test_distinct_status_uses_app_colors(
    client: httpx.AsyncClient, ctx: dict[str, Any]
) -> None:
    body = (await _colorize(client, ctx, F("system", "status"), "distinct")).json()
    assert body["colors"]["10"] == colors.STATUS_COLORS["Completa"]
    assert body["colors"]["12"] == colors.STATUS_COLORS["Pendente"]
    assert body["colors"]["30"] == colors.NO_VALUE_COLOR  # peça sem marca
    assert [(i["label"], i["pieces"]) for i in body["legend"]] == [
        ("Pendente", 3),
        ("Completa", 2),
        ("Sem marca", 1),  # no status, "sem valor" é peça sem marca
    ]
    assert [i["dbids"] for i in body["legend"]] == [[12, 20, 21], [10, 11], [30]]


async def test_range_numbers_five_bands(client: httpx.AsyncClient, ctx: dict[str, Any]) -> None:
    r = await _colorize(client, ctx, F("model", "Dimensões/Largura"), "range")
    assert r.status_code == 200, r.text
    body = r.json()
    bands = [(i["min"], i["max"], i["pieces"], i["color"]) for i in body["legend"]]
    assert [round(b[0], 2) for b in bands[:5]] == [25.5, 32.4, 39.3, 46.2, 53.1]
    assert [round(b[1], 2) for b in bands[:5]] == [32.4, 39.3, 46.2, 53.1, 60.0]
    assert [b[2] for b in bands] == [1, 0, 2, 0, 1, 2]  # + sem valor
    assert [i["dbids"] for i in body["legend"]] == [[20], [], [10, 11], [], [12], [21, 30]]
    assert [b[3] for b in bands[:5]] == list(colors.RANGE_COLORS)
    assert body["legend"][-1]["color"] == colors.NO_VALUE_COLOR
    c = body["colors"]
    assert (c["20"], c["10"], c["12"], c["21"]) == (
        colors.RANGE_COLORS[0],
        colors.RANGE_COLORS[2],
        colors.RANGE_COLORS[4],
        colors.NO_VALUE_COLOR,
    )


async def test_range_dates_whole_days(client: httpx.AsyncClient, ctx: dict[str, Any]) -> None:
    body = (await _colorize(client, ctx, F("model", "Datas/Data Expedição"), "range")).json()
    bands = [(i["min"], i["max"], i["pieces"]) for i in body["legend"][:5]]
    assert bands == [
        ("2026-09-30", "2026-10-07", 1),
        ("2026-10-08", "2026-10-15", 0),
        ("2026-10-16", "2026-10-24", 1),
        ("2026-10-25", "2026-11-01", 0),
        ("2026-11-02", "2026-11-10", 2),
    ]
    assert body["legend"][0]["label"] == "2026-09-30 – 2026-10-07"


async def test_range_single_value_and_factory_number(
    client: httpx.AsyncClient, ctx: dict[str, Any]
) -> None:
    ciclo = F("factory", str(ctx["p"]["ciclo"].id))  # 12 na V01
    body = (await _colorize(client, ctx, ciclo, "range")).json()
    assert [(i["min"], i["max"], i["pieces"]) for i in body["legend"]] == [
        (12.0, 12.0, 2),
        (None, None, 4),
    ]
    assert body["legend"][0]["label"] == "12"


async def test_colorize_errors(
    client: httpx.AsyncClient, ctx: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    r = await _colorize(client, ctx, F("model", "Dados/Tipo"), "range")
    assert r.status_code == 422 and "texto" in r.json()["detail"]
    assert (await _colorize(client, ctx, F("system", "new"), "distinct")).status_code == 422
    assert (await _colorize(client, ctx, F("model", "Nada/Nada"), "distinct")).status_code == 422
    monkeypatch.setattr(colors, "MAX_DISTINCT", 2)
    r = await _colorize(client, ctx, F("model", "Dados/Tipo"), "distinct")
    assert r.status_code == 422 and "valores diferentes" in r.json()["detail"]
    r = await client.post(
        f"{ctx['url']}/colorize",
        json={"field": F("model", "Dados/Tipo"), "mode": "rainbow"},
        headers=ctx["h"][Role.LEITURA],
    )
    assert r.status_code == 422
    assert (
        await client.post(f"{ctx['url']}/colorize", json={"field": F("system", "category")})
    ).status_code == 401
