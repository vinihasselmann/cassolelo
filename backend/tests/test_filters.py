"""Motor de filtros (piece_props + filters): campos, valores, operadores, e/ou, 422,
injeção de SQL, sincronização dos valores da fábrica e backfill.

Versão sintética (hoje fixo = 2026-11-13). Largura / Data Expedição / Código / Tipo:

- 10 PP001 Pilar TÉRREO: 40,0 cm / 2026-11-05 / A1 / Pilar Térreo
- 11 PP001 Pilar TÉRREO: 40.0 cm / 20261110 / 12 / Pilar Térreo
- 12 PP002 Pilar 1º PAVIMENTO: 60 cm / 2026-10-20T08:00:00 / B7 / Pilar alto
- 20 V01 Viga TÉRREO: 25.5 cm / 2026-09-30 / — / Viga 25x60
- 21 V01 Viga 1º PAVIMENTO: — / — / — / Viga 25x60
- 30 (sem marca) Junta TÉRREO: — / — / — / Junta EPS

Fábrica: "Liberação" (texto, obrigatório) = "Ok" no PP001; "Ciclo" (número) = 12 na V01;
"Expedido em" (data) = 2026-11-10 no PP002.
"""

from __future__ import annotations

import io
from datetime import date
from typing import Any

import httpx
import pytest
from openpyxl import load_workbook
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Element, Mark, ModelVersion, Obra, ParamDef, ParamValue, PieceProp, User
from app.models import VersionPropertyName as VPN
from app.models.enums import Role
from app.services import filters, piece_props
from tests.conftest import as_user, include_params

TODAY = date(2026, 11, 13)

PIECES: list[tuple[int, str | None, str, str, dict[str, Any]]] = [
    (
        10,
        "PP001",
        "Pilar",
        "TÉRREO",
        {"Largura": "40,0 cm", "Exp": "2026-11-05", "Cod": "A1", "Tipo": "Pilar Térreo"},
    ),
    (
        11,
        "PP001",
        "Pilar",
        "TÉRREO",
        {"Largura": "40.0 cm", "Exp": "20261110", "Cod": "12", "Tipo": "Pilar Térreo"},
    ),
    (
        12,
        "PP002",
        "Pilar",
        "1º PAVIMENTO",
        {"Largura": "60 cm", "Exp": "2026-10-20T08:00:00", "Cod": "B7", "Tipo": "Pilar alto"},
    ),
    (
        20,
        "V01",
        "Viga",
        "TÉRREO",
        {"Largura": "25.5 cm", "Exp": "2026-09-30", "Tipo": "Viga 25x60"},
    ),
    (21, "V01", "Viga", "1º PAVIMENTO", {"Tipo": "Viga 25x60"}),
    (30, None, "Junta", "TÉRREO", {"Tipo": "Junta EPS"}),
]


def _props(values: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"Dados": {"Tipo": values["Tipo"]}}
    if "Largura" in values:
        out["Dimensões"] = {"Largura": values["Largura"]}
    if "Exp" in values:
        out["Datas"] = {"Data Expedição": values["Exp"]}
    if "Cod" in values:
        out["Mix"] = {"Código": values["Cod"]}
    return out


@pytest.fixture
async def ctx(session: AsyncSession, users: dict[Role, User]) -> dict[str, Any]:
    return await build_ctx(session, users)


