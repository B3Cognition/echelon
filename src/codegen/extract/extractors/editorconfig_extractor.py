"""
editorconfig_extractor.py — Extracts rules from .editorconfig files.
Spec 018 F3 T-011.
"""
from __future__ import annotations

import logging
import os
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_SECTION_RE = re.compile(r"^\[(.+)\]$")
_KV_RE = re.compile(r"^\s*([a-z_]+)\s*=\s*(.+?)\s*$")
_COMMENT_RE = re.compile(r"^\s*[#;]")


def extract(root: str) -> list:
    """
    Find .editorconfig files under root and extract key=value settings as rules.

    Args:
        root: Directory root to search.

    Returns:
        List of ExtractedRule objects.
    """
    from src.codegen.extract.constitution_extractor import ExtractedRule
    from src.codegen.security.path_safety import PathSafety

    rules: list[ExtractedRule] = []
    safety = PathSafety(root)

    for filepath in safety.safe_walk(root, skip_hidden=False):
        if os.path.basename(filepath) != ".editorconfig":
            continue
        try:
            with open(filepath, encoding="utf-8") as fh:
                lines = fh.readlines()
        except OSError as exc:
            logger.warning("editorconfig_extractor: skipping %s — %s", filepath, exc)
            continue

        current_section = "*"
        for line in lines:
            line = line.rstrip("\n")
            if _COMMENT_RE.match(line) or not line.strip():
                continue
            section_match = _SECTION_RE.match(line.strip())
            if section_match:
                current_section = section_match.group(1)
                continue
            kv_match = _KV_RE.match(line)
            if kv_match:
                key = kv_match.group(1)
                value = kv_match.group(2)
                raw_text = f"EditorConfig [{current_section}] {key} = {value}"
                rules.append(
                    ExtractedRule(
                        source_type="editorconfig",
                        raw_text=raw_text,
                        category="S",
                        confidence=0.90,
                        source="direct",
                    )
                )

    return rules
