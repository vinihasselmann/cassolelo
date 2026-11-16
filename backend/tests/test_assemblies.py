"""Montagens (docs/montagens.md): NWD/RVT com vínculos e IFC com IfcBuildingElementProxy.

Modelos sintéticos com a MESMA estrutura vista nos arquivos reais da obra 9480.

NWD (.rvt central com um vínculo por peça):
- 2 "TÉRREO" (nível do modelo central) > Ambientes > 4 ambiente (não é peça)
- 10 vínculo E1312 ("Marca" 28 do próprio vínculo, que deve ser ignorada)
    > 14 pilar PP312 (corpo, 30 cm) > 15 geometria
    > 17 consolo PP312 (Marca C23) · 18 conjunto de alças PP312 > 19 alça (aninhada)
- 30 vínculo das lajes: 32 e 33 LA3037 (2 lajes idênticas), 34 LA3011, 35 alça LA3037
- 40 vínculo da escada EC301 (sem corpo de pilar/viga/laje): 42 escada, 43 alça, 44 espera
- 50 vínculo com uma viga SEM montagem (51): peça sem marca
"""

from __future__ import annotations

from typing import Any

import httpx
import respx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.aps.client import ApsClient
from app.aps.schemas import PropertyObject, TreeNode
from app.models import Element, ModelVersion, Obra, User
from app.models.enums import Role
from app.services.assemblies import extract_assemblies, is_ifc
from app.services.extraction import extract_elements, find_prop
from app.services.processing import ProcessingConfig, process_version
from tests.apsfakes import MD, Sleeps, mock_token
from tests.conftest import as_user

RULE = ["Nome da montagem", "Marca"]
CATS = ["Category", "Categoria", "IfcClass"]
BODIES = ["Pilares estruturais", "Quadro estrutural"]


def node(oid: int, name: str, *children: dict[str, Any]) -> dict[str, Any]:
    return {"objectid": oid, "name": name, "objects": list(children)}


def inst(eid: str, category: str, montagem: str | None = None, **extra: Any) -> dict[str, Any]:
    element: dict[str, Any] = {"Id": eid, "Category": category, **extra}
    if montagem:
        element["Nome da montagem"] = montagem
    return {"Item": {"Name": eid}, "Element": element, "Fase criada": {"Category": "Fases"}}


NWD_TREE = [
    node(
        1,
        "obra.nwd",
        node(2, "TÉRREO", node(3, "Ambientes", node(4, "Sala"))),
        node(
            10,
            "9480-E1312.rvt : 148 : localização Interno",
            node(
                11,
                "<No level>",
                node(
                    12,
                    "Pilares estruturais",
                    node(13, "CASSOL-PREO-Pilar-R", node(14, "R-30x50", node(15, "geo"))),
                ),
                node(
                    16,
                    "Conexões estruturais",
                    node(17, "Consolo"),
                    node(18, "Conjunto", node(19, "Alça")),
                ),
            ),
        ),
        node(
            30,
            "9480-LAJ-MON.rvt : 64 : localização <Não Compartilhado>",
            node(
                31,
                "Quadro estrutural",
                node(32, "LP15"),
                node(33, "LP15"),
                node(34, "LP15"),
                node(35, "Alça"),
            ),
        ),
        node(
            40,
            "9480-E5301.rvt : 114 : localização Interno",
            node(
                41,
                "Conexões estruturais",
                node(42, "Escada"),
                node(43, "Alça base"),
                node(44, "Espera"),
            ),
        ),
        node(50, "9480-E9999.rvt : 1 : localização Interno", node(51, "Viga sem montagem")),
    )
]
NWD_PROPS: dict[int, dict[str, Any]] = {
    4: inst("r1", "Ambientes"),
    10: {"RevitLinkInstance": {"Marca": "28"}},
    14: inst("p1", "Pilares estruturais", "PP312", Largura="30.0 cm", Comprimento="600.0 cm"),
    15: {"Item": {"Name": "geo"}},
    17: inst("c1", "Conexões estruturais", "PP312", Marca="C23"),
    18: inst("a0", "Conexões estruturais", "PP312"),
    19: inst("a1", "Conexões estruturais", "PP312"),
    32: inst("l1", "Quadro estrutural", "LA3037"),
    33: inst("l2", "Quadro estrutural", "LA3037"),
    34: inst("l3", "Quadro estrutural", "LA3011"),
    35: inst("la", "Conexões estruturais", "LA3037"),
    42: inst("e1", "Conexões estruturais", "EC301", Largura="120 cm", Volume="1.2 m^3"),
    43: inst("e2", "Conexões estruturais", "EC301"),
    44: inst("e3", "Enrijecedores estruturais", "EC301"),
    51: inst("v9", "Quadro estrutural"),
}


