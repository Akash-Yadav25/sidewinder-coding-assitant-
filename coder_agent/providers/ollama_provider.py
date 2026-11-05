"""Local LLM provider integration via Ollama or any OpenAI-compatible API."""

from __future__ import annotations

import os

from openai import OpenAI

from coder_agent.config import Config
from coder_agent.providers.azure_openai_provider import AzureOpenAIProvider


class OllamaProvider(AzureOpenAIProvider):
    """Local LLM provider using Ollama, LM Studio, vLLM, or LocalAI via OpenAI compatibility."""

    def __init__(self, config: Config):
        base_url = (
            config.ollama_base_url
            or os.environ.get("OLLAMA_BASE_URL")
            or "http://localhost:11434/v1"
        )
        api_key = os.environ.get("OLLAMA_API_KEY") or "ollama"

        self.client = OpenAI(
            base_url=base_url,
            api_key=api_key,
        )
        self.model = config.model or "qwen3"
        self.max_tokens = config.max_tokens

    @property
    def name(self) -> str:
        return f"ollama/local ({self.model})"
