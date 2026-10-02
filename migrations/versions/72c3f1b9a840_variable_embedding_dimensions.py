"""Permit version-filtered native 256- and 384-dimensional vectors.

Revision ID: 72c3f1b9a840
Revises: 4add9c6cf395
"""

from alembic import op
from sqlalchemy import text

revision = "72c3f1b9a840"
down_revision = "4add9c6cf395"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE documents ALTER COLUMN vector TYPE vector")


def downgrade():
    if op.get_bind().dialect.name == "postgresql":
        incompatible = op.get_bind().scalar(
            text("SELECT count(*) FROM documents WHERE vector_dims(vector) <> 256")
        )
        if incompatible:
            raise RuntimeError("Reindex all documents with a 256-dimensional encoder before downgrade")
        op.execute("ALTER TABLE documents ALTER COLUMN vector TYPE vector(256)")
