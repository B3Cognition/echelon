"""
test_pattern_extractor.py — Extracts patterns from test files.
Spec 018 F3 T-011.

Detects: describe/it blocks, assertion styles (expect/assert/should),
test file naming conventions.
"""
from __future__ import annotations

import logging
import os
import re
from collections import Counter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Patterns to detect in test files
_DESCRIBE_RE = re.compile(r"\bdescribe\s*\(")
_IT_RE = re.compile(r"\bit\s*\(|\btest\s*\(")
_EXPECT_RE = re.compile(r"\bexpect\s*\(")
_ASSERT_RE = re.compile(r"\bassert\b")
_SHOULD_RE = re.compile(r"\.should\b")
_BEFOREEACH_RE = re.compile(r"\bbeforeEach\s*\(|\bbeforeAll\s*\(")
_AFTEREACH_RE = re.compile(r"\bafterEach\s*\(|\bafterAll\s*\(")
_MOCK_RE = re.compile(r"\bjest\.mock\s*\(|\bvi\.mock\s*\(|\bsinon\b")
_SNAPSHOT_RE = re.compile(r"\.toMatchSnapshot\s*\(|\.toMatchInlineSnapshot\s*\(")

_TEST_FILE_RE = re.compile(r"(test|spec)", re.IGNORECASE)
_TEST_EXTENSIONS = frozenset({".js", ".ts", ".jsx", ".tsx", ".mjs"})


def extract(root: str) -> list:
    """
    Find test files under root and extract common patterns.

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
        basename = os.path.basename(filepath)
        ext = os.path.splitext(basename)[1].lower()
        if ext not in _TEST_EXTENSIONS:
            continue
        if not _TEST_FILE_RE.search(basename):
            continue

        try:
            with open(filepath, encoding="utf-8", errors="replace") as fh:
                content = fh.read()
        except OSError:
            continue

        files_scanned += 1
        if _DESCRIBE_RE.search(content):
            pattern_counts["describe_it_blocks"] += 1
        if _IT_RE.search(content):
            pattern_counts["it_test_blocks"] += 1
        if _EXPECT_RE.search(content):
            pattern_counts["jest_expect_assertions"] += 1
        if _ASSERT_RE.search(content):
            pattern_counts["assert_style_assertions"] += 1
        if _SHOULD_RE.search(content):
            pattern_counts["should_style_assertions"] += 1
        if _BEFOREEACH_RE.search(content):
            pattern_counts["lifecycle_hooks"] += 1
        if _MOCK_RE.search(content):
            pattern_counts["mock_framework_usage"] += 1
        if _SNAPSHOT_RE.search(content):
            pattern_counts["snapshot_testing"] += 1

    if files_scanned == 0:
        return []

    rules: list[ExtractedRule] = []
    threshold = max(1, files_scanned // 2)  # majority presence

    descriptions = {
        "describe_it_blocks": "Test files use describe/it block structure",
        "it_test_blocks": "Test files use it() / test() for individual cases",
        "jest_expect_assertions": "Assertion style: expect(...).to* (Jest/Vitest)",
        "assert_style_assertions": "Assertion style: assert.* (Node assert / Chai)",
        "should_style_assertions": "Assertion style: .should.* (Chai should)",
        "lifecycle_hooks": "Test lifecycle hooks (beforeEach/afterEach) in use",
        "mock_framework_usage": "Mocking via jest.mock / vi.mock / sinon detected",
        "snapshot_testing": "Snapshot testing (toMatchSnapshot) in use",
    }

    for pattern_key, desc in descriptions.items():
        if pattern_counts.get(pattern_key, 0) >= threshold:
            rules.append(
                ExtractedRule(
                    source_type="test_pattern",
                    raw_text=desc,
                    category="B",
                    confidence=0.70,
                    source="direct",
                )
            )

    return rules
