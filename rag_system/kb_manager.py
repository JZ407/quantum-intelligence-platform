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
        # Hybrid: always maintain a BM25 store for keyword search
        self.bm25_store = VectorStore()
        self.bm25_embedder = Bm25Embedder(
            k1=self.config.get("kb.bm25_k1", 1.5),
            b=self.config.get("kb.bm25_b", 0.75),
        )

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
            # Stable chunk_id for debugging and alignment safety
            chunk_id_prefix = meta.pop("chunk_id_prefix", None)
            if chunk_id_prefix:
                meta["chunk_id"] = f"{chunk_id_prefix}_{i}"
            else:
                meta["chunk_id"] = f"{Path(source).stem}_{i}"
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

        # Hybrid: also populate BM25 store for keyword search
        # BM25 needs full rebuild on incremental adds (IDF depends on corpus)
        if len(self.bm25_store) > 0:
            all_docs = self.bm25_store.documents + [dict(d) for d in docs]
        else:
            all_docs = [dict(d) for d in docs]
        all_texts = [d["text"] for d in all_docs]
        self.bm25_embedder.fit(all_texts)
        bm25_vecs = self.bm25_embedder.embed_batch(all_texts)
        self.bm25_store = VectorStore()
        self.bm25_store.add_batch(all_docs, bm25_vecs)

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
            rerank_top_k=self.config.get("reranker.top_k", k * 4),
            bm25_store=self.bm25_store,
            bm25_embedder=self.bm25_embedder,
        )
        return self.retriever

    def enable_cross_en(self, en_config_path: str = None):
        """Enable cross-language fallback: when Pro results are weak, also search EN index."""
        if self.retriever is None:
            self.build_retriever()
        try:
            from .config import Config
            en_cfg = Config.from_yaml(en_config_path or
                os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config_en.yaml'))
            en_kb = KnowledgeBaseManager(en_cfg)
            en_kb.load()
            en_kb.build_retriever()
            self.retriever.en_retriever = en_kb.retriever
            print(f"[INFO] Cross-language EN search enabled (always-on)")
        except Exception as e:
            print(f"[WARN] Cross-language EN fallback not available: {e}")

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

    def query(self, question: str, top_k: Optional[int] = None,
              filter_tags: Optional[List[str]] = None,
              date_from: Optional[str] = None,
              date_to: Optional[str] = None) -> List[Dict[str, Any]]:
        """Keyword/semantic search only (no LLM). Supports metadata filtering."""
        if self.retriever is None:
            self.build_retriever(top_k)
        return self.retriever.retrieve(
            question, filter_tags=filter_tags,
            date_from=date_from, date_to=date_to
        )

    def ask(self, question: str, top_k: Optional[int] = None,
            system_prompt: Optional[str] = None,
            filter_tags: Optional[List[str]] = None,
            date_from: Optional[str] = None,
            date_to: Optional[str] = None) -> Dict[str, Any]:
        """Full RAG ask (retrieve + LLM answer). Supports metadata filtering."""
        if self.pipeline is None:
            self.build_pipeline()
        return self.pipeline.run(
            question, top_k=top_k, system_prompt=system_prompt,
            filter_tags=filter_tags, date_from=date_from, date_to=date_to
        )

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
        # Also save BM25 store
        bm25_path = path + ".bm25" if not path.endswith(".json") else path.replace(".json", ".bm25.json")
        self.bm25_store.save(bm25_path)
        print(f"[INFO] Index saved to {path} + {bm25_path}")

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
        # Load or rebuild BM25 store
        bm25_path = path + ".bm25" if not path.endswith(".json") else path.replace(".json", ".bm25.json")
        try:
            self.bm25_store.load(bm25_path)
            print(f"  + BM25 index loaded")
        except Exception:
            # Rebuild BM25 store from main docs
            self.bm25_embedder.fit(texts)
            bm25_vecs = self.bm25_embedder.embed_batch(texts)
            self.bm25_store = VectorStore()
            self.bm25_store.add_batch([dict(d) for d in self.store.documents], bm25_vecs)
            print(f"  + BM25 index rebuilt ({len(self.bm25_store)} chunks)")
        self._is_fitted = True
        print(f"[INFO] Index loaded from {path}")

    def refresh_metadata(self, source: str, metadata: Dict[str, Any]) -> int:
        """Update metadata for all chunks belonging to source.
        Does NOT recompute vectors; only rewrites the .docs file on save().
        Returns number of chunks updated.
        """
        count = 0
        for doc in self.store.documents:
            if doc.get("metadata", {}).get("source") == source:
                old_meta = doc["metadata"]
                chunk_index = old_meta.get("chunk_index")
                chunk_id = old_meta.get("chunk_id")
                doc["metadata"] = dict(metadata)
                doc["metadata"]["source"] = source
                if chunk_index is not None:
                    doc["metadata"]["chunk_index"] = chunk_index
                if chunk_id is not None:
                    doc["metadata"]["chunk_id"] = chunk_id
                count += 1
        return count

    def stats(self) -> Dict[str, Any]:
        return {
            "total_chunks": len(self.store),
            "embedder": type(self.embedder).__name__,
            "provider": self.config.get("embedding.provider", "bm25"),
        }
