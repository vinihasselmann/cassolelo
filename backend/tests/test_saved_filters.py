"""Filtros salvos (/api/saved-filters) e os antigos atalhos da busca como filtros de
sistema: permissões, nomes únicos, auditoria, validação e equivalência com a busca.

Obra sintética de test_filters.py (v1) + uma v2 para "nova", "órfã" e "a revisar":
- v2: PP001 (10), V01 (20) e PP003 (40, nova); PP002 vira órfã (aberta);
- "Ciclo" passa a obrigatório: PP001 (só Liberação) e V01 (só Ciclo) ficam Parciais,
  PP002 e PP003 Pendentes; V01 é marcada "a revisar" no teste de equivalência.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, Element, Mark, ModelVersion, Orphan, SavedFilter, User
from app.models.enums import Role
from app.services import piece_props
from app.services.saved_filters import SYSTEM_FILTERS
from tests.conftest import as_user, build_app
from tests.test_filters import build_ctx

URL = "/api/saved-filters"
SHORTCUTS = ["pending", "partial", "review", "new", "orphans"]


def definition(*rules: dict[str, Any], logic: str = "and") -> dict[str, Any]:
    return {"mode": "isolate", "logic": logic, "rules": list(rules)}


CAT_PILAR = {"field": {"source": "system", "key": "category"}, "op": "eq", "value": "Pilar"}


@pytest.fixture
async def ctx(session: AsyncSession, users: dict[Role, User]) -> dict[str, Any]:
    c = await build_ctx(session, users)
    c["h"] = {role: as_user(u) for role, u in users.items()}
    return c


async def _v2(session: AsyncSession, c: dict[str, Any]) -> ModelVersion:
    obra, marks = c["obra"], c["marks"]
    marks["PP003"] = Mark(obra_id=obra.id, code="PP003", category="Pilar")
    session.add(marks["PP003"])
    v2 = ModelVersion(obra_id=obra.id, acc_version_id="urn:f:2", version_number=2, status="ready")
    session.add(v2)
    await session.flush()
    for dbid, code, cat in ((10, "PP001", "Pilar"), (20, "V01", "Viga"), (40, "PP003", "Pilar")):
        session.add(
            Element(
                version_id=v2.id,
                dbid=dbid,
                external_id=f"ext-{dbid}",
                name=f"Peça {dbid}",
                category=cat,
                level="TÉRREO",
                mark_id=marks[code].id,
                props={},
                member_dbids=[dbid * 100 + 1],
            )
        )
    session.add(Orphan(mark_id=marks["PP002"].id, since_version_id=v2.id, status="open"))
    c["p"]["ciclo"].required = True
    marks["V01"].review_status = "review"
    await session.flush()
    await piece_props.rebuild_version(session, v2.id)
    return v2


# -------------------------------------------------------------- filtros de sistema


async def test_system_filters_seeded_like_the_code(session: AsyncSession) -> None:
    rows = {
        f.system_key: f
        for f in await session.scalars(
            select(SavedFilter).where(SavedFilter.system_key.is_not(None))
        )
    }
    assert set(rows) == set(SYSTEM_FILTERS)
    for key, (name, definition_) in SYSTEM_FILTERS.items():
        assert (rows[key].name, rows[key].scope, rows[key].obra_id) == (name, "shared", None)
        assert rows[key].definition == definition_


async def test_system_filters_listed_first_and_not_editable(
    client: httpx.AsyncClient, ctx: dict[str, Any]
) -> None:
    admin = ctx["h"][Role.ADMIN]
    created = await client.post(
        URL, json={"name": "Aaa", "scope": "shared", "definition": definition()}, headers=admin
    )
    assert created.status_code == 201, created.text
    items = (await client.get(URL, headers=admin)).json()
    assert [i["system_key"] for i in items[:5]] == SHORTCUTS
    assert items[5]["name"] == "Aaa" and items[5]["editable"] is True
    assert all(i["editable"] is False for i in items[:5])
    for i in items[:5]:
        r = await client.patch(f"{URL}/{i['id']}", json={"name": "X"}, headers=admin)
        assert r.status_code == 403, r.text
        assert (await client.delete(f"{URL}/{i['id']}", headers=admin)).status_code == 403


async def test_shortcuts_equal_system_filters(
    client: httpx.AsyncClient, session: AsyncSession, ctx: dict[str, Any]
) -> None:
    """A busca com atalho e o motor com o filtro de sistema dão as mesmas marcas e peças."""
    v2 = await _v2(session, ctx)
    h = ctx["h"][Role.LEITURA]
    systems = {i["system_key"]: i for i in (await client.get(URL, headers=h)).json()}
    expected = {
        "pending": [("PP003", 1)],
        "partial": [("PP001", 1)],
        "review": [("V01", 1)],
        "new": [("PP003", 1)],
        "orphans": [("PP002", 0)],
    }
    for key in SHORTCUTS:
        r = await client.get(
            f"/api/versions/{v2.id}/marks/search", params={"shortcut": key}, headers=h
        )
        assert r.status_code == 200, r.text
        searched = [(m["code"], m["count"]) for m in r.json()["items"]]
        ev = await client.post(
            f"/api/versions/{v2.id}/filter/evaluate", json=systems[key]["definition"], headers=h
        )
        assert ev.status_code == 200, ev.text
        evaluated = [(g["code"], g["matched"]) for g in ev.json()["groups"] if g["mark_id"]]
        assert searched == evaluated == expected[key], key

    # órfãs: só o texto livre (marca ou categoria) filtra; os outros filtros não se aplicam
    async def orphans(**params: Any) -> list[str]:
        r = await client.get(
            f"/api/versions/{v2.id}/marks/search",
            params={"shortcut": "orphans", **params},
            headers=h,
        )
        return [m["code"] for m in r.json()["items"]]

    assert await orphans(q="pp00") == ["PP002"]
    assert await orphans(q="pilar") == ["PP002"]
    assert await orphans(q="viga") == []


async def test_new_on_first_version_has_note(
    client: httpx.AsyncClient, ctx: dict[str, Any]
) -> None:
    h = ctx["h"][Role.LEITURA]
    r = await client.get(
        f"/api/versions/{ctx['v'].id}/marks/search", params={"shortcut": "new"}, headers=h
    )
    body = r.json()
    assert body["items"] == [] and body["note"].startswith("Primeira versão")
    new = {"field": {"source": "system", "key": "new"}, "op": "eq", "value": True}
    ev = await client.post(
        f"/api/versions/{ctx['v'].id}/filter/evaluate", json=definition(new), headers=h
    )
    assert ev.json()["matched_pieces"] == 0 and ev.json()["notes"] == [body["note"]]


async def test_computed_fields_listed_and_validated(
    client: httpx.AsyncClient, ctx: dict[str, Any]
) -> None:
    h = ctx["h"][Role.LEITURA]
    fields = (await client.get(f"/api/versions/{ctx['v'].id}/fields", headers=h)).json()
    by_key = {(f["source"], f["key"]): f for f in fields}
    assert by_key[("system", "new")]["type"] == "bool"
    assert by_key[("system", "orphan")]["name"] == "Órfã"
    bad = {"field": {"source": "system", "key": "new"}, "op": "eq", "value": "sim"}
    r = await client.post(
        f"/api/versions/{ctx['v'].id}/filter/evaluate", json=definition(bad), headers=h
    )
    assert r.status_code == 422 and "true" in r.json()["detail"]
    bad["op"] = "contains"
    r = await client.post(
        f"/api/versions/{ctx['v'].id}/filter/evaluate", json=definition(bad), headers=h
    )
    assert r.status_code == 422 and "sim/não" in r.json()["detail"]


# ------------------------------------------------------------------- permissões


async def test_personal_filters_only_owner_sees_and_edits(
    client: httpx.AsyncClient, ctx: dict[str, Any]
) -> None:
    owner, admin = ctx["h"][Role.LEITURA], ctx["h"][Role.ADMIN]
    r = await client.post(
        URL, json={"name": "Meus pilares", "definition": definition(CAT_PILAR)}, headers=owner
    )
    assert r.status_code == 201, r.text
    item = r.json()
    assert (item["scope"], item["editable"]) == ("personal", True)
    fid = item["id"]
    # nem o admin vê os pessoais dos outros
    assert fid not in [i["id"] for i in (await client.get(URL, headers=admin)).json()]
    assert (await client.get(f"{URL}/{fid}", headers=admin)).status_code == 404
    patch = await client.patch(f"{URL}/{fid}", json={"name": "X"}, headers=admin)
    assert patch.status_code == 404
    assert (await client.delete(f"{URL}/{fid}", headers=admin)).status_code == 404
    # o dono edita e exclui
    r = await client.patch(f"{URL}/{fid}", json={"name": "Pilares (meus)"}, headers=owner)
    assert r.status_code == 200 and r.json()["name"] == "Pilares (meus)"
    assert (await client.delete(f"{URL}/{fid}", headers=owner)).status_code == 204
    assert (await client.get(f"{URL}/{fid}", headers=owner)).status_code == 404


@pytest.mark.parametrize(
    ("role", "allowed"),
    [(Role.FABRICA, True), (Role.ADMIN, True), (Role.PROJETOS, False), (Role.LEITURA, False)],
)
async def test_shared_filters_need_role(
    client: httpx.AsyncClient, ctx: dict[str, Any], role: Role, allowed: bool
) -> None:
    h = ctx["h"][role]
    body = {"name": f"Comp {role.value}", "scope": "shared", "definition": definition()}
    r = await client.post(URL, json=body, headers=h)
    assert r.status_code == (201 if allowed else 403), r.text
    # um compartilhado criado pela fábrica: todos veem; só os papéis permitidos editam
    shared = await client.post(
        URL,
        json={"name": f"Da fábrica {role.value}", "scope": "shared", "definition": definition()},
        headers=ctx["h"][Role.FABRICA],
    )
    fid = shared.json()["id"]
    listed = {i["id"]: i for i in (await client.get(URL, headers=h)).json()}
    assert listed[fid]["editable"] is allowed
    r = await client.patch(f"{URL}/{fid}", json={"name": f"Novo {role.value}"}, headers=h)
    assert r.status_code == (200 if allowed else 403), r.text
    # pessoal → compartilhado também exige o papel
    mine = await client.post(
        URL, json={"name": f"Meu {role.value}", "definition": definition()}, headers=h
    )
    r = await client.patch(f"{URL}/{mine.json()['id']}", json={"scope": "shared"}, headers=h)
    assert r.status_code == (200 if allowed else 403), r.text


async def test_shared_roles_are_configurable(session: AsyncSession, ctx: dict[str, Any]) -> None:
    app = build_app(session, shared_filter_roles="admin")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        body = {"name": "Só admin", "scope": "shared", "definition": definition()}
        assert (await c.post(URL, json=body, headers=ctx["h"][Role.FABRICA])).status_code == 403
        assert (await c.post(URL, json=body, headers=ctx["h"][Role.ADMIN])).status_code == 201


async def test_requires_user(client: httpx.AsyncClient) -> None:
    assert (await client.get(URL)).status_code == 401


# ------------------------------------------------------------- nomes e validação


async def test_names_unique_per_scope(client: httpx.AsyncClient, ctx: dict[str, Any]) -> None:
    fab, lei, adm = ctx["h"][Role.FABRICA], ctx["h"][Role.LEITURA], ctx["h"][Role.ADMIN]
    shared = {"name": "Pilares", "scope": "shared", "definition": definition()}
    assert (await client.post(URL, json=shared, headers=fab)).status_code == 201
    dup = {**shared, "name": "  PILARES "}  # sem diferenciar maiúsculas e espaços
    r = await client.post(URL, json=dup, headers=adm)
    assert r.status_code == 409 and "compartilhado" in r.json()["detail"]
    # pessoal com o mesmo nome de um compartilhado: pode; dois usuários: pode
    personal = {"name": "Pilares", "definition": definition()}
    assert (await client.post(URL, json=personal, headers=lei)).status_code == 201
    assert (await client.post(URL, json=personal, headers=fab)).status_code == 201
    r = await client.post(URL, json={**personal, "name": "pilares"}, headers=lei)
    assert r.status_code == 409
    # filtro de sistema também ocupa o nome entre os compartilhados
    r = await client.post(URL, json={**shared, "name": "Pendentes"}, headers=fab)
    assert r.status_code == 409


async def test_definition_and_obra_are_validated(
    client: httpx.AsyncClient, ctx: dict[str, Any]
) -> None:
    h = ctx["h"][Role.FABRICA]
    bad = [
        {"name": "x", "definition": {"mode": "explode", "rules": []}},
        {"name": "x", "definition": {**definition(), "sql": "DROP TABLE marks"}},
        {"name": "x", "definition": definition({"field": {"source": "x", "key": "y"}, "op": "eq"})},
        {"name": "", "definition": definition()},
        {"name": "x", "scope": "public", "definition": definition()},
        {"name": "x", "definition": definition(), "extra": 1},
    ]
    for body in bad:
        assert (await client.post(URL, json=body, headers=h)).status_code == 422, body
    r = await client.post(
        URL, json={"name": "x", "obra_id": 999999, "definition": definition()}, headers=h
    )
    assert r.status_code == 422 and "Obra" in r.json()["detail"]


async def test_list_by_obra(
    client: httpx.AsyncClient, session: AsyncSession, ctx: dict[str, Any]
) -> None:
    from app.models import Obra

    other = Obra(code="OB-OUTRA", name="Outra")
    session.add(other)
    await session.flush()
    h = ctx["h"][Role.FABRICA]
    for name, obra_id in (("Todas", None), ("Desta", ctx["obra"].id), ("Da outra", other.id)):
        r = await client.post(
            URL, json={"name": name, "obra_id": obra_id, "definition": definition()}, headers=h
        )
        assert r.status_code == 201, r.text
    names = [
        i["name"]
        for i in (await client.get(URL, params={"obra_id": ctx["obra"].id}, headers=h)).json()
    ]
    assert "Todas" in names and "Desta" in names and "Da outra" not in names
    all_names = [i["name"] for i in (await client.get(URL, headers=h)).json()]
    assert {"Todas", "Desta", "Da outra"} <= set(all_names)


async def test_saved_definition_is_usable_in_evaluate(
    client: httpx.AsyncClient, ctx: dict[str, Any]
) -> None:
    h = ctx["h"][Role.LEITURA]
    r = await client.post(
        URL, json={"name": "Pilares", "definition": definition(CAT_PILAR)}, headers=h
    )
    saved = (await client.get(f"{URL}/{r.json()['id']}", headers=h)).json()
    ev = await client.post(
        f"/api/versions/{ctx['v'].id}/filter/evaluate", json=saved["definition"], headers=h
    )
    assert [p["dbid"] for p in ev.json()["pieces"]] == [10, 11, 12]


# --------------------------------------------------------------------- auditoria


async def test_audit_only_for_shared(
    client: httpx.AsyncClient, session: AsyncSession, ctx: dict[str, Any]
) -> None:
    h = ctx["h"][Role.FABRICA]
    personal = await client.post(
        URL, json={"name": "Pessoal", "definition": definition()}, headers=h
    )
    shared = await client.post(
        URL, json={"name": "Comp", "scope": "shared", "definition": definition()}, headers=h
    )
    sid = shared.json()["id"]
    await client.patch(f"{URL}/{sid}", json={"definition": definition(CAT_PILAR)}, headers=h)
    await client.delete(f"{URL}/{sid}", headers=h)
    await client.patch(f"{URL}/{personal.json()['id']}", json={"name": "P2"}, headers=h)

    rows = list(
        await session.scalars(
            select(AuditLog).where(AuditLog.entity == "saved_filter").order_by(AuditLog.id)
        )
    )
    assert [(r.entity_id, r.action) for r in rows] == [
        (str(sid), "create"),
        (str(sid), "update"),
        (str(sid), "delete"),
    ]
    assert rows[0].user_id == ctx["users"][Role.FABRICA].id
    assert rows[1].before is not None and rows[1].before["definition"]["rules"] == []
    assert rows[1].after is not None and rows[1].after["definition"]["rules"] == [CAT_PILAR]
    assert rows[2].after is None and rows[2].before is not None
