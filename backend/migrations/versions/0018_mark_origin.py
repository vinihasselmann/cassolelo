"""Origem da marca de cada peça.

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-18

- `elements.mark_source`: de qual parâmetro da regra da obra veio a marca da peça
  (ex.: "Nome da montagem").
- `elements.mark_alt`: os outros parâmetros da regra preenchidos na peça,
  [["Marca", "P01"], ...] na ordem da regra.

Versões já processadas: preencher com `python -m app.cli marks origin --all` (lê o `props`
guardado e a regra da obra; não chama o APS). Versões novas já saem preenchidas.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("elements", sa.Column("mark_source", sa.String(255)))
    op.add_column(
        "elements",
        sa.Column(
            "mark_alt",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("elements", "mark_alt")
    op.drop_column("elements", "mark_source")
