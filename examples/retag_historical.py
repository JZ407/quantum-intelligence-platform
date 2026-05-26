"""
Re-tag articles that were classified as 宏观态势 (catch-all default).
Batches articles and sends to LLM for proper 27-tag classification.
Supports resume on interruption.
"""
import sys, os, json, time, sqlite3

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'rag_system'))
from llm_client import LLMClient
import yaml

DB_PATH = 'D:/Claude_code/liangke_historical/historical_v2.db'
BATCH_SIZE = 30
TAGS_LIST = [
    '量子计算', '科技前沿', '产品动态', '量子通信', '行业应用',
    '企业与机构', '硬件平台', '融资商业', '宏观态势', 'AI/ML',
    '半导体', '量子物理', '后量子密码', '融资', 'PQC', 'QKD',
    '量子纠错', '超导', 'NIST', '量子传感', '企业资讯',
    '光量子', '资本运作', '离子阱', '政策标准', '后量子迁移', 'arXiv',
]


def get_llm():
    cfg_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.yaml')
    cfg = yaml.safe_load(open(cfg_path, encoding='utf-8'))['llm']
    return LLMClient(
        provider='openai', api_key=cfg['api_key'], api_base=cfg['api_base'],
        model=cfg['model'], max_tokens=2048, timeout=180,
    )


def retag_batch(articles: list, client: LLMClient) -> dict:
    """Send a batch to LLM for re-tagging. Returns {id: [tag1, tag2, ...]}."""
    lines = [
        f"为以下{len(articles)}篇量子科技新闻重新选择标签（每篇2-5个）。",
        f"可选标签：{', '.join(TAGS_LIST)}",
        "输出格式：文章编号|标签1,标签2,标签3",
        "注意：不要全部标为'宏观态势'，要根据标题和正文内容准确判断。\n"
    ]
    for i, art in enumerate(articles, 1):
        title = art['title'][:100]
        content = (art.get('content') or '')[:150]
        lines.append(f"{i}|{title}|{content}")

    messages = [
        {"role": "system", "content": "你是量子科技编辑。只输出要求的格式，不要解释。每篇文章根据实际内容打2-5个标签。"},
        {"role": "user", "content": "\n".join(lines)},
    ]
    try:
        resp = client.chat(messages)
        results = {}
        for line in resp.strip().split('\n'):
            if '|' not in line:
                continue
            parts = line.split('|')
            try:
                idx = int(parts[0].strip()) - 1
                if 0 <= idx < len(articles):
                    tags = [t.strip() for t in parts[1].replace('，', ',').split(',') if t.strip() in TAGS_LIST]
                    if not tags:
                        tags = ['宏观态势']  # fallback only if LLM gives nothing
                    results[articles[idx]['id']] = tags
            except (ValueError, IndexError):
                continue
        return results
    except Exception as e:
        print(f'  [ERROR] Batch failed: {e}')
        return {}


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # Fetch all articles with 宏观态势 in tags
    c.execute("SELECT id, title, content, tags FROM articles WHERE detail_fetched = 1 ORDER BY id")
    all_rows = c.fetchall()

    # Filter to only those that currently have 宏观态势
    retag_targets = []
    for row in all_rows:
        tags = row['tags']
        if isinstance(tags, str):
            tags = json.loads(tags)
        if isinstance(tags, list) and '宏观态势' in tags:
            retag_targets.append({'id': row['id'], 'title': row['title'], 'content': row['content']})

    total = len(retag_targets)
    print(f'[INFO] {total} articles tagged with 宏观态势 need re-classification')

    if total == 0:
        print('[OK] Nothing to do')
        conn.close()
        return

    client = get_llm()
    print(f'[INFO] Using LLM: {client.model}')

    updated = 0
    for batch_start in range(0, total, BATCH_SIZE):
        batch = retag_targets[batch_start:batch_start + BATCH_SIZE]
        batch_end = min(batch_start + BATCH_SIZE, total)
        print(f'  Batch {batch_start+1}-{batch_end}/{total} ...')

        results = retag_batch(batch, client)
        for art_id, new_tags in results.items():
            c.execute("UPDATE articles SET tags = ? WHERE id = ?", (json.dumps(new_tags, ensure_ascii=False), art_id))
            updated += 1
        conn.commit()
        print(f'    {len(results)} articles retagged (total updated: {updated})')

        if batch_end < total:
            time.sleep(2)

    # Verify
    c.execute("SELECT DISTINCT tags FROM articles WHERE detail_fetched = 1")
    all_tags = {}
    for (t,) in c.fetchall():
        if isinstance(t, str):
            t = json.loads(t)
        for tag in (t or []):
            all_tags[tag] = all_tags.get(tag, 0) + 1
    print(f'\n[OK] Retag complete. Updated {updated} articles.')
    print('New tag distribution:')
    for tag, cnt in sorted(all_tags.items(), key=lambda x: -x[1]):
        print(f'  {tag}: {cnt}')

    conn.close()


if __name__ == '__main__':
    main()
