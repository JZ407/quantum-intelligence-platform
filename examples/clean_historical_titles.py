"""
Clean up historical DB titles by extracting real titles from title+content mix.
"""
import sqlite3

HISTORICAL_DB_PATH = 'D:/Claude_code/liangke_historical/historical.db'


def extract_real_title(title: str, content: str) -> str:
    """Extract real title from flash articles where title contains content."""
    if len(title) < 50 or not content:
        return title

    # Method 1: content starts with title suffix
    for i in range(min(80, len(title)), 5, -1):
        if content.startswith(title[i:]):
            real = title[:i].strip()
            if len(real) >= 10:
                return real

    # Method 2: longest overlap
    for i in range(min(80, len(title)), 5, -1):
        if title[i:] in content[:100]:
            real = title[:i].strip()
            if len(real) >= 10:
                return real

    # Method 3: punctuation cut
    for punct in ['。', '，', '；', '！', '？', '.', ',', ';', '!', '?']:
        idx = title[:80].rfind(punct)
        if idx > 10:
            return title[:idx + 1].strip()

    return title[:50].strip()


def main():
    conn = sqlite3.connect(HISTORICAL_DB_PATH)
    cursor = conn.cursor()

    cursor.execute('SELECT id, title, content FROM articles WHERE article_type = "flash"')
    rows = cursor.fetchall()

    updated = 0
    for row in rows:
        article_id, title, content = row
        real_title = extract_real_title(title, content)
        if real_title != title:
            cursor.execute('UPDATE articles SET title = ? WHERE id = ?', (real_title, article_id))
            updated += 1

    conn.commit()
    conn.close()
    print(f'[OK] Updated {updated}/{len(rows)} flash article titles')


if __name__ == '__main__':
    main()
