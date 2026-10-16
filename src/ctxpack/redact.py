"""Redact credentials before code is pasted into a chat window."""

from __future__ import annotations

import re

# (kind, pattern). Ordered from most to least specific.
PATTERNS: list[tuple[str, re.Pattern]] = [
    ("private-key", re.compile(
        r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z0-9 ]*PRIVATE KEY-----")),
    ("anthropic-key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}")),
    ("openai-key", re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_\-]{32,}")),
    ("github-token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{60,})")),
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("slack-token", re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}")),
    ("stripe-key", re.compile(r"\b[rs]k_live_[0-9A-Za-z]{24,}")),
    ("huggingface-token", re.compile(r"\bhf_[A-Za-z0-9]{34,}")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}")),
]


def redact(text: str) -> tuple[str, dict[str, int]]:
    """Return ``text`` with secrets replaced by ``[REDACTED:<kind>]`` and per-kind counts."""
    counts: dict[str, int] = {}
    for kind, pattern in PATTERNS:
        text, n = pattern.subn(f"[REDACTED:{kind}]", text)
        if n:
            counts[kind] = counts.get(kind, 0) + n
    return text, counts
