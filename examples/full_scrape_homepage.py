"""
Full historical rescrape: homepage feed ?page=1~744 → type-specific extraction.
Replaces the old sub-page approach (/flash, /news, /reference) with the
homepage feed that goes much deeper (744 pages vs ~250 for sub-pages).

Usage: python examples/full_scrape_homepage.py [--resume] [--dry-run]
"""
import sys, os, time, re, pickle, json, argparse
from datetime import datetime
from collections import OrderedDict
import requests
from bs4 import BeautifulSoup
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, JSON, UniqueConstraint
from sqlalchemy.orm import declarative_base, sessionmaker

# ── Paths ──────────────────────────────────────────────────────────
BASE_URL = 'http://www.qtc.com.cn'
COOKIE_PATH = 'D:/Claude_code/liangke_historical/qtc_cookies.pkl'
DB_PATH = 'D:/Claude_code/liangke_historical/historical_v3.db'
MAX_PAGES = 744
DETAIL_DELAY = 2.0   # seconds between detail requests
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Referer': 'http://www.qtc.com.cn/',
}

# ── Database ────────────────────────────────────────────────────────
Base = declarative_base()

class Article(Base):
    __tablename__ = 'articles'
    id = Column(Integer, primary_key=True, autoincrement=True)
    article_type = Column(String(20), nullable=False)
    liangke_url = Column(String(1000), nullable=False)
    liangke_id = Column(String(50), nullable=False, index=True)
    title = Column(String(500), nullable=False)
    content = Column(Text)
    reference_url = Column(String(1000))
    liangke_date = Column(String(50))
    tags = Column(JSON)
    detail_fetched = Column(Integer, default=0)
    dedup_status = Column(String(50))
    __table_args__ = (UniqueConstraint('article_type', 'liangke_id', name='uix_type_id'),)


def get_engine():
    engine = create_engine(f'sqlite:///{DB_PATH}', pool_pre_ping=True, echo=False)
    Base.metadata.create_all(engine)
    return engine


def load_session():
    session = requests.Session()
    with open(COOKIE_PATH, 'rb') as f:
        cookies = pickle.load(f)
    if isinstance(cookies, dict):
        for k, v in cookies.items():
            session.cookies.set(k, v)
    elif isinstance(cookies, list):
        for c in cookies:
            if isinstance(c, dict):
                session.cookies.set(c.get('name', ''), c.get('value', ''),
                                    domain=c.get('domain'), path=c.get('path'))
    session.headers.update(HEADERS)
    return session


# ── Type-specific extractors (from scrape_daily.py) ────────────────

def _extract_flash(soup, url):
    """Flash pages: h2 title, body text from page, external reference link."""
    title = ''
    h2 = soup.find('h2')
    if h2:
        title = h2.get_text(strip=True)

    # Find the article body: first long paragraph after title/date
    content = ''
    body = soup.find('body')
    if body:
        text = body.get_text(separator='\n', strip=True)
        lines = [l.strip() for l in text.split('\n') if l.strip()]
        # Skip title and date lines
        start = 0
        for i, line in enumerate(lines):
            if title and line == title:
                start = i + 1
                break
            if re.match(r'\d{4}年\d{1,2}月\d{1,2}日', line):
                start = i + 1
                break
        # Take first substantial paragraph
        for i in range(start, min(start + 10, len(lines))):
            if len(lines[i]) > 20:
                content = lines[i]
                break
        if not content:
            content = '\n'.join(lines[start:start + 5])

    # Trim at Copyright/粤ICP
    for kw in ['Copyright', '粤ICP', '备案号']:
        pos = content.find(kw)
        if pos > 20:
            content = content[:pos].strip()

    # Extract reference link
    ref = _extract_reference_link(soup)
    return {'title': title, 'content': content, 'primary_reference': ref}


