"""Tipo da peça para o filtro da lista (2026-11-18): exemplos reais da 9121 (NWD), da
9480 (IFC, montagens) e do ORC (RVT)."""

from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Element, Mark, ModelVersion, Obra, User
from app.models.enums import Role
from app.services import piece_type
from app.services.piece_type import ESCADA, LAJE, OUTROS, PILAR, QUADRO, classify
from tests.conftest import as_user

NWD_SLAB: dict[str, Any] = {
    "Item": {"Name": "CASSOL-PREO-Laje-Alveolar_LP20", "Type": "Quadro estrutural: X: LP20"},
    "Level": {"Name": "PAVIMENTO 1"},
}
IFC_SLAB: dict[str, Any] = {
    "Name": "IfcBuildingElementProxy::Montagem Quadro estrutural:LA3062:5416487",
    "IFC Attributes": {"ObjectType": "Montagem Quadro estrutural:LA3062"},
    "Corpo · IFC Type Attributes": {"Name": "CASSOL-PREO-Laje-Alveolar_LP15:LP15-125cm"},
}


def test_real_names() -> None:
    assert classify("Pilares estruturais", "CASSOL-PREO-Pilar-R", "PP001", {}) == PILAR
    assert classify("Pilares estruturais", "Pilares em V13", "PP040", {}) == PILAR
    assert classify("Quadro estrutural", "CASSOL-PREO-Viga-T", "VP001", {}) == QUADRO
    assert classify("Quadro estrutural", "CASSOL-IN LOCO-Viga-R", "VA010", {}) == QUADRO
    assert (
        classify("Quadro estrutural", "CASSOL-PREO-Laje-Alveolar_LP20", "LA002", NWD_SLAB) == LAJE
    )
    assert classify("Conexões estruturais", "CASSOL-PREO-Laje-Macica", "LM001", {}) == LAJE
    assert classify("Conexões estruturais", "CASSOL-PREO-Escada", "EC001", {}) == ESCADA
    assert classify("Fundações estruturais", "CASSOL-IN LOCO-Sapata-CO", "SP001", {}) == OUTROS
    assert classify("Conexões estruturais", "CASSOL-PREO-Complemento", "EC002", {}) == OUTROS


def test_metal_is_out_of_scope() -> None:
    assert classify("Quadro estrutural", "GERDAU-MET-Viga-W", "CM101", {}) == OUTROS


def test_ifc_assembly_finds_lp_in_the_body_type() -> None:
    """Na montagem do IFC o nome não diz LP; o tipo do corpo diz."""
    props = {**IFC_SLAB, "Corpo · IFC Type Attributes": {"Name": "CASSOL-PREO-X_LP15"}}
    assert classify("Quadro estrutural", str(props["Name"]), "XX001", props) == LAJE


def test_slab_codes_only_as_separate_uppercase_tokens() -> None:
    for code in ("LA002", "LAA10", "LP26,1", "LM350"):
        assert classify("Quadro estrutural", "Peça", code, {}) == LAJE, code
    for name in ("Viga HELP", "Viga Lateral", "PLATA", "Viga-lp"):
        assert classify("Quadro estrutural", name, "VA001", {}) == QUADRO, name


def test_level_name_does_not_make_a_slab() -> None:
    props = {
        "Level": {"Name": "LAJE COBERTURA"},
        "Dados de identidade": {"Nome do tipo": "V-30x60"},
    }
    assert classify("Quadro estrutural", "CASSOL-PREO-Viga-R [1]", "VA001", props) == QUADRO
    rvt = {"Dados de identidade": {"Nome do tipo": "Laje alveolar 20"}}
    assert classify("Quadro estrutural", "Familia [2]", "X001", rvt) == LAJE


async def test_marks_api_has_piece_type_and_backfill(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    obra = Obra(code="OB-TIPO", name="Tipos", acc_item_name="t.nwd")
    session.add(obra)
    await session.flush()
    v = ModelVersion(obra_id=obra.id, acc_version_id="urn:tipo", version_number=1, status="ready")
    pp = Mark(obra_id=obra.id, code="PP001", category="Pilares estruturais")
    la = Mark(obra_id=obra.id, code="LA002", category="Quadro estrutural")
    user = User(name="L", email="l-tipo@test", role=Role.LEITURA)
    session.add_all([v, pp, la, user])
    await session.flush()
    session.add_all(
        [
            Element(version_id=v.id, dbid=1, category=pp.category, mark_id=pp.id, name="Pilar"),
            Element(version_id=v.id, dbid=2, category=la.category, mark_id=la.id, props=NWD_SLAB),
        ]
    )
    await session.flush()
    assert await piece_type.rebuild_version(session, v) == 2  # versões antigas
    r = await client.get(f"/api/versions/{v.id}/marks", headers=as_user(user))
    assert r.status_code == 200, r.text
    assert {m["code"]: m["piece_type"] for m in r.json()} == {"PP001": PILAR, "LA002": LAJE}
