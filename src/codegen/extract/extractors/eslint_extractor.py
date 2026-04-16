"""
eslint_extractor.py — Extracts rules from ESLint config files.
Spec 018 F3 T-011.

Suppression detection: if a pattern appears in eslint-disable comments
in source files, that rule is NOT Category S.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_ESLINT_CONFIG_NAMES = frozenset({
    ".eslintrc",
    ".eslintrc.json",
    ".eslintrc.js",
    ".eslintrc.cjs",
    ".eslintrc.yaml",
    ".eslintrc.yml",
    "eslint.config.js",
    "eslint.config.mjs",
    "eslint.config.cjs",
})

_ESLINT_DISABLE_RE = re.compile(
    r"(?://\s*eslint-disable(?:-next-line|-line)?\s+|/\*\s*eslint-disable\s+)([\w\-/@, ]+)"
)
_NOQA_RE = re.compile(r"#\s*noqa\s*:\s*([\w\-,\s]+)")

_SOURCE_EXTENSIONS = frozenset({".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs"})


def _collect_suppressed_rules(root: str) -> set[str]:
    """Scan source files for eslint-disable / noqa patterns and return suppressed rule names."""
    from src.codegen.security.path_safety import PathSafety

    suppressed: set[str] = set()
    safety = PathSafety(root)

    for filepath in safety.safe_walk(root, skip_hidden=True):
        ext = os.path.splitext(filepath)[1].lower()
        if ext not in _SOURCE_EXTENSIONS:
            continue
        try:
            with open(filepath, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue

        for match in _ESLINT_DISABLE_RE.finditer(text):
            for rule in match.group(1).split(","):
                rule = rule.strip()
                if rule:
                    suppressed.add(rule)

        for match in _NOQA_RE.finditer(text):
            for code in match.group(1).split(","):
                code = code.strip()
                if code:
                    suppressed.add(code)

    return suppressed


def _parse_rules_from_data(data: object) -> dict[str, object]:
    """Extract the 'rules' dict from an eslint config object (handles nested structures)."""
    if not isinstance(data, dict):
        return {}
    # Standard .eslintrc format
    rules = data.get("rules", {})
    if isinstance(rules, dict):
        return rules
    return {}


def extract(root: str) -> list:
    """
    Find ESLint config files under root and extract rule entries.

    Args:
        root: Directory root to search.

    Returns:
        List of ExtractedRule objects.
    """
    from src.codegen.extract.constitution_extractor import ExtractedRule
    from src.codegen.security.path_safety import PathSafety

    suppressed = _collect_suppressed_rules(root)
    rules: list[ExtractedRule] = []
    safety = PathSafety(root)

    for filepath in safety.safe_walk(root, skip_hidden=False):
        basename = os.path.basename(filepath)
        if basename not in _ESLINT_CONFIG_NAMES:
            continue

        ext = os.path.splitext(basename)[1].lower()
        try:
            with open(filepath, encoding="utf-8") as fh:
                content = fh.read()
        except OSError as exc:
            logger.warning("eslint_extractor: skipping %s — %s", filepath, exc)
            continue

        data: object = None
        if ext in (".json", "") or basename in (".eslintrc", ".eslintrc.json"):
            try:
                data = json.loads(content)
            except json.JSONDecodeError:
                logger.warning("eslint_extractor: JSON parse error in %s", filepath)
                continue
        elif ext in (".yaml", ".yml"):
            try:
                import yaml  # noqa: PLC0415
                data = yaml.safe_load(content)
            except Exception as exc:  # noqa: BLE001
                logger.warning("eslint_extractor: YAML parse error in %s — %s", filepath, exc)
                continue
        else:
            # .js/.cjs/.mjs — we can only do basic regex extraction; skip deep parse
            logger.debug("eslint_extractor: skipping JS config %s (no JS eval)", filepath)
            continue

        rule_map = _parse_rules_from_data(data)
        for rule_name, rule_value in rule_map.items():
            # Determine severity
            severity = rule_value
            if isinstance(rule_value, (list, tuple)) and rule_value:
                severity = rule_value[0]
            # Skip "off" / 0
            if severity in ("off", 0, "0"):
                continue

            category: str
            source: str
            if rule_name in suppressed:
                # Rule defined but suppressed in code — advisory only
                category = "B"
                source = "active-correction"
            else:
                category = "S"
                source = "direct"

            severity_label = severity if isinstance(severity, str) else {1: "warn", 2: "error"}.get(severity, str(severity))
            raw_text = f"ESLint rule '{rule_name}' set to {severity_label}"

            rules.append(
                ExtractedRule(
                    source_type="eslint",
                    raw_text=raw_text,
                    category=category,
                    confidence=0.80,
                    source=source,
                )
            )

    return rules
