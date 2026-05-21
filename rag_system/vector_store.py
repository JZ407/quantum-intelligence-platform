"""Vector store supporting sparse (BM25/TF-IDF) and dense vectors."""

import json
import os
import math
from typing import List, Dict, Any, Optional


class VectorStore:
    """In-memory vector store with cosine/dot-product retrieval."""

    def __init__(self):
        self.documents: List[Dict[str, Any]] = []
        self.vectors: List[Dict[str, float]] = []

    def add(self, doc: Dict[str, Any], vector: Dict[str, float]) -> None:
        self.documents.append(doc)
        self.vectors.append(vector)

    def add_batch(self, docs: List[Dict[str, Any]], vectors: List[Dict[str, float]]) -> None:
        if len(docs) != len(vectors):
            raise ValueError("docs and vectors must have same length")
        self.documents.extend(docs)
        self.vectors.extend(vectors)

    def search(self, query_vec: Dict[str, float], top_k: int = 5,
               threshold: float = 0.0) -> List[Dict[str, Any]]:
        """Retrieve top-k similar documents."""
        scored = []
        for doc, vec in zip(self.documents, self.vectors):
            score = self._score(query_vec, vec)
            if score >= threshold:
                entry = dict(doc)
                entry["score"] = round(score, 4)
                scored.append(entry)
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]

    def _score(self, a: Dict[str, float], b: Dict[str, float]) -> float:
        # Automatically detect sparse vs dense and choose appropriate metric
        if len(a) > 1000 or len(b) > 1000:
            # Likely sparse (BM25): use dot product
            return self._dot_product(a, b)
        else:
            # Likely dense: use cosine similarity
            return self._cosine(a, b)

    @staticmethod
    def _dot_product(a: Dict[str, float], b: Dict[str, float]) -> float:
        score = 0.0
        if len(a) > len(b):
            a, b = b, a
        for k, v in a.items():
            score += v * b.get(k, 0.0)
        return score

    @staticmethod
    def _cosine(a: Dict[str, float], b: Dict[str, float]) -> float:
        dot = 0.0
        na = 0.0
        nb = 0.0
        for k, v in a.items():
            na += v * v
            dot += v * b.get(k, 0.0)
        for v in b.values():
            nb += v * v
        denom = math.sqrt(na) * math.sqrt(nb)
        return dot / denom if denom else 0.0

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({"documents": self.documents, "vectors": self.vectors},
                      f, ensure_ascii=False, indent=2)

    def load(self, path: str) -> None:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.documents = data["documents"]
        self.vectors = [dict(v) for v in data["vectors"]]

    def __len__(self) -> int:
        return len(self.documents)


class FaissVectorStore:
    """Dense vector store backed by FAISS for fast approximate nearest neighbor search."""

    def __init__(self):
        self.index = None
        self.documents: List[Dict[str, Any]] = []
        self.dim: Optional[int] = None

    def _ensure_index(self, dim: int):
        import faiss
        if self.index is None:
            self.dim = dim
            self.index = faiss.IndexFlatIP(dim)

    def add(self, doc: Dict[str, Any], vector: Dict[str, float]) -> None:
        self.add_batch([doc], [vector])

    def add_batch(self, docs: List[Dict[str, Any]], vectors: List[Dict[str, float]]) -> None:
        import numpy as np
        import faiss
        if not vectors:
            return
        dim = len(vectors[0])
        self._ensure_index(dim)
        vecs = []
        for v in vectors:
            arr = np.array([v.get(str(i), 0.0) for i in range(self.dim)], dtype=np.float32)
            vecs.append(arr)
        vecs = np.array(vecs)
        faiss.normalize_L2(vecs)
        self.index.add(vecs)
        self.documents.extend(docs)

    def search(self, query_vec: Dict[str, float], top_k: int = 5,
               threshold: float = 0.0) -> List[Dict[str, Any]]:
        import numpy as np
        import faiss
        if self.index is None or not self.documents:
            return []
        dim = len(query_vec)
        arr = np.array([query_vec.get(str(i), 0.0) for i in range(dim)], dtype=np.float32)
        arr = arr.reshape(1, -1)
        faiss.normalize_L2(arr)
        scores, indices = self.index.search(arr, top_k)
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx == -1 or score < threshold:
                continue
            doc = dict(self.documents[idx])
            doc["score"] = round(float(score), 4)
            results.append(doc)
        return results

    def save(self, path: str) -> None:
        import faiss
        import json
        os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
        faiss.write_index(self.index, path + ".faiss")
        with open(path + ".docs", "w", encoding="utf-8") as f:
            json.dump(self.documents, f, ensure_ascii=False, indent=2)

    def load(self, path: str) -> None:
        import faiss
        import json
        self.index = faiss.read_index(path + ".faiss")
        with open(path + ".docs", "r", encoding="utf-8") as f:
            self.documents = json.load(f)
        self.dim = self.index.d

    def __len__(self) -> int:
        return len(self.documents)
