"""3.1 · Extração de elementos e marcas (funções puras) nos três formatos."""

from __future__ import annotations

import pytest

from app.aps.schemas import PropertyObject, TreeNode
from app.services.extraction import (
    NO_CATEGORY,
    ExtractedElement,
    clean_category,
    extract_elements,
    find_prop,
    normalize_mark,
)
from tests.apsfakes import model_fixture

MARKS = ["Marca", "Mark"]
CATEGORIES = ["Category", "Categoria", "IfcClass"]


def _extract(fmt: str) -> dict[int, ExtractedElement]:
    tree = [TreeNode.model_validate(o) for o in model_fixture(fmt, "tree")["data"]["objects"]]
    props = [
        PropertyObject.model_validate(p)
        for p in model_fixture(fmt, "properties")["data"]["collection"]
    ]
    return {e.dbid: e for e in extract_elements(tree, props, MARKS, CATEGORIES)}


def test_rvt_elements_marks_and_categories() -> None:
    els = _extract("rvt")
    # 13 e 14 são componentes aninhados da viga 12 (que tem Marca): não contam
    assert sorted(els) == [10, 11, 12, 20, 21, 30, 31]
    assert els[10].mark_code == els[11].mark_code == "V-101"
    assert els[11].mark_raw == "v-101"  # como está no modelo, sem os espaços
    assert els[10].category == "Structural Framing"  # sem o prefixo "Revit "
    assert els[21].mark_code is None and els[21].mark_raw is None  # marca em branco
    assert els[31].mark_code == "P-01" and els[31].category == "Floors"
    assert els[10].external_id == "aaaaaaaa-0000-0000-0000-000000000000-000186a1"
    assert els[10].name == "Viga Pré-moldada [100001]"
    assert els[10].props["Dimensões"]["Comprimento"] == "600.0 cm"


def test_nwd_nested_geometry_and_portuguese_names() -> None:
    els = _extract("nwd")
    assert sorted(els) == [10, 12, 13, 20]  # "Sólido" (11, 14, 15) é geometria aninhada
    assert {els[10].mark_code, els[12].mark_code} == {"V-101"}
    assert els[13].mark_code == "P-01" and els[13].category == "Structural Columns"
    assert els[20].mark_code is None and els[20].category == "Grids"


def test_ifc_class_as_category_and_list_values() -> None:
    els = _extract("ifc")
    assert sorted(els) == [10, 11, 12, 13]
    assert (els[10].mark_code, els[10].category) == ("V-201", "IfcBeam")
    assert els[12].mark_code == "P-201"  # valor em lista
    assert els[13].mark_code is None and els[13].category == "IfcSlab"


def test_tree_category_when_no_property() -> None:
    tree = [
        TreeNode.model_validate(
            {
                "objectid": 1,
                "objects": [{"objectid": 2, "name": "Pilares", "objects": [{"objectid": 3}]}],
            }
        )
    ]
    (el,) = extract_elements(tree, [], MARKS, CATEGORIES)
    assert (el.dbid, el.category, el.mark_code, el.name) == (3, "Pilares", None, None)


def test_mark_names_order_of_preference() -> None:
    props = {"A": {"mark": "M-1"}, "B": {"MARCA": "X-9"}}
    assert find_prop(props, ["Marca", "Mark"]) == "X-9"
    assert find_prop(props, ["Mark"]) == "M-1"
    assert find_prop(props, ["Tag"]) is None


@pytest.mark.parametrize(
    ("raw", "code"),
    [(" v-101 ", "V-101"), ("P-01", "P-01"), ("   ", None), (None, None), ("lá-1", "LÁ-1")],
)
def test_normalize_mark(raw: str | None, code: str | None) -> None:
    assert normalize_mark(raw) == code


def test_clean_category() -> None:
    assert clean_category("Revit Structural Framing") == "Structural Framing"
    assert clean_category("  ") == NO_CATEGORY


def _node(oid: int, name: str, *children: dict[str, object]) -> dict[str, object]:
    return {"objectid": oid, "name": name, "objects": list(children)}


def _props(oid: int, **ident: str) -> PropertyObject:
    return PropertyObject.model_validate(
        {"objectid": oid, "name": f"n{oid}", "properties": {"Dados de identidade": ident}}
    )


def test_type_mark_on_type_node_descends_to_instances() -> None:
    """Estrutura do Revit real: categoria > família > TIPO > instâncias. "Marca de tipo"
    aparece no nó do tipo e se repete nas instâncias: o tipo é agrupamento, não peça."""
    tree = [
        TreeNode.model_validate(
            _node(
                1,
                "Model",
                _node(
                    2,
                    "Quadro estrutural",
                    _node(
                        3,
                        "Viga-R",
                        _node(4, "R80-V10", _node(10, "Viga [1]"), _node(11, "Viga [2]")),
                    ),
                ),
            )
        )
    ]
    props = [
        _props(4, **{"Marca de tipo": "V10"}),
        _props(10, Marca="", **{"Marca de tipo": "V10"}),
        _props(11, Marca="", **{"Marca de tipo": "V10"}),
    ]
    els = extract_elements(tree, props, ["Marca", "Marca de tipo"], CATEGORIES)
    assert [(e.dbid, e.mark_code, e.category) for e in els] == [
        (10, "V10", "Quadro estrutural"),
        (11, "V10", "Quadro estrutural"),
    ]


def test_instance_mark_wins_over_type_mark() -> None:
    tree = [
        TreeNode.model_validate(
            _node(
                1,
                "Model",
                _node(2, "Pilares", _node(4, "Tipo", _node(10, "P [1]"), _node(11, "P [2]"))),
            )
        )
    ]
    props = [
        _props(4, **{"Marca de tipo": "P01"}),
        _props(10, Marca="PP-01", **{"Marca de tipo": "P01"}),
        _props(11, Marca="PP-02", **{"Marca de tipo": "P01"}),
    ]
    els = extract_elements(tree, props, ["Marca", "Marca de tipo"], CATEGORIES)
    assert [(e.dbid, e.mark_code) for e in els] == [(10, "PP-01"), (11, "PP-02")]


def test_piece_with_nested_components_is_still_one_element() -> None:
    """Viga com marca e inserts aninhados (sem marca ou com outra): a viga é a peça."""
    tree = [
        TreeNode.model_validate(
            _node(
                1,
                "Model",
                _node(2, "Vigas", _node(10, "Viga", _node(20, "Insert"), _node(21, "Insert"))),
            )
        )
    ]
    sem_marca = [_props(10, Marca="V-101"), _props(20), _props(21)]
    assert [e.dbid for e in extract_elements(tree, sem_marca, MARKS, CATEGORIES)] == [10]
    outra = [_props(10, Marca="V-101"), _props(20, Marca="IN-01"), _props(21, Marca="IN-01")]
    assert [e.dbid for e in extract_elements(tree, outra, MARKS, CATEGORIES)] == [10]
