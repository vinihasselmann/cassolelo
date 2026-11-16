from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import pytest

import compare_versions as cv


def el(ext: str, mark: str | None, cat: str = "Vigas", comp: str | None = None) -> dict[str, Any]:
    props = {"Dimensões": {"Comprimento": comp}} if comp else {}
    return {"external_id": ext, "mark": mark, "category": cat, "props": props}


V1: dict[str, Any] = {
    "item_id": "I",
    "file_name": "Obra.rvt",
    "version_number": 1,
    "elements": [
        el("a1", "V1", comp="600"),
        el("a2", "V1", comp="600"),
        el("b1", "V2"),
        el("c1", "P1", "Pilares"),
        el("d1", "R1"),
        el("x1", None),
    ],
}
V2: dict[str, Any] = {
    "item_id": "I",
    "file_name": "Obra.rvt",
    "version_number": 2,
    "elements": [
        el("a1", "V1", comp="600"),
        el("a9", "V1", comp="650"),  # recriada e com comprimento diferente
        el("b1", "V2"),
        el("b2", "V2"),
        el("c1", "P1", "Pilares"),
        el("n1", "N1"),
        el("c2", "P1", "Vigas"),  # mesma marca, outra categoria = outra marca
    ],
}


def by_key(rows: list[cv.Row]) -> dict[tuple[str, str], cv.Row]:
    return {(r.mark, r.category): r for r in rows}


def test_compare_statuses() -> None:
    rows = by_key(cv.compare(V1, V2, ["Comprimento"]))
    assert rows[("V1", "Vigas")].status == cv.KEPT
    assert rows[("V2", "Vigas")].status == cv.CHANGED
    assert rows[("P1", "Pilares")].status == cv.KEPT
    assert rows[("P1", "Vigas")].status == cv.NEW
    assert rows[("N1", "Vigas")].status == cv.NEW
    assert rows[("R1", "Vigas")].status == cv.REMOVED
    assert (rows[("V2", "Vigas")].qty_v1, rows[("V2", "Vigas")].qty_v2) == (1, 2)


def test_external_id_changes_only_for_marks_in_both_versions() -> None:
    rows = by_key(cv.compare(V1, V2, ["Comprimento"]))
    v1 = rows[("V1", "Vigas")]
    assert (v1.ext_new, v1.ext_removed) == (["a9"], ["a2"])
    assert rows[("N1", "Vigas")].ext_new == []
    assert rows[("R1", "Vigas")].ext_removed == []


def test_dimension_conflicts_within_version() -> None:
    rows = by_key(cv.compare(V1, V2, ["Comprimento"]))
    assert rows[("V1", "Vigas")].dims_divergent == ["v2"]
    assert rows[("V2", "Vigas")].dims_divergent == []
    assert cv.compare(V1, V2, [])[0].dims_divergent == []


def test_summary_mentions_exceptions() -> None:
    text = "\n".join(cv.summary(V1, V2, cv.compare(V1, V2, ["Comprimento"]), ["Comprimento"]))
    assert "v1: 6 elementos, 1 sem Marca (16.7%)" in text
    assert "V1 [Vigas]: +1 -1" in text
    assert "Marcas com dimensões diferentes em v2: 1" in text
    assert "Comprimento=650" in text


def test_main_writes_csv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cv, "load_dotenv", lambda *_a, **_k: None)
    monkeypatch.setenv("DIMENSION_PROPERTY_NAMES", "Comprimento")
    p1, p2, out = tmp_path / "v1.json", tmp_path / "v2.json", tmp_path / "compare.csv"
    p1.write_text(json.dumps(V1), encoding="utf-8")
    p2.write_text(json.dumps(V2), encoding="utf-8")
    assert cv.main([str(p1), str(p2), "--out", str(out)]) == 0
    with out.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f, delimiter=";"))
    assert len(rows) == 6
    v1 = next(r for r in rows if r["marca"] == "V1")
    assert v1["situacao"] == "mantida"
    assert v1["external_ids_novos"] == "1"
    assert v1["dimensoes_divergentes"] == "v2"


def test_main_bad_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bad = tmp_path / "x.json"
    bad.write_text("{", encoding="utf-8")
    assert cv.main([str(bad), str(bad), "--out", str(tmp_path / "o.csv")]) == 1
    assert "ERRO" in capsys.readouterr().err
