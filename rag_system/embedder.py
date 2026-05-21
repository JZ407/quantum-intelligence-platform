"""Embedding providers: local BM25 and API-based semantic embeddings."""

import re
import math
from typing import List, Dict, Protocol, Optional


class BaseEmbedder(Protocol):
    def fit(self, documents: List[str]) -> None: ...
    def embed(self, text: str) -> Dict[str, float]: ...
    def embed_batch(self, texts: List[str]) -> List[Dict[str, float]]: ...


def _tokenize(text: str) -> List[str]:
    words = re.findall(r'[a-zA-Z]{2,}', text.lower())
    chars = re.findall(r'[一-鿿]', text)
    numbers = re.findall(r'\d+', text)
    return words + chars + numbers


class Bm25Embedder:
    """Pure-Python BM25 embedder (sparse vectors)."""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.idf: Dict[str, float] = {}
        self.doc_freq: Dict[str, int] = {}
        self.doc_len: List[int] = []
        self.avgdl: float = 0.0
        self.vocab: set = set()
        self._n_docs = 0

    def fit(self, documents: List[str]) -> None:
        tokenized = [_tokenize(d) for d in documents]
        self.doc_len = [len(t) for t in tokenized]
        total_len = sum(self.doc_len)
        self.avgdl = total_len / len(tokenized) if tokenized else 1.0

        self.doc_freq = {}
        for tokens in tokenized:
            unique = set(tokens)
            for t in unique:
                self.doc_freq[t] = self.doc_freq.get(t, 0) + 1

        self._n_docs = len(documents)
        self.idf = {}
        self.vocab = set()
        for term, df in self.doc_freq.items():
            self.vocab.add(term)
            # IDF smoothing
            idf_val = math.log((self._n_docs - df + 0.5) / (df + 0.5) + 1.0)
            self.idf[term] = idf_val

    def embed(self, text: str) -> Dict[str, float]:
        tokens = _tokenize(text)
        tf: Dict[str, int] = {}
        for t in tokens:
            tf[t] = tf.get(t, 0) + 1

        dl = len(tokens)
        vec = {}
        for term, freq in tf.items():
            if term not in self.vocab:
                continue
            idf = self.idf.get(term, 0)
            denom = freq + self.k1 * (1 - self.b + self.b * (dl / self.avgdl))
            vec[term] = idf * (freq * (self.k1 + 1)) / denom
        return vec

    def embed_batch(self, texts: List[str]) -> List[Dict[str, float]]:
        return [self.embed(t) for t in texts]


class OpenAIEmbedder:
    """OpenAI API embedder (requires api_key)."""

    def __init__(self, api_key: str, model: str = "text-embedding-3-small",
                 api_base: Optional[str] = None):
        self.api_key = api_key
        self.model = model
        self.api_base = api_base or "https://api.openai.com/v1"

    def fit(self, documents: List[str]) -> None:
        pass

    def embed(self, text: str) -> Dict[str, float]:
        import urllib.request
        import json
        data = json.dumps({
            "input": text,
            "model": self.model,
            "encoding_format": "float"
        }).encode('utf-8')
        req = urllib.request.Request(
            f"{self.api_base}/embeddings",
            data=data,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode('utf-8'))
            vec = result["data"][0]["embedding"]
            # Store as dense dict with integer keys for compatibility
            return {str(i): v for i, v in enumerate(vec)}

    def embed_batch(self, texts: List[str]) -> List[Dict[str, float]]:
        results = []
        for t in texts:
            results.append(self.embed(t))
        return results


class SentenceTransformerEmbedder:
    """Local dense semantic embedder using sentence-transformers."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(model_name)
        self._dim: Optional[int] = None

    def fit(self, documents: List[str]) -> None:
        pass

    def embed(self, text: str) -> Dict[str, float]:
        vec = self.model.encode(text, convert_to_numpy=True)
        return {str(i): float(v) for i, v in enumerate(vec)}

    def embed_batch(self, texts: List[str]) -> List[Dict[str, float]]:
        vecs = self.model.encode(texts, convert_to_numpy=True)
        return [{str(i): float(v) for i, v in enumerate(vec)} for vec in vecs]

    @property
    def dim(self) -> int:
        if self._dim is None:
            self._dim = len(self.embed("test"))
        return self._dim
