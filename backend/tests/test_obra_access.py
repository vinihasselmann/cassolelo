"""Acesso por obra (11.2).

Usuário restrito (all_obras = false) só vê as obras de user_obras. Toda rota que é de uma
obra (pelo caminho ou pela query) responde 404 "Obra não encontrada." para a obra que ele
não vê, em leitura e escrita. A lista de rotas sai da matriz de papéis: rota nova de obra
entra aqui sozinha.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, ColorScheme, Obra, Orphan, ParamDef, SavedFilter, User, UserObra
from app.models.enums import Role
from tests.conftest import as_user
from tests.factories import ready_version
from tests.test_role_matrix import MATRIX

NOT_FOUND = "Obra não encontrada."
# parâmetros de rota que levam a uma obra (app/api/obra_resolve.py)
OBRA_PARAMS = {
    "obra_id",
    "version_id",
    "mark_id",
    "orphan_id",
    "def_id",
    "filter_id",
    "scheme_id",
    "batch_id",
}
_PARAM = re.compile(r"\{([^}]+)\}")


def obra_routes() -> list[str]:
    return sorted(r for r in MATRIX if set(_PARAM.findall(r)) & OBRA_PARAMS)


@pytest_asyncio.fixture
async def world(session: AsyncSession, users: dict[Role, User]) -> dict[str, Any]:
    """Obra A (o usuário restrito vê) e obra B (não vê), cada uma com versão, marca,
    órfã, parâmetro da obra, filtro, esquema e lote."""
    restricted = users[Role.FABRICA]
    restricted.all_obras = False
    out: dict[str, Any] = {"user": restricted}
    for key, code in (("a", "OB-VISTA"), ("b", "OB-OCULTA")):
        obra = Obra(code=code, name=f"Obra {code}", acc_item_name="o.rvt")
        session.add(obra)
        await session.flush()
        version, marks = await ready_version(session, obra, [("PP1", "Pilar", 2)])
        mark = marks["PP1"]
        orphan = Orphan(mark_id=mark.id, since_version_id=version.id)
        param = ParamDef(name=f"Forma {code}", type="text", scope="obra", obra_id=obra.id)
        flt = SavedFilter(
            name=f"F {code}",
            scope="personal",
            owner_id=restricted.id,
            obra_id=obra.id,
            definition={"mode": "isolate", "logic": "and", "rules": []},
        )
        scheme = ColorScheme(
            name=f"C {code}", scope="personal", owner_id=restricted.id, obra_id=obra.id, rules=[]
        )
        session.add_all([orphan, param, flt, scheme])
        await session.flush()
        batch = uuid.uuid4()
        session.add(
            AuditLog(
                entity="mark_value",
                entity_id=str(mark.id),
                action="update",
                before={"mark_id": mark.id, "def_id": param.id, "value": None},
                after={"mark_id": mark.id, "def_id": param.id, "value": "x"},
                user_id=restricted.id,
                batch_id=batch,
            )
        )
        out[key] = {
            "obra_id": obra.id,
            "version_id": version.id,
            "mark_id": mark.id,
            "orphan_id": orphan.id,
            "def_id": param.id,
            "filter_id": flt.id,
            "scheme_id": scheme.id,
            "batch_id": str(batch),
        }
    session.add(UserObra(user_id=restricted.id, obra_id=out["a"]["obra_id"]))
    await session.flush()
    return out


def _url(route: str, ids: dict[str, Any]) -> tuple[str, str]:
    method, path = route.split(" ", 1)
    fill = {**ids, "unit_id": 999999, "dbid": 1001, "source": "model", "key": "x"}
    return method, _PARAM.sub(lambda m: str(fill.get(m.group(1), 999999)), path)


async def _call(client: httpx.AsyncClient, route: str, ids: dict[str, Any], user: User) -> Any:
    method, url = _url(route, ids)
    body: dict[str, Any] | None = {} if method in ("POST", "PUT", "PATCH") else None
    return await client.request(method, url, headers=as_user(user), json=body)


def test_obra_routes_found() -> None:
    routes = obra_routes()
    assert "GET /api/obras/{obra_id}" in routes
    assert "POST /api/batches/{batch_id}/undo" in routes
    assert "GET /api/versions/{version_id}/marks" in routes
    assert len(routes) > 50


@pytest.mark.parametrize("route", obra_routes())
async def test_hidden_obra_is_404_on_every_route(
    client: httpx.AsyncClient, world: dict[str, Any], route: str
) -> None:
    r = await _call(client, route, world["b"], world["user"])
    assert r.status_code == 404, f"{route}: {r.status_code} {r.text[:200]}"
    assert r.json()["detail"] == NOT_FOUND


@pytest.mark.parametrize("route", obra_routes())
async def test_visible_obra_passes_the_access_check(
    client: httpx.AsyncClient, world: dict[str, Any], route: str
) -> None:
    """Contraprova: na obra que vê, a checagem de acesso não barra (a rota pode dar
    outro erro pelo corpo vazio, mas não o 404 de obra)."""
    if route.startswith("GET /api/obras/{obra_id}/events"):
        pytest.skip("fluxo SSE contínuo (coberto em test_events_stream_for_hidden_obra)")
    r = await _call(client, route, world["a"], world["user"])
    assert not (r.status_code == 404 and r.json().get("detail") == NOT_FOUND), route


async def test_events_stream_for_hidden_obra_is_404(
    client: httpx.AsyncClient, world: dict[str, Any]
) -> None:
    r = await client.get(
        f"/api/obras/{world['b']['obra_id']}/events", headers=as_user(world["user"])
    )
    assert r.status_code == 404


async def test_lists_show_only_visible_obras(
    client: httpx.AsyncClient, world: dict[str, Any], users: dict[Role, User]
) -> None:
    h = as_user(world["user"])
    a, b = world["a"], world["b"]

    codes = [o["code"] for o in (await client.get("/api/obras", headers=h)).json()]
    assert "OB-VISTA" in codes and "OB-OCULTA" not in codes

    filters = {f["id"] for f in (await client.get("/api/saved-filters", headers=h)).json()}
    assert a["filter_id"] in filters and b["filter_id"] not in filters
    schemes = {s["id"] for s in (await client.get("/api/color-schemes", headers=h)).json()}
    assert a["scheme_id"] in schemes and b["scheme_id"] not in schemes
    params = {p["id"] for p in (await client.get("/api/param-defs", headers=h)).json()}
    assert a["def_id"] in params and b["def_id"] not in params

    # a obra oculta na query das listas também é 404
    for url in ("/api/saved-filters", "/api/color-schemes", "/api/param-defs"):
        r = await client.get(url, params={"obra_id": b["obra_id"]}, headers=h)
        assert r.status_code == 404, url

    # o admin vê tudo
    admin = as_user(users[Role.ADMIN])
    codes = [o["code"] for o in (await client.get("/api/obras", headers=admin)).json()]
    assert {"OB-VISTA", "OB-OCULTA"} <= set(codes)


async def test_body_pointing_to_hidden_obra_is_422(
    client: httpx.AsyncClient, world: dict[str, Any]
) -> None:
    h = as_user(world["user"])
    hidden = world["b"]["obra_id"]
    definition = {"mode": "isolate", "logic": "and", "rules": []}
    r = await client.post(
        "/api/saved-filters",
        json={"name": "X", "scope": "personal", "obra_id": hidden, "definition": definition},
        headers=h,
    )
    assert r.status_code == 422 and r.json()["detail"] == NOT_FOUND
    r = await client.post(
        "/api/color-schemes",
        json={
            "name": "X",
            "scope": "personal",
            "obra_id": hidden,
            "rules": [{"filter": definition, "color": "#cccccc"}],
        },
        headers=h,
    )
    assert r.status_code == 422 and r.json()["detail"] == NOT_FOUND
    r = await client.post(
        "/api/param-defs",
        json={"name": "Novo", "type": "text", "scope": "obra", "obra_id": hidden},
        headers=h,
    )
    assert r.status_code == 422 and r.json()["detail"] == NOT_FOUND
    r = await client.post(
        "/api/param-defs",
        json={"name": "Novo2", "type": "text", "include_in_obra_id": hidden},
        headers=h,
    )
    assert r.status_code == 422 and r.json()["detail"] == NOT_FOUND


async def test_all_obras_sees_new_obras_restricted_does_not(
    client: httpx.AsyncClient, session: AsyncSession, world: dict[str, Any], users: dict[Role, User]
) -> None:
    session.add(Obra(code="OB-NOVA", name="Nova", acc_item_name="n.rvt"))
    await session.flush()
    restricted = [
        o["code"] for o in (await client.get("/api/obras", headers=as_user(world["user"]))).json()
    ]
    assert "OB-NOVA" not in restricted
    everyone = [
        o["code"]
        for o in (await client.get("/api/obras", headers=as_user(users[Role.LEITURA]))).json()
    ]
    assert "OB-NOVA" in everyone  # padrão: todas, inclusive as criadas depois


async def test_restricted_creator_gets_access_to_new_obra(
    session: AsyncSession, users: dict[Role, User]
) -> None:
    from app.services import obra_access

    creator = users[Role.PROJETOS]
    creator.all_obras = False
    obra = Obra(code="OB-MINHA", name="Minha", acc_item_name="m.rvt")
    session.add(obra)
    await session.flush()
    assert not await obra_access.can_see(session, creator, obra.id)
    await obra_access.grant_creator(session, creator, obra.id)
    assert await obra_access.can_see(session, creator, obra.id)
    logged = await session.scalar(
        select(AuditLog).where(AuditLog.entity == "user", AuditLog.action == "grant_obra")
    )
    assert logged is not None and logged.after == {"obra_id": obra.id}


async def test_admin_always_sees_all(session: AsyncSession, users: dict[Role, User]) -> None:
    from app.services import obra_access

    admin = users[Role.ADMIN]
    admin.all_obras = False  # não tem efeito no admin
    assert await obra_access.visible_obra_ids(session, admin) is None
