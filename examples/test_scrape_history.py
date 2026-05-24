"""
Test scrape: fetch a few pages of flash articles, tag them with LLM, export to Excel.
"""
import sys, os, time, re, pickle, json
from datetime import datetime
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'rag_system'))
from llm_client import LLMClient
import yaml

# Config
BASE_URL = 'http://www.qtc.com.cn'
COOKIE_PATH = 'D:/Claude_code/liangke_historical/qtc_cookies.pkl'
PAGE_DELAY = 1.0
MAX_PAGES = 3  # test with 3 pages
TARGET_TYPE = 'flash'

TAGS_LIST = [
    '量子计算', '科技前沿', '产品动态', '量子通信', '行业应用',
    '企业与机构', '硬件平台', '融资商业', '宏观态势', 'AI/ML',
    '半导体', '量子物理', '后量子密码', '融资', 'PQC', 'QKD',
    '量子纠错', '超导', 'NIST', '量子传感', '企业资讯',
    '光量子', '资本运作', '离子阱', '政策标准', '后量子迁移', 'arXiv',
]


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
    """Use LLM to assign tags from the 27-tag list."""
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
        print(f'  [WARN] LLM tagging failed: {e}')
        return ['宏观态势']


def scrape_list_pages(session, max_pages=MAX_PAGES):
    """Scrape flash list pages, return articles."""
    articles = []
    for page in range(1, max_pages + 1):
        url = f'{BASE_URL}/{TARGET_TYPE}?page={page}'
        print(f'[INFO] Fetching list page {page}: {url}')
        resp = session.get(url, timeout=60)
        if resp.status_code != 200:
            print(f'  [WARN] HTTP {resp.status_code}, stopping')
            break
        soup = BeautifulSoup(resp.text, 'html.parser')
        container = soup.find('div', class_='flash-box') or soup.find('div', class_='flash-list')
        if not container:
            print(f'  [WARN] Container not found, stopping')
            break
        items = container.find_all('a', href=re.compile(r'/flash/\d+\.html'))
        page_count = 0
        for a_tag in items:
            href = a_tag['href']
            title = a_tag.get_text(strip=True)
            if not title:
                continue
            full_url = urljoin(BASE_URL, href)
            m = re.search(r'/flash/(\d+)\.html', href)
            liangke_id = m.group(1) if m else href
            # Extract real title from 【】 brackets if present
            m_title = re.search(r'【(.+?)】', title)
            if m_title:
                title = '【' + m_title.group(1) + '】'
            articles.append({
                'article_type': TARGET_TYPE,
                'liangke_url': full_url,
                'liangke_id': liangke_id,
                'title': title,
                'liangke_date': '',
            })
            page_count += 1
        print(f'  Found {page_count} articles on page {page}')
        if page < max_pages:
            time.sleep(PAGE_DELAY)
    return articles


def scrape_detail(session, article: dict, client: LLMClient):
    """Fetch detail page content, reference URL, and generate tags."""
    url = article['liangke_url']
    try:
        resp = session.get(url, timeout=60)
        if resp.status_code != 200:
            print(f'  [WARN] Detail HTTP {resp.status_code} for {url}')
            return
        soup = BeautifulSoup(resp.text, 'html.parser')

        # Extract content, real title, and date from flash-details
        flash_details = soup.find('div', class_='flash-details')
        content = ''
        liangke_date = ''
        if flash_details:
            # Get real title from h2
            h2 = flash_details.find('h2')
            if h2:
                article['title'] = h2.get_text(strip=True)
            # Get content from div.txt
            txt_div = flash_details.find('div', class_='txt')
            if txt_div:
                for tag in txt_div.find_all(['script', 'style']):
                    tag.decompose()
                content = txt_div.get_text(separator='\n', strip=True)
            # Extract date (format: YYYY-MM-DD HH:MM) from spans
            date_match = re.search(r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})', flash_details.get_text())
            if date_match:
                liangke_date = date_match.group(1)

        # Reference URL
        ref_url = ''
        ref_a = soup.find('a', string=re.compile(r'参考链接|参考来源'))
        if ref_a and ref_a.get('href'):
            ref_url = ref_a['href'].strip()
            if ref_url.startswith('/'):
                ref_url = urljoin(BASE_URL, ref_url)

        article['content'] = content
        article['reference_url'] = ref_url
        article['liangke_date'] = liangke_date

        # LLM tagging
        tags = tag_article_llm(article['title'], content, client)
        article['tags'] = tags
        print(f'  [{article["liangke_id"]}] tags={tags} title={article["title"][:50]}')
    except Exception as e:
        print(f'  [ERROR] Detail fetch failed for {url}: {e}')
        article['content'] = ''
        article['reference_url'] = ''
        article['tags'] = ['宏观态势']


def main():
    session = load_session()
    client = get_llm_client()
    print(f'[INFO] Using model: {client.model}')

    # 1. Scrape list pages
    articles = scrape_list_pages(session)
    print(f'\n[INFO] Total list articles: {len(articles)}')

    # 2. Scrape details + tag
    print('[INFO] Fetching details and tagging...')
    for i, art in enumerate(articles):
        print(f'  {i+1}/{len(articles)}: {art["liangke_id"]}')
        scrape_detail(session, art, client)
        if i < len(articles) - 1:
            time.sleep(1)

    # 3. Export to Excel
    df = pd.DataFrame(articles)
    df['tags_str'] = df['tags'].apply(lambda x: ', '.join(x) if x else '')
    output_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'test_scrape.xlsx')
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    df.to_excel(output_path, index=False, engine='openpyxl')
    print(f'\n[OK] Exported {len(df)} articles to {output_path}')


if __name__ == '__main__':
    main()
