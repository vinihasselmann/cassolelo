"""Status de produção por marca e progresso da obra (Fase 6.4). Calculado na hora.

Regra (igual ao mockup):
- base = parâmetros OBRIGATÓRIOS que se aplicam à marca (escopo + categoria); se não há
  obrigatórios para ela, qualquer parâmetro aplicável conta;
- nenhum da base preenchido (ou base vazia) → pending; todos → complete; senão → partial;
- review ("a revisar"): a reconciliação (Fase 7.2) marcou a marca (marks.review_status);
  tem precedência sobre os outros até a fábrica "Manter valores" ou editar.

Só entram as marcas que têm peças na versão (as órfãs não têm cor nem progresso).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Element, Mark, ParamDef, ParamValue
from app.models.enums import ReviewStatus
from app.services.errors import NotFoundError
from app.services.param_defs import has_value
from app.services.param_defs import in_obra as param_in_obra
from app.services.version_data import get_ready_version


class MarkStatus(StrEnum):
    PENDING = "pending"
    PARTIAL = "partial"
    COMPLETE = "complete"
    REVIEW = "review"


@dataclass(frozen=True)
class _VersionMark:
    id: int
    category: str
    pieces: int
    review: bool = False


@dataclass
class _Snapshot:
    marks: list[_VersionMark]
    params: list[ParamDef]  # ativos da obra (globais + da obra)
    filled: dict[int, set[int]]  # mark_id -> def_ids com valor


def applies(param: ParamDef, category: str) -> bool:
    return not param.categories or category in param.categories


def status_of(params: list[ParamDef], category: str, filled: set[int]) -> MarkStatus:
    applicable = [p for p in params if applies(p, category)]
    required = [p for p in applicable if p.required]
    base = required or applicable
    done = sum(1 for p in base if p.id in filled)
    if not base or done == 0:
        return MarkStatus.PENDING
    return MarkStatus.COMPLETE if done == len(base) else MarkStatus.PARTIAL


async def _snapshot(session: AsyncSession, version_id: int) -> _Snapshot:
    version = await get_ready_version(session, version_id)
    rows = await session.execute(
        select(Mark.id, Mark.category, func.count(), Mark.review_status)
        .join(Element, Element.mark_id == Mark.id)
        .where(Element.version_id == version_id)
        .group_by(Mark.id)
    )
    marks = [_VersionMark(r[0], r[1], r[2], r[3] == ReviewStatus.REVIEW.value) for r in rows]
    params = list(
        await session.scalars(
            select(ParamDef)
            .where(
                ParamDef.active.is_(True),
                param_in_obra(version.obra_id),
            )
            .order_by(func.lower(ParamDef.name), ParamDef.id)
        )
    )
    filled: dict[int, set[int]] = defaultdict(set)
    if marks and params:
        mark_ids = select(Element.mark_id).where(
            Element.version_id == version_id, Element.mark_id.is_not(None)
        )
        values = await session.execute(
            select(ParamValue.mark_id, ParamValue.def_id).where(
                ParamValue.mark_id.in_(mark_ids),
                ParamValue.def_id.in_([p.id for p in params]),
                has_value(ParamValue.value),
            )
        )
        for mark_id, def_id in values:
            filled[mark_id].add(def_id)
    return _Snapshot(marks, params, filled)


@dataclass(frozen=True)
class StatusResult:
    statuses: dict[int, MarkStatus]  # mark_id -> status
    counts: dict[MarkStatus, int]  # marcas por status (inclui zeros)
    pieces: dict[MarkStatus, int]  # peças por status


async def version_statuses(session: AsyncSession, version_id: int) -> StatusResult:
    snap = await _snapshot(session, version_id)
    statuses = {
        m.id: MarkStatus.REVIEW
        if m.review
        else status_of(snap.params, m.category, snap.filled.get(m.id, set()))
        for m in snap.marks
    }
    counts = Counter(statuses.values())
    pieces: Counter[MarkStatus] = Counter()
    for m in snap.marks:
        pieces[statuses[m.id]] += m.pieces
    return StatusResult(
        statuses=statuses,
        counts={s: counts.get(s, 0) for s in MarkStatus},
        pieces={s: pieces.get(s, 0) for s in MarkStatus},
    )


async def marks_with_status(
    session: AsyncSession, version_id: int, wanted: MarkStatus
) -> list[int]:
    result = await version_statuses(session, version_id)
    return [mid for mid, s in result.statuses.items() if s is wanted]


@dataclass(frozen=True)
class ParamProgress:
    def_id: int
    name: str
    marks_total: int  # marcas da versão em que o parâmetro se aplica
    marks_filled: int
    pieces_total: int
    pieces_filled: int


@dataclass(frozen=True)
class Progress:
    marks: int
    pieces: int
    required: list[ParamProgress]


async def progress(session: AsyncSession, version_id: int) -> Progress:
    """Progresso por parâmetro OBRIGATÓRIO (marcas e peças em que se aplica)."""
    snap = await _snapshot(session, version_id)
    out = []
    for p in snap.params:
        if not p.required:
            continue
        target = [m for m in snap.marks if applies(p, m.category)]
        done = [m for m in target if p.id in snap.filled.get(m.id, set())]
        out.append(
            ParamProgress(
                def_id=p.id,
                name=p.name,
                marks_total=len(target),
                marks_filled=len(done),
                pieces_total=sum(m.pieces for m in target),
                pieces_filled=sum(m.pieces for m in done),
            )
        )
    return Progress(marks=len(snap.marks), pieces=sum(m.pieces for m in snap.marks), required=out)


@dataclass(frozen=True)
class ParamValues:
    param: ParamDef
    values: dict[int, Any]  # mark_id -> valor (só marcas em que se aplica; None = vazio)


async def param_values(session: AsyncSession, version_id: int, def_id: int) -> ParamValues:
    """Valor de UM parâmetro em cada marca da versão (para "Colorir por parâmetro")."""
    snap = await _snapshot(session, version_id)
    param = next((p for p in snap.params if p.id == def_id), None)
    if param is None:
        raise NotFoundError("Parâmetro não encontrado nesta obra.")
    target = {m.id for m in snap.marks if applies(param, m.category)}
    values: dict[int, Any] = dict.fromkeys(target)
    if target:
        rows = await session.execute(
            select(ParamValue.mark_id, ParamValue.value).where(
                ParamValue.def_id == def_id,
                ParamValue.mark_id.in_(target),
                has_value(ParamValue.value),
            )
        )
        for mark_id, value in rows:
            values[mark_id] = value
    return ParamValues(param, values)
