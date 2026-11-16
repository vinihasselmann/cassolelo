"""obras.acc_item_name: nome do arquivo no Docs, para exibição (Fase 2.1).

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("obras", sa.Column("acc_item_name", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("obras", "acc_item_name")
