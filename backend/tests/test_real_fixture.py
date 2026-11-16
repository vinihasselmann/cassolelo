"""Fixture REAL (sanitizada) do modelo de orçamento publicado no Docs: models/rvt_real.

Estrutura real do Revit: Model > categoria > família > TIPO > instâncias; categorias em
português; "Marca" vazia no modelo (orçamento) e SIMULADA na fixture como
<Marca de tipo>-<nn> por (tipo, PEÇA-Comprimento) — veja o README da pasta.
"""

from __future__ import annotations

import collections
import json

import respx
from sqlalchemy.ext.asyncio import AsyncSession

from app.aps.client import ApsClient
from app.aps.schemas import Manifest, PropertyObject, TreeNode
from app.models import ModelVersion, Obra
from app.services.extraction import extract_elements
from app.services.mark_validation import build_report
from app.services.processing import ProcessingConfig, process_version
from tests.apsfakes import FIXTURES, Sleeps, mock_model, mock_token, model_fixture

DIMS = ["SEÇÃO-Altura", "SEÇÃO-Largura", "PEÇA-Comprimento"]
LEVELS = ["Nível base", "Nível de referência", "Nível"]
CATS = ["Category", "Categoria", "IfcClass"]


def _extract(marks: list[str]) -> list:  # type: ignore[type-arg]
    tree = [
        TreeNode.model_validate(o) for o in model_fixture("rvt_real", "tree")["data"]["objects"]
    ]
    props = [
        PropertyObject.model_validate(p)
        for p in model_fixture("rvt_real", "properties")["data"]["collection"]
    ]
    return extract_elements(tree, props, marks, CATS)


def test_manifest_has_svf2_viewable() -> None:
    m = Manifest.model_validate(
        json.loads((FIXTURES / "models/rvt_real/manifest.json").read_text("utf-8"))
    )
    assert m.status == "success" and m.is_ready


def test_instances_are_the_pieces_with_portuguese_categories() -> None:
    els = _extract(["Marca", "Mark"])
    assert len(els) == 33
    assert collections.Counter(e.category for e in els) == {
        "Quadro estrutural": 20,
        "Pilares estruturais": 12,
        "Pisos": 1,
    }
    assert all(e.external_id and e.name for e in els)


def test_simulated_marks_are_consistent() -> None:
    els = _extract(["Marca", "Mark"])
    report = build_report(1, els, DIMS, 5.0)
    assert (report["totals"]["marks"], report["totals"]["inconsistent_marks"]) == (19, 0)


def test_type_mark_descends_from_type_node_and_flags_lengths() -> None:
    """Com "Marca de tipo" como marca, o nó do TIPO não pode virar peça (bug achado no
    modelo real: saíam 9 peças em vez das instâncias). Peças do mesmo tipo têm
    comprimentos diferentes: a validação acusa."""
    els = _extract(["Marca de tipo"])
    assert len(els) == 33
    report = build_report(1, els, DIMS, 5.0)
    assert report["totals"]["marks"] == 9
    assert report["totals"]["inconsistent_marks"] == 5
    props = {d["property"] for m in report["inconsistent"] for d in m["differences"]}
    assert props == {"PEÇA-Comprimento"}


@respx.mock
async def test_process_real_fixture_end_to_end(
    session: AsyncSession, aps: ApsClient, sleeps: Sleeps
) -> None:
    mock_token()
    mock_model("rvt_real", "dXJuOnJ2dF9yZWFs")
    obra = Obra(code="OB-REAL", name="Fixture real")
    session.add(obra)
    await session.flush()
    v = ModelVersion(
        obra_id=obra.id, acc_version_id="urn:v:real", version_number=1, urn="dXJuOnJ2dF9yZWFs"
    )
    session.add(v)
    await session.flush()
    config = ProcessingConfig(
        mark_names=["Marca", "Mark"],
        category_names=CATS,
        dimension_names=DIMS,
        level_names=LEVELS,
        search_names=["Nome do tipo"],
    )
    result = await process_version(session, aps, v.id, config, sleep=sleeps)
    assert result is not None and result.status == "ready"
    assert (result.elements, result.marks, result.without_mark) == (33, 19, 0)


# --------------------------------------------------------------------------- IFC real

IFC_LEVELS = ["IfcSpatialContainer"]


def _extract_ifc() -> list:  # type: ignore[type-arg]
    tree = [
        TreeNode.model_validate(o) for o in model_fixture("ifc_real", "tree")["data"]["objects"]
    ]
    props = [
        PropertyObject.model_validate(p)
        for p in model_fixture("ifc_real", "properties")["data"]["collection"]
    ]
    return extract_elements(tree, props, ["Marca", "Mark"], CATS)


def test_ifc_products_are_pieces_and_geometry_is_not() -> None:
    """IFC do Revit no Docs: Projeto > Site > Edifício > Pavimento > classe > PRODUTO >
    geometria. Só os produtos contam; eixos (IfcGrid) e aberturas ficam de fora."""
    els = _extract_ifc()
    assert collections.Counter(e.category for e in els) == {
        "IfcBeam": 12,
        "IfcColumn": 4,
        "IfcSlab": 1,
    }
    assert all(e.name and e.name.startswith(("IfcBeam::", "IfcColumn::", "IfcSlab::")) for e in els)
    assert all(e.mark_code is None for e in els)  # o IFC (como o .rvt de orçamento) não tem Marca


def test_ifc_level_and_type_properties() -> None:
    from app.services.extraction import find_prop

    els = _extract_ifc()
    levels = collections.Counter(find_prop(e.props, IFC_LEVELS) for e in els)
    assert levels == {"TÉRREO": 4, "EMBARQUE": 5, "DESEMBARQUE": 4, "COBERTURA": 4}
    assert find_prop(els[0].props, ["ObjectType"]) == "CASSOL-PREO-Pilar-R:R-40x40cm-P02"
