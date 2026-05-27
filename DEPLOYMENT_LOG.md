# 部署日志：Claude Code + Kimi-k2.6 + 本地 RAG 知识库

> 记录从 0 到 1 搭建本地知识库 + 线上 LLM 的完整决策链与踩坑点，供复现参考。

---

## 1. 需求确认阶段

**原始需求**：构建一个本地知识库。  
**环境约束**：
- Windows 11，Python 3.14.5
- 无本地 GPU / 不打算部署本地 LLM
- 已有 Kimi API Key

**架构决策**：本地 RAG（检索）+ 线上 LLM（生成）。

---

## 2. 方案选型

| 维度 | 候选方案 | 决策 |
|------|----------|------|
| 嵌入模型 | BM25（纯 Python）/ OpenAI API / sentence-transformers | **两阶段**：先 BM25 验证链路，再切 sentence-transformers |
| 向量存储 | JSON 文件 / ChromaDB / FAISS | **两阶段**：先 JSON 验证，再切 FAISS |
| LLM 客户端 | 自制 urllib / openai SDK / httpx | **自制 urllib**（零依赖），后续升级到 httpx |
| 切分策略 | fixed / paragraph / recursive | **recursive**（保留语义完整性） |

**为何不做 LangChain / LlamaIndex**：
- 依赖重，Python 3.14 兼容性未知
- 用户需要透明可控的代码，方便后续魔改
- 核心逻辑仅 500 行左右，自研成本可控

---

## 3. 第一阶段：BM25 + JSON（验证链路）

**实现内容**：
- `loader.py`：支持 txt/md/pdf/pptx/docx
- `chunker.py`：RecursiveCharacterTextSplitter
- `embedder.py`：纯 Python BM25
- `vector_store.py`：JSON 持久化 + 余弦/点积检索
- `llm_client.py`：多厂商兼容（OpenAI/Claude/DeepSeek/Kimi）
- `kb_manager.py` + `pipeline.py`：端到端 RAG

**验证结果**：
- build_kb.py ✅
- query_kb.py ✅（检索 + LLM 生成均通过）

---

## 4. 第二阶段：语义嵌入 + FAISS（升级）

**触发条件**：用户要求"除了 chromadb 都装上"，测试发现 torch/sentence-transformers/faiss-cpu 在 Python 3.14 上可编译安装。

**改动点**：
1. `embedder.py` + `SentenceTransformerEmbedder`（all-MiniLM-L6-v2）
2. `vector_store.py` + `FaissVectorStore`（IndexFlatIP + L2 归一化）
3. `kb_manager.py`：根据 `embedding.provider` 自动切换 store 类型
4. `config.yaml`：`provider: "local"`
5. `build_kb.py` / `query_kb.py`：适配 FAISS 双文件格式（.faiss + .docs）

**验证结果**：
- 语义相似度分数从 0.4189（BM25）提升到 0.5432（FAISS）
- 索引体积：JSON 单文件 → FAISS 1.6K + docs 606B

---

## 5. 踩坑记录

### 5.1 Kimi k2.6 temperature 限制

**现象**：调用 `kimi-k2.6` 返回 `400 invalid temperature: only 1 is allowed for this model`。  
**根因**：Moonshot 对 k2.6 的采样策略做了硬限制。  
**修复**：LLMClient 中实现 `temperature=None` 时从 payload 中**省略**该字段，config.yaml 中写 `temperature: null`。

### 5.2 Moonshot 域名混淆

**现象**：
- `api.moonshot.cn` + `moonshot-v1-8k` → **200 OK**
- `api.moonshot.cn` + `kimi-k2.6` → **400**（模型名问题）
- `api.moonshot.ai` + 任意模型 → **401 Unauthorized**

**根因**：国内版 Key 绑定在 `.cn` 域名，与国际版 `.ai` 不互通。  
**修复**：确认用户 Key 来源后，统一使用 `https://api.moonshot.cn/v1`。

### 5.3 Python 3.14 兼容性

**原以为**：torch/faiss-cpu 在 Python 3.14 上无法安装（官方 wheel 滞后）。  
**实际**：`pip install sentence-transformers faiss-cpu` 成功编译并运行，耗时约 3-5 分钟。

### 5.4 索引格式兼容性

**现象**：从 BM25（JSON）切换到语义嵌入（FAISS）后，`build_kb.py` 仍硬编码保存为 `.json`。  
**修复**：修改 `kb_manager.save()` 自动根据 store 类型推断文件后缀，修改 `build_kb.py` 调用 `kb.save()` 不传路径。

---

## 6. 最终配置快照

```yaml
embedding:
  provider: "local"
  model: "all-MiniLM-L6-v2"

llm:
  provider: "openai"          # OpenAI-compatible
  model: "kimi-k2.6"
  api_key: "sk-..."
  api_base: "https://api.moonshot.cn/v1"
  temperature: null           # k2.6 不支持自定义 temperature
```

---

## 8. 第三阶段：Reranker + 增量更新 + 三库并行（2026-05-22）

**触发条件**：用户硬件确认为 i9-13900H + 32GB RAM + RTX 4060 4GB，希望根据文档语言选择最优嵌入模型，并要求接入 reranker 与增量更新。

### 8.1 硬件适配与模型选型

| 组件 | 规格 | 模型决策 |
|------|------|----------|
| CPU | i9-13900H (20T) | CPU fallback 充足 |
| RAM | 32GB | 可承载 bge-large 系列（~1.3GB） |
| GPU | RTX 4060 4GB | 可 CUDA 加速 embedding，但不足本地 7B LLM |