def _tree(raw: list[dict[str, Any]]) -> list[TreeNode]:
    return [TreeNode.model_validate(n) for n in raw]


def _props(raw: dict[int, dict[str, Any]]) -> list[PropertyObject]:
    return [
        PropertyObject.model_validate(
            {"objectid": oid, "name": f"n{oid}", "externalId": f"ext-{oid}", "properties": p}
        )
        for oid, p in raw.items()
    ]


def _nwd() -> dict[int, Any]:
    els = extract_assemblies(_tree(NWD_TREE), _props(NWD_PROPS), RULE, CATS, BODIES)
    return {e.dbid: e for e in els}


def test_nwd_one_link_per_piece_uses_link_node_with_body_props() -> None:
    els = _nwd()
    pp = els[10]  # o nó do vínculo: no 3D destaca a peça inteira (com consolos)
    assert (pp.mark_code, pp.category, pp.external_id) == ("PP312", "Pilares estruturais", "ext-14")
    assert pp.props["Element"]["Largura"] == "30.0 cm"  # propriedades do corpo
    assert set(pp.member_dbids) >= {11, 14, 15, 17, 18, 19}
    # a "Marca" do vínculo (28) e a do consolo (C23) não viram peças
    assert {e.mark_code for e in els.values()} == {"PP312", "LA3037", "LA3011", "EC301", None}


def test_nwd_link_with_many_assemblies_counts_each_body() -> None:
    els = _nwd()
    assert [d for d, e in els.items() if e.mark_code == "LA3037"] == [32, 33]  # 2 lajes
    assert [d for d, e in els.items() if e.mark_code == "LA3011"] == [34]
    assert els[32].member_dbids == ()  # alça 35 não é atribuída a uma laje específica


def test_nwd_assembly_without_body_is_one_piece() -> None:
    escada = _nwd()[40]
    assert escada.mark_code == "EC301"
    assert escada.category == "Conexões estruturais"  # a mais comum entre os membros
    assert escada.props["Element"]["Volume"] == "1.2 m^3"  # do maior membro
    assert set(escada.member_dbids) == {41, 42, 43, 44}


def test_nwd_body_without_assembly_is_piece_without_mark_and_rest_ignored() -> None:
    els = _nwd()
    assert els[51].mark_code is None and els[51].category == "Quadro estrutural"
    assert sorted(els) == [10, 32, 33, 34, 40, 51]  # níveis, ambientes e vínculos não
    seen = [d for e in els.values() for d in (e.dbid, *e.member_dbids)]
    assert len(seen) == len(set(seen))  # nenhum dbId em duas peças


# ------------------------------------------------------------------------------- IFC


def ifc(oid: int, klass: str, object_type: str = "", **extra: Any) -> dict[str, Any]:
    return {"IFC Attributes": {"IfcClass": klass, "ObjectType": object_type, **extra}}


IFC_TREE = [
    node(
        1,
        "obra",
        node(
            2,
            "IfcProject",
            node(
                3,
                "IfcBuildingStorey",
                node(
                    10, "Montagem PP312", node(11, "Pilar"), node(12, "Consolo"), node(13, "Alça")
                ),
                node(20, "Consolo solto"),
            ),
        ),
        node(30, "IfcGroup", node(31, "Grupo de modelos")),
    )
]
IFC_PROPS = {
    2: ifc(2, "IfcProject"),
    3: ifc(3, "IfcBuildingStorey"),
    10: ifc(10, "IfcBuildingElementProxy", "Montagem Pilares estruturais:PP312", Tag="5425745"),
    11: {
        **ifc(11, "IfcColumn", "CASSOL-PREO-Pilar-R:R-30x50cm", IfcDecomposes="Montagem ..."),
        "BaseQuantities": {"NetVolume": "2.504 m^3"},
    },
    12: {
        **ifc(12, "IfcColumn", "CASSOL-PREO-Consolo:CP24"),
        "BaseQuantities": {"Length": "24.000 cm", "NetVolume": "0.018 m^3"},
    },
    13: ifc(13, "IfcColumn", "CASSOL-ACS-Alça:A50"),
    20: ifc(20, "IfcColumn", "CASSOL-PREO-Consolo:CP24"),
    30: ifc(30, "IfcGroup"),
    31: ifc(31, "IfcGroup", "Grupo de modelos:juntas"),
}


