"""Autenticação e autorização.

Os endpoints importam SOMENTE daqui (`CurrentUser`, `require_role`, `Role`).
`current_user` (app/auth/current.py) aceita o login Microsoft (Bearer, Fase 11) e,
só com APP_ENV=dev, o usuário simulado X-Dev-User.
"""

from typing import Annotated

from fastapi import Depends

from app.auth.current import current_user
from app.auth.dev import DEV_USER_HEADER
from app.auth.roles import require_role
from app.models import User
from app.models.enums import Role

CurrentUser = Annotated[User, Depends(current_user)]

__all__ = ["DEV_USER_HEADER", "CurrentUser", "Role", "current_user", "require_role"]
