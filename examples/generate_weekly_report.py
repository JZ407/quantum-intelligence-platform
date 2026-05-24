"""
Generate weekly LaTeX/PDF report from MySQL news + optional Excel data.

Usage:
    python examples/generate_weekly_report.py --start 2026-05-19 --end 2026-05-25 --issue 42
"""

import os
import sys
import json
import re
import argparse
import subprocess
from datetime import datetime

import pandas as pd
import yaml
from jinja2 import Environment, FileSystemLoader
from sqlalchemy import create_engine

# ------------------------------------------------------------------
# Config
# ------------------------------------------------------------------
DB_URL = 'mysql+pymysql://scraper:scraper123@127.0.0.1:3306/liangke_scraper?charset=utf8mb4'
CATEGORIES = ['宏观态势', '科技前沿', '产品动态', '企业资讯', '资本运作']
TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'weekly_templates')

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def fetch_news(start_date: str, end_date: str):
    """Fetch articles from MySQL for a date range."""
    engine = create_engine(DB_URL)
    query = f"SELECT * FROM articles WHERE liangke_date BETWEEN '{start_date}' AND '{end_date}' ORDER BY id DESC"
    df = pd.read_sql(query, engine)

    def _parse_tags(x):
        if isinstance(x, list):
            return x
        if isinstance(x, str):
            try:
                return json.loads(x)
            except Exception:
                return []
        return []

    df['tags'] = df['tags'].apply(_parse_tags)
    return df


def classify_news(df: pd.DataFrame):
    """Classify articles into 5 categories based on tags."""
    result = {cat: [] for cat in CATEGORIES}
    for _, row in df.iterrows():
        tags = row.get('tags', [])
        if not isinstance(tags, list):
            continue
        for tag in tags:
            if tag in result:
                result[tag].append(row.to_dict())
                break
    return result


def preprocess_content(content: str, article_date) -> str:
    """Preprocess article content for weekly report."""
    if not content:
        return ""
    # Normalize date to string
    if hasattr(article_date, 'strftime'):
        date_str = article_date.strftime('%Y年%m月%d日')
    else:
        date_str = str(article_date)
    # Replace time-sensitive words
    replacements = {
        '昨日': '此前一日',
        '近日': '近期',
        '日前': '此前',
        '昨天': '此前一日',
        '今天': date_str,
        '当日': date_str,
        '今早': date_str + '早间',
        '昨晚': date_str + '晚间',
    }
    for old, new in replacements.items():
        content = content.replace(old, new)
    # Replace date prefix format: "5月22日——" -> "5月22日消息，"
    content = re.sub(r'(\d{1,2}月\d{1,2}日)[——\-]', r'\1消息，', content)
    return content


def _load_llm_config():
    """Load LLM config from config.yaml."""
    cfg_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.yaml')
    with open(cfg_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def generate_summaries_llm(categories: dict) -> dict:
    """Use LLM to generate trend-analysis summaries for all categories."""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'rag_system'))
    from llm_client import LLMClient
    cfg = _load_llm_config()['llm']
    client = LLMClient(
        provider='openai',
        api_key=cfg['api_key'],
        api_base=cfg['api_base'],
        model=cfg['model'],
        temperature=cfg.get('temperature') if cfg.get('temperature') is not None else 1,
        max_tokens=cfg.get('max_tokens', 2048),
        timeout=180,
    )

    # Build prompt
    prompt_lines = [
        "你是一位量子科技行业分析师。请根据以下本周新闻，为每个分类撰写一句趋势性摘要。",
        "要求：不要写'本周有几条新闻'，不要简单罗列标题。请提炼出行业趋势、重点方向和关键动向。",
        "每个分类一句话，不超过80字。\n"
    ]
    for cat in CATEGORIES:
        arts = categories.get(cat, [])
        if not arts:
            continue
        prompt_lines.append(f"\n【{cat}】")
        for art in arts[:5]:
            prompt_lines.append(f"- {art['title']}")
    prompt_lines.append("\n请按以下格式输出（仅输出5行）：")
    for cat in CATEGORIES:
        prompt_lines.append(f"{cat}：...")

    messages = [
        {"role": "system", "content": "你是一位专业的量子科技行业分析师，擅长从新闻中提炼趋势。"},
        {"role": "user", "content": "\n".join(prompt_lines)},
    ]

    try:
        print('[INFO] Generating trend summaries via LLM...')
        resp = client.chat(messages)
        summaries = {}
        for cat in CATEGORIES:
            # Extract summary line for each category
            import re
            match = re.search(rf'{re.escape(cat)}[：:](.+?)(?:\n|$)', resp)
            if match:
                summaries[cat] = match.group(1).strip()
            else:
                summaries[cat] = "本周该领域保持活跃态势。"
        return summaries
    except Exception as e:
        print(f'[WARN] LLM summary generation failed: {e}')
        return {cat: "本周该领域保持活跃态势。" for cat in CATEGORIES}


