"""Reconciliação entre versões (Fase 7.2).

- marks.review_status: domínio {ok, review} (padrão ok). Os valores antigos
  (pending/issue) nunca foram usados pelo app e viram ok.
- orphans.status ganha "returned" (a marca voltou numa versão seguinte).
- version_diffs: resultado da reconciliação de cada versão com a anterior (JSONB).

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

T = "version_diffs"


def upgrade() -> None:
    op.drop_constraint("ck_marks_review_status", "marks", type_="check")
    op.execute("UPDATE marks SET review_status = 'ok' WHERE review_status IN ('pending', 'issue')")
    op.alter_column("marks", "review_status", server_default=sa.text("'ok'"))
    op.create_check_constraint(
        "ck_marks_review_status", "marks", "review_status IN ('ok', 'review')"
    )
    op.create_index(
        "ix_marks_obra_id_review",
        "marks",
        ["obra_id"],
        postgresql_where=sa.text("review_status = 'review'"),
    )

    op.drop_constraint("ck_orphans_status", "orphans", type_="check")
    op.create_check_constraint(
        "ck_orphans_status", "orphans", "status IN ('open', 'relinked', 'archived', 'returned')"
    )

    op.create_table(
        T,
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column(
            "version_id",
            sa.BigInteger(),
            sa.ForeignKey(
                "model_versions.id", ondelete="CASCADE", name=f"fk_{T}_version_id_model_versions"
            ),
            nullable=False,
        ),
        sa.Column(
            "prev_version_id",
            sa.BigInteger(),
            sa.ForeignKey(
                "model_versions.id",
                ondelete="SET NULL",
                name=f"fk_{T}_prev_version_id_model_versions",
            ),
            nullable=True,
        ),
        sa.Column("diff", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "created_by",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="SET NULL", name=f"fk_{T}_created_by_users"),
            nullable=True,
        ),
        sa.Column(
            "updated_by",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="SET NULL", name=f"fk_{T}_updated_by_users"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id", name=f"pk_{T}"),
        sa.UniqueConstraint("version_id", name=f"uq_{T}_version_id"),
    )


def downgrade() -> None:
    op.drop_table(T)
    op.drop_constraint("ck_orphans_status", "orphans", type_="check")
    op.execute("UPDATE orphans SET status = 'archived' WHERE status = 'returned'")
    op.create_check_constraint(
        "ck_orphans_status", "orphans", "status IN ('open', 'relinked', 'archived')"
    )
    op.drop_index("ix_marks_obra_id_review", table_name="marks")
    op.drop_constraint("ck_marks_review_status", "marks", type_="check")
    op.execute("UPDATE marks SET review_status = 'pending' WHERE review_status = 'review'")
    op.alter_column("marks", "review_status", server_default=sa.text("'pending'"))
    op.create_check_constraint(
        "ck_marks_review_status", "marks", "review_status IN ('pending', 'ok', 'issue')"
    )
