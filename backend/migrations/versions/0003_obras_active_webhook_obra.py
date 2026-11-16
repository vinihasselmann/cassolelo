"""obras.active e webhook_events.obra_id (Fase 2.3).

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "obras", sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False)
    )
    op.add_column(
        "webhook_events",
        sa.Column(
            "obra_id",
            sa.BigInteger(),
            sa.ForeignKey("obras.id", ondelete="SET NULL", name="fk_webhook_events_obra_id_obras"),
            nullable=True,
        ),
    )
    op.create_index("ix_webhook_events_obra_id", "webhook_events", ["obra_id"])


def downgrade() -> None:
    op.drop_index("ix_webhook_events_obra_id", table_name="webhook_events")
    op.drop_column("webhook_events", "obra_id")
    op.drop_column("obras", "active")
