from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.auth import CurrentUser
from app.db import SessionDep
from app.models import ModelVersion, Obra
from app.models.enums import ParamType, VersionStatus
from app.services import (
    colors,
    filters,
    mark_candidates,
    mark_rule,
    mark_status,
    mark_validation,
    review,
    search,
    version_data,
)
from app.services.errors import NotFoundError, ValidationError

router = APIRouter(prefix="/versions", tags=["versions"])


class ReportNotReadyError(NotFoundError):
    code = "report_not_ready"


class VersionReportOut(BaseModel):
    version_id: int
    status: VersionStatus
    updated_at: datetime
    report: dict[str, Any]


@router.get("/{version_id}/report", response_model=VersionReportOut)
async def get_report(version_id: int, session: SessionDep, _user: CurrentUser) -> VersionReportOut:
    """Relatório de validação de marcas. Leitura para todos os papéis; o painel da aba
    Versões é mostrado para projetos/admin."""
    version = await session.get(ModelVersion, version_id)
    if version is None:
        raise NotFoundError("Versão não encontrada.")
    row = await mark_validation.get_report(session, version_id)
    if row is None:
        raise ReportNotReadyError(
            "O relatório de validação desta versão ainda não foi gerado "
            "(ele sai quando o processamento termina)."
        )
    return VersionReportOut(
        version_id=version_id,
        status=VersionStatus(version.status),
        updated_at=row.updated_at,
        report=row.report,
    )


class MarkOut(BaseModel):
    mark_id: int
    code: str
    category: str
    count: int
    dbids: list[int]
    member_dbids: list[int] = []  # membros: o clique neles acha a marca


class PropertyOut(BaseModel):
    name: str
    value: Any


class PropertyGroupOut(BaseModel):
    name: str
    properties: list[PropertyOut]


class ElementOut(BaseModel):
    dbid: int
    external_id: str | None
    name: str | None
    category: str | None
    mark_raw: str | None
    mark: MarkOut | None
    groups: list[PropertyGroupOut]


@router.get("/{version_id}/marks", response_model=list[MarkOut])
async def list_marks(version_id: int, session: SessionDep, _user: CurrentUser) -> list[MarkOut]:
    """Marcas da versão (código, categoria, quantidade e dbIds das peças).
    O Viewer seleciona a marca inteira com estes dbIds."""
    marks = await version_data.list_marks(session, version_id)
    return [MarkOut(**m.__dict__) for m in marks]


@router.get("/{version_id}/elements/{dbid}", response_model=ElementOut)
async def get_element(
    version_id: int, dbid: int, session: SessionDep, _user: CurrentUser
) -> ElementOut:
    """Uma peça com todas as propriedades do modelo, agrupadas (somente leitura)."""
    el = await version_data.get_element(session, version_id, dbid)
    return ElementOut(
        dbid=el.dbid,
        external_id=el.external_id,
        name=el.name,
        category=el.category,
        mark_raw=el.mark_raw,
        mark=MarkOut(**el.mark.__dict__) if el.mark else None,
        groups=[PropertyGroupOut.model_validate(g) for g in el.groups],
    )


class SearchOut(BaseModel):
    total_marks: int
    total_pieces: int
    page: int
    page_size: int
    items: list[MarkOut]
    mark_ids: list[int]
    dbids: list[int]
    note: str | None


class FacetValue(BaseModel):
    value: str
    pieces: int


class FacetsOut(BaseModel):
    categories: list[FacetValue]
    levels: list[FacetValue]
    pieces_without_level: int


def parse_prop(raw: str) -> tuple[str, str]:
    name, sep, value = raw.partition("=")
    if not sep or not name.strip():
        raise ValidationError(f'Filtro de propriedade inválido: "{raw}" (use Nome=valor).')
    return name.strip(), value.strip()


