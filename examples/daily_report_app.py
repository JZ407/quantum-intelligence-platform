"""
Streamlit App: 量子科技情报

Usage (local network):
    python -m streamlit run examples/daily_report_app.py --server.address 0.0.0.0 --server.port 8501
"""

import os
import sys
import io
import json
from datetime import datetime, timedelta

import pandas as pd
from sqlalchemy import create_engine
import streamlit as st
from docx import Document
from docx.shared import Pt, RGBColor, Cm
from docx.enum.text import WD_PARAGRAPH_ALIGNMENT
from docx.oxml.ns import qn

# ------------------------------------------------------------------
# Config
# ------------------------------------------------------------------
DB_URL = 'mysql+pymysql://scraper:scraper123@127.0.0.1:3306/liangke_scraper?charset=utf8mb4'
HISTORICAL_DB_PATH = 'D:/Claude_code/liangke_historical/historical.db'
CATEGORY_PRIORITY = ['资本运作', '产品动态', '企业资讯', '科技前沿', '宏观态势']

CONF_DB_PATH = 'D:/Claude_code/conference_db/conferences.db'

TAGS_LIST = [
    '量子计算', '科技前沿', '产品动态', '量子通信', '行业应用',
    '企业与机构', '硬件平台', '融资商业', '宏观态势', 'AI/ML',
    '半导体', '量子物理', '后量子密码', '融资', 'PQC', 'QKD',
    '量子纠错', '超导', 'NIST', '量子传感', '企业资讯',
    '光量子', '资本运作', '离子阱', '政策标准', '后量子迁移', 'arXiv',
]

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _set_run_font(run, font_name, size_pt):
    run.font.name = font_name
    run._element.rPr.rFonts.set(qn('w:eastAsia'), font_name)
    run.font.size = Pt(size_pt)

def _parse_tags(x):
    if isinstance(x, list):
        return x
    if isinstance(x, str):
        try:
            return json.loads(x)
        except Exception:
            return []
    return []


def fetch_articles(target_date: str):
    """Fetch articles for a specific liangke_date."""
    engine = create_engine(DB_URL)
    query = f"SELECT * FROM articles WHERE liangke_date = '{target_date}' ORDER BY id DESC"
    df = pd.read_sql(query, engine)
    df['tags'] = df['tags'].apply(_parse_tags)
    return df


def _classify_by_title(title: str) -> list:
    """Rule-based classification using keywords in title.
    Returns exactly ONE tag from the 5 main categories.
    Priority: 资本运作 > 产品动态 > 企业资讯 > 科技前沿 > 宏观态势
    """
    t = title.lower()

    # 资本运作（最高优先级）
    if any(k in t for k in ['融资', '投资', 'ipo', '并购', '资本', '轮', '美元', '亿元', '估值', '收购', '领投', 'fund', 'invest', 'merger', 'acquisition', 'capital', 'financing', 'valuation', '独角兽', '上市']):
        return ['资本运作']

    # 产品动态
    if any(k in t for k in ['产品', '发布', '推出', '芯片', '计算机', '软件', '系统', '设备', '仪器', '平台', '上线', '原型机', '量子计算机', '量子芯片', 'product', 'launch', 'release', 'chip', 'computer', 'software', 'system', 'device', 'platform', 'processor']):
        return ['产品动态']

    # 企业资讯
    if any(k in t for k in ['公司', '企业', '合作', '签约', '战略', '成立', '总部', '裁员', '人事', '任命', 'ceo', '总裁', '总监', 'company', 'enterprise', 'cooperation', 'partnership', 'strategic', 'founded', 'appointed', 'president', 'director']):
        return ['企业资讯']

    # 科技前沿
    if any(k in t for k in ['论文', '研究', '突破', '实验', '量子比特', '纠错', '算法', '物理', '科学', 'nature', 'science', '发表', '期刊', 'paper', 'research', 'breakthrough', 'experiment', 'qubit', 'algorithm', 'physics', '论文', '学术', '实验室', '原理', '理论']):
        return ['科技前沿']

    # 宏观态势（兜底）
    return ['宏观态势']


def fetch_historical_articles(target_date: str):
    """Fetch articles from historical SQLite DB for a specific date."""
    import sqlite3
    conn = sqlite3.connect(HISTORICAL_DB_PATH)
    query = f"SELECT id, title, content, reference_url, liangke_url, published_at FROM articles WHERE DATE(published_at) = '{target_date}' ORDER BY published_at DESC"
    df = pd.read_sql(query, conn)
    conn.close()
    # Normalize column names to match daily DB
    df = df.rename(columns={'published_at': 'liangke_date'})
    # For historical DB, prefer liangke_url as the primary reference_url
    # since original links may be dead
    df['reference_url'] = df['liangke_url'].fillna(df['reference_url'])
    df['tags'] = df['title'].apply(_classify_by_title)
    return df

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

