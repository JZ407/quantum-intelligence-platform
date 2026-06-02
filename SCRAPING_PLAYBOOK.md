# 网页抓取工作流经验手册

> 基于量科网 3 类型 + 14 家机构 15 个源的实战总结。每次新抓取任务按此流程走。

---

## 流程总览

```
需求分析 ──→ 源侦察 ──→ 策略设计 ──→ 实现与调试 ──→ 质量验收
  (30min)     (1-2h)     (1-2h)        (2-4h)        (30min)
```

---

## 第一步：需求分析

明确三个问题：

| 问题 | 示例 |
|------|------|
| 抓什么？ | 量子科技新闻、学术论文、Press Release |
| 从哪抓？ | 量科网、IBM 博客、arXiv |
| 多久一次？ | 每日增量、一次性全量 |

**关键判断：内容类型决定抓取策略。**

### 常见内容类型矩阵

| 类型 | 特征 | 策略关键字 | 示例 |
|------|------|-----------|------|
| **快讯** (flash) | 短小、列表项含标题+日期、正文短短 | 从 body 首段取，跳过列表页标题 | 量科网快讯 |
| **参考** (reference) | 转载外部内容、含来源链接 | 专属 div 取正文，裁剪引用头部 | 量科网 arXiv 转载 |
| **长文** (article) | 编辑撰写、正文长、结构复杂 | 全 body 取，裁剪导航+尾部噪声 | 量科网编辑文章 |
| **博客** (blog) | 机构官网、标题清晰、日期分散 | sitemap/列表页发现、og:title 取标题 | IBM/Google 博客 |
| **新闻稿** (press) | 正式公告、独立栏目、标题格式统一 | 独立 URL 模式、需区分 blog | Quantinuum Press |
| **论文** (papers) | 无发布日期、元数据不同 | sitemap lastmod 回退、PDF 元数据 | Google Research |
| **产品页** | 非文章、应被过滤 | URL 模式黑名单 | `/products/`, `/about/` |

---

## 第二步：源侦察

拿到 URL 后，按优先级探测最佳抓取方式。

### 2.1 侦察决策树（优先级递减）

```
输入: 网站 URL
│
├─ 1. 查 Atom/RSS Feed ──────── 有且≥10条目、量子占比>15% ──→ 用 Feed 抓
│    方法: <link rel="alternate"> + /feed/ + /rss/
│
├─ 2. 查 Sitemap ────────────── 有、URL过滤命中、article_ratio>0.3 ──→ 用 Sitemap 抓
│    方法: robots.txt → sitemap.xml → sitemap_index.xml
│    过滤: URL 中含关键词(quantum/qubit/blog/news)，排除产品/关于页
│
├─ 3. 查 HTML 列表页 ────────── 翻页机制明确 ──→ 用列表页+翻页抓
│    方法: 聚类 URL 发现文章前缀模式，识别翻页方式
│
└─ 4. 放弃或人工介入 ───────── 动态加载、反爬严格 ──→ 评估 Playwright/Selenium
```

### 2.2 翻页机制识别

| 翻页类型 | 识别方法 | 处理方式 | 实例 |
|----------|----------|----------|------|
| URL 参数 `?page=N` | 检查 `<a href="?page=2">` | 拼接 URL 模板逐页请求 | IBM (`?page={n}`) |
| Hash 分页 `_page=N` | 检查 `<a href="?_page=2">` | 正则提取 hash key 拼接 | Quantinuum (`?f06a1293_page=N`) |
| 路径分页 `page/N/` | 检查 `<a href="page/2/">` | 拼接路径模板 | Microsoft (`page/{n}/`) |
| Button 翻页 | 检查 `<button data-page="2">` | 需要 `page_url_template` 配置绕过 | IBM (无 href 的 button) |
| 偏移分页 `&o=N` | 检查 `&o=50` 参数 | 设置步长和上限 | IBM PR (`&o=0,50,100`) |
| 无限滚动 (JS) | 翻页后 URL 不变 | 找 Feed/Sitemap 替代 | NVIDIA (HTML 无效→Feed 解决) |
| `<link rel="next">` | 标准 HTML 分页标记 | 最通用的兜底方案 | WordPress 站点 |

### 2.3 文章 URL 模式发现

抓取前先确认什么 URL 是文章、什么不是：

```
✅ 文章 URL 特征:
  - /blog/post-title
  - /news/2024/article-slug
  - /insights/quantum-computing-101

❌ 应过滤的 URL:
  - /products-solutions/       # 产品页
  - /company/about             # 关于页
  - /category/quantum          # 分类聚合页
  - /author/john-doe           # 作者页
  - /tag/quantum               # 标签聚合页
  - 首页 /                     # 网站首页
```

**技巧**：用 URL 长度/层级过滤——文章 URL 通常比导航 URL 层级更深、路径更长。

---

## 第三步：策略设计

确定抓取策略后，设计每类页面的提取器。

### 3.1 标题提取优先级链