@router.get("/{version_id}/marks/search", response_model=SearchOut)
async def search_marks(
    version_id: int,
    request: Request,
    session: SessionDep,
    _user: CurrentUser,
    q: str = "",
    category: Annotated[list[str], Query()] = [],  # noqa: B006 (padrão do FastAPI)
    level: Annotated[list[str], Query()] = [],  # noqa: B006
    prop: Annotated[list[str], Query(description="Nome=valor")] = [],  # noqa: B006
    missing: Annotated[str | None, Query(description="sem <parâmetro>")] = None,
    shortcut: search.Shortcut = search.Shortcut.ALL,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=search.MAX_PAGE_SIZE)] = 50,
    order: Literal["asc", "desc"] = "asc",
) -> SearchOut:
    """Busca marcas da versão. Itens paginados e ordenados pela marca; `mark_ids` e
    `dbids` trazem o resultado inteiro (para o 3D destacar todas as peças)."""
    params = search.SearchParams(
        q=q.strip(),
        categories=category,
        levels=level,
        props=[parse_prop(p) for p in prop],
        missing=missing.strip() if missing and missing.strip() else None,
        shortcut=shortcut,
        page=page,
        page_size=page_size,
        order=order,
        today=filters.today(request.app.state.settings.display_timezone),
    )
    r = await search.search_marks(session, version_id, params)
    return SearchOut(
        total_marks=r.total_marks,
        total_pieces=r.total_pieces,
        page=r.page,
        page_size=r.page_size,
        items=[MarkOut(**m.__dict__) for m in r.items],
        mark_ids=r.mark_ids,
        dbids=r.dbids,
        note=r.note,
    )


@router.get("/{version_id}/marks/facets", response_model=FacetsOut)
async def marks_facets(version_id: int, session: SessionDep, _user: CurrentUser) -> FacetsOut:
    """Categorias e níveis da versão, com o número de peças com marca."""
    f = await search.facets(session, version_id)
    return FacetsOut(
        categories=[FacetValue(value=v, pieces=n) for v, n in f.categories],
        levels=[FacetValue(value=v, pieces=n) for v, n in f.levels],
        pieces_without_level=f.pieces_without_level,
    )


# ------------------------------------------------------------------ status e progresso (6.4)


class MarkStatusItem(BaseModel):
    mark_id: int
    status: mark_status.MarkStatus


class StatusCount(BaseModel):
    status: mark_status.MarkStatus
    marks: int
    pieces: int


class MarkStatusOut(BaseModel):
    items: list[MarkStatusItem]
    counts: list[StatusCount]  # pending, partial, complete, review (nessa ordem)


@router.get("/{version_id}/marks/status", response_model=MarkStatusOut)
async def get_mark_status(
    version_id: int, session: SessionDep, _user: CurrentUser
) -> MarkStatusOut:
    """Status de produção de cada marca da versão (calculado; "review" só na Fase 7)."""
    r = await mark_status.version_statuses(session, version_id)
    return MarkStatusOut(
        items=[MarkStatusItem(mark_id=k, status=v) for k, v in sorted(r.statuses.items())],
        counts=[
            StatusCount(status=s, marks=r.counts[s], pieces=r.pieces[s])
            for s in mark_status.MarkStatus
        ],
    )


class ParamProgressOut(BaseModel):
    def_id: int
    name: str
    marks_total: int
    marks_filled: int
    pieces_total: int
    pieces_filled: int
    level: str = "mark"  # "piece": parâmetro por peça (conta peça a peça)


class ProgressOut(BaseModel):
    marks: int
    pieces: int
    required: list[ParamProgressOut]


@router.get("/{version_id}/progress", response_model=ProgressOut)
async def get_progress(version_id: int, session: SessionDep, _user: CurrentUser) -> ProgressOut:
    """Progresso por parâmetro obrigatório: marcas e peças preenchidas / em que se aplica."""
    p = await mark_status.progress(session, version_id)
    return ProgressOut(
        marks=p.marks,
        pieces=p.pieces,
        required=[ParamProgressOut(**r.__dict__) for r in p.required],
    )


