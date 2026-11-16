"""version_reports: relatório de validação de marcas por versão (Fase 3.2).

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

T = "version_reports"


def upgrade() -> None:
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
        sa.Column("report", postgresql.JSONB(), nullable=False),
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
