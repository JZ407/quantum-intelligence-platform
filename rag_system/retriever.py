"""Retriever combining keyword and optional vector search."""

from typing import List, Dict, Any, Optional
from .vector_store import VectorStore
from .embedder import BaseEmbedder, Bm25Embedder
from .reranker import BaseReranker


class HybridRetriever:
    """Simple retriever that uses a single primary strategy.
    Supports optional reranker for result refinement."""

    def __init__(self, store: VectorStore, embedder: BaseEmbedder,
                 top_k: int = 5, threshold: float = 0.0,
                 reranker: Optional[BaseReranker] = None,
                 rerank_top_k: Optional[int] = None):
        self.store = store
        self.embedder = embedder
        self.top_k = top_k
        self.threshold = threshold
        self.reranker = reranker
        # Reranker sees top-N candidates before final truncation
        self.rerank_top_k = rerank_top_k or top_k * 4

    def retrieve(self, query: str) -> List[Dict[str, Any]]:
        q_vec = self.embedder.embed(query)
        candidates = self.store.search(
            q_vec, top_k=self.rerank_top_k, threshold=self.threshold
        )
        if self.reranker is not None:
            candidates = self.reranker.rerank(query, candidates)
        return candidates[:self.top_k]

    def retrieve_with_scores(self, query: str) -> List[Dict[str, Any]]:
        return self.retrieve(query)
