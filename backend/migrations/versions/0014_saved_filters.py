"""Filtros salvos e esquemas de cores; atalhos da busca viram filtros de sistema.

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-13

- `saved_filters`: nome, escopo (personal | shared), dono, obra (nula = todas) e a
  definição no formato do motor de filtros. `system_key` marca os filtros de sistema.
- `color_schemes`: lista ordenada de regras {filtro, cor, rótulo}.
- Seed: os atalhos Pendentes, Parciais, A revisar, Novas na versão e Órfãs como filtros
  compartilhados de sistema (não editáveis). As definições são as mesmas de
  `app/services/saved_filters.py::SYSTEM_FILTERS` (um teste confere).
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _rule(key: str, value: object) -> dict[str, object]:
    return {"field": {"source": "system", "key": key}, "op": "eq", "value": value}


SYSTEM_FILTERS = [
    ("pending", "Pendentes", _rule("status", "Pendente")),
    ("partial", "Parciais", _rule("status", "Parcial")),
    ("review", "A revisar", _rule("status", "Revisar")),
    ("new", "Novas na versão", _rule("new", True)),
    ("orphans", "Órfãs", _rule("orphan", True)),
]


def _common(table: str) -> list[sa.schema.SchemaItem]:
    return [
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("scope", sa.String(10), nullable=False),
        sa.Column(
            "owner_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE", name=f"fk_{table}_owner_id_users"),
            nullable=True,
        ),
        sa.Column(
            "obra_id",
            sa.BigInteger(),
            sa.ForeignKey("obras.id", ondelete="CASCADE", name=f"fk_{table}_obra_id_obras"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "created_by",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="SET NULL", name=f"fk_{table}_created_by_users"),
            nullable=True,
        ),
        sa.Column(
            "updated_by",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="SET NULL", name=f"fk_{table}_updated_by_users"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id", name=f"pk_{table}"),
        sa.CheckConstraint("scope IN ('personal', 'shared')", name=f"ck_{table}_scope"),
        sa.CheckConstraint("scope <> 'personal' OR owner_id IS NOT NULL", name=f"ck_{table}_owner"),
    ]


def _name_indexes(table: str) -> None:
    op.create_index(
        f"uq_{table}_shared_name",
        table,
        [sa.text("lower(name)")],
        unique=True,
        postgresql_where=sa.text("scope = 'shared'"),
    )
    op.create_index(
        f"uq_{table}_personal_name",
        table,
        ["owner_id", sa.text("lower(name)")],
        unique=True,
        postgresql_where=sa.text("scope = 'personal'"),
    )
    op.create_index(f"ix_{table}_obra_id", table, ["obra_id"])


def upgrade() -> None:
    op.create_table(
        "saved_filters",
        *_common("saved_filters"),
        sa.Column("definition", JSONB(), nullable=False),
        sa.Column("system_key", sa.String(30), nullable=True),
        sa.CheckConstraint(
            "system_key IS NULL OR scope = 'shared'", name="ck_saved_filters_system_shared"
        ),
    )
    _name_indexes("saved_filters")
    op.create_index(
        "uq_saved_filters_system_key",
        "saved_filters",
        ["system_key"],
        unique=True,
        postgresql_where=sa.text("system_key IS NOT NULL"),
    )
    op.create_table(
        "color_schemes",
        *_common("color_schemes"),
        sa.Column("rules", JSONB(), nullable=False),
    )
    _name_indexes("color_schemes")

    table = sa.table(
        "saved_filters",
        sa.column("name", sa.String),
        sa.column("scope", sa.String),
        sa.column("definition", JSONB),
        sa.column("system_key", sa.String),
    )
    op.bulk_insert(
        table,
        [
            {
                "name": name,
                "scope": "shared",
                "system_key": key,
                "definition": json.loads(
                    json.dumps({"mode": "highlight", "logic": "and", "rules": [rule]})
                ),
            }
            for key, name, rule in SYSTEM_FILTERS
        ],
    )


def downgrade() -> None:
    for table in ("color_schemes", "saved_filters"):
        for index in (
            f"uq_{table}_shared_name",
            f"uq_{table}_personal_name",
            f"ix_{table}_obra_id",
        ):
            op.drop_index(index, table_name=table)
    op.drop_index("uq_saved_filters_system_key", table_name="saved_filters")
    op.drop_table("color_schemes")
    op.drop_table("saved_filters")
