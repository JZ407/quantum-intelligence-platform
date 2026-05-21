# RAG 知识库使用手册

## 快速开始（5 分钟上手）

```bash
cd /d/Claude_code/rag_system

# 1. 把文档放进 data/
cp "你的文档.pdf" data/

# 2. 构建索引
python examples/build_kb.py

# 3. 问答
python examples/query_kb.py
```

---

## 目录结构

```
rag_system/
├── data/              ← 放入你的原始文档
├── index/             ← 自动生成的索引（可手动删除重建）
├── config.yaml        ← 配置文件（API Key、模型参数等）
├── examples/
│   ├── build_kb.py    ← 构建知识库
│   └── query_kb.py    ← 查询/问答
└── rag_system/        ← 核心源码（一般不用改）
```

---

## 第一步：准备文档

把任意支持的文件复制到 `data/` 目录：

| 格式 | 说明 |
|------|------|
| `.txt` `.md` `.csv` `.json` | 纯文本，直接读取 |
| `.pdf` | 需 `pypdf`，已安装 |
| `.pptx` | 用标准库解析，无需额外依赖 |
| `.docx` | 用标准库解析，无需额外依赖 |

**支持子目录**：`build_kb.py` 会递归扫描 `data/` 下的所有子文件夹。

---

## 第二步：配置 API

编辑 `config.yaml`：

```yaml
llm:
  provider: "openai"     # 保持 openai（Kimi 兼容此格式）
  model: "kimi-k2.6"
  api_key: "sk-你的密钥"
  api_base: "https://api.moonshot.cn/v1"
  temperature: null      # kimi-k2.6 不支持自定义 temperature，留 null
```

**多厂商切换参考**：

| 厂商 | provider | api_base | model 示例 |
|------|----------|----------|-----------|
| Kimi（月之暗面） | `openai` | `https://api.moonshot.cn/v1` | `kimi-k2.6` |
| DeepSeek | `openai` | `https://api.deepseek.com/v1` | `deepseek-chat` |
| OpenAI | `openai` | `https://api.openai.com/v1` | `gpt-4o-mini` |
| Claude | `claude` | `https://api.anthropic.com/v1` | `claude-3-haiku-20240307` |

---

## 第三步：构建知识库

```bash
python examples/build_kb.py
```

输出示例：
```
[INFO] Ingesting documents from: ./data
  [OK] data\论文.pdf -> 12 chunks
  [OK] data\笔记.txt -> 3 chunks
[INFO] Total chunks ingested: 15
[INFO] Index saved to ./index\kb_index.json
```

**重建索引**：直接删除 `index/` 目录再重新运行即可。

---

## 第四步：查询与问答

```bash
python examples/query_kb.py
```

交互式输入问题，系统会显示两部分：
1. **Retrieved Context**：本地检索到的相关文档片段（带相似度分数）
2. **LLM Answer**：Kimi 基于上下文生成的回答

**仅检索（不调用 LLM）**：把 `config.yaml` 中 `llm.api_key` 注释掉或设为空即可。

---

## 高级配置

### 调整文本切分策略

编辑 `config.yaml`：

```yaml
kb:
  chunk_method: "recursive"   # recursive / fixed / paragraph
  chunk_size: 500             # 每块最大字符数
  chunk_overlap: 100          # 块之间重叠字符数（避免断句）
```

| 策略 | 适用场景 |
|------|----------|
| `recursive` | **推荐**，按段落→句子→单词逐级切分，保留语义完整性 |
| `fixed` | 长文本、代码，严格固定长度 |
| `paragraph` | 结构清晰的文档（如 Markdown），按空行分段 |

### 切换嵌入模型（可选）

默认使用 **BM25**（纯 Python，无需 API，关键词匹配）。

如需更强的语义理解能力，可切换到 **OpenAI Embedding**：

```yaml
embedding:
  provider: "openai"
  model: "text-embedding-3-small"
  api_key: "sk-你的密钥"      # 可与 llm 用不同 Key
  api_base: null
```

> 语义嵌入能理解同义词和近义表达，但需要消耗 embedding API 额度。

### 调整检索数量

```yaml
kb:
  top_k: 5        # 每次检索返回多少个片段

rag:
  max_context_length: 3000   # 传给 LLM 的最大上下文长度（字符）
```

### 自定义 Prompt

```yaml
llm:
  system_prompt: "你是一位严谨的学术助手，回答必须基于提供的文献。"

rag:
  context_template: |
    参考资料：
    {context}

    请回答：{question}
```

---

## 常见问题

### Q1: 调用 LLM 时报错 "invalid temperature"

Kimi `kimi-k2.6` 不支持自定义 temperature。在 `config.yaml` 中设为 `null`：

```yaml
llm:
  temperature: null
```

### Q2: 知识库检索不到相关内容

- 检查文档是否真的放入了 `data/`
- 尝试减小 `chunk_size`（如 300），让切分更细
- 英文文档可尝试 `fixed` 切分策略
- 检查是否重建了索引（修改配置后需重新运行 `build_kb.py`）

### Q3: 如何只检索不生成？

注释掉或清空 `llm.api_key`，`query_kb.py` 会自动跳过 LLM 调用，只展示检索结果。

### Q4: 索引文件很大怎么办？

索引是 JSON 格式，文本越多越大。如需优化，可考虑安装 `faiss-cpu` 或 `chromadb` 替代 JSON 存储（见 `TOOLS.md`）。

### Q5: 支持中文 PDF 吗？

支持，但 PDF 中的文字必须是可选中/复制的文本层。扫描版图片 PDF 无法提取文字（需 OCR 工具）。

---

## 下一步建议

1. **多放文档测试**：尝试 PDF、PPT、Word 混合构建，观察检索效果
2. **调整 chunk 参数**：根据文档类型找到最佳切分策略
3. **对比语义嵌入**：如果有 OpenAI Key，对比 BM25 和 API 嵌入的检索质量差异
