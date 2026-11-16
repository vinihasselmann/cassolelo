"""Utilitários de teste: respostas gravadas do APS, sleep falso e fila falsa."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import respx

from app.aps.auth import TOKEN_PATH

BASE = "https://developer.api.autodesk.com"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "aps"


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def mock_token(router: respx.Router | None = None) -> respx.Route:
    r = router if router is not None else respx
    return r.post(f"{BASE}{TOKEN_PATH}").respond(200, json=fixture("token.json"))


class Sleeps:
    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


class FakeQueue:
    """Registra os jobs; `fail=True` simula Redis fora do ar."""

    def __init__(self, fail: bool = False) -> None:
        self.jobs: list[tuple[str, tuple[Any, ...], str | None]] = []
        self.fail = fail

    async def enqueue(self, function: str, *args: Any, job_id: str | None = None) -> None:
        if self.fail:
            raise ConnectionError("redis indisponível")
        self.jobs.append((function, args, job_id))


# Ids das fixtures sintéticas
HUB = "b.00000000-0000-0000-0000-000000000001"
PROJECT = "b.11111111-1111-1111-1111-111111111111"
FOLDER = "urn:adsk.wipprod:fs.folder:co.PROJECTFILES"
ITEM = "urn:adsk.wipprod:dm.lineage:LINEAGE_RVT"

MANIFEST_RE = r".*/modelderivative/v2/designdata/[^/]+/manifest$"


MODEL_FORMATS = ("rvt", "nwd", "ifc")
MD = f"{BASE}/modelderivative/v2/designdata"


def model_fixture(fmt: str, name: str) -> Any:
    return fixture(f"models/{fmt}/{name}.json")


def mock_model(fmt: str, urn: str) -> dict[str, respx.Route]:
    """metadata, árvore e propriedades do modelo `fmt` (fixtures/aps/models/<fmt>/)."""
    meta = model_fixture(fmt, "metadata")
    guid = next(
        v["guid"]
        for v in sorted(meta["data"]["metadata"], key=lambda v: not v.get("isMasterView"))
        if v["role"] == "3d"
    )
    return {
        "metadata": respx.get(f"{MD}/{urn}/metadata").respond(200, json=meta),
        "tree": respx.get(f"{MD}/{urn}/metadata/{guid}").respond(
            200, json=model_fixture(fmt, "tree")
        ),
        "properties": respx.get(f"{MD}/{urn}/metadata/{guid}/properties").respond(
            200, json=model_fixture(fmt, "properties")
        ),
    }


def mock_manifest(name: str = "manifest_success.json", status: int = 200) -> respx.Route:
    """Qualquer GET de manifest responde com a fixture (ou só o status, se não for 200)."""
    route = respx.get(url__regex=MANIFEST_RE)
    if status == 200:
        return route.respond(200, json=fixture(name))
    return route.respond(status)