def render_latex(context: dict, template_name: str = 'weekly_report_template.tex') -> str:
    """Render LaTeX from Jinja2 template."""
    # Use custom comment delimiters to avoid conflicts with LaTeX \#
    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        comment_start_string='{##',
        comment_end_string='##}',
    )
    # Custom filters for LaTeX escaping
    env.filters['tex_escape'] = tex_escape
    template = env.get_template(template_name)
    return template.render(context)


def tex_escape(s: str) -> str:
    """Escape special LaTeX characters and normalize Unicode."""
    if not isinstance(s, str):
        s = str(s)
    # Unicode subscripts/superscripts → plain text
    unicode_replacements = [
        ('²', '2'),   # ²
        ('³', '3'),   # ³
        ('⁰', '0'),   # ⁰
        ('ⁱ', 'i'),   # ⁱ
        ('⁲', '2'),   # ⁲
        ('⁳', '3'),   # ⁳
        ('⁴', '4'),   # ⁴
        ('⁵', '5'),   # ⁵
        ('⁶', '6'),   # ⁶
        ('⁷', '7'),   # ⁷
        ('⁸', '8'),   # ⁸
        ('⁹', '9'),   # ⁹
        ('₀', '0'),   # ₀
        ('₁', '1'),   # ₁
        ('₂', '2'),   # ₂
        ('₃', '3'),   # ₃
        ('₄', '4'),   # ₄
        ('₅', '5'),   # ₅
        ('₆', '6'),   # ₆
        ('₇', '7'),   # ₇
        ('₈', '8'),   # ₈
        ('₉', '9'),   # ₉
    ]
    for old, new in unicode_replacements:
        s = s.replace(old, new)
    # LaTeX special chars
    replacements = [
        ('\\', '\\textbackslash{}'),
        ('&', '\\&'),
        ('%', '\\%'),
        ('$', '\\$'),
        ('#', '\\#'),
        ('_', '\\_'),
        ('{', '\\{'),
        ('}', '\\}'),
        ('~', '\\textasciitilde{}'),
        ('^', '\\textasciicircum{}'),
    ]
    for old, new in replacements:
        s = s.replace(old, new)
    return s


