"""Ordem dos eixos da numeração por obra (2026-11-19).

Revision ID: 0022
Revises: 0021
Create Date: 2026-11-19

A sequência de montagem passou de X → Y → Z para Z → X → Y. As obras já numeradas pela
sequência (`unit_numbering = 'sequence'`) têm números dados em X → Y → Z e, no NWD, cada
versão nova liga as peças pela ordem: se a ordem mudasse para elas, as peças (e os
valores) trocariam de lugar dentro da marca. Por isso cada obra guarda a sua ordem:
`xyz` para as já numeradas, `zxy` (atual) para as demais.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "obras",
        sa.Column("sequence_axes", sa.String(3), nullable=False, server_default="zxy"),
    )
    op.create_check_constraint("ck_obras_sequence_axes", "obras", "sequence_axes IN ('zxy', 'xyz')")
    op.execute("UPDATE obras SET sequence_axes = 'xyz' WHERE unit_numbering = 'sequence'")


def downgrade() -> None:
    op.drop_constraint("ck_obras_sequence_axes", "obras", type_="check")
    op.drop_column("obras", "sequence_axes")
