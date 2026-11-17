"""Spike coordenadas: servidor (página, módulos e token do spike 0.4) e comparação."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import compare
import server
import viewer_app as va


def _client() -> TestClient:
    cache = va.TokenCache(lambda: ("tok", 3600))
    return TestClient(server.create_app(cache=cache))


def test_serves_page_modules_and_token() -> None:
    c = _client()
    page = c.get("/")
    assert page.status_code == 200 and "coordenadas.js" in page.text
    assert c.get("/axis.js").headers["content-type"].startswith("text/javascript")
    assert c.get("/coordenadas.js").status_code == 200
    assert c.get("/token").json()["access_token"] == "tok"
    assert c.get("/config").status_code == 200
    assert c.get("/server.py").status_code == 404  # só os módulos da página


def test_compare_pairs_nearest_piece_and_swapped_beam_ends(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def piece(kind: str, dbid: int, pts: dict[str, list[float]]) -> dict[str, object]:
        return {
            "kind": kind,
            "member": {"dbId": dbid, "name": f"p{dbid}"},
            "points": {k: {"arquivo_mm": v, "pbp_A_mm": None} for k, v in pts.items()},
        }

    a = [
        piece("pilar", 1, {"base": [0, 0, 0], "topo": [0, 0, 5000]}),
        piece("viga", 2, {"inicio": [0, 0, 4800], "fim": [8000, 0, 4800]}),
    ]
    b = [
        piece("pilar", 9, {"base": [9000, 0, 0], "topo": [9000, 0, 5000]}),  # outra peça
        piece("pilar", 7, {"base": [0.4, 0, 0], "topo": [0.4, 0, 5000]}),
        piece("viga", 8, {"inicio": [8000, 0, 4800], "fim": [0, 0.3, 4800]}),  # pontas trocadas
    ]
    for name, pieces in (("a", a), ("b", b)):
        (tmp_path / f"coordenadas-{name}.json").write_text(json.dumps({"pieces": pieces}), "utf-8")
    monkeypatch.setattr(compare, "OUT", tmp_path)
    text = compare.compare("a", "b")
    assert "Maior diferença: **0.40 mm** (2 peças)." in text