**结论**：LLM 继续走 Kimi-k2.6；本地嵌入模型按语言分库。

### 8.2 三库并行架构

| 库 | 配置 | 模型 | chunk | 用途 |
|----|------|------|-------|------|
| **Lite** | `config.yaml` | all-MiniLM-L6-v2 | 500 | 中文轻量/快速验证 |
| **Pro** | `config_pro.yaml` | bge-large-zh-v1.5 | 800 | 中文深度分析（院士稿、政策） |
| **EN** | `config_en.yaml` | bge-large-en-v1.5 | 1500 | 纯英文论文 |

切换方式：`python examples/query_kb.py --config config_pro.yaml`

### 8.3 Reranker 接入

**模型**：`BAAI/bge-reranker-base`（~1.1GB，CPU 推理）。
**流程**：先召回 top-20 → CrossEncoder 精排 → 取 top-5 给 LLM。
**效果**：相关文档得分从 0.62 提升到 0.96+，弱相关文档被有效过滤。

### 8.4 增量更新

**改动**：`build_kb.py` 新增 `--incremental` / `-i` 参数。
**逻辑**：加载已有索引 → 对比文件 source 列表 → 只编码新增文件 → 直接 append 到 FAISS index。
**修复**：`kb_manager.py` 中 `self.store = VectorStore()` 硬编码改为 `type(self.store)()`，避免 FaissVectorStore 被误替换。

### 8.5 语义检索对比结论

- **中文场景**：bge-large-zh-v1.5 显著优于 all-MiniLM-L6-v2（5/5 相关 vs 1/5 相关）
- **英文场景**：bge-large-en-v1.5 得分更高、排序更合理（0.85+ vs 0.57+）
- **语言对齐**：中文问题优先召回中文文档，英文问题优先召回英文文档

### 8.6 txt + metadata 分离与稳定 chunk_id（2026-05-22）

**问题**：`sync_liangke.py` 早期版本把 tags、dates、URLs 直接拼进 txt，导致标签变更必须重新编码向量；FAISS 索引依赖顺序编号，删除文件后索引错位。

**改动**：
1. **`article_to_txt()`** 只返回 `标题 + body`，tags/dates/URLs 移到 `build_metadata()`。
2. **`refresh_metadata()`**：仅更新 `.docs` JSON，不碰 `.faiss` 向量文件。
3. **`chunk_id`**：由 `chunk_id_prefix`（如 `liangke_79`）+ 分段序号生成最终 ID（如 `liangke_79_0`），写入 metadata。非桥接文档回退到 `Path(source).stem_{i}`。

**验证**：Pro 知识库 37 个 liangke chunks 全部带有稳定 chunk_id，26 篇文章覆盖完整。

### 8.7 抓取与知识库自动桥接（2026-05-22）

**问题**：用户运行 `scrape_daily.py` 后知识库未更新，因为抓取只写 MySQL，不会自动触发 `sync_liangke.py`。

**改动**：新增 `examples/run_daily_pipeline.py`，一键完成：
1. 调用 `liangke_daily/core/scrape_daily.py` 抓取当日新闻入库
2. 调用 `sync_liangke.py --days 1` 增量同步到 Pro 知识库

**用法**：`python examples/run_daily_pipeline.py`

### 8.8 标签变更后 metadata 自动刷新（2026-05-22）

**问题**：用户更新 `scrape_daily.py` 标签库后重新抓取，数据库 tags 已变，但 `sync_liangke.py` 增量模式跳过已有文件，metadata 不更新。

**改动**：
1. **`sync_liangke.py`**：增量模式下对比已有文章的 `tags` 字段，若不同自动调用 `refresh_metadata()`，无需手动 `--refresh-metadata`。
2. **`kb_manager.refresh_metadata()`**：重写 metadata 时保留旧 `chunk_id`，避免稳定标识丢失。

**验证**：全量同步 80 篇文章，112 个 chunks 的 tags 自动刷新，全部 `chunk_id` 完好保留。

### 8.9 每日管道从 subprocess 改为直接导入（2026-05-22）

**问题**：`run_daily_pipeline.py` 使用 `subprocess.run` 调用抓取和同步脚本，在 Windows 上因 GBK 控制台编码与 PIPE 机制互相干扰，导致管道死锁、运行 15 分钟仍不结束。单独运行抓取只需 54 秒。

**改动**：
1. **`run_daily_pipeline.py`**：抛弃 `subprocess.run`，改为直接 `import scrape_daily` 和 `sync_liangke` 并调用其 `main()` 函数。
2. **`sync_liangke.py`**：`main()` 接受可选 `args` 参数，支持程序化传参（如 `main(['--days', '1'])`）。

**验证**：Pipeline 总耗时从 **>15 分钟（死锁）** 降至 **62.8 秒**。

### 8.10 量科网日期提取鲁棒性修复（2026-05-22）

**问题**：用户发现 Quantum Bridge 文章在量科网显示 2026-05-21，但数据库被记为 2026-05-22。`fetch_article_detail` 对 flash 页面仅查找 `<time>` 标签，某些运行时提取失败回退到 `today`，且 `insert_or_update_article` 无条件覆盖旧日期。

**改动**：
1. **`scrape_daily.py`**：`fetch_article_detail` 增加 `span/div/p.time/date/published` fallback 选择器。
2. **`db.py`**：`insert_or_update_article` 更新时，若新 `liangke_date` 晚于旧值则保留旧值，防止 `today` fallback 污染历史记录。
3. 新增 `fix_liangke_dates.py`：批量重抓修正已有错误日期。

