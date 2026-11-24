"""Centros de gravidade das peças e numeração pela sequência de montagem (2026-11-18).

O servidor não tem a geometria (o CLAUDE.md proíbe baixar o derivativo): o navegador, com o
3D carregado, calcula o centro de gravidade de cada peça e manda para cá. O servidor:

1. guarda o centro em `elements.centroid` (vale para a versão; o reprocessamento da mesma
   versão leva junto, ver `processing._store`);
2. **renumera** as unidades de cada marca pela sequência de montagem (Z → X → Y, faixas de
   0,10 m; `assembly_order`), uma única vez, se a obra ainda está com a numeração
   PROVISÓRIA, a versão é a mais recente e nenhuma unidade da obra tem valor por peça.
   Exceção aprovada à regra "o número nunca muda": como ninguém gravou nada nas peças, o
   número ainda não identifica nada fora do app. A renumeração é uma PERMUTAÇÃO dos números
   que a marca já tem (nenhum número novo, nenhum reaproveitado), com auditoria por unidade.
   Depois disso a obra fica `sequence` e os números são definitivos;
3. numa obra `sequence`, refaz as ligações da versão mais recente que foram pela ordem
   (NWD, ou peça sem par pela chave): a ordem agora é a sequência de montagem, a mesma que
   deu os números.

O primeiro valor por peça gravado numa obra provisória trava a numeração (`fixed`): os
números ficam como estão, na ordem estável por nível e nome (`lock_numbering`).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import exists, func, select, update
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
from app.models.enums import LinkMethod, UnitNumbering, UnitStatus, VersionStatus
from app.services import audit, events, piece_props, piece_units
from app.services.assembly_order import CURRENT, Point, sequence
from app.services.errors import NotFoundError
from app.services.param_defs import has_value
from app.services.version_data import VersionNotReadyError

TEMP_OFFSET = 1_000_000  # números temporários na troca (a marca não pode repetir número)


@dataclass(frozen=True)
class CentroidStatus:
    pieces: int  # peças (elementos com marca) da versão
    stored: int  # quantas já têm centro de gravidade
    numbering: str  # provisional | sequence | fixed


@dataclass(frozen=True)
class StoreResult:
    stored: int  # centros gravados nesta chamada
    status: CentroidStatus
    renumbered: int = 0  # unidades que mudaram de número
    relinked: bool = False  # ligações refeitas pela sequência


async def _version(session: AsyncSession, version_id: int) -> tuple[ModelVersion, Obra]:
    version = await session.get(ModelVersion, version_id)
    if version is None:
        raise NotFoundError("Versão não encontrada.")
    if version.status != VersionStatus.READY.value:
        raise VersionNotReadyError("A versão ainda não está pronta.")
    obra = await session.get(Obra, version.obra_id)
    if obra is None:  # pragma: no cover - FK
        raise NotFoundError("Obra não encontrada.")
    return version, obra


async def status(session: AsyncSession, version_id: int) -> CentroidStatus:
    version, obra = await _version(session, version_id)
    return await _status(session, version, obra)


async def _status(session: AsyncSession, version: ModelVersion, obra: Obra) -> CentroidStatus:
    pieces, stored = (
        await session.execute(
            select(
                func.count(),
                func.count().filter(func.jsonb_typeof(Element.centroid) == "array"),
            ).where(Element.version_id == version.id, Element.mark_id.is_not(None))
        )
    ).one()
    return CentroidStatus(int(pieces), int(stored), obra.unit_numbering)


async def obra_has_piece_values(session: AsyncSession, obra_id: int) -> bool:
    return bool(
        await session.scalar(
            select(
                exists().where(
                    PieceValue.unit_id == PieceUnit.id,
                    PieceUnit.obra_id == obra_id,
                    has_value(PieceValue.value),
                )
            )
        )
    )


async def lock_numbering(session: AsyncSession, obra_id: int, actor: User | None) -> None:
    """Obra provisória que recebe o primeiro valor por peça: os números ficam como estão."""
    obra = await session.get(Obra, obra_id)
    if obra is None or obra.unit_numbering != UnitNumbering.PROVISIONAL.value:
        return
    obra.unit_numbering = UnitNumbering.FIXED.value
    await audit.record(
        session,
        "obra",
        obra.id,
        "unit_numbering",
        {"unit_numbering": UnitNumbering.PROVISIONAL.value},
        {"unit_numbering": UnitNumbering.FIXED.value, "reason": "piece_value"},
        actor,
    )


async def store(
    session: AsyncSession,
    version_id: int,
    coordinates: dict[int, Point],
    actor: User | None,
) -> StoreResult:
    """Guarda os centros (dbId -> [x, y, z]) e renumera/religa quando cabe (sem commit)."""
    version, obra = await _version(session, version_id)
    ids = {
        dbid: eid
        for eid, dbid in await session.execute(
            select(Element.id, Element.dbid).where(
                Element.version_id == version.id,
                Element.mark_id.is_not(None),
                Element.dbid.in_(list(coordinates)),
            )
        )
    }
    rows = [
        {"id": eid, "centroid": [float(v) for v in coordinates[dbid]]} for dbid, eid in ids.items()
    ]
    if rows:
        await session.execute(update(Element), rows)
    latest = await piece_units._is_latest(session, version)
    renumbered = 0
    relinked = False
    if rows and latest and obra.unit_numbering == UnitNumbering.PROVISIONAL.value:
        if await obra_has_piece_values(session, obra.id):  # gravado antes da trava existir
            await lock_numbering(session, obra.id, actor)
        else:
            renumbered = await _renumber(session, version, obra, actor)
    elif rows and latest and obra.unit_numbering == UnitNumbering.SEQUENCE.value:
        relinked = await _relink_by_sequence(session, version, actor)
    await session.flush()
    result = StoreResult(len(rows), await _status(session, version, obra), renumbered, relinked)
    if renumbered or relinked:
        events.emit(
            session,
            obra.id,
            "units_renumbered",
            {
                "version_id": version.id,
                "renumbered": renumbered,
                "relinked": relinked,
                "numbering": obra.unit_numbering,
            },
            actor,
        )
    return result


async def _plan(
    session: AsyncSession, version: ModelVersion, obra: Obra
) -> tuple[list[PieceUnit], dict[int, int]]:
    """Unidades da obra e o número novo de cada uma que muda (sequência atual)."""
    linked: dict[int, Point | None] = {}
    for unit_id, centroid in await session.execute(
        select(PieceUnitLink.unit_id, Element.centroid)
        .join(Element, Element.id == PieceUnitLink.element_id)
        .where(PieceUnitLink.version_id == version.id)
    ):
        linked[unit_id] = (
            (float(centroid[0]), float(centroid[1]), float(centroid[2])) if centroid else None
        )
    units = list(
        await session.scalars(
            select(PieceUnit)
            .where(PieceUnit.obra_id == obra.id)
            .order_by(PieceUnit.mark_id, PieceUnit.number)
        )
    )
    by_mark: dict[int, list[PieceUnit]] = defaultdict(list)
    for u in units:
        by_mark[u.mark_id].append(u)

    new_number: dict[int, int] = {}
    for mark_units in by_mark.values():
        with_xyz: list[tuple[PieceUnit, Point]] = []
        rest_linked: list[PieceUnit] = []
        unlinked: list[PieceUnit] = []
        for u in mark_units:  # já em ordem de número
            xyz = linked.get(u.id)
            if u.id in linked and u.status == UnitStatus.LINKED.value and xyz is not None:
                with_xyz.append((u, xyz))
            elif u.id in linked and u.status == UnitStatus.LINKED.value:
                rest_linked.append(u)
            else:
                unlinked.append(u)
        ordered = sequence(with_xyz, order=CURRENT) + rest_linked + unlinked
        numbers = [u.number for u in mark_units]  # os mesmos números, em ordem
        for u, n in zip(ordered, numbers, strict=True):
            if u.number != n:
                new_number[u.id] = n
    return units, new_number


async def _renumber(
    session: AsyncSession,
    version: ModelVersion,
    obra: Obra,
    actor: User | None,
    reason: str | None = None,
) -> int:
    """Permuta os números de cada marca pela sequência de montagem; a obra fica `sequence`."""
    before = {"unit_numbering": obra.unit_numbering, "sequence_axes": obra.sequence_axes}
    units, new_number = await _plan(session, version, obra)
    changed = [u for u in units if u.id in new_number]
    if changed:
        codes = dict(
            (
                await session.execute(
                    select(Mark.id, Mark.code).where(Mark.id.in_({u.mark_id for u in changed}))
                )
            ).all()
        )
        audits = [
            (
                u.id,
                {"number": u.number, "label": f"{codes[u.mark_id]}-{u.number}"},
                {
                    "number": new_number[u.id],
                    "label": f"{codes[u.mark_id]}-{new_number[u.id]}",
                    "version_id": version.id,
                },
            )
            for u in changed
        ]
        for u in changed:  # 1º passo: fora da faixa (único por marca + número)
            u.number += TEMP_OFFSET
        await session.flush()
        for u in changed:
            u.number = new_number[u.id]
            u.updated_by = actor.id if actor else None
        await session.flush()
        await audit.record_many(session, "piece_unit", "renumber", list(audits), actor)
        await _relabel_diff(
            session, version, {u.id: f"{codes[u.mark_id]}-{u.number}" for u in changed}
        )
    obra.unit_numbering = UnitNumbering.SEQUENCE.value
    obra.sequence_axes = CURRENT  # a ligação pela ordem segue a mesma ordem dos números
    await audit.record(
        session,
        "obra",
        obra.id,
        "unit_numbering",
        before,
        {
            "unit_numbering": UnitNumbering.SEQUENCE.value,
            "renumbered": len(changed),
            "sequence_axes": CURRENT,
            "version_id": version.id,
            **({"reason": reason} if reason else {}),
        },
        actor,
    )
    return len(changed)


@dataclass(frozen=True)
class ObraRenumber:
    version_id: int
    pieces: int  # peças da versão
    stored: int  # com centro de gravidade
    changed: int  # unidades que mudam (ou mudaram) de número
    applied: bool


async def renumber_obra(
    session: AsyncSession, obra_id: int, actor: User | None, *, apply: bool
) -> ObraRenumber:
    """Renumera uma obra JÁ numerada pela sequência na ordem atual (Z → X → Y), por decisão
    explícita do usuário (ex.: a 9121, numerada em X → Y → Z; 2026-11-19), ou uma obra
    travada (`fixed`) que não tem mais nenhum valor por peça. Permutação dos
    números de cada marca: os valores ficam nas mesmas unidades (as mesmas peças físicas),
    só os rótulos mudam. Auditado por unidade. `apply=False` só conta. Sem commit."""
    obra = await session.get(Obra, obra_id)
    if obra is None:
        raise NotFoundError("Obra não encontrada.")
    # `fixed` sem nenhum valor por peça: a trava veio de um valor que já foi apagado (ex.: a
    # GUI, travada enquanto os centros eram recusados; 2026-11-19); vale como provisória.
    fixed_empty = obra.unit_numbering == UnitNumbering.FIXED.value and not (
        await obra_has_piece_values(session, obra.id)
    )
    if obra.unit_numbering != UnitNumbering.SEQUENCE.value and not fixed_empty:
        raise ValueError(
            f"A obra está com numeração '{obra.unit_numbering}': só se renumera aqui uma obra "
            "já numerada pela sequência ('sequence') ou travada sem nenhum valor por peça."
        )
    version = await session.scalar(
        select(ModelVersion)
        .where(ModelVersion.obra_id == obra.id, ModelVersion.status == VersionStatus.READY.value)
        .order_by(ModelVersion.version_number.desc())
        .limit(1)
    )
    if version is None or not await piece_units._is_latest(session, version):
        raise ValueError("A versão mais recente da obra não está pronta.")
    st = await _status(session, version, obra)
    if st.stored < st.pieces:
        raise ValueError(
            f"Faltam centros de gravidade ({st.stored} de {st.pieces}): abra o 3D da obra antes."
        )
    if not apply:
        _units, new_number = await _plan(session, version, obra)
        return ObraRenumber(version.id, st.pieces, st.stored, len(new_number), False)
    changed = await _renumber(session, version, obra, actor, reason="manual")
    await session.flush()
    events.emit(
        session,
        obra.id,
        "units_renumbered",
        {
            "version_id": version.id,
            "renumbered": changed,
            "relinked": False,
            "numbering": obra.unit_numbering,
        },
        actor,
    )
    return ObraRenumber(version.id, st.pieces, st.stored, changed, True)


async def _relabel_diff(
    session: AsyncSession, version: ModelVersion, labels: dict[int, str]
) -> None:
    """O banner da versão lista as peças novas pelo rótulo (PP001-3): acompanha a troca."""
    row = await session.scalar(select(VersionDiff).where(VersionDiff.version_id == version.id))
    units = (row.diff or {}).get("units") if row is not None else None
    if row is None or not isinstance(units, dict):
        return
    fixed = {**units}
    for key in ("new_units", "lost_units"):
        fixed[key] = [
            {**u, "label": labels.get(int(u.get("unit_id") or 0), u.get("label"))}
            for u in units.get(key, [])
            if isinstance(u, dict)
        ]
    row.diff = {**row.diff, "units": fixed}  # novo dict: o JSONB é regravado


async def _relink_by_sequence(
    session: AsyncSession, version: ModelVersion, actor: User | None
) -> bool:
    """Refaz as ligações da versão se alguma foi pela ordem (agora pela sequência)."""
    by_order = await session.scalar(
        select(
            exists().where(
                PieceUnitLink.version_id == version.id,
                PieceUnitLink.method == LinkMethod.ORDER.value,
            )
        )
    )
    if not by_order:
        return False
    await piece_units.link_version(session, version, actor)
    await piece_props.sync_factory(session, version.obra_id)
    return True
