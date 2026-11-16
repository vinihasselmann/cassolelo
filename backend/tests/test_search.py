"""5.1 · GET /api/versions/{id}/marks/search e /marks/facets (modelo de teste `validacao`).

Peças com marca: PP001 = 10, 11 (TÉRREO; tipos 40x40 e 40x50), PP002 = 12, 13
(1º PAVIMENTO; 30x30), V-01 = 20 (TÉRREO), 21 (1º PAVIMENTO). Sem marca: 30.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.aps.client import ApsClient
from app.models import Mark, ModelVersion, Obra, Orphan, ParamDef, ParamValue, User
from app.models.enums import Role
from app.services.processing import ProcessingConfig, process_version
from app.services.search import FIRST_VERSION_NOTE
from tests.apsfakes import Sleeps, mock_model, mock_token
from tests.conftest import as_user, include_params

CONFIG = ProcessingConfig(
    mark_names=["Marca", "Mark"],
    category_names=["Category"],
    level_names=["Nível base"],
    search_names=["Tipo"],
)


async def _version(
    session: AsyncSession, aps: ApsClient, sleeps: Sleeps, obra: Obra, n: int, fmt: str
) -> ModelVersion:
    urn = f"dXJu{fmt}{n}"
    mock_model(fmt, urn)
    v = ModelVersion(obra_id=obra.id, acc_version_id=f"urn:v:s:{n}", version_number=n, urn=urn)
    session.add(v)
    await session.flush()
    result = await process_version(session, aps, v.id, CONFIG, sleep=sleeps)
    assert result is not None and result.status == "ready"
    return v


@pytest.fixture
async def setup(
    session: AsyncSession, aps: ApsClient, sleeps: Sleeps, users: dict[Role, User]
) -> dict[str, Any]:
    with respx.mock:
        mock_token()
        obra = Obra(code="OB-S", name="Obra busca")
        session.add(obra)
        await session.flush()
        v1 = await _version(session, aps, sleeps, obra, 1, "validacao")
    marks = {m.code: m for m in await session.scalars(select(Mark).where(Mark.obra_id == obra.id))}
    return {"obra": obra, "v1": v1, "marks": marks, "h": as_user(users[Role.FABRICA])}


async def _search(client: httpx.AsyncClient, s: dict[str, Any], **params: Any) -> Any:
    r = await client.get(f"/api/versions/{s['v1'].id}/marks/search", params=params, headers=s["h"])
    assert r.status_code == 200, r.text
    return r.json()


def _marks(body: Any) -> list[tuple[str, list[int]]]:
    return [(m["code"], m["dbids"]) for m in body["items"]]


async def test_mark_code_returns_exactly_its_pieces(
    client: httpx.AsyncClient, setup: dict[str, Any]
) -> None:
    body = await _search(client, setup, q="PP001")
    assert _marks(body) == [("PP001", [10, 11])]
    assert body["dbids"] == [10, 11] and body["total_pieces"] == 2


async def test_free_text_is_case_insensitive_and_ordered(
    client: httpx.AsyncClient, setup: dict[str, Any]
) -> None:
    assert [m for m, _ in _marks(await _search(client, setup, q="pp00"))] == ["PP001", "PP002"]
    desc = await _search(client, setup, q="pp00", order="desc")
    assert [m for m, _ in _marks(desc)] == ["PP002", "PP001"]


async def test_free_text_matches_type_section_category_and_level(
    client: httpx.AsyncClient, setup: dict[str, Any]
) -> None:
    # seção (do Tipo): só a peça 11 é 40x50
    assert _marks(await _search(client, setup, q="40x50")) == [("PP001", [11])]
    assert _marks(await _search(client, setup, q="30x")) == [
        ("PP002", [12, 13]),
        ("V-01", [20, 21]),
    ]
    assert [m for m, _ in _marks(await _search(client, setup, q="framing"))] == ["V-01"]
    # várias palavras: todas precisam aparecer
    assert _marks(await _search(client, setup, q="viga térreo")) == [("V-01", [20])]
    # curingas do LIKE são tratados como texto
    assert (await _search(client, setup, q="%"))["total_marks"] == 0


async def test_category_and_level_filters(client: httpx.AsyncClient, setup: dict[str, Any]) -> None:
    body = await _search(client, setup, category="Structural Framing")
    assert _marks(body) == [("V-01", [20, 21])]
    body = await _search(client, setup, level="TÉRREO")
    assert _marks(body) == [("PP001", [10, 11]), ("V-01", [20])]
    body = await _search(
        client, setup, level=["TÉRREO", "1º PAVIMENTO"], category="Structural Columns"
    )
    assert [m for m, _ in _marks(body)] == ["PP001", "PP002"]


async def test_property_filter_name_equals_value(
    client: httpx.AsyncClient, setup: dict[str, Any]
) -> None:
    assert _marks(await _search(client, setup, prop="Altura=50.0 cm")) == [("PP001", [11])]
    body = await _search(client, setup, prop="nível base=TÉRREO")  # nome sem diferenciar maiúsculas
    assert _marks(body) == [("PP001", [10, 11]), ("V-01", [20])]
    assert (await _search(client, setup, prop="Inexistente=1"))["total_marks"] == 0
    both = await _search(client, setup, prop=["Altura=30.0 cm", "Comprimento=600.3 cm"])
    assert _marks(both) == [("PP002", [13])]


async def test_text_ignores_accents(client: httpx.AsyncClient, setup: dict[str, Any]) -> None:
    expected = [("PP001", [10, 11]), ("V-01", [20])]
    for q in ("terreo", "TERREO", "térreo", "TÉRREO"):
        assert _marks(await _search(client, setup, q=q)) == expected, q
    assert _marks(await _search(client, setup, q="viga terreo")) == [("V-01", [20])]
    # nome e valor da propriedade também sem acento
    assert _marks(await _search(client, setup, prop="nivel base=terreo")) == expected


async def test_property_number_without_unit(
    client: httpx.AsyncClient, setup: dict[str, Any]
) -> None:
    for value in ("50", "50,0", "50.00", "50 cm", "50cm", "50 CM"):
        assert _marks(await _search(client, setup, prop=f"Altura={value}")) == [("PP001", [11])], (
            value
        )
    for value in ("5", "500", "50 mm", "-50"):  # outro número ou outra unidade: não acha
        assert (await _search(client, setup, prop=f"Altura={value}"))["total_marks"] == 0, value
    both = await _search(client, setup, prop=["Altura=30", "Comprimento=600,3"])
    assert _marks(both) == [("PP002", [13])]
    # valor que não é "número + unidade" continua sendo texto: 40 não acha "Pilar 40x40"
    assert (await _search(client, setup, prop="Tipo=40"))["total_marks"] == 0
    assert _marks(await _search(client, setup, prop="tipo=pilar 40x50")) == [("PP001", [11])]


async def test_invalid_property_filter_is_422(
    client: httpx.AsyncClient, setup: dict[str, Any]
) -> None:
    r = await client.get(
        f"/api/versions/{setup['v1'].id}/marks/search",
        params={"prop": "semigual"},
        headers=setup["h"],
    )
    assert r.status_code == 422 and "Nome=valor" in r.json()["detail"]


async def test_missing_factory_parameter_and_text_in_parameter_values(
    session: AsyncSession, client: httpx.AsyncClient, setup: dict[str, Any]
) -> None:
    forma = ParamDef(name="Forma", type="text", scope="global")
    session.add(forma)
    await session.flush()
    await include_params(session, setup["obra"].id, forma)
    marks = setup["marks"]
    session.add_all(
        [
            ParamValue(mark_id=marks["PP001"].id, def_id=forma.id, value="F-12"),
            ParamValue(mark_id=marks["V-01"].id, def_id=forma.id, value=""),  # vazio = sem valor
        ]
    )
    await session.flush()

    body = await _search(client, setup, missing="forma")
    assert [m for m, _ in _marks(body)] == ["PP002", "V-01"]
    assert _marks(await _search(client, setup, q="f-12")) == [("PP001", [10, 11])]

    r = await client.get(
        f"/api/versions/{setup['v1'].id}/marks/search",
        params={"missing": "Pista"},
        headers=setup["h"],
    )
    assert r.status_code == 422 and r.json()["code"] == "unknown_param"
    assert r.json()["detail"] == 'Parâmetro da fábrica "Pista" não existe.'


async def test_any_factory_parameter_name_works_without_accents(
    session: AsyncSession, client: httpx.AsyncClient, setup: dict[str, Any]
) -> None:
    """Nenhum parâmetro tem nome fixo: vale o que a fábrica criar, com ou sem acento."""
    liberacao = ParamDef(name="Liberação da peça", type="text", scope="global")
    session.add(liberacao)
    await session.flush()
    await include_params(session, setup["obra"].id, liberacao)
    session.add(ParamValue(mark_id=setup["marks"]["PP002"].id, def_id=liberacao.id, value="Sim"))
    await session.flush()
    body = await _search(client, setup, missing="liberacao da peca")
    assert [m for m, _ in _marks(body)] == ["PP001", "V-01"]


async def test_missing_respects_obra_scope(
    session: AsyncSession, client: httpx.AsyncClient, setup: dict[str, Any]
) -> None:
    other = Obra(code="OB-OUTRA", name="Outra")
    session.add(other)
    await session.flush()
    session.add(ParamDef(name="Pista", type="text", scope="obra", obra_id=other.id))
    await session.flush()
    r = await client.get(
        f"/api/versions/{setup['v1'].id}/marks/search",
        params={"missing": "Pista"},
        headers=setup["h"],
    )
    assert r.status_code == 422  # parâmetro de outra obra não vale aqui
    session.add(ParamDef(name="Pista", type="text", scope="obra", obra_id=setup["obra"].id))
    await session.flush()
    assert (await _search(client, setup, missing="Pista"))["total_marks"] == 3


async def test_shortcut_new_in_version(
    session: AsyncSession,
    aps: ApsClient,
    sleeps: Sleeps,
    client: httpx.AsyncClient,
    setup: dict[str, Any],
) -> None:
    first = await _search(client, setup, shortcut="new")
    assert first["total_marks"] == 0 and first["note"] == FIRST_VERSION_NOTE

    with respx.mock:
        mock_token()
        v2 = await _version(session, aps, sleeps, setup["obra"], 2, "rvt")
    r = await client.get(
        f"/api/versions/{v2.id}/marks/search", params={"shortcut": "new"}, headers=setup["h"]
    )
    new = {m["code"] for m in r.json()["items"]}
    assert new == {"V-101", "V-102", "P-01", "LA-01"}  # nenhuma das marcas da v1


async def test_review_shortcut_lists_marks_in_review(
    session: AsyncSession, client: httpx.AsyncClient, setup: dict[str, Any]
) -> None:
    assert (await _search(client, setup, shortcut="review"))["total_marks"] == 0
    setup["marks"]["V-01"].review_status = "review"
    await session.flush()
    body = await _search(client, setup, shortcut="review")
    assert [m["code"] for m in body["items"]] == ["V-01"] and body["note"] is None


async def test_shortcut_orphans(
    session: AsyncSession, client: httpx.AsyncClient, setup: dict[str, Any]
) -> None:
    assert (await _search(client, setup, shortcut="orphans"))["total_marks"] == 0
    session.add(Orphan(mark_id=setup["marks"]["PP002"].id, since_version_id=setup["v1"].id))
    await session.flush()
    body = await _search(client, setup, shortcut="orphans")
    assert [(m["code"], m["count"], m["dbids"]) for m in body["items"]] == [("PP002", 0, [])]


async def test_pagination_keeps_full_result_for_3d(
    client: httpx.AsyncClient, setup: dict[str, Any]
) -> None:
    p1 = await _search(client, setup, page_size=2)
    assert [m for m, _ in _marks(p1)] == ["PP001", "PP002"]
    assert (p1["total_marks"], p1["page"], len(p1["mark_ids"])) == (3, 1, 3)
    assert p1["dbids"] == [10, 11, 12, 13, 20, 21]  # a peça 30 (sem marca) não entra
    p2 = await _search(client, setup, page_size=2, page=2)
    assert [m for m, _ in _marks(p2)] == ["V-01"]


async def test_facets(client: httpx.AsyncClient, setup: dict[str, Any]) -> None:
    r = await client.get(f"/api/versions/{setup['v1'].id}/marks/facets", headers=setup["h"])
    assert r.json() == {
        "categories": [
            {"value": "Structural Columns", "pieces": 4},
            {"value": "Structural Framing", "pieces": 2},
        ],
        "levels": [{"value": "1º PAVIMENTO", "pieces": 3}, {"value": "TÉRREO", "pieces": 3}],
        "pieces_without_level": 0,
    }


async def test_not_ready_and_auth(
    session: AsyncSession, client: httpx.AsyncClient, setup: dict[str, Any]
) -> None:
    v = ModelVersion(
        obra_id=setup["obra"].id, acc_version_id="urn:v:s:p", version_number=9, status="pending"
    )
    session.add(v)
    await session.flush()
    for path in ("search", "facets"):
        r = await client.get(f"/api/versions/{v.id}/marks/{path}", headers=setup["h"])
        assert r.status_code == 409
        assert (await client.get(f"/api/versions/{v.id}/marks/{path}")).status_code == 401


def test_parse_number_accepts_units_with_exponent() -> None:
    from decimal import Decimal

    from app.services.search import _parse_number

    assert _parse_number("2.504 m^3") == (Decimal("2.504"), "m^3")
    assert _parse_number("1,2 m²") == (Decimal("1.2"), "m²")
    assert _parse_number("60") == (Decimal("60"), "")
    assert _parse_number("60 cm") == (Decimal("60"), "cm")
    assert _parse_number("60x60") is None
    assert _parse_number("Pilar 40x40") is None
