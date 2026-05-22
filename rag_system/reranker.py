"""Reranker for refining retrieval results using cross-encoders."""

from typing import List, Dict, Any, Optional


class BaseReranker:
    def rerank(self, query: str, documents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        ...


class BgeReranker(BaseReranker):
    """Cross-encoder reranker (e.g., BAAI/bge-reranker-base).
    Runs on CPU by default; GPU can be specified via device.
    """

    def __init__(self, model_name: str = "BAAI/bge-reranker-base",
                 device: Optional[str] = None):
        from sentence_transformers import CrossEncoder
        self.model = CrossEncoder(model_name, device=device)

    def rerank(self, query: str, documents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not documents:
            return []
        pairs = [(query, doc["text"]) for doc in documents]
        scores = self.model.predict(pairs, batch_size=8, show_progress_bar=False)
        for doc, score in zip(documents, scores):
            doc["rerank_score"] = round(float(score), 4)
        # Sort by rerank_score descending
        return sorted(documents, key=lambda x: x["rerank_score"], reverse=True)
