"""Compatibility imports for the pgvector storage migration.

Production vector persistence now lives in ``services.database.vector``.  This
module remains temporarily so existing store imports can migrate without a flag day;
it does not import or connect to Qdrant.
"""

from services.database.vector import (
    GROUP_COLLECTION,
    REPRESENTATION_COLLECTION,
    TAG_COLLECTION,
    TOPIC_COLLECTION,
    PostgresVectorStore,
    VectorPoint,
    vector_store,
)

# Temporary compatibility alias. This is PostgreSQL-backed.
qdrant_client = vector_store
QdrantClient = PostgresVectorStore

__all__ = [
    "GROUP_COLLECTION",
    "REPRESENTATION_COLLECTION",
    "TAG_COLLECTION",
    "TOPIC_COLLECTION",
    "PostgresVectorStore",
    "QdrantClient",
    "VectorPoint",
    "qdrant_client",
    "vector_store",
]