async def build_ctx(
    session: AsyncSession, users: dict[Role, User], obra_code: str = "OB-F"
) -> dict[str, Any]:
    """Obra sintética do docstring (também usada pelos testes de filtros salvos e cores)."""
    obra = Obra(code=obra_code, name="Obra filtros")
    session.add(obra)
    await session.flush()
    v = ModelVersion(obra_id=obra.id, acc_version_id="urn:f:1", version_number=1, status="ready")
    session.add(v)
    await session.flush()
    marks: dict[str, Mark] = {}
    for mark_code, cat in (("PP001", "Pilar"), ("PP002", "Pilar"), ("V01", "Viga")):
        marks[mark_code] = Mark(obra_id=obra.id, code=mark_code, category=cat)
    session.add_all(marks.values())
    await session.flush()
    for dbid, code, cat, level, values in PIECES:
        session.add(
            Element(
                version_id=v.id,
                dbid=dbid,
                external_id=f"ext-{dbid}",
                name=f"Peça {dbid}",
                category=cat,
                level=level,
                mark_id=marks[code].id if code else None,
                props=_props(values),
                member_dbids=[dbid * 100 + 1, dbid * 100 + 2],
            )
        )
    for group, name in (
        ("Dados", "Tipo"),
        ("Dimensões", "Largura"),
        ("Datas", "Data Expedição"),
        ("Mix", "Código"),
    ):
        session.add(VPN(version_id=v.id, group_name=group, prop_name=name))
    params = {
        "lib": ParamDef(name="Liberação", type="text", scope="global", required=True),
        "ciclo": ParamDef(name="Ciclo", type="number", scope="global"),
        "exp": ParamDef(name="Expedido em", type="date", scope="obra", obra_id=obra.id),
        "fora": ParamDef(name="Fora da obra", type="text", scope="global"),  # não incluído
    }
    session.add_all(params.values())
    await session.flush()
    await include_params(session, obra.id, params["lib"], params["ciclo"])
    session.add_all(
        [
            ParamValue(mark_id=marks["PP001"].id, def_id=params["lib"].id, value="Ok"),
            ParamValue(mark_id=marks["V01"].id, def_id=params["ciclo"].id, value=12),
            ParamValue(mark_id=marks["PP002"].id, def_id=params["exp"].id, value="2026-11-10"),
        ]
    )
    await session.flush()
    await piece_props.rebuild_version(session, v.id)
    return {
        "obra": obra,
        "v": v,
        "marks": marks,
        "p": params,
        "h": as_user(users[Role.LEITURA]),
        "users": users,
    }


def F(source: str, key: str) -> dict[str, str]:
    return {"source": source, "key": key}


async def _eval(
    session: AsyncSession, ctx: dict[str, Any], rules: list[dict[str, Any]], logic: str = "and"
) -> list[int]:
    definition = filters.FilterDef.model_validate(
        {"mode": "isolate", "logic": logic, "rules": rules}
    )
    result = await filters.evaluate(session, ctx["v"].id, definition, TODAY)
    return [p.dbid for p in result.pieces]


def R(field: dict[str, str], op: str, value: Any = None) -> dict[str, Any]:
    return {"field": field, "op": op, "value": value}


LARGURA = F("model", "Dimensões/Largura")
EXP = F("model", "Datas/Data Expedição")
COD = F("model", "Mix/Código")
TIPO = F("model", "Dados/Tipo")


# ----------------------------------------------------------------- tipos e campos


def test_type_inference_and_parsing() -> None:
    assert piece_props.infer_type(["40,0 cm", "60", "2.504 m^3"]) == "number"
    assert piece_props.infer_type(["2026-11-05", "20261110", "2026-10-20T08:00:00"]) == "date"
    assert piece_props.infer_type(["A1", "12"]) == "text"  # nem todos convertem
    assert piece_props.infer_type([]) == "text"
    assert piece_props.parse_number("1.234,5") is None  # milhar não é aceito
    assert piece_props.parse_date("20261340") is None  # mês inválido


async def test_fields_lists_types_sources_and_distinct_counts(
    client: httpx.AsyncClient, ctx: dict[str, Any]
) -> None:
    r = await client.get(f"/api/versions/{ctx['v'].id}/fields", headers=ctx["h"])
    assert r.status_code == 200, r.text
    by_key = {(f["source"], f["key"]): f for f in r.json()}
    assert by_key[("model", "Dimensões/Largura")]["type"] == "number"
    assert by_key[("model", "Datas/Data Expedição")]["type"] == "date"
    assert by_key[("model", "Mix/Código")]["type"] == "text"
    assert by_key[("model", "Dimensões/Largura")]["distinct_values"] == 4
    assert by_key[("model", "Dimensões/Largura")]["group"] == "Dimensões"
    lib = by_key[("factory", str(ctx["p"]["lib"].id))]
    assert (lib["name"], lib["type"], lib["pieces"]) == ("Liberação", "text", 2)
    assert by_key[("factory", str(ctx["p"]["exp"].id))]["type"] == "date"
    assert ("factory", str(ctx["p"]["fora"].id)) not in by_key  # não incluído na obra
    status = by_key[("system", "status")]
    assert (status["name"], status["distinct_values"]) == ("Status de produção", 2)
    assert by_key[("system", "first_version")]["type"] == "number"


