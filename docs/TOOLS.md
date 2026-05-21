# 推荐工具与扩展

当前系统使用纯 Python 标准库 + `pypdf` 实现，零重型依赖。以下是按优先级排序的增强工具推荐，你可以根据需求选择安装。

---

## 高优先级（显著提升体验）

### 1. PyYAML
**用途**：解析 `config.yaml` 配置文件  
**状态**：已安装 ✅  
**安装**：`pip install pyyaml`

### 2. HTTPX / Requests
**用途**：替换标准库 `urllib`，提供更现代的 HTTP 客户端，支持连接池、重试、超时精细化控制  
**推荐度**：⭐⭐⭐⭐⭐  
**安装**：`pip install httpx`  
**收益**：API 调用更稳定，错误处理更友好，后续加异步也容易

### 3. ChromaDB
**用途**：专业向量数据库，替代当前 JSON 文件存储  
**推荐度**：⭐⭐⭐⭐  
**安装**：`pip install chromadb`  
**收益**：
- 支持百万级向量的高效检索
- 内置元数据过滤（如只检索某份文档）
- 持久化更可靠，支持增量更新

### 4. Sentence-Transformers + Torch
**用途**：本地语义嵌入模型（如 `all-MiniLM-L6-v2`）  
**推荐度**：⭐⭐⭐⭐  
**安装**：`pip install sentence-transformers`  
**收益**：
- 无需 API 费用，完全本地运行
- 理解语义相似性（同义词、近义句）
- 首次下载模型约 100MB，之后离线使用
**注意**：Torch 在 Windows + Python 3.14 上可能暂无预编译 wheel，安装时间较长或失败

---

## 中优先级（特定场景有用）

### 5. FAISS-CPU
**用途**：Facebook 的近似最近邻搜索库  
**推荐度**：⭐⭐⭐  
**安装**：`pip install faiss-cpu`  
**收益**：比纯 Python 向量检索快 10~100 倍，适合万级以上文档  
**注意**：Windows 上安装可能需 Visual C++ 运行时

### 6. BeautifulSoup4 + lxml
**用途**：网页抓取与解析  
**推荐度**：⭐⭐⭐  
**安装**：`pip install beautifulsoup4 lxml`  
**收益**：可以抓取网页直接进知识库，无需手动复制粘贴

### 7. python-docx + python-pptx
**用途**：更完善的 Word/PPT 解析  
**推荐度**：⭐⭐  
**安装**：`pip install python-docx python-pptx`  
**收益**：
- 保留表格、列表层级等结构信息
- 提取备注/批注
- 当前标准库方案已够用，这属于锦上添花

### 8. Jieba
**用途**：中文分词  
**推荐度**：⭐⭐  
**安装**：`pip install jieba`  
**收益**：BM25 的关键词切分更精准（如"量子计算"不会切成"量/子/计/算"）  
**注意**：需修改 `embedder.py` 的 `_tokenize` 函数接入 jieba

---

## 低优先级（开发体验优化）

### 9. Rich
**用途**：终端美化输出  
**推荐度**：⭐⭐  
**安装**：`pip install rich`  
**收益**：Markdown 渲染、进度条、彩色表格，让 `query_kb.py` 的交互更美观

### 10. Typer / Click
**用途**：构建命令行界面  
**推荐度**：⭐⭐  
**安装**：`pip install typer`  
**收益**：把 `build_kb.py` 和 `query_kb.py` 合并成一个带子命令的 CLI 工具

### 11. Watchdog
**用途**：监控文件变更  
**推荐度**：⭐  
**安装**：`pip install watchdog`  
**收益**：`data/` 目录有新文件时自动重建索引

---

## 安装建议组合

根据你的场景选择：

### 组合 A：API 党（推荐当前方案）
只增强稳定性和体验：
```bash
pip install httpx rich
```

### 组合 B：语义升级党
加入本地语义嵌入 + 专业向量库：
```bash
pip install httpx chromadb sentence-transformers
```

### 组合 C：全都要党
```bash
pip install httpx chromadb sentence-transformers faiss-cpu beautifulsoup4 lxml python-docx python-pptx jieba rich typer watchdog
```

---

## Python 3.14 兼容性提示

由于你使用的是 **Python 3.14**（非常新的版本），以下包可能存在安装问题：

| 包 | 兼容性 | 备注 |
|----|--------|------|
| `torch` | ⚠️ 可能失败 | 官方 wheel 通常滞后 1~2 个 Python 版本 |
| `faiss-cpu` | ⚠️ 可能失败 | 需编译 C++ 扩展 |
| `chromadb` | ✅ 大概率成功 | 纯 Python 依赖多，但通常可装 |
| `httpx` | ✅ 成功 | 纯 Python |
| `sentence-transformers` | ⚠️ 依赖 torch | torch 失败则整体失败 |

**如果 torch 装不上**，语义嵌入的替代方案：
1. 继续使用 OpenAI Embedding API（无需本地模型）
2. 使用 ONNX 格式的轻量模型（如 `optimum[onnxruntime]`）

需要我现在帮你测试其中哪些包能在你的 Python 3.14 上成功安装吗？
