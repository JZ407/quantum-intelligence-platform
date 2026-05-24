"""
Full historical scrape: list pages + detail pages + LLM tagging.
Supports resume on interruption.
"""
import sys, os, time, re, pickle, json
from datetime import datetime
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, JSON, UniqueConstraint
from sqlalchemy.orm import declarative_base, sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'rag_system'))
from llm_client import LLMClient
import yaml

# Config
BASE_URL = 'http://www.qtc.com.cn'
COOKIE_PATH = 'D:/Claude_code/liangke_historical/qtc_cookies.pkl'
DB_PATH = 'D:/Claude_code/liangke_historical/historical_v2.db'
PAGE_DELAY = 1.0
DETAIL_DELAY = 3.0
LLM_BATCH_SIZE = 1  # process one article at a time for reliability

TAGS_LIST = [
    '量子计算', '科技前沿', '产品动态', '量子通信', '行业应用',
    '企业与机构', '硬件平台', '融资商业', '宏观态势', 'AI/ML',
    '半导体', '量子物理', '后量子密码', '融资', 'PQC', 'QKD',
    '量子纠错', '超导', 'NIST', '量子传感', '企业资讯',
    '光量子', '资本运作', '离子阱', '政策标准', '后量子迁移', 'arXiv',
]

# Database setup
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
    detail_fetched = Column(Integer, default=0)  # 0=listed only, 1=complete

    __table_args__ = (UniqueConstraint('article_type', 'liangke_id', name='uix_type_id'),)


class ScrapeProgress(Base):
    __tablename__ = 'scrape_progress'
    id = Column(Integer, primary_key=True)
    list_type = Column(String(20), nullable=False, unique=True)
    current_page = Column(Integer, default=0)
    total_articles = Column(Integer, default=0)
    last_scraped_at = Column(DateTime, default=datetime.now)
    finished = Column(Integer, default=0)


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
    else:
        for c in cookies:
            session.cookies.set(c['name'], c['value'], domain=c.get('domain'), path=c.get('path'))
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': BASE_URL + '/',
    })
    return session


def get_llm_client():
    cfg_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.yaml')
    cfg = yaml.safe_load(open(cfg_path, encoding='utf-8'))['llm']
    return LLMClient(
        provider='openai',
        api_key=cfg['api_key'],
        api_base=cfg['api_base'],
        model=cfg['model'],
        max_tokens=2048,
        timeout=120,
    )


def tag_article_llm(title: str, content: str, client: LLMClient) -> list:
    full_text = f"标题：{title}\n正文：{content[:600]}" if content else f"标题：{title}"
    prompt = f"""你是一位量子科技行业编辑。请根据以下文章内容，从标签列表中选择最合适的标签（可多选，通常2-4个）。

标签列表：{', '.join(TAGS_LIST)}

{full_text}

请只输出选中的标签，用逗号分隔，不要任何解释。如果没有合适的标签，输出：宏观态势"""
    messages = [
        {"role": "system", "content": "你是专业的量子科技编辑。只输出要求的标签，不要任何解释。"},
        {"role": "user", "content": prompt},
    ]
    try:
        resp = client.chat(messages)
        tags = [t.strip() for t in resp.replace('、', ',').replace('，', ',').split(',')]
        valid = [t for t in tags if t in TAGS_LIST]
        return valid if valid else ['宏观态势']
    except Exception as e:
        return ['宏观态势']


