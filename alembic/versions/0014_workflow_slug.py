"""URL names for workflows and action definitions.

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-21

``workflows.slug`` is the readable part of the page URL (``/stages/<slug>``), unique per kind.
Existing rows get one derived from their name, with ``-2``, ``-3`` ... on collisions. The slug rule
is repeated here on purpose: a migration must not change when the application code does.
"""

import re
import unicodedata
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})


def _slugify(name: str, fallback: str) -> str:
    text = unicodedata.normalize("NFKD", name.lower().translate(_UMLAUTS))
    text = text.encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")[:80].strip("-") or fallback


def upgrade() -> None:
    with op.batch_alter_table("workflows") as batch:
        batch.add_column(sa.Column("slug", sa.String(100), nullable=True))
    conn = op.get_bind()
    taken: set[tuple[str, str]] = set()
    rows = conn.execute(sa.text("SELECT id, name, kind FROM workflows ORDER BY created_at, id"))
    for row_id, name, kind in rows.fetchall():
        base = _slugify(name, "stage" if kind == "workflow" else "action")
        slug, n = base, 2
        while (kind, slug) in taken:
            slug, n = f"{base}-{n}", n + 1
        taken.add((kind, slug))
        conn.execute(
            sa.text("UPDATE workflows SET slug = :s WHERE id = :i"), {"s": slug, "i": row_id}
        )
    with op.batch_alter_table("workflows") as batch:
        batch.alter_column("slug", existing_type=sa.String(100), nullable=False)
        batch.create_index("ux_workflows_kind_slug", ["kind", "slug"], unique=True)


def downgrade() -> None:
    with op.batch_alter_table("workflows") as batch:
        batch.drop_index("ux_workflows_kind_slug")
        batch.drop_column("slug")
