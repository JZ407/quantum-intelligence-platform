"""
Investment data extractor: reads 3 databases, extracts structured fields,
outputs investments.json for the quantum investment dashboard.
"""
import sys, os, re, json, sqlite3
from datetime import datetime, timedelta
from collections import defaultdict

# --- Path setup ---
sys.path.insert(0, 'D:/Claude_code')
sys.path.insert(0, 'D:/Claude_code/knowledge_graph')
from core.entity_dict import INSTITUTIONS, TECH_PLATFORMS, normalize_entity

# --- Country mapping (company canonical -> ISO) ---
COMPANY_COUNTRY = {
    'Origin Quantum': 'CN', 'QuantumCTek': 'CN', 'Baidu': 'CN', 'Alibaba': 'CN',
    'Tencent': 'CN', 'Huawei': 'CN', 'China Telecom': 'CN', 'China Mobile': 'CN',
    'USTC': 'CN', 'Tsinghua University': 'CN', 'Peking University': 'CN',
    'IBM': 'US', 'Google Quantum AI': 'US', 'Microsoft': 'US', 'NVIDIA': 'US',
    'IonQ': 'US', 'Rigetti': 'US', 'PsiQuantum': 'US', 'D-Wave': 'US',
    'Atom Computing': 'US', 'Infleqtion': 'US', 'Amazon': 'US', 'Intel': 'US',
    'DARPA': 'US', 'NIST': 'US', 'NASA': 'US',
    'Quantinuum': 'US',
    'OQC': 'GB', 'Oxford Ionics': 'GB', 'QuantWare': 'GB', 'Q-CTRL': 'AU',
    'QuEra': 'US', 'Xanadu': 'CA', 'Pasqal': 'FR', 'Quandela': 'FR',
    'Alice & Bob': 'FR', 'ID Quantique': 'CH', 'Toshiba': 'JP', 'Hitachi': 'JP',
    'NTT': 'JP', 'RIKEN': 'JP', 'University of Tokyo': 'JP',
    'QunaSys': 'JP', 'Samsung': 'KR', 'LG Electronics': 'KR',
    'Cleveland Clinic': 'US', 'MIT': 'US', 'Caltech': 'US',
    'Bosch': 'DE', 'Siemens': 'DE', 'BMW': 'DE', 'BASF': 'DE',
    'Thales': 'FR', 'Airbus': 'FR', 'TotalEnergies': 'FR', 'EDF': 'FR',
    'JPMorgan': 'US', 'Goldman Sachs': 'US', 'HSBC': 'GB',
    'AstraZeneca': 'GB', 'Boeing': 'US', 'Lockheed Martin': 'US',
    'Northrop Grumman': 'US', 'CERN': 'CH', 'ESA': 'FR',
}

# Additional Chinese companies (add canonical + aliases for matching)
CHINESE_COMPANIES = {
    '量旋科技': ['量旋科技', 'SpinQ'], '玻色量子': ['玻色量子'],
    '图灵量子': ['图灵量子', 'TuringQ'], '本源量子': ['本源量子', 'Origin Quantum'],
    '国盾量子': ['国盾量子', 'QuantumCTek'], '国仪量子': ['国仪量子'],
    '华翊量子': ['华翊量子'], '逻辑比特': ['逻辑比特', '逻辑比特科技'],
    '幺正量子': ['幺正量子'], '相干科技': ['相干科技'],
    '微观纪元': ['微观纪元'], '量坤科技': ['量坤科技'],
    '两仪万象': ['两仪万象', '两仪万向'], '太一量生': ['太一量生'],
    '中科酷原': ['中科酷原'], '国测量子': ['国测量子'],
    '未磁科技': ['未磁科技'], '知冷低温': ['知冷低温'],
    '奇算光启': ['奇算光启'], '矩量光启': ['矩量光启'],
    '无问清芯': ['无问清芯'], '隧穿智元': ['隧穿智元'],
    '国光量子': ['国光量子'], '不筹量子': ['不筹量子'],
    '原子矩阵': ['原子矩阵', 'MatriQ'], '频准激光': ['频准激光'],
}

