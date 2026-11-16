"""Configuração da aplicação (pydantic-settings).

Lê variáveis de ambiente e, se existirem, infra/.env e backend/.env.
Segredos ficam só nesses arquivos (fora do git) e nunca são logados.

Produção/teste (10.3): segredos por ARQUIVO, um por campo, em SECRETS_DIR (Docker
secrets: /run/secrets/aps_client_secret, /run/secrets/database_url, ...). Variável
de ambiente e .env têm precedência; em produção eles não levam segredo.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]

AppEnv = Literal["dev", "test", "staging", "prod"]
ApsRegion = Literal["US", "EMEA", "AUS"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / "infra" / ".env", REPO_ROOT / "backend" / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: AppEnv = "dev"
    # Usuário simulado (X-Dev-User) fora de dev, até a Fase 11: só no ambiente de teste
    # com a fábrica (APP_ENV=staging). Com APP_ENV=prod o backend não sobe com ele ligado.
    dev_users_enabled: bool = False
    log_level: str = "INFO"
    # Observabilidade (10.1): json (uma linha por evento, para o coletor) ou text
    log_format: Literal["json", "text"] = "json"
    # GET /api/metrics também aceita "Authorization: Bearer <METRICS_TOKEN>" (coletor)
    metrics_token: SecretStr = SecretStr("")
    # Alertas: Teams (Workflows) e/ou e-mail. Sem nenhum, só vão para o log.
    alert_teams_webhook_url: SecretStr = SecretStr("")
    alert_email_to: str = ""  # lista separada por vírgulas
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: SecretStr = SecretStr("")
    smtp_from: str = ""
    smtp_starttls: bool = True
    # Backup (10.3): alerta se não houver backup bem-sucedido nesse intervalo; 0 desliga
    backup_max_age_hours: int = 0
    # Endereço do app para links nos alertas (ex.: https://bim.cassol.local)
    app_base_url: str = ""

    # Segurança (10.2). CORS: origens permitidas, separadas por vírgulas; vazio = só a
    # origem de APP_BASE_URL (fora de dev). "*" é recusado. Em dev o Vite repassa /api.
    cors_origins: str = ""
    # HSTS (só fora de dev): max-age em segundos; 0 desliga
    hsts_max_age: int = 31_536_000
    # Escritas (POST/PUT/PATCH/DELETE) por usuário por minuto; 0 desliga
    rate_limit_writes_per_min: int = 120

    database_url: str
    # 127.0.0.1, não "localhost": no Windows ele tenta ::1 antes e a recusa leva ~2 s
    redis_url: str = "redis://127.0.0.1:6379/0"

    aps_client_id: str = ""
    aps_client_secret: SecretStr = SecretStr("")
    aps_region: ApsRegion = "US"
    aps_base_url: str = "https://developer.api.autodesk.com"

    mark_property_names: str = "Marca,Mark"
    # Propriedade de categoria, em ordem de preferência; sem nenhuma, usa a categoria da
    # árvore do modelo (1º nível abaixo da raiz). Confirmar os nomes reais na Fase 0.
    category_property_names: str = "Category,Categoria,IfcClass"
    # Montagens (.nwd/.rvt com vínculos): categorias do "corpo" da peça, sugeridas ao
    # ligar o modo montagens numa obra (pilares, vigas e lajes alveolares).
    piece_category_names: str = "Pilares estruturais,Quadro estrutural"
    # Validação de marcas (3.2): dimensões comparadas entre peças da mesma marca+categoria
    # Nomes reais confirmados no modelo da Cassol (Fase 0): SEÇÃO-*, PEÇA-Comprimento.
    # IFC (montagens, obra 9480): só NetVolume. Length/Width/Height do BaseQuantities vêm
    # com os eixos trocados em parte das peças idênticas (falsos alertas); o volume não.
    dimension_property_names: str = (
        "SEÇÃO-Altura,SEÇÃO-Largura,PEÇA-Comprimento,Comprimento,Largura,Altura,NetVolume"
    )
    dimension_tolerance_mm: float = 5.0
    # Reconciliação (7.1): além das dimensões acima, propriedades cuja mudança entre
    # versões manda a marca para "revisar" (texto). Padrão: só o tipo (Revit "Nome do
    # tipo"; IFC ObjectType), que existe em qualquer modelo. Nenhuma propriedade da
    # fábrica é obrigatória: outras entram por configuração, conforme o uso.
    # Datas mostradas e exportadas (Excel, 9.1)
    display_timezone: str = "America/Sao_Paulo"
    # Tempo real (8.1): intervalo do heartbeat do SSE /api/obras/{id}/events
    sse_heartbeat_seconds: float = 20.0
    review_property_names: str = "Nome do tipo,Type Name,ObjectType"
    # Filtros salvos e esquemas de cores COMPARTILHADOS: papéis que criam, editam e
    # excluem (os pessoais, só o dono). Valores: fabrica, admin, projetos, leitura.
    shared_filter_roles: str = "fabrica,admin"
    # Busca (5.1): nível da peça e propriedades cujos VALORES entram no texto livre
    level_property_names: str = (
        "Nível,Level,Nível base,Base Level,Nível de referência,Reference Level,"
        "Restrição da base,Base Constraint,IfcSpatialContainer"
    )
    search_property_names: str = (
        "Tipo,Type,Type Name,Nome do tipo,Família e tipo,Family and Type,Família,Family,"
        "Seção,Section,Material estrutural,Structural Material,ObjectType"
    )

    # Webhooks APS: secret da assinatura x-adsk-signature e URL pública do backend
    # (ex.: túnel https://abc.trycloudflare.com). Sem PUBLIC_BASE_URL, os hooks não
    # são registrados automaticamente e só a verificação periódica encontra versões.
    aps_webhook_secret: SecretStr = SecretStr("")
    public_base_url: str | None = None

    @property
    def webhook_callback_url(self) -> str | None:
        if not self.public_base_url:
            return None
        return self.public_base_url.rstrip("/") + "/api/webhooks/aps"

    @property
    def alert_email_list(self) -> list[str]:
        return [e.strip() for e in self.alert_email_to.split(",") if e.strip()]

    @property
    def piece_category_list(self) -> list[str]:
        return [n.strip() for n in self.piece_category_names.split(",") if n.strip()]

    @property
    def mark_property_list(self) -> list[str]:
        return [n.strip() for n in self.mark_property_names.split(",") if n.strip()]

    @property
    def category_property_list(self) -> list[str]:
        return [n.strip() for n in self.category_property_names.split(",") if n.strip()]

    @property
    def level_property_list(self) -> list[str]:
        return [n.strip() for n in self.level_property_names.split(",") if n.strip()]

    @property
    def search_property_list(self) -> list[str]:
        return [n.strip() for n in self.search_property_names.split(",") if n.strip()]

    @property
    def dimension_property_list(self) -> list[str]:
        return [n.strip() for n in self.dimension_property_names.split(",") if n.strip()]

    @property
    def shared_filter_role_list(self) -> list[str]:
        return [n.strip().lower() for n in self.shared_filter_roles.split(",") if n.strip()]

    @property
    def review_property_list(self) -> list[str]:
        return [n.strip() for n in self.review_property_names.split(",") if n.strip()]

    @property
    def cors_origin_list(self) -> list[str]:
        """Origens CORS normalizadas (esquema://host[:porta], sem barra final)."""
        raw = [o.strip() for o in self.cors_origins.split(",") if o.strip()]
        if not raw and self.app_base_url and not self.is_dev:
            raw = [self.app_base_url]
        origins: list[str] = []
        for value in raw:
            if "*" in value:
                raise ValueError("CORS_ORIGINS não aceita '*': informe o domínio do app.")
            parts = urlsplit(value)
            if parts.scheme not in ("http", "https") or not parts.netloc:
                raise ValueError(f"Origem CORS inválida: {value!r} (use https://dominio).")
            origins.append(f"{parts.scheme}://{parts.netloc}")
        return origins

    @property
    def is_dev(self) -> bool:
        return self.app_env == "dev"

    @property
    def dev_users_allowed(self) -> bool:
        """X-Dev-User vale: sempre em dev; em staging só com DEV_USERS_ENABLED."""
        return self.is_dev or (self.app_env == "staging" and self.dev_users_enabled)

    @model_validator(mode="after")
    def _no_dev_users_in_prod(self) -> Settings:
        if self.dev_users_enabled and self.app_env == "prod":
            raise ValueError("DEV_USERS_ENABLED não é permitido com APP_ENV=prod.")
        return self


@lru_cache
def get_settings() -> Settings:
    # database_url vem do ambiente/.env ou do arquivo SECRETS_DIR/database_url
    secrets_dir = os.getenv("SECRETS_DIR") or None
    return Settings(_secrets_dir=secrets_dir)
