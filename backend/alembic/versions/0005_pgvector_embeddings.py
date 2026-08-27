"""move dense vectors to PostgreSQL pgvector

Revision ID: 0005_pgvector_embeddings
Revises: 0004_pair_class_recommendation
Create Date: 2026-08-25
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005_pgvector_embeddings"
down_revision: str | None = "0004_pair_class_recommendation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VECTOR_DIMENSION = 384
TABLES = (
    "topic_embeddings",
    "tag_key_value_embeddings",
    "tag_group_centroids",
    "class_pair_embeddings",
    "class_pair_prototypes",
    "class_stream_context_prototypes",
)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    for table in TABLES:
        op.execute(
            f"""
            CREATE TABLE {table} (
                identity TEXT PRIMARY KEY,
                embedding vector({VECTOR_DIMENSION}) NOT NULL,
                payload JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        op.execute(
            f"CREATE INDEX idx_{table}_embedding_hnsw "
            f"ON {table} USING hnsw (embedding vector_cosine_ops)"
        )
        op.execute(
            f"CREATE INDEX idx_{table}_payload_gin ON {table} USING gin (payload)"
        )


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE {table}")
    # The extension is intentionally retained. It may be shared by other schemas
    # or later migrations even when this application's vector tables are removed.
