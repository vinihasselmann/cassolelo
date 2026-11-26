"""Unidades de peça e valores por peça (decisão de 2026-11-16, docs/pecas/verificacao.md).

Uma MARCA agrupa N peças físicas idênticas; cada uma é uma UNIDADE DE PEÇA numerada no
app (PP001-1, PP001-2…). O número nunca é reaproveitado. A cada versão processada, a
unidade é ligada a um elemento do modelo (pelo externalId; sem par, pela ordem). Os
parâmetros POR PEÇA guardam um valor por unidade, nunca por versão.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import AuthorMixin, Base, TimestampMixin
from app.models.enums import LinkMethod, UnitStatus, check_in


class PieceUnit(TimestampMixin, AuthorMixin, Base):
    __tablename__ = "piece_units"
    __table_args__ = (
        UniqueConstraint("mark_id", "number", name="uq_piece_units_mark_id_number"),
        CheckConstraint(check_in("status", UnitStatus), name="ck_piece_units_status"),
        CheckConstraint("number >= 1", name="ck_piece_units_number"),
        Index("ix_piece_units_obra_id_status", "obra_id", "status"),
        Index(
            "uq_piece_units_obra_plannix_code",
            "obra_id",
            "plannix_code",
            unique=True,
            postgresql_where=text("plannix_code IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    obra_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("obras.id", ondelete="RESTRICT"))
    mark_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("marks.id", ondelete="RESTRICT"))
    number: Mapped[int] = mapped_column(Integer)  # PP001-<number>; nunca reaproveitado
    # chave do elemento da última ligação (UniqueId no Revit, GlobalId no IFC)
    external_id: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(
        String(10), default=UnitStatus.LINKED, server_default=text("'linked'")
    )
    # "Código" da peça no Plannix, guardado na 1ª importação que a ligou (2026-11-24)
    plannix_code: Mapped[str | None] = mapped_column(String(30))
    # versão em que ficou sem peça (status orphan/unlinked)
    since_version_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("model_versions.id", ondelete="SET NULL")
    )


class PieceUnitLink(Base):
    """Ligação unidade ↔ elemento numa versão (refeita a cada processamento da versão)."""

    __tablename__ = "piece_unit_links"
    __table_args__ = (
        UniqueConstraint("version_id", "element_id", name="uq_piece_unit_links_version_element"),
        CheckConstraint(check_in("method", LinkMethod), name="ck_piece_unit_links_method"),
        Index("ix_piece_unit_links_unit_id", "unit_id"),
    )

    version_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("model_versions.id", ondelete="CASCADE"), primary_key=True
    )
    unit_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("piece_units.id", ondelete="CASCADE"), primary_key=True
    )
    element_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("elements.id", ondelete="CASCADE")
    )
    method: Mapped[str] = mapped_column(String(10))


class PieceValue(TimestampMixin, AuthorMixin, Base):
    """Valor de um parâmetro POR PEÇA para uma unidade (nunca para uma versão)."""

    __tablename__ = "piece_values"
    __table_args__ = (UniqueConstraint("unit_id", "def_id", name="uq_piece_values_unit_id_def_id"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    unit_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("piece_units.id", ondelete="RESTRICT")
    )
    def_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("param_defs.id", ondelete="RESTRICT")
    )
    value: Mapped[Any] = mapped_column(JSONB, nullable=True)  # nulo = valor apagado
    row_version: Mapped[int] = mapped_column(Integer, server_default=text("1"))

    # Concorrência otimista, como em param_values.
    __mapper_args__ = {"version_id_col": row_version}  # noqa: RUF012