def _extract_reference(soup, url):
    """Reference pages: h2 title, div.refer-txt, trim headers/tails."""
    title = ''
    h2 = soup.find('h2')
    if h2:
        title = h2.get_text(strip=True)

    content = ''
    div = soup.find('div', class_='refer-txt')
    if div:
        content = div.get_text(separator='\n', strip=True)

    # Trim before 3rd ➔
    if content:
        arrows = [m.start() for m in re.finditer('➔', content)]
        if len(arrows) >= 3:
            content = content[arrows[2] + 1:].strip()

    # Trim after 作者单位
    for kw in ['作者单位：', '作者单位:']:
        pos = content.find(kw) if content else -1
        if pos > 0:
            content = content[:pos].strip()

    # Trim at Copyright
    for kw in ['Copyright', '粤ICP', '备案号']:
        pos = content.find(kw) if content else -1
        if pos > 20:
            content = content[:pos].strip()

    ref = _extract_reference_link(soup)
    return {'title': title, 'content': content, 'primary_reference': ref}


def _extract_article(soup, url):
    """Article pages: title + full body, trim nav+footer+references.

    Handles both modern layout (h1.page-header) and legacy layout (pre-2023,
    where h1 is the site logo and the real title is in <title> tag + body text).
    """
    title = ''
    # Modern layout: h1.page-header
    h1 = soup.find('h1', class_='page-header') or soup.find('h1')
    if h1:
        txt = h1.get_text(strip=True)
        # Detect site logo h1 (old layout) — these contain 量科网/量子科技中心
        if '量科' not in txt and '量子科技中心' not in txt:
            title = txt
    # Fallback: <title> tag (strip site suffix)
    if not title:
        ttag = soup.find('title')
        if ttag:
            title = ttag.get_text(strip=True).split('|')[0].strip()

    # Nav crumbs to skip (appear in body text on legacy pages)
    NAV_CRUMBS = {
        '首页', '快讯', '文章', '参考', '企服', 'VIP', '企业', '所有', '短讯',
        '量科快讯', '商业情报', '一点数据', '知识碎片', '实时快讯', '用户专享：',
        '我的帐户', '退出', '企业动态', '国际', '国内', '量子信息',
        '量子计算', '量子通信', '量子传感', '量子物理', '安全', 'PQC', 'QKD',
        'ArXiv更新', '按主题',
    }
    # Category/institution labels to skip (max 5 after title)
    META_SKIP = {
        '技术研究', '行业观点', '企业动态', '产业资讯',
        '宏观态势', '科技前沿', '产品动态', '企业资讯', '资本运作',
    }

    content = ''
    body = soup.find('body')
    if body:
        # Remove scripts and styles
        for noise in body.find_all(['script', 'style']):
            noise.decompose()
        # Also try to remove nav/header/footer if tagged (modern layout)
        for noise in body.find_all(['nav', 'header', 'footer']):
            noise.decompose()

        text = body.get_text(separator='\n', strip=True)
        lines = [l.strip() for l in text.split('\n') if l.strip()]

        # Find the real article title in the body text
        start_idx = 0
        for i, l in enumerate(lines):
            if title and title[:15] in l:
                start_idx = i + 1
                break

        # Skip post-title metadata lines (date, view count, category, short source name)
        skip_count = 0
        while start_idx + skip_count < len(lines) and skip_count < 5:
            l = lines[start_idx + skip_count]
            is_meta = (
                re.match(r'\d{4}-\d{2}-\d{2}', l) or           # YYYY-MM-DD date
                re.match(r'\d{4}年\d{1,2}月\d{1,2}日', l) or   # 中文日期
                (l.isdigit() and len(l) < 5) or                 # view count
                l in META_SKIP or                               # category tag
                (len(l) < 30 and not any(p in l for p in '，。！？'))  # short name
            )
            if is_meta:
                skip_count += 1
            else:
                break

        # Collect content lines
        result_lines = []
        for l in lines[start_idx + skip_count:]:
            # Skip nav crumbs
            if l in NAV_CRUMBS:
                continue
            # Stop at page footer (both modern and legacy)
            if any(kw in l for kw in [
                '量科网 - 量子科技中心', '粤ICP备', '粤公网安备', 'Copyright',
                '人气主题', '关于量科网', '联系方式', '在线投稿', '版权声明',
            ]):
                break
            if '参考链接¹' in l:
                break
            result_lines.append(l)

        content = '\n'.join(result_lines).strip()

        # Cleanup
        if '注册用户以继续' in content:
            content = content.split('注册用户以继续')[0].strip()

    ref = _extract_reference_link(soup)
    return {'title': title, 'content': content, 'primary_reference': ref}


