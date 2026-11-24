"""Numeração das unidades pela sequência de montagem Z → X → Y (passo 2; ordem de 2026-11-19).

O 3D manda o centro de gravidade das peças; a obra provisória e sem valores por peça é
renumerada uma única vez (permutação dos números da marca); o 1º valor trava a numeração;
nas obras `sequence`, a ligação pela ordem (NWD) segue a sequência e fica estável.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.aps.client import ApsClient
from app.models import (
    AuditLog,
    Element,
    Mark,
    ModelVersion,
    Obra,
    ParamDef,
    PieceUnit,
    PieceValue,
    User,
    VersionDiff,
)
from app.models.enums import Role
from app.services import piece_units, piece_values, processing, unit_sequence
from app.services.errors import NotFoundError
from app.services.extraction import ExtractedElement
from app.services.unit_matching import ElementIn, UnitIn, match, ordered_elements
from tests.conftest import as_user
from tests.test_piece_units import _linked, _obra, _units, _version

Z = {"a": 10.0, "b": 0.0, "c": 5.0}  # altura (Z): b, c, a (Z → X → Y)


async def _coords(
    session: AsyncSession, v: ModelVersion, z: dict[str, float]
) -> dict[int, tuple[float, float, float]]:
    rows = await session.execute(
        select(Element.dbid, Element.external_id).where(Element.version_id == v.id)
    )
    # Z decide; o X vai ao contrário, para provar que ele só entra depois do Z
    return {
        dbid: (10.0 - z[ext[-1]], 0.0, z[ext[-1]]) for dbid, ext in rows if ext and ext[-1] in z
    }


async def _numbers(session: AsyncSession, v: ModelVersion) -> dict[str, int]:
    """chave do elemento -> número da unidade ligada."""
    return {str(ext): n for ext, (n, _m) in (await _linked(session, v)).items()}


async def _text_param(session: AsyncSession, obra: Obra) -> ParamDef:
    p = ParamDef(name="Forma", type="text", scope="obra", obra_id=obra.id)
    p.level = "piece"
    session.add(p)
    await session.flush()
    return p


async def _user(session: AsyncSession) -> User:
    u = User(name="Fábrica", email="fab-seq@test", role=Role.FABRICA)
    session.add(u)
    await session.flush()
    return u


# ------------------------------------------------------------------ renumeração


async def test_provisional_obra_is_renumbered_by_sequence_once(session: AsyncSession) -> None:
    obra, mark = await _obra(session)
    v1, _ = await _version(session, obra, mark, 1, [(10, "a"), (11, "b"), (12, "c")])
    assert await _numbers(session, v1) == {"a": 1, "b": 2, "c": 3}  # nível/nome: provisória
    assert obra.unit_numbering == "provisional"

    r = await unit_sequence.store(session, v1.id, await _coords(session, v1, Z), None)
    assert (r.stored, r.renumbered, r.status.numbering) == (3, 3, "sequence")
    assert (r.status.pieces, r.status.stored) == (3, 3)
    assert await _numbers(session, v1) == {"b": 1, "c": 2, "a": 3}
    assert obra.sequence_axes == "zxy"

    audits = list(
        await session.scalars(
            select(AuditLog).where(AuditLog.entity == "piece_unit", AuditLog.action == "renumber")
        )
    )
    assert sorted(((a.before or {})["label"], (a.after or {})["label"]) for a in audits) == [
        ("PP001-1", "PP001-3"),
        ("PP001-2", "PP001-1"),
        ("PP001-3", "PP001-2"),
    ]
    assert await session.scalar(
        select(AuditLog.id).where(AuditLog.entity == "obra", AuditLog.action == "unit_numbering")
    )

    # 2ª vez (outro navegador, outras coordenadas): nada muda, os números são definitivos
    again = await unit_sequence.store(
        session, v1.id, await _coords(session, v1, {"a": 0.0, "b": 9.0, "c": 5.0}), None
    )
    assert (again.renumbered, again.relinked) == (0, False)
    assert await _numbers(session, v1) == {"b": 1, "c": 2, "a": 3}


async def test_renumbering_is_a_permutation_of_existing_numbers(session: AsyncSession) -> None:
    """A unidade sem peça mantém um número da marca; nenhum número novo aparece."""
    obra, mark = await _obra(session)
    await _version(session, obra, mark, 1, [(10, "a"), (11, "b"), (12, "c"), (13, "d")])
    v2, _ = await _version(session, obra, mark, 2, [(20, "a"), (21, "b"), (22, "c")])
    assert (await _units(session, obra))[4] == ("d", "unlinked")

    await unit_sequence.store(session, v2.id, await _coords(session, v2, Z), None)
    assert await _numbers(session, v2) == {"b": 1, "c": 2, "a": 3}
    units = await _units(session, obra)
    assert sorted(units) == [1, 2, 3, 4] and units[4] == ("d", "unlinked")


async def test_piece_value_before_centroids_locks_numbering(session: AsyncSession) -> None:
    obra, mark = await _obra(session)
    v1, _ = await _version(session, obra, mark, 1, [(10, "a"), (11, "b"), (12, "c")])
    param = await _text_param(session, obra)
    user = await _user(session)
    unit = await session.scalar(
        select(PieceUnit).where(PieceUnit.number == 1, PieceUnit.obra_id == obra.id)
    )
    assert unit is not None
    await piece_values.save_values(
        session, obra.id, unit.id, [piece_values.Change(param.id, "F-12", None)], user
    )
    assert obra.unit_numbering == "fixed"

    r = await unit_sequence.store(session, v1.id, await _coords(session, v1, Z), None)
    assert (r.stored, r.renumbered, r.status.numbering) == (3, 0, "fixed")
    assert await _numbers(session, v1) == {"a": 1, "b": 2, "c": 3}  # "F-12" segue na PP001-1


async def test_legacy_value_without_lock_is_respected(session: AsyncSession) -> None:
    """Valor gravado antes da trava existir (ou por fora): não renumera, trava."""
    obra, mark = await _obra(session)
    v1, _ = await _version(session, obra, mark, 1, [(10, "a"), (11, "b")])
    param = await _text_param(session, obra)
    unit = await session.scalar(select(PieceUnit).where(PieceUnit.obra_id == obra.id).limit(1))
    assert unit is not None
    session.add(PieceValue(unit_id=unit.id, def_id=param.id, value="F-1"))
    await session.flush()
    r = await unit_sequence.store(session, v1.id, await _coords(session, v1, Z), None)
    assert (r.renumbered, r.status.numbering) == (0, "fixed")


async def test_older_version_only_stores(session: AsyncSession) -> None:
    obra, mark = await _obra(session)
    v1, _ = await _version(session, obra, mark, 1, [(10, "a"), (11, "b"), (12, "c")])
    await _version(session, obra, mark, 2, [(20, "a"), (21, "b"), (22, "c")])
    r = await unit_sequence.store(session, v1.id, await _coords(session, v1, Z), None)
    assert (r.stored, r.renumbered, r.status.numbering) == (3, 0, "provisional")


# ------------------------------------------------------------------ NWD (ligação pela ordem)


async def test_nwd_numbering_stays_stable_on_relink_and_follows_new_versions(
    session: AsyncSession,
) -> None:
    obra, mark = await _obra(session, "modelo.nwd")
    v1, _ = await _version(session, obra, mark, 1, [(10, "0/a"), (11, "0/b"), (12, "0/c")])
    await unit_sequence.store(session, v1.id, await _coords(session, v1, Z), None)
    assert await _numbers(session, v1) == {"0/b": 1, "0/c": 2, "0/a": 3}

    # reprocessamento da mesma versão (troca de regra): os centros seguem; o par também
    param = await _text_param(session, obra)
    unit3 = await session.scalar(
        select(PieceUnit).where(PieceUnit.obra_id == obra.id, PieceUnit.number == 3)
    )
    assert unit3 is not None
    session.add(PieceValue(unit_id=unit3.id, def_id=param.id, value="F-3"))
    await session.flush()
    await piece_units.link_version(session, v1)
    # com valor só na PP001-3, ela continua na peça de cima (antes ia para a 1ª da ordem)
    assert await _numbers(session, v1) == {"0/b": 1, "0/c": 2, "0/a": 3}

    # versão nova: sem centros, a ordem é provisória; com eles, as ligações seguem a sequência
    v2, _ = await _version(session, obra, mark, 2, [(20, "1/a"), (21, "1/b"), (22, "1/c")])
    assert await _numbers(session, v2) == {"1/a": 1, "1/b": 2, "1/c": 3}  # "conferir"
    r = await unit_sequence.store(session, v2.id, await _coords(session, v2, Z), None)
    assert (r.renumbered, r.relinked) == (0, True)
    assert await _numbers(session, v2) == {"1/b": 1, "1/c": 2, "1/a": 3}


async def test_nwd_legacy_obra_links_by_its_own_axes(session: AsyncSession) -> None:
    """Obra numerada em X → Y → Z (antes de 2026-11-19): a versão nova liga as peças pela
    ordem DELA, senão as peças (e os valores) trocariam de lugar dentro da marca."""
    obra, mark = await _obra(session, "modelo.nwd")
    v1, _ = await _version(session, obra, mark, 1, [(10, "0/a"), (11, "0/b"), (12, "0/c")])
    await unit_sequence.store(session, v1.id, await _coords(session, v1, Z), None)
    obra.sequence_axes = "xyz"  # como a migração 0022 marca as obras já numeradas
    await session.flush()

    v2, _ = await _version(session, obra, mark, 2, [(20, "1/a"), (21, "1/b"), (22, "1/c")])
    r = await unit_sequence.store(session, v2.id, await _coords(session, v2, Z), None)
    assert (r.renumbered, r.relinked) == (0, True)
    # X crescente (em _coords, X = 10 - Z): a, c, b; em Z → X → Y seria b, c, a
    assert await _numbers(session, v2) == {"1/a": 1, "1/c": 2, "1/b": 3}


async def _legacy_obra_with_value(
    session: AsyncSession,
) -> tuple[Obra, ModelVersion, ParamDef]:
    """Obra NWD numerada em X → Y → Z (como a 9121): a, c, b = 1, 2, 3; valor na PP001-1."""
    obra, mark = await _obra(session, "modelo.nwd")
    v1, _ = await _version(session, obra, mark, 1, [(10, "0/a"), (11, "0/b"), (12, "0/c")])
    for e in await session.scalars(select(Element).where(Element.version_id == v1.id)):
        z = Z[str(e.external_id)[-1]]
        e.centroid = [10.0 - z, 0.0, z]  # X = 10 - Z: em X → Y → Z a ordem é a, c, b
    obra.unit_numbering, obra.sequence_axes = "sequence", "xyz"
    await session.flush()
    await piece_units.link_version(session, v1)
    assert await _numbers(session, v1) == {"0/a": 1, "0/c": 2, "0/b": 3}
    param = await _text_param(session, obra)
    unit1 = await session.scalar(
        select(PieceUnit).where(PieceUnit.obra_id == obra.id, PieceUnit.number == 1)
    )
    assert unit1 is not None
    session.add(PieceValue(unit_id=unit1.id, def_id=param.id, value="F-A"))
    await session.flush()
    return obra, v1, param


async def test_renumber_obra_to_current_order_keeps_values_on_the_same_piece(
    session: AsyncSession,
) -> None:
    """Decisão de 2026-11-19: a 9121 passa para Z → X → Y; os valores seguem a peça física."""
    obra, v1, param = await _legacy_obra_with_value(session)
    user = await _user(session)

    dry = await unit_sequence.renumber_obra(session, obra.id, user, apply=False)
    assert (dry.changed, dry.applied, dry.pieces) == (2, False, 3)  # a: 1->3, b: 3->1
    assert await _numbers(session, v1) == {"0/a": 1, "0/c": 2, "0/b": 3}  # nada gravado

    r = await unit_sequence.renumber_obra(session, obra.id, user, apply=True)
    assert (r.changed, r.applied) == (2, True)
    assert await _numbers(session, v1) == {"0/b": 1, "0/c": 2, "0/a": 3}
    assert (obra.unit_numbering, obra.sequence_axes) == ("sequence", "zxy")
    # o valor continua na peça "a" (agora PP001-3)
    value_unit = await session.scalar(
        select(PieceValue.unit_id).where(PieceValue.def_id == param.id)
    )
    number = await session.scalar(select(PieceUnit.number).where(PieceUnit.id == value_unit))
    assert number == 3
    audit_row = await session.scalar(
        select(AuditLog).where(AuditLog.entity == "obra", AuditLog.action == "unit_numbering")
    )
    assert audit_row is not None
    assert audit_row.before == {"unit_numbering": "sequence", "sequence_axes": "xyz"}
    assert (audit_row.after or {})["reason"] == "manual"
    assert audit_row.user_id == user.id

    # versão nova: liga pela ordem nova, a mesma dos números
    mark = await session.scalar(select(PieceUnit.mark_id).where(PieceUnit.obra_id == obra.id))
    assert mark is not None
    v2, _ = await _version(
        session, obra, await session.get_one(Mark, mark), 2, [(20, "1/a"), (21, "1/b"), (22, "1/c")]
    )
    await unit_sequence.store(session, v2.id, await _coords(session, v2, Z), None)
    assert await _numbers(session, v2) == {"1/b": 1, "1/c": 2, "1/a": 3}


async def test_renumber_obra_refuses_other_states(session: AsyncSession) -> None:
    obra, mark = await _obra(session)
    v1, _ = await _version(session, obra, mark, 1, [(10, "a"), (11, "b")])
    with pytest.raises(ValueError, match="provisional"):
        await unit_sequence.renumber_obra(session, obra.id, None, apply=True)
    obra.unit_numbering = "sequence"
    await session.flush()
    with pytest.raises(ValueError, match="centros de gravidade"):  # sem os centros do 3D
        await unit_sequence.renumber_obra(session, obra.id, None, apply=True)
    with pytest.raises(NotFoundError):
        await unit_sequence.renumber_obra(session, 999_999, None, apply=True)
    assert v1.id


async def test_renumber_fixed_obra_only_without_piece_values(session: AsyncSession) -> None:
    """Travada por um valor que depois foi apagado: renumera; com valor, recusa."""
    obra, mark = await _obra(session)
    v1, _ = await _version(session, obra, mark, 1, [(10, "a"), (11, "b"), (12, "c")])
    for e in await session.scalars(select(Element).where(Element.version_id == v1.id)):
        z = Z[str(e.external_id)[-1]]
        e.centroid = [10.0 - z, 0.0, z]
    obra.unit_numbering = "fixed"
    param = await _text_param(session, obra)
    unit = await session.scalar(select(PieceUnit).where(PieceUnit.obra_id == obra.id).limit(1))
    assert unit is not None
    value = PieceValue(unit_id=unit.id, def_id=param.id, value="F-1")
    session.add(value)
    await session.flush()
    with pytest.raises(ValueError, match="fixed"):
        await unit_sequence.renumber_obra(session, obra.id, None, apply=True)

    value.value = None  # apagado depois
    await session.flush()
    r = await unit_sequence.renumber_obra(session, obra.id, None, apply=True)
    assert r.applied
    assert await _numbers(session, v1) == {"b": 1, "c": 2, "a": 3}
    assert (obra.unit_numbering, obra.sequence_axes) == ("sequence", "zxy")


async def test_cli_units_renumber(
    session: AsyncSession, aps: ApsClient, capsys: pytest.CaptureFixture[str]
) -> None:
    from app.cli import run as cli_run
    from tests.conftest import make_settings

    obra, v1, _param = await _legacy_obra_with_value(session)
    admin = User(name="Admin", email="admin-renum@test", role=Role.ADMIN)
    session.add(admin)
    await session.flush()
    args = ["units", "renumber", "--obra", str(obra.id), "--user", admin.email]
    assert await cli_run(args, make_settings(), session, aps) == 0
    assert "2 de 3 peças mudariam" in capsys.readouterr().out
    assert await _numbers(session, v1) == {"0/a": 1, "0/c": 2, "0/b": 3}
    assert await cli_run([*args, "--yes"], make_settings(), session, aps) == 0
    assert "2 peças renumeradas em Z → X → Y (por Admin)" in capsys.readouterr().out
    assert await _numbers(session, v1) == {"0/b": 1, "0/c": 2, "0/a": 3}
    assert (
        await cli_run(["units", "renumber", "--obra", "999999"], make_settings(), session, aps) == 2
    )


async def test_reprocess_keeps_stored_centroids(session: AsyncSession) -> None:
    obra, mark = await _obra(session)
    v1, _ = await _version(session, obra, mark, 1, [(10, "a"), (11, "b")])
    await unit_sequence.store(session, v1.id, {10: (1.0, 2.0, 3.0)}, None)
    extracted = [
        ExtractedElement(dbid, ext, f"Pilar {ext}", "Pilar", "PP001", "PP001", {})
        for dbid, ext in [(10, "a"), (11, "b")]
    ]
    config = processing.ProcessingConfig(mark_names=["Marca"], category_names=["Category"])
    await processing._store(session, v1, extracted, config)
    rows = dict(
        (
            await session.execute(
                select(Element.dbid, Element.centroid).where(Element.version_id == v1.id)
            )
        ).all()
    )
    assert rows == {10: [1.0, 2.0, 3.0], 11: None}
    # a peça sem centro fica sem centro (não conta como guardada)
    s = await unit_sequence.status(session, v1.id)
    assert (s.pieces, s.stored) == (2, 1)
    assert (
        await session.scalar(
            select(func.count()).where(Element.version_id == v1.id, Element.centroid.is_(None))
        )
        == 1
    )


# ------------------------------------------------------------------ função pura


def test_pairing_by_order_keeps_numbers_when_there_is_a_piece_for_every_unit() -> None:
    units = [UnitIn(1, 1, None, False), UnitIn(2, 2, None, False), UnitIn(5, 5, None, True)]
    elems = [
        ElementIn(10, None, "T", "A"),
        ElementIn(11, None, "T", "B"),
        ElementIn(12, None, "T", "C"),
    ]
    r = match(units, elems, use_key=False)
    assert sorted((lk.unit_id, lk.element_id) for lk in r.links) == [(1, 10), (2, 11), (5, 12)]


def test_sequence_order_puts_elements_without_centroid_last() -> None:
    elems = [
        ElementIn(1, None, "T", "A", (0.0, 0.0, 9.0)),
        ElementIn(2, None, "T", "B", None),
        ElementIn(3, None, "T", "C", (0.0, 0.0, 1.0)),
    ]
    assert [e.id for e in ordered_elements(elems, by_sequence=True)] == [3, 1, 2]
    assert [e.id for e in ordered_elements(elems)] == [1, 2, 3]


# ------------------------------------------------------------------ API


async def test_api_status_put_and_validation(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    obra, mark = await _obra(session)
    v1, _ = await _version(session, obra, mark, 1, [(10, "a"), (11, "b"), (12, "c")])
    reader = User(name="Leitura", email="leit-seq@test", role=Role.LEITURA)
    session.add(reader)
    await session.flush()
    h = as_user(reader)

    r = await client.get(f"/api/versions/{v1.id}/centroids", headers=h)
    assert r.json() == {"pieces": 3, "stored": 0, "numbering": "provisional"}

    for bad in ({"10": [1, 2]}, {"10": [1e9, 0, 0]}, {"x": [0, 0, 0]}):
        r = await client.put(
            f"/api/versions/{v1.id}/centroids", json={"coordinates": bad}, headers=h
        )
        assert r.status_code == 422, (bad, r.text)

    body: dict[str, Any] = {
        "coordinates": {str(k): list(v) for k, v in (await _coords(session, v1, Z)).items()}
    }
    r = await client.put(f"/api/versions/{v1.id}/centroids", json=body, headers=h)
    assert r.status_code == 200, r.text
    assert r.json() == {
        "pieces": 3,
        "stored": 3,
        "numbering": "sequence",
        "renumbered": 3,
        "relinked": False,
    }
    await session.refresh(obra)  # sessão do teste é a mesma da API (updated_at do servidor)
    o = await client.get(f"/api/obras/{obra.id}", headers=h)
    assert o.json()["unit_numbering"] == "sequence"


async def test_api_version_not_ready(client: httpx.AsyncClient, session: AsyncSession) -> None:
    obra, _mark = await _obra(session)
    v = ModelVersion(
        obra_id=obra.id, acc_version_id="urn:nr", version_number=1, status="processing"
    )
    session.add(v)
    reader = User(name="L", email="l-seq@test", role=Role.LEITURA)
    session.add(reader)
    await session.flush()
    r = await client.put(
        f"/api/versions/{v.id}/centroids", json={"coordinates": {}}, headers=as_user(reader)
    )
    assert r.status_code == 409 and r.json()["code"] == "version_not_ready"


async def test_version_banner_labels_follow_the_new_numbers(session: AsyncSession) -> None:
    obra, mark = await _obra(session)
    v1, _ = await _version(session, obra, mark, 1, [(10, "a"), (11, "b"), (12, "c")])
    first = await session.scalar(
        select(PieceUnit).where(PieceUnit.obra_id == obra.id, PieceUnit.number == 1)
    )
    assert first is not None
    session.add(
        VersionDiff(
            version_id=v1.id,
            diff={"units": {"new": 1, "new_units": [{"unit_id": first.id, "label": "PP001-1"}]}},
        )
    )
    await session.flush()
    await unit_sequence.store(session, v1.id, await _coords(session, v1, Z), None)
    row = await session.scalar(select(VersionDiff).where(VersionDiff.version_id == v1.id))
    assert row is not None
    assert row.diff["units"]["new_units"] == [{"unit_id": first.id, "label": "PP001-3"}]