```
1. og:title <meta property="og:title">    ← 通常最干净
2. h1 / h2 标签                             ← 详情页首选
3. <meta name="title">
4. <title> 标签                              ← 需去后缀("| Site Name")
5. JSON-LD headline
6. 列表页链接文本                             ← 兜底，可能混入正文
```

**常见后缀需清理**：`"| IBM Quantum Computing Blog"`、`" - Microsoft Azure Quantum Blog"`、`" | NVIDIA Technical Blog"`

### 3.2 正文提取策略

```
优先级:
  1. <article> 标签                           ← HTML5 语义标签
  2. [role="main"]                            ← ARIA 可访问性
  3. 站点专属 div class                       ← 需侦察确认
     - IBM: div.post-body
     - Quantinuum: div.blog-content
     - IonQ: .rich-text
     - liangke reference: div.refer-txt
  4. <main> 标签
  5. body 全文本（需裁剪导航/footer）         ← 最后兜底
```

### 3.3 正文裁剪规则

正文提取后必须裁剪噪声，按站点定制停止词：

| 噪声类型 | 识别方式 | 处理 |
|----------|----------|------|
| 面包屑导航 | 首段含 "Home > Blog >" | 跳过前 N 行 |
| 元数据行 | 日期/阅读量/分类标签行 | regex 匹配删除 |
| 作者署名 | "By John Doe, Published" | regex 匹配删除 |
| 社交媒体按钮 | "Share on Twitter/LinkedIn" | 关键词匹配跳过 |
| 相关文章推荐 | "Related Posts" / "You may also like" | 遇到停止词截断 |
| 评论区 | "Comments" / "Leave a reply" | 遇到停止词截断 |
| 作者 Bio | "About the Author" | 遇到停止词截断 |
| 页脚/版权 | Copyright / 粤ICP /备案号 | 遇到停止词截断 |
| 参考链接引用 | "参考链接¹" / "References" | 遇到停止词截断 |

**通用停止词集合**（按最早出现位置截断）：
```
Copyright, 粤ICP, 备案号, 参考链接, References,
Related Posts, You may also like, Share this,
About the Author, Leave a comment, 人气主题, 热点内容
```

### 3.4 日期提取回退链

```
1. <meta property="article:published_time" content="2024-03-15">
2. <meta name="awa-publishedDate" content="20240315">    ← Microsoft 专属
3. <time datetime="2024-03-15">
4. JSON-LD: {"datePublished": "2024-03-15"}
5. 正文文本正则:
   - "March 15, 2024"     → %B %d, %Y
   - "15 Mar 2024"        → %d %b %Y
   - "2024-03-15"         → \d{4}-\d{2}-\d{2}
   - "2024年3月15日"       → 中文日期
6. URL 路径: /2024/03/15/title-slug
7. Sitemap <lastmod>
8. 无日期 → 标记为 NULL，不入 "unknown" 占位
```

### 3.5 翻页终止条件

```
1. 返回空列表（无文章链接）
2. 状态码 404
3. 当前页文章全部在 seen_urls 中（去重集合全命中）
4. 达到 max_pages 上限（默认 10-30 页）
5. 下一页 URL == 当前页 URL（死循环保护）
```

---

## 第四步：实现与调试

### 4.1 核心防坑清单

| 坑 | 现象 | 修复 |
|----|------|------|
| **href 前导换行** | `href="\nhttps://..."` 导致 `startswith('http')` 失败 | 所有 URL 读取后立即 `.strip()` |
| **双链接去重** | 图片 `<a>` 和文字 `<a>` 指向同 URL，列表看起来是实际 2 倍 | `seen_urls` set 去重 |
| **CSS 类名变更** | 站点改版后 `div.txt` 从正文变侧边栏 | 用语义标签（article/main）优先 |
| **GBK 编码** | Windows 控制台打印中文崩溃 | `PYTHONIOENCODING=utf-8` |
| **API 限速** | DeepSeek 发送限速警告 | 请求间隔 ≥ 3s |
| **Cookie 过期** | 登录墙返回 "注册用户继续阅读" | 每次抓取前做登录态验证 |
| **翻页误判** | "next generation" 文本被当翻页链接 | 优先检查 href 中含 `_page=`/`?page=` |
| **Subprocess 死锁** | Windows PIPE + GBK 互扰 | 用 `import` 替代 `subprocess.run` |
| **unique constraint** | 多篇文章共享同一个外部参考链接 | 评估是否真需要唯一约束 |

### 4.2 Cookie / 登录态管理

```
抓取前验证:
  1. 请求一个已知需要登录的页面
  2. 检查响应中是否含登录墙关键词（"登录"、"login"、"注册"）
  3. 若过期 → 报错退出，不继续抓取（避免静默产生空内容）

Cookie 更新流程:
  1. 浏览器手动登录目标站
  2. F12 → Application → Cookies → 导出
  3. 保存为 pickle 文件
  4. 或: 关闭浏览器 → 运行 CDP 自动提取脚本
```

