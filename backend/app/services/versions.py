"""Sincronização das versões do arquivo no Docs com model_versions."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.aps import data_management as dm
from app.aps.client import ApsClient
from app.aps.derivatives import urn_from_version
from app.aps.errors import ApsNotFoundError
from app.aps.schemas import Version
from app.models import ModelVersion, Obra, User
from app.models.enums import AccFileState, VersionStatus
from app.observability import metrics
from app.services import audit, events
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
    deleted: int = 0  # versões "Deleted" novas (o arquivo foi excluído no Docs)
    file_state: str = AccFileState.OK.value


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

    try:
        versions = await dm.list_versions(aps, obra.acc_project_id, obra.acc_item_id)
    except ApsNotFoundError:
        # O Docs não acha mais o item: a obra fica bloqueada e sai da verificação
        # periódica (o "Sincronizar agora" continua tentando e a libera se o item voltar).
        await _set_file_state(session, obra, AccFileState.MISSING, actor)
        await session.commit()
        raise
    existing = {
        row.acc_version_id: row
        for row in await session.scalars(
            select(ModelVersion).where(ModelVersion.obra_id == obra_id)
        )
    }
    result = SyncResult(obra_id=obra_id, total_in_docs=len(versions))
    batch_id = uuid.uuid4()
    actor_id = actor.id if actor else None

    for v in sorted(versions, key=lambda x: x.number):
        if v.id in existing:
            await _fix_deleted_version(session, existing[v.id], v, batch_id)
            continue
        values = {
            "obra_id": obra_id,
            "acc_version_id": v.id,
            "version_number": v.number,
            "urn": None if v.is_deleted else urn_from_version(v),
            "status": (VersionStatus.DELETED if v.is_deleted else VersionStatus.PENDING).value,
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
        if v.is_deleted:
            result.deleted += 1
        else:
            result.created_ids.append(new_id)

    # A versão mais recente diz a situação do arquivo: "Deleted" = excluído (na lixeira);
    # restaurar no Docs cria outra versão normal por cima e libera a obra de novo.
    latest = max(versions, key=lambda x: x.number, default=None)
    state = AccFileState.DELETED if latest is not None and latest.is_deleted else AccFileState.OK
    await _set_file_state(session, obra, state, actor)
    result.file_state = state.value

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


async def _fix_deleted_version(
    session: AsyncSession, row: ModelVersion, v: Version, batch_id: uuid.UUID
) -> None:
    """Versão "Deleted" gravada antes deste tratamento (como no_translation): corrige."""
    if not v.is_deleted or row.status == VersionStatus.DELETED.value:
        return
    before = audit.snapshot(row)
    row.status = VersionStatus.DELETED.value
    row.error = None
    row.urn = None
    await session.flush()
    await audit.record(
        session, "model_version", row.id, "update", before, audit.snapshot(row), None, batch_id
    )


async def _set_file_state(
    session: AsyncSession, obra: Obra, state: AccFileState, actor: User | None
) -> None:
    """Grava a situação do arquivo no Docs (com auditoria e aviso às telas abertas)."""
    if obra.acc_file_state == state.value:
        return
    before = audit.snapshot(obra)
    obra.acc_file_state = state.value
    obra.acc_file_state_at = datetime.now(UTC)
    await session.flush()
    await audit.record(session, "obra", obra.id, "file_state", before, audit.snapshot(obra), actor)
    events.emit(session, obra.id, "obra_file_state", {"state": state.value}, actor)
    log.info("Obra %s: arquivo no Docs agora '%s'", obra.id, state.value)


async def sync_all_obras(session: AsyncSession, aps: ApsClient, queue: JobQueue) -> list[int]:
    """Verificação periódica (reserva para webhooks perdidos): sincroniza todas as
    obras ativas vinculadas. Uma obra com erro não impede as demais."""
    ids = list(
        await session.scalars(
            select(Obra.id)
            .where(
                Obra.active.is_(True),
                Obra.acc_item_id.is_not(None),
                # item que o Docs não acha mais: não insistir a cada 10 min (o log
                # repetia o mesmo erro). Obra "deleted" segue sendo verificada para
                # perceber uma restauração.
                Obra.acc_file_state != AccFileState.MISSING.value,
            )
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
        except ApsNotFoundError:
            log.warning("Verificação periódica: o Docs não acha mais o arquivo da obra %s", obra_id)
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