**验证**：16 篇文章被检查，id=67（Quantum Bridge）从 2026-05-22 修正为 2026-05-21，知识库同步后旧 chunks 已清理替换。

---

## 9. 待办 / 未来方向

- [x] 接入 Reranker 精排模型（bge-reranker-base）
- [x] 实现增量更新（--incremental）
- [x] 多配置文件切换（Lite/Pro/EN）
- [x] 量科网每日数据桥接（MySQL → RAG 增量入库）
- [x] txt + metadata 分离（标签/日期变更无需重新编码向量）
- [x] 稳定 chunk_id（避免依赖 FAISS 顺序索引）
- [x] Streamlit 日报生成器（一键生成 Word + 远程访问）
- [x] ngrok 内网穿透试验（后卸载，切换为直接公网访问）
- [x] HuggingFace 镜像配置（hf-mirror.com，解决中国大陆超时）
- [ ] 用 `httpx` 替换 `urllib`（更稳定、支持异步）
- [ ] 接入 `jieba` 优化中文 BM25 分词（备用方案）
- [ ] 用 `rich` 美化 `query_kb.py` 的终端交互
- [ ] 支持网页抓取（beautifulsoup4）直接入知识库
- [ ] 评估 ChromaDB（虽然用户当前未选择，但可保留接口）

---

## 10. 第四阶段：Streamlit 日报生成器 + 内网穿透（2026-05-22）

**触发条件**：用户需要每日筛选重要新闻生成 Word 日报，并让同事通过网页远程访问一键生成。

### 10.1 Streamlit 日报生成器

**功能**：
- 选择日期 → 从 MySQL 读取当天文章 → 按优先级自动选 top-3
- 优先级：资本运作 > 产品动态 > 企业资讯 > 科技前沿 > 宏观态势
- 生成 Word 文档，一键下载

**文件**：`examples/daily_report_app.py`

### 10.2 pd.read_sql JSON 解析修复

**问题**：`pd.read_sql` 不自动解析 MySQL JSON 列，tags 全部显示为空列表 `[]`，导致 `select_top3()` 无法按优先级筛选。

**修复**：在 `fetch_articles()` 中添加 `json.loads` 显式解析 tags 列。验证：15 篇文章全部正确解析。

### 10.3 Word 格式定制

**要求**：
- 文件名：`日报{日期}.docx`
- 大标题：`每日情报资讯（XXXX-XX-XX）：`，微软雅黑 3 号
- 新闻标题：微软雅黑 3 号加粗
- 内容摘要：微软雅黑 4 号
- 参考链接：微软雅黑 5 号蓝色
- 末尾专利占位：`4、专利：`（3 号）+ 空行（4 号）+ `参考链接：`（5 号）

**实现**：`_set_run_font()` 辅助函数同时设置西文和东亚字体（`w:eastAsia`）。

### 10.4 访问方式与内网穿透

| 地址 | 范围 |
|------|------|
| `http://localhost:8501` | 本机 |
| `http://192.168.5.113:8501` | 局域网 |
| `http://38.150.71.74:8501` | 公网（需端口映射） |

**ngrok 试验**：
- 安装 pyngrok + ngrok，配置 authtoken，成功创建 `https://xxx.ngrok-free.dev` 公网隧道
- 后卸载（用户确认不再需要，直接使用公网 IP 访问）

**启动脚本**：`start_daily_report.bat`，双击启动 + 显示三个访问地址。

### 10.5 HuggingFace 镜像配置

**问题**：中国大陆直连 `huggingface.co` 超时，`run_daily_pipeline.py` 和 `sync_liangke.py` 加载 BGE 模型时卡住。

**修复**：在两个脚本开头设置 `os.environ.setdefault('HF_ENDPOINT', 'https://hf-mirror.com')`，使用清华镜像。

**验证**：镜像模式下模型加载秒过，同步 19 篇文章、12 chunks 成功。

### 10.6 日报生成器交互升级（2026-05-24）

**触发条件**：用户希望从「系统自动选 3 条」改为「用户手动勾选 3 条」，增加自由度；同时要求 Word 输出保留全文并首行缩进。

**改动点**：
1. **手动勾选**：新闻列表左侧增加 `st.checkbox`，用户自选要纳入日报的文章。
2. **数量提示**：日报生成区根据勾选数量给出动态提示（0 条→提示勾选，1–2 条→提示再选，3 条→可生成，>3 条→取前 3 条）。
3. **全文保留**：`build_docx()` 去掉原来的 `content[:300]` 截断，完整输出正文。
4. **首行缩进 2 字符**：正文按换行符拆分，每段独立创建段落并设置 `first_line_indent = Cm(0.74)`（约 14pt 微软雅黑下 2 字符）。

**文件**：`examples/daily_report_app.py`

---

## 11. 周报生成系统（已取消）

**时间**：2026-05-24
**状态**：项目取消，相关文件已清理，DEPLOYMENT_LOG 保留记录。

### 11.1 已完成的部分

- LaTeX 模板渲染 + xelatex 编译（封面、目录、摘要、5 分类正文、会议表格、招投标表格、专利动态）
- MySQL → 分类 → LLM 趋势摘要 → PDF 的完整链路
- 新闻内容预处理：删除模糊时间词、添加日期前缀、清理破折号
- quantum.info/conf/ 会议抓取 + 月份过滤
- 会议翻译（LLM 批量英译中，保留缩写）
- 招投标/专利 Excel 解析（灵活列名匹配）
- 专利 LLM 筛选 + 按领域分组
- Streamlit 周报 UI（日期范围、期数、Excel 上传、PDF 下载）