### 4.3 断点续传

大规模抓取（>100 篇）必备：

```python
# 模式1: 基于 DB 记录判断
already_scraped = set(db.get_all_urls())
new_urls = [u for u in discovered if u not in already_scraped]

# 模式2: 基于进度文件
progress = json.load(open('progress.json'))
start_from = progress.get('last_page', 0)
```

### 4.4 抓取日志

每次抓取记录（用于回归排查）：

```python
{
    "run_time": "2026-06-02 13:00",
    "source": "liangke_daily",
    "total_discovered": 25,
    "new_added": 8,
    "updated": 3,
    "skipped": 14,
    "errors": [],
    "duration_seconds": 54.2,
    "cookie_valid": true
}
```

---

## 第五步：质量验收

### 5.1 验收检查表

- [ ] **标题完整性**：随机抽 10 篇，标题长度 > 5 字，不含 HTML 标签碎片
- [ ] **正文有效性**：随机抽 10 篇，正文 > 100 字，不含 "注册用户继续阅读"
- [ ] **日期覆盖率**：≥ 95% 文章有非空日期
- [ ] **空内容率**：< 5%（抓了但正文为空）
- [ ] **重复率**：同一 source 下无同 URL 重复文章
- [ ] **噪声检查**：正文开头不含面包屑导航，结尾不含评论区/作者 Bio
- [ ] **链接有效性**：`reference_url` 以 `http` 开头，不以 `\n` 开头
- [ ] **类型标记**：`page_type` 字段正确（flash/reference/article/blog/press）

### 5.2 常见质量问题与修复优先级

| 问题 | 影响 | 修复方式 |
|------|------|----------|
| 正文为空 | 严重 | 检查 CSS 选择器是否过时，加 fallback |
| 标题为空 | 严重 | og:title → h1 → h2 多层兜底 |
| 日期缺失 | 中等 | 回退到 sitemap lastmod 或 URL 路径 |
| 正文截断 | 中等 | 去掉过早触发的停止词 |
| 正文含噪声 | 轻微 | 添加站点专属裁剪规则 |
| 类型错标 | 轻微 | URL 路由逻辑修正 |

---

## 实战速查：按源类型选策略

### 聚合站（量科网类）

```
特征: 多内容类型混在一个站点
策略: URL 路由 → 类型专属提取器

URL 含 /flash/     → flash 提取器: body 首段、跳过标题日期行
URL 含 /reference/ → reference 提取器: div.refer-txt、裁剪引用头尾
URL 含 /article/   → article 提取器: 全 body、裁剪导航+参考链接+footer
其他               → 跳过或 article 兜底
```

### 机构博客（IBM/Google/Quantinuum 类）

```
特征: 统一博客系统、有列表页或 sitemap
策略: 列表发现 → 详情页提取

标题: og:title（去后缀）
正文: <article> 标签优先，回退 <main>
日期: meta published_time → JSON-LD → 文本正则 → sitemap lastmod
翻页: URL 参数 > 路径 > Button 模板
```

### Press Release

```
特征: 与博客共享域名但独立栏目
策略: 独立源文件、专属 URL pattern

关键: 区分 Blog URL 和 Press URL
      Blog: /news/blog/some-title
      Press: /news/news/some-title (或 /press/)
```

### Sitemap 源

```
特征: 网站提供 sitemap.xml、无列表页
策略: XML 解析 → 关键词过滤 → 逐页详情

过滤: URL 中至少命中 1 个量子关键词
日期: <lastmod> 直接作为发布日期
风险: sitemap 可能含产品页等非文章 URL，需 article_ratio 判断
```

### Atom/RSS Feed

```
特征: 提供标准 Feed 端点
策略: XML 解析 <entry> → 逐页详情

优势: 比 HTML 列表干净 10 倍，自带日期+标题+链接
常见路径: /feed/, /rss/, /blog/feed/
```

---

## 一句话经验

1. **先侦察后动手** — 花 1 小时分析页面结构，比写 3 小时代码再调试省时间
2. **Feed > Sitemap > HTML** — 能走 Feed 不走 Sitemap，能走 Sitemap 不走 HTML 列表
3. **每种页面类型独立提取器** — 别用一个函数处理所有类型，互相冲突
4. **标题 og:title 第一，正文 article 标签第一** — 这是 Web 标准，大多数站遵守
5. **所有 href 先 strip** — 前导 `\n` 是最隐蔽的 bug
6. **Cookie 有效性每次检查** — 静默产生空内容比报错更糟糕
7. **裁剪规则按站点配** — 通用停止词有 80% 覆盖面，剩下 20% 需要站点专属
8. **日期提取走回退链** — 别只查一个地方，meta → JSON-LD → 文本 → URL → sitemap
9. **seen_urls 全局去重** — 图片+文字双链接是最常见的重复源
10. **大规模抓取必须断点续传** — 中断后从头开始是对 API 和时间的双重浪费
