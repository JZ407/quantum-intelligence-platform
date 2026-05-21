"""Example: build knowledge base index from documents."""

import sys
import os

# Add project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rag_system.kb_manager import KnowledgeBaseManager
from rag_system.config import Config


def main():
    # Load config
    config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.yaml")
    if os.path.exists(config_path):
        config = Config.from_yaml(config_path)
    else:
        config = Config()

    kb = KnowledgeBaseManager(config)

    data_dir = config.get("kb.data_dir", "./data")
    if not os.path.exists(data_dir):
        print(f"[WARN] Data directory not found: {data_dir}")
        print("Please put your documents in ./data/ and re-run.")
        return

    print(f"[INFO] Ingesting documents from: {data_dir}")
    total = kb.ingest_directory(data_dir)
    print(f"[INFO] Total chunks ingested: {total}")
    print(f"[INFO] Stats: {kb.stats()}")

    # Save index (auto-detects format based on store type)
    kb.save()
    print(f"[INFO] Knowledge base built successfully.")


if __name__ == "__main__":
    main()
