"""
secret_scrubber.py — Shared credential scrubbing utility.

SEC-025 FIX-1: Secret scrubbing before any MemPalace/ChromaDB write.

Uses the security package's credential deny-list so persistent-memory
scrubbing remains independent of any execution harness.

FR-001: Apply deny-list to all document fields before ChromaDB writes.
FR-002: Replace matched secret values with [REDACTED]; preserve surrounding text.
"""
from __future__ import annotations

import re

from codegen.security.credential_patterns import CREDENTIAL_DENY_PATTERNS

# Additional patterns for connection string passwords, bearer tokens, and PEM keys.
_EXTRA_PATTERNS = [
    # URI credentials: scheme://user:password@host
    re.compile(r"(?<=[:/]{2})[^:@\s]+:[^@\s]+(?=@)"),
    # Bearer / Authorization header values
    re.compile(r"(?i)Bearer\s+[A-Za-z0-9\-_./+]{20,}"),
    # PEM private key block
    re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----"),
    # Generic high-entropy tokens: 32+ hex chars or base64 runs
    re.compile(r"[A-Za-z0-9+/]{40,}={0,2}"),
]

# All patterns in priority order: shared deny-list first, then extras.
_ALL_PATTERNS = list(CREDENTIAL_DENY_PATTERNS) + _EXTRA_PATTERNS

_REDACTED = "[REDACTED]"


def scrub_secrets(text: str) -> str:
    """
    Apply all credential patterns to *text*, replacing matches with [REDACTED].

    Preserves surrounding non-secret text.  Non-destructive: if no pattern
    matches the original text is returned unchanged.

    Args:
        text: The raw document field content to scrub.

    Returns:
        Scrubbed text with credential values replaced by [REDACTED].
    """
    result = text
    for pattern in _ALL_PATTERNS:
        result = pattern.sub(_REDACTED, result)
    return result
