"""Reconciliação com as DUAS revisões reais do projeto de teste da Fase 0 (só GET no APS).

    cd backend && uv run python -m tests.real_revisions --v1 <versão ORC> --v2 <versão R02> \\
        [--create-obra "30.327-01-REC"]

O ORC.rvt é um modelo de orçamento (Marca vazia) e a ORC-R02.rvt foi publicada como OUTRO
arquivo no Docs (não como v2). Para reproduzir o cenário de produção, a Marca da R02 é
copiada para as peças da v1 com o MESMO externalId (a R02 foi salva a partir do ORC):
"o que a fábrica teria tido na v1". Depois:

1. reconcilia as duas versões em memória (motor da 7.1) e imprime o resultado;
2. com --create-obra: cria (ou recria) no banco de DATABASE_URL uma obra com v1 = ORC e
   v2 = R02 (URNs reais, o Viewer abre os modelos de verdade), processa as duas pelo
   process_version com as respostas reais (a v1 com a Marca copiada), preenche um valor
   da fábrica em cada marca da v1 e mostra o diff, as revisões e as órfãs da chegada da v2.

Nunca escreve no APS nem no arquivo BIM.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
from typing import Any

import respx
from sqlalchemy import select

from app.aps import build_aps_client
from app.aps import derivatives as md
from app.config import get_settings
from app.db import create_engine, create_sessionmaker
from app.models import Mark, ModelVersion, Obra, Orphan, ParamDef, ParamValue
from app.services import review
from app.services.extraction import extract_elements, find_prop
from app.services.processing import ProcessingConfig, process_version
from app.services.reconcile import ElementInput, build_snapshots, reconcile

MARK_GROUP = "Dados de identidade"


async def _fetch(urn: str) -> dict[str, Any]:
    """Respostas REAIS (GET) de metadata, árvore e propriedades da vista 3D."""
    aps = build_aps_client(get_settings())
    try:
        meta = await aps.get_json(f"{aps.md_prefix}/{urn}/metadata")
        view = md.choose_3d_view(await md.get_metadata(aps, urn))
        tree = await aps.get_json(f"{aps.md_prefix}/{urn}/metadata/{view.guid}")
        props = await aps.get_json(f"{aps.md_prefix}/{urn}/metadata/{view.guid}/properties")
    finally:
        await aps.http.aclose()
    return {"guid": view.guid, "metadata": meta, "tree": tree, "properties": props}


def _copy_marks(v1: dict[str, Any], v2: dict[str, Any]) -> int:
    """Marca da R02 → peças da v1 com o mesmo externalId. Devolve quantas receberam."""
    marks = {}
    for p in v2["properties"]["data"]["collection"]:
        mark = find_prop(p.get("properties") or {}, ["Marca"])
        if mark and p.get("externalId"):
            marks[p["externalId"]] = mark
    n = 0
    for p in v1["properties"]["data"]["collection"]:
        ident = (p.get("properties") or {}).get(MARK_GROUP)
        if isinstance(ident, dict) and "Marca" in ident and p.get("externalId") in marks:
            ident["Marca"] = marks[p["externalId"]]
            n += 1
    return n


def _elements(data: dict[str, Any], config: ProcessingConfig) -> list[ElementInput]:
    from app.aps.schemas import PropertyObject, TreeNode

    tree = [TreeNode.model_validate(o) for o in data["tree"]["data"]["objects"]]
    props = [PropertyObject.model_validate(p) for p in data["properties"]["data"]["collection"]]
    return [
        ElementInput(e.mark_code, e.category, e.external_id, e.props)
        for e in extract_elements(tree, props, config.mark_names, config.category_names)
    ]


def _mock(router: respx.MockRouter, urn: str, data: dict[str, Any]) -> None:
    base = "https://developer.api.autodesk.com/modelderivative/v2/designdata"
    router.get(f"{base}/{urn}/metadata").respond(200, json=data["metadata"])
    router.get(f"{base}/{urn}/metadata/{data['guid']}").respond(200, json=data["tree"])
    router.get(f"{base}/{urn}/metadata/{data['guid']}/properties").respond(
        200, json=data["properties"]
    )


async def _create_obra(
    code: str,
    urns: tuple[str, str],
    data: tuple[dict[str, Any], dict[str, Any]],
    config: ProcessingConfig,
) -> None:
    settings = get_settings()
    engine = create_engine(settings.database_url)
    maker = create_sessionmaker(engine)
    try:
        async with maker() as session:
            obra = await session.scalar(select(Obra).where(Obra.code == code))
            if obra is not None:
                raise SystemExit(f"A obra {code} já existe; use outro código.")
            obra = Obra(code=code, name="ORC → R02 (revisões reais da Fase 0)", active=False)
            obra.acc_item_name = "30.327-01 - MODELO - ORC.rvt"
            session.add(obra)
            await session.flush()
            versions = []
            for n, urn in enumerate(urns, start=1):
                v = ModelVersion(
                    obra_id=obra.id,
                    acc_version_id=f"real-revisions:{code}:{n}",
                    version_number=n,
                    urn=urn,
                    published_by="Fase 0 (Docs)",
                )
                session.add(v)
                versions.append(v)
            await session.commit()
            aps = build_aps_client(settings)
            try:
                # v1 com as respostas (reais) já com a Marca copiada; token de verdade.
                with respx.mock(assert_all_called=False) as router:
                    router.route(
                        host="developer.api.autodesk.com", path__startswith="/authentication"
                    ).pass_through()
                    _mock(router, urns[0], data[0])
                    r1 = await process_version(session, aps, versions[0].id, config)
                print(f"v1: {r1}")
                if r1 is None or r1.status != "ready":
                    raise SystemExit("v1 não processou; veja o log acima.")
                forma = ParamDef(
                    name="Tipo de forma",
                    type="list",
                    options=["F-11", "F-12", "F-13"],
                    required=True,
                    scope="obra",
                    obra_id=obra.id,
                )
                session.add(forma)
                await session.flush()
                marks = list(await session.scalars(select(Mark).where(Mark.obra_id == obra.id)))
                for i, m in enumerate(sorted(marks, key=lambda m: m.code)):
                    session.add(
                        ParamValue(
                            mark_id=m.id, def_id=forma.id, value=["F-11", "F-12", "F-13"][i % 3]
                        )
                    )
                await session.commit()
                with respx.mock(assert_all_called=False) as router:
                    router.route(
                        host="developer.api.autodesk.com", path__startswith="/authentication"
                    ).pass_through()
                    _mock(router, urns[1], data[1])
                    r2 = await process_version(session, aps, versions[1].id, config)
                print(f"v2: {r2}")
            finally:
                await aps.http.aclose()
            view = await review.get_diff(session, versions[1].id)
            print("diff:", json.dumps(view.diff, ensure_ascii=False, indent=1))
            rows = await session.execute(
                select(Mark.code, Mark.review_status, Mark.review_note).where(
                    Mark.obra_id == obra.id
                )
            )
            print("marcas:", [tuple(r) for r in rows])
            orphans = await session.execute(
                select(Mark.code, Orphan.status)
                .join(Mark, Mark.id == Orphan.mark_id)
                .where(Mark.obra_id == obra.id)
            )
            print("órfãs:", [tuple(r) for r in orphans])
            print(f"obra {obra.id}: abra /obras/{obra.id}/modelo (v2 = R02)")
    finally:
        await engine.dispose()


async def main(v1_urn: str, v2_urn: str, create: str | None) -> None:
    settings = get_settings()
    config = ProcessingConfig.from_settings(settings)
    v1, v2 = await _fetch(v1_urn), await _fetch(v2_urn)
    v1_original = copy.deepcopy(v1)
    copied = _copy_marks(v1, v2)
    print(f"Marca copiada da R02 para {copied} peça(s) da v1 (mesmo externalId)")
    result = reconcile(
        build_snapshots(_elements(v1, config), config.reconcile),
        build_snapshots(_elements(v2, config), config.reconcile),
        config.reconcile,
    )
    print("totais:", {k.value: n for k, n in result.totals.items()})
    for m in result.marks:
        counts = f"{m.prev_count}→{m.curr_count}"
        print(f"  {m.code:8} {m.category:22} {m.change.value:14} {counts}  {m.summary()}")
    original_marks = sum(1 for e in _elements(v1_original, config) if e.mark_code)
    print(f"(sem a cópia, a v1 teria {original_marks} peça(s) com Marca)")
    if create:
        await _create_obra(create, (v1_urn, v2_urn), (v1, v2), config)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--v1", required=True, help="URN (base64) da versão do ORC.rvt")
    ap.add_argument("--v2", required=True, help="URN (base64) da versão da ORC-R02.rvt")
    ap.add_argument("--create-obra", default=None)
    a = ap.parse_args()
    asyncio.run(main(a.v1, a.v2, a.create_obra))
