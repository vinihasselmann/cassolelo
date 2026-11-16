from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, HTTPException, status

from app.auth.dev import current_user
from app.models import User
from app.models.enums import Role


def require_role(*roles: Role) -> Callable[[User], Awaitable[User]]:
    """Dependência que exige um dos papéis informados.

    @router.post("/x", dependencies=[Depends(require_role(Role.FABRICA, Role.ADMIN))])
    """
    if not roles:
        raise ValueError("require_role precisa de pelo menos um papel")
    allowed = frozenset(r.value for r in roles)

    async def dependency(user: Annotated[User, Depends(current_user)]) -> User:
        if user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Seu papel não permite esta ação.",
            )
        return user

    return dependency
