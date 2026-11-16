from __future__ import annotations

import httpx

from tests.conftest import build_app


async def test_health_does_not_need_database() -> None:
    app = build_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "env": "dev"}


def test_settings_parse_mark_property_names() -> None:
    from tests.conftest import make_settings

    s = make_settings(mark_property_names=" Marca , Mark,, ")
    assert s.mark_property_list == ["Marca", "Mark"]
    assert "segredo" not in repr(make_settings(aps_client_secret="segredo"))


def test_make_settings_ignores_env_and_dotenv(monkeypatch: object) -> None:
    import pytest

    from tests.conftest import make_settings

    assert isinstance(monkeypatch, pytest.MonkeyPatch)
    monkeypatch.setenv("APS_WEBHOOK_SECRET", "vindo-do-ambiente")
    monkeypatch.setenv("APP_ENV", "prod")
    s = make_settings()
    assert s.aps_webhook_secret.get_secret_value() == ""
    assert s.app_env == "dev"
