"""Minimal-collection helpers: never store card-like numbers or secrets in free text."""
from __future__ import annotations

import re

_CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")
_SECRET = re.compile(r"(?i)\b(password|passwd|secret|api[_-]?key|token)\s*[:=]\s*\S+")


def mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    return (local[:1] + "***@" + domain) if domain else "***"


def scrub_text(text: str | None, limit: int = 300) -> str | None:
    if text is None:
        return None
    text = _CARD.sub("[REDACTED-NUMBER]", text)
    text = _SECRET.sub(lambda m: f"{m.group(1)}=[REDACTED]", text)
    return text[:limit]
