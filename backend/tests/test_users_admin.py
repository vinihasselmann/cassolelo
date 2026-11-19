"""Tela "Usuários" (11.2): listar, cadastrar, papel, ativo e obras de cada um. Só admin
(a matriz de papéis cobre o 403 dos outros papéis)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, Obra, User
from app.models.enums import Role
from tests.conftest import as_user, build_app

URL = "/api/users"


@pytest_asyncio.fixture
async def obras(session: AsyncSession) -> list[Obra]:
    rows = [Obra(code=f"OB-U{i}", name=f"Obra {i}", acc_item_name="o.rvt") for i in (1, 2)]
    session.add_all(rows)
    await session.flush()
    return rows


async def _api(session: AsyncSession, **settings: Any) -> httpx.AsyncClient:
    app = build_app(session, **settings)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def _audit(session: AsyncSession, user_id: int) -> list[AuditLog]:
    rows = await session.scalars(
        select(AuditLog)
        .where(AuditLog.entity == "user", AuditLog.entity_id == str(user_id))
        .order_by(AuditLog.id)
    )
    return list(rows)


async def test_list_users_with_access(client: httpx.AsyncClient, users: dict[Role, User]) -> None:
    r = await client.get(URL, headers=as_user(users[Role.ADMIN]))
    assert r.status_code == 200
    by_email = {u["email"]: u for u in r.json()}
    fab = by_email[users[Role.FABRICA].email]
    assert fab["role"] == "fabrica" and fab["active"] is True
    assert fab["all_obras"] is True and fab["obra_ids"] == []
    assert fab["role_source"] == "table"


async def test_create_user_before_first_login(
    client: httpx.AsyncClient, session: AsyncSession, users: dict[Role, User], obras: list[Obra]
) -> None:
    admin = users[Role.ADMIN]
    r = await client.post(
        URL,
        json={
            "email": "  Novo.Usuario@Cassol.ind.br ",
            "role": "fabrica",
            "all_obras": False,
            "obra_ids": [obras[1].id, obras[0].id, obras[0].id],
        },
        headers=as_user(admin),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["email"] == "novo.usuario@cassol.ind.br"
    assert body["name"] == "novo.usuario@cassol.ind.br"  # o login preenche o nome real
    assert body["obra_ids"] == sorted([obras[0].id, obras[1].id])
    log = await _audit(session, body["id"])
    assert [e.action for e in log] == ["create"]
    assert log[0].user_id == admin.id and log[0].after is not None
    assert log[0].after["obra_ids"] == body["obra_ids"]

    again = await client.post(
        URL, json={"email": "novo.usuario@cassol.ind.br"}, headers=as_user(admin)
    )
    assert again.status_code == 409


async def test_create_user_validations(client: httpx.AsyncClient, users: dict[Role, User]) -> None:
    h = as_user(users[Role.ADMIN])
    r = await client.post(URL, json={"email": "fulano@gmail.com"}, headers=h)
    assert r.status_code == 422 and "domínios permitidos" in r.json()["detail"]
    r = await client.post(URL, json={"email": "sem-arroba"}, headers=h)
    assert r.status_code == 422
    r = await client.post(
        URL, json={"email": "x@cassol.ind.br", "all_obras": False, "obra_ids": [999999]}, headers=h
    )
    assert r.status_code == 422 and "999999" in r.json()["detail"]


async def test_update_role_active_and_obras(
    client: httpx.AsyncClient, session: AsyncSession, users: dict[Role, User], obras: list[Obra]
) -> None:
    admin, target = users[Role.ADMIN], users[Role.LEITURA]
    h = as_user(admin)
    r = await client.patch(
        f"{URL}/{target.id}",
        json={"role": "projetos", "all_obras": False, "obra_ids": [obras[0].id]},
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "projetos" and r.json()["obra_ids"] == [obras[0].id]

    # já vale: a pessoa só vê a obra 1
    seen = [o["id"] for o in (await client.get("/api/obras", headers=as_user(target))).json()]
    assert seen == [obras[0].id]

    # voltar para "todas" limpa a lista
    r = await client.patch(f"{URL}/{target.id}", json={"all_obras": True}, headers=h)
    assert r.json()["all_obras"] is True and r.json()["obra_ids"] == []

    # desativar: não entra mais
    r = await client.patch(f"{URL}/{target.id}", json={"active": False}, headers=h)
    assert r.json()["active"] is False
    assert (await client.get("/api/me", headers=as_user(target))).status_code == 401

    log = await _audit(session, target.id)
    updates = [e for e in log if e.action == "update"]
    assert len(updates) == 3 and all(e.user_id == admin.id for e in updates)
    assert updates[0].before is not None and updates[0].after is not None
    assert updates[0].before["role"] == "leitura" and updates[0].after["role"] == "projetos"
    assert updates[0].after["obra_ids"] == [obras[0].id]

    # nada mudou: nada na auditoria
    await client.patch(f"{URL}/{target.id}", json={"active": False}, headers=h)
    assert len(await _audit(session, target.id)) == len(log)


async def test_admin_cannot_lock_themselves_out(
    client: httpx.AsyncClient, users: dict[Role, User]
) -> None:
    admin = users[Role.ADMIN]
    h = as_user(admin)
    r = await client.patch(f"{URL}/{admin.id}", json={"active": False}, headers=h)
    assert r.status_code == 409 and "própria conta" in r.json()["detail"]
    r = await client.patch(f"{URL}/{admin.id}", json={"role": "leitura"}, headers=h)
    assert r.status_code == 409 and "próprio papel" in r.json()["detail"]


async def test_last_active_admin_keeps_role(
    client: httpx.AsyncClient, session: AsyncSession, users: dict[Role, User]
) -> None:
    admin = users[Role.ADMIN]
    other = User(name="Outro Admin", email="outro.admin@cassol.ind.br", role="admin", active=True)
    session.add(other)
    await session.flush()
    h = as_user(other)
    # com dois admins, um pode rebaixar o outro
    r = await client.patch(f"{URL}/{admin.id}", json={"role": "fabrica"}, headers=h)
    assert r.status_code == 200
    assert (await client.get("/api/me", headers=as_user(admin))).json()["role"] == "fabrica"


async def test_last_active_admin_cannot_be_demoted(
    session: AsyncSession, users: dict[Role, User]
) -> None:
    """Sem passar pela API (um admin não pode rebaixar a si mesmo), o serviço ainda
    recusa deixar o app sem admin ativo."""
    from app.services import user_admin
    from app.services.errors import ConflictError
    from app.services.user_admin import UserPatch
    from tests.conftest import make_settings

    admin = users[Role.ADMIN]
    robot = User(name="Robô", email="robo@cassol.ind.br", role="fabrica", active=True)
    session.add(robot)
    await session.flush()
    settings = make_settings(bootstrap_admin_emails="")
    try:
        await user_admin.update_user(
            session, settings, admin.id, UserPatch(role=Role.LEITURA), robot
        )
    except ConflictError as exc:
        assert "último administrador" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("deveria recusar")


async def test_role_from_bootstrap_or_groups_is_not_editable(
    session: AsyncSession, users: dict[Role, User]
) -> None:
    admin = users[Role.ADMIN]
    boot = User(name="Boot", email="boot@cassol.ind.br", role="admin", active=True)
    session.add(boot)
    await session.flush()
    async with await _api(session, bootstrap_admin_emails="boot@cassol.ind.br") as api:
        listed = {u["email"]: u for u in (await api.get(URL, headers=as_user(admin))).json()}
        assert listed["boot@cassol.ind.br"]["role_source"] == "bootstrap"
        r = await api.patch(f"{URL}/{boot.id}", json={"role": "leitura"}, headers=as_user(admin))
        assert r.status_code == 409 and "BOOTSTRAP_ADMIN_EMAILS" in r.json()["detail"]
        # o resto (nome, obras, ativo) continua editável
        r = await api.patch(f"{URL}/{boot.id}", json={"name": "Boot Silva"}, headers=as_user(admin))
        assert r.status_code == 200 and r.json()["name"] == "Boot Silva"

    groups = "admin=0a0a0a0a-0000-0000-0000-00000000000a"
    target = users[Role.LEITURA]
    async with await _api(session, entra_role_groups=groups) as api:
        r = await api.patch(f"{URL}/{target.id}", json={"role": "fabrica"}, headers=as_user(admin))
        assert r.status_code == 409 and "ENTRA_ROLE_GROUPS" in r.json()["detail"]
        r = await api.patch(f"{URL}/{target.id}", json={"active": False}, headers=as_user(admin))
        assert r.status_code == 200
