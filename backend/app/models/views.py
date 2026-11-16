"""Filtros salvos e esquemas de cores (docs/filtros/plano.md, passo 2).

- personal: só o dono vê e edita; shared: todos veem, criar e editar exige um papel de
  SHARED_FILTER_ROLES (padrão fábrica e admin).
- obra_id nulo = vale para todas as obras.
- Filtros de SISTEMA (system_key preenchido): os antigos atalhos da busca (Pendentes,
  Parciais, A revisar, Novas na versão, Órfãs). Compartilhados e não editáveis.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Identity,
    Index,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import AuthorMixin, Base, TimestampMixin

SCOPE_CHECK = "scope IN ('personal', 'shared')"
OWNER_CHECK = "scope <> 'personal' OR owner_id IS NOT NULL"


class SavedFilter(TimestampMixin, AuthorMixin, Base):
    __tablename__ = "saved_filters"
    __table_args__ = (
        CheckConstraint(SCOPE_CHECK, name="ck_saved_filters_scope"),
        CheckConstraint(OWNER_CHECK, name="ck_saved_filters_owner"),
        CheckConstraint(
            "system_key IS NULL OR scope = 'shared'", name="ck_saved_filters_system_shared"
        ),
        # Nomes únicos por escopo (sem diferenciar maiúsculas): compartilhados entre si;
        # pessoais por dono.
        Index(
            "uq_saved_filters_shared_name",
            func.lower(text("name")),
            unique=True,
            postgresql_where=text("scope = 'shared'"),
        ),
        Index(
            "uq_saved_filters_personal_name",
            "owner_id",
            func.lower(text("name")),
            unique=True,
            postgresql_where=text("scope = 'personal'"),
        ),
        Index(
            "uq_saved_filters_system_key",
            "system_key",
            unique=True,
            postgresql_where=text("system_key IS NOT NULL"),
        ),
        Index("ix_saved_filters_obra_id", "obra_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    scope: Mapped[str] = mapped_column(String(10))
    owner_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE")
    )
    obra_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("obras.id", ondelete="CASCADE")
    )
    definition: Mapped[dict[str, Any]] = mapped_column()
    system_key: Mapped[str | None] = mapped_column(String(30))


class ColorScheme(TimestampMixin, AuthorMixin, Base):
    __tablename__ = "color_schemes"
    __table_args__ = (
        CheckConstraint(SCOPE_CHECK, name="ck_color_schemes_scope"),
        CheckConstraint(OWNER_CHECK, name="ck_color_schemes_owner"),
        Index(
            "uq_color_schemes_shared_name",
            func.lower(text("name")),
            unique=True,
            postgresql_where=text("scope = 'shared'"),
        ),
        Index(
            "uq_color_schemes_personal_name",
            "owner_id",
            func.lower(text("name")),
            unique=True,
            postgresql_where=text("scope = 'personal'"),
        ),
        Index("ix_color_schemes_obra_id", "obra_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    scope: Mapped[str] = mapped_column(String(10))
    owner_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE")
    )
    obra_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("obras.id", ondelete="CASCADE")
    )
    # lista ORDENADA: [{"filter": <id de filtro salvo> | <definição>, "color": "#RRGGBB",
    # "label": "..."}]; a primeira regra que bater vence
    rules: Mapped[list[Any]] = mapped_column()
