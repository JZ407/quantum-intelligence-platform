"""
Scrape 光子盒 (quantumchina.com/bg) for report listings using Playwright.
"""
import sys, os, time, re, sqlite3

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'resources.db')
SOURCE = '光子盒'
BASE_URL = 'https://quantumchina.com/bg'


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        publisher TEXT,
        source_url TEXT,
        download_url TEXT UNIQUE,
        publish_date TEXT,
        abstract TEXT,
        source_site TEXT DEFAULT '光子盒',
        crawled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.commit()
    return conn


def scrape():
    from playwright.sync_api import sync_playwright
    conn = init_db()
    c = conn.cursor()

    print(f'[INFO] Launching browser...')
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(BASE_URL, wait_until='networkidle', timeout=30000)
        page.wait_for_timeout(3000)
        content = page.content()
        browser.close()

    from bs4 import BeautifulSoup
    soup = BeautifulSoup(content, 'html.parser')

    reports = []
    for a in soup.find_all('a', href=True):
        href = a.get('href', '')
        title = a.get_text(strip=True)
        if not title or len(title) < 5:
            continue
        if '/filedownload/' not in href and not title.endswith('.pdf'):
            continue

        if href.startswith('/'):
            href = 'https://quantumchina.com' + href

        parent_text = a.parent.get_text(strip=True) if a.parent else ''
        date_match = re.match(r'(\d{4}-\d{2}-\d{2})', parent_text)
        publish_date = date_match.group(1) if date_match else ''

        publisher = '光子盒研究院' if '全球' in title else '光子盒'

        reports.append({
            'title': title.replace('.pdf', ''),
            'download_url': href,
            'publisher': publisher,
            'publish_date': publish_date,
        })

    new_count = 0
    for r in reports:
        try:
            c.execute('''INSERT INTO reports (title, publisher, download_url, publish_date, source_site)
                        VALUES (?, ?, ?, ?, ?)''',
                     (r['title'], r['publisher'], r['download_url'], r['publish_date'], SOURCE))
            new_count += 1
        except sqlite3.IntegrityError:
            pass

    conn.commit()
    conn.close()
    print(f'[INFO] Found {len(reports)} reports, {new_count} new')
    print(f'[OK] Saved to {DB_PATH}')


if __name__ == '__main__':
    scrape()