### 11.2 取消原因

- 会议翻译调试过程中发现 kimi-k2.6 对长列表批量翻译的响应不稳定（28 条会议返回空 content），需分批处理，维护成本上升
- 用户决定暂停该方向，聚焦其他工作

### 11.3 已清理的文件

- `examples/generate_weekly_report.py`
- `examples/weekly_report_app.py`
- `examples/conf_fetcher.py`
- `weekly_templates/weekly_report_template.tex`
- `weekly_output/` 目录（所有生成的 PDF、tex、log 等）

---

## 12. 情报资讯平台重构与周报重启准备（2026-05-24）

### 12.1 应用架构重构

**触发条件**：用户希望将原「量科网每日资讯」升级为「量子科技情报」综合平台，整合每日资讯、历史检索、会议信息。

**改动点**：
1. **品牌升级**：应用总标题改为「量子科技情报」，侧边栏导航改为「每日资讯」+「会议信息」。
2. **页面拆分**：将原单页拆分为 `page_daily_news()` 和 `page_conferences()`，通过 `st.sidebar.radio` 切换。
3. **每日资讯页内标题**：「量科网每日情报资讯」。

**文件**：`examples/daily_report_app.py`

### 12.2 历史数据库深度接入

**数据规模**：量科历史库（SQLite）共 8,953 篇文章，时间跨度 2021-11-18 ~ 2026-05-21。

**接入功能**：
1. **双数据源切换**：页面顶部增加「量科每日库 / 量科历史库」选择框。
2. **日期范围限制**：每日库最小可选 2026-04-11，历史库最小可选 2021-11-18，下方标注记录起始时间。
3. **关键词检索**：支持标题+正文实时过滤。

**历史库数据清洗**：
1. **标题提取**：发现 flash 类型 8,670 篇文章的 `title` 字段格式为 `【真正标题】混有正文内容`，通过正则提取 `【】` 内文本。批量更新 7,517 篇，平均长度从 130.6 → 32.5 字符。
2. **标签补全**：历史库原始 `tags` 为空，基于标题关键词做规则分类（严格优先级：资本运作 > 产品动态 > 企业资讯 > 科技前沿 > 宏观态势），每篇只打一个标签。
3. **链接兜底**：`reference_url` 优先返回量科网 `liangke_url`，避免原始来源链接失效。

**新增脚本**：
- `examples/clean_historical_titles.py`：批量清洗历史库标题
- `examples/build_conference_cache.py`：会议缓存构建（供周报复用）

### 12.3 会议信息展示

**实现**：新增「会议信息」导航页，读取本地 `data/conferences_zh.json`，支持 1–12 月筛选，表格展示日期、中文名称、中文地点、链接。

**数据来源**：quantum.info/conf/ 共 211 场会议，由用户人工翻译后生成 JSON 缓存。

### 12.4 周报系统重启准备

**状态**：从「已取消」转为「重启准备中」。

**已完成**：
1. 恢复 `examples/conf_fetcher.py`（会议抓取）。
2. 会议翻译方案改为「本地 JSON 缓存」：`examples/build_conference_cache.py` + `data/conferences_zh.json`，彻底绕过 LLM 实时翻译的不稳定问题。
3. 已清理的周报核心文件（`generate_weekly_report.py`、`weekly_report_app.py`、`weekly_report_template.tex`）尚未恢复，待后续需要时重建。

### 12.5 日报生成器最终交互形态

**在 10.6 基础上进一步调整**：
1. **数据源感知**：切换历史库时，新闻列表、勾选、生成日报全部通用。
2. **widget key 隔离**：checkbox 和按钮 key 加入数据源前缀（`daily_` / `hist_`），避免两个库 ID 冲突。
3. **Word 输出**：保留全文 + 首行缩进 2 字符（`Cm(0.74)`）。

---

## 13. 待办 / 未来方向

- [ ] 恢复周报核心文件（`generate_weekly_report.py`、`weekly_report_app.py`、`weekly_report_template.tex`）
- [ ] 招投标/专利 Excel 解析实测（需要样例文件）
- [ ] 用 `httpx` 替换 `urllib`（更稳定、支持异步）
- [ ] 接入 `jieba` 优化中文 BM25 分词（备用方案）
- [ ] 用 `rich` 美化 `query_kb.py` 的终端交互
- [ ] 支持网页抓取（beautifulsoup4）直接入知识库
- [ ] 评估 ChromaDB（虽然用户当前未选择，但可保留接口）

---

## 14. 历史库全量重抓 + 情报资讯平台深化（2026-05-24）

### 14.1 LLM 切换

**触发条件**：Kimi k2.6 对长列表批量翻译响应不稳定，且用户决定统一使用 DeepSeek。

**改动**：`config.yaml` 中 LLM 配置从 `kimi-k2.6 @ moonshot.cn` 切换为 `deepseek-v4-pro @ api.deepseek.com`。

### 14.2 历史库全量重抓

**背景**：旧历史库存在标题混入正文、无标签、部分链接失效等问题，用户决定从量科网重新抓取全量数据。

**抓取规模**：flash 8,685 篇 + news 150 篇 + reference 100 篇 = **8,935 篇**。

