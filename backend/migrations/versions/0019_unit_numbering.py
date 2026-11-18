"""Numeração das unidades pela sequência de montagem.

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-18

- `elements.centroid`: centro de gravidade da peça, [x, y, z] em metros (origem interna do
  arquivo), calculado no navegador com o 3D carregado e guardado pelo servidor.
- `obras.unit_numbering`: como as unidades (PP001-1, -2…) foram numeradas:
  `provisional` (ordem estável por nível/nome, à espera dos centros de gravidade),
  `sequence` (renumeradas pela sequência de montagem Z → X → Y) ou `fixed` (travada na
  ordem estável: a obra já tinha valores por peça antes de ter os centros).

Obras existentes: com algum valor por peça, `fixed` (os números não mudam); sem, `provisional`.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("elements", sa.Column("centroid", postgresql.JSONB(astext_type=sa.Text())))
    op.add_column(
        "obras",
        sa.Column(
            "unit_numbering",
            sa.String(12),
            nullable=False,
            server_default=sa.text("'provisional'"),
        ),
    )
    op.create_check_constraint(
        "ck_obras_unit_numbering",
        "obras",
        "unit_numbering IN ('provisional', 'sequence', 'fixed')",
    )
    op.execute(
        """
        UPDATE obras SET unit_numbering = 'fixed'
        WHERE EXISTS (
            SELECT 1 FROM piece_values pv JOIN piece_units u ON u.id = pv.unit_id
            WHERE u.obra_id = obras.id AND pv.value IS NOT NULL
              AND pv.value <> 'null'::jsonb AND pv.value <> '""'::jsonb
        )
        """
    )


def downgrade() -> None:
    op.drop_constraint("ck_obras_unit_numbering", "obras", type_="check")
    op.drop_column("obras", "unit_numbering")
    op.drop_column("elements", "centroid")