async def test_field_values_autocomplete(client: httpx.AsyncClient, ctx: dict[str, Any]) -> None:
    url = f"/api/versions/{ctx['v'].id}/fields/model/Dados/Tipo/values"
    r = await client.get(url, params={"q": "terreo"}, headers=ctx["h"])  # sem acento
    assert r.status_code == 200, r.text
    assert r.json() == [{"value": "Pilar Térreo", "pieces": 2}]
    top = (await client.get(url, headers=ctx["h"])).json()
    assert top[0]["pieces"] == 2 and len(top) == 4
    r = await client.get(
        f"/api/versions/{ctx['v'].id}/fields/system/status/values", headers=ctx["h"]
    )
    assert {v["value"]: v["pieces"] for v in r.json()} == {"Pendente": 3, "Completa": 2}
    r = await client.get(
        f"/api/versions/{ctx['v'].id}/fields/model/Nada/X/values", headers=ctx["h"]
    )
    assert r.status_code == 422


# -------------------------------------------------------------------- operadores


@pytest.mark.parametrize(
    ("rule", "expected"),
    [
        (R(TIPO, "eq", "pilar terreo"), [10, 11]),  # sem acento e maiúsculas
        (R(TIPO, "ne", "Pilar Térreo"), [12, 20, 21, 30]),
        (R(TIPO, "contains", "25X"), [20, 21]),
        (R(TIPO, "not_contains", "pilar"), [20, 21, 30]),
        (R(TIPO, "starts_with", "vig"), [20, 21]),
        (R(COD, "empty"), [20, 21, 30]),
        (R(COD, "not_empty"), [10, 11, 12]),
        (R(TIPO, "in", ["Junta EPS", "pilar alto"]), [12, 30]),
        (R(TIPO, "contains", "%"), []),  # curinga tratado como texto
        (R(F("system", "category"), "eq", "Viga"), [20, 21]),
        (R(F("system", "mark"), "starts_with", "pp"), [10, 11, 12]),
        (R(F("system", "level"), "eq", "1º pavimento"), [12, 21]),
    ],
)
async def test_text_operators(
    session: AsyncSession, ctx: dict[str, Any], rule: dict[str, Any], expected: list[int]
) -> None:
    assert await _eval(session, ctx, [rule]) == expected


@pytest.mark.parametrize(
    ("rule", "expected"),
    [
        (R(LARGURA, "eq", 40), [10, 11]),
        (R(LARGURA, "eq", "40,0"), [10, 11]),
        (R(LARGURA, "ne", 40), [12, 20, 21, 30]),  # inclui as sem valor
        (R(LARGURA, "gt", 40), [12]),
        (R(LARGURA, "gte", 40), [10, 11, 12]),
        (R(LARGURA, "lt", "40"), [20]),
        (R(LARGURA, "lte", 40), [10, 11, 20]),
        (R(LARGURA, "between", [60, 25.5]), [10, 11, 12, 20]),  # ordem invertida
        (R(LARGURA, "empty"), [21, 30]),
        (R(LARGURA, "not_empty"), [10, 11, 12, 20]),
        (R(F("system", "first_version"), "eq", 1), [10, 11, 12, 20, 21]),
    ],
)
async def test_number_operators(
    session: AsyncSession, ctx: dict[str, Any], rule: dict[str, Any], expected: list[int]
) -> None:
    assert await _eval(session, ctx, [rule]) == expected


