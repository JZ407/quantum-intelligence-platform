"""Configuration management for RAG system."""

import os
import yaml
from typing import Dict, Any, Optional
from pathlib import Path


DEFAULT_CONFIG = {
    "kb": {
        "data_dir": "./data",
        "index_dir": "./index",
        "chunk_method": "recursive",  # recursive / fixed / paragraph
        "chunk_size": 500,
        "chunk_overlap": 100,
        "top_k": 5,
        "bm25_k1": 1.5,
        "bm25_b": 0.75,
    },
    "embedding": {
        "provider": "bm25",  # bm25 / openai / local
        "model": "text-embedding-3-small",  # for openai
        "api_key": None,
        "api_base": None,
        "local_model_path": None,
    },
    "llm": {
        "provider": "openai",  # openai / claude / deepseek / azure
        "model": "gpt-4o-mini",
        "api_key": None,
        "api_base": None,
        "temperature": 0.7,
        "max_tokens": 2048,
        "system_prompt": "你是一个专业的文档问答助手。请基于提供的参考资料回答用户问题。如果资料中没有相关信息，请明确说明。",
    },
    "rag": {
        "max_context_length": 3000,
        "context_template": "参考资料：\n{context}\n\n用户问题：{question}",
    },
}


class Config:
    """Simple config wrapper."""

    def __init__(self, config_dict: Optional[Dict[str, Any]] = None):
        self._cfg = config_dict or DEFAULT_CONFIG.copy()

    def get(self, key_path: str, default: Any = None) -> Any:
        """Get config value by dot-separated path, e.g. 'llm.model'."""
        keys = key_path.split(".")
        val = self._cfg
        for k in keys:
            if isinstance(val, dict) and k in val:
                val = val[k]
            else:
                return default
        return val

    def set(self, key_path: str, value: Any) -> None:
        """Set config value by dot-separated path."""
        keys = key_path.split(".")
        cfg = self._cfg
        for k in keys[:-1]:
            if k not in cfg:
                cfg[k] = {}
            cfg = cfg[k]
        cfg[keys[-1]] = value

    def to_dict(self) -> Dict[str, Any]:
        return dict(self._cfg)

    @classmethod
    def from_yaml(cls, path: str) -> "Config":
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        # Merge with defaults
        merged = _deep_merge(DEFAULT_CONFIG.copy(), data or {})
        return cls(merged)

    @classmethod
    def from_env(cls) -> "Config":
        """Load config from environment variables."""
        cfg = cls()
        # LLM API key
        if os.environ.get("OPENAI_API_KEY"):
            cfg.set("llm.provider", "openai")
            cfg.set("llm.api_key", os.environ["OPENAI_API_KEY"])
        if os.environ.get("ANTHROPIC_API_KEY"):
            cfg.set("llm.provider", "claude")
            cfg.set("llm.api_key", os.environ["ANTHROPIC_API_KEY"])
        if os.environ.get("DEEPSEEK_API_KEY"):
            cfg.set("llm.provider", "deepseek")
            cfg.set("llm.api_key", os.environ["DEEPSEEK_API_KEY"])
        return cfg


def _deep_merge(base: Dict, override: Dict) -> Dict:
    """Deep merge two dicts."""
    for k, v in override.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            base[k] = _deep_merge(base[k], v)
        else:
            base[k] = v
    return base
