"""
Streamlit App: 量子行业每周新闻洞察生成器

Usage:
    python -m streamlit run examples/weekly_report_app.py --server.address 0.0.0.0 --server.port 8501
"""

import os
import sys
import io
import json
import subprocess
from datetime import datetime, timedelta

import pandas as pd
from sqlalchemy import create_engine
import streamlit as st

# ------------------------------------------------------------------
# Config
# ------------------------------------------------------------------
DB_URL = 'mysql+pymysql://scraper:scraper123@127.0.0.1:3306/liangke_scraper?charset=utf8mb4'
CATEGORIES = ['宏观态势', '科技前沿', '产品动态', '企业资讯', '资本运作']

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def fetch_news(start_date: str, end_date: str):
    engine = create_engine(DB_URL)
    query = f"SELECT * FROM articles WHERE liangke_date BETWEEN '{start_date}' AND '{end_date}' ORDER BY id DESC"
    df = pd.read_sql(query, engine)
    def _parse_tags(x):
        if isinstance(x, list): return x
        if isinstance(x, str):
            try: return json.loads(x)
            except: return []
        return []
    df['tags'] = df['tags'].apply(_parse_tags)
    return df

def classify_news(df: pd.DataFrame):
    result = {cat: [] for cat in CATEGORIES}
    for _, row in df.iterrows():
        tags = row.get('tags', [])
        if not isinstance(tags, list): continue
        for tag in tags:
            if tag in result:
                result[tag].append(row.to_dict())
                break
    return result

def generate_summary(category_name: str, articles: list) -> str:
    if not articles:
        return "本周暂无相关新闻。"
    titles = [a['title'] for a in articles[:3]]
    return f"本周共{len(articles)}条{category_name}相关新闻，重点关注：{titles[0]}等。"

def generate_weekly_report(start_date: str, end_date: str, issue_no: str):
    """Call the CLI script to generate the weekly report."""
    script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'generate_weekly_report.py')
    cmd = [
        sys.executable, script_path,
        '--start', start_date,
        '--end', end_date,
        '--issue', issue_no,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
    return result

# ------------------------------------------------------------------
# Streamlit UI
# ------------------------------------------------------------------

def main():
    st.set_page_config(page_title="量子行业每周新闻洞察", page_icon="📊", layout="wide")
    st.title("📊 量子行业每周新闻洞察")

    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input("开始日期", value=datetime.now().date() - timedelta(days=7))
    with col2:
        end_date = st.date_input("结束日期", value=datetime.now().date())

    issue_no = st.text_input("期数", value="42")

    start_str = start_date.strftime('%Y-%m-%d')
    end_str = end_date.strftime('%Y-%m-%d')

    # Preview section
    st.markdown("---")
    st.markdown("### 📋 本周新闻预览")

    with st.spinner("正在读取数据库..."):
        df = fetch_news(start_str, end_str)

    if df.empty:
        st.warning(f"📭 {start_str} ~ {end_str} 暂无数据。请先运行每日新闻抓取。")
        return

    categories = classify_news(df)

    # Show counts
    cols = st.columns(len(CATEGORIES))
    for i, cat in enumerate(CATEGORIES):
        with cols[i]:
            count = len(categories[cat])
            st.metric(cat, f"{count} 条")

    # Show article lists by category
    for cat in CATEGORIES:
        arts = categories[cat]
        if not arts:
            continue
        with st.expander(f"{cat}（{len(arts)} 条）"):
            for art in arts:
                st.markdown(f"**{art['title']}**")
                st.caption(f"日期：{art.get('liangke_date', 'N/A')}")

    st.markdown("---")
    st.markdown("### 📄 生成周报")

    # Optional uploads
    col1, col2 = st.columns(2)
    with col1:
        tender_file = st.file_uploader("招投标 Excel（可选）", type=['xlsx', 'xls'])
    with col2:
        patent_file = st.file_uploader("专利 Excel（可选）", type=['xlsx', 'xls'])

    # Conference month selection
    conf_month = st.selectbox("会议月份", options=list(range(1, 13)),
                               format_func=lambda x: f"{x}月",
                               index=datetime.now().month - 1)

    if st.button("🚀 生成周报 PDF", type="primary"):
        with st.spinner("正在生成周报..."):
            # Save uploaded files temporarily if provided
            temp_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'weekly_temp')
            os.makedirs(temp_dir, exist_ok=True)

            cmd = [
                sys.executable,
                os.path.join(os.path.dirname(os.path.abspath(__file__)), 'generate_weekly_report.py'),
                '--start', start_str,
                '--end', end_str,
                '--issue', issue_no,
                '--conf-month', str(conf_month),
            ]

            if tender_file:
                tender_path = os.path.join(temp_dir, 'tenders.xlsx')
                with open(tender_path, 'wb') as f:
                    f.write(tender_file.getvalue())
                cmd.extend(['--tender-excel', tender_path])

            if patent_file:
                patent_path = os.path.join(temp_dir, 'patents.xlsx')
                with open(patent_path, 'wb') as f:
                    f.write(patent_file.getvalue())
                cmd.extend(['--patent-excel', patent_path])

            result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')

            if result.returncode != 0:
                st.error("生成失败")
                st.code(result.stdout + "\n" + result.stderr)
                return

            st.code(result.stdout)

            pdf_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                'weekly_output',
                f'量子行业每周新闻洞察_第{issue_no}期.pdf'
            )

            if os.path.exists(pdf_path):
                with open(pdf_path, 'rb') as f:
                    st.download_button(
                        label="📥 下载周报 PDF",
                        data=f,
                        file_name=f'量子行业每周新闻洞察_第{issue_no}期.pdf',
                        mime="application/pdf",
                    )
                st.success("周报生成成功！")
            else:
                st.error("PDF 文件未找到，可能编译失败。")

    st.markdown("---")
    st.caption("数据来源：量科网 + quantum.info/conf/ + 上传的 Excel 文件")

if __name__ == '__main__':
    main()
