"""Provider factory and registry for Coder Agent."""

from __future__ import annotations

from typing import TYPE_CHECKING

from coder_agent.providers.base import LLMProvider

if TYPE_CHECKING:
    from coder_agent.config import Config


def create_provider(config: Config) -> LLMProvider:
    """Instantiate and return the configured LLM provider."""
    provider_name = config.provider.lower().strip()

    if provider_name == "anthropic":
        from coder_agent.providers.anthropic_provider import AnthropicProvider

        return AnthropicProvider(config)

    elif provider_name == "bedrock":
        from coder_agent.providers.bedrock_provider import BedrockProvider

        return BedrockProvider(config)

    elif provider_name in ("azure", "azure_openai", "azure-openai"):
        from coder_agent.providers.azure_openai_provider import AzureOpenAIProvider

        return AzureOpenAIProvider(config)

    elif provider_name in ("ollama", "local", "openai_compatible"):
        from coder_agent.providers.ollama_provider import OllamaProvider

        return OllamaProvider(config)

    else:
        valid_options = ["anthropic", "bedrock", "azure", "ollama"]
        raise ValueError(
            f"Unsupported provider '{config.provider}'. Available options: {', '.join(valid_options)}"
        )
