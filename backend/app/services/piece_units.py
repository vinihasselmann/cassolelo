"""Unidades de peça: ligação aos elementos a cada versão processada.

Chamado pelo `process_version` na mesma transação (se falhar, nada fica pela metade).
A regra está em `unit_matching` (função pura, também usada pela migração 0015).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import delete, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Element,
    Mark,
    ModelVersion,
    Obra,
    PieceUnit,
    PieceUnitLink,
    PieceValue,
    User,
    VersionDiff,
)
from app.models.enums import UnitNumbering, UnitStatus, VersionStatus
from app.services import audit
from app.services.param_defs import has_value
from app.services.unit_matching import KEY, NEW, ORDER, ElementIn, UnitIn, match

NO_KEY_FORMATS = (".nwd", ".nwc")  # Navisworks: o id é um caminho na árvore (sem chave)


def uses_key(obra: Obra) -> bool:
    """A obra tem chave estável por elemento? (RVT e IFC sim; NWD não.)"""
    name = (obra.acc_item_name or "").lower()
    return not name.endswith(NO_KEY_FORMATS)


@dataclass(frozen=True)
class LinkSummary:
    by_key: int = 0
    by_order: int = 0  # "conferir"
    new: int = 0
    orphans: int = 0  # unidades com valores que ficaram sem peça NESTA versão
    unlinked: int = 0  # sem peça e sem valores
    latest: bool = True  # False: versão anterior (só ligou; nada criado)
    returned: int = 0  # arquivadas/órfãs que voltaram pela chave
    # P5 (banner): o que mudou NESTA versão, com rótulos (PP001-3)
    lost: list[dict[str, Any]] = field(default_factory=list)  # perderam a peça (com valores)
    created: list[dict[str, Any]] = field(default_factory=list)  # unidades novas

    def as_dict(self) -> dict[str, int | bool]:
        return {
            "by_key": self.by_key,
            "by_order": self.by_order,
            "new": self.new,
            "orphans": self.orphans,
            "unlinked": self.unlinked,
            "latest": self.latest,
            "returned": self.returned,
        }

    def diff(self) -> dict[str, Any]:
        """Bloco `units` do diff da versão (banner da versão nova)."""
        return {
            "lost": len(self.lost),
            "new": len(self.created),
            "returned": self.returned,
            "by_order": self.by_order,
            "lost_units": self.lost,
            "new_units": self.created[:200],
        }


async def _is_latest(session: AsyncSession, version: ModelVersion) -> bool:
    newer = await session.scalar(
        select(
            exists().where(
                ModelVersion.obra_id == version.obra_id,
                ModelVersion.version_number > version.version_number,
                ModelVersion.status == VersionStatus.READY.value,
            )
        )
    )
    return not newer


async def units_with_values(session: AsyncSession, unit_ids: list[int]) -> set[int]:
    if not unit_ids:
        return set()
    rows = await session.scalars(
        select(func.distinct(PieceValue.unit_id)).where(
            PieceValue.unit_id.in_(unit_ids), has_value(PieceValue.value)
        )
    )
    return set(rows)


async def link_version(
    session: AsyncSession, version: ModelVersion, actor: User | None = None
) -> LinkSummary:
    """Liga as unidades das marcas aos elementos da versão (refaz as ligações dela)."""
    obra = await session.get(Obra, version.obra_id)
    if obra is None:  # pragma: no cover - FK
        raise ValueError(f"obra {version.obra_id} não existe")
    latest = await _is_latest(session, version)
    use_key = uses_key(obra)
    by_sequence = obra.unit_numbering == UnitNumbering.SEQUENCE.value
    await session.execute(delete(PieceUnitLink).where(PieceUnitLink.version_id == version.id))

    elements: dict[int, list[ElementIn]] = defaultdict(list)
    for eid, mark_id, ext, level, name, centroid in await session.execute(
        select(
            Element.id,
            Element.mark_id,
            Element.external_id,
            Element.level,
            Element.name,
            Element.centroid,
        ).where(Element.version_id == version.id, Element.mark_id.is_not(None))
    ):
        if mark_id is not None:  # filtrado na consulta; o tipo da coluna admite nulo
            xyz = (float(centroid[0]), float(centroid[1]), float(centroid[2])) if centroid else None
            elements[mark_id].append(ElementIn(eid, ext, level, name, xyz))

    # Versão mais recente: todas as unidades da obra (as de marcas que sumiram ficam sem
    # peça). Versão anterior: só as das marcas presentes, e nada muda de situação.
    stmt = select(PieceUnit).where(PieceUnit.obra_id == obra.id)
    if not latest:
        stmt = stmt.where(PieceUnit.mark_id.in_(list(elements)))
    units = list(await session.scalars(stmt.order_by(PieceUnit.mark_id, PieceUnit.number)))
    by_mark: dict[int, list[PieceUnit]] = defaultdict(list)
    for u in units:
        by_mark[u.mark_id].append(u)
    valued = await units_with_values(session, [u.id for u in units])
    codes = dict(
        (
            await session.execute(
                select(Mark.id, Mark.code).where(Mark.id.in_(set(elements) | set(by_mark)))
            )
        ).all()
    )
    lost: list[dict[str, Any]] = []
    created: list[dict[str, Any]] = []
    returned = 0

    counts = {"key": 0, "order": 0, "new": 0, "orphans": 0, "unlinked": 0}
    links: list[PieceUnitLink] = []
    for mark_id in sorted(set(elements) | set(by_mark)):
        mark_units = by_mark.get(mark_id, [])
        current = {u.id: u for u in mark_units}
        result = match(
            [
                UnitIn(
                    u.id,
                    u.number,
                    u.external_id,
                    u.id in valued,
                    key_only=u.status == UnitStatus.ARCHIVED.value,
                )
                for u in mark_units
            ],
            elements.get(mark_id, []),
            use_key=use_key,
            create=latest,
            by_sequence=by_sequence,
        )
        for link in result.links:
            if link.method == NEW:
                unit = PieceUnit(
                    obra_id=obra.id,
                    mark_id=mark_id,
                    number=link.new_number,
                    external_id=link.external_id,
                    status=UnitStatus.LINKED.value,
                    created_by=actor.id if actor else None,
                    updated_by=actor.id if actor else None,
                )
                session.add(unit)
                await session.flush()
                counts["new"] += 1
                created.append(
                    {"unit_id": unit.id, "label": f"{codes.get(mark_id, '?')}-{unit.number}"}
                )
                links.append(
                    PieceUnitLink(
                        version_id=version.id,
                        unit_id=unit.id,
                        element_id=link.element_id,
                        method=NEW,
                    )
                )
                continue

            unit = current[int(link.unit_id or 0)]
            counts["key" if link.method == KEY else "order"] += 1
            links.append(
                PieceUnitLink(
                    version_id=version.id,
                    unit_id=unit.id,
                    element_id=link.element_id,
                    method=link.method,
                )
            )
            if not latest:
                continue
            if link.method == ORDER and unit.external_id != link.external_id:
                await audit.record(
                    session,
                    "piece_unit",
                    unit.id,
                    "link_order",
                    {"external_id": unit.external_id, "status": unit.status},
                    {"external_id": link.external_id, "version_id": version.id},
                    actor,
                )
                unit.external_id = link.external_id
            if unit.status != UnitStatus.LINKED.value:
                if unit.status in (UnitStatus.ORPHAN.value, UnitStatus.ARCHIVED.value):
                    returned += 1
                    await audit.record(
                        session,
                        "piece_unit",
                        unit.id,
                        "returned",
                        {"status": unit.status, "external_id": unit.external_id},
                        {
                            "status": UnitStatus.LINKED.value,
                            "external_id": link.external_id,
                            "version_id": version.id,
                            "method": link.method,
                        },
                        actor,
                    )
                unit.status = UnitStatus.LINKED.value
                unit.since_version_id = None
        if not latest:
            continue
        for left in result.leftover:
            unit = current[left.id]
            status = UnitStatus.ORPHAN if left.has_values else UnitStatus.UNLINKED
            counts["orphans" if left.has_values else "unlinked"] += 1
            if unit.status == status.value:
                continue
            if status is UnitStatus.ORPHAN:
                lost.append(
                    {"unit_id": unit.id, "label": f"{codes.get(mark_id, '?')}-{unit.number}"}
                )
                await audit.record(
                    session,
                    "piece_unit",
                    unit.id,
                    "orphan",
                    {"status": unit.status, "external_id": unit.external_id},
                    {"status": status.value, "version_id": version.id},
                    actor,
                )
            if unit.status == UnitStatus.LINKED.value:
                unit.since_version_id = version.id
            unit.status = status.value
    session.add_all(links)
    await session.flush()
    summary = LinkSummary(
        counts["key"],
        counts["order"],
        counts["new"],
        counts["orphans"],
        counts["unlinked"],
        latest,
        returned,
        lost,
        created,
    )
    if latest:
        await _record_diff(session, version, summary)
    return summary


async def _record_diff(session: AsyncSession, version: ModelVersion, summary: LinkSummary) -> None:
    """Guarda o resumo das unidades no diff da versão (lido pelo banner)."""
    row = await session.scalar(select(VersionDiff).where(VersionDiff.version_id == version.id))
    if row is not None:
        row.diff = {**row.diff, "units": summary.diff()}  # novo dict: o JSONB é regravado
        await session.flush()
