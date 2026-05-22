"""Bridge: sync liangke_daily MySQL articles into RAG Pro knowledge base."""

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
    """Convert DB row to plain text for RAG ingestion."""
    lines = []
    lines.append(f"标题：{row['title']}")
    lines.append(f"量科网发布日期：{row['liangke_date']}")
    if pd.notna(row.get('original_date')):
        lines.append(f"原始来源日期：{row['original_date']}")
    if pd.notna(row.get('reference_title')) and pd.notna(row.get('reference_url')):
        lines.append(f"参考来源：{row['reference_title']} ({row['reference_url']})")
    if pd.notna(row.get('source_domain')):
        lines.append(f"来源域名：{row['source_domain']}")
    tags = row.get('tags')
    if tags:
        if isinstance(tags, list):
            tag_str = ', '.join(tags)
        else:
            tag_str = str(tags)
        lines.append(f"标签：{tag_str}")
    lines.append("")
    lines.append("正文：")
    lines.append(row['content'])
    return '\n'.join(lines)


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
    args = parser.parse_args()

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Determine date range
    if args.full:
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
        print('[INFO] No articles to sync. Exiting.')
        return

    # Write each article to txt
    written_files = []
    for _, row in df.iterrows():
        safe_title = safe_filename(row['title'])
        filename = f"{row['liangke_date']}_{row['id']}_{safe_title}.txt"
        filepath = os.path.join(OUTPUT_DIR, filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(article_to_txt(row))
        written_files.append(filepath)
        print(f'  [WRITE] {filename}')

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

    existing_sources = {
        d.get('metadata', {}).get('source', '')
        for d in kb.store.documents
    }

    # Incremental ingest
    synced_chunks = 0
    skipped_files = 0
    for filepath in written_files:
        if filepath in existing_sources:
            print(f'  [SKIP] {os.path.basename(filepath)} (already in KB)')
            skipped_files += 1
            continue

        with open(filepath, 'r', encoding='utf-8') as f:
            text = f.read()

        # Extract metadata for the chunk
        row = df[df.apply(lambda r: f"{r['liangke_date']}_{r['id']}_{safe_filename(r['title'])}.txt" == os.path.basename(filepath), axis=1)].iloc[0]
        metadata = {
            'title': row['title'],
            'liangke_date': str(row['liangke_date']),
            'reference_url': row.get('reference_url', ''),
            'source': 'liangke_daily',
        }

        n = kb.ingest_text(text, source=filepath, metadata=metadata)
        synced_chunks += n
        print(f'  [SYNC] {os.path.basename(filepath)} -> {n} chunks')

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
