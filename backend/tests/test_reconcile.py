"""7.1 · Motor de reconciliação (função pura, sem banco).

Os 7 casos do roteiro + bordas. As versões são montadas a partir de ELEMENTOS (como o
process_version entrega), para provar que posição e externalId não influenciam: só as
propriedades de revisão (DIMENSION_PROPERTY_NAMES + REVIEW_PROPERTY_NAMES), a quantidade,
o código e a categoria.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.services.reconcile import (
    Change,
    ElementInput,
    MarkResult,
    MarkSnapshot,
    PropDiff,
    ReconcileConfig,
    build_snapshots,
    reconcile,
)

CONFIG = ReconcileConfig(
    dimension_names=["SEÇÃO-Largura", "SEÇÃO-Altura", "PEÇA-Comprimento"],
    review_names=["Seção", "Armadura"],
    tolerance_mm=5.0,
)


def _el(
    code: str | None,
    category: str = "Pilar",
    *,
    ext: str = "ext",
    secao: str = "40x60",
    largura: str = "40.0 cm",
    altura: str = "60.0 cm",
    comprimento: str = "660.0 cm",
    posicao: str = "0,0,0",
    **extra: Any,
) -> ElementInput:
    props: dict[str, Any] = {
        "Dados de identidade": {"Marca": code or "", "Seção": secao, **extra},
        "Cotas": {
            "SEÇÃO-Largura": largura,
            "SEÇÃO-Altura": altura,
            "PEÇA-Comprimento": comprimento,
        },
        "Localização": {"Ponto": posicao, "Rotação": "0°"},
    }
    return ElementInput(mark_code=code, category=category, external_id=ext, props=props)


def _pieces(code: str, n: int, prefix: str = "a", **kw: Any) -> list[ElementInput]:
    return [_el(code, ext=f"{prefix}-{code}-{i}", **kw) for i in range(n)]


def _run(prev: list[ElementInput], curr: list[ElementInput]) -> dict[tuple[str, str], MarkResult]:
    result = reconcile(build_snapshots(prev, CONFIG), build_snapshots(curr, CONFIG), CONFIG)
    return {(m.code, m.category): m for m in result.marks}


# --------------------------------------------------------------------------- os 7 casos


def test_1_unchanged_mark() -> None:
    marks = _run(_pieces("PP001", 4), _pieces("PP001", 4))
    m = marks[("PP001", "Pilar")]
    assert (m.change, m.prev_count, m.curr_count, m.diffs) == (Change.UNCHANGED, 4, 4, ())


def test_2_moved_piece_is_unchanged() -> None:
    prev = _pieces("PP001", 3)
    curr = [_el("PP001", ext=f"a-PP001-{i}", posicao=f"{i * 500},120,0") for i in range(3)]
    assert _run(prev, curr)[("PP001", "Pilar")].change is Change.UNCHANGED


def test_3_deleted_and_recreated_in_revit_is_unchanged() -> None:
    prev = _pieces("PP001", 3, prefix="old")
    curr = _pieces("PP001", 3, prefix="new")  # externalId novo, mesma marca
    assert _run(prev, curr)[("PP001", "Pilar")].change is Change.UNCHANGED


def test_4_count_12_to_14_is_count_changed() -> None:
    m = _run(_pieces("PP001", 12), _pieces("PP001", 14))[("PP001", "Pilar")]
    assert (m.change, m.prev_count, m.curr_count, m.diffs) == (Change.COUNT_CHANGED, 12, 14, ())


def test_5_section_40x60_to_40x80_is_changed_with_diff() -> None:
    prev = _pieces("PP001", 2, secao="40x60", altura="60.0 cm")
    curr = _pieces("PP001", 2, secao="40x80", altura="80.0 cm")
    m = _run(prev, curr)[("PP001", "Pilar")]
    assert m.change is Change.CHANGED
    assert m.diffs == (
        PropDiff("SEÇÃO-Altura", "60.0 cm", "80.0 cm"),
        PropDiff("Seção", "40x60", "40x80"),
    )
    assert m.summary() == "SEÇÃO-Altura: 60.0 cm → 80.0 cm; Seção: 40x60 → 40x80"


def test_6_renamed_mark_is_removed_plus_new() -> None:
    marks = _run(_pieces("PP001", 4), _pieces("PP001A", 4))
    assert marks[("PP001", "Pilar")].change is Change.REMOVED
    assert marks[("PP001A", "Pilar")].change is Change.NEW
    assert (marks[("PP001", "Pilar")].curr_count, marks[("PP001A", "Pilar")].prev_count) == (0, 0)


def test_7_removed_mark() -> None:
    marks = _run(_pieces("PP001", 2) + _pieces("PP002", 3), _pieces("PP001", 2))
    m = marks[("PP002", "Pilar")]
    assert (m.change, m.prev_count, m.curr_count) == (Change.REMOVED, 3, 0)
    assert marks[("PP001", "Pilar")].change is Change.UNCHANGED


# --------------------------------------------------------------------------- bordas


def test_dimension_within_tolerance_is_unchanged_and_units_are_converted() -> None:
    prev = _pieces("PP001", 2, comprimento="660.0 cm")
    curr = _pieces("PP001", 2, comprimento="6603 mm")  # 3 mm: dentro da tolerância
    assert _run(prev, curr)[("PP001", "Pilar")].change is Change.UNCHANGED
    curr = _pieces("PP001", 2, comprimento="6.70 m")  # 100 mm
    m = _run(prev, curr)[("PP001", "Pilar")]
    assert m.diffs == (PropDiff("PEÇA-Comprimento", "660.0 cm", "6.70 m"),)


def test_text_review_property_ignores_case_and_spaces() -> None:
    prev = _pieces("PP001", 2, Armadura="4Ø16 + estribo Ø8 c/15")
    curr = _pieces("PP001", 2, Armadura="  4ø16 + ESTRIBO ø8 c/15 ")
    assert _run(prev, curr)[("PP001", "Pilar")].change is Change.UNCHANGED
    curr = _pieces("PP001", 2, Armadura="6Ø16 + estribo Ø8 c/15")
    m = _run(prev, curr)[("PP001", "Pilar")]
    assert m.diffs == (PropDiff("Armadura", "4Ø16 + estribo Ø8 c/15", "6Ø16 + estribo Ø8 c/15"),)


def test_changed_wins_over_count_changed_and_keeps_both_counts() -> None:
    m = _run(_pieces("PP001", 12), _pieces("PP001", 14, secao="40x80"))[("PP001", "Pilar")]
    assert (m.change, m.prev_count, m.curr_count) == (Change.CHANGED, 12, 14)
    assert m.count_changed


def test_same_code_other_category_is_another_mark() -> None:
    prev = _pieces("P1", 2)
    curr = [_el("P1", "Viga", ext=f"v{i}") for i in range(2)]
    marks = _run(prev, curr)
    assert marks[("P1", "Pilar")].change is Change.REMOVED
    assert marks[("P1", "Viga")].change is Change.NEW


def test_property_that_appears_or_disappears_is_a_change() -> None:
    prev = _pieces("PP001", 2)
    curr = _pieces("PP001", 2, Armadura="4Ø16")
    m = _run(prev, curr)[("PP001", "Pilar")]
    assert m.diffs == (PropDiff("Armadura", None, "4Ø16"),)
    assert m.summary() == "Armadura: — → 4Ø16"
    back = _run(curr, prev)[("PP001", "Pilar")]
    assert back.diffs == (PropDiff("Armadura", "4Ø16", None),)


def test_mark_with_divergent_pieces_compares_the_set_of_values() -> None:
    prev = [_el("PP001", ext="1", secao="40x60"), _el("PP001", ext="2", secao="40x80")]
    same = [_el("PP001", ext="3", secao="40x80"), _el("PP001", ext="4", secao="40x60")]
    assert _run(prev, same)[("PP001", "Pilar")].change is Change.UNCHANGED
    curr = [_el("PP001", ext="1", secao="40x80"), _el("PP001", ext="2", secao="40x80")]
    m = _run(prev, curr)[("PP001", "Pilar")]
    assert m.diffs == (PropDiff("Seção", "40x60 / 40x80", "40x80"),)


def test_properties_outside_config_are_ignored() -> None:
    prev = _pieces("PP001", 2, Comentários="concretar até sexta")
    curr = _pieces("PP001", 2, Comentários="outro comentário")
    assert _run(prev, curr)[("PP001", "Pilar")].change is Change.UNCHANGED


def test_pieces_without_mark_are_not_marks() -> None:
    snaps = build_snapshots([_el(None), _el(""), *_pieces("PP001", 2)], CONFIG)
    assert [(s.code, s.count) for s in snaps] == [("PP001", 2)]


def test_codes_are_normalized_like_extraction() -> None:
    prev = [_el(" pp001 ", ext="1")]
    curr = [_el("PP001", ext="2")]
    assert _run(prev, curr)[("PP001", "Pilar")].change is Change.UNCHANGED


def test_first_version_everything_is_new_and_totals() -> None:
    result = reconcile([], build_snapshots(_pieces("A", 1) + _pieces("B", 2), CONFIG), CONFIG)
    assert result.totals == {
        Change.UNCHANGED: 0,
        Change.COUNT_CHANGED: 0,
        Change.CHANGED: 0,
        Change.NEW: 2,
        Change.REMOVED: 0,
    }
    assert [m.code for m in result.of(Change.NEW)] == ["A", "B"]


def test_full_revision_totals_and_stable_order() -> None:
    prev = (
        _pieces("PP001", 4)
        + _pieces("PP002", 12)
        + _pieces("PP003", 2)
        + _pieces("PP004", 2)
        + _pieces("PP005", 1)
    )
    curr = (
        _pieces("PP001", 4, prefix="novo")  # recriadas
        + _pieces("PP002", 14)  # quantidade
        + _pieces("PP003", 2, secao="40x80")  # seção
        + _pieces("PP004A", 2)  # renomeada
        + _pieces("PP006", 3)  # nova
    )  # PP005 removida
    result = reconcile(build_snapshots(prev, CONFIG), build_snapshots(curr, CONFIG), CONFIG)
    assert [(m.code, m.change.value) for m in result.marks] == [
        ("PP001", "unchanged"),
        ("PP002", "count_changed"),
        ("PP003", "changed"),
        ("PP004", "removed"),
        ("PP004A", "new"),
        ("PP005", "removed"),
        ("PP006", "new"),
    ]
    assert result.totals[Change.REMOVED] == 2 and result.totals[Change.NEW] == 2


def test_snapshot_is_hashable_input_and_duplicates_are_rejected() -> None:
    snap = MarkSnapshot("PP001", "Pilar", 1, {})
    with pytest.raises(ValueError, match="PP001"):
        reconcile([snap, snap], [], CONFIG)


# --------------------------------------------------------------------------- fixture REAL


def _real_elements() -> list[ElementInput]:
    """Peças do ORC.rvt real (fixture rvt_real, Marca simulada por tipo + comprimento)."""
    from app.aps.schemas import PropertyObject, TreeNode
    from app.services.extraction import extract_elements
    from tests.apsfakes import model_fixture

    tree = [
        TreeNode.model_validate(o) for o in model_fixture("rvt_real", "tree")["data"]["objects"]
    ]
    props = [
        PropertyObject.model_validate(p)
        for p in model_fixture("rvt_real", "properties")["data"]["collection"]
    ]
    return [
        ElementInput(e.mark_code, e.category, e.external_id, e.props)
        for e in extract_elements(tree, props, ["Marca"], ["Category"])
    ]


REAL = ReconcileConfig(
    dimension_names=["SEÇÃO-Altura", "SEÇÃO-Largura", "PEÇA-Comprimento"],
    review_names=["Nome do tipo"],
)


def test_real_model_against_itself_is_all_unchanged() -> None:
    els = _real_elements()
    snaps = build_snapshots(els, REAL)
    assert len(snaps) == 19 and sum(s.count for s in snaps) == 33
    assert any(s.props.get("SEÇÃO-Largura") for s in snaps)  # lê o formato real ("40.000 cm")
    result = reconcile(snaps, build_snapshots(reversed(els), REAL), REAL)
    assert result.totals[Change.UNCHANGED] == 19


def test_real_model_section_change_like_r02() -> None:
    """Cenário da R02 publicada no Docs: pilares trocados de seção (60x60 → 80x80)."""
    import copy

    els = _real_elements()
    target = next(e for e in els if e.category == "Pilares estruturais" and e.mark_code)
    curr = []
    for e in els:
        if e.mark_code == target.mark_code:
            props = copy.deepcopy(dict(e.props))
            props["Cotas"]["SEÇÃO-Largura"] = "80.000 cm"
            props["Dados de identidade"]["Nome do tipo"] = "R-80x80cm-P05"
            e = ElementInput(e.mark_code, e.category, f"novo-{e.external_id}", props)
        curr.append(e)
    result = reconcile(build_snapshots(els, REAL), build_snapshots(curr, REAL), REAL)
    [changed] = result.of(Change.CHANGED)
    assert changed.code == target.mark_code
    before = dict(target.props)["Cotas"]["SEÇÃO-Largura"]
    assert changed.diffs[0] == PropDiff("SEÇÃO-Largura", before, "80.000 cm")
    assert changed.diffs[1].property == "Nome do tipo"
    assert changed.diffs[1].after == "R-80x80cm-P05"
    assert result.totals[Change.UNCHANGED] == 18


def test_config_from_settings() -> None:
    from tests.conftest import make_settings

    cfg = ReconcileConfig.from_settings(
        make_settings(
            review_property_names=" Nome do tipo , Armadura,",
            dimension_property_names="SEÇÃO-Altura,SEÇÃO-Largura",
            dimension_tolerance_mm=2,
        )
    )
    assert cfg.property_names == ["SEÇÃO-Altura", "SEÇÃO-Largura", "Nome do tipo", "Armadura"]
    assert cfg.tolerance_mm == 2 and cfg.is_dimension("seção-altura")
    default = ReconcileConfig.from_settings(make_settings()).review_names
    # padrão: só o tipo, que existe em qualquer modelo; nada específico de uma obra
    assert default == ["Nome do tipo", "Type Name", "ObjectType"]
