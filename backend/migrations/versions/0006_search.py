"""Busca (Fase 5.1): elements.level, elements.search_text e version_property_names.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-11

Versões já processadas ficam com level nulo e sem nomes de propriedade: reprocessar
(process_version) preenche. O backfill abaixo cobre o básico do texto livre.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("elements", sa.Column("level", sa.String(255), nullable=True))
    op.add_column("elements", sa.Column("search_text", sa.Text(), nullable=True))
    op.create_index("ix_elements_version_id_level", "elements", ["version_id", "level"])
    op.execute("UPDATE elements SET search_text = concat_ws(' | ', name, category, mark_raw)")
    op.create_table(
        "version_property_names",
        sa.Column(
            "version_id",
            sa.BigInteger(),
            sa.ForeignKey(
                "model_versions.id",
                ondelete="CASCADE",
                name="fk_version_property_names_version_id_model_versions",
            ),
            nullable=False,
        ),
        sa.Column("group_name", sa.String(255), nullable=False),
        sa.Column("prop_name", sa.String(255), nullable=False),
        sa.PrimaryKeyConstraint(
            "version_id", "group_name", "prop_name", name="pk_version_property_names"
        ),
    )


def downgrade() -> None:
    op.drop_table("version_property_names")
    op.drop_index("ix_elements_version_id_level", table_name="elements")
    op.drop_column("elements", "search_text")
    op.drop_column("elements", "level")
