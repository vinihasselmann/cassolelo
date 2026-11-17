"""Unidades órfãs (P5): unidade arquivada e ligação manual.

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-16

- `piece_units.status` passa a aceitar `archived` (órfã arquivada pela fábrica: os valores
  continuam guardados; a unidade só volta se a chave dela reaparecer no modelo).
- `piece_unit_links.method` passa a aceitar `manual` (religada à mão a outra peça da marca).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _status(values: str) -> None:
    op.drop_constraint("ck_piece_units_status", "piece_units", type_="check")
    op.create_check_constraint("ck_piece_units_status", "piece_units", f"status IN ({values})")


def _method(values: str) -> None:
    op.drop_constraint("ck_piece_unit_links_method", "piece_unit_links", type_="check")
    op.create_check_constraint(
        "ck_piece_unit_links_method", "piece_unit_links", f"method IN ({values})"
    )


def upgrade() -> None:
    _status("'linked', 'unlinked', 'orphan', 'archived'")
    _method("'key', 'order', 'new', 'manual'")


def downgrade() -> None:
    # Volta ao conjunto da 0015: arquivada vira órfã; manual vira "order" (conferir).
    op.execute("UPDATE piece_units SET status = 'orphan' WHERE status = 'archived'")
    op.execute("UPDATE piece_unit_links SET method = 'order' WHERE method = 'manual'")
    _status("'linked', 'unlinked', 'orphan'")
    _method("'key', 'order', 'new'")
