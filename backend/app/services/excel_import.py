"""Importação de valores pelo Excel exportado pelo app (decisões de 2026-11-19).

A pessoa exporta a obra (export.py), preenche as colunas dos parâmetros e envia o
arquivo de volta. O app mostra a prévia (nada gravado) e só grava ao confirmar.

Leitura (o mesmo layout do export):
- aba "Sobre": a obra do arquivo tem de ser esta (código da obra);
- aba "Marcas": parâmetros POR MARCA; a linha é a marca (Marca + Categoria);
- aba "Peças": parâmetros POR PEÇA; a linha é a unidade, achada pelo externalId na
  versão ativa (chave estável). Sem externalId (NWD), pelo rótulo "Peça" (PP001-3). Rótulo
  diferente do atual (a numeração mudou depois do export) vira aviso "conferir".
- colunas de parâmetro pelo cabeçalho "Nome (unidade)" (como o export escreve); as demais
  (Seção, Status, X/Y/Z…) são só leitura e ficam de fora.

Regras:
- célula vazia = sem mudança (o Excel nunca apaga valor);
- valor novo onde o app está vazio = PREENCHER; valor diferente do app = ALTERAR, que só é
  gravado com `overwrite` (padrão: só preenche os vazios);
- linhas com erro (data inválida, opção que não existe, parâmetro que não vale para a
  categoria, marca/peça não encontrada…) ficam de fora e são listadas; as válidas são
  aplicadas;
- fórmulas valem pelo valor calculado que o Excel salvou no arquivo (nunca executadas);
- tudo vai num lote só (`batch_id`): auditoria com `"source": "import"` e um "Desfazer".

`fingerprint` resume o que a prévia mostrou: o apply recalcula e recusa (409) se o estado
mudou desde então (alguém gravou no meio).
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import uuid
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Element,
    Mark,
    ModelVersion,
    Obra,
    ParamDef,
    ParamValue,
    PieceUnit,
    PieceUnitLink,
    PieceValue,
    User,
)
from app.models.enums import ParamLevel, ParamSource, ParamType, UnitStatus, VersionStatus
from app.services import mark_batch, piece_values
from app.services.errors import ConflictError, NotFoundError, ValidationError
from app.services.export import BASE_HEADERS, COORD_HEADERS, SEQ_HEADER
from app.services.mark_batch import BatchMode
from app.services.mark_values import _filled, normalize
from app.services.param_defs import in_obra

MAX_BYTES = 5 * 1024 * 1024  # arquivo enviado
MAX_UNZIPPED = 100 * 1024 * 1024  # proteção contra "zip bomb"
MAX_ROWS = 20_000  # por aba
SOURCE = "import"

MARKS_SHEET, PIECES_SHEET, ABOUT_SHEET = "Marcas", "Peças", "Sobre"
# colunas que o export escreve e que não são parâmetros (só leitura)
MARK_INFO = {*BASE_HEADERS, "Última alteração", "Autor"}
PIECE_INFO = {
    "Marca",
    "Categoria",
    "externalId",
    "Nível",
    "dbId",
    "Peça",
    *COORD_HEADERS,
    SEQ_HEADER,
}

_BR_DATE = re.compile(r"^\s*(\d{1,2})/(\d{1,2})/(\d{4})\s*$")


# --------------------------------------------------------------------------- resultado


@dataclass(frozen=True)
class Issue:
    sheet: str
    row: int | None  # linha do Excel (1 = cabeçalho)
    column: str | None
    message: str


@dataclass(frozen=True)
class Change:
    sheet: str
    row: int
    target: str  # marca (PP001) ou peça (PP001-3)
    category: str
    param: str
    def_id: int
    old: Any  # valor atual no app (None = vazio)
    new: Any  # valor do arquivo, normalizado

    @property
    def is_fill(self) -> bool:
        return self.old is None


@dataclass(frozen=True)
class ParamSummary:
    def_id: int
    name: str
    level: str
    fills: int
    changes: int


@dataclass
class ImportPlan:
    obra_code: str
    file_version: str | None
    marks_rows: int = 0
    pieces_rows: int = 0
    fills: list[Change] = field(default_factory=list)
    changes: list[Change] = field(default_factory=list)
    unchanged: int = 0  # células preenchidas iguais ao app
    errors: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)
    ignored_columns: list[str] = field(default_factory=list)
    params: list[ParamSummary] = field(default_factory=list)
    # planilha do Plannix (plannix_import): ligações, parâmetros novos, avisos por marca
    plannix: Any = None
    fingerprint_extra: list[str] = field(default_factory=list)
    # alvos: (mark_id | unit_id) -> {def_id: valor}
    mark_values: dict[int, dict[int, Any]] = field(default_factory=dict)
    unit_values: dict[int, dict[int, Any]] = field(default_factory=dict)
    mark_change_keys: set[tuple[int, int]] = field(default_factory=set)
    unit_change_keys: set[tuple[int, int]] = field(default_factory=set)

    @property
    def fingerprint(self) -> str:
        """Resumo estável do que a prévia mostrou (alvos, valor atual e novo)."""
        items = sorted(
            json.dumps(
                [c.sheet, c.target, c.category, c.def_id, c.param, c.old, c.new], default=str
            )
            for c in [*self.fills, *self.changes]
        )
        items.extend(self.fingerprint_extra)
        return hashlib.sha256("\n".join(items).encode()).hexdigest()[:32]

    def values_for(
        self, overwrite: bool
    ) -> tuple[dict[int, dict[int, Any]], dict[int, dict[int, Any]]]:
        """O que gravar: os preenchimentos e, com `overwrite`, também as alterações."""

        def pick(
            values: dict[int, dict[int, Any]], skip: set[tuple[int, int]]
        ) -> dict[int, dict[int, Any]]:
            out: dict[int, dict[int, Any]] = {}
            for target, fields in values.items():
                kept = {d: v for d, v in fields.items() if overwrite or (target, d) not in skip}
                if kept:
                    out[target] = kept
            return out

        return pick(self.mark_values, self.mark_change_keys), pick(
            self.unit_values, self.unit_change_keys
        )


@dataclass(frozen=True)
class ImportResult:
    batch_id: uuid.UUID | None
    marks_changed: int
    units_changed: int
    fields_changed: int


# --------------------------------------------------------------------------- arquivo


def _open(content: bytes) -> Any:
    if len(content) > MAX_BYTES:
        raise ValidationError("Arquivo grande demais (máximo 5 MB).")
    if not content.startswith(b"PK"):
        raise ValidationError("O arquivo não é um Excel (.xlsx). Use o Excel exportado pelo app.")
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            names = z.namelist()
            if any(n.lower().endswith("vbaproject.bin") for n in names):
                raise ValidationError("Arquivo com macro (.xlsm) não é aceito: salve como .xlsx.")
            if sum(i.file_size for i in z.infolist()) > MAX_UNZIPPED:
                raise ValidationError("Arquivo grande demais depois de descompactado.")
        return load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except ValidationError:
        raise
    except Exception:
        raise ValidationError(
            "Não foi possível ler o arquivo. Use o Excel exportado pelo app (.xlsx)."
        ) from None


def _rows(ws: Worksheet) -> list[tuple[Any, ...]]:
    rows = []
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i > MAX_ROWS:
            raise ValidationError(f'A aba "{ws.title}" tem linhas demais (máximo {MAX_ROWS}).')
        rows.append(row)
    return rows


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _about(wb: Any) -> dict[str, Any]:
    if ABOUT_SHEET not in wb.sheetnames:
        raise ValidationError(
            'Aba "Sobre" não encontrada: use o Excel exportado pelo app (sem renomear abas).'
        )
    out: dict[str, Any] = {}
    for row in _rows(wb[ABOUT_SHEET]):
        if row and row[0] is not None:
            out[_text(row[0])] = row[1] if len(row) > 1 else None
    return out


def _param_label(p: ParamDef) -> str:
    return f"{p.name} ({p.unit})" if p.unit else p.name


def _raw(param: ParamDef, value: Any) -> Any:
    """Célula do Excel → valor de entrada do `normalize` (as mesmas regras da tela)."""
    if isinstance(value, str):
        value = value.strip()
    if ParamType(param.type) is ParamType.DATE:
        if isinstance(value, datetime):
            return value.date().isoformat()
        if isinstance(value, date):
            return value.isoformat()
        m = _BR_DATE.match(str(value))
        if m:
            day, month, year = (int(g) for g in m.groups())
            return f"{year:04d}-{month:02d}-{day:02d}"
        return str(value)
    if (
        isinstance(value, float)
        and value.is_integer()
        and ParamType(param.type) is not ParamType.NUMBER
    ):
        return str(int(value))  # 12.0 numa coluna de texto/lista → "12"
    return value


def _header_map(
    header: tuple[Any, ...],
    info: set[str],
    params: dict[str, ParamDef],
    sheet: str,
    plan: ImportPlan,
) -> tuple[dict[str, int], dict[int, ParamDef]]:
    """Colunas de identificação (nome → índice) e de parâmetro (índice → parâmetro)."""
    ids: dict[str, int] = {}
    cols: dict[int, ParamDef] = {}
    seen: set[str] = set()
    for i, raw in enumerate(header):
        name = _text(raw)
        if not name:
            continue
        if name in seen:
            raise ValidationError(f'Aba "{sheet}": a coluna "{name}" aparece duas vezes.')
        seen.add(name)
        if name in info:
            ids[name] = i
        elif name in params:
            cols[i] = params[name]
        else:
            plan.ignored_columns.append(f"{sheet}: {name}")
    return ids, cols


# --------------------------------------------------------------------------- obra


async def _active_version(session: AsyncSession, obra_id: int) -> ModelVersion:
    version = await session.scalar(
        select(ModelVersion)
        .where(ModelVersion.obra_id == obra_id, ModelVersion.status == VersionStatus.READY.value)
        .order_by(ModelVersion.version_number.desc())
        .limit(1)
    )
    if version is None:
        raise ValidationError(
            "A obra ainda não tem versão pronta: não há peças para receber valores."
        )
    return version


async def _params(session: AsyncSession, obra_id: int, level: str) -> list[ParamDef]:
    return list(
        await session.scalars(
            select(ParamDef)
            .where(ParamDef.active.is_(True), in_obra(obra_id, level=level))
            # os do Plannix só vêm pela planilha do Plannix (aqui são só leitura)
            .where(ParamDef.source == ParamSource.MANUAL.value)
            .order_by(func.lower(ParamDef.name), ParamDef.id)
        )
    )


def _applies(p: ParamDef, category: str) -> bool:
    return not p.categories or category in p.categories


class _Cells:
    """Lê as células de parâmetro de uma linha: valida, compara com o app e anota."""

    def __init__(self, plan: ImportPlan, sheet: str) -> None:
        self.plan = plan
        self.sheet = sheet
        self.seen: dict[tuple[int, int], tuple[Any, int]] = {}  # (alvo, def) -> (valor, linha)

    def read(
        self,
        row_no: int,
        row: tuple[Any, ...],
        cols: dict[int, ParamDef],
        category: str,
        target_id: int,
        target: str,
        current: dict[int, Any],
        out: dict[int, dict[int, Any]],
        change_keys: set[tuple[int, int]],
    ) -> None:
        for idx, param in cols.items():
            cell = row[idx] if idx < len(row) else None
            if not _filled(cell if not isinstance(cell, str) else cell.strip()):
                continue  # célula vazia: sem mudança
            column = _param_label(param)
            if not _applies(param, category):
                self.error(row_no, column, f'"{param.name}" não vale para a categoria {category}.')
                continue
            try:
                new = normalize(param, _raw(param, cell))
            except ValidationError as exc:
                msg = exc.message
                self.error(row_no, column, msg if param.name in msg else f"{param.name}: {msg}")
                continue
            key = (target_id, param.id)
            if key in self.seen:
                prev, prev_row = self.seen[key]
                if prev != new:
                    self.error(
                        row_no,
                        column,
                        f"{target} aparece de novo (linha {prev_row}) com outro valor.",
                    )
                continue
            self.seen[key] = (new, row_no)
            old = current.get(param.id)
            if old == new:
                self.plan.unchanged += 1
                continue
            change = Change(self.sheet, row_no, target, category, param.name, param.id, old, new)
            out.setdefault(target_id, {})[param.id] = new
            if change.is_fill:
                self.plan.fills.append(change)
            else:
                self.plan.changes.append(change)
                change_keys.add(key)

    def error(self, row: int | None, column: str | None, message: str) -> None:
        self.plan.errors.append(Issue(self.sheet, row, column, message))


async def _marks_sheet(
    session: AsyncSession, obra_id: int, version: ModelVersion, wb: Any, plan: ImportPlan
) -> None:
    if MARKS_SHEET not in wb.sheetnames:
        return
    rows = _rows(wb[MARKS_SHEET])
    if not rows:
        return
    params = {_param_label(p): p for p in await _params(session, obra_id, ParamLevel.MARK.value)}
    ids, cols = _header_map(rows[0], MARK_INFO, params, MARKS_SHEET, plan)
    if "Marca" not in ids or "Categoria" not in ids:
        raise ValidationError('Aba "Marcas": faltam as colunas "Marca" e "Categoria".')
    if not cols:
        return
    # marcas da versão ativa
    marks = {
        (m.code, m.category): m
        for m in await session.scalars(
            select(Mark)
            .where(Mark.obra_id == obra_id)
            .where(Mark.id.in_(select(Element.mark_id).where(Element.version_id == version.id)))
        )
    }
    current: dict[int, dict[int, Any]] = defaultdict(dict)
    for v in await session.scalars(
        select(ParamValue).where(
            ParamValue.mark_id.in_([m.id for m in marks.values()]),
            ParamValue.def_id.in_([p.id for p in cols.values()]),
        )
    ):
        if _filled(v.value):
            current[v.mark_id][v.def_id] = v.value
    cells = _Cells(plan, MARKS_SHEET)
    for row_no, row in enumerate(rows[1:], start=2):
        code, category = _text(row[ids["Marca"]]), _text(row[ids["Categoria"]])
        if not code and not category:
            continue
        has_values = any(_filled(row[i]) for i in cols if i < len(row))
        if not has_values:
            continue
        plan.marks_rows += 1
        mark = marks.get((code, category))
        if mark is None:
            cells.error(
                row_no, "Marca", f"Marca {code} ({category}) não está na versão ativa da obra."
            )
            continue
        cells.read(
            row_no,
            row,
            cols,
            category,
            mark.id,
            mark.code,
            current[mark.id],
            plan.mark_values,
            plan.mark_change_keys,
        )


async def _pieces_sheet(
    session: AsyncSession, obra_id: int, version: ModelVersion, wb: Any, plan: ImportPlan
) -> None:
    if PIECES_SHEET not in wb.sheetnames:
        return
    rows = _rows(wb[PIECES_SHEET])
    if not rows:
        return
    params = {_param_label(p): p for p in await _params(session, obra_id, ParamLevel.PIECE.value)}
    ids, cols = _header_map(rows[0], PIECE_INFO, params, PIECES_SHEET, plan)
    if not cols:
        return
    if "externalId" not in ids and "Peça" not in ids:
        raise ValidationError('Aba "Peças": faltam as colunas "externalId" e "Peça".')

    # unidades da obra e as ligações da versão ativa (externalId → unidade)
    units = {
        u.id: u
        for u in await session.scalars(select(PieceUnit).where(PieceUnit.obra_id == obra_id))
    }
    marks = {m.id: m for m in await session.scalars(select(Mark).where(Mark.obra_id == obra_id))}
    by_external: dict[str, PieceUnit] = {}
    for ext, unit_id in await session.execute(
        select(Element.external_id, PieceUnitLink.unit_id)
        .join(PieceUnitLink, PieceUnitLink.element_id == Element.id)
        .where(PieceUnitLink.version_id == version.id, Element.external_id.is_not(None))
    ):
        by_external[str(ext)] = units[unit_id]
    by_label = {
        piece_values.unit_label(marks[u.mark_id], u): u
        for u in units.values()
        if u.status == UnitStatus.LINKED.value
    }
    current: dict[int, dict[int, Any]] = defaultdict(dict)
    for v in await session.scalars(
        select(PieceValue)
        .where(PieceValue.def_id.in_([p.id for p in cols.values()]))
        .where(PieceValue.unit_id.in_(list(units)))
    ):
        if _filled(v.value):
            current[v.unit_id][v.def_id] = v.value

    cells = _Cells(plan, PIECES_SHEET)
    for row_no, row in enumerate(rows[1:], start=2):
        has_values = any(_filled(row[i]) for i in cols if i < len(row))
        if not has_values:
            continue
        plan.pieces_rows += 1
        ext = _text(row[ids["externalId"]]) if "externalId" in ids else ""
        label = _text(row[ids["Peça"]]) if "Peça" in ids else ""
        unit = by_external.get(ext) if ext else None
        if unit is None and ext and not label:
            cells.error(row_no, "externalId", f"Peça {ext} não está na versão ativa da obra.")
            continue
        if unit is None:
            unit = by_label.get(label) if label else None
            if unit is None:
                what = label or ext or "sem identificação"
                cells.error(row_no, "Peça", f"Peça {what} não está na versão ativa da obra.")
                continue
        if unit.status != UnitStatus.LINKED.value:
            cells.error(
                row_no, "Peça", f"Peça {label or ext} está órfã ou arquivada: não recebe valores."
            )
            continue
        mark = marks[unit.mark_id]
        now_label = piece_values.unit_label(mark, unit)
        if label and label != now_label:
            plan.warnings.append(
                Issue(
                    PIECES_SHEET,
                    row_no,
                    "Peça",
                    f"Conferir: no arquivo {label}, hoje é {now_label} (ligada pelo externalId;"
                    " a numeração mudou depois do export).",
                )
            )
        cells.read(
            row_no,
            row,
            cols,
            mark.category,
            unit.id,
            now_label,
            current[unit.id],
            plan.unit_values,
            plan.unit_change_keys,
        )


def _summaries(plan: ImportPlan, levels: dict[int, str]) -> list[ParamSummary]:
    counts: dict[int, list[Any]] = {}
    for c in [*plan.fills, *plan.changes]:
        entry = counts.setdefault(c.def_id, [c.param, 0, 0])
        entry[1 if c.is_fill else 2] += 1
    return [
        ParamSummary(def_id, name, levels.get(def_id, ParamLevel.MARK.value), fills, changes)
        for def_id, (name, fills, changes) in sorted(
            counts.items(), key=lambda kv: kv[1][0].casefold()
        )
    ]


async def build_plan(session: AsyncSession, obra_id: int, content: bytes) -> ImportPlan:
    """Lê o arquivo e compara com o app. Não grava nada."""
    obra = await session.get(Obra, obra_id)
    if obra is None:
        raise NotFoundError("Obra não encontrada.")
    wb = _open(content)
    from app.services import plannix_import  # o Plannix usa as peças deste módulo

    if plannix_import.is_plannix(wb):
        try:
            return await plannix_import.build_plan(session, obra, wb)
        finally:
            wb.close()
    try:
        about = _about(wb)
        file_obra = _text(about.get("Obra"))
        file_code = file_obra.split(" — ", 1)[0].strip()
        if file_code != obra.code:
            raise ValidationError(
                f"Este arquivo é da obra {file_code or '(sem obra)'}, não da {obra.code}."
            )
        version = await _active_version(session, obra_id)
        plan = ImportPlan(obra_code=obra.code, file_version=_text(about.get("Versão")) or None)
        await _marks_sheet(session, obra_id, version, wb, plan)
        await _pieces_sheet(session, obra_id, version, wb, plan)
    finally:
        wb.close()
    levels = {
        p.id: p.level
        for p in await session.scalars(
            select(ParamDef).where(
                ParamDef.id.in_({c.def_id for c in [*plan.fills, *plan.changes]})
            )
        )
    }
    plan.params = _summaries(plan, levels)
    return plan


async def apply(
    session: AsyncSession,
    obra_id: int,
    content: bytes,
    *,
    overwrite: bool,
    fingerprint: str,
    actor: User,
) -> tuple[ImportPlan, ImportResult]:
    """Recalcula a prévia e grava (sem commit aqui). 409 se mudou desde a prévia."""
    plan = await build_plan(session, obra_id, content)
    if plan.fingerprint != fingerprint:
        raise ConflictError(
            "Os valores da obra mudaram desde a prévia (alguém gravou agora). Confira de novo."
        )
    if plan.plannix is not None:
        from app.services import plannix_import

        return plan, await plannix_import.apply(session, obra_id, plan, actor)
    marks, units = plan.values_for(overwrite)
    if not marks and not units:
        raise ValidationError("Nada para gravar: o arquivo não traz valores novos.")
    mode = BatchMode.OVERWRITE if overwrite else BatchMode.ONLY_EMPTY
    batch = uuid.uuid4()
    rm = await mark_batch.apply_values(
        session, obra_id, marks, mode, actor, source=SOURCE, batch=batch
    )
    ru = await piece_values.apply_values(
        session, obra_id, units, mode, actor, source=SOURCE, batch=batch
    )
    changed = rm.fields_changed + ru.fields_changed
    return plan, ImportResult(
        batch if changed else None, rm.marks_changed, ru.units_changed, changed
    )
