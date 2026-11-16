from __future__ import annotations

from typing import Annotated

import httpx
import pytest
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import DEV_USER_HEADER, Role, require_role
from app.models import User
from tests.conftest import build_app

ALL_ROLES = list(Role)


def _user(role: Role) -> User:
    return User(id=1, name="x", email="x@dev.local", role=role.value, active=True)


# ------------------------------------------------------------------ require_role (unitário)

RULES: list[tuple[Role, ...]] = [
    (Role.PROJETOS,),
    (Role.FABRICA,),
    (Role.ADMIN,),
    (Role.LEITURA,),
    (Role.FABRICA, Role.ADMIN),
    tuple(Role),
]


@pytest.mark.parametrize("role", ALL_ROLES, ids=[r.value for r in ALL_ROLES])
@pytest.mark.parametrize("allowed", RULES, ids=["+".join(r.value for r in a) for a in RULES])
async def test_require_role_each_role(role: Role, allowed: tuple[Role, ...]) -> None:
    dep = require_role(*allowed)
    user = _user(role)
    if role in allowed:
        assert await dep(user) is user
    else:
        with pytest.raises(HTTPException) as exc:
            await dep(user)
        assert exc.value.status_code == 403


def test_require_role_needs_roles() -> None:
    with pytest.raises(ValueError, match="papel"):
        require_role()


# ------------------------------------------------------------------ current_user (integração)


def _client(app: object) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")  # type: ignore[arg-type]


@pytest.mark.parametrize("role", ALL_ROLES, ids=[r.value for r in ALL_ROLES])
async def test_me_returns_role_of_simulated_user(
    client: httpx.AsyncClient, users: dict[Role, User], role: Role
) -> None:
    r = await client.get("/api/me", headers={DEV_USER_HEADER: str(users[role].id)})
    assert r.status_code == 200
    assert r.json()["role"] == role.value


async def test_switching_user_changes_role(
    client: httpx.AsyncClient, users: dict[Role, User]
) -> None:
    roles = []
    for role in (Role.FABRICA, Role.ADMIN, Role.LEITURA):
        r = await client.get("/api/me", headers={DEV_USER_HEADER: str(users[role].id)})
        roles.append(r.json()["role"])
    assert roles == ["fabrica", "admin", "leitura"]


@pytest.mark.parametrize("header", [None, "", "abc", "999999"])
async def test_me_401_without_valid_user(
    client: httpx.AsyncClient, users: dict[Role, User], header: str | None
) -> None:
    headers = {DEV_USER_HEADER: header} if header is not None else {}
    r = await client.get("/api/me", headers=headers)
    assert r.status_code == 401


async def test_inactive_user_401(
    session: AsyncSession, client: httpx.AsyncClient, users: dict[Role, User]
) -> None:
    users[Role.LEITURA].active = False
    await session.flush()
    r = await client.get("/api/me", headers={DEV_USER_HEADER: str(users[Role.LEITURA].id)})
    assert r.status_code == 401


@pytest.mark.parametrize("env", ["test", "staging", "prod"])
async def test_dev_header_rejected_outside_dev(env: str) -> None:
    app = build_app(app_env=env)
    async with _client(app) as c:
        r = await c.get("/api/me", headers={DEV_USER_HEADER: "1"})
        dev = await c.get("/api/dev/users")
    assert r.status_code == 401
    assert dev.status_code == 404


async def test_require_role_on_endpoint(session: AsyncSession, users: dict[Role, User]) -> None:
    app = build_app(session)
    router = APIRouter()

    @router.post("/api/_teste/fabrica")
    async def only_factory(
        user: Annotated[User, Depends(require_role(Role.FABRICA, Role.ADMIN))],
    ) -> dict[str, str]:
        return {"ok": user.role}

    app.include_router(router)
    async with _client(app) as c:
        codes = {
            role: (
                await c.post("/api/_teste/fabrica", headers={DEV_USER_HEADER: str(u.id)})
            ).status_code
            for role, u in users.items()
        }
    assert codes == {Role.PROJETOS: 403, Role.FABRICA: 200, Role.ADMIN: 200, Role.LEITURA: 403}


async def test_dev_users_lists_seed(client: httpx.AsyncClient, users: dict[Role, User]) -> None:
    r = await client.get("/api/dev/users")
    assert r.status_code == 200
    assert sorted(u["role"] for u in r.json()) == sorted(r.value for r in Role)