def scrape_list_pages(session, engine, list_type, max_pages=None):
    """Scrape all list pages for a given type. Stores into DB."""
    Session = sessionmaker(bind=engine)
    db_session = Session()

    # Check progress
    progress = db_session.query(ScrapeProgress).filter_by(list_type=list_type).first()
    if not progress:
        progress = ScrapeProgress(list_type=list_type)
        db_session.add(progress)
        db_session.commit()

    page = progress.current_page + 1
    total_inserted = progress.total_articles
    first_ids = []

    print(f'[INFO] Starting {list_type} from page {page}')
    while True:
        if max_pages and page > max_pages:
            break
        url = f'{BASE_URL}/{list_type}?page={page}'
        try:
            resp = session.get(url, timeout=60)
            if resp.status_code != 200:
                print(f'  Page {page}: HTTP {resp.status_code}, stopping')
                break
        except Exception as e:
            print(f'  Page {page}: error - {e}, retrying after delay')
            time.sleep(PAGE_DELAY * 3)
            continue

        soup = BeautifulSoup(resp.text, 'html.parser')

        # Container and link pattern varies by type
        if list_type == 'flash':
            container = soup.find('div', class_='flash-box') or soup.find('div', class_='flash-list')
            link_pattern = r'/flash/\d+\.html'
            id_pattern = r'/flash/(\d+)\.html'
        elif list_type == 'reference':
            container = soup.find('div', class_='term-list') or soup.find('div', class_='item-list')
            link_pattern = r'/reference/\d+\.html'
            id_pattern = r'/reference/(\d+)\.html'
        else:  # news uses /article/xxx.html inside div.news-list
            container = soup.find('div', class_='news-list')
            link_pattern = r'/article/\d+\.html'
            id_pattern = r'/article/(\d+)\.html'

        if not container:
            print(f'  Page {page}: no container found, stopping')
            break

        articles = []
        for a_tag in container.find_all('a', href=re.compile(link_pattern)):
            href = a_tag['href']
            title = a_tag.get_text(strip=True)
            if not title:
                continue
            # Clean title: extract from 【】 brackets
            m_title = re.search(r'【(.+?)】', title)
            if m_title:
                title = m_title.group(1)
            full_url = urljoin(BASE_URL, href)
            m = re.search(id_pattern, href)
            liangke_id = m.group(1) if m else href

            # Check duplicate
            existing = db_session.query(Article).filter_by(article_type=list_type, liangke_id=liangke_id).first()
            if existing:
                print(f'  Page {page}: first ID repeated, stopping')
                break
            articles.append((liangke_id, title, full_url))
            first_ids.append(liangke_id)

        if not articles:
            print(f'  Page {page}: no articles')
            break

        for liangke_id, title, full_url in articles:
            a = Article(
                article_type=list_type,
                liangke_url=full_url,
                liangke_id=liangke_id,
                title=title,
                detail_fetched=0,
            )
            db_session.add(a)
            total_inserted += 1

        db_session.commit()
        print(f'  Page {page}: {len(articles)} articles, total {total_inserted}')

        # Update progress
        progress.current_page = page
        progress.total_articles = total_inserted
        progress.last_scraped_at = datetime.now()
        db_session.commit()

        page += 1
        time.sleep(PAGE_DELAY)

    progress.finished = 1
    db_session.commit()
    db_session.close()
    print(f'[OK] {list_type} done: {total_inserted} articles total')


