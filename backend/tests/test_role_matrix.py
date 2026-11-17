"""Matriz de papéis (10.2): TODAS as rotas da API × projetos, fábrica, admin, leitura
e anônimo.

- papel permitido: nunca 401/403 (ids inexistentes dão 404/422, e tudo bem);
- papel negado: 403; anônimo (sem X-Dev-User): 401;
- rotas públicas têm proteção própria (assinatura do webhook, só dev) e ficam anotadas.

`test_matrix_covers_every_route` falha se surgir rota nova fora da matriz: quem cria
um endpoint precisa decidir quem pode usá-lo. A mesma tabela está em docs/operacao.md.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

import httpx
import pytest
import respx
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.models.enums import Role
from tests.apsfakes import BASE
from tests.conftest import as_user, build_app

P, F, A, L = Role.PROJETOS, Role.FABRICA, Role.ADMIN, Role.LEITURA
ALL = frozenset({P, F, A, L})
EDITOR = frozenset({P, A})  # cadastro de obras e navegação no Docs
SYNC = frozenset({P, F, A})  # "Sincronizar agora"
FACTORY = frozenset({F, A})  # parâmetros da fábrica
ADMIN = frozenset({A})
PUBLIC = "public"  # sem usuário: saúde, lista de usuários do dev, webhook (assinatura)

MATRIX: dict[str, frozenset[Role] | str] = {
    "GET /api/health": PUBLIC,
    "GET /api/ready": PUBLIC,
    "GET /api/metrics": ADMIN,  # ou o coletor com Bearer METRICS_TOKEN
    "GET /api/me": ALL,
    "GET /api/dev/users": PUBLIC,  # 404 fora de dev
    "GET /api/acc/hubs": EDITOR,
    "GET /api/acc/hubs/{hub_id}/projects": EDITOR,
    "GET /api/acc/hubs/{hub_id}/projects/{project_id}/top-folders": EDITOR,
    "GET /api/acc/projects/{project_id}/folders/{folder_id}": EDITOR,
    "GET /api/obras": ALL,
    "POST /api/obras": EDITOR,
    "GET /api/obras/{obra_id}": ALL,
    "PATCH /api/obras/{obra_id}": EDITOR,
    "DELETE /api/obras/{obra_id}": EDITOR,  # com valores preenchidos, só admin (serviço)
    "GET /api/obras/{obra_id}/delete-preview": EDITOR,
    "GET /api/obras/{obra_id}/versions": ALL,
    "POST /api/obras/{obra_id}/sync": SYNC,
    "GET /api/obras/{obra_id}/mark-rule": ALL,
    "POST /api/obras/{obra_id}/params/{def_id}": FACTORY,  # incluir parâmetro da biblioteca
    "DELETE /api/obras/{obra_id}/params/{def_id}": FACTORY,  # retirar da obra
    "PUT /api/obras/{obra_id}/mark-rule": ALL,  # decisão de 2026-11-13: todos definem
    "GET /api/obras/{obra_id}/marks/{mark_id}/values": ALL,
    "PUT /api/obras/{obra_id}/marks/{mark_id}/values": FACTORY,
    "GET /api/obras/{obra_id}/marks/{mark_id}/history": ALL,
    "POST /api/obras/{obra_id}/marks/batch-preview": ALL,  # só calcula, não grava
    "POST /api/obras/{obra_id}/marks/batch-apply": FACTORY,
    # parâmetros por peça (P2): leitura para todos, gravação fábrica e admin
    "GET /api/obras/{obra_id}/marks/{mark_id}/units": ALL,
    "GET /api/obras/{obra_id}/units/{unit_id}": ALL,
    "PUT /api/obras/{obra_id}/units/{unit_id}/values": FACTORY,
    "GET /api/obras/{obra_id}/units/{unit_id}/history": ALL,
    "POST /api/obras/{obra_id}/units/batch-preview": ALL,  # só calcula, não grava
    "POST /api/obras/{obra_id}/units/batch-apply": FACTORY,
    "GET /api/obras/{obra_id}/unit-orphans": ALL,
    "POST /api/obras/{obra_id}/units/{unit_id}/relink": FACTORY,
    "POST /api/obras/{obra_id}/units/{unit_id}/archive": FACTORY,
    "GET /api/obras/{obra_id}/orphans": ALL,
    "GET /api/obras/{obra_id}/events": ALL,
    "GET /api/obras/{obra_id}/export.xlsx": ALL,
    "POST /api/obras/{obra_id}/export.xlsx": ALL,
    "POST /api/batches/{batch_id}/undo": FACTORY,
    "POST /api/marks/{mark_id}/review/keep": FACTORY,
    "POST /api/orphans/{orphan_id}/relink": FACTORY,
    "POST /api/orphans/{orphan_id}/archive": FACTORY,
    "GET /api/param-defs": ALL,
    "POST /api/param-defs": FACTORY,
    "PATCH /api/param-defs/{def_id}": FACTORY,
    "DELETE /api/param-defs/{def_id}": FACTORY,
    "GET /api/versions/{version_id}/report": ALL,
    "GET /api/versions/{version_id}/marks": ALL,
    "GET /api/versions/{version_id}/elements/{dbid}": ALL,
    "GET /api/versions/{version_id}/marks/search": ALL,
    "GET /api/versions/{version_id}/marks/facets": ALL,
    "GET /api/versions/{version_id}/marks/status": ALL,
    "GET /api/versions/{version_id}/progress": ALL,
    "GET /api/versions/{version_id}/params/{def_id}/values": ALL,
    "GET /api/versions/{version_id}/diff": ALL,
    "GET /api/versions/{version_id}/mark-candidates": ALL,
    "GET /api/versions/{version_id}/fields": ALL,
    "GET /api/versions/{version_id}/fields/{source}/{key}/values": ALL,
    "POST /api/versions/{version_id}/filter/evaluate": ALL,
    "POST /api/versions/{version_id}/color-scheme/evaluate": ALL,
    "POST /api/versions/{version_id}/colorize": ALL,
    # filtros salvos e esquemas de cores: pessoais para todos; os compartilhados exigem
    # SHARED_FILTER_ROLES (padrão fábrica e admin), checado no serviço (test_saved_filters)
    "GET /api/saved-filters": ALL,
    "POST /api/saved-filters": ALL,
    "GET /api/saved-filters/{filter_id}": ALL,
    "PATCH /api/saved-filters/{filter_id}": ALL,
    "DELETE /api/saved-filters/{filter_id}": ALL,
    "GET /api/color-schemes": ALL,
    "POST /api/color-schemes": ALL,
    "GET /api/color-schemes/{scheme_id}": ALL,
    "PATCH /api/color-schemes/{scheme_id}": ALL,
    "DELETE /api/color-schemes/{scheme_id}": ALL,
    "GET /api/viewer-token": ALL,
    "GET /api/viewer-config": ALL,
    "POST /api/webhooks/aps": PUBLIC,  # assinatura x-adsk-signature
}

_PARAM = re.compile(r"\{[^}]+\}")


def app_routes() -> set[str]:
    spec = build_app().openapi()
    return {
        f"{method.upper()} {path}"
        for path, ops in spec["paths"].items()
        for method in ops
        if method in ("get", "post", "put", "patch", "delete")
    }


def test_matrix_covers_every_route() -> None:
    routes = app_routes()
    assert routes - MATRIX.keys() == set(), "rota sem papel definido na matriz"
    assert MATRIX.keys() - routes == set(), "rota da matriz não existe mais"


@pytest.fixture
def aps_404() -> Iterator[None]:
    """Qualquer chamada ao APS responde 404 (nunca 403, para não confundir com papel)."""
    with respx.mock(base_url=BASE, assert_all_called=False) as router:
        router.route().respond(404, json={})
        yield


async def _call(client: httpx.AsyncClient, route: str, headers: dict[str, str]) -> int:
    method, path = route.split(" ", 1)
    url = _PARAM.sub("999999", path)
    body: dict[str, object] | None = {} if method in ("POST", "PUT", "PATCH") else None
    r = await client.request(method, url, headers=headers, json=body)
    return r.status_code


@pytest.mark.parametrize("route", sorted(MATRIX))
async def test_role_matrix(
    client: httpx.AsyncClient, users: dict[Role, User], aps_404: None, route: str
) -> None:
    access = MATRIX[route]
    results: dict[str, int] = {}
    for role in Role:
        results[role.value] = await _call(client, route, as_user(users[role]))
    results["anônimo"] = await _call(client, route, {})

    wrong: list[str] = []
    if access == PUBLIC:
        wrong = [f"{who}: {code}" for who, code in results.items() if code == 403]
    else:
        assert isinstance(access, frozenset)
        for role in Role:
            code = results[role.value]
            if role in access and code in (401, 403):
                wrong.append(f"{role.value} deveria poder ({code})")
            if role not in access and code != 403:
                wrong.append(f"{role.value} deveria receber 403 ({code})")
        if results["anônimo"] != 401:
            wrong.append(f"anônimo deveria receber 401 ({results['anônimo']})")
    assert wrong == [], f"{route}: {wrong}"


async def test_webhook_without_signature_is_rejected(client: httpx.AsyncClient) -> None:
    r = await client.post("/api/webhooks/aps", json={})
    assert r.status_code in (401, 503)


async def test_dev_users_hidden_outside_dev() -> None:
    app = build_app(app_env="test")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        assert (await c.get("/api/dev/users")).status_code == 404
        # fora de dev o usuário simulado não vale: tudo que pede usuário dá 401
        assert (await c.get("/api/obras", headers={"X-Dev-User": "1"})).status_code == 401


async def test_staging_with_dev_users_for_the_factory_pilot(
    session: AsyncSession, users: dict[Role, User]
) -> None:
    """Ambiente de teste com a fábrica (10.3): usuário simulado e papéis valem iguais."""
    app = build_app(session, app_env="staging", dev_users_enabled=True)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        assert (await c.get("/api/dev/users")).status_code == 200
        assert (await c.get("/api/obras", headers=as_user(users[Role.LEITURA]))).status_code == 200
        r = await c.post("/api/param-defs", json={}, headers=as_user(users[Role.PROJETOS]))
        assert r.status_code == 403
        assert (await c.get("/docs")).status_code == 404  # endurecimento continua
