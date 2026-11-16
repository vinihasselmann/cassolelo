"""Montagem direta de uma versão PRONTA com peças e marcas (sem passar pelo APS)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Element, Mark, ModelVersion, Obra
from app.models.enums import VersionStatus


async def ready_version(
    session: AsyncSession,
    obra: Obra,
    marks: list[tuple[str, str, int]],
    *,
    number: int = 1,
    unmarked: int = 0,
) -> tuple[ModelVersion, dict[str, Mark]]:
    """`marks` = [(código, categoria, nº de peças)]. Devolve a versão e as marcas por código."""
    version = ModelVersion(
        obra_id=obra.id,
        acc_version_id=f"urn:v:{obra.code}:{number}",
        version_number=number,
        urn=f"dXJu{obra.code}{number}",
        status=VersionStatus.READY.value,
    )
    session.add(version)
    by_code = {code: Mark(obra_id=obra.id, code=code, category=cat) for code, cat, _ in marks}
    session.add_all(by_code.values())
    await session.flush()
    dbid = 1000
    for code, cat, pieces in marks:
        for _ in range(pieces):
            dbid += 1
            session.add(
                Element(version_id=version.id, dbid=dbid, category=cat, mark_id=by_code[code].id)
            )
    for _ in range(unmarked):
        dbid += 1
        session.add(Element(version_id=version.id, dbid=dbid, category="Pilar"))
    await session.flush()
    return version, by_code
