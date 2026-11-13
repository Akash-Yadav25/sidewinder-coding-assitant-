"""Secret detection and redaction scanner to prevent credential exfiltration."""

from __future__ import annotations

import re

SECRET_PATTERNS = [
    # Private Keys
    (
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
        "[REDACTED_PRIVATE_KEY]",
    ),
    # Anthropic API Keys
    (
        re.compile(r"sk-ant-[a-zA-Z0-9_\-]{20,}"),
        "[REDACTED_ANTHROPIC_KEY]",
    ),
    # OpenAI API Keys
    (
        re.compile(r"sk-(?:proj-)?[a-zA-Z0-9_\-]{30,}"),
        "[REDACTED_OPENAI_KEY]",
    ),
    # AWS Access Key IDs
    (
        re.compile(r"(?:AKIA|ASIA)[0-9A-Z]{16}"),
        "[REDACTED_AWS_KEY_ID]",
    ),
    # GitHub Tokens
    (
        re.compile(r"gh[pousr]_[A-Za-z0-9_]{36,}"),
        "[REDACTED_GITHUB_TOKEN]",
    ),
    # Slack Tokens
    (
        re.compile(r"xox[baprs]-[0-9A-Za-z\-]{20,}"),
        "[REDACTED_SLACK_TOKEN]",
    ),
    # Database URIs with passwords
    (
        re.compile(r"(postgres(?:ql)?|mysql|mongodb)://[^:]+:([^@]+)@"),
        lambda m: m.group(0).replace(m.group(2), "********"),
    ),
]


def redact_secrets(text: str) -> str:
    """Scan and redact known secrets, credentials, and private keys from text."""
    if not text:
        return text

    redacted = text
    for pattern, repl in SECRET_PATTERNS:
        if callable(repl):
            redacted = pattern.sub(repl, redacted)
        else:
            redacted = pattern.sub(repl, redacted)

    return redacted


def contains_secrets(text: str) -> bool:
    """Return True if text contains any recognized secret patterns."""
    if not text:
        return False
    return any(p.search(text) is not None for p, _ in SECRET_PATTERNS)
