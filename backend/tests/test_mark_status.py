"""6.4 · Status por marca, progresso por obrigatório, valores por parâmetro e atalhos."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Mark, Obra, ParamDef, ParamValue, User
from app.models.enums import Role
from app.services.mark_status import MarkStatus, status_of
from tests.conftest import as_user, include_params
from tests.factories import ready_version

# --------------------------------------------------------------------------- regra pura


def _p(i: int, required: bool = False, cats: list[str] | None = None) -> ParamDef:
    return ParamDef(id=i, name=f"P{i}", type="text", required=required, categories=cats)


def test_without_params_is_pending() -> None:
    assert status_of([], "Pilar", set()) is MarkStatus.PENDING


def test_required_params_define_the_status() -> None:
    params = [_p(1, True), _p(2, True), _p(3)]
    assert status_of(params, "Pilar", set()) is MarkStatus.PENDING
    assert status_of(params, "Pilar", {3}) is MarkStatus.PENDING  # opcional não conta
    assert status_of(params, "Pilar", {1}) is MarkStatus.PARTIAL
    assert status_of(params, "Pilar", {1, 2}) is MarkStatus.COMPLETE


def test_without_required_any_applicable_param_counts() -> None:
    params = [_p(1), _p(2), _p(3, cats=["Viga"])]
    assert status_of(params, "Pilar", {1}) is MarkStatus.PARTIAL
    assert status_of(params, "Pilar", {1, 2}) is MarkStatus.COMPLETE  # P3 não vale p/ Pilar


def test_required_of_other_category_does_not_apply() -> None:
    params = [_p(1, True, cats=["Viga"]), _p(2)]
    assert status_of(params, "Pilar", {2}) is MarkStatus.COMPLETE
    assert status_of(params, "Viga", {2}) is MarkStatus.PENDING


# --------------------------------------------------------------------------- API


@pytest.fixture
async def ctx(session: AsyncSession, users: dict[Role, User]) -> dict[str, Any]:
    obra = Obra(code="OB-ST", name="Obra status")
    other = Obra(code="OB-ST2", name="Outra")
    session.add_all([obra, other])
    await session.flush()
    version, marks = await ready_version(
        session,
        obra,
        [("P1", "Pilar", 4), ("P2", "Pilar", 2), ("P3", "Pilar", 1), ("V1", "Viga", 3)],
        unmarked=2,
    )
    d = {
        "forma": ParamDef(
            name="Tipo de forma",
            type="list",
            options=["F-11", "F-12"],
            required=True,
            categories=["Pilar"],
            scope="global",
        ),
        "data": ParamDef(name="Data", type="date", required=True, scope="obra", obra_id=obra.id),
        "obs": ParamDef(name="Obs", type="text", scope="global"),
        "alheio": ParamDef(
            name="Alheio", type="text", required=True, scope="obra", obra_id=other.id
        ),
        "inativo": ParamDef(name="Excluído", type="text", required=True, active=False),
    }
    for p in d.values():
        p.scope = p.scope or "global"
    session.add_all(d.values())
    await session.flush()
    await include_params(session, obra.id, *d.values())
    return {"v": version, "m": marks, "d": d, "h": as_user(users[Role.LEITURA])}


async def _fill(session: AsyncSession, mark: Mark, param: ParamDef, value: Any) -> None:
    session.add(ParamValue(mark_id=mark.id, def_id=param.id, value=value))
    await session.flush()


async def _status(client: httpx.AsyncClient, ctx: dict[str, Any]) -> dict[str, Any]:
    r = await client.get(f"/api/versions/{ctx['v'].id}/marks/status", headers=ctx["h"])
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    return body


async def test_status_per_mark_and_counts(
    client: httpx.AsyncClient, session: AsyncSession, ctx: dict[str, Any]
) -> None:
    m, d = ctx["m"], ctx["d"]
    await _fill(session, m["P1"], d["forma"], "F-11")
    await _fill(session, m["P1"], d["data"], "2026-12-01")
    await _fill(session, m["P2"], d["forma"], "F-12")
    await _fill(session, m["P3"], d["obs"], "só opcional")
    await _fill(session, m["V1"], d["data"], "2026-12-02")
    await _fill(session, m["P3"], d["forma"], None)  # linha apagada não conta
    body = await _status(client, ctx)
    by_id = {i["mark_id"]: i["status"] for i in body["items"]}
    assert by_id == {
        m["P1"].id: "complete",
        m["P2"].id: "partial",
        m["P3"].id: "pending",
        m["V1"].id: "complete",  # "Tipo de forma" é só de Pilar
    }
    assert body["counts"] == [
        {"status": "pending", "marks": 1, "pieces": 1},
        {"status": "partial", "marks": 1, "pieces": 2},
        {"status": "complete", "marks": 2, "pieces": 7},
        {"status": "review", "marks": 0, "pieces": 0},
    ]


async def test_progress_per_required_param(
    client: httpx.AsyncClient, session: AsyncSession, ctx: dict[str, Any]
) -> None:
    m, d = ctx["m"], ctx["d"]
    await _fill(session, m["P1"], d["forma"], "F-11")
    await _fill(session, m["V1"], d["data"], "2026-12-02")
    r = await client.get(f"/api/versions/{ctx['v'].id}/progress", headers=ctx["h"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["marks"], body["pieces"]) == (4, 10)  # peças sem Marca não entram
    assert [(p["name"], p["marks_filled"], p["marks_total"]) for p in body["required"]] == [
        ("Data", 1, 4),
        ("Tipo de forma", 1, 3),
    ]
    forma = body["required"][1]
    assert (forma["pieces_filled"], forma["pieces_total"]) == (4, 7)


async def test_param_values_for_coloring(
    client: httpx.AsyncClient, session: AsyncSession, ctx: dict[str, Any]
) -> None:
    m, d = ctx["m"], ctx["d"]
    await _fill(session, m["P2"], d["forma"], "F-12")
    r = await client.get(
        f"/api/versions/{ctx['v'].id}/params/{d['forma'].id}/values", headers=ctx["h"]
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["name"], body["type"], body["options"]) == (
        "Tipo de forma",
        "list",
        ["F-11", "F-12"],
    )
    assert {i["mark_id"]: i["value"] for i in body["items"]} == {
        m["P1"].id: None,
        m["P2"].id: "F-12",
        m["P3"].id: None,
    }  # a viga não entra: o parâmetro não se aplica
    for key in ("alheio", "inativo"):
        r = await client.get(
            f"/api/versions/{ctx['v'].id}/params/{d[key].id}/values", headers=ctx["h"]
        )
        assert r.status_code == 404


async def test_pending_and_partial_shortcuts(
    client: httpx.AsyncClient, session: AsyncSession, ctx: dict[str, Any]
) -> None:
    m, d = ctx["m"], ctx["d"]
    await _fill(session, m["P1"], d["forma"], "F-11")
    await _fill(session, m["P1"], d["data"], "2026-12-01")
    await _fill(session, m["P2"], d["forma"], "F-12")

    async def codes(shortcut: str) -> list[str]:
        r = await client.get(
            f"/api/versions/{ctx['v'].id}/marks/search",
            params={"shortcut": shortcut},
            headers=ctx["h"],
        )
        assert r.status_code == 200, r.text
        return [i["code"] for i in r.json()["items"]]

    assert await codes("pending") == ["P3", "V1"]
    assert await codes("partial") == ["P2"]
    # combina com os outros filtros
    r = await client.get(
        f"/api/versions/{ctx['v'].id}/marks/search",
        params={"shortcut": "pending", "category": "Viga"},
        headers=ctx["h"],
    )
    assert [i["code"] for i in r.json()["items"]] == ["V1"]
