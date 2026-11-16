"""Integração com o Autodesk Platform Services (somente leitura).

Credenciais ficam só no backend. O frontend recebe, no máximo, tokens curtos
com viewables:read (Fase 4).
"""

from __future__ import annotations

import httpx

from app.aps.auth import TokenProvider
from app.aps.client import ApsClient
from app.config import Settings


def build_aps_client(settings: Settings, *, timeout: float = 30.0) -> ApsClient:
    http = httpx.AsyncClient(base_url=settings.aps_base_url, timeout=timeout)
    tokens = TokenProvider(
        client_id=settings.aps_client_id,
        client_secret=settings.aps_client_secret,
        http=http,
    )
    client = ApsClient(http=http, tokens=tokens, region=settings.aps_region)
    # Falhas de leitura e erros de credencial viram métricas/alertas (Fase 10.1).
    from app.observability.metrics import record_aps_error

    client.error_hooks.append(record_aps_error)
    return client


__all__ = ["ApsClient", "TokenProvider", "build_aps_client"]
