"""5.1 · Desempenho da busca: 20 mil elementos sintéticos, cada consulta abaixo de 1 s.

Mede a chamada inteira da API (FastAPI em processo + Postgres), não só o SQL.
Rode com `-s` para ver os tempos.
"""

from __future__ import annotations

import time
from typing import Any

import httpx
import pytest
from sqlalchemy import insert, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Element, Mark, ModelVersion, Obra, ParamDef, ParamValue, User
from app.models.enums import Role
from app.models.obra import VersionPropertyName
from tests.conftest import as_user, include_params

N_ELEMENTS = 20_000
N_MARKS = 2_000
LIMIT_S = 1.0
CATEGORIES = ["Structural Columns", "Structural Framing", "Floors", "Walls"]
LEVELS = ["TÉRREO", "1º PAVIMENTO", "2º PAVIMENTO", "COBERTURA"]
SECTIONS = ["30x30", "40x40", "40x80", "50x100"]


def _props(code: str, i: int) -> dict[str, Any]:
    section = SECTIONS[i % len(SECTIONS)]
    w, h = section.split("x")
    return {
        "Dados de identidade": {"Marca": code, "Tipo": f"Peça {section}", "Comentários": ""},
        "Dimensões": {
            "Largura": f"{w}.0 cm",
            "Altura": f"{h}.0 cm",
            "Comprimento": f"{600 + i % 7 * 50}.0 cm",
            **{f"Dim {k}": f"{k}.0 cm" for k in range(8)},
        },
        "Restrições": {"Nível base": LEVELS[i % len(LEVELS)]},
        "Estrutural": {f"Prop {k}": f"valor {k}" for k in range(10)},
        "Other": {"Category": f"Revit {CATEGORIES[i % len(CATEGORIES)]}"},
    }


