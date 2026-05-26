"""
De-duplicate historical articles based on:
1. Same reference_url → exact duplicate
2. High title similarity (>80%) within 3 days → near duplicate
Keeps the longest content version, flags duplicates.
"""
import sys, os, json, sqlite3
from difflib import SequenceMatcher

DB_PATH = 'D:/Claude_code/liangke_historical/historical_v2.db'


def title_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # Fetch all detailed articles ordered by date
    c.execute("SELECT id, title, content, reference_url, liangke_url, liangke_date FROM articles WHERE detail_fetched = 1 ORDER BY liangke_date")
    rows = c.fetchall()
    print(f'[INFO] Scanning {len(rows)} articles for duplicates...')

    dup_ids = set()
    groups = []
    kept = set()

    # Pass 1: exact URL duplicates
    url_map = {}
    for r in rows:
        url = r['reference_url'] or r['liangke_url'] or ''
        if url:
            key = url
            if key in url_map:
                prev = url_map[key]
                # Keep longer content
                if len(r['content'] or '') > len(prev['content'] or ''):
                    dup_ids.add(prev['id'])
                    url_map[key] = r
                else:
                    dup_ids.add(r['id'])
            else:
                url_map[key] = r

    print(f'  Pass 1 (exact URL): {len(dup_ids)} duplicates found')

    # Pass 2: title similarity within 3-day window
    title_dup = set()
    for i in range(len(rows)):
        if rows[i]['id'] in dup_ids:
            continue
        for j in range(i + 1, len(rows)):
            if rows[j]['id'] in dup_ids:
                continue
            # Check date proximity
            d1 = rows[i]['liangke_date'][:10]
            d2 = rows[j]['liangke_date'][:10]
            if d1 > d2:
                continue  # skip if more than 3 days apart (rough string compare)
            if d2 > d1:
                if d2 > d1:
                    try:
                        from datetime import datetime
                        dt1 = datetime.strptime(d1, '%Y-%m-%d')
                        dt2 = datetime.strptime(d2, '%Y-%m-%d')
                        if (dt2 - dt1).days > 3:
                            continue
                    except:
                        pass
            # Title similarity
            sim = title_similarity(rows[i]['title'], rows[j]['title'])
            if sim > 0.80:
                # Keep longer content
                if len(rows[i]['content'] or '') >= len(rows[j]['content'] or ''):
                    title_dup.add(rows[j]['id'])
                else:
                    title_dup.add(rows[i]['id'])

    dup_ids.update(title_dup)
    print(f'  Pass 2 (title similarity): {len(title_dup)} more duplicates')
    print(f'  Total duplicates: {len(dup_ids)}')

    if not dup_ids:
        print('[OK] No duplicates found.')
        conn.close()
        return

    # Show some examples
    dup_sample = list(dup_ids)[:10]
    placeholders = ','.join('?' * len(dup_sample))
    c.execute(f"SELECT id, title, liangke_date FROM articles WHERE id IN ({placeholders})", dup_sample)
    print('\nSample duplicates:')
    for r in c.fetchall():
        d = r['liangke_date'] or ''
        t = r['title'] or ''
        print(f'  [{d[:10]}] {t[:70]}')

    # Save duplicate IDs for review
    dup_list = list(dup_ids)
    with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'dup_ids.json'), 'w') as f:
        json.dump(dup_list, f)
    print(f'\n[INFO] Saved {len(dup_list)} duplicate IDs to data/dup_ids.json')
    print('[INFO] Run with --apply to mark these in DB (adds dedup_status field)')
    print('[INFO] Run with --revert to undo')

    conn.close()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--revert', action='store_true')
    args = parser.parse_args()

    if args.apply:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        # Add dedup_status column if needed
        try:
            c.execute('ALTER TABLE articles ADD COLUMN dedup_status TEXT DEFAULT "ok"')
        except sqlite3.OperationalError:
            pass
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'dup_ids.json')) as f:
            dup_ids = json.load(f)
        for did in dup_ids:
            c.execute('UPDATE articles SET dedup_status = ? WHERE id = ?', ('dup', did))
        conn.commit()
        conn.close()
        print(f'[APPLY] Marked {len(dup_ids)} articles as dup')
    elif args.revert:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE articles SET dedup_status = 'ok' WHERE dedup_status = 'dup'")
        conn.commit()
        conn.close()
        print('[REVERT] All dup marks cleared')
    else:
        main()