def _extract_date(soup):
    """Extract date from a detail page. Fallback chain: meta → text regex."""
    # Meta tags
    for meta_prop in ['article:published_time']:
        meta = soup.find('meta', property=meta_prop)
        if meta and meta.get('content', '').strip():
            d = meta['content'].strip()[:10]
            if re.match(r'\d{4}-\d{2}-\d{2}', d):
                return d
    # Text regex: YYYY-MM-DD or 中文日期
    text = soup.get_text()[:3000]
    m = re.search(r'(\d{4}-\d{2}-\d{2})', text)
    if m:
        return m.group(1)
    m = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', text)
    if m:
        return f'{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}'
    return ''


def _extract_reference_link(soup):
    """Extract external reference link common to all page types."""
    for a in soup.find_all('a', href=True):
        href = a['href'].strip()
        if not href.startswith('http'):
            continue
        if any(n in href.lower() for n in ['beian.miit.gov.cn', 'qtc.com.cn',
                                            '/flash/', '/article/', '/reference/',
                                            'user/login', 'javascript:', 'mailto:']):
            continue
        text = a.get_text(strip=True)
        if text and len(text) > 2:
            return {'url': href, 'text': text[:200]}
    return None


# ── Discover articles from homepage feed ────────────────────────────

def discover_all_articles(session, max_pages=MAX_PAGES):
    """Scan homepage ?page=1..max_pages, extract all article links with metadata."""
    all_articles = OrderedDict()  # liangke_id -> article dict
    seen_on_pages = {}            # liangke_id -> first page seen

    for page in range(1, max_pages + 1):
        url = f'{BASE_URL}/?page={page}'
        try:
            resp = session.get(url, timeout=30)
            if resp.status_code != 200:
                print(f'  page={page}: HTTP {resp.status_code}')
                break
        except Exception as e:
            print(f'  page={page}: ERROR {e}')
            break

        soup = BeautifulSoup(resp.text, 'html.parser')
        new_on_page = {'flash': 0, 'article': 0, 'reference': 0}

        for a in soup.find_all('a', href=True):
            href = a['href'].strip()
            if not href.startswith(('/', 'http')):
                continue
            if href.startswith('http') and 'qtc.com.cn' not in href:
                continue

            # Match flash/article/reference URL patterns
            m = re.match(r'^/(flash|article|reference)/(\d+)\.html$', href)
            if not m:
                continue

            art_type = m.group(1)
            art_id = m.group(2)

            if art_id in all_articles:
                continue

            if art_id in seen_on_pages:
                continue
            seen_on_pages[art_id] = page

            # Title
            title = a.get_text(strip=True)
            if not title or len(title) < 3:
                continue

            # Date from nearby text
            date_str = ''
            elem = a
            for _ in range(5):
                if elem:
                    t = elem.get_text(separator=' ', strip=True)
                    dm = re.search(r'(\d{4}-\d{2}-\d{2})', t)
                    if dm:
                        date_str = dm.group(1)
                        break
                    elem = elem.find_parent()

            all_articles[art_id] = {
                'article_type': art_type,
                'liangke_url': BASE_URL + href,
                'liangke_id': art_id,
                'title': title,
                'liangke_date': date_str,
                'first_page': page,
            }
            new_on_page[art_type] += 1

        total_new = sum(new_on_page.values())
        if page % 50 == 1 or page == 1 or total_new == 0:
            print(f'  page={page:>4}: +{total_new:>3} (flash={new_on_page["flash"]}, '
                  f'article={new_on_page["article"]}, ref={new_on_page["reference"]}) '
                  f'cumulative={len(all_articles)}')

        if total_new == 0:
            print(f'  No new articles on page {page}, stopping pagination')
            break

        time.sleep(0.3)

    print(f'\nDiscovered {len(all_articles)} unique articles across {page} pages')
    return list(all_articles.values())