**实现**：`examples/full_scrape_history.py`
- 分两步执行：列表页抓取（~450 页，10 分钟内完成）+ 详情页抓取 + LLM 打标签
- **支持断点续传**：中断后重新运行自动从未处理文章继续
- **标签自动生成**：每篇详情抓取后用 DeepSeek-v4-pro 从 27 个标签中选取适用标签（多选，通常 2-4 个）
- **标题清洗**：列表页和详情页均提取【】内内容或 h2 标题，丢弃混入的正文
- **日期提取**：flash 从详情页正则匹配，news 从 span.time 获取
- 修复 Unicode 打印崩溃问题（GBK 编码）
- **数据库**：`D:/Claude_code/liangke_historical/historical_v2.db`

**当前状态**：详情抓取后台运行中（约 207/8935 已完成），预计总耗时 10-12 小时。

### 14.3 会议数据库

**触发条件**：用户翻译了会议日期并希望用数据库管理会议信息。

**实现**：
- 新建 `D:/Claude_code/conference_db/` 项目
- `conferences.db`：SQLite 数据库，211 条会议，含 date_str / month / name_zh / location_zh / url
- `build_db.py`：从 Excel 或 JSON 导入数据的建库脚本
- `daily_report_app.py` 中 load_conferences 改为从 SQLite 读取（60s 缓存）

### 14.4 情报资讯交互深化

**改动**：
1. **检索架构分离**：
   - 日期选择器仅用于日报生成和当日浏览
   - 关键词检索框独立，输入即跨**全库搜索**，不限日期
   - 搜索结果每条新闻标注日期
2. **数据导出**（底部独立区域）：
   - 日期范围选择（开始/结束）
   - 关键词筛选
   - 标签筛选（27 个标签多选）
   - 导出格式：Excel (.xlsx) / SQLite (.db)
   - 三个筛选条件可组合，导出时重新查询数据库
3. **新闻列表**：每条新闻显示日期和标签，tag 以 `·` 分隔

**文件**：`examples/daily_report_app.py`、`examples/full_scrape_history.py`

### 14.5 每日新闻抓取

**执行**：`run_daily_pipeline.py` 运行正常，抓取 2026-05-24 当日新闻。新增 12 篇，更新 8 篇，RAG Pro 知识库同步至 893 chunks，总耗时 105.5 秒。

---

## 15. 周报系统恢复与专利/招投标深度集成（2026-05-24）

### 15.1 核心文件恢复

恢复了三份被删除的周报核心文件：
- `examples/generate_weekly_report.py`：CLI 生成脚本
- `weekly_templates/weekly_report_template.tex`：LaTeX 模板
- 会议改为从 `data/conferences_zh.json` 本地缓存读取

### 15.2 LLM 三轮内容处理

| 步骤 | 功能 | 说明 |
|------|------|------|
| 1. 内容清洗 | 删模糊时间词、修日期重复 | 57 篇文章一次调用批量检查 |
| 2. 长文精简 | >400 字文章全文送 LLM 精简至 300 字 | 22 篇长文一次调用 |
| 3. 段摘要 | 每类一段 100-150 字概括 | 替换"一句话+长标题列表" |

### 15.3 专利动态完整集成

**上传流式**：
1. 单入口多文件上传，按文件名含板块名自动归类 5 个板块
2. 按 `公开(公告)日` 筛选本周专利
3. >8 条触发 LLM 按优先级排名（授权 > 公开 > 实用新型 > 外观），精选 8 条
4. 使用 `标题(译)(简体中文)` 和 `摘要(译)(简体中文)` 列
5. 从 `公开(公告)号` 列提取智慧芽超链接（openpyxl）

**关键 bug 修复**：CLI `_parse_patent_df` 缺 `url` 列映射，导致 UI 保存的临时 Excel 传入 CLI 后链接丢失。添加 `url` 列候选 + column 回退读取解决。

**模板调整**：
- 专利动态移至产品动态后、企业资讯前
- 申请人/发明人/公开日各占独立行
- `group.items` → `group.entries`（Jinja2 与 dict.items() 冲突）
- 摘要区新增专利概况

### 15.4 招投标集成

- `_parse_tender_df`：灵活列名匹配中英文字段
- UI + CLI 均支持上传

### 15.5 交互界面

**新增「周报生成」导航页**：
- 日期范围、期号、会议月份
- 招投标单文件上传
- 专利单入口多文件上传（按文件名自动归板）
- 生成按钮 + 下载/状态并排显示（`session_state` 持久化）

### 15.6 模板细节修复汇总

- 封面日期 `YYYY.MM.DD` 点分隔
- 摘要「摘 要」居中，两字 2em 间距
- 摘要每类一段概括，不再拼接标题列表
- 日期前缀正则扩展至带年份格式，清除内容开头事件日期
- 新闻内容预处理：正则清理 + LLM 审核双保险

---

## 16. 历史库全量抓取完成 & API 限速处理（2026-05-25）

### 16.1 API 限速与密钥更新

**问题**：全量抓取期间 LLM 调用频率过高，DeepSeek 发送限速警告邮件并终止访问。

**处理**：
1. 更换新 API key（`config.yaml`）
2. `full_scrape_history.py` 延迟从 0.5s → **3.0s**，避免触发限速

### 16.2 历史库全量抓取完成

**结果**：8,935/8,935 全部完成，每篇均已打上 LLM 标签。

| 类型 | 数量 |
|------|------|
| flash | 8,685 |
| news | 150 |
| reference | 100 |
| **总计** | **8,935** |

**数据库**：`D:/Claude_code/liangke_historical/historical_v2.db`

### 16.3 交互页面切换

`daily_report_app.py` 中 `HISTORICAL_DB_PATH` 从旧库 `historical.db` 切换为 `historical_v2.db`，历史检索使用新版带标签数据。

