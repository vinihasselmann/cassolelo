"""Importação da planilha do Plannix (decisões de 2026-11-24, docs/plannix.md).

O Plannix (sistema de produção da fábrica) exporta uma planilha com UMA LINHA POR PEÇA
FÍSICA. A importação preenche, por peça, as datas das etapas de produção:

    Data CD → Corte e dobra    Data AR → Armação           Data FO → Forma
    Data FA → Forma e armação  Data CO → Concretagem       Data Aca → Acabamento

Os 6 parâmetros são da biblioteca, por peça, do tipo data e com origem "plannix": só esta
importação grava neles (na tela ficam só leitura). Faltando algum, a importação o cria e o
inclui na obra.

Ligação da linha à peça do app:
- obra: a coluna "Sigla" tem de ser o código da obra;
- linhas com "Status de Projeto" vazio são peças recusadas na produção: ficam de fora;
- marca: o prefixo mais longo de "Peça" (cortando em "-" ou espaço) que existe na versão
  ativa ("LA3008-LP15 7X9,5-75%-125" → LA3008; "P-06" → P-06); a mesma marca em duas
  categorias é erro;
- peça: pelo "Código" do Plannix, se uma importação anterior já o guardou na unidade; senão
  "Seq." n/total → unidade n da marca (PP301 13/20 → PP301-13), e o Código fica guardado;
- quantidade diferente entre o Plannix e o modelo: liga assim mesmo e avisa "conferir";
  linha sem peça no modelo (n maior que as peças, unidade já tomada) fica de fora;
- "Seq." que o Excel converteu em data: formato dia/mês → n = dia, total = mês; formato
  mês/ano → n = mês, total = ano (dois dígitos).

Gravação: o Plannix manda nesses campos. Sobrescreve sempre e célula vazia APAGA (a peça
refeita depois de uma recusa chega sem datas). Um lote só, com "Desfazer" dos valores e
auditoria com `"source": "plannix"`; os Códigos guardados ficam (auditados no mesmo lote).
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from collections import Counter, defaultdict
from collections.abc import Container
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Element, Mark, Obra, ParamDef, PieceUnit, PieceUnitLink, PieceValue, User
from app.models.enums import ParamLevel, ParamScope, ParamSource, ParamType
from app.services import audit, param_defs, piece_values
from app.services.errors import ValidationError
from app.services.excel_import import (
    ABOUT_SHEET,
    MAX_ROWS,
    Change,
    ImportPlan,
    ImportResult,
    Issue,
    ParamSummary,
    _active_version,
    _applies,
    _raw,
    _text,
)
from app.services.mark_batch import BatchMode
from app.services.mark_values import _filled, normalize

SHEET = "Plannix"
SOURCE = "plannix"

# coluna do Plannix (sem acento/caixa) → parâmetro do app, na ordem das etapas
STAGES: tuple[tuple[str, str], ...] = (
    ("data cd", "Corte e dobra"),
    ("data ar", "Armação"),
    ("data fo", "Forma"),
    ("data fa", "Forma e armação"),
    ("data co", "Concretagem"),
    ("data aca", "Acabamento"),
)
COL_CODE, COL_PIECE, COL_SIGLA, COL_SEQ, COL_STATUS = (
    "codigo",
    "peca",
    "sigla",
    "seq.",
    "status de projeto",
)
REQUIRED = (COL_CODE, COL_PIECE, COL_SIGLA, COL_SEQ, COL_STATUS)

_SEQ = re.compile(r"^\s*(\d+)\s*/\s*(\d+)\s*$")
_MARK_END = re.compile(r"[-\s]")


# --------------------------------------------------------------------------- leitura


def _key(value: Any) -> str:
    """Cabeçalho comparável: sem acento, sem caixa, espaços simples ("Código" → "codigo")."""
    text = unicodedata.normalize("NFKD", _text(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.casefold().split())


def _code(value: Any) -> str:
    """Número do Excel sem ".0" (Código 22781092525, Sigla 9480)."""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return _text(value)


def mark_candidates(piece: str) -> list[str]:
    """Prefixos de "Peça" que podem ser a marca, do mais longo ao mais curto, cortando em
    "-" ou espaço: "LA3008-LP15 7X9,5" → ["LA3008-LP15 7X9,5", "LA3008-LP15", "LA3008"]."""
    text = " ".join(piece.split()).upper()  # marks.code é trim + maiúsculas
    out = [text]
    for m in reversed(list(_MARK_END.finditer(text))):
        prefix = text[: m.start()].strip()
        if prefix and prefix not in out:
            out.append(prefix)
    return out


def mark_code(piece: str, known: Container[str] = ()) -> str:
    """Marca da linha: o prefixo mais longo que existe no modelo (`known`), para valer
    tanto "LA3008-LP15 7X9,5-75%-125 /R" → LA3008 quanto "P-06" → P-06. Nenhum no modelo:
    o mais curto (antes do 1º "-" ou espaço)."""
    candidates = mark_candidates(piece)
    return next((c for c in candidates if c in known), candidates[-1])


def parse_seq(value: Any, number_format: str | None) -> tuple[int, int] | None:
    """ "n/total" → (n, total). O Excel converte "1/2" em 01/fev (formato dia/mês) e "1/36"
    em jan/1936 (formato mês/ano): a conversão se desfaz pelo formato da célula."""
    if isinstance(value, datetime | date):
        if "y" in (number_format or "").casefold():
            n, total = value.month, value.year % 100
        else:
            n, total = value.day, value.month
    else:
        m = _SEQ.match(_text(value))
        if m is None:
            return None
        n, total = int(m[1]), int(m[2])
    return (n, total) if n >= 1 and total >= 1 else None


def _find_sheet(wb: Any) -> tuple[Any, dict[str, int]] | None:
    for ws in wb.worksheets:
        header = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), ())
        cols: dict[str, int] = {}
        for i, v in enumerate(header):
            if v is not None:
                cols.setdefault(_key(v), i)
        if all(c in cols for c in REQUIRED):
            return ws, cols
    return None


def is_plannix(wb: Any) -> bool:
    """Planilha do Plannix: sem a aba "Sobre" do export e com Código, Peça, Sigla, Seq."""
    return ABOUT_SHEET not in wb.sheetnames and _find_sheet(wb) is not None


@dataclass
class _Row:
    row_no: int
    code: str  # Código do Plannix (único por peça física)
    piece: str  # "Peça" como está no Plannix
    mark: str
    label: str  # "PP301 13/20" para as mensagens
    seq: tuple[int, int] | None
    dates: dict[str, Any]  # parâmetro → célula
    unit: PieceUnit | None = None
    done: bool = False


# --------------------------------------------------------------------------- resultado


@dataclass(frozen=True)
class MarkCheck:
    code: str
    plannix: int  # linhas da marca no Plannix (sem as recusadas)
    model: int  # peças da marca na versão ativa


@dataclass
class PlannixInfo:
    rows: int = 0  # linhas de peça lidas (sem as recusadas)
    rejected: int = 0  # "Status de Projeto" vazio: peça recusada
    linked: int = 0  # linhas ligadas a uma peça do app
    leftovers: int = 0  # linhas sem peça no modelo
    new_links: dict[int, str] = field(default_factory=dict)  # unit_id → Código
    new_params: list[str] = field(default_factory=list)  # a criar na biblioteca
    include: list[int] = field(default_factory=list)  # da biblioteca, a incluir na obra
    params: dict[str, ParamDef] = field(default_factory=dict)  # já existentes, por nome
    check_marks: list[MarkCheck] = field(default_factory=list)
    outside_model: list[tuple[str, int]] = field(default_factory=list)  # marca, linhas
    values: dict[int, dict[str, Any]] = field(default_factory=dict)  # unit_id → {nome: valor}


# --------------------------------------------------------------------------- prévia


async def _stage_params(
    session: AsyncSession, obra_id: int
) -> tuple[dict[str, ParamDef], list[int], list[str]]:
    """Parâmetros das etapas: existentes (por nome), a incluir na obra e a criar."""
    included = await param_defs.included_ids(session, obra_id)
    existing: dict[str, ParamDef] = {}
    include: list[int] = []
    missing: list[str] = []
    for _, name in STAGES:
        found = list(
            await session.scalars(
                select(ParamDef).where(
                    ParamDef.active.is_(True),
                    func.lower(ParamDef.name) == name.casefold(),
                    or_(ParamDef.scope == ParamScope.GLOBAL.value, ParamDef.obra_id == obra_id),
                )
            )
        )
        manual = [p for p in found if p.source != ParamSource.PLANNIX.value]
        if manual:
            where = "na biblioteca" if manual[0].scope == ParamScope.GLOBAL.value else "na obra"
            raise ValidationError(
                f'Já existe o parâmetro "{manual[0].name}" criado à mão ({where}). '
                "Renomeie ou exclua-o para importar o Plannix."
            )
        if not found:
            missing.append(name)
            continue
        p = found[0]
        if p.level != ParamLevel.PIECE.value or p.type != ParamType.DATE.value:
            raise ValidationError(
                f'O parâmetro "{p.name}" do Plannix tem de ser por peça e do tipo data.'
            )
        existing[name] = p
        if p.scope == ParamScope.GLOBAL.value and p.id not in included:
            include.append(p.id)
    return existing, include, missing


def _read_rows(
    ws: Any, cols: dict[str, int], obra: Obra, plan: ImportPlan, info: PlannixInfo
) -> list[_Row]:
    stages = [(cols[key], name) for key, name in STAGES if key in cols]
    if not stages:
        raise ValidationError("A planilha do Plannix não tem as colunas de datas (Data CD, AR…).")
    rows: list[_Row] = []
    siglas: Counter[str] = Counter()
    seen_codes: dict[str, int] = {}
    for row_no, cells in enumerate(ws.iter_rows(min_row=2), start=2):
        if row_no > MAX_ROWS + 1:
            raise ValidationError(f"A planilha tem linhas demais (máximo {MAX_ROWS}).")

        def cell(i: int, cells: Any = cells) -> Any:
            return cells[i].value if i < len(cells) else None

        piece = _text(cell(cols[COL_PIECE]))
        if not piece:
            continue
        sigla = _code(cell(cols[COL_SIGLA]))
        if sigla:
            siglas[sigla] += 1
        if not _text(cell(cols[COL_STATUS])):
            info.rejected += 1  # peça recusada na produção
            continue
        info.rows += 1
        code = _code(cell(cols[COL_CODE]))
        seq_cell = cells[cols[COL_SEQ]] if cols[COL_SEQ] < len(cells) else None
        seq = (
            parse_seq(seq_cell.value, getattr(seq_cell, "number_format", None))
            if seq_cell is not None
            else None
        )
        mark = mark_code(piece)
        label = f"{mark} {seq[0]}/{seq[1]}" if seq else mark
        r = _Row(row_no, code, piece, mark, label, seq, {name: cell(i) for i, name in stages})
        if not code:
            plan.errors.append(Issue(SHEET, row_no, "Código", f"{label}: linha sem Código."))
            r.done = True
        elif code in seen_codes:
            plan.errors.append(
                Issue(
                    SHEET,
                    row_no,
                    "Código",
                    f"O Código {code} aparece de novo (linha {seen_codes[code]}).",
                )
            )
            r.done = True
        else:
            seen_codes[code] = row_no
        rows.append(r)
    wanted = obra.code.strip().casefold()
    if siglas and wanted not in {s.casefold() for s in siglas}:
        other = siglas.most_common(1)[0][0]
        raise ValidationError(f"Esta planilha do Plannix é da obra {other}, não da {obra.code}.")
    others = sorted(s for s in siglas if s.casefold() != wanted)
    if others:
        raise ValidationError(
            f"A planilha tem peças de outras obras (Sigla {', '.join(others)}): "
            f"exporte do Plannix só a obra {obra.code}."
        )
    return rows


async def build_plan(session: AsyncSession, obra: Obra, wb: Any) -> ImportPlan:
    """Lê a planilha do Plannix e compara com o app. Não grava nada."""
    found = _find_sheet(wb)
    if found is None:  # is_plannix() já conferiu
        raise ValidationError("Planilha do Plannix não reconhecida.")
    ws, cols = found
    plan = ImportPlan(obra_code=obra.code, file_version=None)
    info = PlannixInfo()
    plan.plannix = info
    rows = _read_rows(ws, cols, obra, plan, info)
    plan.pieces_rows = info.rows
    info.params, info.include, info.new_params = await _stage_params(session, obra.id)
    version = await _active_version(session, obra.id)

    # marcas e unidades ligadas na versão ativa
    by_code: dict[str, list[Mark]] = defaultdict(list)
    for m in await session.scalars(
        select(Mark)
        .where(Mark.obra_id == obra.id)
        .where(Mark.id.in_(select(Element.mark_id).where(Element.version_id == version.id)))
        .order_by(Mark.category)
    ):
        by_code[m.code].append(m)
    linked: dict[int, dict[int, PieceUnit]] = defaultdict(dict)  # mark_id → número → unidade
    for u in await session.scalars(
        select(PieceUnit)
        .join(PieceUnitLink, PieceUnitLink.unit_id == PieceUnit.id)
        .where(PieceUnitLink.version_id == version.id)
    ):
        linked[u.mark_id][u.number] = u
    linked_ids = {u.id for units in linked.values() for u in units.values()}
    by_plannix = {
        u.plannix_code: u
        for u in await session.scalars(
            select(PieceUnit).where(
                PieceUnit.obra_id == obra.id, PieceUnit.plannix_code.is_not(None)
            )
        )
        if u.plannix_code
    }
    all_marks = {
        m.id: m
        for m in await session.scalars(
            select(Mark).where(Mark.id.in_({u.mark_id for u in by_plannix.values()}))
        )
    }
    current: dict[tuple[int, int], Any] = {}
    if info.params and linked_ids:
        for v in await session.scalars(
            select(PieceValue).where(
                PieceValue.unit_id.in_(linked_ids),
                PieceValue.def_id.in_([p.id for p in info.params.values()]),
            )
        ):
            if _filled(v.value):
                current[(v.unit_id, v.def_id)] = v.value

    def error(r: _Row, column: str, message: str) -> None:
        plan.errors.append(Issue(SHEET, r.row_no, column, message))

    def warn(r: _Row | None, column: str | None, message: str) -> None:
        plan.warnings.append(Issue(SHEET, r.row_no if r else None, column, message))

    groups: dict[str, list[_Row]] = defaultdict(list)
    for r in rows:
        r.mark = mark_code(r.piece, by_code)
        r.label = f"{r.mark} {r.seq[0]}/{r.seq[1]}" if r.seq else r.mark
        groups[r.mark].append(r)
    claimed: set[int] = set()
    for code in sorted(groups):
        group = groups[code]
        found_marks = by_code.get(code, [])
        if not found_marks:
            info.outside_model.append((code, len(group)))
            continue
        if len(found_marks) > 1:
            cats = ", ".join(m.category for m in found_marks)
            for r in group:
                if not r.done:
                    error(r, "Peça", f"{code} existe em mais de uma categoria no modelo ({cats}).")
            continue
        mark = found_marks[0]
        units = linked.get(mark.id, {})
        if len(group) != len(units):
            info.check_marks.append(MarkCheck(code, len(group), len(units)))
            warn(
                None,
                "Peça",
                f"Conferir {code}: {len(group)} no Plannix, {len(units)} no modelo.",
            )
        # 1º: pelo Código guardado numa importação anterior
        for r in group:
            known = by_plannix.get(r.code) if not r.done else None
            if known is None:
                continue
            r.done = True
            label = piece_values.unit_label(all_marks.get(known.mark_id, mark), known)
            if known.mark_id != mark.id:
                error(r, "Peça", f"{r.label}: o Código {r.code} está ligado à peça {label}.")
            elif known.id not in linked_ids:
                warn(r, "Peça", f"{r.label}: a peça {label} não está na versão ativa.")
                info.leftovers += 1
            else:
                r.unit = known
                claimed.add(known.id)
        # 2º: pela Seq. n/total → unidade n
        for r in group:
            if r.done:
                continue
            if r.seq is None:
                error(r, "Seq.", f"{r.label}: Seq. inválida (use n/total, ex.: 13/20).")
                continue
            slot = units.get(r.seq[0])
            if slot is None:
                warn(r, "Seq.", f"{r.label}: o modelo tem {len(units)} peças; ficou sem peça.")
                info.leftovers += 1
                continue
            label = piece_values.unit_label(mark, slot)
            if slot.id in claimed or (slot.plannix_code and slot.plannix_code != r.code):
                other = f" (Código {slot.plannix_code})" if slot.plannix_code else ""
                warn(r, "Seq.", f"{r.label}: {label} já está ligada a outra linha{other}.")
                info.leftovers += 1
                continue
            r.unit = slot
            claimed.add(slot.id)
            info.new_links[slot.id] = r.code

        # datas das peças ligadas
        for r in group:
            if r.unit is None:
                continue
            u = r.unit
            info.linked += 1
            label = piece_values.unit_label(mark, u)
            for name, raw in r.dates.items():
                param = info.params.get(name)
                filled = _filled(raw if not isinstance(raw, str) else raw.strip())
                if param is not None and not _applies(param, mark.category):
                    if filled:
                        error(r, name, f'"{name}" não vale para a categoria {mark.category}.')
                    continue
                check = param or ParamDef(name=name, type=ParamType.DATE.value)
                try:
                    new = normalize(check, _raw(check, raw)) if filled else None
                except ValidationError as exc:
                    error(r, name, f"{label} · {name}: {exc.message}")
                    continue
                old = current.get((u.id, param.id)) if param is not None else None
                if old == new:
                    if new is not None:
                        plan.unchanged += 1
                    continue
                change = Change(
                    SHEET, r.row_no, label, mark.category, name, param.id if param else 0, old, new
                )
                (plan.fills if change.is_fill else plan.changes).append(change)
                info.values.setdefault(u.id, {})[name] = new

    plan.params = _summaries(plan, info)
    plan.fingerprint_extra = [
        *(f"link:{uid}:{code}" for uid, code in sorted(info.new_links.items())),
        *(f"new:{name}" for name in info.new_params),
        *(f"include:{def_id}" for def_id in info.include),
    ]
    return plan


def _summaries(plan: ImportPlan, info: PlannixInfo) -> list[ParamSummary]:
    counts: dict[str, list[int]] = {}
    for c in [*plan.fills, *plan.changes]:
        entry = counts.setdefault(c.param, [0, 0])
        entry[0 if c.is_fill else 1] += 1
    out = []
    for _, name in STAGES:
        if name in counts:
            p = info.params.get(name)
            fills, changes = counts[name]
            out.append(ParamSummary(p.id if p else 0, name, ParamLevel.PIECE.value, fills, changes))
    return out


# --------------------------------------------------------------------------- gravação


async def apply(session: AsyncSession, obra_id: int, plan: ImportPlan, actor: User) -> ImportResult:
    """Cria/inclui os parâmetros, guarda os Códigos e grava as datas (sem commit aqui)."""
    info: PlannixInfo = plan.plannix
    if not info.values and not info.new_links:
        raise ValidationError("Nada para gravar: a planilha não traz datas novas.")
    batch = uuid.uuid4()
    defs = dict(info.params)
    for def_id in info.include:
        await param_defs.include_param(session, obra_id, def_id, actor)
    for name in info.new_params:
        defs[name] = await param_defs.create_param(
            session,
            param_defs.ParamDefInput(
                name=name,
                type=ParamType.DATE.value,
                level=ParamLevel.PIECE.value,
                scope=ParamScope.GLOBAL.value,
                include_in_obra_id=obra_id,
                source=ParamSource.PLANNIX.value,
                required=True,  # contam no status (decisão de 2026-11-24)
            ),
            actor,
        )
    if info.new_links:
        units = list(
            await session.scalars(select(PieceUnit).where(PieceUnit.id.in_(list(info.new_links))))
        )
        marks = {
            m.id: m
            for m in await session.scalars(
                select(Mark).where(Mark.id.in_({u.mark_id for u in units}))
            )
        }
        for u in units:
            before, u.plannix_code = u.plannix_code, info.new_links[u.id]
            u.updated_by = actor.id
            label = piece_values.unit_label(marks[u.mark_id], u)
            await audit.record(
                session,
                "piece_unit",
                u.id,
                "plannix_link",
                {"unit": label, "plannix_code": before},
                {"unit": label, "plannix_code": u.plannix_code, "source": SOURCE},
                actor,
                batch,
            )
        await session.flush()
    values = {
        uid: {defs[name].id: v for name, v in fields.items()} for uid, fields in info.values.items()
    }
    result = await piece_values.apply_values(
        session, obra_id, values, BatchMode.OVERWRITE, actor, source=SOURCE, batch=batch
    )
    return ImportResult(
        batch if result.fields_changed else None,
        0,
        result.units_changed,
        result.fields_changed,
    )
