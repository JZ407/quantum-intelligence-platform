"""Bridge: sync liangke_daily MySQL articles into RAG Pro knowledge base.

Strategy: txt files contain ONLY title + body (for embedding).
Tags, dates, and URLs are kept in metadata (no re-encoding needed on change).
"""

import sys
import os
import argparse
from datetime import datetime, timedelta

# Add project roots
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, 'D:/Claude_code/liangke_daily')

from sqlalchemy import create_engine
import pandas as pd

from rag_system.kb_manager import KnowledgeBaseManager
from rag_system.config import Config

DB_URL = 'mysql+pymysql://scraper:scraper123@127.0.0.1:3306/liangke_scraper?charset=utf8mb4'
OUTPUT_DIR = 'D:/Claude_code/rag_system/data_pro/liangke_daily'
CONFIG_PATH = 'D:/Claude_code/rag_system/config_pro.yaml'


def fetch_articles(start_date=None, end_date=None):
    """Fetch articles from MySQL with optional date filter."""
    engine = create_engine(DB_URL)
    query = 'SELECT * FROM articles'
    conditions = []
    if start_date:
        conditions.append(f"liangke_date >= '{start_date}'")
    if end_date:
        conditions.append(f"liangke_date <= '{end_date}'")
    if conditions:
        query += ' WHERE ' + ' AND '.join(conditions)
    query += ' ORDER BY liangke_date DESC, id DESC'
    return pd.read_sql(query, engine)


def article_to_txt(row):
    """Convert DB row to plain text for RAG embedding.
    ONLY title + body; no tags/dates/URLs (those live in metadata).
    """
    lines = []
    lines.append(f"标题：{row['title']}")
    lines.append("")
    lines.append(row['content'])
    return '\n'.join(lines)


def build_metadata(row):
    """Build metadata dict from DB row."""
    tags = row.get('tags')
    if tags:
        if isinstance(tags, list):
            tag_str = ', '.join(tags)
        else:
            tag_str = str(tags)
    else:
        tag_str = ''
    return {
        'title': row['title'],
        'liangke_date': str(row['liangke_date']) if pd.notna(row.get('liangke_date')) else '',
        'original_date': str(row['original_date']) if pd.notna(row.get('original_date')) else '',
        'reference_url': row.get('reference_url', '') or '',
        'reference_title': row.get('reference_title', '') or '',
        'source_domain': row.get('source_domain', '') or '',
        'tags': tag_str,
        'db_id': int(row['id']),
        'source': 'liangke_daily',
        'chunk_id_prefix': f"liangke_{int(row['id'])}",
    }


def safe_filename(title):
    """Make a filesystem-safe filename from title."""
    cleaned = ''.join(c for c in title if c.isalnum() or c in '_- ').strip()
    return cleaned[:50]


def main():
    parser = argparse.ArgumentParser(description='Sync liangke articles to RAG KB.')
    parser.add_argument('--days', type=int, default=1,
                        help='Sync articles from last N days (default: 1)')
    parser.add_argument('--since', type=str, default=None,
                        help='Sync since date (YYYY-MM-DD)')
    parser.add_argument('--full', action='store_true',
                        help='Sync all historical articles (use with caution)')
    parser.add_argument('--refresh-metadata', action='store_true',
                        help='Only refresh metadata for already-indexed articles (fast, no re-encoding)')
    args = parser.parse_args()

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Determine date range
    if args.refresh_metadata:
        start_date = None
        if args.since:
            start_date = args.since
        elif not args.full:
            start_date = (datetime.now() - timedelta(days=args.days)).strftime('%Y-%m-%d')
        print(f'[INFO] Refresh-metadata mode: fetching from {start_date or "all"}')
    elif args.full:
        start_date = None
        print('[INFO] Full sync mode: fetching ALL historical articles')
    elif args.since:
        start_date = args.since
        print(f'[INFO] Syncing articles since {start_date}')
    else:
        start_date = (datetime.now() - timedelta(days=args.days)).strftime('%Y-%m-%d')
        print(f'[INFO] Syncing articles from last {args.days} day(s) ({start_date} onwards)')

    # Fetch from MySQL
    print('[INFO] Fetching from MySQL...')
    df = fetch_articles(start_date=start_date)
    print(f'[INFO] Fetched {len(df)} articles')

    if len(df) == 0:
        print('[INFO] No articles to process. Exiting.')
        return

    # Write each article to txt (always overwrite so txt stays in sync with DB)
    written_files = []
    for _, row in df.iterrows():
        safe_title = safe_filename(row['title'])
        filename = f"{row['liangke_date']}_{row['id']}_{safe_title}.txt"
        filepath = os.path.join(OUTPUT_DIR, filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(article_to_txt(row))
        written_files.append(filepath)

    # Load RAG KB
    print(f'\n[INFO] Loading RAG knowledge base...')
    config = Config.from_yaml(CONFIG_PATH)
    kb = KnowledgeBaseManager(config)

    index_dir = config.get('kb.index_dir', './index')
    json_path = os.path.join(index_dir, 'kb_index.json')
    faiss_path = os.path.join(index_dir, 'kb_index.faiss')
    if os.path.exists(json_path) or os.path.exists(faiss_path):
        kb.load()
        print(f'[INFO] Loaded existing index ({kb.stats()["total_chunks"]} chunks)')
    else:
        print('[WARN] No existing index found; starting fresh')

    # Mode A: refresh metadata only (fast, no re-encoding)
    if args.refresh_metadata:
        refreshed = 0
        for _, row in df.iterrows():
            safe_title = safe_filename(row['title'])
            filename = f"{row['liangke_date']}_{row['id']}_{safe_title}.txt"
            filepath = os.path.join(OUTPUT_DIR, filename)
            meta = build_metadata(row)
            meta['source'] = filepath
            n = kb.refresh_metadata(filepath, meta)
            if n > 0:
                refreshed += n
                print(f'  [REFRESH] {filename} -> {n} chunks')
            else:
                print(f'  [MISSING] {filename} (not in KB yet)')
        kb.save()
        print(f'\n{"="*50}')
        print(f'Metadata refresh complete')
        print(f'  Chunks refreshed:   {refreshed}')
        print(f'  Total KB chunks:    {kb.stats()["total_chunks"]}')
        print(f'{"="*50}')
        return

    # Mode B: normal sync (incremental ingest)
    existing_sources = {
        d.get('metadata', {}).get('source', '')
        for d in kb.store.documents
    }

    synced_chunks = 0
    skipped_files = 0
    for _, row in df.iterrows():
        safe_title = safe_filename(row['title'])
        filename = f"{row['liangke_date']}_{row['id']}_{safe_title}.txt"
        filepath = os.path.join(OUTPUT_DIR, filename)

        if filepath in existing_sources:
            print(f'  [SKIP] {filename} (already indexed)')
            skipped_files += 1
            continue

        with open(filepath, 'r', encoding='utf-8') as f:
            text = f.read()

        meta = build_metadata(row)
        meta['source'] = filepath

        n = kb.ingest_text(text, source=filepath, metadata=meta)
        synced_chunks += n
        print(f'  [SYNC] {filename} -> {n} chunks')

    kb.save()
    print(f'\n{"="*50}')
    print(f'Sync complete')
    print(f'  Articles written:   {len(written_files)}')
    print(f'  New chunks synced:  {synced_chunks}')
    print(f'  Skipped (exists):   {skipped_files}')
    print(f'  Total KB chunks:    {kb.stats()["total_chunks"]}')
    print(f'{"="*50}')


if __name__ == '__main__':
    main()
