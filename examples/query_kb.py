"""Example: query the knowledge base with or without LLM."""

import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rag_system.kb_manager import KnowledgeBaseManager
from rag_system.config import Config


def main():
    parser = argparse.ArgumentParser(description="Query the knowledge base.")
    parser.add_argument(
        "--config", "-c",
        default=None,
        help="Path to config file (default: ../config.yaml)"
    )
    args = parser.parse_args()

    # Load config
    if args.config:
        config_path = args.config
    else:
        config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.yaml")

    if os.path.exists(config_path):
        config = Config.from_yaml(config_path)
        print(f"[INFO] Loaded config: {config_path}")
    else:
        config = Config()
        print("[WARN] No config found, using defaults.")

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
