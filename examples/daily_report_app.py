"""
Streamlit App: 量科每日讯日报生成器

Usage (local network):
    python -m streamlit run examples/daily_report_app.py --server.address 0.0.0.0 --server.port 8501

Usage + public access via ngrok:
    1. pip install pyngrok
    2. python -m streamlit run examples/daily_report_app.py &
    3. ngrok http 8501
"""

import os
import sys
import io
from datetime import datetime, timedelta

import pandas as pd
from sqlalchemy import create_engine
import streamlit as st
from docx import Document
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_PARAGRAPH_ALIGNMENT

# ------------------------------------------------------------------
# Config
# ------------------------------------------------------------------
DB_URL = 'mysql+pymysql://scraper:scraper123@127.0.0.1:3306/liangke_scraper?charset=utf8mb4'
CATEGORY_PRIORITY = ['资本运作', '产品动态', '企业资讯', '科技前沿', '宏观态势']

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def fetch_articles(target_date: str):
    """Fetch articles for a specific liangke_date."""
    engine = create_engine(DB_URL)
    query = f"SELECT * FROM articles WHERE liangke_date = '{target_date}' ORDER BY id DESC"
    return pd.read_sql(query, engine)


def select_top3(df: pd.DataFrame):
    """Select top-3 articles by category priority."""
    if df.empty:
        return []

    selected = []
    used_ids = set()

    for cat in CATEGORY_PRIORITY:
        mask = df['tags'].apply(lambda tags: isinstance(tags, list) and cat in tags)
        candidates = df[mask]
        if not candidates.empty:
            # Sort by fetch_count desc, then id desc (newer first)
            candidates = candidates.sort_values(by=['fetch_count', 'id'], ascending=[False, False])
            for _, row in candidates.iterrows():
                if row['id'] not in used_ids:
                    selected.append(row)
                    used_ids.add(row['id'])
                    break
        if len(selected) >= 3:
            break

    # If still < 3, fill with remaining articles (newest first)
    if len(selected) < 3:
        remaining = df[~df['id'].isin(used_ids)].sort_values(by='id', ascending=False)
        for _, row in remaining.iterrows():
            selected.append(row)
            if len(selected) >= 3:
                break

    return selected


def build_docx(title: str, articles: list) -> io.BytesIO:
    """Generate a Word document and return as BytesIO."""
    doc = Document()

    # Title
    p = doc.add_paragraph()
    run = p.add_run(title)
    run.font.size = Pt(16)
    run.font.bold = True
    run.font.color.rgb = RGBColor(0, 0, 0)
    p.alignment = WD_PARAGRAPH_ALIGNMENT.LEFT

    doc.add_paragraph()  # blank line

    for idx, art in enumerate(articles, 1):
        # Article title
        p = doc.add_paragraph()
        run = p.add_run(f"{idx}. {art['title']}")
        run.font.size = Pt(12)
        run.font.bold = True

        # Summary (first 300 chars of content)
        content = art.get('content', '') or ''
        summary = content[:300].strip()
        if summary:
            doc.add_paragraph(summary)

        # Reference link
        ref_url = art.get('reference_url', '') or art.get('liangke_url', '')
        if ref_url:
            p = doc.add_paragraph()
            run = p.add_run(f"参考链接：{ref_url}")
            run.font.size = Pt(10)
            run.font.color.rgb = RGBColor(0, 0, 255)

        doc.add_paragraph()  # blank line between articles

    # Save to memory
    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf


# ------------------------------------------------------------------
# Streamlit UI
# ------------------------------------------------------------------

def main():
    st.set_page_config(page_title="量科每日讯日报生成器", page_icon="📰")
    st.title("📰 量科每日讯日报生成器")

    # Date picker
    today = datetime.now().date()
    target_date = st.date_input("选择日期", value=today)
    target_date_str = target_date.strftime('%Y-%m-%d')

    st.markdown("---")

    if st.button("🚀 生成日报", type="primary"):
        with st.spinner("正在读取数据库..."):
            df = fetch_articles(target_date_str)

        if df.empty:
            st.warning(f"📭 {target_date_str} 暂无数据。请先运行每日新闻抓取。")
            return

        with st.spinner("正在筛选重要新闻..."):
            top3 = select_top3(df)

        if not top3:
            st.warning("未能筛选出合适的新闻。")
            return

        st.success(f"已筛选 {len(top3)} 条新闻（当日共 {len(df)} 条）")

        # Preview
        for idx, art in enumerate(top3, 1):
            with st.container():
                st.markdown(f"**{idx}. {art['title']}**")
                tags = art.get('tags', [])
                if isinstance(tags, list) and tags:
                    st.caption(f"标签：{' | '.join(tags)}")
                st.markdown("---")

        # Generate docx
        doc_title = f"量科每日讯{target_date_str}"
        doc_buf = build_docx(doc_title, top3)
        file_name = f"量科每日讯{target_date_str}.docx"

        st.download_button(
            label="📥 下载 Word 日报",
            data=doc_buf,
            file_name=file_name,
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

    st.markdown("---")
    st.caption("筛选优先级：资本运作 > 产品动态 > 企业资讯 > 科技前沿 > 宏观态势")


if __name__ == '__main__':
    main()
