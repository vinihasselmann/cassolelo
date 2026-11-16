"""Parâmetros da fábrica e marcas órfãs."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    UniqueConstraint,
    false,
    func,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import AuthorMixin, Base, TimestampMixin
from app.models.enums import OrphanStatus, ParamScope, ParamType, check_in


class ParamDef(TimestampMixin, AuthorMixin, Base):
    __tablename__ = "param_defs"
    __table_args__ = (
        CheckConstraint(check_in("type", ParamType), name="ck_param_defs_type"),
        CheckConstraint(check_in("scope", ParamScope), name="ck_param_defs_scope"),
        CheckConstraint(
            "(scope = 'global' AND obra_id IS NULL) OR (scope = 'obra' AND obra_id IS NOT NULL)",
            name="ck_param_defs_scope_obra",
        ),
        # Nome único sem diferenciar maiúsculas, só entre ativos (exclusão é lógica).
        Index(
            "uq_param_defs_global_name",
            func.lower(text("name")),
            unique=True,
            postgresql_where=text("scope = 'global' AND active"),
        ),
        Index(
            "uq_param_defs_obra_name",
            "obra_id",
            func.lower(text("name")),
            unique=True,
            postgresql_where=text("scope = 'obra' AND active"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(10))
    unit: Mapped[str | None] = mapped_column(String(30))
    options: Mapped[list[Any] | None] = mapped_column()  # opções de uma lista
    required: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    categories: Mapped[list[Any] | None] = mapped_column()  # nulo = todas as categorias
    scope: Mapped[str] = mapped_column(String(10))
    obra_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("obras.id", ondelete="RESTRICT")
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())


class ObraParam(Base):
    """Parâmetro da biblioteca (scope = global) INCLUÍDO numa obra. Sem esta linha, o
    parâmetro não vale para a obra (decisão de 2026-11-13). Retirar não apaga valores."""

    __tablename__ = "obra_params"
    __table_args__ = (Index("ix_obra_params_def_id", "def_id"),)

    obra_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("obras.id", ondelete="RESTRICT"), primary_key=True
    )
    def_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("param_defs.id", ondelete="RESTRICT"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )


class ParamValue(TimestampMixin, AuthorMixin, Base):
    """Valor de um parâmetro para uma MARCA (nunca para uma versão)."""

    __tablename__ = "param_values"
    __table_args__ = (UniqueConstraint("mark_id", "def_id", name="uq_param_values_mark_id_def_id"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    mark_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("marks.id", ondelete="RESTRICT"))
    def_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("param_defs.id", ondelete="RESTRICT")
    )
    value: Mapped[Any] = mapped_column(JSONB, nullable=True)  # nulo = valor apagado
    row_version: Mapped[int] = mapped_column(Integer, server_default=text("1"))

    # Concorrência otimista: UPDATE ... WHERE row_version = <lido>; incrementa a cada escrita.
    __mapper_args__ = {"version_id_col": row_version}  # noqa: RUF012


class Orphan(TimestampMixin, AuthorMixin, Base):
    """Marca que sumiu do modelo mas tem valores (nunca apagar em silêncio)."""

    __tablename__ = "orphans"
    __table_args__ = (
        CheckConstraint(check_in("status", OrphanStatus), name="ck_orphans_status"),
        Index(
            "uq_orphans_open_mark_id",
            "mark_id",
            unique=True,
            postgresql_where=text("status = 'open'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    mark_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("marks.id", ondelete="RESTRICT"))
    since_version_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("model_versions.id", ondelete="RESTRICT")
    )
    status: Mapped[str] = mapped_column(
        String(20), default=OrphanStatus.OPEN, server_default=text("'open'")
    )
    relinked_to: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("marks.id", ondelete="RESTRICT")
    )