class MarkParamValue(BaseModel):
    mark_id: int
    value: Any  # nulo = sem valor


class ParamValuesOut(BaseModel):
    def_id: int
    name: str
    type: ParamType
    options: list[str] | None
    items: list[MarkParamValue]  # só as marcas em que o parâmetro se aplica


@router.get("/{version_id}/params/{def_id}/values", response_model=ParamValuesOut)
async def get_param_values(
    version_id: int, def_id: int, session: SessionDep, _user: CurrentUser
) -> ParamValuesOut:
    """Valor de um parâmetro da fábrica em cada marca da versão ("Colorir por parâmetro")."""
    r = await mark_status.param_values(session, version_id, def_id)
    return ParamValuesOut(
        def_id=r.param.id,
        name=r.param.name,
        type=ParamType(r.param.type),
        options=r.param.options,
        items=[MarkParamValue(mark_id=k, value=v) for k, v in sorted(r.values.items())],
    )


# ------------------------------------------------------------------ diff entre versões (7.2)


class UnitLabelOut(BaseModel):
    unit_id: int
    label: str


class UnitDiffOut(BaseModel):
    lost: int = 0  # unidades com valores que perderam a peça nesta versão
    new: int = 0  # unidades novas (peças a mais)
    returned: int = 0  # órfãs/arquivadas que voltaram pela chave
    by_order: int = 0  # ligadas pela ordem: conferir
    lost_units: list[UnitLabelOut] = []
    new_units: list[UnitLabelOut] = []
    orphans_open: int = 0  # unidades órfãs abertas da obra, agora


class VersionDiffOut(BaseModel):
    version_id: int
    version_number: int
    prev_version_id: int | None
    prev_version_number: int | None
    totals: dict[str, int]  # unchanged, count_changed, changed, new, removed
    review: int  # marcas que esta versão mandou para revisão
    orphans: int  # órfãs criadas por esta versão
    returned: int  # órfãs cujas marcas voltaram
    review_open: int  # marcas desta versão AINDA em revisão
    orphans_open: int  # órfãs abertas da obra, agora
    review_properties: list[str]
    marks: list[dict[str, Any]]  # marcas que não ficaram inalteradas
    units: UnitDiffOut  # parâmetros por peça (P5)


@router.get("/{version_id}/diff", response_model=VersionDiffOut)
async def get_diff(version_id: int, session: SessionDep, _user: CurrentUser) -> VersionDiffOut:
    """Comparação com a versão pronta anterior: totais por classe, marcas e o que foi feito."""
    view = await review.get_diff(session, version_id)
    d = view.diff
    return VersionDiffOut(
        version_id=view.version_id,
        version_number=view.version_number,
        prev_version_id=d.get("prev_version_id"),
        prev_version_number=d.get("prev_version_number"),
        totals=d.get("totals", {}),
        review=d.get("review", 0),
        orphans=d.get("orphans", 0),
        returned=d.get("returned", 0),
        review_open=view.review_open,
        orphans_open=view.orphans_open,
        review_properties=d.get("review_properties", []),
        marks=d.get("marks", []),
        units=UnitDiffOut(**d.get("units", {}), orphans_open=view.unit_orphans_open),
    )


class CandidateOut(BaseModel):
    name: str
    groups: list[str]
    pieces_with_value: int
    marks: int
    inconsistent_marks: int
    inconsistent_pieces: int
    unique_per_piece: bool  # quase um valor por peça (≥ 90%)
    constant: bool
    measure: bool  # número + unidade
    current: bool
    examples: list[tuple[str, int]]


class CandidatesOut(BaseModel):
    version_id: int
    pieces: int
    mark_property_names: list[str]
    dimensions_checked: bool  # False: o modelo não tem DIMENSION_PROPERTY_NAMES
    candidates: list[CandidateOut]


