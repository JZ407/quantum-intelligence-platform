"""Unified LLM client supporting multiple providers."""

import json
import urllib.request
from typing import List, Dict, Any, Optional, Generator


class LLMClient:
    """Chat completion client for OpenAI-compatible / Claude / DeepSeek APIs."""

    PROVIDER_CONFIGS = {
        "openai": {
            "api_base": "https://api.openai.com/v1",
            "default_model": "gpt-4o-mini",
        },
        "claude": {
            "api_base": "https://api.anthropic.com/v1",
            "default_model": "claude-3-haiku-20240307",
        },
        "deepseek": {
            "api_base": "https://api.deepseek.com/v1",
            "default_model": "deepseek-chat",
        },
        "azure": {
            "api_base": None,  # must be provided
            "default_model": None,
        },
    }

    def __init__(self, provider: str = "openai", api_key: Optional[str] = None,
                 api_base: Optional[str] = None, model: Optional[str] = None,
                 temperature: float = 0.7, max_tokens: int = 2048,
                 timeout: int = 120):
        self.provider = provider.lower()
        self.api_key = api_key or ""
        cfg = self.PROVIDER_CONFIGS.get(self.provider, self.PROVIDER_CONFIGS["openai"])
        self.api_base = api_base or cfg["api_base"] or ""
        self.model = model or cfg["default_model"] or "gpt-4o-mini"
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout

    def chat(self, messages: List[Dict[str, str]], stream: bool = False,
             max_tokens: int = None) -> str:
        """Send chat completion request. Returns full response text."""
        if self.provider == "claude":
            return self._chat_claude(messages, stream, max_tokens)
        return self._chat_openai_compatible(messages, stream, max_tokens)

    def _chat_openai_compatible(self, messages: List[Dict[str, str]], stream: bool,
                                 max_tokens: int = None) -> str:
        url = f"{self.api_base}/chat/completions"
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens or self.max_tokens,
            "stream": stream,
        }
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")

        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            body = resp.read().decode('utf-8')
            result = json.loads(body)
            return result["choices"][0]["message"]["content"]

    def _chat_claude(self, messages: List[Dict[str, str]], stream: bool,
                      max_tokens: int = None) -> str:
        url = f"{self.api_base}/messages"
        # Claude API format
        system_msg = ""
        claude_messages = []
        for m in messages:
            if m["role"] == "system":
                system_msg = m["content"]
            else:
                claude_messages.append({"role": m["role"], "content": m["content"]})

        payload: Dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": claude_messages,
        }
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        if system_msg:
            payload["system"] = system_msg

        headers = {
            "x-api-key": self.api_key,
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        }
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")

        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            body = resp.read().decode('utf-8')
            result = json.loads(body)
            return result["content"][0]["text"]

    def simple_chat(self, user_message: str, system_prompt: Optional[str] = None) -> str:
        """One-shot chat."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_message})
        return self.chat(messages)