# CS: Chinese round keywords -> normalized round
ROUND_PATTERNS_CN = [
    (r'种子轮', 'Seed'), (r'天使轮', 'Angel'), (r'Pre-A|PreA', 'Pre-A'),
    (r'A\+{1,2}轮', 'A'), (r'[^a-z]A轮', 'A'), (r'[^a-z]B\+{0,2}轮', 'B'),
    (r'[^a-z]C\+{0,2}轮', 'C'), (r'[^a-z]D\+{0,2}轮', 'D'),
    (r'Pre-IPO|上市前融资', 'Pre-IPO'),
    (r'IPO|首次公开|上市申请|敲钟|挂牌|过会|提交注册|F-4|S-1|registration statement|招股书|注册声明', 'IPO'),
    (r'SPAC|借壳上市|特殊目的收购', 'SPAC'),
    (r'收购|并购|acquires?\b|acquisition', 'Acquisition'),
    (r'战略投资|战略融资|战投|注资|增资|战略配售', '战略融资'),
    (r'产业基金|引导基金|创投基金|母基金|专项基金|基金设立|设立.*基金|量子基金', 'Fund'),
    (r'\w+轮', 'Unknown'),
]

ROUND_PATTERNS_EN = [
    (r'seed', 'Seed'), (r'angel', 'Angel'), (r'pre-a', 'Pre-A'),
    (r'series a|series-a', 'A'), (r'series b|series-b', 'B'),
    (r'series c|series-c', 'C'), (r'series d|series-d', 'D'),
    (r'ipo|initial public offering|public listing|goes public|went public', 'IPO'),
    (r'spac', 'SPAC'), (r'acquir|merge|buy', 'Acquisition'),
    (r'grant|award|contract|funding award', 'Grant'),
    (r'rais|funding|financ|investment|round', 'Unknown'),
]

CITY_MAP = {
    '合肥': 'CN-HF', '北京': 'CN-BJ', '深圳': 'CN-SZ', '上海': 'CN-SH',
    '武汉': 'CN-WH', '杭州': 'CN-HZ', '成都': 'CN-CD', '济南': 'CN-JN',
    '广州': 'CN-GZ', '苏州': 'CN-SZ', '南京': 'CN-NJ', '西安': 'CN-XA',
    '天津': 'CN-TJ', '长沙': 'CN-CS', '无锡': 'CN-WX',
}

# ── Amount extraction ─────────────────────────────────────────────────

def extract_amount_cny(text):
    """Extract amount from Chinese text, return CNY int or None.
    Handles: 2亿元, 3000万美元, 数亿元, 近亿元, 数千万元, 1.39亿美元
    """
    text = text.replace(',', '').replace(' ', '')
    # Numeric + unit
    m = re.search(r'(\d+(?:\.\d+)?)\s*(亿|万)\s*(元|美元|欧元|英镑|加元|澳元|日元|卢比)?', text)
    if m:
        val = float(m.group(1))
        unit = m.group(2)  # 亿 or 万
        currency = m.group(3) or '元'
        base = val * 1e8 if unit == '亿' else val * 1e4
        if currency == '美元': base *= 7.2
        elif currency == '欧元': base *= 7.8
        elif currency == '英镑': base *= 9.1
        return int(base)
    # Vague amounts
    for pat, estimate in [('数亿', 3e8), ('数千万', 3e7), ('近亿', 9e7),
                           ('近千万', 9e6), ('逾亿', 1.5e8), ('超亿', 1.5e8),
                           ('近.*亿', 9e7), ('超.*亿', 1.5e8)]:
        if re.search(pat, text):
            return int(estimate)
    return None

