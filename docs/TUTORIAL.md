# 部署教程：Claude Code + Kimi-k2.6 + 本地 RAG 知识库

> 面向开发者的完整复现指南。环境：Windows 11 + Python 3.14 + Git Bash。

---

## 目录

1. [环境准备](#1-环境准备)
2. [安装 Claude Code](#2-安装-claude-code)
3. [配置 Kimi API](#3-配置-kimi-api)
4. [部署本地知识库](#4-部署本地知识库)
5. [构建索引与问答](#5-构建索引与问答)
6. [升级到语义嵌入](#6-升级到语义嵌入可选但推荐)
7. [常见问题排查](#7-常见问题排查)

---

## 1. 环境准备

### 1.1 必需软件

| 软件 | 版本要求 | 用途 |
|------|----------|------|
| Python | 3.10+（本文用 3.14） | 运行知识库 |
| Git Bash | 最新 | Windows 下的 Unix-like 终端 |
| Claude Code | 最新 | AI 助手交互 |

### 1.2 验证 Python

```bash
python --version
# 输出：Python 3.14.x
```

### 1.3 创建工作目录

```bash
mkdir -p /d/Claude_code/rag_system
cd /d/Claude_code/rag_system
```

---

## 2. 安装 Claude Code

Claude Code 是 Anthropic 的官方 CLI 工具，通过它你可以用自然语言指挥 AI 写代码、操作文件、运行命令。

```bash
# 安装（需 Node.js 18+）
npm install -g @anthropic-ai/claude-code

# 首次运行，按提示登录 Anthropic 账号
claude
```

> 安装完成后，在 `D:\Claude_code` 目录下运行 `claude`，即可进入交互式会话。

---

## 3. 配置 Kimi API

### 3.1 获取 API Key

1. 访问 [platform.moonshot.cn](https://platform.moonshot.cn)
2. 注册/登录账号
3. 进入「API Key 管理」创建新 Key

> **重要**：国内用户请确认 Key 绑定在 `moonshot.cn`（不是 `.ai`）。

### 3.2 写入配置文件

创建 `config.yaml`：

```yaml
llm:
  provider: "openai"          # Kimi 使用 OpenAI 兼容格式
  model: "kimi-k2.6"
  api_key: "sk-你的Key"
  api_base: "https://api.moonshot.cn/v1"
  temperature: null           # kimi-k2.6 不支持自定义 temperature
  max_tokens: 2048
  system_prompt: "你是一个专业的文档问答助手。请基于提供的参考资料回答用户问题。"

embedding:
  provider: "bm25"            # 第一阶段先用 BM25（零依赖）

kb:
  data_dir: "./data"
  index_dir: "./index"
  chunk_method: "recursive"
  chunk_size: 500
  chunk_overlap: 100
  top_k: 5
```

### 3.3 验证 API 连通性

```bash
python -c "
from rag_system.llm_client import LLMClient
client = LLMClient(
    provider='openai', model='kimi-k2.6',
    api_key='sk-你的Key', api_base='https://api.moonshot.cn/v1',
    temperature=None, max_tokens=100
)
print(client.simple_chat('你好'))
"
```

---

## 4. 部署本地知识库

### 4.1 获取源码

把以下核心文件放入 `rag_system/` 目录：

```
rag_system/
├── rag_system/
│   ├── __init__.py
│   ├── kb_manager.py
│   ├── pipeline.py
│   ├── llm_client.py
│   ├── retriever.py
│   ├── embedder.py
│   ├── vector_store.py
│   ├── chunker.py
│   ├── loader.py
│   └── config.py
├── examples/
│   ├── build_kb.py
│   └── query_kb.py
├── data/          ← 你的文档放这里
├── index/         ← 自动生成的索引
└── config.yaml
```

> 完整源码可参考本项目的 `rag_system/` 目录。

### 4.2 安装最小依赖

```bash
pip install pypdf pyyaml
```

---

## 5. 构建索引与问答

### 5.1 放入文档

```bash
mkdir -p data
cp "你的论文.pdf" data/
cp "你的笔记.txt" data/
```

### 5.2 构建索引

```bash
python examples/build_kb.py
```

预期输出：
```
[INFO] Ingesting documents from: ./data
  [OK] data\论文.pdf -> 12 chunks
  [OK] data\笔记.txt -> 3 chunks
[INFO] Total chunks ingested: 15
[INFO] Index saved to ./index\kb_index.json
```

### 5.3 问答

```bash
python examples/query_kb.py
```

输入问题后，你会看到：
1. **Retrieved Context** — 本地检索到的相关片段
2. **LLM Answer** — Kimi 基于上下文生成的回答

---

## 6. 升级到语义嵌入（可选但推荐）

BM25 基于关键词匹配，对同义词和语义近似的召回能力有限。推荐升级到 `sentence-transformers` + `FAISS`。

### 6.1 安装依赖

```bash
pip install sentence-transformers faiss-cpu
```

> Python 3.14 上安装可能需要 3-5 分钟（编译 C++ 扩展），请耐心等待。

### 6.2 修改配置

```yaml
embedding:
  provider: "local"
  model: "all-MiniLM-L6-v2"    # 轻量双语模型，384 维
```

### 6.3 重建索引

```bash
# 删除旧索引
rm -rf index/*

# 重新构建
python examples/build_kb.py
```

预期输出：
```
[INFO] Stats: {'total_chunks': 15, 'embedder': 'SentenceTransformerEmbedder', 'provider': 'local'}
[INFO] Index saved to ./index\kb_index
```

注意：FAISS 索引会生成两个文件 `kb_index.faiss` + `kb_index.docs`。

### 6.4 效果对比

| 指标 | BM25 | 语义嵌入 + FAISS |
|------|------|-----------------|
| 相似度分数 | ~0.42 | ~0.54 |
| 同义词召回 | 弱 | 强 |
| 索引体积 | 单个 JSON | .faiss + .docs |
| 检索速度 | O(n) 线性扫描 | O(log n) 近似检索 |

---

## 7. 常见问题排查

### Q1: 调用 Kimi 报错 "invalid temperature"

**原因**：kimi-k2.6 不支持自定义 temperature。  
**解决**：`config.yaml` 中写 `temperature: null`。

### Q2: 调用 Kimi 报错 "401 Unauthorized"

**原因**：Key 绑定在 `moonshot.cn`，但用了 `moonshot.ai`。  
**解决**：确认 Key 来源，国内用户统一用 `https://api.moonshot.cn/v1`。

### Q3: 调用 Kimi 报错 "429 Too Many Requests"

**原因**：请求过于频繁触发限流。  
**解决**：等待 10-30 秒后重试，或降低并发。

### Q4: Python 3.14 安装 torch 失败

**实际情况**：经测试 `sentence-transformers` + `faiss-cpu` 可在 Python 3.14 上成功编译安装。  
**若失败**：继续使用 BM25 方案，或改用 OpenAI Embedding API。

### Q5: 检索不到相关内容

- 确认文档已放入 `data/`
- 尝试减小 `chunk_size`（如 300）
- 重建索引：`rm -rf index/* && python examples/build_kb.py`

### Q6: 扫描版 PDF（图片）无法提取文字

当前 loader 只支持文本层 PDF。扫描版需先用 OCR 工具（如 PaddleOCR、Adobe Acrobat）转为可搜索 PDF。

---

## 附录：多厂商 LLM 切换表

| 厂商 | provider | api_base | model 示例 |
|------|----------|----------|-----------|
| Kimi（月之暗面） | `openai` | `https://api.moonshot.cn/v1` | `kimi-k2.6` |
| DeepSeek | `openai` | `https://api.deepseek.com/v1` | `deepseek-chat` |
| OpenAI | `openai` | `https://api.openai.com/v1` | `gpt-4o-mini` |
| Claude | `claude` | `https://api.anthropic.com/v1` | `claude-3-haiku-20240307` |
| Azure | `azure` | `你的 Azure Endpoint` | `gpt-4o` |

---

## 下一步推荐阅读

- `docs/USER_GUIDE.md` — 日常使用手册
- `docs/TOOLS.md` — 可选增强工具清单
- `DEPLOYMENT_LOG.md` — 本项目的完整决策链与踩坑记录
