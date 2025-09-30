from sentence_transformers import SentenceTransformer
from .base_model import BaseEmbeddingModel

class STEmbeddingModel(BaseEmbeddingModel):
    def __init__(self, model_name="all-MiniLM-L6-v2"):
        self.model = SentenceTransformer(model_name)

    def encode(self, texts):
        return self.model.encode(texts, normalize_embeddings=True).tolist()
