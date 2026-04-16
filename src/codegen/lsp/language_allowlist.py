"""
language_allowlist.py — Strict allowlist for language field values.
Spec 018 T-SEC-1: RAR-001 command injection prevention.

Only languages in LANGUAGE_ALLOWLIST may trigger LSP gate tool invocation.
Any other value in codegen-state.json:language is rejected before subprocess invocation.
This prevents command injection via crafted language field values.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Allowlisted language identifiers and their LSP tools
# ---------------------------------------------------------------------------

#: Map from normalized language identifier → LSP tool binary name.
#: Only these entries may trigger a subprocess invocation in LspGate.
LANGUAGE_ALLOWLIST: dict[str, str] = {
    "typescript": "tsc",
    "javascript": "tsc",
    "python": "mypy",
    "go": "go",
    "java": "mvn",
}

#: Set of valid language identifiers (for O(1) membership test).
VALID_LANGUAGES: frozenset[str] = frozenset(LANGUAGE_ALLOWLIST.keys())


def is_allowed(language: str) -> bool:
    """Return True if the language identifier is in the allowlist."""
    return language.lower().strip() in VALID_LANGUAGES


def get_tool(language: str) -> str | None:
    """
    Return the LSP tool binary name for an allowed language.
    Returns None if the language is not in the allowlist.
    """
    return LANGUAGE_ALLOWLIST.get(language.lower().strip())
