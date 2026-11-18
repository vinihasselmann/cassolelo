"""Tipo da peça (filtro da lista: pilar, quadro, laje, escada, outros).

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-18

- `elements.piece_type`: classificação de `app/services/piece_type.py` (categoria, nome e
  tipo da peça). Versões já processadas: `python -m app.cli marks type --all` (lê o `props`
  guardado; não chama o APS). Versões novas já saem preenchidas.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("elements", sa.Column("piece_type", sa.String(12)))


def downgrade() -> None:
    op.drop_column("elements", "piece_type")
