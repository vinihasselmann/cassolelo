"""E2E (Fase 8): uma versão nova chega à obra E2E-REV enquanto as telas estão abertas.

    cd backend && uv run python -m tests.e2e_new_version

Cria a próxima versão da E2E-REV (V3, V4…) com o conteúdo de revisao_v2 e a
processa com o MESMO process_version do worker, publicando os eventos no Redis real
(como o worker faz): as telas abertas recebem version_ready. O seed (tests.e2e_seed)
apaga essas versões extras. APS simulado com respx. Imprime {"version_id", "version_number"}.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import respx
from pydantic import SecretStr
from sqlalchemy import func, select

from app.aps.auth import TokenProvider
from app.aps.client import ApsClient
from app.config import get_settings
from app.db import create_engine, create_sessionmaker
from app.models import ModelVersion, Obra
from app.services import events
from app.services.processing import ProcessingConfig, process_version
from tests.apsfakes import BASE, mock_model, mock_token
from tests.e2e_seed import REV_CODE


async def main() -> dict[str, int]:
    settings = get_settings()
    engine = create_engine(settings.database_url)
    bus = events.RedisEventBus(settings.redis_url)
    events.configure(bus)
    try:
        async with create_sessionmaker(engine)() as session:
            obra = await session.scalar(select(Obra).where(Obra.code == REV_CODE))
            if obra is None:
                raise SystemExit("Obra E2E-REV não existe: rode tests.e2e_seed antes.")
            last = await session.scalar(
                select(func.max(ModelVersion.version_number)).where(ModelVersion.obra_id == obra.id)
            )
            n = (last or 0) + 1
            urn = f"ZTJlLXJldmlzYW8tbm92YS0{n}"
            version = ModelVersion(
                obra_id=obra.id,
                acc_version_id=f"e2e:revisao:extra:{n}",
                version_number=n,
                urn=urn,
                published_by="E2E",
            )
            session.add(version)
            await session.commit()
            config = ProcessingConfig.from_settings(settings)
            async with httpx.AsyncClient(base_url=BASE) as http, respx.mock:
                mock_token()
                mock_model("revisao_v2", urn)
                tokens = TokenProvider(client_id="e2e", client_secret=SecretStr("e2e"), http=http)
                result = await process_version(
                    session, ApsClient(http=http, tokens=tokens), version.id, config
                )
            if result is None or result.status != "ready":
                raise SystemExit(f"Falha ao processar a versão nova: {result}")
            await events.drain()  # version_ready publicado no Redis
            return {"version_id": version.id, "version_number": n}
    finally:
        await bus.close()
        await engine.dispose()


if __name__ == "__main__":
    print(json.dumps(asyncio.run(main())))
