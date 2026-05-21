"""Example: query the knowledge base with or without LLM."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rag_system.kb_manager import KnowledgeBaseManager
from rag_system.config import Config


def main():
    config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.yaml")
    if os.path.exists(config_path):
        config = Config.from_yaml(config_path)
    else:
        config = Config()

    kb = KnowledgeBaseManager(config)

    # Load existing index (auto-detect JSON or FAISS)
    index_dir = config.get("kb.index_dir", "./index")
    json_path = os.path.join(index_dir, "kb_index.json")
    faiss_path = os.path.join(index_dir, "kb_index.faiss")
    if os.path.exists(json_path):
        kb.load(json_path)
    elif os.path.exists(faiss_path):
        kb.load(os.path.join(index_dir, "kb_index"))
    else:
        print(f"[ERROR] Index not found in {index_dir}")
        print("Please run build_kb.py first to build the knowledge base.")
        return
    kb.build_pipeline()
    print(f"[INFO] Knowledge base loaded. {kb.stats()}")
    print("Enter questions (empty line to quit):\n")

    while True:
        try:
            q = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not q:
            break

        # Option 1: retrieval only
        print("\n--- Retrieved Context ---")
        results = kb.query(q)
        for r in results:
            src = r.get("metadata", {}).get("source", "unknown")
            print(f"  [score={r['score']}] [{src}]")
            print(f"  {r['text'][:200]}...")
            print()

        # Option 2: full RAG (requires valid LLM API key)
        if config.get("llm.api_key"):
            print("--- LLM Answer ---")
            try:
                result = kb.ask(q)
                print(result["answer"])
            except Exception as e:
                print(f"[ERROR] LLM call failed: {e}")
        else:
            print("[INFO] No LLM API key configured. Skipping generation.")
        print()


if __name__ == "__main__":
    main()
