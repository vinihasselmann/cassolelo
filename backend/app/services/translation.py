"""Situação da conversão do Docs para cada versão (só LÊ o manifest; nunca converte).

manifest success + SVF/SVF2 -> pending  (convertida; segue para process_version)
manifest pending/inprogress -> translating (reconsulta a cada 2 min, até 2 h)
sem derivativo / 404 / sem SVF -> no_translation
manifest failed/timeout      -> failed
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.aps import derivatives as md
from app.aps.client import ApsClient
from app.aps.errors import ApsError, ApsNoTranslationError
from app.models import ModelVersion
from app.models.enums import VersionStatus
from app.services import audit, events
from app.workers.queue import JobQueue

log = logging.getLogger("app.services.translation")

PROCESS_VERSION_JOB = "process_version"
TRANSLATION_TIMEOUT = timedelta(hours=2)
NO_TRANSLATION_MSG = (
    "Este arquivo não foi convertido pelo Docs. Abra-o no Autodesk Docs e inicie o "
    "processamento, ou publique pelo site do Docs ou pela publicação em nuvem do Revit."
)


class Outcome(StrEnum):
    READY = "ready"  # convertido: enfileirar process_version
    IN_PROGRESS = "in_progress"
    NO_TRANSLATION = "no_translation"
    FAILED = "failed"
    CHECK_ERROR = "check_error"  # falha ao consultar: tentar de novo depois


async def check_translation(
    session: AsyncSession, aps: ApsClient, version: ModelVersion
) -> Outcome:
    """Consulta o manifest e atualiza o status da versão (com auditoria). Não faz commit."""
    before = audit.snapshot(version)
    error: str | None = None
    if version.urn is None:
        outcome, status = Outcome.NO_TRANSLATION, VersionStatus.NO_TRANSLATION
    else:
        try:
            manifest = await md.get_manifest(aps, version.urn)
        except ApsNoTranslationError:
            outcome, status = Outcome.NO_TRANSLATION, VersionStatus.NO_TRANSLATION
        except ApsError as exc:
            log.warning("Manifest da versão %s indisponível: %s", version.id, exc)
            outcome, status = Outcome.CHECK_ERROR, VersionStatus.TRANSLATING
            error = "Falha ao consultar o Docs; nova verificação automática em breve."
        else:
            if manifest.in_progress:
                outcome, status = Outcome.IN_PROGRESS, VersionStatus.TRANSLATING
            elif manifest.status == "success":
                if manifest.has_viewable:
                    outcome, status = Outcome.READY, VersionStatus.PENDING
                else:
                    outcome, status = Outcome.NO_TRANSLATION, VersionStatus.NO_TRANSLATION
            else:
                outcome, status = Outcome.FAILED, VersionStatus.FAILED
                detail = " | ".join(m for m in manifest.messages if m)[:500]
                error = f"Conversão do Docs com status '{manifest.status}'. {detail}".strip()

    previous = version.status
    version.status = status.value
    version.error = error
    if status in (VersionStatus.FAILED, VersionStatus.NO_TRANSLATION) and previous != status.value:
        events.emit(
            session,
            version.obra_id,
            "version_failed",
            {
                "version_id": version.id,
                "version_number": version.version_number,
                "status": status.value,
                "error": error,
            },
        )
    if session.is_modified(version):
        await session.flush()
        await audit.record(
            session,
            "model_version",
            version.id,
            "translation_check",
            before,
            audit.snapshot(version),
            None,
        )
    return outcome


async def enqueue_processing(queue: JobQueue, version_id: int) -> bool:
    try:
        await queue.enqueue(
            PROCESS_VERSION_JOB, version_id, job_id=f"{PROCESS_VERSION_JOB}:{version_id}"
        )
        return True
    except Exception:
        log.exception("Falha ao enfileirar %s(%s)", PROCESS_VERSION_JOB, version_id)
        return False


async def recheck_translating(
    session: AsyncSession, aps: ApsClient, queue: JobQueue, now: datetime | None = None
) -> dict[str, int]:
    """Cron (a cada 2 min): reconsulta versões em `translating`.

    Passadas 2 horas desde que o app viu a versão, marca como `failed`.
    """
    now = now or datetime.now(UTC)
    rows = list(
        await session.scalars(
            select(ModelVersion).where(ModelVersion.status == VersionStatus.TRANSLATING.value)
        )
    )
    counts = {o.value: 0 for o in Outcome} | {"timeout": 0}
    ready: list[int] = []
    for version in rows:
        outcome = await check_translation(session, aps, version)
        if outcome is Outcome.READY:
            ready.append(version.id)
        elif outcome in (Outcome.IN_PROGRESS, Outcome.CHECK_ERROR) and (
            now - version.created_at > TRANSLATION_TIMEOUT
        ):
            before = audit.snapshot(version)
            version.status = VersionStatus.FAILED.value
            version.error = "A conversão do Docs não terminou em 2 horas."
            await session.flush()
            await audit.record(
                session,
                "model_version",
                version.id,
                "translation_timeout",
                before,
                audit.snapshot(version),
                None,
            )
            counts["timeout"] += 1
            continue
        counts[outcome.value] += 1
    await session.commit()
    for version_id in ready:
        await enqueue_processing(queue, version_id)
    return counts