def extract_amount_usd(text):
    """Extract amount from English text, return USD int or None."""
    text = text.replace(',', '')
    # $X million/billion
    m = re.search(r'\$\s*(\d+(?:\.\d+)?)\s*(million|billion|trillion)', text, re.I)
    if m:
        val = float(m.group(1))
        unit = m.group(2).lower()
        if unit == 'billion': val *= 1e9
        elif unit == 'million': val *= 1e6
        elif unit == 'trillion': val *= 1e12
        return int(val)
    # X million/billion dollars/euros/pounds
    m = re.search(r'(\d+(?:\.\d+)?)\s*(million|billion)\s*(dollar|euro|pound|€|£)', text, re.I)
    if m:
        val = float(m.group(1)) * (1e9 if m.group(2).lower() == 'billion' else 1e6)
        curr = m.group(3).lower()
        if 'euro' in curr or '€' in curr: val *= 1.08
        if 'pound' in curr or '£' in curr: val *= 1.26
        return int(val)
    # €X million
    m = re.search(r'[€]\s*(\d+(?:\.\d+)?)\s*(million|billion)', text, re.I)
    if m:
        val = float(m.group(1)) * (1e9 if m.group(2).lower() == 'billion' else 1e6) * 1.08
        return int(val)
    return None


# ── Round extraction ──────────────────────────────────────────────────

def extract_round(text):
    """Extract investment round from Chinese or English text."""
    # Try Chinese specific rounds first
    for pat, label in [
        (r'种子轮', 'Seed'), (r'天使轮', 'Angel'), (r'Pre-A', 'Pre-A'),
        (r'A\+{1,2}轮', 'A'), (r'[^a-zA-Z]A轮', 'A'),
        (r'B\+{0,2}轮', 'B'), (r'C\+{0,2}轮', 'C'), (r'D\+{0,2}轮', 'D'),
        (r'Pre-IPO|上市前融资', 'Pre-IPO'),
        (r'IPO|首次公开|上市申请|敲钟|挂牌|过会|提交注册|F-4|S-1|招股书|注册声明', 'IPO'),
        (r'SPAC|借壳上市|特殊目的收购|合并协议.*上市|de-SPAC', 'SPAC'),
        (r'收购|并购|acquires?\b|acquisition', 'Acquisition'),
        (r'战略投资|战略融资|战投|注资|增资|战略配售', '战略融资'),
        (r'产业基金|引导基金|创投基金|母基金|专项基金|基金设立|设立.*基金|量子基金', 'Fund'),
    ]:
        if re.search(pat, text, re.I):
            return label
    # Catch-all: anything ending in 轮 that wasn't caught above
    if re.search(r'(?:[A-Za-z+]+|[一-鿿]{1,3})轮', text):
        return 'Unknown'
    # English rounds
    for pat, label in [
        (r'\bseed\b', 'Seed'), (r'\bangel\b', 'Angel'), (r'\bpre-a\b', 'Pre-A'),
        (r'series\s*a\b', 'A'), (r'series\s*b\b', 'B'), (r'series\s*c\b', 'C'),
        (r'series\s*d\b', 'D'), (r'grant|award|contract.*million|contract.*billion', 'Grant'),
        (r'\brais(?:e[ds]?|ing)\b.*\b(?:million|billion|funding|capital)\b', 'Unknown'),
    ]:
        if re.search(pat, text, re.I):
            return label
    return None


# ── Company extraction ────────────────────────────────────────────────

def extract_company(text):
    """Extract company name from title using entity_dict + custom Chinese list."""
    text_lower = text.lower()
    # Check Chinese companies first (more specific)
    for canonical, aliases in CHINESE_COMPANIES.items():
        for alias in aliases:
            if alias in text or alias.lower() in text_lower:
                return canonical
    # Check entity_dict institutions
    for canonical, aliases in INSTITUTIONS.items():
        for alias in aliases:
            if alias.lower() in text_lower:
                return canonical
    # Fallback: extract before "完成"/"获" + 轮 in Chinese
    m = re.search(r'(.{2,20}?)(完成|获|获得|宣布|签署|达成).{0,10}(轮融资|元融资|融资|投资)', text)
    if m:
        return m.group(1).strip()
    # Fallback: first entity-like phrase in English (Capitalized Words Inc/Ltd)
    m = re.search(r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})', text)
    if m:
        return m.group(1).strip()
    return None


# ── Tech route extraction ─────────────────────────────────────────────

TECH_ROUTE_GROUPS = {
    '超导量子计算': ['超导量子计算'],
    '光量子计算': ['光子量子计算'],
    '离子阱量子计算': ['离子阱量子计算'],
    '中性原子量子计算': ['中性原子量子计算'],
    '量子通信': ['量子密钥分发', '量子中继', '量子网络', '量子隐形传态', '纠缠分发'],
    '量子精密测量': ['量子磁力计', '量子重力仪', '量子时钟', '量子雷达', '量子惯性传感'],
    '硅自旋量子计算': ['硅自旋量子计算'],
    '拓扑量子计算': ['拓扑量子计算'],
}

