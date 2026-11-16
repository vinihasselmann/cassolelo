"""7.2 · Reconciliação aplicada na chegada da versão + revisão + órfãs.

Fixtures models/revisao_v1 → revisao_v2 (tests/make_revisao_fixture.py), processadas
pelo process_version de verdade (APS simulado). Casos plantados:
V-01 inalterada · PP002 movida/recriada · PP003 2→3 peças · PP001 seção 40x60→40x80 ·
PP004→PP004A renomeada · PP005 removida (com valores) · PP006 removida (sem valores) ·
PP007 nova.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.aps.client import ApsClient
from app.models import (
    AuditLog,
    Element,
    Mark,
    ModelVersion,
    Obra,
    Orphan,
    ParamDef,
    ParamValue,
    User,
    VersionDiff,
)
from app.models.enums import Role
from app.services import version_reconcile
from app.services.processing import ProcessingConfig, process_version
from tests.apsfakes import Sleeps, mock_model, mock_token
from tests.conftest import as_user

DIMS = ["SEÇÃO-Altura", "SEÇÃO-Largura", "PEÇA-Comprimento", "Comprimento", "Largura", "Altura"]
CONFIG = ProcessingConfig(
    mark_names=["Marca", "Mark"],
    category_names=["Category"],
    dimension_names=DIMS,
    level_names=["Nível base"],
    search_names=["Tipo"],
    review_names=["Seção"],
)


async def _process(
    session: AsyncSession, aps: ApsClient, sleeps: Sleeps, obra: Obra, n: int, fmt: str
) -> ModelVersion:
    urn = f"dXJucmV2{n}"
    with respx.mock:
        mock_token()
        mock_model(fmt, urn)
        v = await session.scalar(
            select(ModelVersion).where(
                ModelVersion.obra_id == obra.id, ModelVersion.version_number == n
            )
        )
        if v is None:
            v = ModelVersion(
                obra_id=obra.id, acc_version_id=f"urn:v:rev:{n}", version_number=n, urn=urn
            )
            session.add(v)
            await session.flush()
        result = await process_version(session, aps, v.id, CONFIG, sleep=sleeps)
    assert result is not None and result.status == "ready", result
    return v


async def _marks(session: AsyncSession, obra: Obra) -> dict[str, Mark]:
    rows = await session.scalars(select(Mark).where(Mark.obra_id == obra.id))
    return {m.code: m for m in rows}


@pytest.fixture
async def ctx(
    session: AsyncSession, aps: ApsClient, sleeps: Sleeps, users: dict[Role, User]
) -> dict[str, Any]:
    obra = Obra(code="OB-REV", name="Obra revisões")
    session.add(obra)
    await session.flush()
    v1 = await _process(session, aps, sleeps, obra, 1, "revisao_v1")
    forma = ParamDef(
        name="Tipo de forma",
        type="list",
        options=["F-11", "F-12", "F-13"],
        required=True,
        scope="obra",
        obra_id=obra.id,
    )
    obs = ParamDef(name="Obs", type="text", scope="obra", obra_id=obra.id, categories=["Viga"])
    session.add_all([forma, obs])
    await session.flush()
    marks = await _marks(session, obra)
    for code, value in (
        ("PP001", "F-11"),
        ("PP002", "F-11"),
        ("PP003", "F-12"),
        ("PP004", "F-12"),
        ("PP005", "F-13"),
    ):  # PP006 e V-01 sem valores
        session.add(ParamValue(mark_id=marks[code].id, def_id=forma.id, value=value))
    await session.flush()
    return {
        "obra": obra,
        "v1": v1,
        "forma": forma,
        "obs": obs,
        "aps": aps,
        "sleeps": sleeps,
        "users": users,
        "fab": as_user(users[Role.FABRICA]),
    }


async def _v2(session: AsyncSession, ctx: dict[str, Any]) -> ModelVersion:
    return await _process(session, ctx["aps"], ctx["sleeps"], ctx["obra"], 2, "revisao_v2")


async def _diff(client: httpx.AsyncClient, ctx: dict[str, Any], v: ModelVersion) -> Any:
    r = await client.get(f"/api/versions/{v.id}/diff", headers=ctx["fab"])
    assert r.status_code == 200, r.text
    return r.json()


# --------------------------------------------------------------------------- chegada


async def test_first_version_has_diff_without_previous(
    client: httpx.AsyncClient, ctx: dict[str, Any]
) -> None:
    body = await _diff(client, ctx, ctx["v1"])
    assert (body["prev_version_id"], body["totals"]["new"], body["marks"]) == (None, 7, [])
    assert (body["review"], body["orphans"]) == (0, 0)


async def test_arrival_classifies_the_seven_cases_and_acts(
    client: httpx.AsyncClient, session: AsyncSession, ctx: dict[str, Any]
) -> None:
    v2 = await _v2(session, ctx)
    body = await _diff(client, ctx, v2)
    assert body["prev_version_number"] == 1
    assert body["totals"] == {
        "unchanged": 2,  # V-01 (1) e PP002 movida/recriada (2, 3)
        "count_changed": 1,  # PP003 (4)
        "changed": 1,  # PP001 (5)
        "new": 2,  # PP004A (6) e PP007
        "removed": 3,  # PP004 (6), PP005 (7) e PP006
    }
    by_code = {m["code"]: m for m in body["marks"]}
    assert set(by_code) == {"PP001", "PP003", "PP004", "PP004A", "PP005", "PP006", "PP007"}
    assert (by_code["PP001"]["action"], by_code["PP001"]["note"]) == (
        "review",
        "Altura: 60.0 cm → 80.0 cm; Seção: 40x60 → 40x80",
    )
    assert (by_code["PP003"]["prev_count"], by_code["PP003"]["curr_count"]) == (2, 3)
    assert by_code["PP003"]["action"] is None  # só registra
    assert by_code["PP004"]["action"] == by_code["PP005"]["action"] == "orphan"
    assert (by_code["PP006"]["has_values"], by_code["PP006"]["action"]) == (False, None)
    assert (body["review"], body["orphans"], body["review_open"], body["orphans_open"]) == (
        1,
        2,
        1,
        2,
    )

    marks = await _marks(session, ctx["obra"])
    assert (marks["PP001"].review_status, marks["PP001"].review_note) == (
        "review",
        "Altura: 60.0 cm → 80.0 cm; Seção: 40x60 → 40x80",
    )
    assert all(m.review_status == "ok" for c, m in marks.items() if c != "PP001")
    orphans = {o.mark_id: o.status for o in await session.scalars(select(Orphan))}
    assert orphans == {marks["PP004"].id: "open", marks["PP005"].id: "open"}
    audit_rows = await session.scalars(
        select(AuditLog.action).where(
            AuditLog.entity.in_(["mark", "orphan"]), AuditLog.action != "create"
        )
    )
    assert sorted(audit_rows) == ["review"]


async def test_no_value_disappears_without_going_through_the_orphan_queue(
    session: AsyncSession, ctx: dict[str, Any]
) -> None:
    v2 = await _v2(session, ctx)
    marks = await _marks(session, ctx["obra"])
    with_values = await version_reconcile.marks_with_values(session, [m.id for m in marks.values()])
    in_v2 = set(
        await session.scalars(
            select(Element.mark_id).where(Element.version_id == v2.id, Element.mark_id.is_not(None))
        )
    )
    open_orphans = set(await session.scalars(select(Orphan.mark_id).where(Orphan.status == "open")))
    assert with_values  # o teste tem valores
    assert with_values <= in_v2 | open_orphans
    # e os valores das removidas continuam gravados
    n = await session.scalar(
        select(func.count()).where(ParamValue.mark_id.in_([marks["PP004"].id, marks["PP005"].id]))
    )
    assert n == 2


async def test_new_pieces_of_existing_mark_inherit_values(
    client: httpx.AsyncClient, session: AsyncSession, ctx: dict[str, Any]
) -> None:
    v2 = await _v2(session, ctx)
    r = await client.get(
        f"/api/versions/{v2.id}/marks/search", params={"q": "F-12"}, headers=ctx["fab"]
    )
    items = {i["code"]: i["dbids"] for i in r.json()["items"]}
    assert items == {"PP003": [14, 15, 16]}  # a peça 16 é nova e já aparece com F-12


async def test_status_and_shortcuts_after_arrival(
    client: httpx.AsyncClient, session: AsyncSession, ctx: dict[str, Any]
) -> None:
    v2 = await _v2(session, ctx)
    marks = await _marks(session, ctx["obra"])
    status = (await client.get(f"/api/versions/{v2.id}/marks/status", headers=ctx["fab"])).json()
    assert {i["mark_id"]: i["status"] for i in status["items"]}[marks["PP001"].id] == "review"
    review_count = next(c for c in status["counts"] if c["status"] == "review")
    assert (review_count["marks"], review_count["pieces"]) == (1, 2)

    async def codes(shortcut: str) -> list[str]:
        r = await client.get(
            f"/api/versions/{v2.id}/marks/search", params={"shortcut": shortcut}, headers=ctx["fab"]
        )
        return [i["code"] for i in r.json()["items"]]

    assert await codes("review") == ["PP001"]
    assert await codes("new") == ["PP004A", "PP007"]
    assert await codes("orphans") == ["PP004", "PP005"]


async def test_reprocessing_is_idempotent(session: AsyncSession, ctx: dict[str, Any]) -> None:
    v2 = await _v2(session, ctx)
    await _process(session, ctx["aps"], ctx["sleeps"], ctx["obra"], 2, "revisao_v2")
    assert await session.scalar(select(func.count(Orphan.id))) == 2
    assert (
        await session.scalar(
            select(func.count(VersionDiff.id)).where(VersionDiff.version_id == v2.id)
        )
        == 1
    )


async def test_mark_that_comes_back_closes_its_orphan(
    client: httpx.AsyncClient, session: AsyncSession, ctx: dict[str, Any]
) -> None:
    await _v2(session, ctx)
    v3 = await _process(session, ctx["aps"], ctx["sleeps"], ctx["obra"], 3, "revisao_v1")
    body = await _diff(client, ctx, v3)
    assert body["returned"] == 2 and body["orphans_open"] == 0
    statuses = sorted(o.status for o in await session.scalars(select(Orphan)))
    assert statuses == ["returned", "returned"]


async def test_failure_in_reconcile_rolls_back_everything(
    session: AsyncSession, ctx: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def boom(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("falha simulada")

    monkeypatch.setattr(version_reconcile, "apply", boom)
    obra_id = ctx["obra"].id
    urn = "dXJucmV2Mg"
    v2 = ModelVersion(obra_id=obra_id, acc_version_id="urn:v:rev:x", version_number=2, urn=urn)
    session.add(v2)
    await session.flush()
    with respx.mock:
        mock_token()
        mock_model("revisao_v2", urn)
        result = await process_version(session, ctx["aps"], v2.id, CONFIG, sleep=ctx["sleeps"])
    assert result is not None and result.status == "failed"
    v2_id = v2.id
    count = select(func.count(Element.id)).where(Element.version_id == v2_id)
    assert await session.scalar(count) == 0
    assert await session.scalar(select(func.count(Orphan.id))) == 0
    codes = set(await session.scalars(select(Mark.code).where(Mark.obra_id == obra_id)))
    assert "PP007" not in codes  # nem as marcas novas ficaram


# --------------------------------------------------------------------------- revisão


async def test_keep_values_clears_review_and_audits(
    client: httpx.AsyncClient, session: AsyncSession, ctx: dict[str, Any]
) -> None:
    await _v2(session, ctx)
    pp001 = (await _marks(session, ctx["obra"]))["PP001"]
    r = await client.post(
        f"/api/marks/{pp001.id}/review/keep", headers=as_user(ctx["users"][Role.LEITURA])
    )
    assert r.status_code == 403
    values = await client.get(
        f"/api/obras/{ctx['obra'].id}/marks/{pp001.id}/values", headers=ctx["fab"]
    )
    assert values.json()["mark"]["review_status"] == "review"
    assert values.json()["mark"]["review_note"].endswith("Seção: 40x60 → 40x80")

    r = await client.post(f"/api/marks/{pp001.id}/review/keep", headers=ctx["fab"])
    assert r.status_code == 200, r.text
    assert (r.json()["review_status"], r.json()["review_note"]) == ("ok", None)
    entry = await session.scalar(
        select(AuditLog).where(AuditLog.entity == "mark", AuditLog.action == "review_keep")
    )
    assert entry is not None and entry.before and entry.before["review_note"].startswith("Altura")
    again = await client.post(f"/api/marks/{pp001.id}/review/keep", headers=ctx["fab"])
    assert again.status_code == 409


async def test_editing_values_resolves_review_and_batch_undo_restores_it(
    client: httpx.AsyncClient, session: AsyncSession, ctx: dict[str, Any]
) -> None:
    await _v2(session, ctx)
    marks = await _marks(session, ctx["obra"])
    pp001, forma = marks["PP001"], ctx["forma"]
    url = f"/api/obras/{ctx['obra'].id}"
    # lote com PP001 (em revisão) → sai da revisão; desfazer → volta
    r = await client.post(
        f"{url}/marks/batch-apply",
        json={"mark_ids": [pp001.id], "changes": {str(forma.id): "F-13"}, "mode": "overwrite"},
        headers=ctx["fab"],
    )
    assert r.status_code == 200, r.text
    await session.refresh(pp001)
    assert pp001.review_status == "ok"
    undo = await client.post(f"/api/batches/{r.json()['batch_id']}/undo", headers=ctx["fab"])
    assert undo.status_code == 200, undo.text
    await session.refresh(pp001)
    assert pp001.review_status == "review" and pp001.review_note
    # edição individual também resolve
    current = (await client.get(f"{url}/marks/{pp001.id}/values", headers=ctx["fab"])).json()
    row_version = next(v["row_version"] for v in current["values"] if v["def_id"] == forma.id)
    r = await client.put(
        f"{url}/marks/{pp001.id}/values",
        json={"changes": [{"def_id": forma.id, "value": "F-12", "row_version": row_version}]},
        headers=ctx["fab"],
    )
    assert r.status_code == 200, r.text
    assert r.json()["mark"]["review_status"] == "ok"


# --------------------------------------------------------------------------- órfãs


async def _orphans(client: httpx.AsyncClient, ctx: dict[str, Any], status: str = "open") -> Any:
    r = await client.get(
        f"/api/obras/{ctx['obra'].id}/orphans", params={"status": status}, headers=ctx["fab"]
    )
    assert r.status_code == 200, r.text
    return r.json()


async def test_list_orphans_with_values(
    client: httpx.AsyncClient, session: AsyncSession, ctx: dict[str, Any]
) -> None:
    await _v2(session, ctx)
    body = await _orphans(client, ctx)
    assert [(o["code"], o["since_version_number"], o["status"]) for o in body] == [
        ("PP004", 2, "open"),
        ("PP005", 2, "open"),
    ]
    assert body[0]["values"] == [
        {"def_id": ctx["forma"].id, "name": "Tipo de forma", "type": "list", "value": "F-12"}
    ]


async def test_relink_copies_values_audits_and_closes(
    client: httpx.AsyncClient, session: AsyncSession, ctx: dict[str, Any]
) -> None:
    await _v2(session, ctx)
    marks = await _marks(session, ctx["obra"])
    orphan = next(o for o in await _orphans(client, ctx) if o["code"] == "PP004")
    r = await client.post(
        f"/api/orphans/{orphan['id']}/relink",
        json={"target_mark_id": marks["PP004A"].id},
        headers=ctx["fab"],
    )
    assert r.status_code == 200, r.text
    assert (r.json()["copied"], r.json()["skipped"]) == (["Tipo de forma"], [])
    target = await client.get(
        f"/api/obras/{ctx['obra'].id}/marks/{marks['PP004A'].id}/values", headers=ctx["fab"]
    )
    assert (
        next(v["value"] for v in target.json()["values"] if v["name"] == "Tipo de forma") == "F-12"
    )
    history = await client.get(
        f"/api/obras/{ctx['obra'].id}/marks/{marks['PP004A'].id}/history", headers=ctx["fab"]
    )
    assert history.json()[0]["after"] == "F-12"
    # a órfã fecha; a marca antiga continua com o valor
    closed = await _orphans(client, ctx, "relinked")
    assert [(o["code"], o["relinked_to_code"]) for o in closed] == [("PP004", "PP004A")]
    kept = await session.scalar(
        select(ParamValue.value).where(ParamValue.mark_id == marks["PP004"].id)
    )
    assert kept == "F-12"
    again = await client.post(
        f"/api/orphans/{orphan['id']}/relink",
        json={"target_mark_id": marks["PP004A"].id},
        headers=ctx["fab"],
    )
    assert again.status_code == 409


async def test_relink_conflict_needs_overwrite_and_skips_other_category(
    client: httpx.AsyncClient, session: AsyncSession, ctx: dict[str, Any]
) -> None:
    await _v2(session, ctx)
    marks = await _marks(session, ctx["obra"])
    session.add(ParamValue(mark_id=marks["PP007"].id, def_id=ctx["forma"].id, value="F-11"))
    await session.flush()
    orphan = next(o for o in await _orphans(client, ctx) if o["code"] == "PP005")
    url = f"/api/orphans/{orphan['id']}/relink"
    r = await client.post(url, json={"target_mark_id": marks["PP007"].id}, headers=ctx["fab"])
    assert (r.status_code, r.json()["code"]) == (409, "relink_conflict")
    assert r.json()["conflicts"] == [
        {
            "def_id": ctx["forma"].id,
            "name": "Tipo de forma",
            "orphan_value": "F-13",
            "target_value": "F-11",
        }
    ]
    r = await client.post(
        url, json={"target_mark_id": marks["PP007"].id, "overwrite": True}, headers=ctx["fab"]
    )
    assert r.status_code == 200 and r.json()["copied"] == ["Tipo de forma"]


async def test_relink_validation_and_permissions(
    client: httpx.AsyncClient, session: AsyncSession, ctx: dict[str, Any]
) -> None:
    await _v2(session, ctx)
    marks = await _marks(session, ctx["obra"])
    orphans = {o["code"]: o["id"] for o in await _orphans(client, ctx)}
    url = f"/api/orphans/{orphans['PP004']}/relink"
    proj = as_user(ctx["users"][Role.PROJETOS])
    assert (
        await client.post(url, json={"target_mark_id": marks["PP004A"].id}, headers=proj)
    ).status_code == 403
    r = await client.post(url, json={"target_mark_id": marks["PP004"].id}, headers=ctx["fab"])
    assert r.status_code == 422  # a própria
    r = await client.post(url, json={"target_mark_id": marks["PP005"].id}, headers=ctx["fab"])
    assert r.status_code == 422  # destino também órfão
    other = Obra(code="OB-X", name="Outra")
    session.add(other)
    await session.flush()
    alien = Mark(obra_id=other.id, code="PP004A", category="Structural Columns")
    session.add(alien)
    await session.flush()
    r = await client.post(url, json={"target_mark_id": alien.id}, headers=ctx["fab"])
    assert r.status_code == 404
    assert (await client.post("/api/orphans/999999/archive", headers=ctx["fab"])).status_code == 404


async def test_archive_keeps_values(
    client: httpx.AsyncClient, session: AsyncSession, ctx: dict[str, Any]
) -> None:
    await _v2(session, ctx)
    marks = await _marks(session, ctx["obra"])
    orphan = next(o for o in await _orphans(client, ctx) if o["code"] == "PP005")
    r = await client.post(f"/api/orphans/{orphan['id']}/archive", headers=ctx["fab"])
    assert (r.status_code, r.json()["status"]) == (200, "archived")
    assert [o["code"] for o in await _orphans(client, ctx)] == ["PP004"]
    kept = await session.scalar(
        select(ParamValue.value).where(ParamValue.mark_id == marks["PP005"].id)
    )
    assert kept == "F-13"
    entry = await session.scalar(
        select(AuditLog).where(AuditLog.entity == "orphan", AuditLog.action == "archive")
    )
    assert entry is not None


async def test_diff_not_ready_and_unknown(
    client: httpx.AsyncClient, session: AsyncSession, ctx: dict[str, Any]
) -> None:
    v = ModelVersion(obra_id=ctx["obra"].id, acc_version_id="urn:v:pend", version_number=9)
    session.add(v)
    await session.flush()
    r = await client.get(f"/api/versions/{v.id}/diff", headers=ctx["fab"])
    assert (r.status_code, r.json()["code"]) == (404, "diff_not_ready")
    assert (await client.get("/api/versions/999999/diff", headers=ctx["fab"])).status_code == 404
