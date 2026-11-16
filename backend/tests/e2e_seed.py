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
Imprime {"obra_id", "version_id", "param_def_id", "rev_obra_id", "rev_version_id"}.
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
    Mark,
    ModelVersion,
    Obra,
    Orphan,
    ParamDef,
    ParamValue,
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
    # Versões extras (Rev.03… do teste de "nova versão", 8.2) saem: v2 volta a ser a ativa.
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
            return ids
    finally:
        await engine.dispose()


if __name__ == "__main__":
    print(json.dumps(asyncio.run(main())))
