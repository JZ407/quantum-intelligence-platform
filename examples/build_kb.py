"""Example: build knowledge base index from documents."""

import sys
import os
import argparse

# Add project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rag_system.kb_manager import KnowledgeBaseManager
from rag_system.config import Config


def main():
    parser = argparse.ArgumentParser(description="Build knowledge base index.")
    parser.add_argument(
        "--config", "-c",
        default=None,
        help="Path to config file (default: ../config.yaml)"
    )
    parser.add_argument(
        "--incremental", "-i",
        action="store_true",
        help="Only ingest new files not already in the index"
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

    data_dir = config.get("kb.data_dir", "./data")
    if not os.path.exists(data_dir):
        print(f"[WARN] Data directory not found: {data_dir}")
        print("Please put your documents in the configured data dir and re-run.")
        return

    # Incremental mode: load existing index and skip already-indexed files
    existing_sources = set()
    if args.incremental:
        index_dir = config.get("kb.index_dir", "./index")
        json_path = os.path.join(index_dir, "kb_index.json")
        faiss_path = os.path.join(index_dir, "kb_index.faiss")
        if os.path.exists(json_path) or os.path.exists(faiss_path):
            kb.load()
            existing_sources = {
                d.get("metadata", {}).get("source", "")
                for d in kb.store.documents
            }
            print(f"[INFO] Incremental mode: {len(existing_sources)} files already indexed")
        else:
            print("[INFO] No existing index found; falling back to full build")

    print(f"[INFO] Ingesting documents from: {data_dir}")
    from rag_system.loader import load_directory
    files = load_directory(data_dir, recursive=True)
    total = 0
    skipped = 0
    for doc in files:
        if doc["source"] in existing_sources:
            print(f"  [SKIP] {doc['source']} (already indexed)")
            skipped += 1
            continue
        n = kb.ingest_text(doc["content"], source=doc["source"])
        total += n
        print(f"  [OK] {doc['source']} -> {n} chunks")

    print(f"[INFO] Total chunks ingested: {total}  (skipped: {skipped})")
    print(f"[INFO] Stats: {kb.stats()}")

    # Save index (auto-detects format based on store type)
    kb.save()
    print(f"[INFO] Knowledge base built successfully.")


if __name__ == "__main__":
    main()
