"""Autenticação e autorização.

Os endpoints importam SOMENTE daqui (`CurrentUser`, `require_role`, `Role`).
Na Fase 11 basta trocar a implementação de `current_user` (hoje: usuário
simulado por X-Dev-User em app/auth/dev.py) sem mexer nos endpoints.
"""

from typing import Annotated

from fastapi import Depends

from app.auth.dev import DEV_USER_HEADER, current_user
from app.auth.roles import require_role
from app.models import User
from app.models.enums import Role

CurrentUser = Annotated[User, Depends(current_user)]

__all__ = ["DEV_USER_HEADER", "CurrentUser", "Role", "current_user", "require_role"]
