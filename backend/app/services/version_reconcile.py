"""Aplica a reconciliação quando uma versão termina de processar (Fase 7.2).

Roda dentro do process_version, na MESMA transação que grava os elementos (se algo
falhar, nada fica pela metade). Compara com a versão PRONTA anterior da obra:

- changed + marca com valores → review_status = review, review_note = diff;
- removed + marca com valores → órfã aberta (nunca apagar em silêncio);
- removed sem valores, new, count_changed → só ficam registrados no diff;
- new de uma marca que tinha órfã aberta (voltou) → órfã "returned";
- novas peças de marca existente herdam os valores automaticamente: valores são da
  MARCA (param_values.mark_id), não da versão nem da peça.

O resultado vai para version_diffs (JSONB): totais por classe e as marcas que não
ficaram inalteradas, com o que foi feito em cada uma.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Element, Mark, ModelVersion, Orphan, ParamDef, ParamValue, User, VersionDiff
from app.models.enums import OrphanStatus, ReviewStatus, VersionStatus
from app.services import audit
from app.services.extraction import ExtractedElement
from app.services.param_defs import has_value
from app.services.reconcile import (
    Change,
    ElementInput,
    MarkResult,
    ReconcileConfig,
    build_snapshots,
    reconcile,
)


@dataclass(frozen=True)
class ApplyResult:
    prev_version_id: int | None
    totals: dict[str, int]
    review: int
    orphans: int
    returned: int


async def previous_ready(session: AsyncSession, version: ModelVersion) -> ModelVersion | None:
    found: ModelVersion | None = await session.scalar(
        select(ModelVersion)
        .where(
            ModelVersion.obra_id == version.obra_id,
            ModelVersion.version_number < version.version_number,
            ModelVersion.status == VersionStatus.READY.value,
        )
        .order_by(ModelVersion.version_number.desc())
        .limit(1)
    )
    return found


async def marks_with_values(session: AsyncSession, mark_ids: list[int]) -> set[int]:
    """Marcas que têm algum valor preenchido (de parâmetro ativo)."""
    if not mark_ids:
        return set()
    rows = await session.scalars(
        select(ParamValue.mark_id)
        .join(ParamDef, ParamDef.id == ParamValue.def_id)
        .where(
            ParamValue.mark_id.in_(mark_ids),
            ParamDef.active.is_(True),
            has_value(ParamValue.value),
        )
        .distinct()
    )
    return set(rows)


async def _prev_elements(session: AsyncSession, version_id: int) -> list[ElementInput]:
    rows = await session.execute(
        select(Mark.code, Element.category, Element.external_id, Element.props)
        .join(Mark, Mark.id == Element.mark_id)
        .where(Element.version_id == version_id)
    )
    return [ElementInput(code, cat or "", ext, props) for code, cat, ext, props in rows]


def _mark_entry(
    m: MarkResult, mark_id: int | None, has_values: bool, action: str | None
) -> dict[str, Any]:
    return {
        "mark_id": mark_id,
        "code": m.code,
        "category": m.category,
        "change": m.change.value,
        "prev_count": m.prev_count,
        "curr_count": m.curr_count,
        "diffs": [{"property": d.property, "before": d.before, "after": d.after} for d in m.diffs],
        "note": m.summary() or None,
        "has_values": has_values,
        "action": action,  # review | orphan | returned | None (só registrado)
    }


async def apply(
    session: AsyncSession,
    version: ModelVersion,
    elements: list[ExtractedElement],
    config: ReconcileConfig,
    actor: User | None = None,
) -> ApplyResult:
    """Reconcilia `version` (elementos já gravados) com a versão pronta anterior. Sem commit."""
    prev = await previous_ready(session, version)
    curr_snaps = build_snapshots(
        [ElementInput(e.mark_code, e.category[:255], e.external_id, e.props) for e in elements],
        config,
    )
    prev_snaps = build_snapshots(await _prev_elements(session, prev.id), config) if prev else []
    result = reconcile(prev_snaps, curr_snaps, config)

    marks = {
        (m.code, m.category): m
        for m in await session.scalars(select(Mark).where(Mark.obra_id == version.obra_id))
    }
    with_values = await marks_with_values(session, [m.id for m in marks.values()])
    open_orphans = {
        o.mark_id: o
        for o in await session.scalars(
            select(Orphan).where(
                Orphan.mark_id.in_([m.id for m in marks.values()]),
                Orphan.status == OrphanStatus.OPEN.value,
            )
        )
    }
    batch = uuid.uuid4()
    entries: list[dict[str, Any]] = []
    review = orphans = returned = 0
    for item in result.marks:
        mark = marks.get((item.code, item.category))
        mark_id = mark.id if mark else None
        filled = mark_id in with_values
        action: str | None = None
        if mark is not None and item.change is Change.CHANGED and filled:
            before = {"review_status": mark.review_status, "review_note": mark.review_note}
            mark.review_status = ReviewStatus.REVIEW.value
            mark.review_note = item.summary()
            await audit.record(
                session,
                "mark",
                mark.id,
                "review",
                before,
                {
                    "review_status": mark.review_status,
                    "review_note": mark.review_note,
                    "version_id": version.id,
                },
                actor,
                batch,
            )
            action, review = "review", review + 1
        elif mark is not None and item.change is Change.REMOVED and filled:
            if mark.id not in open_orphans:
                orphan = Orphan(
                    mark_id=mark.id,
                    since_version_id=version.id,
                    status=OrphanStatus.OPEN.value,
                    created_by=actor.id if actor else None,
                    updated_by=actor.id if actor else None,
                )
                session.add(orphan)
                await session.flush()
                open_orphans[mark.id] = orphan
                await audit.record(
                    session,
                    "orphan",
                    orphan.id,
                    "create",
                    None,
                    {"mark_id": mark.id, "mark": mark.code, "since_version_id": version.id},
                    actor,
                    batch,
                )
                orphans += 1
            action = "orphan"
        elif mark is not None and item.change is Change.NEW and mark.id in open_orphans:
            orphan = open_orphans.pop(mark.id)
            orphan.status = OrphanStatus.RETURNED.value
            orphan.updated_by = actor.id if actor else None
            await audit.record(
                session,
                "orphan",
                orphan.id,
                "returned",
                {"status": OrphanStatus.OPEN.value},
                {"status": orphan.status, "mark": mark.code, "version_id": version.id},
                actor,
                batch,
            )
            action, returned = "returned", returned + 1
        if item.change is not Change.UNCHANGED and prev is not None:
            entries.append(_mark_entry(item, mark_id, filled, action))

    totals = {c.value: n for c, n in result.totals.items()}
    diff = {
        "prev_version_id": prev.id if prev else None,
        "prev_version_number": prev.version_number if prev else None,
        "totals": totals,
        "review": review,
        "orphans": orphans,
        "returned": returned,
        "review_properties": config.property_names,
        "marks": entries,  # sem as inalteradas; vazio na primeira versão
    }
    await session.execute(
        pg_insert(VersionDiff)
        .values(version_id=version.id, prev_version_id=prev.id if prev else None, diff=diff)
        .on_conflict_do_update(
            constraint="uq_version_diffs_version_id",
            set_={
                "prev_version_id": prev.id if prev else None,
                "diff": diff,
                "updated_at": func.now(),
            },
        )
    )
    return ApplyResult(prev.id if prev else None, totals, review, orphans, returned)