def test_ifc_assembly_node_is_the_piece_with_name_and_naming_category() -> None:
    props = _props(IFC_PROPS)
    assert is_ifc(props)
    els = {e.dbid: e for e in extract_elements(_tree(IFC_TREE), props, RULE, CATS)}
    assert sorted(els) == [10, 20]  # grupos não são peças; membros ficam dentro
    pp = els[10]
    assert (pp.mark_code, pp.category) == ("PP312", "Pilares estruturais")
    assert pp.member_dbids == (11, 12, 13)
    assert pp.props["Montagem"]["Nome da montagem"] == "PP312"
    # o corpo (membro de maior volume: o pilar, não o consolo) empresta tipo e volume:
    # busca por seção, validação e revisão entre versões funcionam no IFC
    assert pp.props["Corpo · BaseQuantities"]["NetVolume"] == "2.504 m^3"
    assert find_prop(pp.props, ["ObjectType"]) == "CASSOL-PREO-Pilar-R:R-30x50cm"
    assert find_prop(pp.props, ["IfcClass"]) == "IfcColumn"  # do corpo
    assert els[20].mark_code is None  # consolo solto: peça sem marca (vai ao relatório)


def test_ifc_without_assembly_name_in_rule_has_no_mark() -> None:
    """A regra da obra decide: com "Marca, Mark" o IFC de montagens não tem marca."""
    els = extract_elements(_tree(IFC_TREE), _props(IFC_PROPS), ["Marca", "Mark"], CATS)
    assert all(e.mark_code is None for e in els)


# ----------------------------------------------------------------- processamento + API

URN = "dXJubndkbW9udA"
GUID = "nwd-3d-0001"


def _mock_nwd() -> None:
    respx.get(f"{MD}/{URN}/metadata").respond(
        200,
        json={
            "data": {
                "type": "metadata",
                "metadata": [{"name": "nwd", "role": "3d", "guid": GUID, "isMasterView": True}],
            }
        },
    )
    respx.get(f"{MD}/{URN}/metadata/{GUID}").respond(
        200, json={"data": {"type": "objects", "objects": NWD_TREE}}
    )
    collection = [
        {"objectid": oid, "name": f"n{oid}", "externalId": f"ext-{oid}", "properties": p}
        for oid, p in NWD_PROPS.items()
    ]
    respx.get(f"{MD}/{URN}/metadata/{GUID}/properties").respond(
        200, json={"data": {"type": "properties", "collection": collection}}
    )


async def test_processing_with_assembly_mode_and_click_on_member(
    session: AsyncSession,
    aps: ApsClient,
    sleeps: Sleeps,
    client: httpx.AsyncClient,
    users: dict[Role, User],
) -> None:
    obra = Obra(
        code="OB-9480",
        name="Montagens",
        mark_property_names=["Nome da montagem"],
        piece_category_names=BODIES,
    )
    session.add(obra)
    await session.flush()
    v = ModelVersion(obra_id=obra.id, acc_version_id="urn:v:nwd:1", version_number=1, urn=URN)
    session.add(v)
    await session.flush()
    config = ProcessingConfig(mark_names=["Marca"], category_names=CATS)  # obra substitui
    with respx.mock:
        mock_token()
        _mock_nwd()
        result = await process_version(session, aps, v.id, config, sleep=sleeps)
    assert result is not None and result.status == "ready"
    assert (result.elements, result.marks) == (6, 4)

    stored = await session.scalar(
        select(Element.member_dbids).where(Element.version_id == v.id, Element.dbid == 10)
    )
    assert stored is not None and 17 in stored

    h = as_user(users[Role.FABRICA])
    # clique no consolo (17) abre a peça PP312 (nó do vínculo 10)
    r = await client.get(f"/api/versions/{v.id}/elements/17", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["dbid"] == 10 and r.json()["mark"]["code"] == "PP312"
    # a lista de marcas leva os membros (o 3D mapeia o clique)
    marks = {
        m["code"]: m for m in (await client.get(f"/api/versions/{v.id}/marks", headers=h)).json()
    }
    assert marks["PP312"]["dbids"] == [10] and 19 in marks["PP312"]["member_dbids"]
    assert marks["LA3037"]["count"] == 2
