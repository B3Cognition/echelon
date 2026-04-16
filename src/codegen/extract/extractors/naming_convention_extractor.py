"""
naming_convention_extractor.py — Detects naming conventions from source files.
Spec 018 F3 T-011.

Detects camelCase, snake_case, PascalCase patterns via regex.
Active-correction detection: pattern in codebase AND linter config as violation
→ Category B with source: active-correction.
"""
from __future__ import annotations

import json
import logging
import os
import re
from collections import Counter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_SOURCE_EXTENSIONS = frozenset({".js", ".ts", ".jsx", ".tsx", ".py", ".mjs", ".cjs"})

# Regex for identifier detection (simplified: word boundaries around identifiers)
_CAMEL_CASE_RE = re.compile(r"\b[a-z][a-zA-Z0-9]*[A-Z][a-zA-Z0-9]*\b")
_SNAKE_CASE_RE = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")
_PASCAL_CASE_RE = re.compile(r"\b[A-Z][a-z][a-zA-Z0-9]*\b")
_SCREAMING_SNAKE_RE = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b")

# ESLint rule names that enforce naming conventions
_ESLINT_NAMING_RULES = frozenset({
    "camelcase",
    "@typescript-eslint/naming-convention",
    "new-cap",
    "id-naming-convention",
})


def _get_linter_naming_violations(root: str) -> set[str]:
    """
    Check ESLint configs for naming-convention rules.
    Returns set of naming style strings that the linter flags as violations.
    """
    from src.codegen.security.path_safety import PathSafety

    flagged: set[str] = set()
    safety = PathSafety(root)
    config_names = frozenset({
        ".eslintrc", ".eslintrc.json", ".eslintrc.yaml", ".eslintrc.yml",
    })

    for filepath in safety.safe_walk(root, skip_hidden=False):
        basename = os.path.basename(filepath)
        if basename not in config_names:
            continue
        try:
            with open(filepath, encoding="utf-8") as fh:
                content = fh.read()
            data = json.loads(content)
        except (OSError, json.JSONDecodeError):
            continue

        rules = data.get("rules", {}) if isinstance(data, dict) else {}
        for rule_name in _ESLINT_NAMING_RULES:
            if rule_name in rules:
                rule_val = rules[rule_name]
                severity = rule_val[0] if isinstance(rule_val, (list, tuple)) and rule_val else rule_val
                if severity not in ("off", 0, "0"):
                    # camelcase rule flags snake_case
                    if rule_name == "camelcase":
                        flagged.add("snake_case")
                    elif rule_name == "@typescript-eslint/naming-convention":
                        flagged.add("naming-convention-enforced")

    return flagged


def extract(root: str) -> list:
    """
    Scan source files under root and detect naming convention patterns.

    Args:
        root: Directory root to search.

    Returns:
        List of ExtractedRule objects.
    """
    from src.codegen.extract.constitution_extractor import ExtractedRule
    from src.codegen.security.path_safety import PathSafety

    safety = PathSafety(root)
    pattern_counts: Counter[str] = Counter()
    files_scanned = 0

    for filepath in safety.safe_walk(root, skip_hidden=True):
        ext = os.path.splitext(filepath)[1].lower()
        if ext not in _SOURCE_EXTENSIONS:
            continue
        # Skip test files for naming convention detection
        basename = os.path.basename(filepath)
        if re.search(r"(test|spec)", basename, re.IGNORECASE):
            continue

        try:
            with open(filepath, encoding="utf-8", errors="replace") as fh:
                content = fh.read()
        except OSError:
            continue

        files_scanned += 1
        if _CAMEL_CASE_RE.search(content):
            pattern_counts["camelCase"] += 1
        if _SNAKE_CASE_RE.search(content):
            pattern_counts["snake_case"] += 1
        if _PASCAL_CASE_RE.search(content):
            pattern_counts["PascalCase"] += 1
        if _SCREAMING_SNAKE_RE.search(content):
            pattern_counts["SCREAMING_SNAKE_CASE"] += 1

    if files_scanned == 0:
        return []

    linter_violations = _get_linter_naming_violations(root)
    threshold = max(1, files_scanned // 2)

    descriptions = {
        "camelCase": "Naming convention: camelCase used for variables/functions",
        "snake_case": "Naming convention: snake_case used in codebase",
        "PascalCase": "Naming convention: PascalCase used for classes/components",
        "SCREAMING_SNAKE_CASE": "Naming convention: SCREAMING_SNAKE_CASE used for constants",
    }

    rules: list[ExtractedRule] = []
    for convention, desc in descriptions.items():
        if pattern_counts.get(convention, 0) < threshold:
            continue

        # Active-correction: pattern present AND linter flags it as violation
        if convention in linter_violations:
            category = "B"
            source = "active-correction"
            raw_text = f"{desc} (active-correction: linter flags this pattern)"
        else:
            category = "B"
            source = "direct"
            raw_text = desc

        rules.append(
            ExtractedRule(
                source_type="naming_convention",
                raw_text=raw_text,
                category=category,
                confidence=0.65,
                source=source,
            )
        )

    return rules
