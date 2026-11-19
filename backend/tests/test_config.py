from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource

from app.config import Settings, get_settings
from tests.conftest import make_settings


def test_default_redis_url_uses_ipv4_loopback() -> None:
    # No Windows, "localhost" tenta ::1 primeiro; o compose publica só em 127.0.0.1
    # e a recusa demora ~2 s, estourando o conn_timeout do Arq.
    assert urlsplit(make_settings().redis_url).hostname == "127.0.0.1"


# --------------------------------------------------------------------------- 10.3


class _SecretsOnly(Settings):
    """Só init + arquivos de segredo (ignora o .env real da máquina)."""

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (init_settings, file_secret_settings)


def test_secrets_are_read_from_files(tmp_path: Path) -> None:
    (tmp_path / "database_url").write_text("postgresql+asyncpg://u:p@db:5432/bim\n")
    (tmp_path / "aps_client_secret").write_text("s3cr3t")
    (tmp_path / "metrics_token").write_text("tok")
    s = _SecretsOnly(_secrets_dir=tmp_path)
    assert s.database_url == "postgresql+asyncpg://u:p@db:5432/bim"
    assert s.aps_client_secret.get_secret_value() == "s3cr3t"
    assert s.metrics_token.get_secret_value() == "tok"
    assert "s3cr3t" not in repr(s)  # SecretStr não aparece em log/repr


def test_get_settings_uses_secrets_dir_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "smtp_password").write_text("senha-smtp")
    monkeypatch.setenv("SECRETS_DIR", str(tmp_path))
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@db:5432/bim")
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)
    monkeypatch.setattr(Settings, "model_config", {**Settings.model_config, "env_file": ()})
    get_settings.cache_clear()
    try:
        assert get_settings().smtp_password.get_secret_value() == "senha-smtp"
    finally:
        get_settings.cache_clear()


def test_dev_users_only_in_dev() -> None:
    assert make_settings(app_env="dev").dev_users_allowed
    for env in ("staging", "test", "prod"):
        assert not make_settings(app_env=env, **ENTRA_OK).dev_users_allowed


@pytest.mark.parametrize("env", ["staging", "test", "prod"])
def test_dev_users_flag_refused_outside_dev(env: str) -> None:
    with pytest.raises(ValueError, match="DEV_USERS_ENABLED foi removido"):
        make_settings(app_env=env, dev_users_enabled=True, **ENTRA_OK)


ENTRA_OK: dict[str, Any] = {"entra_client_id": "cid", "entra_tenant_id": "tid"}


def test_prod_requires_entra_and_domains() -> None:
    with pytest.raises(ValueError, match="ENTRA_CLIENT_ID"):
        make_settings(app_env="prod")
    with pytest.raises(ValueError, match="ALLOWED_EMAIL_DOMAINS"):
        make_settings(app_env="prod", allowed_email_domains=" ", **ENTRA_OK)
    s = make_settings(app_env="prod", **ENTRA_OK)
    assert s.allowed_email_domain_list == ["cassol.ind.br"]
    assert s.bootstrap_admin_list == ["vhbastos@cassol.ind.br"]
    assert s.entra_scope == "api://cid/access_as_user"
    make_settings(app_env="staging")  # staging sobe sem login (só responde 401)


def test_invalid_role_groups_fail_at_startup() -> None:
    with pytest.raises(ValueError, match="ENTRA_ROLE_GROUPS"):
        make_settings(entra_role_groups="gerente=abc")