def build_docx(date_str: str, articles: list) -> io.BytesIO:
    """Generate a Word document and return as BytesIO."""
    doc = Document()
    YAHEI = '微软雅黑'

    # Title
    p = doc.add_paragraph()
    run = p.add_run(f"每日情报资讯（{date_str}）：")
    _set_run_font(run, YAHEI, 16)
    run.font.bold = True
    run.font.color.rgb = RGBColor(0, 0, 0)
    p.alignment = WD_PARAGRAPH_ALIGNMENT.LEFT

    doc.add_paragraph()  # blank line

    for idx, art in enumerate(articles, 1):
        # Article title
        p = doc.add_paragraph()
        run = p.add_run(f"{idx}、{art['title']}：")
        _set_run_font(run, YAHEI, 16)
        run.font.bold = True

        # Full content (split by newline, indent each paragraph)
        content = art.get('content', '') or ''
        for line in content.strip().split('\n'):
            line = line.strip()
            if not line:
                continue
            p = doc.add_paragraph()
            p.paragraph_format.first_line_indent = Cm(0.74)  # ~2 Chinese chars
            run = p.add_run(line)
            _set_run_font(run, YAHEI, 14)

        # Reference link
        ref_url = art.get('reference_url', '') or art.get('liangke_url', '')
        if ref_url:
            p = doc.add_paragraph()
            run = p.add_run(f"参考链接：{ref_url}")
            _set_run_font(run, YAHEI, 10.5)
            run.font.color.rgb = RGBColor(0, 0, 255)

        doc.add_paragraph()  # blank line between articles

    # Patent section
    p = doc.add_paragraph()
    run = p.add_run("4、专利：")
    _set_run_font(run, YAHEI, 16)
    run.font.bold = True

    p = doc.add_paragraph()
    run = p.add_run(" ")
    _set_run_font(run, YAHEI, 14)

    p = doc.add_paragraph()
    run = p.add_run("参考链接：")
    _set_run_font(run, YAHEI, 10.5)
    run.font.color.rgb = RGBColor(0, 0, 255)

    # Save to memory
    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf

# ------------------------------------------------------------------
# Conference helpers
# ------------------------------------------------------------------

