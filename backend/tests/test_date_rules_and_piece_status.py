"""Correção do bug de data por peça (docs/bugs/data-por-peca.md):
- validação de data (completa, ano 1900–2100);
- status de produção POR PEÇA (preencher uma peça não muda as outras da marca);
- comando que lista e limpa/corrige datas inválidas já gravadas (auditado)."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.aps.client import ApsClient
from app.models import AuditLog, Mark, Obra, ParamDef, ParamValue, PieceUnit, PieceValue, User
from app.models.enums import Role
from app.services import invalid_dates
from app.services.errors import NotFoundError, ValidationError
from app.services.mark_status import MarkStatus, aggregate, status_of
from app.services.mark_values import DATE_INVALID, valid_date

# ------------------------------------------------------------------ validação de data


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-05-05", "2026-05-05"),
        ("1900-01-01", "1900-01-01"),
        ("2100-12-31", "2100-12-31"),
        ("2026-05-05T00:00:00", "2026-05-05"),  # sufixo de hora é descartado
        (" 2026-05-05 ", "2026-05-05"),
        ("0002-05-05", None),  # o bug: ano parcial
        ("0020-11-16", None),
        ("1899-12-31", None),
        ("2101-01-01", None),
        ("2026-02-30", None),  # não existe
        ("2026-5-5", None),  # incompleta
        ("05/05/2026", None),  # formato da tela, não da API
        ("", None),
        ("abc", None),
    ],
)
def test_valid_date(raw: str, expected: str | None) -> None:
    assert valid_date(raw) == expected


def test_date_message() -> None:
    assert DATE_INVALID == "Data inválida: use dd/mm/aaaa"


# ------------------------------------------------------------------ status por peça


def _param(
    id_: int, *, level: str = "mark", required: bool = False, cats: list[str] | None = None
) -> ParamDef:
    p = ParamDef(id=id_, name=f"p{id_}", type="date", scope="obra", required=required)
    p.level = level
    p.categories = cats
    return p


def test_piece_status_counts_only_this_piece_unit() -> None:
    concretagem = _param(16, level="piece")  # opcional e único: a base é ele
    params = [concretagem]
    # a peça preenchida fica completa; as outras da mesma marca continuam pendentes
    assert status_of(params, "Pilar", set(), {16}) is MarkStatus.COMPLETE
    assert status_of(params, "Pilar", set(), set()) is MarkStatus.PENDING


def test_piece_status_mixes_mark_and_piece_params() -> None:
    forma = _param(1, required=True)  # por marca
    fab = _param(2, level="piece", required=True)  # por peça
    nota = _param(3, level="piece")  # opcional: não conta quando há obrigatórios
    params = [forma, fab, nota]
    assert status_of(params, "Pilar", set(), set()) is MarkStatus.PENDING
    assert status_of(params, "Pilar", set(), {3}) is MarkStatus.PENDING
    assert status_of(params, "Pilar", {1}, set()) is MarkStatus.PARTIAL
    assert status_of(params, "Pilar", set(), {2}) is MarkStatus.PARTIAL
    assert status_of(params, "Pilar", {1}, {2}) is MarkStatus.COMPLETE
    # parâmetro de outra categoria não entra
    viga = _param(4, level="piece", required=True, cats=["Viga"])
    assert status_of([*params, viga], "Pilar", {1}, {2}) is MarkStatus.COMPLETE


def test_mark_status_is_the_aggregate_of_its_pieces() -> None:
    C, P, X, R = MarkStatus.COMPLETE, MarkStatus.PENDING, MarkStatus.PARTIAL, MarkStatus.REVIEW
    assert aggregate([C, C, C]) is C
    assert aggregate([P] * 13) is P
    assert aggregate([C] + [P] * 12) is X  # 1 de 13 preenchida: a MARCA é parcial
    assert aggregate([X, X]) is X
    assert aggregate([R, C]) is R
    assert aggregate([]) is P


# ------------------------------------------------------------------ comando de datas inválidas


@pytest.fixture
async def bad(session: AsyncSession, users: dict[Role, User]) -> dict[str, Any]:
    obra = Obra(code="OB-DT", name="Obra datas")
    session.add(obra)
    await session.flush()
    mark = Mark(obra_id=obra.id, code="PP318", category="Pilar")
    session.add(mark)
    await session.flush()
    unit = PieceUnit(obra_id=obra.id, mark_id=mark.id, number=10, status="linked")
    ok_unit = PieceUnit(obra_id=obra.id, mark_id=mark.id, number=11, status="linked")
    concretagem = _param(0, level="piece")
    concretagem.id = None  # type: ignore[assignment]
    concretagem.name, concretagem.obra_id = "concretagem", obra.id
    entrega = ParamDef(name="Entrega", type="date", scope="obra", obra_id=obra.id)
    session.add_all([unit, ok_unit, concretagem, entrega])
    await session.flush()
    # gravados pelo editor antigo (sem validação)
    session.add_all(
        [
            PieceValue(unit_id=unit.id, def_id=concretagem.id, value="0002-05-05"),
            PieceValue(unit_id=ok_unit.id, def_id=concretagem.id, value="2026-05-05"),
            ParamValue(mark_id=mark.id, def_id=entrega.id, value="0020-11-16"),
        ]
    )
    await session.flush()
    return {
        "obra": obra,
        "mark": mark,
        "unit": unit,
        "concretagem": concretagem,
        "admin": users[Role.ADMIN],
    }


async def test_list_invalid_dates(session: AsyncSession, bad: dict[str, Any]) -> None:
    found = await invalid_dates.list_invalid(session, bad["obra"].id)
    assert [(d.level, d.where, d.param, d.value) for d in found] == [
        ("marca", "PP318", "Entrega", "0020-11-16"),
        ("peça", "PP318-10", "concretagem", "0002-05-05"),
    ]
    assert found[1].key.startswith("p:")
    assert await invalid_dates.list_invalid(session, bad["obra"].id + 999) == []


async def test_clear_and_fix_are_audited(session: AsyncSession, bad: dict[str, Any]) -> None:
    found = {d.where: d for d in await invalid_dates.list_invalid(session, bad["obra"].id)}
    await invalid_dates.fix(session, found["PP318-10"].key, None, bad["admin"])
    await invalid_dates.fix(session, found["PP318"].key, "2026-11-16", bad["admin"])
    assert await invalid_dates.list_invalid(session, bad["obra"].id) == []
    value = await session.scalar(
        select(PieceValue.value).where(PieceValue.unit_id == bad["unit"].id)
    )
    assert value is None
    actions = {
        (a.entity, a.action, (a.before or {}).get("value"), (a.after or {}).get("value"))
        for a in await session.scalars(select(AuditLog).where(AuditLog.user_id == bad["admin"].id))
    }
    assert ("piece_value", "clear", "0002-05-05", None) in actions
    assert ("mark_value", "update", "0020-11-16", "2026-11-16") in actions


async def test_fix_rejects_bad_new_value_and_unknown_key(
    session: AsyncSession, bad: dict[str, Any]
) -> None:
    [_, piece] = await invalid_dates.list_invalid(session, bad["obra"].id)
    with pytest.raises(ValidationError, match="Data inválida"):
        await invalid_dates.fix(session, piece.key, "0002-01-01", bad["admin"])
    with pytest.raises(NotFoundError):
        await invalid_dates.fix(session, "p:999999", None, bad["admin"])


async def test_cli_lists_and_clears(
    session: AsyncSession, aps: ApsClient, bad: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    from app.cli import run as cli_run
    from tests.conftest import make_settings

    obra = str(bad["obra"].id)
    assert await cli_run(["dates", "list", "--obra", obra], make_settings(), session, aps) == 0
    out = capsys.readouterr().out
    assert "PP318-10\tconcretagem\t0002-05-05" in out and "2 data(s) inválida(s)." in out
    key = next(line.split("\t")[0] for line in out.splitlines() if "PP318-10" in line)
    code = await cli_run(["dates", "fix", key, "--clear"], make_settings(), session, aps)
    assert code == 0
    assert "0002-05-05 apagada" in capsys.readouterr().out
    assert await cli_run(["dates", "fix", key, "--clear"], make_settings(), session, aps) == 2
