# Local RAG Knowledge Base + Online LLM

A lightweight, local-first Retrieval-Augmented Generation system.

## Architecture

```
Documents -> Load -> Chunk -> Embed (BM25 or API) -> Store (Local JSON)
                                                          |
User Question -> Retrieve (Local) -> Build Prompt -> LLM API -> Answer
```

## Features

- **Zero heavy ML dependencies**: Works with Python standard library + `pypdf`
- **Local storage**: All indices saved as JSON, fully portable
- **Multiple formats**: `.txt`, `.md`, `.pdf`, `.pptx`, `.docx`
- **Smart chunking**: Recursive character text splitter
- **Hybrid embedders**:
  - `bm25` (default): pure-Python, no API needed
  - `openai`: high-quality semantic vectors via API
- **Multi-provider LLM**: OpenAI, Claude, DeepSeek, Azure
- **Config-driven**: All settings in `config.yaml`

## Quick Start

### 1. Prepare Documents

```bash
mkdir data
cp your_docs/* data/
```

### 2. Configure API Keys (Optional)

Edit `config.yaml`:

```yaml
llm:
  provider: "deepseek"
  model: "deepseek-chat"
  api_key: "sk-..."

# Optional: use OpenAI embedding instead of BM25
embedding:
  provider: "openai"
  api_key: "sk-..."
```

Or set environment variables:
```bash
export OPENAI_API_KEY="sk-..."
export DEEPSEEK_API_KEY="sk-..."
export ANTHROPIC_API_KEY="sk-..."
```

### 3. Build Knowledge Base

```bash
cd /d/Claude_code/rag_system
python examples/build_kb.py
```

### 4. Query

```bash
python examples/query_kb.py
```

## Project Structure

```
rag_system/
├── rag_system/
│   ├── kb_manager.py      # Main knowledge base manager
│   ├── pipeline.py        # RAG pipeline
│   ├── llm_client.py      # Multi-provider LLM client
│   ├── retriever.py       # Hybrid retriever
│   ├── embedder.py        # BM25 / OpenAI embedders
│   ├── vector_store.py    # Local JSON vector store
│   ├── chunker.py         # Recursive text splitter
│   ├── loader.py          # Multi-format document loader
│   └── config.py          # Config management
├── data/                  # Your documents
├── index/                 # Generated indices
├── examples/
│   ├── build_kb.py
│   └── query_kb.py
├── config.yaml
└── README.md
```

## API Key Setup

| Provider | Variable Name | Default Base URL |
|----------|--------------|------------------|
| OpenAI | `OPENAI_API_KEY` | `https://api.openai.com/v1` |
| Claude | `ANTHROPIC_API_KEY` | `https://api.anthropic.com/v1` |
| DeepSeek | `DEEPSEEK_API_KEY` | `https://api.deepseek.com/v1` |
| Azure | - | Provide full endpoint in `api_base` |

## Using Without Any API Key

If you don't have an LLM API key yet, you can still:

1. Build the knowledge base with `build_kb.py`
2. Run `query_kb.py` in "retrieval-only" mode
3. Copy the retrieved context manually into any online chatbot

The local BM25 embedder requires **zero API calls**.
