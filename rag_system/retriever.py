"""Retriever combining keyword and optional vector search."""

from typing import List, Dict, Any, Optional
from .vector_store import VectorStore
from .embedder import BaseEmbedder, Bm25Embedder


class HybridRetriever:
    """Simple retriever that uses a single primary strategy.
    Can be extended to merge results from multiple stores."""

    def __init__(self, store: VectorStore, embedder: BaseEmbedder,
                 top_k: int = 5, threshold: float = 0.0):
        self.store = store
        self.embedder = embedder
        self.top_k = top_k
        self.threshold = threshold

    def retrieve(self, query: str) -> List[Dict[str, Any]]:
        q_vec = self.embedder.embed(query)
        return self.store.search(q_vec, top_k=self.top_k, threshold=self.threshold)

    def retrieve_with_scores(self, query: str) -> List[Dict[str, Any]]:
        return self.retrieve(query)
