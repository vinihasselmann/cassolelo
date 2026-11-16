"""Parâmetros da biblioteca incluídos em cada obra.

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-13

Decisão de 2026-11-13: um parâmetro da biblioteca (scope = global) não vale para nenhuma
obra até ser INCLUÍDO nela (`obra_params`). Retirar de uma obra não apaga os valores.
Backfill: cada parâmetro global ativo é incluído nas obras onde já tem valores, para
nada sumir das telas.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "obra_params",
        sa.Column(
            "obra_id",
            sa.BigInteger(),
            sa.ForeignKey("obras.id", ondelete="RESTRICT", name="fk_obra_params_obra_id_obras"),
            nullable=False,
        ),
        sa.Column(
            "def_id",
            sa.BigInteger(),
            sa.ForeignKey(
                "param_defs.id", ondelete="RESTRICT", name="fk_obra_params_def_id_param_defs"
            ),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "created_by",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="SET NULL", name="fk_obra_params_created_by_users"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("obra_id", "def_id", name="pk_obra_params"),
    )
    op.create_index("ix_obra_params_def_id", "obra_params", ["def_id"])
    op.execute(
        """
        INSERT INTO obra_params (obra_id, def_id)
        SELECT DISTINCT m.obra_id, d.id
          FROM param_defs d
          JOIN param_values v ON v.def_id = d.id
          JOIN marks m ON m.id = v.mark_id
         WHERE d.scope = 'global' AND d.active
           AND v.value IS NOT NULL AND jsonb_typeof(v.value) <> 'null' AND v.value <> '""'::jsonb
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index("ix_obra_params_def_id", table_name="obra_params")
    op.drop_table("obra_params")
