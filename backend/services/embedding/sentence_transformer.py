from sentence_transformers import SentenceTransformer
from .base_model import BaseEmbeddingModel
from config import config

class STEmbeddingModel(BaseEmbeddingModel):
    def __init__(self, model_name: str | None = None):
        model_to_load = model_name or config.EMBEDDING_MODEL
        print(f"[Embedding] Loading model: {model_to_load} on device={config.EMBEDDING_DEVICE}")
        self.model = SentenceTransformer(model_to_load, device=config.EMBEDDING_DEVICE)

    def encode(self, texts):
        return self.model.encode(texts, normalize_embeddings=True).tolist()
