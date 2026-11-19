"""Aceite da 11.2, ponta a ponta com o login Microsoft (APP_ENV=prod, tokens assinados
por uma chave de teste; nada de usuário simulado):

- sem login a API responde 401;
- Fábrica não cria obra;
- Projetos não edita parâmetro;
- usuário sem a obra não a vê;
- a auditoria mostra os nomes reais (da conta Microsoft).

O admin é o de BOOTSTRAP_ADMIN_EMAILS e administra tudo pela API da tela "Usuários".
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest_asyncio
import respx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, Obra, ParamDef
from tests.conftest import build_app, include_params
from tests.factories import ready_version
from tests.test_auth_entra import ENTRA, bearer, jwks, token  # noqa: F401 (fixture jwks)

ADMIN = "vhbastos@cassol.ind.br"
MARIA, JOAO, ANA = "maria@cassol.ind.br", "joao@cassol.ind.br", "ana@cassol.ind.br"


def as_(email: str, name: str) -> dict[str, str]:
    return bearer(token(email, name=name))


@pytest_asyncio.fixture
async def api(session: AsyncSession, jwks: respx.Route) -> AsyncIterator[httpx.AsyncClient]:  # noqa: F811
    app = build_app(session, **ENTRA)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c


@pytest_asyncio.fixture
async def obras(session: AsyncSession) -> dict[str, Any]:
    out: dict[str, Any] = {}
    forma = ParamDef(name="Tipo de forma", type="text", scope="global")
    session.add(forma)
    await session.flush()
    for key, code in (("a", "OB-E2E-A"), ("b", "OB-E2E-B")):
        obra = Obra(code=code, name=f"Obra {code}", acc_item_name="o.rvt")
        session.add(obra)
        await session.flush()
        _, marks = await ready_version(session, obra, [("PP001", "Pilar", 2)])
        await include_params(session, obra.id, forma)
        out[key] = {"obra": obra, "mark": marks["PP001"]}
    out["forma"] = forma
    return out


async def _register(api: httpx.AsyncClient, email: str, role: str, **extra: Any) -> dict[str, Any]:
    """O admin cadastra a pessoa pelo e-mail, antes do primeiro acesso."""
    admin = as_(ADMIN, "Vinicius Bastos")
    r = await api.post("/api/users", json={"email": email, "role": role, **extra}, headers=admin)
    assert r.status_code == 201, r.text
    body: dict[str, Any] = r.json()
    return body


async def test_without_login_api_is_401(api: httpx.AsyncClient, obras: dict[str, Any]) -> None:
    obra_id = obras["a"]["obra"].id
    for method, url in [
        ("GET", "/api/me"),
        ("GET", "/api/obras"),
        ("GET", f"/api/obras/{obra_id}"),
        ("GET", "/api/users"),
        ("POST", "/api/obras"),
        ("PUT", f"/api/obras/{obra_id}/marks/{obras['a']['mark'].id}/values"),
    ]:
        r = await api.request(method, url, json={} if method != "GET" else None)
        assert r.status_code == 401, (method, url)
        assert r.headers["www-authenticate"] == "Bearer"
    # o usuário simulado não existe fora de dev
    r = await api.get("/api/obras", headers={"X-Dev-User": "1"})
    assert r.status_code == 401
    # o que o frontend precisa para o login continua público
    assert (await api.get("/api/auth/config")).json()["dev_login"] is False


async def test_fabrica_cannot_create_obra(api: httpx.AsyncClient) -> None:
    await _register(api, MARIA, "fabrica")
    acc = {"hub_id": "h", "project_id": "p", "folder_id": "f", "item_id": "i"}
    r = await api.post(
        "/api/obras",
        json={"code": "OB-X", "name": "X", "acc": acc},
        headers=as_(MARIA, "Maria Souza"),
    )
    assert r.status_code == 403
    assert r.json()["detail"] == "Seu papel não permite esta ação."


async def test_projetos_cannot_edit_parameter(
    api: httpx.AsyncClient, obras: dict[str, Any]
) -> None:
    await _register(api, JOAO, "projetos")
    h = as_(JOAO, "João Lima")
    obra, mark, forma = obras["a"]["obra"], obras["a"]["mark"], obras["forma"]
    changes = {"changes": [{"def_id": forma.id, "value": "Metálica"}]}
    r = await api.put(f"/api/obras/{obra.id}/marks/{mark.id}/values", json=changes, headers=h)
    assert r.status_code == 403
    r = await api.post(
        f"/api/obras/{obra.id}/marks/batch-apply",
        json={"mark_ids": [mark.id], "changes": changes["changes"]},
        headers=h,
    )
    assert r.status_code == 403
    r = await api.post("/api/param-defs", json={"name": "Novo", "type": "text"}, headers=h)
    assert r.status_code == 403
    # mas lê normalmente
    r = await api.get(f"/api/obras/{obra.id}/marks/{mark.id}/values", headers=h)
    assert r.status_code == 200


async def test_user_without_the_obra_does_not_see_it(
    api: httpx.AsyncClient, obras: dict[str, Any]
) -> None:
    a, b = obras["a"]["obra"], obras["b"]["obra"]
    ana = await _register(api, ANA, "fabrica", all_obras=False, obra_ids=[a.id])
    h = as_(ANA, "Ana Prado")

    codes = [o["code"] for o in (await api.get("/api/obras", headers=h)).json()]
    assert codes == ["OB-E2E-A"]
    for url in (
        f"/api/obras/{b.id}",
        f"/api/obras/{b.id}/versions",
        f"/api/obras/{b.id}/marks/{obras['b']['mark'].id}/values",
        f"/api/obras/{b.id}/export.xlsx",
        f"/api/obras/{b.id}/events",
    ):
        r = await api.get(url, headers=h)
        assert r.status_code == 404, url
    r = await api.put(
        f"/api/obras/{b.id}/marks/{obras['b']['mark'].id}/values",
        json={"changes": [{"def_id": obras["forma"].id, "value": "Madeira"}]},
        headers=h,
    )
    assert r.status_code == 404

    # o admin libera a obra B: passa a ver
    admin = as_(ADMIN, "Vinicius Bastos")
    r = await api.patch(f"/api/users/{ana['id']}", json={"obra_ids": [a.id, b.id]}, headers=admin)
    assert r.status_code == 200
    assert (await api.get(f"/api/obras/{b.id}", headers=h)).status_code == 200


async def test_audit_shows_real_names(
    api: httpx.AsyncClient, session: AsyncSession, obras: dict[str, Any]
) -> None:
    maria = await _register(api, MARIA, "fabrica")
    assert maria["name"] == MARIA  # cadastrada só com o e-mail

    # 1º acesso: o nome vem da conta Microsoft
    me = (await api.get("/api/me", headers=as_(MARIA, "Maria Souza"))).json()
    assert me["name"] == "Maria Souza" and me["role"] == "fabrica"
    # depois o nome não muda mais pelo login (o admin corrige, se for o caso)
    me = (await api.get("/api/me", headers=as_(MARIA, "M. Souza"))).json()
    assert me["name"] == "Maria Souza"

    obra, mark, forma = obras["a"]["obra"], obras["a"]["mark"], obras["forma"]
    r = await api.put(
        f"/api/obras/{obra.id}/marks/{mark.id}/values",
        json={"changes": [{"def_id": forma.id, "value": "Metálica"}]},
        headers=as_(MARIA, "Maria Souza"),
    )
    assert r.status_code == 200, r.text
    history = (
        await api.get(
            f"/api/obras/{obra.id}/marks/{mark.id}/history", headers=as_(ANA, "Ana Prado")
        )
    ).json()
    assert [(h["user_name"], h["after"]) for h in history] == [("Maria Souza", "Metálica")]

    # a tela Usuários mostra o nome real e quem administrou fica na auditoria
    listed = {u["email"]: u for u in (await api.get("/api/users", headers=as_(ADMIN, "V"))).json()}
    assert listed[MARIA]["name"] == "Maria Souza"
    assert listed[ADMIN]["name"] == "Vinicius Bastos"
    created = await session.scalar(
        select(AuditLog).where(
            AuditLog.entity == "user",
            AuditLog.entity_id == str(maria["id"]),
            AuditLog.action == "create",
        )
    )
    assert created is not None and created.user_id == listed[ADMIN]["id"]