---

## 17. Cookie 过期 & 提取方式修复（2026-05-25）

### 17.1 问题链

1. 每日抓取返回"注册用户继续阅读" → 量科网 Cookie 过期
2. 尝试从 Edge SQLite 直读 Cookie → 解密失败（Edge 存的是 `encrypted_value` 密文）
3. 用户手动 F12 获取 Cookie 值 → 写成 pickle，但路径错误（多个项目各自读不同路径）

### 17.2 两个项目的 Cookie 路径

| 项目 | Cookie 路径 |
|------|-------------|
| `liangke_daily` | `data/cookies/qtc_cookies.pkl` |
| `liangke_historical` | `qtc_cookies.pkl`（项目根） |

每次 Cookie 过期需**同步更新两份**。

### 17.3 解决方案

- 创建 `update_cookie.bat`：通过 Edge CDP 协议自动提取 Cookie（`core/extract_cookie.py`，之前已存在），绕过 SQLite 加密，自动同步到两个项目
- 后续 Cookie 过期：Edge 登录量科网 → 关闭 Edge → 双击 `update_cookie.bat`

### 17.4 其他修复

- 每日抓取 `scrape_daily.py` 增加空内容/注册墙检测，跳过无内容文章
- 封面图移入 `weekly_templates/`，清理旧模板文件夹
- 清理 `D:/Claude_code/` 所有临时文件
- 配置 Windows 定时任务，每天 13:30 自动抓取（`schtasks` + `daily_scrape.bat`）
- 交互页面历史库查询修复：列名 `liangke_date`（非 `published_at`）、日期 LIKE 匹配（非精确匹配）、tags JSON 解析

### 17.5 Cookie 路径确认

**发现**：每日抓取脚本读取的实际路径为 `liangke_daily/data/cookies/qtc_cookies.pkl`（非之前以为的 `cookies/` 目录）。extract_cookie.py 之前已存在但 update_cookie.bat 从未创建，本次补上。Cookie 过期后的正确流程：Edge 登录量科网 → 关闭 Edge → 双击 `update_cookie.bat` → 自动同步到两个项目。

### 17.6 项目清理

- 封面图移入 `weekly_templates/Cover_Suzhou.png`，删除旧模板文件夹
- 清理 `D:/Claude_code/` 及 `rag_system/` 全部临时文件（`.txt`、`.log`、`test_*.docx`、编译中间文件）

---

## 18. RAG 四大优化 + 统一入库（2026-05-26）

### 18.1 Metadata 过滤（`retriever.py`）

**实现**：检索时支持 `filter_tags`（27 个标签）和 `date_from`/`date_to`（日期范围）。后过滤策略：先召回 3 倍候选 → Python 条件筛选 → reranker 精排。

**CLI 交互**：`/tags 资本运作,融资` `/from 2026-05-01` `/to 2026-05-25` `/clear`

**穿透**：`retriever.py` → `pipeline.py` → `kb_manager.py` → `query_kb.py`

### 18.2 混合检索 Dense + BM25（`retriever.py` + `kb_manager.py`）

**实现**：每次查询并行搜索两路：
- FAISS dense（bge-large-zh-v1.5 语义向量）
- BM25 sparse（关键词 IDF 向量，`bm25_store`）

结果用 RRF（倒数排名融合）合并去重。BM25 store 与 FAISS 同步增量更新，独立持久化为 `kb_index.bm25`。

### 18.3 Query 改写（`pipeline.py`）

**实现**：可配置的 LLM 预改写步骤。`config_pro.yaml` 中 `rag.query_rewrite: true` 开启后，用户口语化问题先送 LLM 转为检索关键词短语再查询。关闭则直搜。

### 18.4 跨语言 EN fallback（`retriever.py` + `kb_manager.py`）

**实现**：`enable_cross_en()` 方法加载 EN 索引，每次查询同时搜 Pro + EN，两路 RRF 合并。无阈值门槛，始终双路。按钮配置：`config_pro.yaml` 中 `cross_en_fallback: true`。

### 18.5 Lite Reranker 启用

`config.yaml` 中 `reranker.model` 从 `null` 改为 `"BAAI/bge-reranker-base"`，一行改动。

### 18.6 统一入库 (`data_all/` + `build_all_kb.py`)

**新增文件**：
- `rag_system/lang_detect.py`：字符比例语言检测（中文/英文 ratio 计算）
- `examples/build_all_kb.py`：扫描 `data_all/` → 自动判断语言 → 路由到对应 KB → 构建

**路由规则**：CN chars > 40% → Pro，EN chars > 40% → EN，两者都达标 → Pro + EN。

**使用方式**：文件丢 `data_all/` → `python examples/build_all_kb.py`。

### 18.7 修复

- `vector_store.py`：FAISS 索引越界保护
- `config_pro.yaml`：LLM 从 kimi-k2.6 切换为 deepseek-v4-pro

---

## 19. 历史库分析能力建设 & 报告提醒系统（2026-05-26）

### 19.1 历史库合理性分析

**分析结论**：
- 时间覆盖优秀：近 12 月每月 208–325 篇，4.5 年跨度适合年对年对比
- 内容类型单一：97% 为 flash 快讯，平均 192 字，适合频次/趋势量化分析
- 标签分布偏斜：宏观态势占 64%，需 LLM 重新分类
- 缺失精确去重：同一事件连续多日报道未聚合

### 19.2 精确去重（`examples/dedup_historical.py`）