@pytest.mark.parametrize(
    ("rule", "expected"),
    [
        (R(EXP, "on", "2026-11-05"), [10]),
        (R(EXP, "on", "20261110"), [11]),  # AAAAMMDD
        (R(EXP, "before", "2026-10-20"), [20]),
        (R(EXP, "after", "2026-10-20"), [10, 11]),
        (R(EXP, "between", ["2026-11-30", "2026-10-01"]), [10, 11, 12]),
        (R(EXP, "this_month"), [10, 11]),  # novembro/2026
        (R(EXP, "last_month"), [12]),  # outubro/2026 (com hora)
        (R(EXP, "last_n_days", 7), [11]),  # 07 a 13/11
        (R(EXP, "last_n_days", 9), [10, 11]),  # 05 a 13/11
        (R(EXP, "empty"), [21, 30]),
        (R(EXP, "not_empty"), [10, 11, 12, 20]),
    ],
)
async def test_date_operators_with_fixed_today(
    session: AsyncSession, ctx: dict[str, Any], rule: dict[str, Any], expected: list[int]
) -> None:
    assert await _eval(session, ctx, [rule]) == expected


async def test_relative_months_across_year_boundary(
    session: AsyncSession, ctx: dict[str, Any]
) -> None:
    jan = filters.FilterDef.model_validate({"mode": "isolate", "rules": [R(EXP, "last_month")]})
    result = await filters.evaluate(session, ctx["v"].id, jan, date(2027, 1, 15))
    assert result.matched_pieces == 0  # dezembro/2026: nenhuma


async def test_factory_fields(session: AsyncSession, ctx: dict[str, Any]) -> None:
    p = ctx["p"]
    assert await _eval(session, ctx, [R(F("factory", str(p["lib"].id)), "eq", "ok")]) == [10, 11]
    assert await _eval(session, ctx, [R(F("factory", str(p["ciclo"].id)), "gte", 12)]) == [20, 21]
    assert await _eval(session, ctx, [R(F("factory", str(p["exp"].id)), "this_month")]) == [12]
    assert await _eval(session, ctx, [R(F("factory", str(p["lib"].id)), "empty")]) == [
        12,
        20,
        21,
        30,
    ]
    assert await _eval(session, ctx, [R(F("system", "status"), "eq", "Completa")]) == [10, 11]


async def test_and_or_and_no_rules(session: AsyncSession, ctx: dict[str, Any]) -> None:
    pilar = R(F("system", "category"), "eq", "Pilar")
    terreo = R(F("system", "level"), "eq", "TÉRREO")
    assert await _eval(session, ctx, [pilar, terreo], "and") == [10, 11]
    assert await _eval(session, ctx, [pilar, terreo], "or") == [10, 11, 12, 20, 30]
    assert await _eval(session, ctx, []) == [10, 11, 12, 20, 21, 30]


# ------------------------------------------------------------- API, grupos, 422


