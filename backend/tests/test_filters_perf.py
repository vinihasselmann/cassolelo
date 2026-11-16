"""Desempenho do motor de filtros: 20.000 peças sintéticas (mesma base de
test_search_perf: 2.000 marcas, ~26 propriedades por peça => ~600 mil linhas em
piece_props). Cada avaliação precisa responder em menos de 1 s."""

from __future__ import annotations

import time
from typing import Any

import httpx
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PieceProp, User
from app.models.enums import Role
from app.services import piece_props
from tests.conftest import as_user
from tests.test_search_perf import N_ELEMENTS, big_version  # noqa: F401 (fixture)

LIMIT_S = 1.0


def _r(source: str, key: str, op: str, value: Any = None) -> dict[str, Any]:
    return {"field": {"source": source, "key": key}, "op": op, "value": value}


FILTERS: list[tuple[str, dict[str, Any]]] = [
    ("sem regras (tudo)", {"mode": "isolate", "rules": []}),
    ("texto igual (nível)", {"mode": "isolate", "rules": [_r("system", "level", "eq", "terreo")]}),
    (
        "texto contém (tipo)",
        {"mode": "isolate", "rules": [_r("model", "Dados de identidade/Tipo", "contains", "40x")]},
    ),
    (
        "número entre (comprimento)",
        {"mode": "isolate", "rules": [_r("model", "Dimensões/Comprimento", "between", [650, 800])]},
    ),
    ("número > (largura)", {"mode": "hide", "rules": [_r("model", "Dimensões/Largura", "gt", 35)]}),
    (
        "status (fábrica)",
        {"mode": "highlight", "rules": [_r("system", "status", "eq", "Pendente")]},
    ),
    (
        "vazio (comentários)",
        {"mode": "isolate", "rules": [_r("model", "Dados de identidade/Comentários", "empty")]},
    ),
    (
        "combinada E (4 regras)",
        {
            "mode": "isolate",
            "logic": "and",
            "rules": [
                _r("system", "category", "in", ["Structural Columns", "Floors"]),
                _r("model", "Dimensões/Altura", "gte", 80),
                _r("model", "Restrições/Nível base", "ne", "COBERTURA"),
                _r("system", "mark", "starts_with", "pp0"),
            ],
        },
    ),
    (
        "combinada OU (3 regras)",
        {
            "mode": "isolate",
            "logic": "or",
            "rules": [
                _r("model", "Dimensões/Largura", "eq", 30),
                _r("model", "Estrutural/Prop 3", "contains", "valor"),
                _r("system", "level", "eq", "COBERTURA"),
            ],
        },
    ),
]


async def test_filter_engine_under_one_second_with_20k_pieces(
    session: AsyncSession,
    client: httpx.AsyncClient,
    users: dict[Role, User],
    big_version: dict[str, int],  # noqa: F811
) -> None:
    vid = big_version["version_id"]
    start = time.perf_counter()
    rows = await piece_props.rebuild_version(session, vid)
    build_s = time.perf_counter() - start
    await session.execute(text("ANALYZE piece_props"))
    count = await session.scalar(
        select(func.count()).select_from(PieceProp).where(PieceProp.version_id == vid)
    )
    assert count is not None and count >= N_ELEMENTS * 20

    h = as_user(users[Role.FABRICA])
    url = f"/api/versions/{vid}/filter/evaluate"
    await client.post(url, json=FILTERS[1][1], headers=h)  # aquece
    times: dict[str, float] = {}
    for label, body in FILTERS:
        t0 = time.perf_counter()
        r = await client.post(url, json=body, headers=h)
        times[label] = time.perf_counter() - t0
        assert r.status_code == 200, (label, r.text)
        assert r.json()["matched_pieces"] > 0, label
    t0 = time.perf_counter()
    fields = await client.get(f"/api/versions/{vid}/fields", headers=h)
    times["GET fields"] = time.perf_counter() - t0
    assert fields.status_code == 200
    t0 = time.perf_counter()
    values = await client.get(
        f"/api/versions/{vid}/fields/model/Dimensões/Comprimento/values", headers=h
    )
    times["GET values"] = time.perf_counter() - t0
    assert values.status_code == 200 and values.json()

    # cores: esquema com 4 regras (a primeira que bate vence) e coloração por campo
    scheme = {
        "rules": [
            {"filter": FILTERS[5][1], "color": "#B9BEC6"},  # status
            {"filter": FILTERS[3][1], "color": "#E3B341"},  # número entre
            {"filter": FILTERS[2][1], "color": "#33A06F"},  # texto contém
            {"filter": FILTERS[0][1], "color": "#E8743B"},  # resto
        ]
    }
    color_calls: list[tuple[str, str, dict[str, Any]]] = [
        ("esquema (4 regras)", "color-scheme/evaluate", scheme),
        (
            "colorir distinct (tipo)",
            "colorize",
            {"field": {"source": "model", "key": "Dados de identidade/Tipo"}, "mode": "distinct"},
        ),
        (
            "colorir range (comprimento)",
            "colorize",
            {"field": {"source": "model", "key": "Dimensões/Comprimento"}, "mode": "range"},
        ),
        (
            "colorir distinct (status)",
            "colorize",
            {"field": {"source": "system", "key": "status"}, "mode": "distinct"},
        ),
    ]
    for label, path, body in color_calls:
        t0 = time.perf_counter()
        r = await client.post(f"/api/versions/{vid}/{path}", json=body, headers=h)
        times[label] = time.perf_counter() - t0
        assert r.status_code == 200, (label, r.text)
        assert len(r.json()["colors"]) >= N_ELEMENTS, label

    print(f"\nMotor de filtros, {N_ELEMENTS} peças / {count} valores (montagem {build_s:.1f} s):")
    for label, seconds in times.items():
        print(f"  {seconds * 1000:7.1f} ms  {label}")
    slow = {k: round(v, 3) for k, v in times.items() if v >= LIMIT_S}
    assert not slow, f"acima de {LIMIT_S}s: {slow}"
    assert rows == count + 0 or rows >= count  # build + sync (status) contados