def extract_tech_route(title, content, tags_data):
    """Extract tech route from text + existing tags."""
    text = (title + ' ' + (content or '')[:1000]).lower()
    # First: check existing tags (MySQL knowledge_graph.technologies)
    if isinstance(tags_data, dict) and 'knowledge_graph' in tags_data:
        kg = tags_data.get('knowledge_graph', {})
        techs = kg.get('technologies', [])
        for tech in techs:
            for group, members in TECH_ROUTE_GROUPS.items():
                if tech in members:
                    return group
    # Second: match TECH_PLATFORMS
    for group, members in TECH_ROUTE_GROUPS.items():
        for member in members:
            aliases = TECH_PLATFORMS.get(member, [])
            for alias in aliases:
                if alias.lower() in text:
                    return group
    return None


# ── Country detection ─────────────────────────────────────────────────

def detect_country(company, title, source_domain):
    """Detect country from company, title keywords, or domain."""
    # From company mapping
    if company in COMPANY_COUNTRY:
        return COMPANY_COUNTRY[company]
    if company in CHINESE_COMPANIES:
        return 'CN'
    # From title keywords
    title_text = title or ''
    if any(k in title_text for k in ['合肥', '北京', '深圳', '上海', '武汉', '杭州', '成都',
                                       '苏州', '南京', '济南', '广州', '无锡', '安徽', '浙江',
                                       '湖北', '四川', '山东', '江苏', '广东']):
        return 'CN'
    if re.search(r'美国|U\.S\.|United States|American', title_text, re.I): return 'US'
    if re.search(r'英国|U\.K\.|United Kingdom|British|London', title_text, re.I): return 'GB'
    if re.search(r'法国|France|Paris', title_text, re.I): return 'FR'
    if re.search(r'德国|Germany|Berlin', title_text, re.I): return 'DE'
    if re.search(r'日本|Japan|Tokyo', title_text, re.I): return 'JP'
    if re.search(r'加拿大|Canada|Toronto|Vancouver', title_text, re.I): return 'CA'
    if re.search(r'澳大利亚|Australia|Sydney', title_text, re.I): return 'AU'
    if re.search(r'新加坡|Singapore', title_text, re.I): return 'SG'
    if re.search(r'瑞士|Switzerland|Zurich|Geneva', title_text, re.I): return 'CH'
    if re.search(r'韩国|Korea|Seoul', title_text, re.I): return 'KR'
    if re.search(r'荷兰|Netherlands|Amsterdam', title_text, re.I): return 'NL'
    if re.search(r'芬兰|Finland|Helsinki', title_text, re.I): return 'FI'
    if re.search(r'印度|India|Bangalore', title_text, re.I): return 'IN'
    if re.search(r'以色列|Israel|Tel Aviv', title_text, re.I): return 'IL'
    # From domain TLD
    if source_domain:
        if '.cn' in source_domain: return 'CN'
        if '.jp' in source_domain: return 'JP'
        if '.de' in source_domain: return 'DE'
        if '.uk' in source_domain or '.co.uk' in source_domain: return 'GB'
        if '.fr' in source_domain: return 'FR'
    # Default: Chinese characters in title -> CN
    if re.search(r'[一-鿿]', title_text): return 'CN'
    return 'US'  # default for English content


# ── Investor extraction ───────────────────────────────────────────────

