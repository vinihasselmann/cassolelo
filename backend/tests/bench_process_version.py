"""Mede o process_version num modelo SINTÉTICO grande (não é coletado pelo pytest).

    cd backend && uv run python -m tests.bench_process_version --elements 30000 --marks 3000

Cria um banco temporário (como os testes), simula o APS com respx e roda o
processamento duas vezes (a 2ª mede o reprocessamento idempotente).
Trocar por um modelo real quando os aceites da Fase 0 rodarem.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from typing import Any

import httpx
import respx
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.aps.auth import TokenProvider
from app.aps.client import ApsClient
from app.models import ModelVersion, Obra
from app.services.processing import ProcessingConfig, process_version
from tests import dbutil
from tests.apsfakes import BASE, MD, mock_token

CATEGORIES = ["Structural Framing", "Structural Columns", "Floors", "Walls", "Generic Models"]
GUID = "bench-3d"


def synthetic_model(n_elements: int, n_marks: int) -> tuple[dict[str, Any], dict[str, Any]]:
    """Árvore Model > categoria > família > instâncias; ~30 propriedades por peça."""
    tree_cats: list[dict[str, Any]] = []
    collection: list[dict[str, Any]] = []
    oid = 10
    per_cat = n_elements // len(CATEGORIES)
    for ci, cat in enumerate(CATEGORIES):
        instances = []
        for i in range(per_cat):
            oid += 1
            idx = ci * per_cat + i
            mark = None if idx % 50 == 0 else f"M-{idx % n_marks:05d}"
            instances.append({"objectid": oid, "name": f"{cat} [{oid}]"})
            collection.append(
                {
                    "objectid": oid,
                    "name": f"{cat} [{oid}]",
                    "externalId": f"{oid:08x}-0000-0000-0000-000000000000-{oid:08x}",
                    "properties": {
                        "Dados de identidade": {"Marca": mark or "", "Comentários": ""},
                        "Dimensões": {f"Dim {k}": f"{100 + k}.0 cm" for k in range(12)},
                        "Estrutural": {f"Prop {k}": f"valor {k}" for k in range(12)},
                        "Other": {"Category": f"Revit {cat}"},
                    },
                }
            )
        tree_cats.append(
            {
                "objectid": ci + 2,
                "name": cat,
                "objects": [{"objectid": 1000000 + ci, "name": "Família", "objects": instances}],
            }
        )
    tree = {"data": {"objects": [{"objectid": 1, "name": "Model", "objects": tree_cats}]}}
    return tree, {"data": {"collection": collection}}


async def main(n_elements: int, n_marks: int) -> None:
    base = dbutil.base_database_url()
    assert base, "DATABASE_URL não definido"
    url = await asyncio.to_thread(dbutil.create_temp_database, base)
    try:
        await asyncio.to_thread(dbutil.upgrade, url)
        tree, props = synthetic_model(n_elements, n_marks)
        size_mb = len(json.dumps(props)) / 1e6
        print(f"modelo: {n_elements} elementos, {n_marks} marcas, propriedades {size_mb:.1f} MB")

        engine = create_async_engine(url)
        async with httpx.AsyncClient(base_url=BASE) as http, respx.mock:
            mock_token()
            meta = {"data": {"metadata": [{"guid": GUID, "role": "3d", "isMasterView": True}]}}
            respx.get(f"{MD}/dXJu/metadata").respond(200, json=meta)
            respx.get(f"{MD}/dXJu/metadata/{GUID}").respond(200, json=tree)
            respx.get(f"{MD}/dXJu/metadata/{GUID}/properties").respond(200, json=props)
            tokens = TokenProvider(client_id="cid", client_secret=SecretStr("s"), http=http)
            aps = ApsClient(http=http, tokens=tokens)

            async with AsyncSession(engine, expire_on_commit=False) as session:
                obra = Obra(code="BENCH", name="Benchmark")
                session.add(obra)
                await session.flush()
                v = ModelVersion(obra_id=obra.id, acc_version_id="bench:1", version_number=1)
                v.urn = "dXJu"
                session.add(v)
                await session.commit()

                for label in ("1º processamento", "reprocessamento"):
                    t0 = time.perf_counter()
                    r = await process_version(
                        session,
                        aps,
                        v.id,
                        ProcessingConfig(
                            mark_names=["Marca", "Mark"],
                            category_names=["Category"],
                            dimension_names=["Dim 0", "Dim 1", "Dim 2"],
                        ),
                    )
                    assert r is not None and r.status == "ready", r
                    print(
                        f"{label}: {time.perf_counter() - t0:.2f}s  (elementos {r.elements}, "
                        f"sem marca {r.without_mark}, marcas {r.marks}, novas {r.marks_created})"
                    )
        await engine.dispose()
    finally:
        await asyncio.to_thread(dbutil.drop_database, url)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--elements", type=int, default=30000)
    p.add_argument("--marks", type=int, default=3000)
    a = p.parse_args()
    asyncio.run(main(a.elements, a.marks))
