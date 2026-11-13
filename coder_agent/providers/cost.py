"""Model pricing tables and token cost tracking."""

from __future__ import annotations

from coder_agent.types import TokenUsage

# Pricing per 1,000,000 tokens (USD)
# (input_price_per_m, output_price_per_m)
MODEL_PRICING: dict[str, tuple[float, float]] = {
    # Anthropic
    "claude-sonnet-4": (3.00, 15.00),
    "claude-sonnet-4-20250514": (3.00, 15.00),
    "claude-3-5-sonnet-20241022": (3.00, 15.00),
    "claude-3-5-sonnet-20240620": (3.00, 15.00),
    "claude-3-5-haiku-20241022": (0.80, 4.00),
    "claude-opus-4": (15.00, 75.00),
    "claude-3-opus-20240229": (15.00, 75.00),
    # OpenAI / Azure
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-2024-08-06": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4-turbo": (10.00, 30.00),
    # Local
    "ollama": (0.00, 0.00),
}


def calculate_cost(provider: str, model: str, usage: TokenUsage) -> float:
    """Calculate the estimated USD cost based on token usage and model pricing."""
    if provider.lower() == "ollama":
        return 0.0

    # Look up by exact model match or substring
    model_lower = model.lower()
    rates: tuple[float, float] | None = None

    for key, price_pair in MODEL_PRICING.items():
        if key in model_lower:
            rates = price_pair
            break

    if rates is None:
        # Default reasonable estimate (Sonnet-class: $3 / $15)
        rates = (3.00, 15.00)

    input_cost = (usage.input_tokens / 1_000_000.0) * rates[0]
    output_cost = (usage.output_tokens / 1_000_000.0) * rates[1]
    return input_cost + output_cost


def format_cost(cost: float) -> str:
    """Format USD cost nicely."""
    if cost == 0.0:
        return "$0.00"
    if cost < 0.01:
        return f"${cost:.4f}"
    return f"${cost:.2f}"
