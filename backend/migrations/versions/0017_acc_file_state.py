"""Arquivo excluído no Docs.

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-18

- `obras.acc_file_state` (ok | deleted | missing) e `obras.acc_file_state_at`: excluir o
  arquivo no Docs bloqueia a obra no app (só editar/excluir); restaurar libera de novo.
- `model_versions.status` passa a aceitar `deleted` (a versão "Deleted" que o Docs cria ao
  excluir). Versões já gravadas como `no_translation` são corrigidas no próximo sync.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BASE = "'pending', 'translating', 'processing', 'ready', 'failed', 'no_translation'"


def _version_status(values: str) -> None:
    op.drop_constraint("ck_model_versions_status", "model_versions", type_="check")
    op.create_check_constraint(
        "ck_model_versions_status", "model_versions", f"status IN ({values})"
    )


def upgrade() -> None:
    op.add_column(
        "obras",
        sa.Column("acc_file_state", sa.String(20), nullable=False, server_default=sa.text("'ok'")),
    )
    op.add_column("obras", sa.Column("acc_file_state_at", sa.DateTime(timezone=True)))
    op.create_check_constraint(
        "ck_obras_acc_file_state", "obras", "acc_file_state IN ('ok', 'deleted', 'missing')"
    )
    _version_status(f"{_BASE}, 'deleted'")


def downgrade() -> None:
    op.execute("UPDATE model_versions SET status = 'no_translation' WHERE status = 'deleted'")
    _version_status(_BASE)
    op.drop_constraint("ck_obras_acc_file_state", "obras", type_="check")
    op.drop_column("obras", "acc_file_state_at")
    op.drop_column("obras", "acc_file_state")
