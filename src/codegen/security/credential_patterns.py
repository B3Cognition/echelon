"""Credential patterns shared by active persistent-memory writers."""
from __future__ import annotations

import re

CREDENTIAL_DENY_PATTERNS = (
    re.compile(r"/Users/[^/\s]+"),
    re.compile(r"/home/[^/\s]+"),
    re.compile(r"C:\\\\[^\s]+"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}"),
    re.compile(r"(?i)(password|secret|token)\s*[:=]\s*\S+"),
)
