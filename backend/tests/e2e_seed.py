"""Obra de teste do E2E (Playwright), no banco de DATABASE_URL (dev):

    cd backend && uv run python -m tests.e2e_seed

Garante os usuários simulados e cria (ou reaproveita) a obra E2E-01 com uma versão
processada pelo MESMO process_version do worker, a partir de `fixtures/aps/models/validacao`
(APS simulado com respx: não precisa de credenciais). Cria o parâmetro "Tipo de forma"
(lista F-11/F-12/F-13, escopo da obra) e zera os valores da obra.
F3 (filtros): parâmetro "Data de expedição" (data, opcional) com PP001 = hoje e V-01 =
um ano atrás (só o PP001 é "do mês atual"); apaga os filtros salvos e os esquemas de
cores da obra E2E-01.
Fase 7: cria também a obra E2E-REV com DUAS versões (fixtures revisao_v1 → revisao_v2,
REVIEW_PROPERTY_NAMES=Seção). A cada execução zera órfãs, revisões e valores, preenche
"Tipo de forma" na v1 (PP001 F-11, PP003 F-12, PP004 F-12, PP005 F-13) e reprocessa a v2:
a chegada da v2 deixa PP001 em revisão (40x60 → 40x80) e PP004/PP005 órfãs.
P4 (parâmetros por peça): cria a obra E2E-PEC (fixture `pecas`: P-06 com 6 pilares, V-02
com 2 vigas) com o parâmetro POR PEÇA "Data de fabricação" (data) e zera os valores por peça.
P5 (unidades órfãs): obra E2E-PECREV com DUAS versões (fixtures `pecas` → `pecas_v2`, a
v2 sem a peça pec-0012). A cada execução apaga as unidades da obra, processa a v1,
preenche a "Data de fabricação" (hoje) só na unidade da peça pec-0012 e processa a v2:
essa unidade fica ÓRFÃ com o valor.
Plannix (2026-11-24): obra E2E-PLX (fixture `pecas`) zerada a cada execução: apaga as
unidades da obra (com os valores e os Códigos do Plannix), retira dela os parâmetros do
Plannix (sem apagá-los: são da biblioteca) e reprocessa a versão; a importação de
`tests/e2e_plannix_xlsx.py` os cria ou inclui de novo.
Imprime {"obra_id", "version_id", "param_def_id", "rev_obra_id", "rev_version_id",
"pec_obra_id", "pec_version_id", "pec_param_def_id", "pecrev_obra_id",
"pecrev_version_id", "plx_obra_id", "plx_version_id"}.
Idempotente: rodar de novo reprocessa as mesmas versões.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import date, timedelta

import httpx
import respx
from pydantic import SecretStr
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.aps.auth import TokenProvider
from app.aps.client import ApsClient
from app.config import get_settings
from app.db import create_engine, create_sessionmaker
from app.models import (
    ColorScheme,
    Element,
    Mark,
    ModelVersion,
    Obra,
    ObraParam,
    Orphan,
    ParamDef,
    ParamValue,
    PieceUnit,
    PieceUnitLink,
    PieceValue,
    SavedFilter,
    VersionDiff,
)
from app.seed import seed_users
from app.services import piece_props
from app.services.processing import ProcessingConfig, process_version
from tests.apsfakes import BASE, mock_model, mock_token

OBRA_CODE = "E2E-01"
URN = "ZTJlLXZhbGlkYWNhbw"  # fictício; o Viewer falso do E2E não usa
REV_CODE = "E2E-REV"
REV_URNS = {1: "ZTJlLXJldmlzYW8x", 2: "ZTJlLXJldmlzYW8y"}
PEC_CODE = "E2E-PEC"
PEC_URN = "ZTJlLXBlY2Fz"
PECREV_CODE = "E2E-PECREV"
PECREV_URNS = {1: "ZTJlLXBlY3JldjE", 2: "ZTJlLXBlY3JldjI"}
PECREV_FIXTURES = {1: "pecas", 2: "pecas_v2"}
PLX_CODE = "E2E-PLX"  # igual à Sigla da planilha de tests/e2e_plannix_xlsx.py
PLX_URN = "ZTJlLXBsYW5uaXg"
REV_VALUES = {"PP001": "F-11", "PP003": "F-12", "PP004": "F-12", "PP005": "F-13"}


async def _process(
    session: AsyncSession, version_id: int, fmt: str, urn: str, config: ProcessingConfig
) -> None:
    async with httpx.AsyncClient(base_url=BASE) as http, respx.mock:
        mock_token()
        mock_model(fmt, urn)
        tokens = TokenProvider(client_id="e2e", client_secret=SecretStr("e2e"), http=http)
        result = await process_version(
            session, ApsClient(http=http, tokens=tokens), version_id, config
        )
    if result is None or result.status != "ready":
        raise SystemExit(f"Falha ao processar a versão de teste {fmt}: {result}")


async def _forma(session: AsyncSession, obra: Obra) -> ParamDef:
    forma = await session.scalar(
        select(ParamDef).where(
            ParamDef.obra_id == obra.id, ParamDef.name == "Tipo de forma", ParamDef.active
        )
    )
    if forma is None:
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
    return forma


async def _expedicao(session: AsyncSession, obra: Obra) -> None:
    """Data de expedição (F3): PP001 hoje, V-01 há um ano; o resto sem valor."""
    exp = await session.scalar(
        select(ParamDef).where(
            ParamDef.obra_id == obra.id, ParamDef.name == "Data de expedição", ParamDef.active
        )
    )
    if exp is None:
        exp = ParamDef(name="Data de expedição", type="date", scope="obra", obra_id=obra.id)
        session.add(exp)
        await session.flush()
    codes = {"PP001": date.today(), "V-01": date.today() - timedelta(days=365)}
    for mark in await session.scalars(
        select(Mark).where(Mark.obra_id == obra.id, Mark.code.in_(list(codes)))
    ):
        session.add(ParamValue(mark_id=mark.id, def_id=exp.id, value=codes[mark.code].isoformat()))
    await session.flush()
    await piece_props.sync_factory(session, obra.id)


async def _revisions(session: AsyncSession, config: ProcessingConfig) -> dict[str, int]:
    """Obra E2E-REV: v1 com valores, v2 chegando (revisão + órfãs), estado zerado."""
    obra = await session.scalar(select(Obra).where(Obra.code == REV_CODE))
    if obra is None:
        obra = Obra(code=REV_CODE, name="Obra de teste E2E · revisões", active=False)
        obra.acc_item_name = "modelo-revisao.rvt"
        session.add(obra)
        await session.flush()
    versions: dict[int, ModelVersion] = {}
    for n, urn in REV_URNS.items():
        v = await session.scalar(
            select(ModelVersion).where(ModelVersion.acc_version_id == f"e2e:revisao:{n}")
        )
        if v is None:
            v = ModelVersion(
                obra_id=obra.id,
                acc_version_id=f"e2e:revisao:{n}",
                version_number=n,
                urn=urn,
                published_by="E2E",
            )
            session.add(v)
        v.status = "pending"
        versions[n] = v
    await session.flush()
    marks = select(Mark.id).where(Mark.obra_id == obra.id)
    await session.execute(delete(Orphan).where(Orphan.mark_id.in_(marks)))
    # Versões extras (V3… do teste de "nova versão", 8.2) saem: v2 volta a ser a ativa.
    await session.execute(
        delete(ModelVersion).where(
            ModelVersion.obra_id == obra.id, ModelVersion.version_number > max(REV_URNS)
        )
    )
    await session.execute(delete(ParamValue).where(ParamValue.mark_id.in_(marks)))
    await session.execute(
        update(Mark).where(Mark.obra_id == obra.id).values(review_status="ok", review_note=None)
    )
    await session.execute(
        delete(VersionDiff).where(VersionDiff.version_id.in_([v.id for v in versions.values()]))
    )
    await session.commit()

    await _process(session, versions[1].id, "revisao_v1", REV_URNS[1], config)
    versions[2].status = "pending"  # só fica pronta depois: a v1 não compara com ela
    await session.commit()
    forma = await _forma(session, obra)
    by_code = {
        m.code: m for m in await session.scalars(select(Mark).where(Mark.obra_id == obra.id))
    }
    for code, value in REV_VALUES.items():
        session.add(ParamValue(mark_id=by_code[code].id, def_id=forma.id, value=value))
    await session.commit()
    await _process(session, versions[2].id, "revisao_v2", REV_URNS[2], config)
    return {"rev_obra_id": obra.id, "rev_version_id": versions[2].id}


async def _pieces(session: AsyncSession, config: ProcessingConfig) -> dict[str, int]:
    """Obra E2E-PEC (P4): marca de 6 peças e um parâmetro por peça, sem valores."""
    obra = await session.scalar(select(Obra).where(Obra.code == PEC_CODE))
    if obra is None:
        obra = Obra(code=PEC_CODE, name="Obra de teste E2E · por peça", active=False)
        obra.acc_item_name = "modelo-pecas.rvt"
        session.add(obra)
        await session.flush()
    version = await session.scalar(
        select(ModelVersion).where(ModelVersion.acc_version_id == "e2e:pecas:1")
    )
    if version is None:
        version = ModelVersion(
            obra_id=obra.id,
            acc_version_id="e2e:pecas:1",
            version_number=1,
            urn=PEC_URN,
            published_by="E2E",
        )
        session.add(version)
    version.status = "pending"
    await session.commit()
    await _process(session, version.id, "pecas", PEC_URN, config)
    fab = await session.scalar(
        select(ParamDef).where(
            ParamDef.obra_id == obra.id, ParamDef.name == "Data de fabricação", ParamDef.active
        )
    )
    if fab is None:
        fab = ParamDef(
            name="Data de fabricação", type="date", scope="obra", obra_id=obra.id, level="piece"
        )
        session.add(fab)
        await session.flush()
    units = select(PieceUnit.id).join(Mark, Mark.id == PieceUnit.mark_id)
    await session.execute(
        delete(PieceValue).where(PieceValue.unit_id.in_(units.where(Mark.obra_id == obra.id)))
    )
    await session.execute(delete(SavedFilter).where(SavedFilter.obra_id == obra.id))
    await session.flush()
    await piece_props.sync_factory(session, obra.id)
    await session.commit()
    return {"pec_obra_id": obra.id, "pec_version_id": version.id, "pec_param_def_id": fab.id}


async def _piece_revisions(session: AsyncSession, config: ProcessingConfig) -> dict[str, int]:
    """Obra E2E-PECREV (P5): v2 com uma peça a menos deixa uma unidade órfã com valor."""
    obra = await session.scalar(select(Obra).where(Obra.code == PECREV_CODE))
    if obra is None:
        obra = Obra(code=PECREV_CODE, name="Obra de teste E2E · peças órfãs", active=False)
        obra.acc_item_name = "modelo-pecas-rev.rvt"
        session.add(obra)
        await session.flush()
    versions: dict[int, ModelVersion] = {}
    for n, urn in PECREV_URNS.items():
        v = await session.scalar(
            select(ModelVersion).where(ModelVersion.acc_version_id == f"e2e:pecrev:{n}")
        )
        if v is None:
            v = ModelVersion(
                obra_id=obra.id,
                acc_version_id=f"e2e:pecrev:{n}",
                version_number=n,
                urn=urn,
                published_by="E2E",
            )
            session.add(v)
        v.status = "pending"
        versions[n] = v
    await session.flush()
    # Estado zerado: sem unidades (e sem valores por peça) nesta obra.
    units = select(PieceUnit.id).where(PieceUnit.obra_id == obra.id)
    await session.execute(delete(PieceValue).where(PieceValue.unit_id.in_(units)))
    await session.execute(delete(PieceUnitLink).where(PieceUnitLink.unit_id.in_(units)))
    await session.execute(delete(PieceUnit).where(PieceUnit.obra_id == obra.id))
    await session.commit()

    await _process(session, versions[1].id, PECREV_FIXTURES[1], PECREV_URNS[1], config)
    versions[2].status = "pending"
    fab = await session.scalar(
        select(ParamDef).where(
            ParamDef.obra_id == obra.id, ParamDef.name == "Data de fabricação", ParamDef.active
        )
    )
    if fab is None:
        fab = ParamDef(
            name="Data de fabricação", type="date", scope="obra", obra_id=obra.id, level="piece"
        )
        session.add(fab)
        await session.flush()
    gone = await session.scalar(
        select(PieceUnit).where(PieceUnit.obra_id == obra.id, PieceUnit.external_id == "pec-0012")
    )
    if gone is None:
        raise SystemExit("E2E-PECREV: unidade da peça pec-0012 não encontrada")
    session.add(PieceValue(unit_id=gone.id, def_id=fab.id, value=date.today().isoformat()))
    await session.commit()
    await _process(session, versions[2].id, PECREV_FIXTURES[2], PECREV_URNS[2], config)
    return {"pecrev_obra_id": obra.id, "pecrev_version_id": versions[2].id}


async def _plannix(session: AsyncSession, config: ProcessingConfig) -> dict[str, int]:
    """Obra E2E-PLX: modelo `pecas` sem unidades, valores nem parâmetros do Plannix."""
    obra = await session.scalar(select(Obra).where(Obra.code == PLX_CODE))
    if obra is None:
        obra = Obra(code=PLX_CODE, name="Obra de teste E2E · Plannix", active=False)
        obra.acc_item_name = "modelo-plannix.rvt"
        session.add(obra)
        await session.flush()
    version = await session.scalar(
        select(ModelVersion).where(ModelVersion.acc_version_id == "e2e:plannix:1")
    )
    if version is None:
        version = ModelVersion(
            obra_id=obra.id,
            acc_version_id="e2e:plannix:1",
            version_number=1,
            urn=PLX_URN,
            published_by="E2E",
        )
        session.add(version)
    version.status = "pending"
    # Só esta obra é zerada: os parâmetros do Plannix são da biblioteca e podem ter
    # valores em obras reais (o seed também roda no banco de dev); aqui só saem da obra.
    plannix = select(ParamDef.id).where(ParamDef.source == "plannix")
    await session.execute(
        delete(ObraParam).where(ObraParam.obra_id == obra.id, ObraParam.def_id.in_(plannix))
    )
    units = select(PieceUnit.id).where(PieceUnit.obra_id == obra.id)
    await session.execute(delete(PieceValue).where(PieceValue.unit_id.in_(units)))
    await session.execute(delete(PieceUnitLink).where(PieceUnitLink.unit_id.in_(units)))
    await session.execute(delete(PieceUnit).where(PieceUnit.obra_id == obra.id))
    await session.execute(delete(SavedFilter).where(SavedFilter.obra_id == obra.id))
    await session.execute(delete(ColorScheme).where(ColorScheme.obra_id == obra.id))
    obra.unit_numbering = "provisional"
    await session.commit()
    await _process(session, version.id, "pecas", PLX_URN, config)
    # sem centros: a 1ª abertura do 3D renumera as peças pela montagem (o teste espera por ela)
    await session.execute(
        update(Element).where(Element.version_id == version.id).values(centroid=None)
    )
    await session.commit()
    return {"plx_obra_id": obra.id, "plx_version_id": version.id}


async def main() -> dict[str, int]:
    settings = get_settings()
    engine = create_engine(settings.database_url)
    maker = create_sessionmaker(engine)
    try:
        async with maker() as session:
            await seed_users(session)  # usuários simulados (idempotente)
            obra = await session.scalar(select(Obra).where(Obra.code == OBRA_CODE))
            if obra is None:
                obra = Obra(code=OBRA_CODE, name="Obra de teste E2E", active=False)
                obra.acc_item_name = "modelo-validacao.rvt"
                session.add(obra)
                await session.flush()
            version = await session.scalar(
                select(ModelVersion).where(ModelVersion.acc_version_id == "e2e:validacao:1")
            )
            if version is None:
                version = ModelVersion(
                    obra_id=obra.id,
                    acc_version_id="e2e:validacao:1",
                    version_number=1,
                    urn=URN,
                    published_by="E2E",
                )
                session.add(version)
            version.status = "pending"
            await session.commit()
            ids = {"obra_id": obra.id, "version_id": version.id}

            config = ProcessingConfig.from_settings(settings)
            await _process(session, version.id, "validacao", URN, config)
            # Parâmetro de teste (6.2) e valores zerados a cada execução (só a obra E2E).
            forma = await _forma(session, obra)
            marks = select(Mark.id).where(Mark.obra_id == obra.id)
            await session.execute(delete(ParamValue).where(ParamValue.mark_id.in_(marks)))
            await session.execute(delete(ColorScheme).where(ColorScheme.obra_id == obra.id))
            await session.execute(delete(SavedFilter).where(SavedFilter.obra_id == obra.id))
            await _expedicao(session, obra)
            await session.commit()
            ids["param_def_id"] = forma.id
            ids |= await _revisions(session, replace(config, review_names=["Seção"]))
            ids |= await _pieces(session, config)
            ids |= await _piece_revisions(session, config)
            ids |= await _plannix(session, config)
            return ids
    finally:
        await engine.dispose()


if __name__ == "__main__":
    print(json.dumps(asyncio.run(main())))
