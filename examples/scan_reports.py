"""
Scan articles for mentions of published reports/whitepapers/policy docs.
Uses LLM to identify downloadable documents and saves alerts.
"""
import sys, os, json, sqlite3
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'rag_system'))
from llm_client import LLMClient
import yaml

DAILY_DB = 'mysql+pymysql://scraper:scraper123@127.0.0.1:3306/liangke_scraper?charset=utf8mb4'
HISTORICAL_DB = 'D:/Claude_code/liangke_historical/historical_v2.db'
ALERT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'report_alerts.json')


def get_llm():
    cfg_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.yaml')
    cfg = yaml.safe_load(open(cfg_path, encoding='utf-8'))['llm']
    return LLMClient(
        provider='openai', api_key=cfg['api_key'], api_base=cfg['api_base'],
        model=cfg['model'], max_tokens=2048, timeout=180,
    )


def scan_articles(articles: list, client: LLMClient) -> list:
    """Batch scan articles for report mentions. Returns list of alerts."""
    if not articles:
        return []

    lines = [
        f"检查以下{len(articles)}条新闻，找出哪些提到了**公开发布的报告/白皮书/路线图/政策文件/战略文档**。",
        "筛选标准：新闻中明确提及某份文档已发布或即将发布（非学术论文，非一般新闻）。",
        "输出格式：序号|报告名称|发布机构|下载链接(如有)|一句话价值说明",
        "没有报告发布的新闻不要输出。\n"
    ]
    for i, art in enumerate(articles, 1):
        title = art.get('title', '')[:120]
        content = (art.get('content', '') or '')[:200]
        lines.append(f"{i}|{title}|{content}")

    messages = [
        {"role": "system", "content": "你是政策研究和行业报告追踪专家。只输出有报告发布的条目，不要解释。"},
        {"role": "user", "content": "\n".join(lines)},
    ]
    try:
        resp = client.chat(messages)
        alerts = []
        for line in resp.strip().split('\n'):
            if '|' not in line:
                continue
            parts = line.split('|')
            try:
                idx = int(parts[0].strip()) - 1
                if 0 <= idx < len(articles):
                    d = articles[idx].get('liangke_date', '')
                    if hasattr(d, 'strftime'):
                        d = d.strftime('%Y-%m-%d')
                    else:
                        d = str(d)[:10]
                    alerts.append({
                        'date': d,
                        'title': articles[idx].get('title', ''),
                        'report_name': parts[1].strip() if len(parts) > 1 else '',
                        'publisher': parts[2].strip() if len(parts) > 2 else '',
                        'url': parts[3].strip() if len(parts) > 3 else '',
                        'note': parts[4].strip() if len(parts) > 4 else '',
                        'source_article_url': articles[idx].get('liangke_url', ''),
                    })
            except (ValueError, IndexError):
                continue
        return alerts
    except Exception as e:
        print(f'  [ERROR] Report scan failed: {e}')
        return []


def main(days=1):
    client = get_llm()

    # Fetch recent articles from daily DB
    from sqlalchemy import create_engine
    import pandas as pd
    engine = create_engine(DAILY_DB)
    df = pd.read_sql(f"SELECT * FROM articles WHERE liangke_date >= DATE_SUB(CURDATE(), INTERVAL {days} DAY) ORDER BY liangke_date DESC", engine)
    articles = df.to_dict('records')
    print(f'[INFO] Scanning {len(articles)} articles from daily DB (last {days} days)...')

    alerts = scan_articles(articles, client)

    if alerts:
        # Load existing alerts
        existing = []
        if os.path.exists(ALERT_PATH):
            with open(ALERT_PATH, 'r', encoding='utf-8') as f:
                existing = json.load(f)

        # Merge: keep existing, add new ones (avoid duplicates by source URL)
        seen_urls = {a['source_article_url'] for a in existing}
        new_alerts = [a for a in alerts if a['source_article_url'] not in seen_urls]
        existing = new_alerts + existing  # new first

        with open(ALERT_PATH, 'w', encoding='utf-8') as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)

        print(f'\n{"="*60}')
        print(f'[ALERTS] {len(new_alerts)} new reports found (total: {len(existing)})')
        print(f'{"="*60}')
        for a in new_alerts:
            print(f"  [{a['date']}] {a['report_name']}")
            print(f"    发布: {a['publisher']}")
            if a['url']:
                print(f"    链接: {a['url']}")
            print(f"    价值: {a['note']}")
            print()
    else:
        print('[INFO] No new reports detected.')


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--days', type=int, default=1)
    args = parser.parse_args()
    main(days=args.days)
