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

## 7. 待办 / 未来方向

- [ ] 用 `httpx` 替换 `urllib`（更稳定、支持异步）
- [ ] 接入 `jieba` 优化中文 BM25 分词（备用方案）
- [ ] 用 `rich` 美化 `query_kb.py` 的终端交互
- [ ] 支持网页抓取（beautifulsoup4）直接入知识库
- [ ] 评估 ChromaDB（虽然用户当前未选择，但可保留接口）