def compile_pdf(tex_path: str, output_dir: str) -> str:
    """Compile LaTeX to PDF using xelatex (run twice for TOC)."""
    env = os.environ.copy()
    env['PYTHONIOENCODING'] = 'utf-8'
    for i in range(2):
        print(f'  xelatex run {i+1}/2...')
        result = subprocess.run(
            ['xelatex', '-interaction=nonstopmode', '-output-directory', output_dir, os.path.basename(tex_path)],
            cwd=output_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        # Decode manually with errors='replace' to avoid GBK issues
        out = result.stdout.decode('utf-8', errors='replace') if result.stdout else ''
        err = result.stderr.decode('utf-8', errors='replace') if result.stderr else ''
        if result.returncode != 0:
            print(f'[WARN] xelatex returned {result.returncode}')
            if '!' in out:
                print(out[-2000:])  # print last 2KB of output for debugging
    pdf_path = tex_path.replace('.tex', '.pdf')
    return pdf_path


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description='Generate weekly quantum news report')
    parser.add_argument('--start', required=True, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end', required=True, help='End date (YYYY-MM-DD)')
    parser.add_argument('--issue', required=True, help='Issue number (e.g. 42)')
    parser.add_argument('--output', default=None, help='Output directory')
    parser.add_argument('--conf-month', type=int, default=None, help='Conference month to include')
    parser.add_argument('--tender-excel', default=None, help='Path to tender Excel file')
    parser.add_argument('--patent-excel', default=None, help='Path to patent Excel file')
    args = parser.parse_args()

    output_dir = args.output or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'weekly_output')
    os.makedirs(output_dir, exist_ok=True)

    # 1. Fetch and classify news
    print(f'[INFO] Fetching news from {args.start} to {args.end}...')
    df = fetch_news(args.start, args.end)
    print(f'[INFO] Fetched {len(df)} articles')

    categories = classify_news(df)
    for cat, arts in categories.items():
        print(f'  {cat}: {len(arts)} articles')

    # 2. Preprocess article content and set URL
    for cat in CATEGORIES:
        for art in categories[cat]:
            art['content'] = preprocess_content(art.get('content', '') or '', art.get('liangke_date', ''))
            art['url'] = art.get('reference_url') or art.get('liangke_url') or ''

    # 3. Generate trend summaries via LLM
    summaries = generate_summaries_llm(categories)

    # 3. Optional: conferences
    conferences = []
    if args.conf_month:
        print(f'[INFO] Fetching conferences for month {args.conf_month}...')
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from examples.conf_fetcher import fetch_conferences, filter_by_month
        confs = fetch_conferences()
        for c in filter_by_month(confs, args.conf_month):
            conferences.append({
                'date_str': c['date_str'],
                'name': c['name_en'],  # TODO: translate
                'location': c['location_en'],  # TODO: translate
            })
        print(f'[INFO] {len(conferences)} conferences found')

    # 4. Optional: tenders from Excel
    tenders = []
    if args.tender_excel and os.path.exists(args.tender_excel):
        print(f'[INFO] Reading tenders from {args.tender_excel}...')
        # TODO: implement Excel parsing

    # 5. Optional: patents from Excel
    patents = []
    if args.patent_excel and os.path.exists(args.patent_excel):
        print(f'[INFO] Reading patents from {args.patent_excel}...')
        # TODO: implement Excel parsing

    # 6. Escape article content for LaTeX before rendering
    for cat in CATEGORIES:
        for art in categories[cat]:
            for key in ['title', 'content', 'liangke_url']:
                if key in art and art[key]:
                    art[key] = tex_escape(art[key])
        summaries[cat] = tex_escape(summaries[cat])

    # 7. Render LaTeX
    print('[INFO] Rendering LaTeX...')
    context = {
        'start_date': args.start,
        'end_date': args.end,
        'issue_no': args.issue,
        'summaries': summaries,
        'categories': categories,
        'conferences': conferences,
        'conf_month': args.conf_month,
        'tenders': tenders,
        'patents': patents,
    }
    latex = render_latex(context)

    tex_path = os.path.join(output_dir, f'量子行业每周新闻洞察_第{args.issue}期.tex')
    with open(tex_path, 'w', encoding='utf-8') as f:
        f.write(latex)
    print(f'[OK] LaTeX saved to {tex_path}')

    # 7. Copy cover image
    cover_candidates = [
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'weekly_templates', 'Cover_Suzhou.png'),
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '量子行业每周新闻洞察_模板文件夹', '量子行业每周新闻洞察_模板文件夹', 'Cover_Suzhou.png'),
        r'D:\Claude_code\量子行业每周新闻洞察_模板文件夹\量子行业每周新闻洞察_模板文件夹\Cover_Suzhou.png',
    ]
    cover_copied = False
    for cover_src in cover_candidates:
        if os.path.exists(cover_src):
            import shutil
            shutil.copy(cover_src, os.path.join(output_dir, 'Cover_Suzhou.png'))
            print(f'[OK] Cover image copied from {cover_src}')
            cover_copied = True
            break
    if not cover_copied:
        print(f'[WARN] Cover image not found')

    # 8. Compile PDF
    print('[INFO] Compiling PDF (xelatex x2)...')
    pdf_path = compile_pdf(tex_path, output_dir)
    print(f'[OK] PDF saved to {pdf_path}')


if __name__ == '__main__':
    main()
