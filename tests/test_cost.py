"""Unit tests for model pricing and cost calculation."""

from __future__ import annotations

from coder_agent.providers.cost import calculate_cost, format_cost
from coder_agent.types import TokenUsage


def test_calculate_cost_anthropic_sonnet():
    # 1,000,000 input tokens = $3.00, 1,000,000 output tokens = $15.00
    usage = TokenUsage(input_tokens=1_000_000, output_tokens=1_000_000)
    cost = calculate_cost("anthropic", "claude-sonnet-4-20250514", usage)
    assert abs(cost - 18.0) < 0.001


def test_calculate_cost_gpt_4o():
    # 100,000 in = $0.25, 10,000 out = $0.10 -> $0.35
    usage = TokenUsage(input_tokens=100_000, output_tokens=10_000)
    cost = calculate_cost("azure", "gpt-4o", usage)
    assert abs(cost - 0.35) < 0.001


def test_calculate_cost_ollama_free():
    usage = TokenUsage(input_tokens=500_000, output_tokens=50_000)
    cost = calculate_cost("ollama", "qwen3", usage)
    assert cost == 0.0


def test_format_cost():
    assert format_cost(0.0) == "$0.00"
    assert format_cost(0.0045) == "$0.0045"
    assert format_cost(1.50) == "$1.50"
