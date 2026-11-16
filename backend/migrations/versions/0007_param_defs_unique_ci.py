"""param_defs: nome único sem diferenciar maiúsculas, só entre ativos (Fase 6.1).

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-11

Excluir é lógico (active=false); um nome excluído pode ser criado de novo.
A regra "global não colide com parâmetro de obra" é verificada no serviço.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("uq_param_defs_global_name", table_name="param_defs")
    op.drop_index("uq_param_defs_obra_name", table_name="param_defs")
    op.create_index(
        "uq_param_defs_global_name",
        "param_defs",
        [sa.text("lower(name)")],
        unique=True,
        postgresql_where=sa.text("scope = 'global' AND active"),
    )
    op.create_index(
        "uq_param_defs_obra_name",
        "param_defs",
        ["obra_id", sa.text("lower(name)")],
        unique=True,
        postgresql_where=sa.text("scope = 'obra' AND active"),
    )


def downgrade() -> None:
    op.drop_index("uq_param_defs_global_name", table_name="param_defs")
    op.drop_index("uq_param_defs_obra_name", table_name="param_defs")
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