def scrape_all_details(session, engine, client):
    """Scrape detail pages and tag for all articles without detail."""
    Session = sessionmaker(bind=engine)
    db_session = Session()

    pending = db_session.query(Article).filter(Article.detail_fetched == 0).all()
    total = len(pending)
    print(f'[INFO] {total} articles pending for detail scraping')

    for i, art in enumerate(pending):
        try:
            print(f'  {i+1}/{total}: [{art.article_type}] {art.liangke_id} - {art.title[:40]}')
        except UnicodeEncodeError:
            print(f'  {i+1}/{total}: [{art.article_type}] {art.liangke_id}')
        try:
            resp = session.get(art.liangke_url, timeout=60)
            if resp.status_code != 200:
                print(f'    HTTP {resp.status_code}, skipping')
                continue
            soup = BeautifulSoup(resp.text, 'html.parser')

            content = ''
            liangke_date = ''

            if art.article_type == 'flash':
                flash_details = soup.find('div', class_='flash-details')
                if flash_details:
                    # Title from h2
                    h2 = flash_details.find('h2')
                    if h2:
                        art.title = h2.get_text(strip=True)
                    # Content from div.txt
                    txt_div = flash_details.find('div', class_='txt')
                    if txt_div:
                        for tag in txt_div.find_all(['script', 'style']):
                            tag.decompose()
                        content = txt_div.get_text(separator='\n', strip=True)
                    # Date
                    dm = re.search(r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})', flash_details.get_text())
                    if dm:
                        liangke_date = dm.group(1)

            elif art.article_type == 'news':
                h1 = soup.find('h1', class_='page-header')
                if h1:
                    art.title = h1.get_text(strip=True)
                content_div = soup.find('div', class_='content')
                if content_div:
                    for tag in content_div.find_all(['script', 'style']):
                        tag.decompose()
                    content = content_div.get_text(separator='\n', strip=True)
                # Date from span.time
                time_span = soup.find('span', class_='time')
                if time_span:
                    dm = re.search(r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})', time_span.get_text())
                    if dm:
                        liangke_date = dm.group(1)

            elif art.article_type == 'reference':
                h2 = soup.find('h2')
                if h2:
                    art.title = h2.get_text(strip=True)
                content_div = soup.find('div', class_='refer-txt')
                if content_div:
                    for tag in content_div.find_all(['script', 'style']):
                        tag.decompose()
                    content = content_div.get_text(separator='\n', strip=True)

            # Reference URL
            ref_url = ''
            ref_a = soup.find('a', string=re.compile(r'参考链接|参考来源'))
            if ref_a and ref_a.get('href'):
                ref_url = ref_a['href'].strip()
                if ref_url.startswith('/'):
                    ref_url = urljoin(BASE_URL, ref_url)

            art.content = content
            art.liangke_date = liangke_date
            art.reference_url = ref_url

            # LLM tagging
            tags = tag_article_llm(art.title, content, client)
            art.tags = tags
            try:
                print(f'    tags={tags}')
            except UnicodeEncodeError:
                print(f'    tags OK')

            art.detail_fetched = 1
            db_session.commit()

        except Exception as e:
            print(f'    Error: {e}')
            db_session.rollback()

        if i < total - 1:
            time.sleep(DETAIL_DELAY)

    db_session.close()
    print(f'[OK] Detail scraping done')


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--step', choices=['list', 'detail', 'all'], default='all')
    parser.add_argument('--type', choices=['flash', 'news', 'reference', 'all'], default='all')
    parser.add_argument('--max-pages', type=int, default=None)
    args = parser.parse_args()

    session = load_session()
    engine = get_engine()

    if args.step in ('list', 'all'):
        types = ['flash', 'news', 'reference'] if args.type == 'all' else [args.type]
        for t in types:
            print(f'\n{"="*60}')
            print(f'STEP 1: Scraping {t} list pages')
            print(f'{"="*60}')
            scrape_list_pages(session, engine, t, max_pages=args.max_pages)

    if args.step in ('detail', 'all'):
        print(f'\n{"="*60}')
        print(f'STEP 2: Scraping details + LLM tagging')
        print(f'{"="*60}')
        client = get_llm_client()
        print(f'[INFO] Using model: {client.model}')
        scrape_all_details(session, engine, client)

    # Print summary
    Session = sessionmaker(bind=engine)
    db_session = Session()
    counts = {}
    for t in ['flash', 'news', 'reference']:
        counts[t] = db_session.query(Article).filter_by(article_type=t).count()
    detailed = db_session.query(Article).filter_by(detail_fetched=1).count()
    print(f'\n[SUMMARY] Total: {sum(counts.values())} (flash={counts.get("flash",0)}, news={counts.get("news",0)}, ref={counts.get("reference",0)})')
    print(f'[SUMMARY] Detailed + tagged: {detailed}')
    print(f'[SUMMARY] DB: {DB_PATH}')
    db_session.close()


if __name__ == '__main__':
    main()
