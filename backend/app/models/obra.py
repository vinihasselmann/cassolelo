"""Obras, versões do modelo, elementos e marcas."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import AuthorMixin, Base, TimestampMixin
from app.models.enums import AccFileState, ReviewStatus, UnitNumbering, VersionStatus, check_in


class Obra(TimestampMixin, AuthorMixin, Base):
    __tablename__ = "obras"
    __table_args__ = (
        UniqueConstraint("code", name="uq_obras_code"),
        CheckConstraint(check_in("acc_file_state", AccFileState), name="ck_obras_acc_file_state"),
        CheckConstraint(check_in("unit_numbering", UnitNumbering), name="ck_obras_unit_numbering"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(200))
    acc_hub_id: Mapped[str | None] = mapped_column(String(255))
    acc_project_id: Mapped[str | None] = mapped_column(String(255))
    acc_folder_id: Mapped[str | None] = mapped_column(String(512))
    acc_item_id: Mapped[str | None] = mapped_column(String(512))
    acc_item_name: Mapped[str | None] = mapped_column(String(255))  # só para exibição
    # Obras inativas saem da verificação periódica de versões.
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    # Arquivo excluído no Docs: a obra fica bloqueada (só editar/excluir). Volta a "ok"
    # sozinha se o arquivo for restaurado. `acc_file_state_at` = quando o app percebeu.
    acc_file_state: Mapped[str] = mapped_column(
        String(20), default=AccFileState.OK, server_default=text("'ok'")
    )
    acc_file_state_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Numeração das unidades: provisória até o 3D mandar os centros de gravidade; então
    # renumerada pela sequência de montagem, se a obra ainda não tem valores por peça.
    unit_numbering: Mapped[str] = mapped_column(
        String(12), default=UnitNumbering.PROVISIONAL, server_default=text("'provisional'")
    )
    # Regra de identificação das peças (nulo = padrão do servidor): parâmetros do modelo
    # que dão a marca e a categoria, em ordem de prioridade.
    mark_property_names: Mapped[list[str] | None] = mapped_column(JSONB)
    category_property_names: Mapped[list[str] | None] = mapped_column(JSONB)
    # Montagens (.nwd/.rvt com vínculos): categorias do "corpo" da peça. Nulo = regra
    # antiga (nó com marca). Ver app/services/assemblies.py.
    piece_category_names: Mapped[list[str] | None] = mapped_column(JSONB)


class ModelVersion(TimestampMixin, AuthorMixin, Base):
    __tablename__ = "model_versions"
    __table_args__ = (
        UniqueConstraint("acc_version_id", name="uq_model_versions_acc_version_id"),
        CheckConstraint(check_in("status", VersionStatus), name="ck_model_versions_status"),
        Index("ix_model_versions_obra_id_version_number", "obra_id", "version_number"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    obra_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("obras.id", ondelete="RESTRICT"))
    acc_version_id: Mapped[str] = mapped_column(String(512))
    version_number: Mapped[int] = mapped_column(Integer)
    urn: Mapped[str | None] = mapped_column(String(1024))
    status: Mapped[str] = mapped_column(
        String(20), default=VersionStatus.PENDING, server_default=text("'pending'")
    )
    published_by: Mapped[str | None] = mapped_column(String(255))  # nome vindo do ACC
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    comment: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)


class Mark(TimestampMixin, AuthorMixin, Base):
    """MARCA = (obra, código, categoria). Agrupa N peças físicas idênticas."""

    __tablename__ = "marks"
    __table_args__ = (
        UniqueConstraint("obra_id", "code", "category", name="uq_marks_obra_id_code_category"),
        CheckConstraint(check_in("review_status", ReviewStatus), name="ck_marks_review_status"),
        Index(
            "ix_marks_obra_id_review",
            "obra_id",
            postgresql_where=text("review_status = 'review'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    obra_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("obras.id", ondelete="RESTRICT"))
    code: Mapped[str] = mapped_column(String(100))
    category: Mapped[str] = mapped_column(String(255))
    review_status: Mapped[str] = mapped_column(
        String(20), default=ReviewStatus.OK, server_default=text("'ok'")
    )
    review_note: Mapped[str | None] = mapped_column(Text)


class VersionReport(TimestampMixin, AuthorMixin, Base):
    """Relatório de validação de marcas de uma versão (recriável: CASCADE com a versão)."""

    __tablename__ = "version_reports"
    __table_args__ = (UniqueConstraint("version_id", name="uq_version_reports_version_id"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    version_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("model_versions.id", ondelete="CASCADE")
    )
    report: Mapped[dict[str, Any]] = mapped_column()


class VersionDiff(TimestampMixin, AuthorMixin, Base):
    """Reconciliação de uma versão com a anterior pronta (Fase 7.2): totais e marcas."""

    __tablename__ = "version_diffs"
    __table_args__ = (UniqueConstraint("version_id", name="uq_version_diffs_version_id"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    version_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("model_versions.id", ondelete="CASCADE")
    )
    prev_version_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("model_versions.id", ondelete="SET NULL")
    )
    diff: Mapped[dict[str, Any]] = mapped_column()


class Element(Base):
    """Peça de uma versão específica do modelo (dados do BIM, imutáveis)."""

    __tablename__ = "elements"
    __table_args__ = (
        UniqueConstraint("version_id", "dbid", name="uq_elements_version_id_dbid"),
        Index("ix_elements_version_id_external_id", "version_id", "external_id"),
        Index("ix_elements_mark_id", "mark_id"),
        Index("ix_elements_props_gin", "props", postgresql_using="gin"),
        Index("ix_elements_version_id_level", "version_id", "level"),
        Index(
            "ix_elements_member_dbids",
            "member_dbids",
            postgresql_using="gin",
            postgresql_ops={"member_dbids": "jsonb_path_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    version_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("model_versions.id", ondelete="CASCADE")
    )
    external_id: Mapped[str | None] = mapped_column(String(255))
    dbid: Mapped[int] = mapped_column(Integer)
    name: Mapped[str | None] = mapped_column(String(512))
    mark_raw: Mapped[str | None] = mapped_column(String(255))
    # De qual parâmetro da regra da obra veio a marca (ex.: "Nome da montagem") e os outros
    # parâmetros da regra preenchidos na peça: [["Marca", "P01"], ...] na ordem da regra.
    mark_source: Mapped[str | None] = mapped_column(String(255))
    mark_alt: Mapped[list[Any]] = mapped_column(default=list, server_default=text("'[]'::jsonb"))
    # centro de gravidade [x, y, z] (m), mandado pelo navegador (unit_sequence.py)
    # (None vira NULL do SQL, não o JSON null: "sem centro" é contado pelo status)
    centroid: Mapped[list[float] | None] = mapped_column(JSONB(none_as_null=True))
    # pilar | quadro | laje | escada | outros (piece_type.py; filtro da lista)
    piece_type: Mapped[str | None] = mapped_column(String(12))
    category: Mapped[str | None] = mapped_column(String(255))
    level: Mapped[str | None] = mapped_column(String(255))  # nível/pavimento (busca)
    # nome, categoria, marca, nível e valores de SEARCH_PROPERTY_NAMES (texto livre)
    search_text: Mapped[str | None] = mapped_column(Text)
    props: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=text("'{}'::jsonb"))
    # dbIds abaixo da peça e dos membros da montagem (clique no 3D em qualquer parte)
    member_dbids: Mapped[list[Any]] = mapped_column(
        default=list, server_default=text("'[]'::jsonb")
    )
    mark_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("marks.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VersionPropertyName(Base):
    """(grupo, propriedade) presentes nos elementos de uma versão.

    Permite filtrar "Nome=valor": os valores ficam em elements.props por grupo
    ({"Grupo": {"Nome": "valor"}}), e esta tabela diz em quais grupos o nome existe.
    Dado derivado do BIM (recriado a cada processamento).
    """

    __tablename__ = "version_property_names"

    version_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("model_versions.id", ondelete="CASCADE"), primary_key=True
    )
    group_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    prop_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    # Motor de filtros (0013): tipo inferido (text | number | date), peças com valor e
    # valores distintos. Calculados no processamento (piece_props.build_version).
    value_type: Mapped[str | None] = mapped_column(String(10))
    pieces: Mapped[int | None] = mapped_column(Integer)
    distinct_values: Mapped[int | None] = mapped_column(Integer)


class PieceProp(Base):
    """Valor de um campo numa peça (motor de filtros). Origem model (propriedade do
    modelo), system (categoria, nível, status...) ou factory (parâmetro da fábrica,
    copiado da marca). Derivado: reconstruído no processamento e sincronizado quando os
    valores da fábrica mudam (app/services/piece_props.py)."""

    __tablename__ = "piece_props"
    __table_args__ = (
        CheckConstraint("source IN ('model', 'factory', 'system')", name="ck_piece_props_source"),
        Index("ix_piece_props_version_key_text", "version_id", "source", "key", "value_text"),
        Index("ix_piece_props_version_key_num", "version_id", "source", "key", "value_num"),
        Index("ix_piece_props_version_key_date", "version_id", "source", "key", "value_date"),
        Index("ix_piece_props_piece_id", "piece_id"),
        Index("ix_piece_props_mark_source", "mark_id", "source"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    version_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("model_versions.id", ondelete="CASCADE")
    )
    piece_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("elements.id", ondelete="CASCADE"))
    mark_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("marks.id", ondelete="RESTRICT")
    )
    source: Mapped[str] = mapped_column(String(10))
    key: Mapped[str] = mapped_column(String(600))
    value_text: Mapped[str] = mapped_column(String(500))
    value_num: Mapped[Decimal | None] = mapped_column(Numeric)
    value_date: Mapped[date | None] = mapped_column(Date)
