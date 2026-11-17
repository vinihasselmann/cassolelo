"""Aceite dos parâmetros POR PEÇA com um modelo real do Docs (P6). Só lê e grava no banco do
app (DATABASE_URL); nunca chama o APS nem escreve no arquivo BIM.

1. Preparar (antes da revisão), na versão ativa da obra:

       cd backend && uv run python -m tests.real_units_acceptance prepare \\
           --obra 5 --mark PP005 [--param "Data de fabricação"] --out aceite-p6.json

   Garante o parâmetro POR PEÇA (data, só desta obra; cria se não existir), grava uma data
   DIFERENTE em cada unidade da marca (pelo serviço normal: auditado) e salva o retrato
   (unidade, chave, ElementId do Revit, valor) em `--out`. Imprime a tabela com os
   ElementIds para achar os pilares no Revit.

2. No Revit: mover uma peça da marca e apagar e recriar outra (com a mesma Marca); publicar
   com o MESMO nome do arquivo (vira a versão seguinte no Docs); "Sincronizar agora".

3. Conferir (depois que a versão nova estiver pronta):

       cd backend && uv run python -m tests.real_units_acceptance check --snapshot aceite-p6.json

   Para cada unidade: como ficou ligada (chave / ordem "conferir" / órfã), a chave antes e
   depois e se o valor continua o mesmo. Imprime o resultado em Markdown (para o PROGRESS).
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import create_engine, create_sessionmaker
from app.models import (
    Element,
    Mark,
    ModelVersion,
    ParamDef,
    PieceUnit,
    PieceUnitLink,
    PieceValue,
    User,
)
from app.models.enums import ParamLevel, Role, VersionStatus
from app.services import param_defs, piece_values

FIRST_DAY = date(2026, 11, 1)  # unidade n recebe FIRST_DAY + (n - 1) dias


def revit_element_id(external_id: str | None) -> int | None:
    """ElementId do Revit: os 8 últimos dígitos hexadecimais do UniqueId."""
    if not external_id or len(external_id) < 9 or external_id[-9] != "-":
        return None
    try:
        return int(external_id[-8:], 16)
    except ValueError:
        return None


async def _latest(session: AsyncSession, obra_id: int) -> ModelVersion:
    v = await session.scalar(
        select(ModelVersion)
        .where(ModelVersion.obra_id == obra_id, ModelVersion.status == VersionStatus.READY.value)
        .order_by(ModelVersion.version_number.desc())
        .limit(1)
    )
    if v is None:
        raise SystemExit(f"A obra {obra_id} não tem versão pronta.")
    return v


async def _mark(session: AsyncSession, obra_id: int, code: str) -> Mark:
    marks = list(
        await session.scalars(select(Mark).where(Mark.obra_id == obra_id, Mark.code == code))
    )
    if len(marks) != 1:
        raise SystemExit(f"Marca {code}: {len(marks)} encontradas na obra {obra_id} (esperado 1).")
    return marks[0]


async def _param(session: AsyncSession, obra_id: int, name: str, actor: User) -> ParamDef:
    """O parâmetro por peça do aceite: o existente com esse nome nesta obra, ou um novo
    (data, por peça, só desta obra), criado pelo serviço normal (auditado)."""
    for p in await session.scalars(
        select(ParamDef).where(ParamDef.active.is_(True), param_defs.in_obra(obra_id, level=None))
    ):
        if p.name.lower() == name.lower():
            if p.level != ParamLevel.PIECE.value:
                raise SystemExit(f'"{name}" existe nesta obra, mas é por marca.')
            return p
    return await param_defs.create_param(
        session,
        param_defs.ParamDefInput(
            name=name, type="date", scope="obra", obra_id=obra_id, level=ParamLevel.PIECE.value
        ),
        actor,
    )


async def _links(
    session: AsyncSession, version_id: int, unit_ids: list[int]
) -> dict[int, tuple[str, int, str | None, str | None]]:
    """unidade -> (método, dbId, chave, nível) na versão."""
    rows = await session.execute(
        select(
            PieceUnitLink.unit_id,
            PieceUnitLink.method,
            Element.dbid,
            Element.external_id,
            Element.level,
        )
        .join(Element, Element.id == PieceUnitLink.element_id)
        .where(PieceUnitLink.version_id == version_id, PieceUnitLink.unit_id.in_(unit_ids))
    )
    return {u: (m, d, e, lv) for u, m, d, e, lv in rows}


async def prepare(
    session: AsyncSession, obra_id: int, mark_code: str, param_name: str, actor: User
) -> dict[str, Any]:
    """Grava uma data diferente em cada unidade da marca e devolve o retrato. Sem commit."""
    version = await _latest(session, obra_id)
    mark = await _mark(session, obra_id, mark_code)
    param = await _param(session, obra_id, param_name, actor)
    units = list(
        await session.scalars(
            select(PieceUnit).where(PieceUnit.mark_id == mark.id).order_by(PieceUnit.number)
        )
    )
    links = await _links(session, version.id, [u.id for u in units])
    out = []
    for u in units:
        if u.id not in links:
            continue  # sem peça na versão ativa
        current = await session.scalar(
            select(PieceValue).where(PieceValue.unit_id == u.id, PieceValue.def_id == param.id)
        )
        value = (FIRST_DAY + timedelta(days=u.number - 1)).isoformat()
        await piece_values.save_values(
            session,
            obra_id,
            u.id,
            [piece_values.Change(param.id, value, current.row_version if current else None)],
            actor,
        )
        _method, dbid, ext, level = links[u.id]
        out.append(
            {
                "unit_id": u.id,
                "label": f"{mark.code}-{u.number}",
                "external_id": ext,
                "revit_element_id": revit_element_id(ext),
                "dbid": dbid,
                "level": level,
                "value": value,
            }
        )
    if not out:
        raise SystemExit(f"A marca {mark_code} não tem peças na versão ativa.")
    return {
        "obra_id": obra_id,
        "version_id": version.id,
        "version_number": version.version_number,
        "mark": mark.code,
        "mark_id": mark.id,
        "param_id": param.id,
        "param": param.name,
        "units": out,
    }


@dataclass
class UnitCheck:
    label: str
    value_before: str
    value_now: Any
    key_before: str | None
    key_now: str | None
    status: str  # linked | orphan | unlinked | archived
    method: str | None  # key | order | manual | new (None = sem peça)
    dbid_before: int | None
    dbid_now: int | None
    key_gone: bool  # a chave antiga sumiu da versão nova (peça apagada)

    @property
    def verdict(self) -> str:
        if self.value_now != self.value_before:
            return "ERRO: o valor mudou"
        if self.status != "linked":
            return f"sem peça ({self.status}): conferir a fila de peças órfãs"
        if self.method == "key" and self.key_now == self.key_before:
            moved = self.dbid_now != self.dbid_before
            return "seguiu a mesma peça pela chave" + (" (dbId mudou)" if moved else "")
        if self.method == "order" and self.key_gone:
            return "peça recriada: ligada pela ordem à peça nova (conferir)"
        if self.method == "manual":
            return "religada à mão"
        return f"ATENÇÃO: ligada por {self.method} a outra chave"

    @property
    def ok(self) -> bool:
        return not self.verdict.startswith(("ERRO", "ATENÇÃO"))


@dataclass
class Report:
    mark: str
    param: str
    version_before: int
    version_now: int
    units: list[UnitCheck] = field(default_factory=list)
    new_units: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.version_now > self.version_before and all(u.ok for u in self.units)


async def check(session: AsyncSession, snapshot: dict[str, Any]) -> Report:
    version = await _latest(session, snapshot["obra_id"])
    report = Report(
        snapshot["mark"], snapshot["param"], snapshot["version_number"], version.version_number
    )
    ids = [u["unit_id"] for u in snapshot["units"]]
    links = await _links(session, version.id, ids)
    keys_now = set(
        await session.scalars(select(Element.external_id).where(Element.version_id == version.id))
    )
    for u in snapshot["units"]:
        unit = await session.get(PieceUnit, u["unit_id"])
        if unit is None:  # pragma: no cover - unidades nunca são apagadas
            raise SystemExit(f"Unidade {u['label']} sumiu do banco.")
        value = await session.scalar(
            select(PieceValue.value).where(
                PieceValue.unit_id == unit.id, PieceValue.def_id == snapshot["param_id"]
            )
        )
        method, dbid, ext, _level = links.get(unit.id, (None, None, None, None))
        report.units.append(
            UnitCheck(
                label=u["label"],
                value_before=u["value"],
                value_now=value,
                key_before=u["external_id"],
                key_now=ext,
                status=unit.status,
                method=method,
                dbid_before=u["dbid"],
                dbid_now=dbid,
                key_gone=u["external_id"] not in keys_now,
            )
        )
    for (number,) in await session.execute(
        select(PieceUnit.number)
        .join(PieceUnitLink, PieceUnitLink.unit_id == PieceUnit.id)
        .where(
            PieceUnit.mark_id == snapshot["mark_id"],
            PieceUnitLink.version_id == version.id,
            PieceUnitLink.method == "new",
            PieceUnit.id.not_in(ids),
        )
    ):
        report.new_units.append(f"{snapshot['mark']}-{number}")
    return report


def render(r: Report) -> str:
    def short(k: str | None) -> str:
        eid = revit_element_id(k)
        return str(eid) if eid is not None else (k or "—")

    if r.version_now <= r.version_before:
        return (
            f"Marca **{r.mark}**: a versão ativa ainda é a v{r.version_now} (a do retrato). "
            "Ainda não há versão nova pronta: publique a revisão e sincronize."
        )
    lines = [
        f"Marca **{r.mark}**, parâmetro por peça **{r.param}**: "
        f"v{r.version_before} → v{r.version_now}. Resultado: **{'OK' if r.ok else 'FALHOU'}**.",
        "",
        "| Unidade | Valor antes | Valor agora | ElementId antes → agora "
        "| dbId antes → agora | Resultado |",
        "|---|---|---|---|---|---|",
    ]
    for u in r.units:
        dbid_now = u.dbid_now if u.dbid_now is not None else "—"
        lines.append(
            f"| {u.label} | {u.value_before} | {u.value_now} | {short(u.key_before)} → "
            f"{short(u.key_now)} | {u.dbid_before} → {dbid_now} | {u.verdict} |"
        )
    if r.new_units:
        lines.append("")
        lines.append(f"Unidades novas (vazias): {', '.join(r.new_units)}.")
    return "\n".join(lines)


async def _factory_user(session: AsyncSession) -> User:
    user = await session.scalar(
        select(User).where(User.role == Role.FABRICA.value).order_by(User.id).limit(1)
    )
    if user is None:
        raise SystemExit("Nenhum usuário da fábrica no banco (rode o seed).")
    return user


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--obra", type=int, required=True)
    p.add_argument("--mark", required=True)
    p.add_argument("--param", default="Data de fabricação")
    p.add_argument("--out", type=Path, required=True)
    c = sub.add_parser("check")
    c.add_argument("--snapshot", type=Path, required=True)
    args = parser.parse_args(argv)

    engine = create_engine(get_settings().database_url)
    maker = create_sessionmaker(engine)
    try:
        async with maker() as session:
            if args.cmd == "prepare":
                snap = await prepare(
                    session, args.obra, args.mark, args.param, await _factory_user(session)
                )
                await session.commit()
                args.out.write_text(json.dumps(snap, ensure_ascii=False, indent=2), "utf-8")
                print(
                    f"{snap['mark']} (v{snap['version_number']}): {len(snap['units'])} peças "
                    f"preenchidas em “{snap['param']}”. Retrato: {args.out}"
                )
                print("| Unidade | ElementId no Revit | Nível | Valor |")
                print("|---|---|---|---|")
                for u in snap["units"]:
                    print(
                        f"| {u['label']} | {u['revit_element_id']} | {u['level']} | {u['value']} |"
                    )
                return 0
            snap = json.loads(args.snapshot.read_text("utf-8"))
            report = await check(session, snap)
            print(render(report))
            return 0 if report.ok else 1
    finally:
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
