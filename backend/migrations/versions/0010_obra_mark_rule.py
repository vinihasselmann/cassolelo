"""Regra de identificação das peças por obra.

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-13

`obras.mark_property_names`: parâmetros do modelo que dão o código da marca, em ordem de
prioridade (ex.: ["Nome da montagem", "Marca"]). `obras.category_property_names`: idem
para a categoria. Nulo = padrão do servidor (MARK_PROPERTY_NAMES / CATEGORY_PROPERTY_NAMES).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("obras", sa.Column("mark_property_names", postgresql.JSONB(), nullable=True))
    op.add_column("obras", sa.Column("category_property_names", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("obras", "category_property_names")
    op.drop_column("obras", "mark_property_names")
