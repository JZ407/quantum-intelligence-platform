"""Unified KB builder: scan data_all, auto-route to Pro/EN/Lite, build all three."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rag_system.kb_manager import KnowledgeBaseManager
from rag_system.lang_detect import detect_lang, route_to_kbs
from rag_system.loader import load_file

DATA_ALL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data_all')
CONFIG_MAP = {
    'pro': os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config_pro.yaml'),
    'en': os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config_en.yaml'),
}


def scan_files(data_dir: str) -> list:
    """Scan data directory for supported files."""
    from rag_system.loader import load_directory
    return load_directory(data_dir, recursive=True)


def main():
    files = scan_files(DATA_ALL)
    if not files:
        print(f'[INFO] No files found in {DATA_ALL}')
        return

    print(f'[INFO] Found {len(files)} files in data_all/')

    # Route files
    routing = {'pro': [], 'en': []}
    for f in files:
        try:
            text = f.get('content', '')
            if not text:
                text = load_file(f.get('source', ''))
        except Exception:
            pass
        targets = route_to_kbs(text)
        lang = detect_lang(text)
        fname = os.path.basename(f.get('source', ''))
        cn, en = lang['cn'], lang['en']
        print(f'  {fname[:60]:60s} → {",".join(targets):6s}  (CN={cn}, EN={en})')
        for t in targets:
            routing[t].append(f)

    # Build each KB
    for kb_name, docs in routing.items():
        if not docs:
            print(f'\n[SKIP] {kb_name}: no documents')
            continue
        config_path = CONFIG_MAP[kb_name]
        print(f'\n{"="*60}')
        print(f'Building {kb_name} KB ({len(docs)} docs) -> {config_path}')
        print(f'{"="*60}')

        from rag_system.config import Config
        cfg = Config.from_yaml(config_path)
        kb = KnowledgeBaseManager(cfg)

        for doc in docs:
            n = kb.ingest_text(doc['content'], source=doc['source'])
            src = doc.get('source', '')
            print(f'  {os.path.basename(src)} -> {n} chunks')

        data_dir = cfg.get('kb.data_dir')
        index_dir = cfg.get('kb.index_dir')
        os.makedirs(data_dir, exist_ok=True)
        os.makedirs(index_dir, exist_ok=True)
        index_path = os.path.join(index_dir, 'kb_index')
        kb.save(index_path)
        s = kb.stats()
        chunks = s.get('total_chunks', 0)
        docs = s.get('total_docs', 0)
        print(f'  [{kb_name}] Saved: {chunks} chunks, {docs} docs')


if __name__ == '__main__':
    main()
