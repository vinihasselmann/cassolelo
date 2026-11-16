"""Montagens: categorias de corpo da peça por obra e membros de cada peça.

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-13

`obras.piece_category_names`: com valor, o .nwd/.rvt da obra é lido como modelo com
montagens (app/services/assemblies.py); nulo = regra antiga (nó com marca).
`elements.member_dbids`: dbIds abaixo da peça e dos membros da montagem (consolos,
alças...), para um clique em qualquer parte no 3D achar a peça. Índice GIN.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("obras", sa.Column("piece_category_names", postgresql.JSONB(), nullable=True))
    op.add_column(
        "elements",
        sa.Column(
            "member_dbids",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.create_index(
        "ix_elements_member_dbids",
        "elements",
        ["member_dbids"],
        postgresql_using="gin",
        postgresql_ops={"member_dbids": "jsonb_path_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_elements_member_dbids", table_name="elements")
    op.drop_column("elements", "member_dbids")
    op.drop_column("obras", "piece_category_names")
