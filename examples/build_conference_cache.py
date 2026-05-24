"""
Fetch all quantum conferences and translate them to Chinese via LLM.
Output: data/conferences_zh.json (cached for weekly report usage)
"""
import os
import sys
import json
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'rag_system'))
from llm_client import LLMClient
from conf_fetcher import fetch_conferences

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
OUTPUT_PATH = os.path.join(DATA_DIR, 'conferences_zh.json')
BATCH_SIZE = 20


def _load_llm_config():
    cfg_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.yaml')
    with open(cfg_path, 'r', encoding='utf-8') as f:
        import yaml
        return yaml.safe_load(f)


def _get_llm_client():
    cfg = _load_llm_config()['llm']
    return LLMClient(
        provider='openai',
        api_key=cfg['api_key'],
        api_base=cfg['api_base'],
        model=cfg['model'],
        temperature=cfg.get('temperature') if cfg.get('temperature') is not None else 1,
        max_tokens=cfg.get('max_tokens', 2048),
        timeout=180,
    )


def translate_batch(batch: list, start_idx: int, client: LLMClient) -> dict:
    """Translate a batch of conferences. Returns {global_idx: (name_zh, location_zh)}."""
    lines = ["请将以下量子科技会议名称和地点翻译为中文。会议名称保留英文缩写。输出格式：序号|名称|地点", ""]
    for i, c in enumerate(batch, start_idx + 1):
        lines.append(f"{i}|{c['name_en']}|{c['location_en']}")

    messages = [
        {"role": "system", "content": "你是专业科技翻译助手，擅长英译中。保留英文缩写，地名用中文惯用译名。只输出要求的格式，不要任何解释。"},
        {"role": "user", "content": "\n".join(lines)},
    ]

    print(f'[INFO] Translating batch {start_idx + 1}-{start_idx + len(batch)} ...')
    resp = client.chat(messages)
    print(f'  -> response length: {len(resp)}, lines: {len([l for l in resp.strip().split(chr(10)) if l.strip()])}')
    results = {}
    for line in resp.strip().split('\n'):
        line = line.strip()
        if '|' not in line:
            continue
        parts = line.split('|')
        if len(parts) >= 3:
            try:
                idx = int(parts[0].strip()) - 1
                results[idx] = (parts[1].strip(), parts[2].strip())
            except ValueError:
                continue
    return results


def main():
    conferences = fetch_conferences()
    print(f'[INFO] Fetched {len(conferences)} conferences')
    if not conferences:
        return

    client = _get_llm_client()
    total = len(conferences)
    translations = {}

    for batch_start in range(0, total, BATCH_SIZE):
        batch = conferences[batch_start:batch_start + BATCH_SIZE]
        batch_results = translate_batch(batch, batch_start, client)
        translations.update(batch_results)
        if batch_start + BATCH_SIZE < total:
            time.sleep(1)  # brief pause between batches

    # Build output
    output = []
    for i, c in enumerate(conferences):
        name_zh, loc_zh = translations.get(i, (c['name_en'], c['location_en']))
        output.append({
            'date_str': c['date_str'],
            'month': c['month'],
            'name_zh': name_zh,
            'location_zh': loc_zh,
            'url': c['url'],
        })

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f'[OK] Saved {len(output)} conferences to {OUTPUT_PATH}')


if __name__ == '__main__':
    main()
