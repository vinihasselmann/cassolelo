from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, MetaData, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

# Nomes explícitos e estáveis para constraints/índices (a migração usa os mesmos).
NAMING_CONVENTION = {
    "pk": "pk_%(table_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {dict[str, Any]: JSONB, list[Any]: JSONB}  # noqa: RUF012


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AuthorMixin:
    """created_by/updated_by -> users.id (nulo = sistema)."""

    @declared_attr
    def created_by(cls) -> Mapped[int | None]:
        return mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))

    @declared_attr
    def updated_by(cls) -> Mapped[int | None]:
        return mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
