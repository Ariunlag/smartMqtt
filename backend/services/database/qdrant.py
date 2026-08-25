import uuid
from typing import Any

from config import config
from qdrant_client import QdrantClient as QdrantSDKClient
from qdrant_client.models import Distance, PointStruct, VectorParams

TOPIC_COLLECTION = "topic_embeddings"
TAG_COLLECTION = "tag_key_value_embeddings"
GROUP_COLLECTION = "tag_group_centroids"
REPRESENTATION_COLLECTION = "stream_representation_embeddings"


class QdrantClient:
    def __init__(self, url: str, api_key: str | None):
        self.url = url
        self.client = QdrantSDKClient(url=url, api_key=api_key, timeout=10)

    def connect(self):
        try:
            self.client.get_collections()
            print(f"[QdrantClient] Connected to {self.url}")
        except Exception as exc:  # noqa: BLE001 - SDK transport errors vary by backend
            print(f"[QdrantClient] Connection failed: {exc}")

    def disconnect(self):
        self.client.close()

    def check_health(self) -> bool:
        try:
            self.client.get_collections()
            return True
        except Exception:  # noqa: BLE001 - readiness must collapse SDK transport errors
            return False

    def ensure_collection(self, name: str, vector_size: int):
        if not self.client.collection_exists(name):
            self.client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
            )

    @staticmethod
    def point_id(namespace: str, identity: str) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"influxai:{namespace}:{identity}"))

    def upsert(
        self,
        collection: str,
        identity: str,
        vector: list[float],
        payload: dict[str, Any],
    ):
        self.ensure_collection(collection, len(vector))
        self.client.upsert(
            collection_name=collection,
            points=[
                PointStruct(
                    id=self.point_id(collection, identity),
                    vector=vector,
                    payload=payload,
                )
            ],
            wait=True,
        )

    def nearest(self, collection: str, vector: list[float]):
        points = self.nearest_many(collection, vector, limit=1)
        return points[0] if points else None

    def nearest_many(
        self,
        collection: str,
        vector: list[float],
        limit: int = 10,
    ):
        if not self.client.collection_exists(collection):
            return []
        response = self.client.query_points(
            collection_name=collection,
            query=vector,
            limit=limit,
            with_payload=True,
            with_vectors=True,
        )
        return response.points

    def retrieve(self, collection: str, identity: str):
        if not self.client.collection_exists(collection):
            return None
        points = self.client.retrieve(
            collection_name=collection,
            ids=[self.point_id(collection, identity)],
            with_payload=True,
            with_vectors=True,
        )
        return points[0] if points else None

    def delete(self, collection: str, identity: str) -> None:
        """Delete one deterministic point when its collection exists."""
        if not self.client.collection_exists(collection):
            return
        self.client.delete(
            collection_name=collection,
            points_selector=[self.point_id(collection, identity)],
            wait=True,
        )

    def delete_where(self, collection: str, payload: dict[str, Any]) -> None:
        """Delete the bounded set of points matching exact payload fields."""
        if not self.client.collection_exists(collection):
            return
        point_ids = [
            point.id
            for point in self.all_points(collection)
            if all(point.payload.get(key) == value for key, value in payload.items())
        ]
        if point_ids:
            self.client.delete(
                collection_name=collection,
                points_selector=point_ids,
                wait=True,
            )

    def all_points(self, collection: str):
        if not self.client.collection_exists(collection):
            return []
        points = []
        offset = None
        while True:
            batch, offset = self.client.scroll(
                collection_name=collection,
                limit=256,
                offset=offset,
                with_payload=True,
                with_vectors=True,
            )
            points.extend(batch)
            if offset is None:
                return points


qdrant_client = QdrantClient(config.QDRANT_URL, config.QDRANT_API_KEY)