**两轮策略**：
1. 精确 URL 匹配 → same URL = duplicate
2. 标题相似度 > 80% + 时间差 ≤ 3 天 → near duplicate
保留正文最长版本，去重结果写入 `dedup_status` 字段

**结果**：281 条重复（226 URL + 55 标题相似），占总量 3%。

### 19.3 标签修正（`examples/retag_historical.py`）

**方案**：5744 条被误标为宏观态势的文章，批量送 LLM 重新分类到 27 个标签（每批 30 条）。

**当前状态**：✅ 完成。宏观态势 5744 → 1756（-70%）。企业与机构 3877、量子计算 3593 跃居前两名，标签分布趋于健康。

### 19.4 报告提醒系统（`examples/scan_reports.py`）

**功能**：LLM 扫描新闻，识别其中提及的公开报告/白皮书/政策文件/路线图发布，生成提醒清单。

**集成**：每日 Pipeline 抓取→同步后自动运行，提醒持久化到 `data/report_alerts.json`。

**交互**：侧边栏新增「报告提醒」导航页，展示报告名称、发布机构、下载链接、价值说明。

### 19.5 跨语言检索优化

`retriever.py` 中 `enable_cross_en()` 改为**无条件双路**：每次查询同时搜 Pro + EN 两库，RRF 合并，不再设分数阈值。中文也能捞英文文档。

### 19.6 统一入库（`data_all/` + `build_all_kb.py`）

`lang_detect.py` 基于字符比例判断文档语言，`build_all_kb.py` 扫描 `data_all/` 自动路由到 Pro/EN 库。支持单文件同时入双库。旧 `data_lite/data_pro/data_en` 保留可用。

### 19.7 光子盒报告抓取（`examples/scrape_reports_photon.py`）

Playwright 无头浏览器抓取 `quantumchina.com/bg`，提取 10 份年度量子产业报告（2023–2026），含发布日期、下载链接。交互页面「报告提醒」分两个标签：新闻中发现的报告 + 光子盒报告库。
	
## 20. 机构新闻抓取系统（`institution_news/`）

### 20.1 系统概览

新建独立项目 `D:/Claude_code/institution_news/`，从 IBM、Quantinuum、Google、Microsoft、NVIDIA 五家第一梯队量子机构官网直接抓取新闻/博客。

最终成果：**166 篇**文章入库，日期覆盖率 95%+。

| 机构 | 文章数 | 日期覆盖 | 抓取方式 |
|------|--------|----------|----------|
| Microsoft Azure Quantum | 58 | 100% | 博客列表 + 自动翻页 |
| Quantinuum | 40 | 100% | 博客列表 + 5页分页 |
| Google Quantum AI | 36 | 100% | sitemap.xml |
| IBM Quantum | 17 | 88%* | 博客列表 |
| NVIDIA Quantum | 15 | 100% | 博客列表 |

*IBM 缺失的 2 篇为季度总结页面，原文无日期。

### 20.2 日期提取演进

**问题**：首次抓取 55 篇，仅 Google 1 篇有日期。IBM 博客页面日期存在于纯文本 `16 Mar 2026` 格式，原代码只查 `<meta>` 和 `<time>` 标签。

**方案**：`fetch_detail()` 新增四层回退：
1. `<meta property="article:published_time">` 等
2. `<time datetime="...">` 标签
3. `<script type="application/ld+json">` JSON-LD 结构化数据
4. 正文正则：`DD Mon YYYY` / `Month DD, YYYY` / `YYYY-MM-DD`

`crawl_listing()` 列表页同步升级日期提取正则。

**结果**：新增 `backfill_dates.py` 对存量 39 篇无日期文章批量补采，17 篇成功获取日期（其余为产品/导航页，已清理）。

### 20.3 翻页支持

**问题**：Quantinuum 博客有 5 页，但首次只抓了第一页 10 篇（实际应有 40+）；Microsoft 博客也受影响。

**根因**：`crawl_listing()` 无翻页逻辑。

**方案**：
- 新增 `_find_next_page()`：优先匹配 `_page=N` 格式的分页链接（Quantinuum 的 `?f06a1293_page=2`），次选 `<link rel="next">`
- 页间去重：`seen_urls` 集合跨页查重
- `max_pages` 配置限制最大翻页数（默认 5）

**踩坑**：早期版本用 `'next' in text` 做关键词匹配，结果 `<a>` 文本 "GuppyProgram the **next** generation..." 被误识别为翻页链接。修复为优先检查 `href` 中是否含 `_page=\d+`。

### 20.4 Sitemap 模式（Google 专项）

