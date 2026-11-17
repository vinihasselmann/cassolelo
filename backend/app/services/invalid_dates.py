"""Datas gravadas fora do intervalo válido (docs/bugs/data-por-peca.md).

O editor antigo gravava a cada tecla (ex.: 05/05/0002). Este serviço lista os valores de
parâmetros de DATA (por marca e por peça) que não são datas completas com ano entre 1900 e
2100, e limpa ou corrige cada um pelo MESMO caminho da tela (mark_values / piece_values):
auditoria normal (set/update/clear), evento em tempo real e motor de filtros atualizado.

Comando: `uv run python -m app.cli dates list [--obra N]` e `dates fix ...` (app/cli.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Mark, Obra, ParamDef, ParamValue, PieceUnit, PieceValue, User
from app.models.enums import ParamType
from app.services import mark_values, piece_values
from app.services.errors import NotFoundError, ValidationError
from app.services.mark_values import valid_date
from app.services.param_defs import has_value

MARK = "m"  # valor por marca: id "m:<param_values.id>"
PIECE = "p"  # valor por peça: id "p:<piece_values.id>"


@dataclass(frozen=True)
class InvalidDate:
    key: str  # "m:12" / "p:34"
    level: str  # "marca" / "peça"
    obra_id: int
    obra: str
    where: str  # PP318 / PP318-10
    param: str
    def_id: int
    value: Any
    row_version: int
    target_id: int  # marca (por marca) ou unidade (por peça)


async def list_invalid(session: AsyncSession, obra_id: int | None = None) -> list[InvalidDate]:
    """Valores de data inválidos (ano fora de 1900–2100, incompletos, inexistentes)."""
    out: list[InvalidDate] = []
    mark_rows = select(ParamValue, ParamDef, Mark, Obra).join(
        ParamDef, ParamDef.id == ParamValue.def_id
    )
    mark_rows = (
        mark_rows.join(Mark, Mark.id == ParamValue.mark_id)
        .join(Obra, Obra.id == Mark.obra_id)
        .where(ParamDef.type == ParamType.DATE.value, has_value(ParamValue.value))
    )
    if obra_id is not None:
        mark_rows = mark_rows.where(Mark.obra_id == obra_id)
    for v, p, m, o in await session.execute(
        mark_rows.order_by(Obra.code, Mark.code, ParamDef.name)
    ):
        if valid_date(v.value) is None:
            out.append(
                InvalidDate(
                    f"{MARK}:{v.id}",
                    "marca",
                    o.id,
                    o.code,
                    m.code,
                    p.name,
                    p.id,
                    v.value,
                    v.row_version,
                    m.id,
                )
            )
    piece_rows = (
        select(PieceValue, ParamDef, PieceUnit, Mark, Obra)
        .join(ParamDef, ParamDef.id == PieceValue.def_id)
        .join(PieceUnit, PieceUnit.id == PieceValue.unit_id)
        .join(Mark, Mark.id == PieceUnit.mark_id)
        .join(Obra, Obra.id == PieceUnit.obra_id)
        .where(ParamDef.type == ParamType.DATE.value, has_value(PieceValue.value))
    )
    if obra_id is not None:
        piece_rows = piece_rows.where(PieceUnit.obra_id == obra_id)
    for pv, p, u, m, o in await session.execute(
        piece_rows.order_by(Obra.code, Mark.code, PieceUnit.number, ParamDef.name)
    ):
        if valid_date(pv.value) is None:
            out.append(
                InvalidDate(
                    f"{PIECE}:{pv.id}",
                    "peça",
                    o.id,
                    o.code,
                    f"{m.code}-{u.number}",
                    p.name,
                    p.id,
                    pv.value,
                    pv.row_version,
                    u.id,
                )
            )
    return out


async def fix(session: AsyncSession, key: str, new_value: str | None, actor: User) -> InvalidDate:
    """Limpa (new_value=None) ou corrige um valor inválido. Sem commit. A correção passa
    pela validação normal (1900–2100)."""
    found = {d.key: d for d in await list_invalid(session)}
    item = found.get(key)
    if item is None:
        raise NotFoundError(f"{key}: não é um valor de data inválido (já corrigido?).")
    if new_value is not None and valid_date(new_value) is None:
        raise ValidationError(mark_values.DATE_INVALID)
    if item.level == "marca":
        await mark_values.save_values(
            session,
            item.obra_id,
            item.target_id,
            [mark_values.Change(item.def_id, new_value, item.row_version)],
            actor,
        )
    else:
        await piece_values.save_values(
            session,
            item.obra_id,
            item.target_id,
            [piece_values.Change(item.def_id, new_value, item.row_version)],
            actor,
        )
    return item