@st.cache_data(ttl=60)
def load_conferences():
    """Load translated conferences from SQLite database."""
    import sqlite3
    if not os.path.exists(CONF_DB_PATH):
        return []
    conn = sqlite3.connect(CONF_DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('SELECT date_str, month, name_zh, location_zh, url FROM conferences ORDER BY month, id')
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


# ------------------------------------------------------------------
# Article detail dialog
# ------------------------------------------------------------------

@st.dialog("新闻详情", width="large")
def show_article_detail(art: dict):
    """Show article detail in a modal dialog."""
    st.subheader(art['title'])
    tags = art.get('tags', [])
    if isinstance(tags, list) and tags:
        st.caption(f"标签：{' | '.join(tags)}")
    st.markdown("---")
    content = art.get('content', '') or ''
    if content:
        st.markdown(content)
    else:
        st.info("暂无正文内容")
    ref_url = art.get('reference_url', '') or art.get('liangke_url', '')
    if ref_url:
        st.markdown("---")
        st.link_button("🔗 打开参考链接", ref_url)


# ------------------------------------------------------------------
# Page: Daily News
# ------------------------------------------------------------------

def page_daily_news():
    """Daily news selection and report generation."""
    st.header("量科网每日情报资讯")

    today = datetime.now().date()
    col1, col2, col3 = st.columns([2, 2, 2])
    with col1:
        source = st.selectbox("数据源", options=["量科每日库", "量科历史库"], index=0)
    with col2:
        if source == "量科每日库":
            min_date = datetime(2026, 4, 11).date()
            caption = "📌 每日库记录始于 2026-04-11"
        else:
            min_date = datetime(2021, 11, 18).date()
            caption = "📌 历史库记录始于 2021-11-18"
        target_date = st.date_input("选择日期", value=today, min_value=min_date)
    with col3:
        st.caption(caption)
    target_str = target_date.strftime('%Y-%m-%d')

    keyword = st.text_input("🔍 关键词检索（搜索全库，不限日期）", placeholder="输入关键词搜索全库...")

    with st.spinner("正在读取数据库..."):
        if keyword:
            # Search entire database, ignore date
            if source == "量科历史库":
                df = fetch_historical_articles_range('2021-01-01', '2030-01-01')
            else:
                df = _fetch_daily_articles_range('2026-01-01', '2030-01-01')
            kw = keyword.strip()
            mask = df['title'].str.contains(kw, case=False, na=False) | df['content'].str.contains(kw, case=False, na=False)
            df = df[mask]
        else:
            if source == "量科历史库":
                df = fetch_historical_articles(target_str)
            else:
                df = fetch_articles(target_str)

    if df.empty:
        st.warning(f"📭 暂无匹配数据。")
        return

    # News list section (with manual selection)
    if keyword:
        st.markdown(f"### 📋 搜索结果（共 {len(df)} 条）")
        st.caption(f"全文检索 \"{keyword}\" ，跨全库")
    else:
        st.markdown(f"### 📋 新闻列表（{target_str}，共 {len(df)} 条）")
        st.caption("请勾选您认为最重要的 3 条新闻，下方将据此生成日报。")

    source_key = "daily" if source == "量科每日库" else "hist"
    selected_ids = []
    for _, row in df.iterrows():
        with st.container():
            cols = st.columns([0.5, 5, 1])
            with cols[0]:
                checked = st.checkbox("", key=f"sel_{source_key}_{row['id']}", label_visibility="collapsed")
                if checked:
                    selected_ids.append(row['id'])
            with cols[1]:
                st.markdown(f"**{row['title']}**")
                tags = row.get('tags', [])
                date_str = row.get('liangke_date', '')
                # For historical DB, truncate datetime to date
                if date_str and len(str(date_str)) > 10:
                    date_str = str(date_str)[:10]
                tag_text = ' | '.join(tags[:3]) if isinstance(tags, list) and tags else ''
                if tag_text and date_str:
                    st.caption(f"{date_str} · {tag_text}")
                elif date_str:
                    st.caption(f"{date_str}")
                elif tag_text:
                    st.caption(tag_text)
            with cols[2]:
                if st.button("查看详情", key=f"view_{source_key}_{row['id']}", type="secondary"):
                    show_article_detail(row.to_dict())
        st.divider()

    # Daily report generation section
    st.markdown("---")
    st.markdown("### 📄 日报生成")

    selected_rows = df[df['id'].isin(selected_ids)].to_dict('records')
    count = len(selected_rows)

    if count == 0:
        st.info("请在上方新闻列表中勾选要纳入日报的文章（建议 3 条）。")
    elif count < 3:
        st.warning(f"已勾选 {count} 条，建议再选 {3 - count} 条以达到 3 条。")
    elif count > 3:
        st.warning(f"已勾选 {count} 条，建议只保留最重要的 3 条。当前将使用前 3 条生成日报。")
        selected_rows = selected_rows[:3]
    else:
        st.success(f"已勾选 {count} 条，可以生成日报。")

    if selected_rows and st.button("🚀 生成日报", type="primary"):
        rows_to_use = selected_rows[:3]

        st.markdown("#### 日报预览")
        for idx, art in enumerate(rows_to_use, 1):
            with st.container():
                st.markdown(f"**{idx}. {art['title']}**")
                tags = art.get('tags', [])
                if isinstance(tags, list) and tags:
                    st.caption(f"标签：{' | '.join(tags)}")
                st.markdown("---")

        doc_buf = build_docx(target_str, rows_to_use)
        file_name = f"日报{target_str}.docx"

        st.download_button(
            label="📥 下载 Word 日报",
            data=doc_buf,
            file_name=file_name,
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

    # Data export section
    st.markdown("---")
    st.markdown("### 📤 数据导出")

    exp_col1, exp_col2 = st.columns(2)
    with exp_col1:
        exp_start = st.date_input("开始日期", value=target_date, min_value=min_date, key="exp_start")
    with exp_col2:
        exp_end = st.date_input("结束日期", value=target_date, min_value=min_date, key="exp_end")
    exp_kw = st.text_input("关键词筛选", placeholder="留空=全部", key="exp_kw")
    exp_tags = st.multiselect("标签筛选（留空=全部）", options=TAGS_LIST, default=[], key="exp_tags")
    exp_format = st.radio("导出格式", ["Excel (.xlsx)", "SQLite (.db)"], horizontal=True, key="exp_format")

    if st.button("📤 导出数据", type="primary", key="btn_export"):
        with st.spinner("正在读取数据库..."):
            if source == "量科历史库":
                exp_df = fetch_historical_articles_range(exp_start.strftime('%Y-%m-%d'), exp_end.strftime('%Y-%m-%d'))
            else:
                exp_df = _fetch_daily_articles_range(exp_start.strftime('%Y-%m-%d'), exp_end.strftime('%Y-%m-%d'))
        if exp_kw:
            kw = exp_kw.strip()
            mask = exp_df['title'].str.contains(kw, case=False, na=False) | exp_df['content'].str.contains(kw, case=False, na=False)
            exp_df = exp_df[mask]
        if exp_tags:
            mask = exp_df['tags'].apply(lambda t: isinstance(t, list) and any(tag in t for tag in exp_tags))
            exp_df = exp_df[mask]
        if exp_df.empty:
            st.warning("未找到匹配的数据。")
        else:
            if exp_format == "Excel (.xlsx)":
                buf = io.BytesIO()
                exp_df.to_excel(buf, index=False, engine='openpyxl')
                buf.seek(0)
                st.download_button(
                    label="📥 下载 Excel",
                    data=buf,
                    file_name=f"export_{exp_start.strftime('%Y%m%d')}_{exp_end.strftime('%Y%m%d')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
                st.success(f"已导出 {len(exp_df)} 条数据")
            else:
                import sqlite3
                tmp_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'export_tmp.db')
                os.makedirs(os.path.dirname(tmp_path), exist_ok=True)
                tmp_conn = sqlite3.connect(tmp_path)
                exp_df.to_sql('articles', tmp_conn, index=False, if_exists='replace')
                tmp_conn.close()
                with open(tmp_path, 'rb') as f:
                    st.download_button(
                        label="📥 下载 SQLite 数据库",
                        data=f,
                        file_name=f"export_{exp_start.strftime('%Y%m%d')}_{exp_end.strftime('%Y%m%d')}.db",
                        mime="application/octet-stream",
                    )
                st.success(f"已导出 {len(exp_df)} 条数据")


def _fetch_daily_articles_range(start_date: str, end_date: str) -> pd.DataFrame:
    """Fetch articles from daily MySQL DB for a date range."""
    engine = create_engine(DB_URL)
    query = f"SELECT id, title, content, reference_url, liangke_url, liangke_date, tags FROM articles WHERE liangke_date BETWEEN '{start_date}' AND '{end_date}' ORDER BY id DESC"
    df = pd.read_sql(query, engine)
    df['tags'] = df['tags'].apply(_parse_tags)
    return df


def fetch_historical_articles_range(start_date: str, end_date: str) -> pd.DataFrame:
    """Fetch articles from historical SQLite DB for a date range."""
    import sqlite3
    conn = sqlite3.connect(HISTORICAL_DB_PATH)
    query = f"SELECT id, title, content, reference_url, published_at FROM articles WHERE DATE(published_at) BETWEEN '{start_date}' AND '{end_date}' ORDER BY published_at DESC"
    df = pd.read_sql(query, conn)
    conn.close()
    df = df.rename(columns={'published_at': 'liangke_date'})
    df['tags'] = df['title'].apply(_classify_by_title)
    return df


# ------------------------------------------------------------------
# Page: Conferences
# ------------------------------------------------------------------

def page_conferences():
    """Conference list viewer."""
    confs = load_conferences()
    if not confs:
        st.warning("📭 暂无会议数据。请先运行会议缓存构建脚本。")
        return

    st.markdown("### 📅 量子科技行业会议一览")
    st.caption(f"数据来源：quantum.info/conf/，共 {len(confs)} 场会议")

    month = st.selectbox(
        "选择月份",
        options=list(range(1, 13)),
        format_func=lambda x: f"{x}月",
        index=datetime.now().month - 1,
    )

    filtered = [c for c in confs if c.get('month') == month]

    if not filtered:
        st.info(f"{month} 月暂无会议信息。")
        return

    st.success(f"{month} 月共 {len(filtered)} 场会议")

    # Build display table
    rows = []
    for c in filtered:
        rows.append({
            '日期': c.get('date_str', ''),
            '会议名称': c.get('name_zh', c.get('name_en', '')),
            '地点': c.get('location_zh', c.get('location_en', '')),
            '链接': c.get('url', ''),
        })

    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

def main():
    st.set_page_config(page_title="量子科技情报", page_icon="📰", layout="wide")
    st.title("📰 量子科技情报")

    page = st.sidebar.radio("导航", ["每日资讯", "会议信息"])

    if page == "每日资讯":
        page_daily_news()
    elif page == "会议信息":
        page_conferences()


if __name__ == '__main__':
    main()
