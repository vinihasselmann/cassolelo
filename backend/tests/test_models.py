from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from app.models import AuditLog, Element, Mark, ModelVersion, Obra, ParamDef, ParamValue, User
from app.models.enums import Role
from app.seed import seed_users
from app.services import audit


async def _obra(session: AsyncSession, code: str = "OB-1") -> Obra:
    obra = Obra(code=code, name="Obra teste")
    session.add(obra)
    await session.flush()
    return obra


async def _mark(session: AsyncSession, obra: Obra, code: str = "V-101") -> Mark:
    mark = Mark(obra_id=obra.id, code=code, category="Structural Framing")
    session.add(mark)
    await session.flush()
    return mark


async def _def(session: AsyncSession, name: str = "Tipo de forma") -> ParamDef:
    d = ParamDef(name=name, type="list", options=["F1", "F2"], scope="global")
    session.add(d)
    await session.flush()
    return d


async def test_mark_unique_per_obra_code_category(session: AsyncSession) -> None:
    obra = await _obra(session)
    await _mark(session, obra)
    other = await _obra(session, "OB-2")
    await _mark(session, other)  # mesma marca em outra obra: ok
    session.add(Mark(obra_id=obra.id, code="V-101", category="Structural Columns"))
    await session.flush()  # mesma marca, outra categoria: ok
    with pytest.raises(IntegrityError, match="uq_marks_obra_id_code_category"):
        async with session.begin_nested():
            session.add(Mark(obra_id=obra.id, code="V-101", category="Structural Framing"))


async def test_param_value_unique_per_mark_and_def(session: AsyncSession) -> None:
    obra = await _obra(session)
    mark, d = await _mark(session, obra), await _def(session)
    session.add(ParamValue(mark_id=mark.id, def_id=d.id, value="F1"))
    await session.flush()
    with pytest.raises(IntegrityError, match="uq_param_values_mark_id_def_id"):
        async with session.begin_nested():
            session.add(ParamValue(mark_id=mark.id, def_id=d.id, value="F2"))


async def test_param_value_row_version_optimistic_lock(session: AsyncSession) -> None:
    obra = await _obra(session)
    mark, d = await _mark(session, obra), await _def(session)
    pv = ParamValue(mark_id=mark.id, def_id=d.id, value="F1")
    session.add(pv)
    await session.flush()
    assert pv.row_version == 1

    pv.value = "F2"
    await session.flush()
    assert pv.row_version == 2

    # outra "aba" grava antes (fora do ORM): a nossa cópia fica desatualizada
    await session.execute(
        update(ParamValue)
        .where(ParamValue.id == pv.id)
        .values(row_version=ParamValue.row_version + 1, value="F9")
        .execution_options(synchronize_session=False)
    )
    pv.value = "F3"
    with pytest.raises(StaleDataError):
        await session.flush()


async def test_param_def_scope_requires_obra(session: AsyncSession) -> None:
    with pytest.raises(IntegrityError, match="ck_param_defs_scope_obra"):
        async with session.begin_nested():
            session.add(ParamDef(name="X", type="text", scope="obra", obra_id=None))


async def test_check_constraints_reject_invalid_values(session: AsyncSession) -> None:
    with pytest.raises(IntegrityError, match="ck_users_role"):
        async with session.begin_nested():
            session.add(User(name="x", email="x@x", role="chefe"))


async def test_elements_props_gin_index_is_used_for_containment(session: AsyncSession) -> None:
    indexdef = await session.scalar(
        text("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_elements_props_gin'")
    )
    assert indexdef is not None and "USING gin" in indexdef

    obra = await _obra(session)
    v = ModelVersion(obra_id=obra.id, acc_version_id="urn:v1", version_number=1)
    session.add(v)
    await session.flush()
    session.add_all(
        [
            Element(version_id=v.id, dbid=1, props={"Dados": {"Marca": "V-101"}}),
            Element(version_id=v.id, dbid=2, props={"Dados": {"Marca": "P-01"}}),
        ]
    )
    await session.flush()
    found = await session.scalars(
        select(Element.dbid).where(Element.props.contains({"Dados": {"Marca": "V-101"}}))
    )
    assert list(found) == [1]


async def test_audit_record_and_snapshot(session: AsyncSession) -> None:
    users = await seed_users(session)
    actor = users[Role.ADMIN]
    obra = await _obra(session)
    batch = uuid.uuid4()
    before = audit.snapshot(obra)
    obra.name = "Obra renomeada"
    await session.flush()
    entry = await audit.record(
        session, "obra", obra.id, "update", before, audit.snapshot(obra), actor, batch
    )
    stored = await session.get(AuditLog, entry.id)
    assert stored is not None
    assert stored.entity == "obra" and stored.entity_id == str(obra.id)
    assert stored.before is not None and stored.before["name"] == "Obra teste"
    assert stored.after is not None and stored.after["name"] == "Obra renomeada"
    assert isinstance(stored.before["created_at"], str)  # datetime serializado
    assert stored.user_id == actor.id and stored.batch_id == batch


async def test_seed_is_idempotent_and_audited(session: AsyncSession) -> None:
    first = await seed_users(session)
    second = await seed_users(session)
    assert {r: u.id for r, u in first.items()} == {r: u.id for r, u in second.items()}
    count = await session.scalar(
        select(func.count()).select_from(AuditLog).where(AuditLog.entity == "user")
    )
    assert count == 4  # só as criações; a 2ª execução não altera nada