async def test_evaluate_api_groups_members_and_totals(
    client: httpx.AsyncClient, ctx: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(filters, "today", lambda _tz: TODAY)
    body = {
        "mode": "highlight",
        "logic": "or",
        "rules": [R(F("system", "level"), "eq", "TÉRREO"), R(EXP, "this_month")],
    }
    r = await client.post(
        f"/api/versions/{ctx['v'].id}/filter/evaluate", json=body, headers=ctx["h"]
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert (out["mode"], out["total_pieces"], out["matched_pieces"], out["matched_marks"]) == (
        "highlight",
        6,
        4,
        2,
    )
    assert [(g["code"], g["category"], g["matched"], g["total"]) for g in out["groups"]] == [
        ("PP001", "Pilar", 2, 2),
        ("V01", "Viga", 1, 2),  # só a peça do térreo
        (None, "Junta", 1, 1),  # peças sem marca no fim
    ]
    assert out["pieces"][0] == {"dbid": 10, "mark_id": ctx["marks"]["PP001"].id}
    assert 1001 in out["dbids"] and 10 in out["dbids"] and 2001 in out["dbids"]  # membros


@pytest.mark.parametrize(
    ("rule", "message"),
    [
        (
            R(F("model", "Nada/Inexistente"), "eq", "x"),
            'Campo "Nada/Inexistente" (model) não existe',
        ),
        (R(F("system", "cor"), "eq", "x"), 'Campo "cor" (system) não existe'),
        (R(F("factory", "999999"), "eq", "x"), "não existe nesta versão"),
        (R(LARGURA, "contains", "4"), 'o operador "contém" não vale para número'),
        (R(TIPO, "gt", 3), 'o operador ">" não vale para texto'),
        (R(LARGURA, "eq", "quarenta"), '"quarenta" não é um número'),
        (R(EXP, "on", "13/11/2026"), "não é uma data"),
        (R(EXP, "between", ["2026-01-01"]), "precisa de dois valores"),
        (R(EXP, "last_n_days", 0), "número de dias"),
        (R(TIPO, "in", []), "precisa de uma lista"),
        (R(TIPO, "eq", ""), "informe um texto"),
    ],
)
async def test_invalid_rules_are_422(
    client: httpx.AsyncClient, ctx: dict[str, Any], rule: dict[str, Any], message: str
) -> None:
    body = {"mode": "isolate", "rules": [rule]}
    r = await client.post(
        f"/api/versions/{ctx['v'].id}/filter/evaluate", json=body, headers=ctx["h"]
    )
    assert r.status_code == 422, r.text
    assert message in r.json()["detail"]


async def test_factory_param_outside_obra_is_422(
    client: httpx.AsyncClient, ctx: dict[str, Any]
) -> None:
    rule = R(F("factory", str(ctx["p"]["fora"].id)), "eq", "x")
    r = await client.post(
        f"/api/versions/{ctx['v'].id}/filter/evaluate",
        json={"mode": "isolate", "rules": [rule]},
        headers=ctx["h"],
    )
    assert r.status_code == 422


@pytest.mark.parametrize(
    "body",
    [
        {"mode": "explode", "rules": []},
        {"mode": "isolate", "logic": "xor", "rules": []},
        {
            "mode": "isolate",
            "rules": [{"field": {"source": "sql", "key": "x"}, "op": "eq", "value": 1}],
        },
        {
            "mode": "isolate",
            "rules": [{"field": {"source": "model", "key": "x"}, "op": "like", "value": 1}],
        },
        {"mode": "isolate", "rules": [], "extra": True},
    ],
)
async def test_malformed_filter_is_422(
    client: httpx.AsyncClient, ctx: dict[str, Any], body: dict[str, Any]
) -> None:
    r = await client.post(
        f"/api/versions/{ctx['v'].id}/filter/evaluate", json=body, headers=ctx["h"]
    )
    assert r.status_code == 422


async def test_sql_injection_attempts_are_inert(
    session: AsyncSession, client: httpx.AsyncClient, ctx: dict[str, Any]
) -> None:
    url = f"/api/versions/{ctx['v'].id}/filter/evaluate"
    evil = "x'); DROP TABLE piece_props; --"
    # na chave: campo inexistente (422), nada executado
    r = await client.post(
        url, json={"mode": "isolate", "rules": [R(F("model", evil), "eq", "1")]}, headers=ctx["h"]
    )
    assert r.status_code == 422
    # no valor: parâmetro ligado, só não bate
    for op in ("eq", "contains", "starts_with"):
        r = await client.post(
            url, json={"mode": "isolate", "rules": [R(TIPO, op, evil)]}, headers=ctx["h"]
        )
        assert r.status_code == 200 and r.json()["matched_pieces"] == 0
    r = await client.post(
        url,
        json={"mode": "isolate", "rules": [R(TIPO, "in", [evil, "' OR '1'='1"])]},
        headers=ctx["h"],
    )
    assert r.status_code == 200 and r.json()["matched_pieces"] == 0
    r = await client.get(
        f"/api/versions/{ctx['v'].id}/fields/model/Dados/Tipo/values",
        params={"q": "' OR 1=1 --"},
        headers=ctx["h"],
    )
    assert r.status_code == 200 and r.json() == []
    assert (await session.execute(text("SELECT count(*) FROM piece_props"))).scalar_one() > 0


async def test_requires_user_and_ready_version(
    client: httpx.AsyncClient, ctx: dict[str, Any], session: AsyncSession
) -> None:
    url = f"/api/versions/{ctx['v'].id}/filter/evaluate"
    assert (await client.post(url, json={"mode": "isolate", "rules": []})).status_code == 401
    assert (
        await client.post(
            "/api/versions/999999/filter/evaluate", json={"mode": "isolate"}, headers=ctx["h"]
        )
    ).status_code == 404
    ctx["v"].status = "processing"
    await session.flush()
    assert (await client.post(url, json={"mode": "isolate"}, headers=ctx["h"])).status_code == 409


# ------------------------------------------------- sincronização dos valores da fábrica


async def test_factory_values_stay_in_sync(
    session: AsyncSession, client: httpx.AsyncClient, ctx: dict[str, Any]
) -> None:
    obra, marks, p = ctx["obra"], ctx["marks"], ctx["p"]
    fab = as_user(ctx["users"][Role.FABRICA])
    lib = F("factory", str(p["lib"].id))

    # salvar numa marca
    r = await client.put(
        f"/api/obras/{obra.id}/marks/{marks['V01'].id}/values",
        json={"changes": [{"def_id": p["lib"].id, "value": "Ok"}]},
        headers=fab,
    )
    assert r.status_code == 200, r.text
    assert await _eval(session, ctx, [R(lib, "eq", "ok")]) == [10, 11, 20, 21]

    # lote
    r = await client.post(
        f"/api/obras/{obra.id}/marks/batch-apply",
        json={"mark_ids": [marks["PP002"].id], "changes": {str(p["lib"].id): "Bloqueado"}},
        headers=fab,
    )
    assert r.status_code == 200, r.text
    assert await _eval(session, ctx, [R(lib, "eq", "bloqueado")]) == [12]

    # desfazer o lote
    r = await client.post(f"/api/batches/{r.json()['batch_id']}/undo", headers=fab)
    assert r.status_code == 200, r.text
    assert await _eval(session, ctx, [R(lib, "eq", "bloqueado")]) == []

    # retirar o parâmetro da obra: some do filtro (campo deixa de existir)
    r = await client.delete(f"/api/obras/{obra.id}/params/{p['lib'].id}", headers=fab)
    assert r.status_code == 200
    rows = await session.scalar(
        select(func.count())
        .select_from(PieceProp)
        .where(PieceProp.source == "factory", PieceProp.key == str(p["lib"].id))
    )
    assert rows == 0


# --------------------------------------------------------- processamento e backfill


async def test_backfill_command_rebuilds_rows(session: AsyncSession, ctx: dict[str, Any]) -> None:
    from app.aps.client import ApsClient
    from app.cli import run as cli_run
    from tests.conftest import make_settings

    await session.execute(delete(PieceProp).where(PieceProp.version_id == ctx["v"].id))
    await session.execute(update(VPN).values(value_type=None))
    code = await cli_run(
        ["piece-props", "backfill", "--version", str(ctx["v"].id)],
        make_settings(),
        session,
        ApsClient.__new__(ApsClient),
        None,
    )
    assert code == 0
    assert await _eval(session, ctx, [R(LARGURA, "eq", 40)]) == [10, 11]
    vtype = await session.scalar(select(VPN.value_type).where(VPN.prop_name == "Largura"))
    assert vtype == "number"


async def test_process_version_builds_piece_props(
    session: AsyncSession, aps: Any, sleeps: Any
) -> None:
    """Pelo caminho real: process_version (modelo de teste "validacao") monta o motor."""
    import respx

    from app.services.processing import ProcessingConfig, process_version
    from tests.apsfakes import mock_model, mock_token

    obra = Obra(code="OB-PROC", name="Processamento")
    session.add(obra)
    await session.flush()
    v = ModelVersion(
        obra_id=obra.id, acc_version_id="urn:f:proc", version_number=1, urn="dXJuUFJPQw"
    )
    session.add(v)
    await session.flush()
    config = ProcessingConfig(
        mark_names=["Marca"], category_names=["Category"], level_names=["Nível base"]
    )
    with respx.mock:
        mock_token()
        mock_model("validacao", "dXJuUFJPQw")
        result = await process_version(session, aps, v.id, config, sleep=sleeps)
    assert result is not None and result.status == "ready"

    fields = {(f.source, f.key): f for f in await filters.list_fields(session, v.id)}
    assert fields[("model", "Dimensões/Altura")].type == "number"
    assert fields[("system", "status")].pieces > 0  # sincronizado no fim do processamento
    definition = filters.FilterDef.model_validate(
        {"mode": "isolate", "rules": [R(F("model", "Dimensões/Altura"), "eq", 50)]}
    )
    out = await filters.evaluate(session, v.id, definition, TODAY)
    assert [p.dbid for p in out.pieces] == [11]
    assert [(g.code, g.matched, g.total) for g in out.groups] == [("PP001", 1, 2)]


# ------------------------------------------- F3: modo por regra, texto livre, 3D


async def _run(
    session: AsyncSession,
    ctx: dict[str, Any],
    rules: list[dict[str, Any]],
    q: str = "",
    logic: str = "and",
) -> filters.Evaluation:
    definition = filters.FilterDef.model_validate(
        {"mode": "isolate", "logic": logic, "rules": rules, "q": q}
    )
    return await filters.evaluate(session, ctx["v"].id, definition, TODAY)


def M(mode: str, rule: dict[str, Any]) -> dict[str, Any]:
    return {**rule, "mode": mode}


async def test_modes_per_rule_combine_like_dalux(
    session: AsyncSession, ctx: dict[str, Any]
) -> None:
    terreo = R(F("system", "level"), "eq", "TÉRREO")
    viga = R(F("system", "category"), "eq", "Viga")
    ok = R(F("factory", str(ctx["p"]["lib"].id)), "eq", "Ok")

    # Isolar térreo, menos as vigas: o resultado é o que fica à vista
    r = await _run(session, ctx, [M("isolate", terreo), M("hide", viga)])
    assert [p.dbid for p in r.pieces] == [10, 11, 30]
    assert (r.view, r.hidden_dbids) == ("isolate", [])

    # Só Ocultar: tudo menos as vigas
    r = await _run(session, ctx, [M("hide", viga)])
    assert [p.dbid for p in r.pieces] == [10, 11, 12, 30]

    # Ocultar é sempre "qualquer regra", mesmo com E
    pilar = R(F("system", "category"), "eq", "Pilar")
    r = await _run(session, ctx, [M("hide", viga), M("hide", pilar)])
    assert [p.dbid for p in r.pieces] == [30]

    # Destacar dentro das visíveis: o resto visível esmaece, o que não é visível some
    r = await _run(session, ctx, [M("isolate", terreo), M("hide", viga), M("highlight", ok)])
    assert [p.dbid for p in r.pieces] == [10, 11]
    assert r.view == "highlight"
    assert r.hidden_dbids == [12, 20, 21, 1201, 1202, 2001, 2002, 2101, 2102]

    # Só Destacar: nada oculto
    r = await _run(session, ctx, [M("highlight", ok)])
    assert ([p.dbid for p in r.pieces], r.view, r.hidden_dbids) == ([10, 11], "highlight", [])

    # OU vale dentro de Isolar e de Destacar
    um = R(F("system", "level"), "eq", "1º PAVIMENTO")
    r = await _run(session, ctx, [M("isolate", viga), M("isolate", um)], logic="or")
    assert [p.dbid for p in r.pieces] == [12, 20, 21]


async def test_rule_without_mode_uses_the_filter_mode(
    session: AsyncSession, ctx: dict[str, Any]
) -> None:
    viga = R(F("system", "category"), "eq", "Viga")
    definition = filters.FilterDef.model_validate({"mode": "hide", "rules": [viga]})
    r = await filters.evaluate(session, ctx["v"].id, definition, TODAY)
    assert [p.dbid for p in r.pieces] == [10, 11, 12, 30]


async def test_free_text_search_narrows_and_highlights(
    session: AsyncSession, ctx: dict[str, Any]
) -> None:
    async def dbids(q: str, rules: list[dict[str, Any]] | None = None) -> list[int]:
        return [p.dbid for p in (await _run(session, ctx, rules or [], q)).pieces]

    assert await dbids("pp001") == [10, 11]  # código da marca
    assert await dbids("junta") == [30]  # categoria (peça sem marca também)
    assert await dbids("ok") == [10, 11]  # valor de parâmetro da fábrica
    assert await dbids("viga xyz") == []  # cada palavra precisa aparecer
    assert await dbids("viga 01") == [20, 21]
    assert await dbids("50%") == []  # curinga tratado como texto

    terreo = R(F("system", "level"), "eq", "TÉRREO")
    r = await _run(session, ctx, [M("isolate", terreo)], "viga")
    assert [p.dbid for p in r.pieces] == [20]
    assert r.view == "highlight"  # o texto destaca: o térreo fica esmaecido
    assert r.hidden_dbids == [12, 21, 1201, 1202, 2101, 2102]


async def test_evaluate_api_accepts_text_and_returns_view(
    client: httpx.AsyncClient, ctx: dict[str, Any]
) -> None:
    body = {
        "mode": "isolate",
        "q": "PP",
        "rules": [M("hide", R(F("system", "mark"), "eq", "PP002"))],
    }
    r = await client.post(
        f"/api/versions/{ctx['v'].id}/filter/evaluate", json=body, headers=ctx["h"]
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert [p["dbid"] for p in out["pieces"]] == [10, 11]
    assert out["view"] == "highlight"
    assert 12 in out["hidden_dbids"] and 10 not in out["hidden_dbids"]
    bad = {**body, "rules": [M("sumir", R(F("system", "mark"), "eq", "PP002"))]}
    r = await client.post(
        f"/api/versions/{ctx['v'].id}/filter/evaluate", json=bad, headers=ctx["h"]
    )
    assert r.status_code == 422


async def test_saved_filter_keeps_rule_modes(
    client: httpx.AsyncClient, ctx: dict[str, Any]
) -> None:
    definition = {
        "mode": "isolate",
        "logic": "and",
        "q": "pp",
        "rules": [M("hide", R(F("system", "category"), "eq", "Viga"))],
    }
    h = as_user(ctx["users"][Role.FABRICA])
    r = await client.post(
        "/api/saved-filters",
        json={"name": "Sem vigas", "obra_id": ctx["obra"].id, "definition": definition},
        headers=h,
    )
    assert r.status_code == 201, r.text
    saved = r.json()["definition"]
    assert (saved["rules"][0]["mode"], saved["q"]) == ("hide", "pp")


async def test_filtered_export_uses_the_screen_filter(
    client: httpx.AsyncClient, ctx: dict[str, Any]
) -> None:
    body = {
        "version_id": ctx["v"].id,
        "filter": {"mode": "isolate", "rules": [R(F("system", "category"), "eq", "Pilar")]},
    }
    url = f"/api/obras/{ctx['obra'].id}/export.xlsx"
    r = await client.post(url, json=body, headers=ctx["h"])
    assert r.status_code == 200, r.text
    assert (r.headers["X-Export-Marks"], r.headers["X-Export-Pieces"]) == ("2", "3")
    about = load_workbook(io.BytesIO(r.content))["Sobre"]
    assert about["B3"].value == "Categoria é igual a Pilar"
    body = {"version_id": ctx["v"].id, "filter": {"mode": "isolate", "q": "v01"}}
    r = await client.post(url, json=body, headers=ctx["h"])
    assert (r.headers["X-Export-Marks"], r.headers["X-Export-Pieces"]) == ("1", "2")
    assert load_workbook(io.BytesIO(r.content))["Sobre"]["B3"].value == 'texto "v01"'


async def test_me_says_if_the_role_can_share_filters(
    client: httpx.AsyncClient, ctx: dict[str, Any]
) -> None:
    users = ctx["users"]
    r = await client.get("/api/me", headers=as_user(users[Role.FABRICA]))
    assert r.json()["can_share_filters"] is True
    r = await client.get("/api/me", headers=as_user(users[Role.LEITURA]))
    assert r.json()["can_share_filters"] is False
