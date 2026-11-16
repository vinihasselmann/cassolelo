"""Model Derivative API: SOMENTE GET (manifest, metadata, properties, árvore).

Este módulo não tem, e não pode ter, função que dispare conversão (POST /job).
Se o Docs não converteu o arquivo, levantamos ApsNoTranslationError.
"""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Awaitable, Callable
from typing import Any

from app.aps.client import ApsClient
from app.aps.errors import ApsError, ApsNotFoundError, ApsNoTranslationError
from app.aps.schemas import Manifest, PropertyObject, TreeNode, Version, ViewMeta

NO_TRANSLATION_MSG = "arquivo sem conversão no Docs"


def to_urn(derivative_id: str) -> str:
    """URN em base64 url-safe sem padding (aceita id cru 'urn:...' ou já codificado)."""
    if derivative_id.startswith("urn:"):
        return base64.urlsafe_b64encode(derivative_id.encode()).decode().rstrip("=")
    return derivative_id.replace("+", "-").replace("/", "_").rstrip("=")


def urn_from_version(version: Version) -> str | None:
    return to_urn(version.derivative_id) if version.derivative_id else None


async def get_manifest(c: ApsClient, urn: str) -> Manifest:
    try:
        body = await c.get_json(f"{c.md_prefix}/{urn}/manifest")
    except ApsNotFoundError as exc:
        raise ApsNoTranslationError(NO_TRANSLATION_MSG) from exc
    return Manifest.model_validate(body)


async def get_metadata(c: ApsClient, urn: str) -> list[ViewMeta]:
    body = await c.get_json(f"{c.md_prefix}/{urn}/metadata")
    views = (body.get("data") or {}).get("metadata") or []
    return [ViewMeta.model_validate(v) for v in views]


def choose_3d_view(views: list[ViewMeta]) -> ViewMeta:
    views3d = [v for v in views if v.role == "3d"]
    if not views3d:
        raise ApsError("O derivativo não tem vista 3D.")
    master = [v for v in views3d if v.is_master_view]
    return (master or views3d)[0]


async def _poll_json(
    c: ApsClient,
    path: str,
    *,
    poll_seconds: float,
    max_wait_seconds: float,
    sleep: Callable[[float], Awaitable[None]],
) -> dict[str, Any]:
    """202 = ainda processando (espera e repete); 413 = grande demais (forceget=true)."""
    params: dict[str, str] = {}
    waited = 0.0
    while True:
        resp = await c.request("GET", path, params=params or None, allow_status=(202, 413))
        if resp.status_code == 202:
            if waited >= max_wait_seconds:
                raise ApsError(f"Propriedades ainda em processamento após {waited:.0f}s.")
            await sleep(poll_seconds)
            waited += poll_seconds
            continue
        if resp.status_code == 413:
            if "forceget" in params:
                raise ApsError("Resposta grande demais mesmo com forceget=true.")
            params["forceget"] = "true"
            continue
        body: dict[str, Any] = resp.json()
        return body


async def get_properties(
    c: ApsClient,
    urn: str,
    guid: str,
    *,
    poll_seconds: float = 5.0,
    max_wait_seconds: float = 600.0,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> list[PropertyObject]:
    body = await _poll_json(
        c,
        f"{c.md_prefix}/{urn}/metadata/{guid}/properties",
        poll_seconds=poll_seconds,
        max_wait_seconds=max_wait_seconds,
        sleep=sleep,
    )
    coll = (body.get("data") or {}).get("collection") or []
    return [PropertyObject.model_validate(p) for p in coll]


async def get_object_tree(
    c: ApsClient,
    urn: str,
    guid: str,
    *,
    poll_seconds: float = 5.0,
    max_wait_seconds: float = 600.0,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> list[TreeNode]:
    body = await _poll_json(
        c,
        f"{c.md_prefix}/{urn}/metadata/{guid}",
        poll_seconds=poll_seconds,
        max_wait_seconds=max_wait_seconds,
        sleep=sleep,
    )
    objs = (body.get("data") or {}).get("objects") or []
    return [TreeNode.model_validate(o) for o in objs]