@router.get("/{version_id}/mark-candidates", response_model=CandidatesOut)
async def get_mark_candidates(
    version_id: int,
    request: Request,
    session: SessionDep,
    _user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> CandidatesOut:
    """Assistente: quais propriedades do modelo poderiam identificar as peças."""
    settings = request.app.state.settings
    version = await session.get(ModelVersion, version_id)
    if version is None:
        raise NotFoundError("Versão não encontrada.")
    obra = await session.get(Obra, version.obra_id)
    if obra is None:  # pragma: no cover - FK garante
        raise NotFoundError("Obra não encontrada.")
    rule = mark_rule.effective_rule(obra, settings)
    result = await mark_candidates.candidates(
        session,
        version_id,
        settings.dimension_property_list,
        settings.dimension_tolerance_mm,
        rule.mark_names,
        limit,
        excluded_names=rule.category_names,
    )
    return CandidatesOut(
        version_id=result.version_id,
        pieces=result.pieces,
        mark_property_names=rule.mark_names,
        dimensions_checked=result.dimensions_checked,
        candidates=[
            CandidateOut(
                name=c.name,
                groups=sorted(c.groups),
                pieces_with_value=c.pieces_with_value,
                marks=c.marks,
                inconsistent_marks=c.inconsistent_marks,
                inconsistent_pieces=c.inconsistent_pieces,
                unique_per_piece=c.unique_per_piece,
                constant=c.constant,
                measure=c.measure,
                current=c.current,
                examples=c.examples,
            )
            for c in result.candidates
        ],
    )


# ----------------------------------------------------------- motor de filtros


class FieldOut(BaseModel):
    source: Literal["model", "factory", "system"]
    key: str
    name: str
    group: str | None
    type: Literal["text", "number", "date", "bool"]
    distinct_values: int
    pieces: int


class FieldValueOut(BaseModel):
    value: str
    pieces: int


class MatchedPieceOut(BaseModel):
    dbid: int
    mark_id: int | None


class MarkGroupOut(BaseModel):
    mark_id: int | None
    code: str | None  # Nome da montagem; null = peças sem marca
    category: str
    matched: int  # peças que bateram
    total: int  # peças da marca nesta versão


class EvaluationOut(BaseModel):
    mode: str
    logic: str
    total_pieces: int
    matched_pieces: int
    matched_marks: int
    pieces: list[MatchedPieceOut]
    dbids: list[int]  # peças que bateram + todos os membros delas
    groups: list[MarkGroupOut]  # inclui marcas órfãs (matched 0) quando o filtro usa "Órfã"
    notes: list[str]  # avisos (ex.: primeira versão, sem anterior para "Nova na versão")
    view: Literal["isolate", "highlight"]  # 3D: só o resultado, ou o resto esmaecido
    hidden_dbids: list[int]  # com "highlight": peças fora das visíveis (ficam ocultas)


@router.get("/{version_id}/fields", response_model=list[FieldOut])
async def get_fields(version_id: int, session: SessionDep, _user: CurrentUser) -> list[FieldOut]:
    """Campos filtráveis: sistema, parâmetros da fábrica da obra e propriedades do modelo."""
    return [FieldOut(**f.__dict__) for f in await filters.list_fields(session, version_id)]


@router.get("/{version_id}/fields/{source}/{key:path}/values", response_model=list[FieldValueOut])
async def get_field_values(
    version_id: int,
    source: Literal["model", "factory", "system"],
    key: str,
    session: SessionDep,
    _user: CurrentUser,
    q: str = "",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[FieldValueOut]:
    """Valores do campo para autocompletar (mais comuns primeiro), com o nº de peças.
    A chave das propriedades do modelo é "<grupo>/<nome>" (pode conter "/")."""
    ref = filters.FieldRef(source=source, key=key)
    values = await filters.field_values(session, version_id, ref, q, limit)
    return [FieldValueOut(value=v.value, pieces=v.pieces) for v in values]


@router.post("/{version_id}/filter/evaluate", response_model=EvaluationOut)
async def evaluate_filter(
    version_id: int,
    body: filters.FilterDef,
    request: Request,
    session: SessionDep,
    _user: CurrentUser,
) -> JSONResponse:
    """Peças que batem no filtro, agrupadas por Nome da montagem. Leitura: todos os papéis
    (o app ainda não tem permissão por obra; a Fase 11 traz login e acesso por obra).

    A resposta (dezenas de milhares de peças) é montada direto em JSON, no formato de
    EvaluationOut: revalidar cada item custava mais que a consulta."""
    today = filters.today(request.app.state.settings.display_timezone)
    result = await filters.evaluate(session, version_id, body, today)
    return JSONResponse(
        {
            "mode": result.mode,
            "logic": result.logic,
            "total_pieces": result.total_pieces,
            "matched_pieces": result.matched_pieces,
            "matched_marks": result.matched_marks,
            "pieces": [{"dbid": p.dbid, "mark_id": p.mark_id} for p in result.pieces],
            "dbids": result.dbids,
            "groups": [g.__dict__ for g in result.groups],
            "notes": result.notes,
            "view": result.view,
            "hidden_dbids": result.hidden_dbids,
        }
    )


# ----------------------------------------------------------------- cores no 3D


class RuleResultOut(BaseModel):
    index: int
    label: str
    color: str
    filter_id: int | None
    matched: int  # peças que batem no filtro da regra
    pieces: int  # peças que ficaram com a cor desta regra
    dbids: list[int]  # essas peças (sem membros): clicar na legenda seleciona


class SchemeResultOut(BaseModel):
    colors: dict[int, str]  # dbId (peças e membros) -> "#RRGGBB"
    rules: list[RuleResultOut]
    total_pieces: int
    colored_pieces: int
    notes: list[str]


class LegendItemOut(BaseModel):
    label: str
    color: str
    pieces: int
    value: str | None = None
    min: float | str | None = None
    max: float | str | None = None
    dbids: list[int] = []  # peças do item (sem membros): clicar na legenda seleciona


class ColorizeOut(BaseModel):
    mode: Literal["distinct", "range"]
    field_name: str
    field_type: str
    colors: dict[int, str]
    legend: list[LegendItemOut]
    total_pieces: int


@router.post("/{version_id}/color-scheme/evaluate", response_model=SchemeResultOut)
async def evaluate_color_scheme(
    version_id: int,
    body: colors.SchemeEvaluateInput,
    request: Request,
    session: SessionDep,
    user: CurrentUser,
) -> JSONResponse:
    """Cor de cada peça pelo esquema (salvo ou em prévia): a PRIMEIRA regra que bate
    vence; os membros da peça recebem a mesma cor. Contagem por regra."""
    today = filters.today(request.app.state.settings.display_timezone)
    r = await colors.evaluate_scheme(session, version_id, body, user, today)
    return JSONResponse(
        {
            "colors": {str(k): v for k, v in r.colors.items()},
            "rules": [x.__dict__ for x in r.rules],
            "total_pieces": r.total_pieces,
            "colored_pieces": r.colored_pieces,
            "notes": r.notes,
        }
    )


@router.post("/{version_id}/colorize", response_model=ColorizeOut)
async def colorize_by_field(
    version_id: int, body: colors.ColorizeInput, session: SessionDep, _user: CurrentUser
) -> JSONResponse:
    """Coloração por campo: `distinct` (cor estável por valor; "Sem valor" em cinza) ou
    `range` (números e datas: 5 faixas com os limites)."""
    r = await colors.colorize(session, version_id, body)
    return JSONResponse(
        {
            "mode": r.mode,
            "field_name": r.field_name,
            "field_type": r.field_type,
            "colors": {str(k): v for k, v in r.colors.items()},
            "legend": [x.__dict__ for x in r.legend],
            "total_pieces": r.total_pieces,
        }
    )
