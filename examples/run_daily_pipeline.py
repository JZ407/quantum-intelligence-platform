"""
Daily pipeline: scrape liangke news → sync to RAG Pro KB.

Usage:
    python examples/run_daily_pipeline.py

Steps:
    1. Import and run liangke_daily/core/scrape_daily.py (requires cookies)
    2. Import and run sync_liangke.py --days 1 (incremental ingest into Pro KB)

NOTE: Uses direct Python imports instead of subprocess to avoid Windows
GBK/encoding deadlocks that can hang the pipeline for 10+ minutes.
"""

import os
import sys
import time

# Use HuggingFace mirror to avoid connection timeouts in China
os.environ.setdefault('HF_ENDPOINT', 'https://hf-mirror.com')

RAG_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIANGKE_ROOT = os.path.join(os.path.dirname(RAG_ROOT), 'liangke_daily')

# Ensure liangke_daily modules are importable
sys.path.insert(0, os.path.join(LIANGKE_ROOT, 'core'))

# Ensure rag_system modules are importable
sys.path.insert(0, RAG_ROOT)


def run_scrape():
    print(f'\n{"="*50}')
    print('STEP: Scrape daily news from liangke')
    print(f'{"="*50}')
    start = time.time()
    try:
        import scrape_daily
        scrape_daily.main()
        elapsed = time.time() - start
        print(f'[OK] Scrape completed in {elapsed:.1f}s')
        return True
    except Exception as e:
        print(f'[ERROR] Scrape failed: {e}')
        return False


def run_sync():
    print(f'\n{"="*50}')
    print('STEP: Sync to RAG Pro KB')
    print(f'{"="*50}')
    start = time.time()
    try:
        from sync_liangke import main as sync_main
        sync_main(['--days', '1'])
        elapsed = time.time() - start
        print(f'[OK] Sync completed in {elapsed:.1f}s')
        return True
    except Exception as e:
        print(f'[ERROR] Sync failed: {e}')
        return False


def main():
    total_start = time.time()

    if not run_scrape():
        print('[ABORT] Scrape failed; skipping sync.')
        sys.exit(1)

    if not run_sync():
        sys.exit(1)

    total_elapsed = time.time() - total_start
    print(f'\n{sep}')
    print(f'Daily pipeline complete in {total_elapsed:.1f}s')
    print(sep)


if __name__ == '__main__':
    main()
