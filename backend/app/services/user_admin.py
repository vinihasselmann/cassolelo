"""Administração de usuários pela tela "Usuários" (11.2, só admin).

- Listar, cadastrar pelo e-mail antes do primeiro acesso, definir papel, ativar/desativar
  e definir as obras que cada um vê (padrão: todas).
- Papel que vem de fora não se troca aqui: e-mail em BOOTSTRAP_ADMIN_EMAILS (sempre
  admin) ou ENTRA_ROLE_GROUPS configurado (o grupo do Entra manda). O próximo login
  desfaria a troca; a tela explica.
- Ninguém tranca o app: o admin não se desativa nem tira o próprio papel de admin, e o
  último admin ativo não perde o papel nem é desativado.
- Tudo vai para o audit_log com o autor (o admin logado).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import Obra, User, UserObra
from app.models.enums import Role
from app.services import audit
from app.services.errors import ConflictError, NotFoundError, ValidationError

AUDIT_ENTITY = "user"
TRACKED = ("name", "role", "active", "all_obras", "obra_ids")


class RoleSource(StrEnum):
    TABLE = "table"  # definido nesta tela (ou pela CLI)
    BOOTSTRAP = "bootstrap"  # BOOTSTRAP_ADMIN_EMAILS: sempre admin
    GROUPS = "groups"  # ENTRA_ROLE_GROUPS: o grupo do Entra define a cada login


@dataclass
class UserInfo:
    user: User
    obra_ids: list[int]  # só quando all_obras = false (admin: sempre vazio, vê todas)
    role_source: RoleSource


@dataclass
class UserPatch:
    name: str | None = None
    role: Role | None = None
    active: bool | None = None
    all_obras: bool | None = None
    obra_ids: Sequence[int] | None = None


def role_source(settings: Settings, email: str) -> RoleSource:
    if email.lower() in settings.bootstrap_admin_list:
        return RoleSource.BOOTSTRAP
    if settings.entra_role_group_list:
        return RoleSource.GROUPS
    return RoleSource.TABLE


async def _obra_ids_by_user(session: AsyncSession, user_ids: list[int]) -> dict[int, list[int]]:
    out: dict[int, list[int]] = {i: [] for i in user_ids}
    if not user_ids:
        return out
    rows = await session.execute(
        select(UserObra.user_id, UserObra.obra_id)
        .where(UserObra.user_id.in_(user_ids))
        .order_by(UserObra.obra_id)
    )
    for user_id, obra_id in rows:
        out[user_id].append(obra_id)
    return out


async def list_users(session: AsyncSession, settings: Settings) -> list[UserInfo]:
    users = list(await session.scalars(select(User).order_by(func.lower(User.name), User.id)))
    obras = await _obra_ids_by_user(session, [u.id for u in users])
    return [UserInfo(u, obras[u.id], role_source(settings, u.email)) for u in users]


async def get_user(session: AsyncSession, settings: Settings, user_id: int) -> UserInfo:
    user = await session.get(User, user_id)
    if user is None:
        raise NotFoundError("Usuário não encontrado.")
    obras = await _obra_ids_by_user(session, [user.id])
    return UserInfo(user, obras[user.id], role_source(settings, user.email))


def _clean_email(settings: Settings, raw: str) -> str:
    email = raw.strip().lower()
    local, at, domain = email.partition("@")
    if not local or not at or "." not in domain or " " in email:
        raise ValidationError("Informe um e-mail válido.")
    allowed = settings.allowed_email_domain_list
    if allowed and domain not in allowed:
        raise ValidationError(f"E-mail fora dos domínios permitidos ({', '.join(allowed)}).")
    return email


def _clean_name(raw: str | None) -> str | None:
    if raw is None:
        return None
    name = " ".join(raw.split())
    if not name:
        raise ValidationError("Informe o nome.")
    if len(name) > 200:
        raise ValidationError("Nome muito longo (máximo 200 caracteres).")
    return name


async def _check_obras(session: AsyncSession, obra_ids: Sequence[int]) -> list[int]:
    ids = sorted(set(obra_ids))
    if not ids:
        return []
    found = set(await session.scalars(select(Obra.id).where(Obra.id.in_(ids))))
    if missing := [i for i in ids if i not in found]:
        raise ValidationError(f"Obra não encontrada: {', '.join(map(str, missing))}.")
    return ids


async def _set_obras(
    session: AsyncSession, user: User, obra_ids: list[int], actor: User
) -> tuple[list[int], list[int]]:
    """Troca as obras do usuário. Devolve (antes, depois)."""
    before = (await _obra_ids_by_user(session, [user.id]))[user.id]
    if before == obra_ids:
        return before, before
    await session.execute(delete(UserObra).where(UserObra.user_id == user.id))
    for obra_id in obra_ids:
        session.add(
            UserObra(user_id=user.id, obra_id=obra_id, created_by=actor.id, updated_by=actor.id)
        )
    await session.flush()
    return before, obra_ids


async def _active_admins(session: AsyncSession) -> int:
    count = await session.scalar(
        select(func.count())
        .select_from(User)
        .where(User.role == Role.ADMIN.value, User.active.is_(True))
    )
    return int(count or 0)


async def create_user(
    session: AsyncSession,
    settings: Settings,
    *,
    email: str,
    name: str | None,
    role: Role,
    all_obras: bool,
    obra_ids: Sequence[int],
    actor: User,
) -> UserInfo:
    """Cadastra antes do primeiro acesso. Sem nome, fica o e-mail até a pessoa entrar
    (o login preenche o nome da conta Microsoft)."""
    email = _clean_email(settings, email)
    clean_name = _clean_name(name) or email
    exists = await session.scalar(select(User.id).where(func.lower(User.email) == email))
    if exists is not None:
        raise ConflictError("Já existe um usuário com esse e-mail.")
    source = role_source(settings, email)
    if source is RoleSource.BOOTSTRAP:
        role = Role.ADMIN
    ids = await _check_obras(session, obra_ids) if not all_obras else []
    user = User(
        name=clean_name,
        email=email,
        role=role.value,
        active=True,
        all_obras=all_obras,
        created_by=actor.id,
        updated_by=actor.id,
    )
    session.add(user)
    await session.flush()
    await _set_obras(session, user, ids, actor)
    after = {**audit.snapshot(user), "obra_ids": ids}
    await audit.record(session, AUDIT_ENTITY, user.id, "create", None, after, actor)
    return UserInfo(user, ids, source)


async def update_user(
    session: AsyncSession, settings: Settings, user_id: int, patch: UserPatch, actor: User
) -> UserInfo:
    info = await get_user(session, settings, user_id)
    user = info.user
    before = {**audit.snapshot(user), "obra_ids": info.obra_ids}
    is_self = user.id == actor.id

    if patch.role is not None and patch.role.value != user.role:
        if info.role_source is RoleSource.BOOTSTRAP:
            raise ConflictError(
                "Este e-mail é administrador fixo (BOOTSTRAP_ADMIN_EMAILS): o papel não muda "
                "por aqui."
            )
        if info.role_source is RoleSource.GROUPS:
            raise ConflictError(
                "O papel vem dos grupos do Microsoft Entra (ENTRA_ROLE_GROUPS): troque o "
                "grupo da pessoa no Entra."
            )
        if user.role == Role.ADMIN.value:
            if is_self:
                raise ConflictError("Você não pode tirar o seu próprio papel de administrador.")
            if user.active and await _active_admins(session) <= 1:
                raise ConflictError("Este é o último administrador ativo: promova outro antes.")
        user.role = patch.role.value

    if patch.active is not None and patch.active != user.active:
        if not patch.active:
            if is_self:
                raise ConflictError("Você não pode desativar a sua própria conta.")
            if user.role == Role.ADMIN.value and await _active_admins(session) <= 1:
                raise ConflictError("Este é o último administrador ativo: promova outro antes.")
        user.active = patch.active

    if (name := _clean_name(patch.name)) is not None:
        user.name = name

    ids = info.obra_ids
    if patch.all_obras is not None:
        user.all_obras = patch.all_obras
    if user.all_obras:
        ids = []  # vê todas: a lista antiga não vale mais
    elif patch.obra_ids is not None:
        ids = await _check_obras(session, patch.obra_ids)
    if ids != info.obra_ids:
        await _set_obras(session, user, ids, actor)

    after = {**audit.snapshot(user), "obra_ids": ids}
    if any(before.get(k) != after.get(k) for k in TRACKED):
        user.updated_by = actor.id
        await session.flush()
        after["updated_by"] = actor.id
        await audit.record(session, AUDIT_ENTITY, user.id, "update", before, after, actor)
    return UserInfo(user, ids, info.role_source)