**问题**：Google 博客无量子专属列表页，`blog.google/technology/research/?q=quantum` 搜索页只返回 3 篇量子相关。但 [sitemap](https://blog.google/en-us/sitemap.xml) 中 11296 个 URL，搜索 "quantum" 命中 37 个。

**方案**：新增 `crawl_sitemap()` 函数 + `type: 'sitemap'` 源类型。解析 XML sitemap，按 `url_pattern` 关键词过滤 URL，`<lastmod>` 直接作为发布日期。

**结果**：Google 1 → 36 篇（排除 1 个 topic hub 页）。

### 20.5 URL 过滤 Bug 修复

**问题**：Quantinuum 产品页（`/products-solutions/`）、About 页（`/company/about`）等导航链接被误抓。

**根因**：`crawl_listing()` 过滤逻辑有漏洞——`href.startswith('/')` 的链接不做 `url_pattern` 检查直接放行。

**修复**：先将 `href` 补全为绝对 URL，再统一检查 `url_pattern`。

### 20.6 quantum_native 标记

**问题**：Quantinuum 列表页标题为 "Read our blogpost"、"Hardware RoadmapExplore..." 等破碎文本，LLM 量子相关性过滤因标题太差而大量误拒。

**方案**：源配置新增 `quantum_native: True`，量子原生公司跳过 `filter_quantum_llm()`，所有文章直接入库。仅 Google（综合博客）保留过滤。

### 20.7 标题修正

**问题**：部分网站列表页标题质量差（如前所述 Quantinuum）。

**方案**：`fetch_detail()` 新增 `_extract_page_title()`，优先取 `og:title` → `<meta name="title">` → `<h1>` → `<title>`。`main()` 中比较列表标题与详情标题长度，用更长的那个。

### 20.8 UI 升级

交互页面机构新闻库改进：
- **细粒度标签**：`FINE_TAG_MAP` 18 类标签（量子计算/量子纠错/超导/离子阱/AI·ML/融资商业...），中英文关键词混合匹配，替代原有 5 大类单标签
- **标题可点击**：列表标题直接链接原文 URL
- **日期排序**：`ORDER BY publish_date DESC`，无日期置底
- **机构显示**：列表和详情弹窗均显示来源机构名

### 20.9 IBM button 翻页修复

**问题**：IBM 博客翻页用的 `<button data-page="2">`，不是 `<a>` 标签，`_find_next_page()` 无法提取 href。

**方案**：新增 `page_url_template` 配置项。IBM 设 `'?page={n}'`，`_find_next_page()` 检测到模板后直接拼接 URL 不走页面解析。

**结果**：IBM 17 → 81 篇（5 页 × 16 篇/页）。

### 20.10 NVIDIA Atom Feed 发现

**问题**：NVIDIA HTML 列表仅 15 篇，`/page/2/` 返回相同内容（JS 无限滚动）。

**发现**：NVIDIA 提供 Atom Feed（`/feed/`），含 47 篇全量文章，XML 结构干净（标题+链接+发布日期）。

**方案**：新增 `crawl_atom()` 函数 + `type: 'atom'` 源类型。解析 Atom `<entry>` 标签。

**结果**：NVIDIA 15 → 45 篇。

### 20.11 内容质量与双语化

**正文提取改进**：新增 `_extract_body()`，按 `<article>` → `[role=main]` → `[class*=article-body]` 优先级找正文容器，找不到则清理全页文本。NVIDIA 正文平均 4333 字符（旧方法 3000 上限）。

**中文摘要**：DB 新增 `summary_cn` 字段。新文章入库时 LLM 实时生成一句话中文摘要（≤100 字）。存量文章 `backfill_cn.py` 批量补全。

**UI 双语展示**：详情弹窗显示「中文摘要」置顶，原文折叠在 `expander` 中。列表页标签已支持英文标题匹配。

### 20.12 智能探测模块（`auto_detect.py`）

**目标**：输入 URL → 自动返回最佳抓取策略，无需人工分析页面结构。

**探测决策树**（优先级递减）：
1. **Atom/RSS Feed** — 解析页面 `<link rel="alternate">` + 尝试 `/feed/` `/rss/` 等常见路径。要求 ≥10 entry 且量子标题占比 >15%。置信度 0.75-0.90
2. **Sitemap** — 读取 `robots.txt` → 回退 `/sitemap.xml`。检查文章 URL 占比，拒绝全站噪声 sitemap（>200 quantum URLs 且 article_ratio <0.3）。置信度 0.70-0.95
3. **HTML 列表页** — 聚类 URL 发现 `url_pattern`、识别翻页方式（`<a>` 链接 / `<button>` 模板 / 无翻页）、评估日期覆盖率和量子原生性。置信度 0.50-0.85

**关键子功能**：
- `detect_sitemap()`：robots.txt → sitemap.xml → sitemap_index.xml
- `detect_feed()`：`<link rel>` 标签 + 常见路径探测
- `detect_article_pattern()`：URL 聚类发现文章路径前缀，以 base URL 路径为主要提示
- `detect_pagination()`：`_page=N`（Quantinuum）、`?page=N`（IBM）、`data-page` button 三种模式
- `_sitemap_article_ratio()`：处理 sitemap 索引（嵌套子 sitemap）的文章占比计算

**验证结果**（5 家已知 + 1 家新机构）：

| 机构 | 探测模式 | 置信度 | 关键发现 |
|------|----------|--------|----------|
| IBM Quantum | enterprise + template | 70% | pattern=`/quantum/blog`, button翻页自动发现 |
| Quantinuum | enterprise + auto | 70% | pattern=`/news/blog`, `_page=N` 翻页 |
| Google Quantum AI | sitemap | 95% | 55 quantum URLs in blog sitemap |
| Microsoft Azure | atom | 75% | Feed 10 entries, 9/10 quantum |
| NVIDIA Quantum | atom | 90% | Feed 47 entries, 42/47 quantum |
| **IonQ** (新) | sitemap | 70% | 253 quantum URLs |

**使用方式**：`python auto_detect.py "机构名" "URL"` → 打印推荐配置 + 置信度 + 探测详情。

### 20.13 UI 交互优化

- **公司筛选**：机构新闻库增加下拉栏，可选全部/IBM/Quantinuum/Google/Microsoft/NVIDIA，联动列表和导出
- **日报区域收敛**：日报生成及勾选框仅在「量科每日库」显示，历史库和机构库自动隐藏
- **导出位置重排**：导出功能从页面底部移至新闻列表上方，用 `st.expander` 折叠，无需滚到底
