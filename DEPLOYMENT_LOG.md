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

---

## 9. 待办 / 未来方向

- [x] 接入 Reranker 精排模型（bge-reranker-base）
- [x] 实现增量更新（--incremental）
- [x] 多配置文件切换（Lite/Pro/EN）
- [ ] 用 `httpx` 替换 `urllib`（更稳定、支持异步）
- [ ] 接入 `jieba` 优化中文 BM25 分词（备用方案）
- [ ] 用 `rich` 美化 `query_kb.py` 的终端交互
- [ ] 支持网页抓取（beautifulsoup4）直接入知识库
- [ ] 评估 ChromaDB（虽然用户当前未选择，但可保留接口）
- [x] 量科网每日数据桥接（MySQL → RAG 增量入库）
- [x] txt + metadata 分离（标签/日期变更无需重新编码向量）
- [x] 稳定 chunk_id（避免依赖 FAISS 顺序索引）
