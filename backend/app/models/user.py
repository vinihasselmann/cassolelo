from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Identity,
    String,
    UniqueConstraint,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import AuthorMixin, Base, TimestampMixin
from app.models.enums import Role, check_in


class User(TimestampMixin, AuthorMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("email", name="uq_users_email"),
        CheckConstraint(check_in("role", Role), name="ck_users_role"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(320))
    role: Mapped[str] = mapped_column(String(20))
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    # vê todas as obras (padrão); false = só as de user_obras (11.2). Admin vê sempre todas.
    all_obras: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())


class UserObra(AuthorMixin, Base):
    """Obra que um usuário restrito (all_obras = false) pode ver (11.2)."""

    __tablename__ = "user_obras"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    obra_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("obras.id", ondelete="CASCADE"), primary_key=True, index=True
    )
