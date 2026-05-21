# 快速开始（给新电脑）

> 拿到这份代码后，按以下步骤 10 分钟跑通。

## 1. 解压

把 `rag_system/` 文件夹复制到任意位置，例如：

```bash
cd /d/你的项目目录
```

## 2. 创建虚拟环境（强烈建议）

```bash
python -m venv venv
source venv/Scripts/activate   # Windows Git Bash
# 或 venv\Scripts\activate.bat # Windows CMD
```

## 3. 安装依赖

```bash
cd rag_system
pip install -r requirements.txt
```

## 4. 填入 API Key

复制 `config.yaml` 并重命名一份自己的（或者直接在 `config.yaml` 里改）：

```yaml
llm:
  provider: "openai"
  model: "kimi-k2.6"          # 或 deepseek-chat / gpt-4o-mini
  api_key: "sk-你的Key"        # ← 改成你自己的
  api_base: "https://api.moonshot.cn/v1"
  temperature: null
```

> **Kimi 用户注意**：国内 Key 用 `api.moonshot.cn`，温度必须设 `null`。

## 5. 放入你的文档

```bash
mkdir -p data
cp "你的文件.pdf" data/
cp "你的笔记.txt" data/
```

## 6. 构建索引

```bash
python examples/build_kb.py
```

第一次运行会自动下载 `all-MiniLM-L6-v2` 模型（约 100MB）。

## 7. 开始问答

```bash
python examples/query_kb.py
```

输入问题，回车，即可看到检索结果 + LLM 回答。

---

## 常见问题（新电脑版）

**Q: 没有 API Key 怎么办？**  
先注释掉 `llm.api_key`，`query_kb.py` 会只返回本地检索结果，不调用 LLM。

**Q: 提示模型下载失败？**  
设置 HuggingFace 镜像：
```bash
export HF_ENDPOINT=https://hf-mirror.com
```

**Q: 想先试试不装 sentence-transformers？**  
把 `config.yaml` 里 `embedding.provider` 改成 `bm25`，删除 `index/*` 后重建。
