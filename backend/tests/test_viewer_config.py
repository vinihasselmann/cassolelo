"""Coordenadas do eixo: AXIS_Z_RULE (configuração) e GET /api/viewer-config."""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import parse_axis_z_rule
from app.models import User
from app.models.enums import Role
from tests.conftest import as_user, build_app, make_settings


def test_parse_axis_z_rule_default_and_overrides() -> None:
    assert parse_axis_z_rule("Pilar=base;Viga=meia altura;Laje=face inferior") == {
        "pilar": "base",
        "viga": "meia altura",
        "laje": "face inferior",
    }
    # sem diferenciar maiúsculas, espaços extras; tipo omitido fica com o padrão
    assert parse_axis_z_rule(" pilar = TOPO ; laje=Face  Superior") == {
        "pilar": "topo",
        "viga": "meia altura",
        "laje": "face superior",
    }
    assert parse_axis_z_rule("") == parse_axis_z_rule("Pilar=base")


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("Parede=base", "tipo inválido"),
        ("Pilar", "tipo inválido"),
        ("Pilar=meia altura", "Pilar aceita base, topo"),
        ("Laje=base", "Laje aceita face inferior, face superior"),
    ],
)
def test_parse_axis_z_rule_rejects_invalid(text: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse_axis_z_rule(text)


def test_invalid_rule_fails_at_startup() -> None:
    with pytest.raises(ValueError, match="AXIS_Z_RULE"):
        make_settings(axis_z_rule="Viga=topo")


async def test_viewer_config_returns_the_rule(
    session: AsyncSession, users: dict[Role, User]
) -> None:
    app = build_app(session, axis_z_rule="Pilar=topo")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.get("/api/viewer-config", headers=as_user(users[Role.LEITURA]))
        assert r.status_code == 200
        assert r.json() == {
            "axis_z_rule": {"pilar": "topo", "viga": "meia altura", "laje": "face inferior"}
        }
        assert (await c.get("/api/viewer-config")).status_code == 401
