"""Regra de ligação das unidades de peça (função pura, sem banco)."""

from __future__ import annotations

from app.services.unit_matching import KEY, NEW, ORDER, ElementIn, UnitIn, element_order, match


def U(uid: int, number: int, ext: str | None, values: bool = False) -> UnitIn:
    return UnitIn(uid, number, ext, values)


def E(
    eid: int, ext: str | None, level: str | None = "TÉRREO", name: str | None = "Pilar"
) -> ElementIn:
    return ElementIn(eid, ext, level, name)


def links(result: object) -> list[tuple[int | None, int, str, int | None]]:
    return sorted(
        ((lk.unit_id, lk.element_id, lk.method, lk.new_number) for lk in result.links),  # type: ignore[attr-defined]
        key=lambda t: t[1],
    )


def test_first_version_creates_numbered_units_in_stable_order() -> None:
    r = match([], [E(30, "c", "1º PAV"), E(10, "a", "TÉRREO"), E(20, "b", None)])
    # ordem: nível (sem nível por último), nome, externalId — nunca o id/dbId
    assert [(lk.element_id, lk.new_number, lk.method) for lk in r.links] == [
        (30, 1, NEW),
        (10, 2, NEW),
        (20, 3, NEW),
    ]
    assert r.leftover == []


def test_moved_element_keeps_its_unit_by_key() -> None:
    # outra versão: os elementos têm outro id (dbId muda), a chave é a mesma
    units = [U(1, 1, "a"), U(2, 2, "b"), U(3, 3, "c")]
    r = match(units, [E(103, "c"), E(101, "a"), E(102, "b")])
    assert links(r) == [(1, 101, KEY, None), (2, 102, KEY, None), (3, 103, KEY, None)]


def test_recreated_element_keeps_the_unit_by_order() -> None:
    # a peça da unidade 2 foi apagada e recriada: chave nova
    units = [U(1, 1, "a"), U(2, 2, "b", values=True), U(3, 3, "c")]
    r = match(units, [E(101, "a"), E(109, "b-nova"), E(103, "c")])
    assert links(r) == [(1, 101, KEY, None), (3, 103, KEY, None), (2, 109, ORDER, None)]
    by_order = next(lk for lk in r.links if lk.method == ORDER)
    assert by_order.external_id == "b-nova"  # a unidade passa a ter a nova chave


def test_more_pieces_get_new_units_and_numbers_are_never_reused() -> None:
    # a unidade 3 está sem peça (registrada); a peça nova ganha o 4, não o 3
    units = [U(1, 1, "a"), U(2, 2, "b"), U(3, 3, "c")]
    r = match(units, [E(101, "a"), E(102, "b"), E(104, None, name="Z"), E(105, None, name="Y")])
    by_unit = {lk.element_id: (lk.unit_id, lk.method, lk.new_number) for lk in r.links}
    assert by_unit[101] == (1, KEY, None) and by_unit[102] == (2, KEY, None)
    # a 3 (sem par pela chave) pega um dos elementos pela ordem; o outro vira a unidade 4
    assert by_unit[105] == (3, ORDER, None)  # "Y" < "Z"
    assert by_unit[104] == (None, NEW, 4)
    assert r.leftover == []


def test_fewer_pieces_leave_units_without_piece() -> None:
    units = [U(1, 1, "a"), U(2, 2, "b"), U(3, 3, "c")]
    r = match(units, [E(101, "a"), E(103, "c")])
    assert links(r) == [(1, 101, KEY, None), (3, 103, KEY, None)]
    assert [u.id for u in r.leftover] == [2]


def test_units_with_values_are_paired_first_and_the_empty_one_is_left() -> None:
    # 2 unidades sem par e 1 elemento sem par: fica com a peça a unidade COM valores
    units = [U(1, 1, "a"), U(2, 2, "b"), U(3, 3, "c", values=True)]
    r = match(units, [E(101, "a"), E(109, "nova")])
    assert links(r) == [(1, 101, KEY, None), (3, 109, ORDER, None)]
    assert [(u.id, u.has_values) for u in r.leftover] == [(2, False)]


def test_orphan_with_values_when_the_mark_lost_all_pieces() -> None:
    r = match([U(1, 1, "a", values=True), U(2, 2, "b")], [])
    assert r.links == []
    assert [(u.id, u.has_values) for u in r.leftover] == [(1, True), (2, False)]


def test_same_input_gives_same_result() -> None:
    units = [U(1, 1, "a"), U(2, 2, "x")]
    elems = [E(101, "a"), E(102, "y", name="B"), E(103, "z", name="A")]
    assert links(match(units, elems)) == links(match(list(reversed(units)), list(reversed(elems))))


def test_nwd_has_no_key_everything_by_order() -> None:
    units = [U(1, 1, "0/1/0"), U(2, 2, "0/1/1")]
    r = match(units, [E(101, "0/1/0", name="B"), E(102, "0/1/1", name="A")], use_key=False)
    # sem chave: a ordem dos elementos (nome A antes de B) define o par
    assert links(r) == [(2, 101, ORDER, None), (1, 102, ORDER, None)]


def test_older_version_only_links_and_never_creates() -> None:
    r = match([U(1, 1, "a")], [E(101, "a"), E(102, "b")], create=False)
    assert links(r) == [(1, 101, KEY, None)]


def test_duplicated_key_links_only_once() -> None:
    r = match([U(1, 1, "a")], [E(101, "a"), E(102, "a")])
    assert sorted(lk.method for lk in r.links) == [KEY, NEW]


def test_element_order_puts_missing_level_last() -> None:
    elems = [E(1, "x", None, "A"), E(2, "y", "B", "A"), E(3, "z", "A", "B")]
    assert [e.id for e in sorted(elems, key=element_order)] == [3, 2, 1]
