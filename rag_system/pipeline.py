"""RAG Pipeline: retrieve context -> build prompt -> call LLM."""

from typing import List, Dict, Any, Optional
from .retriever import HybridRetriever
from .llm_client import LLMClient
from .config import Config


class RAGPipeline:
    """End-to-end RAG pipeline."""

    def __init__(self, retriever: HybridRetriever, llm_client: LLMClient,
                 config: Optional[Config] = None):
        self.retriever = retriever
        self.llm = llm_client
        self.config = config or Config()

    def run(self, question: str, top_k: Optional[int] = None,
            system_prompt: Optional[str] = None) -> Dict[str, Any]:
        """Execute full RAG pipeline.

        Returns dict with keys:
            - answer: str (LLM generated answer)
            - sources: list of retrieved chunks
            - context: str (formatted context string)
            - prompt: str (full prompt sent to LLM)
        """
        # 1. Retrieve relevant chunks
        k = top_k or self.config.get("kb.top_k", 5)
        results = self.retriever.retrieve(question)
        if len(results) > k:
            results = results[:k]

        # 2. Build context string
        context_parts = []
        total_len = 0
        max_ctx = self.config.get("rag.max_context_length", 3000)
        for i, r in enumerate(results, 1):
            text = r.get("text", "")
            source = r.get("metadata", {}).get("source", "unknown")
            part = f"[文档 {i}] 来源: {source}\n{text}\n"
            if total_len + len(part) > max_ctx:
                break
            context_parts.append(part)
            total_len += len(part)

        context = "\n".join(context_parts)

        # 3. Build prompt
        template = self.config.get("rag.context_template",
            "参考资料：\n{context}\n\n用户问题：{question}")
        prompt = template.format(context=context, question=question)

        # 4. Call LLM
        sys_prompt = system_prompt or self.config.get("llm.system_prompt", "")
        answer = self.llm.simple_chat(prompt, system_prompt=sys_prompt)

        return {
            "answer": answer,
            "sources": results,
            "context": context,
            "prompt": prompt,
        }
