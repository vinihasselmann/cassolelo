"""Acesso por obra (11.2).

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-19

- `users.all_obras`: o usuário vê todas as obras (padrão, inclusive para os existentes).
- `user_obras`: as obras que um usuário restrito (`all_obras = false`) vê. A linha some
  com o usuário ou com a obra (cascade). Admin vê sempre todas.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("all_obras", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_table(
        "user_obras",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("obra_id", sa.BigInteger(), nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_user_obras_user_id_users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["obra_id"], ["obras.id"], name="fk_user_obras_obra_id_obras", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name="fk_user_obras_created_by_users", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"], ["users.id"], name="fk_user_obras_updated_by_users", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("user_id", "obra_id", name="pk_user_obras"),
    )
    op.create_index("ix_user_obras_obra_id", "user_obras", ["obra_id"])


def downgrade() -> None:
    op.drop_index("ix_user_obras_obra_id", table_name="user_obras")
    op.drop_table("user_obras")
    op.drop_column("users", "all_obras")
