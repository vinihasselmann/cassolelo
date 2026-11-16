"""Modelo de dados inicial (Fase 1.3).

Revision ID: 0001
Revises:
Create Date: 2026-11-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _id() -> sa.Column:  # type: ignore[type-arg]
    return sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True)


def _timestamps() -> list[sa.Column]:  # type: ignore[type-arg]
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def _authors(table: str) -> list[sa.Column]:  # type: ignore[type-arg]
    return [
        sa.Column(
            "created_by",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="SET NULL", name=f"fk_{table}_created_by_users"),
            nullable=True,
        ),
        sa.Column(
            "updated_by",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="SET NULL", name=f"fk_{table}_updated_by_users"),
            nullable=True,
        ),
    ]


def _fk(column: str, table: str, ref: str, ondelete: str) -> sa.ForeignKey:
    return sa.ForeignKey(f"{ref}.id", ondelete=ondelete, name=f"fk_{table}_{column}_{ref}")


def upgrade() -> None:
    op.create_table(
        "users",
        _id(),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        *_timestamps(),
        *_authors("users"),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.CheckConstraint(
            "role IN ('projetos', 'fabrica', 'admin', 'leitura')", name="ck_users_role"
        ),
    )

    op.create_table(
        "obras",
        _id(),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("acc_hub_id", sa.String(255), nullable=True),
        sa.Column("acc_project_id", sa.String(255), nullable=True),
        sa.Column("acc_folder_id", sa.String(512), nullable=True),
        sa.Column("acc_item_id", sa.String(512), nullable=True),
        *_timestamps(),
        *_authors("obras"),
        sa.PrimaryKeyConstraint("id", name="pk_obras"),
        sa.UniqueConstraint("code", name="uq_obras_code"),
    )

    op.create_table(
        "model_versions",
        _id(),
        sa.Column(
            "obra_id",
            sa.BigInteger(),
            _fk("obra_id", "model_versions", "obras", "RESTRICT"),
            nullable=False,
        ),
        sa.Column("acc_version_id", sa.String(512), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("urn", sa.String(1024), nullable=True),
        sa.Column("status", sa.String(20), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("published_by", sa.String(255), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        *_timestamps(),
        *_authors("model_versions"),
        sa.PrimaryKeyConstraint("id", name="pk_model_versions"),
        sa.UniqueConstraint("acc_version_id", name="uq_model_versions_acc_version_id"),
        sa.CheckConstraint(
            "status IN ('pending', 'translating', 'processing', 'ready', 'failed', 'no_translation')",
            name="ck_model_versions_status",
        ),
    )
    op.create_index(
        "ix_model_versions_obra_id_version_number", "model_versions", ["obra_id", "version_number"]
    )

    op.create_table(
        "marks",
        _id(),
        sa.Column(
            "obra_id", sa.BigInteger(), _fk("obra_id", "marks", "obras", "RESTRICT"), nullable=False
        ),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("category", sa.String(255), nullable=False),
        sa.Column(
            "review_status", sa.String(20), server_default=sa.text("'pending'"), nullable=False
        ),
        sa.Column("review_note", sa.Text(), nullable=True),
        *_timestamps(),
        *_authors("marks"),
        sa.PrimaryKeyConstraint("id", name="pk_marks"),
        sa.UniqueConstraint("obra_id", "code", "category", name="uq_marks_obra_id_code_category"),
        sa.CheckConstraint(
            "review_status IN ('pending', 'ok', 'issue')", name="ck_marks_review_status"
        ),
    )

    op.create_table(
        "elements",
        _id(),
        sa.Column(
            "version_id",
            sa.BigInteger(),
            _fk("version_id", "elements", "model_versions", "CASCADE"),
            nullable=False,
        ),
        sa.Column("external_id", sa.String(255), nullable=True),
        sa.Column("dbid", sa.Integer(), nullable=False),
        sa.Column("mark_raw", sa.String(255), nullable=True),
        sa.Column("category", sa.String(255), nullable=True),
        sa.Column(
            "props", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column(
            "mark_id",
            sa.BigInteger(),
            _fk("mark_id", "elements", "marks", "SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_elements"),
        sa.UniqueConstraint("version_id", "dbid", name="uq_elements_version_id_dbid"),
    )
    op.create_index("ix_elements_version_id_external_id", "elements", ["version_id", "external_id"])
    op.create_index("ix_elements_mark_id", "elements", ["mark_id"])
    op.create_index("ix_elements_props_gin", "elements", ["props"], postgresql_using="gin")

    op.create_table(
        "param_defs",
        _id(),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("type", sa.String(10), nullable=False),
        sa.Column("unit", sa.String(30), nullable=True),
        sa.Column("options", postgresql.JSONB(), nullable=True),
        sa.Column("required", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("categories", postgresql.JSONB(), nullable=True),
        sa.Column("scope", sa.String(10), nullable=False),
        sa.Column(
            "obra_id",
            sa.BigInteger(),
            _fk("obra_id", "param_defs", "obras", "RESTRICT"),
            nullable=True,
        ),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        *_timestamps(),
        *_authors("param_defs"),
        sa.PrimaryKeyConstraint("id", name="pk_param_defs"),
        sa.CheckConstraint(
            "type IN ('text', 'number', 'list', 'date', 'bool')", name="ck_param_defs_type"
        ),
        sa.CheckConstraint("scope IN ('global', 'obra')", name="ck_param_defs_scope"),
        sa.CheckConstraint(
            "(scope = 'global' AND obra_id IS NULL) OR (scope = 'obra' AND obra_id IS NOT NULL)",
            name="ck_param_defs_scope_obra",
        ),
    )
    op.create_index(
        "uq_param_defs_global_name",
        "param_defs",
        ["name"],
        unique=True,
        postgresql_where=sa.text("scope = 'global'"),
    )
    op.create_index(
        "uq_param_defs_obra_name",
        "param_defs",
        ["obra_id", "name"],
        unique=True,
        postgresql_where=sa.text("scope = 'obra'"),
    )

    op.create_table(
        "param_values",
        _id(),
        sa.Column(
            "mark_id",
            sa.BigInteger(),
            _fk("mark_id", "param_values", "marks", "RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "def_id",
            sa.BigInteger(),
            _fk("def_id", "param_values", "param_defs", "RESTRICT"),
            nullable=False,
        ),
        sa.Column("value", postgresql.JSONB(), nullable=True),
        sa.Column("row_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        *_timestamps(),
        *_authors("param_values"),
        sa.PrimaryKeyConstraint("id", name="pk_param_values"),
        sa.UniqueConstraint("mark_id", "def_id", name="uq_param_values_mark_id_def_id"),
    )

    op.create_table(
        "orphans",
        _id(),
        sa.Column(
            "mark_id",
            sa.BigInteger(),
            _fk("mark_id", "orphans", "marks", "RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "since_version_id",
            sa.BigInteger(),
            _fk("since_version_id", "orphans", "model_versions", "RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(20), server_default=sa.text("'open'"), nullable=False),
        sa.Column(
            "relinked_to",
            sa.BigInteger(),
            _fk("relinked_to", "orphans", "marks", "RESTRICT"),
            nullable=True,
        ),
        *_timestamps(),
        *_authors("orphans"),
        sa.PrimaryKeyConstraint("id", name="pk_orphans"),
        sa.CheckConstraint("status IN ('open', 'relinked', 'archived')", name="ck_orphans_status"),
    )
    op.create_index(
        "uq_orphans_open_mark_id",
        "orphans",
        ["mark_id"],
        unique=True,
        postgresql_where=sa.text("status = 'open'"),
    )

    op.create_table(
        "audit_log",
        _id(),
        sa.Column("entity", sa.String(50), nullable=False),
        sa.Column("entity_id", sa.String(64), nullable=False),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("before", postgresql.JSONB(), nullable=True),
        sa.Column("after", postgresql.JSONB(), nullable=True),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            _fk("user_id", "audit_log", "users", "SET NULL"),
            nullable=True,
        ),
        sa.Column("batch_id", sa.Uuid(), nullable=True),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_audit_log"),
    )
    op.create_index("ix_audit_log_entity_entity_id", "audit_log", ["entity", "entity_id"])
    op.create_index("ix_audit_log_batch_id", "audit_log", ["batch_id"])
    op.create_index("ix_audit_log_at", "audit_log", ["at"])

    op.create_table(
        "webhook_events",
        _id(),
        sa.Column("event_id", sa.String(255), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column(
            "received_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_webhook_events"),
        sa.UniqueConstraint("event_id", name="uq_webhook_events_event_id"),
    )


def downgrade() -> None:
    op.drop_table("webhook_events")
    op.drop_table("audit_log")
    op.drop_table("orphans")
    op.drop_table("param_values")
    op.drop_table("param_defs")
    op.drop_table("elements")
    op.drop_table("marks")
    op.drop_table("model_versions")
    op.drop_table("obras")
    op.drop_table("users")
