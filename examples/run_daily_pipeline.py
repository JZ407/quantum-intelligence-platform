"""
Daily pipeline: scrape liangke news → sync to RAG Pro KB.

Usage:
    python examples/run_daily_pipeline.py

Steps:
    1. Run liangke_daily/core/scrape_daily.py (requires cookies)
    2. Run sync_liangke.py --days 1 (incremental ingest into Pro KB)
"""

import os
import sys
import subprocess

RAG_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIANGKE_ROOT = os.path.join(os.path.dirname(RAG_ROOT), 'liangke_daily')
SCRAPER = os.path.join(LIANGKE_ROOT, 'core', 'scrape_daily.py')
SYNCER = os.path.join(RAG_ROOT, 'examples', 'sync_liangke.py')


def run_step(name, cmd, cwd):
    print(f'\n{"="*50}')
    print(f'STEP: {name}')
    print(f'{"="*50}')
    result = subprocess.run(
        [sys.executable, cmd],
        cwd=cwd,
        encoding='utf-8'
    )
    if result.returncode != 0:
        print(f'[ERROR] {name} failed with code {result.returncode}')
        return False
    return True


def main():
    # Step 1: scrape
    if not os.path.exists(SCRAPER):
        print(f'[ERROR] Scraper not found: {SCRAPER}')
        sys.exit(1)

    ok = run_step('Scrape daily news from liangke', SCRAPER, LIANGKE_ROOT)
    if not ok:
        print('[ABORT] Scrape failed; skipping sync.')
        sys.exit(1)

    # Step 2: sync to RAG
    if not os.path.exists(SYNCER):
        print(f'[ERROR] Syncer not found: {SYNCER}')
        sys.exit(1)

    ok = run_step('Sync to RAG Pro KB', SYNCER, RAG_ROOT)
    if not ok:
        sys.exit(1)

    print(f'\n{"="*50}')
    print('Daily pipeline complete.')
    print(f'{"="*50}')


if __name__ == '__main__':
    main()