# ── Main ────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true', help='Only discover, no detail fetch')
    parser.add_argument('--resume', action='store_true', help='Skip already-fetched articles')
    parser.add_argument('--start-page', type=int, default=1)
    parser.add_argument('--max-pages', type=int, default=MAX_PAGES)
    args = parser.parse_args()

    session = load_session()
    engine = get_engine()
    Session = sessionmaker(bind=engine)

    # Step 1: Discover all articles from homepage feed
    print('=' * 60)
    print('STEP 1: Discovering articles from homepage feed')
    print('=' * 60)
    articles = discover_all_articles(session, max_pages=args.max_pages)
    if not articles:
        print('[ERROR] No articles discovered')
        return

    # Type summary
    type_counts = {}
    for a in articles:
        type_counts[a['article_type']] = type_counts.get(a['article_type'], 0) + 1
    print(f'Type distribution: {type_counts}')
    print(f'Date coverage: {articles[-1]["liangke_date"]} ~ {articles[0]["liangke_date"]}')

    if args.dry_run:
        print('[DRY-RUN] Skipping detail fetch')
        return

    # Step 2: Fetch details and insert
    print(f'\n{"=" * 60}')
    print('STEP 2: Fetching details + inserting')
    print('=' * 60)

    db_session = Session()
    inserted, skipped, empty = 0, 0, 0

    for i, art in enumerate(articles):
        art_id = art['liangke_id']
        art_type = art['article_type']
        url = art['liangke_url']

        # Check if already in DB
        if args.resume:
            existing = db_session.query(Article).filter_by(
                article_type=art_type, liangke_id=art_id, detail_fetched=1
            ).first()
            if existing:
                skipped += 1
                if (i + 1) % 100 == 0:
                    print(f'  [{i+1}/{len(articles)}] ... {inserted} new, {skipped} skipped')
                continue

        # Fetch detail
        try:
            resp = session.get(url, timeout=30)
            if resp.status_code != 200:
                print(f'  [{i+1}/{len(articles)}] HTTP {resp.status_code}: {art["title"][:50]}')
                skipped += 1
                continue
        except Exception as e:
            print(f'  [{i+1}/{len(articles)}] ERROR: {art["title"][:50]} -> {e}')
            skipped += 1
            continue

        soup = BeautifulSoup(resp.text, 'html.parser')

        if art_type == 'flash':
            detail = _extract_flash(soup, url)
        elif art_type == 'reference':
            detail = _extract_reference(soup, url)
        else:
            detail = _extract_article(soup, url)

        title = detail['title'] or art['title']
        content = detail['content']
        date = _extract_date(soup) or art['liangke_date']
        if len(content) < 20:
            empty += 1
            if empty <= 5:
                print(f'  [{i+1}/{len(articles)}] EMPTY content: {title[:60]}')
            skipped += 1
            continue

        ref_url = ''
        if detail['primary_reference']:
            ref_url = detail['primary_reference']['url']

        # Insert / update
        existing = db_session.query(Article).filter_by(
            article_type=art_type, liangke_id=art_id
        ).first()
        if existing:
            existing.title = title
            existing.content = content
            existing.reference_url = ref_url
            existing.liangke_date = date or existing.liangke_date
            existing.detail_fetched = 1
        else:
            db_session.add(Article(
                article_type=art_type,
                liangke_url=url,
                liangke_id=art_id,
                title=title,
                content=content,
                reference_url=ref_url,
                liangke_date=date,
                detail_fetched=1,
            ))
        inserted += 1

        if (i + 1) % 10 == 0:
            db_session.commit()
            print(f'  [{i+1}/{len(articles)}] {title[:70]}')

        time.sleep(DETAIL_DELAY)

    db_session.commit()
    print(f'\n[OK] Done: {inserted} inserted/updated, {skipped} skipped, {empty} empty')

    # Summary
    counts = {}
    for t in ['flash', 'article', 'reference']:
        counts[t] = db_session.query(Article).filter_by(article_type=t, detail_fetched=1).count()
    print(f'[SUMMARY] Total: {sum(counts.values())} (flash={counts.get("flash",0)}, '
          f'article={counts.get("article",0)}, ref={counts.get("reference",0)})')
    db_session.close()


if __name__ == '__main__':
    main()