def extract_investors(title, content):
    """Extract investor names from text using entity_dict matching."""
    text = (title + ' ' + (content or '')[:500])
    investors = set()
    # Look for known institutions in text
    for canonical, aliases in INSTITUTIONS.items():
        for alias in aliases:
            if len(alias) >= 4 and alias.lower() in text.lower():
                investors.add(canonical)
                break
    # Also check Chinese company names as potential investors
    for canonical in CHINESE_COMPANIES:
        if canonical in text:
            investors.add(canonical)
    # Look for specific known investor patterns in Chinese
    investor_patterns = [
        '中科创星', '顺为资本', '高瓴创投', '红杉', '深创投', '毅达资本',
        '英诺天使', '蓝驰创投', '基石资本', '君联资本', '经纬创投', '达晨财智',
        'IDG', '鼎晖', '启赋资本', '联想创投', '天际资本', '普华资本',
        '蚂蚁集团', '科大讯飞', '华为哈勃', '中国移动', '比亚迪', '吉利',
        '复星', '商汤', '中芯聚源', '华泰', '中信建投', '光源资本',
        'BV百度风投', '北京金控', '工银资本', '招银国际', '深投控',
        '亦庄国投', '合肥高投', '浦东科创', '四川振兴', '容亿投资',
        '云岫资本', '指数资本', '张江浩成', '北工投资',
    ]
    for p in investor_patterns:
        if p in text:
            investors.add(p)
    return sorted(investors) if investors else []


# ── DB Readers ────────────────────────────────────────────────────────

