"""Motor de filtros: valores de cada peça por campo (piece_props) e tipos dos campos.

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-13

`piece_props`: uma linha por (peça, campo) com valor. As origens são:
- model: propriedades do modelo;
- system: categoria, nível, Nome da montagem, status...;
- factory: parâmetros da fábrica, copiados da marca para cada peça.
O valor fica como texto e, quando converte, também como número e/ou data. Os índices
(version_id, key, value_*) servem às regras do filtro.

`version_property_names` ganha o tipo inferido, o nº de peças e o nº de valores
distintos de cada propriedade do modelo, calculados no processamento.
Versões já processadas: `python -m app.cli piece-props backfill --all`.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "piece_props",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column(
            "version_id",
            sa.BigInteger(),
            sa.ForeignKey(
                "model_versions.id",
                ondelete="CASCADE",
                name="fk_piece_props_version_id_model_versions",
            ),
            nullable=False,
        ),
        sa.Column(
            "piece_id",
            sa.BigInteger(),
            sa.ForeignKey(
                "elements.id", ondelete="CASCADE", name="fk_piece_props_piece_id_elements"
            ),
            nullable=False,
        ),
        sa.Column(
            "mark_id",
            sa.BigInteger(),
            sa.ForeignKey("marks.id", ondelete="RESTRICT", name="fk_piece_props_mark_id_marks"),
            nullable=True,
        ),
        sa.Column("source", sa.String(10), nullable=False),
        sa.Column("key", sa.String(600), nullable=False),
        sa.Column("value_text", sa.String(500), nullable=False),
        sa.Column("value_num", sa.Numeric(), nullable=True),
        sa.Column("value_date", sa.Date(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_piece_props"),
        sa.CheckConstraint(
            "source IN ('model', 'factory', 'system')", name="ck_piece_props_source"
        ),
    )
    op.create_index(
        "ix_piece_props_version_key_text",
        "piece_props",
        ["version_id", "source", "key", "value_text"],
    )
    op.create_index(
        "ix_piece_props_version_key_num",
        "piece_props",
        ["version_id", "source", "key", "value_num"],
    )
    op.create_index(
        "ix_piece_props_version_key_date",
        "piece_props",
        ["version_id", "source", "key", "value_date"],
    )
    op.create_index("ix_piece_props_piece_id", "piece_props", ["piece_id"])
    op.create_index("ix_piece_props_mark_source", "piece_props", ["mark_id", "source"])

    op.add_column("version_property_names", sa.Column("value_type", sa.String(10), nullable=True))
    op.add_column("version_property_names", sa.Column("pieces", sa.Integer(), nullable=True))
    op.add_column(
        "version_property_names", sa.Column("distinct_values", sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("version_property_names", "distinct_values")
    op.drop_column("version_property_names", "pieces")
    op.drop_column("version_property_names", "value_type")
    op.drop_index("ix_piece_props_mark_source", table_name="piece_props")
    op.drop_index("ix_piece_props_piece_id", table_name="piece_props")
    op.drop_index("ix_piece_props_version_key_date", table_name="piece_props")
    op.drop_index("ix_piece_props_version_key_num", table_name="piece_props")
    op.drop_index("ix_piece_props_version_key_text", table_name="piece_props")
    op.drop_table("piece_props")
