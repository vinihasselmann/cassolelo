"""Sincronização das versões do arquivo no Docs com model_versions."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.aps import data_management as dm
from app.aps.client import ApsClient
from app.aps.derivatives import urn_from_version
from app.models import ModelVersion, Obra, User
from app.models.enums import VersionStatus
from app.observability import metrics
from app.services import audit
from app.services.errors import ConflictError
from app.services.obras import get_obra
from app.services.translation import (
    PROCESS_VERSION_JOB,
    Outcome,
    check_translation,
    enqueue_processing,
)
from app.workers.queue import JobQueue

log = logging.getLogger("app.services.versions")

__all__ = ["PROCESS_VERSION_JOB", "SyncResult", "list_versions", "sync_all_obras", "sync_versions"]


@dataclass
class SyncResult:
    obra_id: int
    total_in_docs: int
    created_ids: list[int] = field(default_factory=list)
    ready: int = 0
    translating: int = 0
    no_translation: int = 0
    failed: int = 0
    enqueued: int = 0
    enqueue_failed: int = 0


async def sync_versions(
    session: AsyncSession,
    aps: ApsClient,
    queue: JobQueue,
    obra_id: int,
    actor: User | None = None,
) -> SyncResult:
    """Insere as versões do Docs que faltam, consulta o manifest de cada uma e
    enfileira process_version para as que o Docs já converteu.

    Idempotente: versões já existentes (por acc_version_id) são ignoradas, inclusive
    sob sincronizações concorrentes (INSERT ... ON CONFLICT DO NOTHING).

    Faz COMMIT antes de enfileirar, para o worker sempre encontrar a linha. Se a fila
    falhar, as versões continuam salvas (pending) e a falha é informada no resultado.
    """
    obra = await get_obra(session, obra_id)
    if not obra.acc_project_id or not obra.acc_item_id:
        raise ConflictError("A obra não está vinculada a um arquivo do Docs.")

    versions = await dm.list_versions(aps, obra.acc_project_id, obra.acc_item_id)
    existing = set(
        await session.scalars(
            select(ModelVersion.acc_version_id).where(ModelVersion.obra_id == obra_id)
        )
    )
    result = SyncResult(obra_id=obra_id, total_in_docs=len(versions))
    batch_id = uuid.uuid4()
    actor_id = actor.id if actor else None

    for v in sorted(versions, key=lambda x: x.number):
        if v.id in existing:
            continue
        values = {
            "obra_id": obra_id,
            "acc_version_id": v.id,
            "version_number": v.number,
            "urn": urn_from_version(v),
            "status": VersionStatus.PENDING.value,
            "published_by": v.create_user_name,
            "published_at": v.create_time,
            "comment": v.comment,
            "created_by": actor_id,
            "updated_by": actor_id,
        }
        stmt = (
            pg_insert(ModelVersion)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["acc_version_id"])
            .returning(ModelVersion.id)
        )
        new_id = await session.scalar(stmt)
        if new_id is None:  # outra sincronização inseriu antes
            continue
        await audit.record(
            session,
            "model_version",
            new_id,
            "create",
            None,
            {"id": new_id, **values},
            actor,
            batch_id,
        )
        result.created_ids.append(new_id)

    ready_ids: list[int] = []
    for version_id in result.created_ids:
        version = await session.get(ModelVersion, version_id)
        if version is None:  # pragma: no cover
            continue
        outcome = await check_translation(session, aps, version)
        if outcome is Outcome.READY:
            result.ready += 1
            ready_ids.append(version_id)
        elif outcome in (Outcome.IN_PROGRESS, Outcome.CHECK_ERROR):
            result.translating += 1
        elif outcome is Outcome.NO_TRANSLATION:
            result.no_translation += 1
        else:
            result.failed += 1

    await session.commit()

    for version_id in ready_ids:
        if await enqueue_processing(queue, version_id):
            result.enqueued += 1
        else:
            result.enqueue_failed += 1
    return result


async def sync_all_obras(session: AsyncSession, aps: ApsClient, queue: JobQueue) -> list[int]:
    """Verificação periódica (reserva para webhooks perdidos): sincroniza todas as
    obras ativas vinculadas. Uma obra com erro não impede as demais."""
    ids = list(
        await session.scalars(
            select(Obra.id)
            .where(Obra.active.is_(True), Obra.acc_item_id.is_not(None))
            .order_by(Obra.id)
        )
    )
    synced: list[int] = []
    found = 0
    for obra_id in ids:
        try:
            result = await sync_versions(session, aps, queue, obra_id)
            found += len(result.created_ids)
            synced.append(obra_id)
        except Exception:
            log.exception("Verificação periódica: falha ao sincronizar a obra %s", obra_id)
            await session.rollback()
    if found:
        # Versões que só a verificação periódica achou: o webhook não avisou (alerta 10.1).
        await metrics.incr("periodic_new_versions_total", found)
        await metrics.mark("periodic_found_versions")
    return synced


async def list_versions(session: AsyncSession, obra_id: int) -> list[ModelVersion]:
    await get_obra(session, obra_id)
    rows = await session.scalars(
        select(ModelVersion)
        .where(ModelVersion.obra_id == obra_id)
        .order_by(ModelVersion.version_number.desc())
    )
    return list(rows)