@pytest.fixture
async def big_version(session: AsyncSession) -> dict[str, int]:
    obra = Obra(code="OB-PERF", name="Obra desempenho")
    session.add(obra)
    await session.flush()
    v1 = ModelVersion(obra_id=obra.id, acc_version_id="perf:1", version_number=1, status="ready")
    v2 = ModelVersion(obra_id=obra.id, acc_version_id="perf:2", version_number=2, status="ready")
    session.add_all([v1, v2])
    await session.flush()

    mark_rows = [
        {"obra_id": obra.id, "code": f"PP{m:04d}", "category": CATEGORIES[m % len(CATEGORIES)]}
        for m in range(N_MARKS)
    ]
    mark_ids = list(await session.scalars(insert(Mark).returning(Mark.id), mark_rows))
    rows = []
    for i in range(N_ELEMENTS):
        m = i % N_MARKS
        code = f"PP{m:04d}"
        level = LEVELS[i % len(LEVELS)]
        props = _props(code, m)  # peças da mesma marca têm as mesmas propriedades
        rows.append(
            {
                "version_id": v2.id,
                "dbid": 1000 + i,
                "external_id": f"ext-{i}",
                "name": f"Peça [{i}]",
                "category": CATEGORIES[m % len(CATEGORIES)],
                "level": level,
                "mark_raw": code,
                "mark_id": mark_ids[m],
                "props": props,
                "search_text": f"Peça [{i}] | {CATEGORIES[m % len(CATEGORIES)]} | {code} | "
                f"{level} | {props['Dados de identidade']['Tipo']}",
            }
        )
    for i in range(0, len(rows), 2000):
        await session.execute(insert(Element), rows[i : i + 2000])
    # v1 tinha só metade das marcas: a outra metade é "nova na versão"
    old = [dict(r, version_id=v1.id) for r in rows if r["mark_id"] in set(mark_ids[: N_MARKS // 2])]
    for i in range(0, len(old), 2000):
        await session.execute(insert(Element), old[i : i + 2000])

    names = sorted({(g, n) for g, content in _props("X", 0).items() for n in content})
    await session.execute(
        insert(VersionPropertyName),
        [{"version_id": v2.id, "group_name": g, "prop_name": n} for g, n in names],
    )
    forma = ParamDef(name="Forma", type="text", scope="global")
    session.add(forma)
    await session.flush()
    await include_params(session, v2.obra_id, forma)
    await session.execute(
        insert(ParamValue),
        [
            {"mark_id": mid, "def_id": forma.id, "value": f"F-{k % 40}"}
            for k, mid in enumerate(mark_ids[::2])
        ],
    )
    await session.execute(text("ANALYZE elements"))
    await session.execute(text("ANALYZE marks"))
    await session.execute(text("ANALYZE param_values"))
    return {"version_id": v2.id}


QUERIES: list[tuple[str, dict[str, Any]]] = [
    ("tudo (1ª página)", {}),
    ("marca PP0012", {"q": "PP0012"}),
    ("prefixo PP00", {"q": "PP00"}),
    ("seção 40x80", {"q": "40x80"}),
    ("parâmetro F-12", {"q": "F-12"}),
    ("categoria", {"category": "Floors"}),
    ("nível", {"level": "COBERTURA"}),
    ("propriedade Altura=80.0 cm", {"prop": "Altura=80.0 cm"}),
    ("sem forma", {"missing": "forma"}),
    ("novas na versão", {"shortcut": "new"}),
    ("pendentes (status calculado)", {"shortcut": "pending"}),
    (
        "combinada",
        {"q": "pp 40x", "level": ["1º PAVIMENTO", "2º PAVIMENTO"], "prop": "Largura=40.0 cm"},
    ),
]


async def test_search_under_one_second_with_20k_elements(
    client: httpx.AsyncClient, users: dict[Role, User], big_version: dict[str, int]
) -> None:
    url = f"/api/versions/{big_version['version_id']}/marks/search"
    h = as_user(users[Role.FABRICA])
    await client.get(url, headers=h)  # aquece conexão e caches

    times: dict[str, float] = {}
    for label, params in QUERIES:
        start = time.perf_counter()
        r = await client.get(url, params=params, headers=h)
        times[label] = time.perf_counter() - start
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total_marks"] > 0, label

    print("\nBusca com 20.000 elementos / 2.000 marcas:")
    for label, seconds in times.items():
        print(f"  {seconds * 1000:7.1f} ms  {label}")
    slow = {k: round(v, 3) for k, v in times.items() if v >= LIMIT_S}
    assert not slow, f"consultas acima de {LIMIT_S}s: {slow}"

    full = (await client.get(url, params={"page_size": 500}, headers=h)).json()
    assert full["total_pieces"] == N_ELEMENTS and len(full["dbids"]) == N_ELEMENTS
    news = (await client.get(url, params={"shortcut": "new"}, headers=h)).json()
    assert news["total_marks"] == N_MARKS // 2


async def test_status_and_progress_under_one_second_with_20k_elements(
    client: httpx.AsyncClient, users: dict[Role, User], big_version: dict[str, int]
) -> None:
    base = f"/api/versions/{big_version['version_id']}"
    h = as_user(users[Role.FABRICA])
    await client.get(f"{base}/marks/status", headers=h)  # aquece
    times: dict[str, float] = {}
    for label, path in (("status por marca", "/marks/status"), ("progresso", "/progress")):
        start = time.perf_counter()
        r = await client.get(base + path, headers=h)
        times[label] = time.perf_counter() - start
        assert r.status_code == 200, r.text
    print("\nStatus/progresso com 20.000 elementos / 2.000 marcas:")
    for label, seconds in times.items():
        print(f"  {seconds * 1000:7.1f} ms  {label}")
    assert all(v < LIMIT_S for v in times.values()), times
    status = (await client.get(f"{base}/marks/status", headers=h)).json()
    counts = {c["status"]: c["marks"] for c in status["counts"]}
    assert counts["complete"] + counts["pending"] == len(status["items"])
    assert counts["complete"] > 0 and counts["pending"] > 0
