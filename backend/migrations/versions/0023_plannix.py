"""Importação do Plannix (2026-11-24).

Revision ID: 0023
Revises: 0022
Create Date: 2026-11-24

- `param_defs.source`: `manual` (padrão) ou `plannix`. Os parâmetros do Plannix (datas
  das etapas de produção) só são gravados pela importação; na tela ficam só leitura.
- `piece_units.plannix_code`: o "Código" da peça no Plannix, guardado na primeira
  importação que ligou a linha à unidade; nas seguintes, a linha acha a unidade por ele.
  Único dentro da obra.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "param_defs",
        sa.Column("source", sa.String(10), nullable=False, server_default="manual"),
    )
    op.create_check_constraint(
        "ck_param_defs_source", "param_defs", "source IN ('manual', 'plannix')"
    )
    op.add_column("piece_units", sa.Column("plannix_code", sa.String(30), nullable=True))
    op.create_index(
        "uq_piece_units_obra_plannix_code",
        "piece_units",
        ["obra_id", "plannix_code"],
        unique=True,
        postgresql_where=sa.text("plannix_code IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_piece_units_obra_plannix_code", table_name="piece_units")
    op.drop_column("piece_units", "plannix_code")
    op.drop_constraint("ck_param_defs_source", "param_defs", type_="check")
    op.drop_column("param_defs", "source")
