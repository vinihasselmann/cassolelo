"""Busca sem diferenciar acentos: extensão unaccent e função f_unaccent.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-13

`unaccent()` é STABLE (depende do dicionário configurado); a função `f_unaccent(text)`
fixa o dicionário e é IMMUTABLE, para poder ser usada em índices no futuro.
A extensão é "trusted" desde o PostgreSQL 13: o dono do banco consegue criá-la.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION f_unaccent(text) RETURNS text
        LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
        AS $$ SELECT public.unaccent('public.unaccent'::regdictionary, $1) $$
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS f_unaccent(text)")
    op.execute("DROP EXTENSION IF EXISTS unaccent")
