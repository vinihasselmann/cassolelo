"""Parâmetros por peça: nível do parâmetro, unidades de peça, ligações e valores.

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-16

Decisão de 2026-11-16 (docs/pecas/verificacao.md):
- `param_defs.level` ("mark" | "piece"); os existentes ficam "mark".
- `piece_units`: cada peça física de uma marca, numerada (o número nunca é reaproveitado),
  com a chave (externalId) da última ligação e a situação (linked | unlinked | orphan).
- `piece_unit_links`: unidade ↔ elemento por versão (key | order | new).
- `piece_values`: valor de um parâmetro por peça para uma unidade.
- Backfill: as versões prontas de cada obra, da mais antiga para a mais nova, ligadas
  pela MESMA regra do processamento (`app.services.unit_matching`, função pura). Ainda
  não há valores por peça: unidade que fica sem peça vira `unlinked`.
"""

from collections import defaultdict
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.services.unit_matching import NEW, ORDER, ElementIn, UnitIn, match

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NO_KEY_FORMATS = (".nwd", ".nwc")


def _author_columns() -> list[sa.Column]:  # type: ignore[type-arg]
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "created_by", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL", name=None)
        ),
        sa.Column(
            "updated_by", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL", name=None)
        ),
    ]


def upgrade() -> None:
    op.add_column(
        "param_defs",
        sa.Column("level", sa.String(10), server_default=sa.text("'mark'"), nullable=False),
    )
    op.create_check_constraint("ck_param_defs_level", "param_defs", "level IN ('mark', 'piece')")

    op.create_table(
        "piece_units",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "obra_id",
            sa.BigInteger(),
            sa.ForeignKey("obras.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "mark_id",
            sa.BigInteger(),
            sa.ForeignKey("marks.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("external_id", sa.String(255)),
        sa.Column("status", sa.String(10), server_default=sa.text("'linked'"), nullable=False),
        sa.Column(
            "since_version_id",
            sa.BigInteger(),
            sa.ForeignKey("model_versions.id", ondelete="SET NULL"),
        ),
        *_author_columns(),
        sa.UniqueConstraint("mark_id", "number", name="uq_piece_units_mark_id_number"),
        sa.CheckConstraint(
            "status IN ('linked', 'unlinked', 'orphan')", name="ck_piece_units_status"
        ),
        sa.CheckConstraint("number >= 1", name="ck_piece_units_number"),
    )
    op.create_index("ix_piece_units_obra_id_status", "piece_units", ["obra_id", "status"])

    op.create_table(
        "piece_unit_links",
        sa.Column(
            "version_id",
            sa.BigInteger(),
            sa.ForeignKey("model_versions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "unit_id",
            sa.BigInteger(),
            sa.ForeignKey("piece_units.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "element_id",
            sa.BigInteger(),
            sa.ForeignKey("elements.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("method", sa.String(10), nullable=False),
        sa.UniqueConstraint("version_id", "element_id", name="uq_piece_unit_links_version_element"),
        sa.CheckConstraint("method IN ('key', 'order', 'new')", name="ck_piece_unit_links_method"),
    )
    op.create_index("ix_piece_unit_links_unit_id", "piece_unit_links", ["unit_id"])

    op.create_table(
        "piece_values",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "unit_id",
            sa.BigInteger(),
            sa.ForeignKey("piece_units.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "def_id",
            sa.BigInteger(),
            sa.ForeignKey("param_defs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("value", sa.dialects.postgresql.JSONB()),
        sa.Column("row_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        *_author_columns(),
        sa.UniqueConstraint("unit_id", "def_id", name="uq_piece_values_unit_id_def_id"),
    )

    _backfill(op.get_bind())


def _backfill(conn: sa.Connection) -> None:
    """Unidades das versões prontas existentes (sem valores ainda: sobra = unlinked)."""
    obras = conn.execute(sa.text("SELECT id, coalesce(acc_item_name, '') FROM obras ORDER BY id"))
    for obra_id, item_name in obras.fetchall():
        use_key = not str(item_name).lower().endswith(NO_KEY_FORMATS)
        units: dict[int, list[dict[str, object]]] = defaultdict(list)  # mark_id -> unidades
        versions = conn.execute(
            sa.text(
                "SELECT id FROM model_versions WHERE obra_id = :o AND status = 'ready' "
                "ORDER BY version_number"
            ),
            {"o": obra_id},
        ).scalars()
        for version_id in list(versions):
            elements: dict[int, list[ElementIn]] = defaultdict(list)
            rows = conn.execute(
                sa.text(
                    "SELECT id, mark_id, external_id, level, name FROM elements "
                    "WHERE version_id = :v AND mark_id IS NOT NULL"
                ),
                {"v": version_id},
            )
            for eid, mark_id, ext, level, name in rows:
                elements[mark_id].append(ElementIn(eid, ext, level, name))
            for mark_id in sorted(set(elements) | set(units)):
                mine = units[mark_id]
                by_id = {int(str(u["id"])): u for u in mine}
                result = match(
                    [
                        UnitIn(int(str(u["id"])), int(str(u["number"])), u["external_id"], False)  # type: ignore[arg-type]
                        for u in mine
                    ],
                    elements.get(mark_id, []),
                    use_key=use_key,
                )
                for link in result.links:
                    if link.method == NEW:
                        unit_id = conn.execute(
                            sa.text(
                                "INSERT INTO piece_units (obra_id, mark_id, number, external_id, status) "
                                "VALUES (:o, :m, :n, :x, 'linked') RETURNING id"
                            ),
                            {
                                "o": obra_id,
                                "m": mark_id,
                                "n": link.new_number,
                                "x": link.external_id,
                            },
                        ).scalar_one()
                        mine.append(
                            {
                                "id": unit_id,
                                "number": link.new_number,
                                "external_id": link.external_id,
                            }
                        )
                    else:
                        unit_id = link.unit_id
                        unit = by_id[int(unit_id or 0)]
                        if link.method == ORDER:
                            unit["external_id"] = link.external_id
                        conn.execute(
                            sa.text(
                                "UPDATE piece_units SET external_id = :x, status = 'linked', "
                                "since_version_id = NULL WHERE id = :u"
                            ),
                            {"x": unit["external_id"], "u": unit_id},
                        )
                    conn.execute(
                        sa.text(
                            "INSERT INTO piece_unit_links (version_id, unit_id, element_id, method) "
                            "VALUES (:v, :u, :e, :m)"
                        ),
                        {"v": version_id, "u": unit_id, "e": link.element_id, "m": link.method},
                    )
                for left in result.leftover:
                    conn.execute(
                        sa.text(
                            "UPDATE piece_units SET status = 'unlinked', "
                            "since_version_id = coalesce(since_version_id, :v) "
                            "WHERE id = :u AND status = 'linked'"
                        ),
                        {"v": version_id, "u": left.id},
                    )


def downgrade() -> None:
    op.drop_table("piece_values")
    op.drop_index("ix_piece_unit_links_unit_id", table_name="piece_unit_links")
    op.drop_table("piece_unit_links")
    op.drop_index("ix_piece_units_obra_id_status", table_name="piece_units")
    op.drop_table("piece_units")
    op.drop_constraint("ck_param_defs_level", "param_defs", type_="check")
    op.drop_column("param_defs", "level")