def read_mysql():
    """Read capital ops articles from MySQL daily DB."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import Column, Integer, String, Text, Date, DateTime, JSON
    from sqlalchemy.orm import declarative_base
    import json as _json

    Base = declarative_base()
    class Article(Base):
        __tablename__ = 'articles'
        id = Column(Integer, primary_key=True)
        reference_url = Column(String(1000))
        liangke_url = Column(String(1000))
        title = Column(String(500))
        content = Column(Text)
        original_date = Column(Date)
        liangke_date = Column(Date)
        source_domain = Column(String(200))
        reference_title = Column(String(200))
        tags = Column(JSON)
        page_type = Column(String(20))

    engine = create_engine(
        f'mysql+pymysql://scraper:{os.environ.get("LIANGKE_MYSQL_PASSWORD", "")}'
        f'@127.0.0.1:3306/liangke_scraper?charset=utf8mb4',
        pool_pre_ping=True, echo=False)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        articles = session.query(Article).filter(Article.tags != None).all()
        results = []
        for a in articles:
            tags = a.tags
            if not tags: continue
            if isinstance(tags, str): tags = _json.loads(tags)
            if not isinstance(tags, dict): continue
            weekly = tags.get('weekly', [])
            if '资本运作' not in weekly: continue
            results.append({
                'id': f'mysql:{a.id}',
                'title': a.title or '',
                'content': a.content or '',
                'date': (a.original_date or a.liangke_date),
                'source_domain': a.source_domain or '',
                'tags': tags,
                '_source': 'liangke_daily',
            })
        return results
    finally:
        session.close()


def read_historical():
    """Read capital ops articles from historical SQLite DB."""
    conn = sqlite3.connect('D:/Claude_code/liangke_historical/historical_final.db')
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM articles WHERE tags LIKE '%资本运作%'")
    results = []
    for row in c.fetchall():
        tags_raw = row['tags'] or '[]'
        try: tags = json.loads(tags_raw)
        except: tags = []
        date_str = row['liangke_date'] or ''
        try: date = datetime.strptime(date_str[:10], '%Y-%m-%d').date()
        except: date = None
        results.append({
            'id': f'hist:{row["id"]}',
            'title': row['title'] or '',
            'content': row['content'] or '',
            'date': date,
            'source_domain': '',
            'tags': tags,
            '_source': 'historical',
        })
    conn.close()
    return results


def read_institutions():
    """Read capital ops articles from institution SQLite DB."""
    conn = sqlite3.connect('D:/Claude_code/institution_news/institutions.db')
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM articles WHERE tags LIKE '%资本运作%'")
    results = []
    for row in c.fetchall():
        tags_raw = row['tags'] or '{}'
        try: tags = json.loads(tags_raw)
        except: tags = {}
        date_str = row['publish_date'] or ''
        try: date = datetime.strptime(date_str[:10], '%Y-%m-%d').date()
        except: date = None
        title = row['title_cn'] or row['title'] or ''
        results.append({
            'id': f'inst:{row["id"]}',
            'title': title,
            'content': row['content'] or '',
            'date': date,
            'source_domain': row['source'] or '',
            'tags': tags,
            '_source': 'institution',
        })
    conn.close()
    return results


# ── Deduplication ─────────────────────────────────────────────────────

def _to_date(d):
    """Convert string or date to date object."""
    if d is None: return None
    if isinstance(d, datetime): return d.date()
    if isinstance(d, str):
        try: return datetime.strptime(d[:10], '%Y-%m-%d').date()
        except: return None
    return d

def deduplicate(records):
    """Deduplicate by (company, round, date within 7 days)."""
    groups = defaultdict(list)
    for r in records:
        key = (r.get('company') or 'unknown', r.get('round') or 'unknown')
        groups[key].append(r)
    result = []
    for key, group in groups.items():
        group.sort(key=lambda x: x['date'] or '0000-00-00')
        i = 0
        while i < len(group):
            cluster = [group[i]]
            base_date = _to_date(group[i]['date'])
            j = i + 1
            while j < len(group):
                d2 = _to_date(group[j]['date'])
                if base_date and d2 and abs((d2 - base_date).days) <= 7:
                    cluster.append(group[j])
                    j += 1
                else:
                    break
            best = max(cluster, key=lambda x: (x.get('amount_cny') or 0))
            result.append(best)
            i = j
    return result


# ── Main ──────────────────────────────────────────────────────────────

def main():
    print("Reading databases...")
    all_raw = read_mysql() + read_historical() + read_institutions()
    print(f"  Total capital ops articles: {len(all_raw)}")
    by_source = defaultdict(int)
    for r in all_raw: by_source[r['_source']] += 1
    for k, v in sorted(by_source.items()): print(f"    {k}: {v}")

    print("\nExtracting structured fields...")
    investments = []
    stats = {'amount_ok': 0, 'round_ok': 0, 'company_ok': 0, 'tech_ok': 0}
    for i, r in enumerate(all_raw):
        title = r['title']
        content = r['content']
        full_text = title + ' ' + (content or '')[:500]

        company = extract_company(full_text)
        if company: stats['company_ok'] += 1

        round_ = extract_round(title)
        if round_: stats['round_ok'] += 1
        elif '融资' in title or 'funding' in title.lower() or 'rais' in title.lower():
            round_ = 'Unknown'

        amount_cny = extract_amount_cny(full_text)
        amount_usd = extract_amount_usd(full_text)
        if amount_cny or amount_usd: stats['amount_ok'] += 1

        tech_route = extract_tech_route(title, content, r['tags'])
        if tech_route: stats['tech_ok'] += 1

        country = detect_country(company, title, r['source_domain'])
        investors = extract_investors(title, content)

        inv = {
            'id': r['id'],
            'company': company,
            'country': country,
            'round': round_,
            'amount_cny': amount_cny,
            'amount_usd': amount_usd,
            'tech_route': tech_route,
            'investors': investors,
            'date': r['date'].isoformat() if r['date'] else None,
            'title': title,
            'source_db': r['_source'],
        }
        investments.append(inv)

        if (i+1) % 100 == 0:
            print(f"  Processed {i+1}/{len(all_raw)}...")

    print(f"\n  Extraction stats:")
    for k, v in stats.items():
        print(f"    {k}: {v}/{len(all_raw)} ({100*v//len(all_raw)}%)")

    print("\nDeduplicating...")
    before = len(investments)
    investments = deduplicate(investments)
    print(f"  {before} -> {len(investments)} (removed {before - len(investments)} duplicates)")

    # Sort by date
    investments.sort(key=lambda x: x['date'] or '0000-00-00', reverse=True)

    # Country distribution
    country_counts = defaultdict(int)
    for inv in investments: country_counts[inv['country'] or '??'] += 1
    print(f"\n  Country distribution:")
    for k, v in sorted(country_counts.items(), key=lambda x: -x[1]):
        print(f"    {k}: {v}")

    # Output
    output_path = os.path.join(os.path.dirname(__file__), 'investments.json')
    output = {
        'meta': {
            'generated_at': datetime.now().isoformat(),
            'total_records': len(investments),
            'source_counts': dict(by_source),
        },
        'investments': investments,
    }
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\nOutput: {output_path}")
    print(f"Total records: {len(investments)}")


if __name__ == '__main__':
    main()
