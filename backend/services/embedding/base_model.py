from abc import ABC, abstractmethod
from typing import List

class BaseEmbeddingModel(ABC):
    @abstractmethod
    def encode(self, texts: List[str]) -> List[List[float]]:
        '''Encodes a list of texts into their corresponding vector embeddings.'''
        pass