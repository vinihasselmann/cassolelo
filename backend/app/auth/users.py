"""Do token Microsoft ao usuário do app (Fase 11).

- Encontra o usuário pelo e-mail (sem diferenciar maiúsculas) ou cria, só para os
  domínios de ALLOWED_EMAIL_DOMAINS. Usuário novo entra como "leitura".
- Papel: o da tabela users (o admin define), salvo:
  * e-mail em BOOTSTRAP_ADMIN_EMAILS -> sempre admin;
  * ENTRA_ROLE_GROUPS configurado e grupos no token -> o do 1º grupo da lista em que a
    pessoa está, ou "leitura" se nenhum. Sem a claim de grupos no token, fica a tabela.
- Toda criação ou troca de papel vai para o audit_log (ação do sistema).
- Usuário desativado na tabela não entra (403), mesmo com token válido.
- Cadastrado pelo admin só com o e-mail (nome = e-mail): o 1º login grava o nome da conta.
"""

from __future__ import annotations

import logging

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.entra import EntraIdentity
from app.config import Settings
from app.models import User
from app.models.enums import Role
from app.services import audit

log = logging.getLogger("app.auth")


def _forbidden(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def email_allowed(settings: Settings, email: str) -> bool:
    domain = email.rsplit("@", 1)[-1].lower()
    return domain in settings.allowed_email_domain_list


def target_role(settings: Settings, identity: EntraIdentity, current: str | None) -> str:
    """Papel que o usuário deve ter agora (current = o da tabela, ou None se novo)."""
    if identity.email in settings.bootstrap_admin_list:
        return Role.ADMIN.value
    groups = settings.entra_role_group_list
    if groups and identity.groups is not None:
        member = set(identity.groups)
        for role, group_id in groups:
            if group_id in member:
                return role
        return Role.LEITURA.value
    if groups and identity.groups is None:
        log.warning(
            "ENTRA_ROLE_GROUPS configurado, mas o token não trouxe os grupos: vale o papel "
            "da tabela (ligar a claim groups no registro do app)."
        )
    return current or Role.LEITURA.value


async def _find(session: AsyncSession, email: str) -> User | None:
    return await session.scalar(select(User).where(func.lower(User.email) == email))


async def resolve_user(session: AsyncSession, settings: Settings, identity: EntraIdentity) -> User:
    if not email_allowed(settings, identity.email):
        domains = ", ".join(settings.allowed_email_domain_list) or "nenhum configurado"
        raise _forbidden(f"E-mail fora dos domínios permitidos ({domains}).")

    user = await _find(session, identity.email)
    if user is None:
        user = User(
            name=identity.name,
            email=identity.email,
            role=target_role(settings, identity, None),
            active=True,
        )
        try:
            async with session.begin_nested():
                session.add(user)
                await session.flush()
        except IntegrityError:
            # outra requisição criou o mesmo usuário ao mesmo tempo
            user = await _find(session, identity.email)
            if user is None:  # pragma: no cover - só se o outro foi desfeito
                raise
        else:
            await audit.record(session, "user", user.id, "create", None, audit.snapshot(user), None)
            await session.commit()
            return user

    if not user.active:
        raise _forbidden("Usuário desativado. Fale com o administrador do app.")
    role = target_role(settings, identity, user.role)
    # cadastrado pelo admin só com o e-mail (11.2): o nome real vem da conta Microsoft
    named = user.name.strip().lower() == user.email.lower() and identity.name != identity.email
    if role != user.role or named:
        before = audit.snapshot(user)
        user.role = role
        if named:
            user.name = identity.name
        await session.flush()
        await audit.record(session, "user", user.id, "update", before, audit.snapshot(user), None)
        await session.commit()
    return user
