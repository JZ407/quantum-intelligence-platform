"""Knowledge Base Manager: build, update, query, persist."""

import os
from typing import List, Dict, Any, Optional
from pathlib import Path

from .config import Config
from .loader import load_directory, load_file
from .chunker import get_splitter
from .embedder import BaseEmbedder, Bm25Embedder, OpenAIEmbedder, SentenceTransformerEmbedder
from .vector_store import VectorStore, FaissVectorStore
from .retriever import HybridRetriever
from .reranker import BgeReranker
from .llm_client import LLMClient
from .pipeline import RAGPipeline


class KnowledgeBaseManager:
    """High-level manager for the local knowledge base."""

    def __init__(self, config: Optional[Config] = None):
        self.config = config or Config()
        self.embedder = self._create_embedder()
        self.store = self._create_store()
        self.retriever: Optional[HybridRetriever] = None
        self.pipeline: Optional[RAGPipeline] = None
        self._is_fitted = False

    def _create_embedder(self) -> BaseEmbedder:
        provider = self.config.get("embedding.provider", "bm25")
        if provider == "openai":
            return OpenAIEmbedder(
                api_key=self.config.get("embedding.api_key", ""),
                model=self.config.get("embedding.model", "text-embedding-3-small"),
                api_base=self.config.get("embedding.api_base", None),
            )
        if provider == "local":
            return SentenceTransformerEmbedder(
                model_name=self.config.get("embedding.model", "all-MiniLM-L6-v2"),
            )
        # Default: BM25
        return Bm25Embedder(
            k1=self.config.get("kb.bm25_k1", 1.5),
            b=self.config.get("kb.bm25_b", 0.75),
        )

    def _create_store(self):
        provider = self.config.get("embedding.provider", "bm25")
        if provider in ("openai", "local"):
            return FaissVectorStore()
        return VectorStore()

    def ingest_file(self, path: str) -> int:
        """Ingest a single file. Returns number of chunks added."""
        text = load_file(path)
        return self.ingest_text(text, source=path)

    def ingest_text(self, text: str, source: str = "unknown",
                    metadata: Optional[Dict[str, Any]] = None) -> int:
        """Ingest raw text."""
        splitter = get_splitter(
            method=self.config.get("kb.chunk_method", "recursive"),
            chunk_size=self.config.get("kb.chunk_size", 500),
            chunk_overlap=self.config.get("kb.chunk_overlap", 100),
        )
        chunks = splitter.split_text(text)

        docs = []
        for i, c in enumerate(chunks):
            meta = dict(metadata) if metadata else {}
            meta.update({"source": source, "chunk_index": i})
            docs.append({"text": c, "metadata": meta})

        if not docs:
            return 0

        texts = [d["text"] for d in docs]
        if not self._is_fitted:
            # BM25 requires refitting when vocab changes; dense embedders do not.
            if isinstance(self.embedder, Bm25Embedder):
                all_texts = texts
                if len(self.store) > 0:
                    all_texts = [d["text"] for d in self.store.documents] + texts
                self.embedder.fit(all_texts)
                if len(self.store) > 0:
                    old_docs = self.store.documents[:]
                    old_vecs = self.embedder.embed_batch([d["text"] for d in old_docs])
                    self.store = type(self.store)()
                    self.store.add_batch(old_docs, old_vecs)
            self._is_fitted = True

        vectors = self.embedder.embed_batch(texts)
        self.store.add_batch(docs, vectors)
        return len(docs)

    def ingest_directory(self, dir_path: str, recursive: bool = True) -> int:
        """Ingest all supported files in a directory."""
        files = load_directory(dir_path, recursive=recursive)
        total = 0
        for doc in files:
            n = self.ingest_text(doc["content"], source=doc["source"])
            total += n
            print(f"  [OK] {doc['source']} -> {n} chunks")
        return total

    def build_retriever(self, top_k: Optional[int] = None) -> HybridRetriever:
        """Build retriever from current store."""
        k = top_k or self.config.get("kb.top_k", 5)
        reranker = None
        reranker_model = self.config.get("reranker.model")
        if reranker_model:
            reranker = BgeReranker(model_name=reranker_model)
        self.retriever = HybridRetriever(
            self.store, self.embedder, top_k=k,
            reranker=reranker,
            rerank_top_k=self.config.get("reranker.top_k", k * 4)
        )
        return self.retriever

    def build_pipeline(self, llm_client: Optional[LLMClient] = None) -> RAGPipeline:
        """Build full RAG pipeline."""
        if self.retriever is None:
            self.build_retriever()
        if llm_client is None:
            llm_client = LLMClient(
                provider=self.config.get("llm.provider", "openai"),
                api_key=self.config.get("llm.api_key", ""),
                api_base=self.config.get("llm.api_base", None),
                model=self.config.get("llm.model", "gpt-4o-mini"),
                temperature=self.config.get("llm.temperature", 0.7),
                max_tokens=self.config.get("llm.max_tokens", 2048),
            )
        self.pipeline = RAGPipeline(self.retriever, llm_client, self.config)
        return self.pipeline

    def query(self, question: str, top_k: Optional[int] = None) -> List[Dict[str, Any]]:
        """Keyword/semantic search only (no LLM)."""
        if self.retriever is None:
            self.build_retriever(top_k)
        return self.retriever.retrieve(question)

    def ask(self, question: str, top_k: Optional[int] = None,
            system_prompt: Optional[str] = None) -> Dict[str, Any]:
        """Full RAG ask (retrieve + LLM answer)."""
        if self.pipeline is None:
            self.build_pipeline()
        return self.pipeline.run(question, top_k=top_k, system_prompt=system_prompt)

    def save(self, index_path: Optional[str] = None) -> None:
        if index_path is None:
            index_dir = self.config.get("kb.index_dir", "./index")
            os.makedirs(index_dir, exist_ok=True)
            if isinstance(self.store, FaissVectorStore):
                path = os.path.join(index_dir, "kb_index")
            else:
                path = os.path.join(index_dir, "kb_index.json")
        else:
            path = index_path
        self.store.save(path)
        print(f"[INFO] Index saved to {path}")

    def load(self, index_path: Optional[str] = None) -> None:
        if index_path is None:
            index_dir = self.config.get("kb.index_dir", "./index")
            if isinstance(self.store, FaissVectorStore):
                path = os.path.join(index_dir, "kb_index")
            else:
                path = os.path.join(index_dir, "kb_index.json")
        else:
            path = index_path
        self.store.load(path)
        # Re-fit embedder on loaded docs
        texts = [d["text"] for d in self.store.documents]
        self.embedder.fit(texts)
        self._is_fitted = True
        print(f"[INFO] Index loaded from {path}")

    def stats(self) -> Dict[str, Any]:
        return {
            "total_chunks": len(self.store),
            "embedder": type(self.embedder).__name__,
            "provider": self.config.get("embedding.provider", "bm25"),
        }
