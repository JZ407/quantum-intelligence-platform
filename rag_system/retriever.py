"""Retriever combining keyword and optional vector search."""

import json
from typing import List, Dict, Any, Optional
from .vector_store import VectorStore
from .embedder import BaseEmbedder, Bm25Embedder
from .reranker import BaseReranker


def _parse_tags(tags_val):
    """Parse tags from metadata which may be a JSON string or list."""
    if isinstance(tags_val, list):
        return tags_val
    if isinstance(tags_val, str):
        try:
            return json.loads(tags_val)
        except (json.JSONDecodeError, TypeError):
            return []
    return []


def _apply_metadata_filter(docs: List[Dict], tags: Optional[List[str]],
                           date_from: Optional[str], date_to: Optional[str]) -> List[Dict]:
    """Filter documents by metadata tags and date range."""
    results = []
    for doc in docs:
        meta = doc.get('metadata', {})
        # Tag filter: doc must have at least one matching tag
        if tags:
            doc_tags = _parse_tags(meta.get('tags', []))
            if not any(t in doc_tags for t in tags):
                continue
        # Date filter
        doc_date = meta.get('liangke_date', '')
        if date_from and doc_date < date_from:
            continue
        if date_to and doc_date > date_to:
            continue
        results.append(doc)
    return results


def _rrf_merge(list_a: List[Dict], list_b: List[Dict], k: int = 60) -> List[Dict]:
    """Reciprocal Rank Fusion: merge two ranked lists into one."""
    scores = {}
    seen = {}
    for rank, doc in enumerate(list_a):
        key = doc.get('metadata', {}).get('chunk_id') or doc.get('text', '')[:100]
        scores[key] = scores.get(key, 0) + 1.0 / (k + rank + 1)
        seen[key] = doc
    for rank, doc in enumerate(list_b):
        key = doc.get('metadata', {}).get('chunk_id') or doc.get('text', '')[:100]
        scores[key] = scores.get(key, 0) + 1.0 / (k + rank + 1)
        seen[key] = doc
    merged = [(seen[key], scores[key]) for key in scores]
    merged.sort(key=lambda x: x[1], reverse=True)
    return [doc for doc, _score in merged]


class HybridRetriever:
    """Retriever supporting dense (FAISS), sparse (BM25), or hybrid search.
    Supports optional reranker for result refinement and metadata filtering."""

    def __init__(self, store: VectorStore, embedder: BaseEmbedder,
                 top_k: int = 5, threshold: float = 0.0,
                 reranker: Optional[BaseReranker] = None,
                 rerank_top_k: Optional[int] = None,
                 bm25_store: Optional[VectorStore] = None,
                 bm25_embedder: Optional[BaseEmbedder] = None):
        self.store = store
        self.embedder = embedder
        self.top_k = top_k
        self.threshold = threshold
        self.reranker = reranker
        self.rerank_top_k = rerank_top_k or top_k * 4
        # Hybrid search: optional BM25 store + embedder
        self.bm25_store = bm25_store
        self.bm25_embedder = bm25_embedder or Bm25Embedder()
        self._hybrid_ready = bm25_store is not None
        # Cross-language: optional EN retriever for always-on bilingual search
        self.en_retriever: Optional['HybridRetriever'] = None

    def enable_hybrid(self, bm25_store: VectorStore, bm25_embedder: Optional[BaseEmbedder] = None):
        """Enable hybrid search with a BM25 vector store."""
        self.bm25_store = bm25_store
        if bm25_embedder:
            self.bm25_embedder = bm25_embedder
        self._hybrid_ready = True

    def retrieve(self, query: str,
                 filter_tags: Optional[List[str]] = None,
                 date_from: Optional[str] = None,
                 date_to: Optional[str] = None) -> List[Dict[str, Any]]:
        has_filter = bool(filter_tags or date_from or date_to)
        fetch_k = min(self.rerank_top_k * 3, len(self.store)) if has_filter else self.rerank_top_k

        # Dense search
        q_vec = self.embedder.embed(query)
        dense_results = self.store.search(q_vec, top_k=fetch_k, threshold=self.threshold)

        # Hybrid: also search BM25 store
        if self._hybrid_ready and self.bm25_store is not None:
            bm25_vec = self.bm25_embedder.embed(query)  # Dict[str, float] sparse vector
            sparse_results = self.bm25_store.search(bm25_vec, top_k=fetch_k, threshold=0.0)
            candidates = _rrf_merge(dense_results, sparse_results)
        else:
            candidates = dense_results

        if has_filter:
            candidates = _apply_metadata_filter(candidates, filter_tags, date_from, date_to)

        if self.reranker is not None:
            candidates = self.reranker.rerank(query, candidates)

        # Cross-language: always merge EN results when enabled
        if self.en_retriever:
            try:
                en_results = self.en_retriever.retrieve(
                    query, filter_tags=filter_tags,
                    date_from=date_from, date_to=date_to
                )
                candidates = _rrf_merge(candidates, en_results)
                if self.reranker is not None:
                    candidates = self.reranker.rerank(query, candidates)
            except Exception:
                pass

        return candidates[:self.top_k]

    def retrieve_with_scores(self, query: str) -> List[Dict[str, Any]]:
        return self.retrieve(query)
