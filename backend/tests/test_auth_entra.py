"""Login Microsoft (Fase 11): tokens assinados por uma chave RSA de teste, JWKS via respx."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx
import jwt
import pytest
import pytest_asyncio
import respx
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.entra import EntraVerifier, TokenError, jwks_url
from app.config import parse_role_groups
from app.models import AuditLog, User
from app.models.enums import Role
from tests.conftest import as_user, build_app, make_settings

TENANT = "11111111-2222-3333-4444-555555555555"
CLIENT = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
G_ADMIN = "0a0a0a0a-0000-0000-0000-00000000000a"
G_FABRICA = "0f0f0f0f-0000-0000-0000-00000000000f"
ISS_V2 = f"https://login.microsoftonline.com/{TENANT}/v2.0"

ENTRA: dict[str, Any] = {
    "app_env": "prod",
    "entra_client_id": CLIENT,
    "entra_tenant_id": TENANT,
    "allowed_email_domains": "cassol.ind.br",
    "bootstrap_admin_emails": "vhbastos@cassol.ind.br",
}


def _new_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


KEY = _new_key()
OTHER_KEY = _new_key()


def _jwk(key: rsa.RSAPrivateKey, kid: str) -> dict[str, Any]:
    jwk: dict[str, Any] = RSAAlgorithm.to_jwk(key.public_key(), as_dict=True)
    return {**jwk, "kid": kid, "use": "sig", "alg": "RS256"}


def token(
    addr: str = "fulano@cassol.ind.br",
    *,
    key: rsa.RSAPrivateKey = KEY,
    kid: str = "k1",
    alg: str = "RS256",
    **claims: Any,
) -> str:
    now = int(time.time())
    payload: dict[str, Any] = {
        "iss": ISS_V2,
        "aud": CLIENT,
        "tid": TENANT,
        "oid": "oid-1",
        "scp": "access_as_user",
        "name": "Fulano de Tal",
        "preferred_username": addr,
        "iat": now,
        "nbf": now,
        "exp": now + 3600,
    }
    payload.update(claims)
    payload = {k: v for k, v in payload.items() if v is not None}
    return jwt.encode(payload, key, algorithm=alg, headers={"kid": kid})


def bearer(tok: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture
def jwks() -> Iterator[respx.Route]:
    with respx.mock(assert_all_called=False) as mock:
        route = mock.get(jwks_url(TENANT)).respond(json={"keys": [_jwk(KEY, "k1")]})
        yield route


@pytest_asyncio.fixture
async def api(session: AsyncSession, jwks: respx.Route) -> AsyncIterator[httpx.AsyncClient]:
    app = build_app(session, **ENTRA)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def _api_with(session: AsyncSession, **settings: Any) -> httpx.AsyncClient:
    app = build_app(session, **{**ENTRA, **settings})
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def _user(session: AsyncSession, email: str) -> User | None:
    return await session.scalar(select(User).where(func.lower(User.email) == email.lower()))


# ------------------------------------------------------------------ token válido


async def test_valid_token_creates_user_as_leitura(
    api: httpx.AsyncClient, session: AsyncSession
) -> None:
    r = await api.get("/api/me", headers=bearer(token()))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["email"] == "fulano@cassol.ind.br"
    assert body["name"] == "Fulano de Tal"
    assert body["role"] == "leitura"
    user = await _user(session, "fulano@cassol.ind.br")
    assert user is not None
    audit = await session.scalar(
        select(AuditLog).where(AuditLog.entity == "user", AuditLog.entity_id == str(user.id))
    )
    assert audit is not None and audit.action == "create" and audit.user_id is None


async def test_same_user_on_second_login_and_email_case_insensitive(
    api: httpx.AsyncClient, session: AsyncSession
) -> None:
    first = (await api.get("/api/me", headers=bearer(token("Fulano@Cassol.IND.br")))).json()
    second = (await api.get("/api/me", headers=bearer(token("fulano@cassol.ind.br")))).json()
    assert first["id"] == second["id"]
    assert first["email"] == "fulano@cassol.ind.br"
    n = await session.scalar(
        select(func.count()).select_from(User).where(User.email == "fulano@cassol.ind.br")
    )
    assert n == 1


async def test_existing_user_keeps_role_from_table(
    api: httpx.AsyncClient, session: AsyncSession
) -> None:
    session.add(User(name="Fábio", email="fabio@cassol.ind.br", role="fabrica", active=True))
    await session.flush()
    r = await api.get("/api/me", headers=bearer(token("fabio@cassol.ind.br")))
    assert r.json()["role"] == "fabrica"
    assert r.json()["name"] == "Fábio"  # nome definido pelo admin não é sobrescrito


async def test_bootstrap_admin_is_admin_from_first_login(api: httpx.AsyncClient) -> None:
    r = await api.get("/api/me", headers=bearer(token("VHBastos@cassol.ind.br")))
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "admin"


async def test_bootstrap_admin_promoted_if_table_says_otherwise(
    api: httpx.AsyncClient, session: AsyncSession
) -> None:
    session.add(User(name="V", email="vhbastos@cassol.ind.br", role="leitura", active=True))
    await session.flush()
    r = await api.get("/api/me", headers=bearer(token("vhbastos@cassol.ind.br")))
    assert r.json()["role"] == "admin"


async def test_email_from_email_or_upn_claim(api: httpx.AsyncClient) -> None:
    t = token(preferred_username=None, email=None, upn="beltrano@cassol.ind.br")
    r = await api.get("/api/me", headers=bearer(t))
    assert r.status_code == 200, r.text
    assert r.json()["email"] == "beltrano@cassol.ind.br"


async def test_v1_issuer_and_app_id_uri_audience_accepted(api: httpx.AsyncClient) -> None:
    t = token(iss=f"https://sts.windows.net/{TENANT}/", aud=f"api://{CLIENT}")
    assert (await api.get("/api/me", headers=bearer(t))).status_code == 200


async def test_roles_from_token_apply_to_endpoints(api: httpx.AsyncClient) -> None:
    # leitura (usuário novo) não cria parâmetro: 403 pelo require_role de sempre
    r = await api.post("/api/param-defs", json={}, headers=bearer(token()))
    assert r.status_code == 403
    assert (await api.get("/api/obras", headers=bearer(token()))).status_code == 200


# ------------------------------------------------------------------ token recusado


@pytest.mark.parametrize(
    ("make", "detail"),
    [
        (lambda: token(key=OTHER_KEY), "Token inválido."),
        (lambda: token(exp=int(time.time()) - 3600), "Sessão expirada"),
        (lambda: token(aud="00000003-0000-0000-c000-000000000000"), "outro aplicativo"),
        (lambda: token(iss="https://login.microsoftonline.com/outro/v2.0"), "outro tenant"),
        (lambda: token(tid="99999999-0000-0000-0000-000000000000"), "outro tenant"),
        (lambda: token(scp="User.Read"), "escopo"),
        (lambda: token(nbf=int(time.time()) + 3600), "Token inválido."),
        (lambda: token(preferred_username=None, email=None), "sem e-mail"),
        (lambda: "nao-e-um-jwt", "Token inválido."),
    ],
    ids=[
        "assinatura",
        "expirado",
        "audiencia",
        "emissor",
        "tenant",
        "escopo",
        "nbf",
        "sem-email",
        "lixo",
    ],
)
async def test_invalid_tokens_are_401(
    api: httpx.AsyncClient, session: AsyncSession, make: Any, detail: str
) -> None:
    r = await api.get("/api/me", headers=bearer(make()))
    assert r.status_code == 401, r.text
    assert detail in r.json()["detail"]
    assert r.headers["www-authenticate"] == "Bearer"
    assert await _user(session, "fulano@cassol.ind.br") is None  # nada criado


async def test_hs256_and_none_algorithms_refused(api: httpx.AsyncClient) -> None:
    now = int(time.time())
    claims = {
        "iss": ISS_V2,
        "aud": CLIENT,
        "tid": TENANT,
        "scp": "access_as_user",
        "preferred_username": "fulano@cassol.ind.br",
        "iat": now,
        "exp": now + 600,
    }
    hs = jwt.encode(
        claims, "segredo-qualquer-com-32-bytes-ou-mais!!", algorithm="HS256", headers={"kid": "k1"}
    )
    none = jwt.encode(claims, None, algorithm="none", headers={"kid": "k1"})  # type: ignore[arg-type]
    for t in (hs, none):
        r = await api.get("/api/me", headers=bearer(t))
        assert r.status_code == 401
        assert "algoritmo" in r.json()["detail"]


async def test_email_outside_allowed_domain_is_403(
    api: httpx.AsyncClient, session: AsyncSession
) -> None:
    r = await api.get("/api/me", headers=bearer(token("alguem@gmail.com")))
    assert r.status_code == 403
    assert "cassol.ind.br" in r.json()["detail"]
    assert await _user(session, "alguem@gmail.com") is None


async def test_lookalike_domain_is_403(api: httpx.AsyncClient) -> None:
    r = await api.get("/api/me", headers=bearer(token("x@cassol.ind.br.evil.com")))
    assert r.status_code == 403


async def test_inactive_user_is_403(api: httpx.AsyncClient, session: AsyncSession) -> None:
    session.add(User(name="Ex", email="ex@cassol.ind.br", role="admin", active=False))
    await session.flush()
    r = await api.get("/api/me", headers=bearer(token("ex@cassol.ind.br")))
    assert r.status_code == 403
    assert "desativado" in r.json()["detail"]


# ------------------------------------------------------------------ grupos do Entra


async def test_role_from_entra_group_with_priority(
    session: AsyncSession, jwks: respx.Route
) -> None:
    groups = f"admin={G_ADMIN};fabrica={G_FABRICA}"
    async with await _api_with(session, entra_role_groups=groups) as c:
        r = await c.get("/api/me", headers=bearer(token(groups=[G_FABRICA])))
        assert r.json()["role"] == "fabrica"
        r = await c.get(
            "/api/me", headers=bearer(token("b@cassol.ind.br", groups=[G_FABRICA, G_ADMIN.upper()]))
        )
        assert r.json()["role"] == "admin"  # 1º da lista vence; id sem diferenciar caixa


async def test_group_overrides_table_and_no_group_means_leitura(
    session: AsyncSession, jwks: respx.Route
) -> None:
    session.add(User(name="P", email="p@cassol.ind.br", role="projetos", active=True))
    await session.flush()
    async with await _api_with(session, entra_role_groups=f"admin={G_ADMIN}") as c:
        r = await c.get("/api/me", headers=bearer(token("p@cassol.ind.br", groups=["outro"])))
        assert r.json()["role"] == "leitura"
    user = await _user(session, "p@cassol.ind.br")
    assert user is not None
    audit = await session.scalar(
        select(AuditLog).where(
            AuditLog.entity == "user",
            AuditLog.entity_id == str(user.id),
            AuditLog.action == "update",
        )
    )
    assert audit is not None
    assert audit.before is not None and audit.before["role"] == "projetos"
    assert audit.after is not None and audit.after["role"] == "leitura"


async def test_groups_missing_in_token_keeps_table_role(
    session: AsyncSession, jwks: respx.Route
) -> None:
    session.add(User(name="P", email="p@cassol.ind.br", role="projetos", active=True))
    await session.flush()
    async with await _api_with(session, entra_role_groups=f"admin={G_ADMIN}") as c:
        r = await c.get("/api/me", headers=bearer(token("p@cassol.ind.br")))
        assert r.json()["role"] == "projetos"
        # excesso de grupos (> 200): o token traz _claim_names e não a lista
        over = token("p@cassol.ind.br", _claim_names={"groups": "src1"})
        assert (await c.get("/api/me", headers=bearer(over))).json()["role"] == "projetos"


async def test_bootstrap_admin_wins_over_groups(session: AsyncSession, jwks: respx.Route) -> None:
    async with await _api_with(session, entra_role_groups=f"fabrica={G_FABRICA}") as c:
        r = await c.get(
            "/api/me", headers=bearer(token("vhbastos@cassol.ind.br", groups=[G_FABRICA]))
        )
        assert r.json()["role"] == "admin"


def test_role_groups_parsing() -> None:
    assert parse_role_groups(" Admin = AB ; fabrica=cd,") == [("admin", "ab"), ("fabrica", "cd")]
    assert parse_role_groups("") == []
    for bad in ("chefe=1", "admin", "admin="):
        with pytest.raises(ValueError, match="ENTRA_ROLE_GROUPS"):
            parse_role_groups(bad)


# ------------------------------------------------------------------ JWKS


async def test_jwks_cached_and_refetched_on_unknown_kid() -> None:
    now = [1000.0]
    settings = make_settings(**ENTRA)
    with respx.mock() as mock:
        route = mock.get(jwks_url(TENANT)).respond(json={"keys": [_jwk(KEY, "k1")]})
        async with httpx.AsyncClient() as http:
            v = EntraVerifier(settings, http=http, clock=lambda: now[0])
            await v.verify(token())
            await v.verify(token())
            assert route.call_count == 1  # cache
            # a Microsoft girou as chaves: kid novo
            route.respond(json={"keys": [_jwk(KEY, "k1"), _jwk(OTHER_KEY, "k2")]})
            with pytest.raises(TokenError, match="chave"):
                await v.verify(token(key=OTHER_KEY, kid="k2"))  # < 60 s: não rebusca
            assert route.call_count == 1
            now[0] += 61
            identity = await v.verify(token(key=OTHER_KEY, kid="k2"))
            assert identity.email == "fulano@cassol.ind.br"
            assert route.call_count == 2
            now[0] += 25 * 3600  # cache venceu
            await v.verify(token())
            assert route.call_count == 3


async def test_jwks_unavailable_is_503(session: AsyncSession) -> None:
    with respx.mock() as mock:
        mock.get(jwks_url(TENANT)).respond(status_code=500)
        async with await _api_with(session) as c:
            r = await c.get("/api/me", headers=bearer(token()))
    assert r.status_code == 503
    assert "Microsoft" in r.json()["detail"]


# ------------------------------------------------------------------ X-Dev-User e config


@pytest.mark.parametrize("env", ["prod", "staging", "test"])
async def test_dev_user_header_refused_outside_dev(
    session: AsyncSession, users: dict[Role, User], env: str
) -> None:
    async with await _api_with(session, app_env=env) as c:
        r = await c.get("/api/me", headers=as_user(users[Role.ADMIN]))
        assert r.status_code == 401
        assert "Microsoft" in r.json()["detail"]
        assert (await c.get("/api/dev/users")).status_code == 404


async def test_dev_user_still_works_in_dev_and_bearer_too(
    session: AsyncSession, users: dict[Role, User], jwks: respx.Route
) -> None:
    async with await _api_with(session, app_env="dev") as c:
        r = await c.get("/api/me", headers=as_user(users[Role.FABRICA]))
        assert r.status_code == 200 and r.json()["role"] == "fabrica"
        r = await c.get("/api/me", headers=bearer(token("vhbastos@cassol.ind.br")))
        assert r.status_code == 200 and r.json()["role"] == "admin"


async def test_bearer_without_entra_configured_is_401(session: AsyncSession) -> None:
    async with await _api_with(session, app_env="dev", entra_client_id="") as c:
        r = await c.get("/api/me", headers=bearer(token()))
        assert r.status_code == 401
        assert "não configurado" in r.json()["detail"]


async def test_auth_config_endpoint(session: AsyncSession) -> None:
    async with await _api_with(session) as c:
        r = await c.get("/api/auth/config")
    assert r.status_code == 200
    assert r.json() == {
        "client_id": CLIENT,
        "tenant_id": TENANT,
        "scope": f"api://{CLIENT}/access_as_user",
        "dev_login": False,
    }
    async with await _api_with(session, app_env="dev", entra_client_id="") as c:
        r = await c.get("/api/auth/config")
    assert r.json() == {"client_id": "", "tenant_id": "", "scope": "", "dev_login": True}


async def test_custom_scope_sets_audience(session: AsyncSession) -> None:
    scope = "api://bim.cassol.ind.br/acesso"
    with respx.mock() as mock:
        mock.get(jwks_url(TENANT)).respond(json={"keys": [_jwk(KEY, "k1")]})
        async with await _api_with(session, entra_api_scope=scope) as c:
            t = token(aud="api://bim.cassol.ind.br", scp="acesso")
            assert (await c.get("/api/me", headers=bearer(t))).status_code == 200


async def test_metrics_accepts_admin_microsoft_token(
    session: AsyncSession, jwks: respx.Route
) -> None:
    async with await _api_with(session, metrics_token="coletor-123") as c:
        r = await c.get("/api/metrics", headers=bearer(token("vhbastos@cassol.ind.br")))
        assert r.status_code == 200, r.text
        assert (await c.get("/api/metrics", headers=bearer(token()))).status_code == 403


# ------------------------------------------------------------------ cli users


async def test_cli_users_set_role_list_and_deactivate(
    session: AsyncSession, aps: Any, capsys: pytest.CaptureFixture[str], jwks: respx.Route
) -> None:
    from app.cli import run as cli_run

    s = make_settings()
    # cria antes do 1º login, com nome; o login depois acha o mesmo usuário e o papel
    args = ["users", "set-role", "Fabio@Cassol.ind.br", "fabrica", "--name", "Fábio"]
    assert await cli_run(args, s, session, aps) == 0
    assert (
        await cli_run(["users", "set-role", "fabio@cassol.ind.br", "admin"], s, session, aps) == 0
    )
    assert await cli_run(["users", "list"], s, session, aps) == 0
    assert "admin     fabio@cassol.ind.br" in capsys.readouterr().out
    async with await _api_with(session) as c:
        r = await c.get("/api/me", headers=bearer(token("fabio@cassol.ind.br")))
        assert (r.json()["role"], r.json()["name"]) == ("admin", "Fábio")
        assert await cli_run(["users", "deactivate", "fabio@cassol.ind.br"], s, session, aps) == 0
        r = await c.get("/api/me", headers=bearer(token("fabio@cassol.ind.br")))
        assert r.status_code == 403
    assert await cli_run(["users", "activate", "ninguem@cassol.ind.br"], s, session, aps) == 1
    user = await _user(session, "fabio@cassol.ind.br")
    assert user is not None
    actions = list(
        await session.scalars(
            select(AuditLog.action)
            .where(AuditLog.entity == "user", AuditLog.entity_id == str(user.id))
            .order_by(AuditLog.id)
        )
    )
    assert actions == ["create", "update", "update"]
