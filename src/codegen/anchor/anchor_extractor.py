"""
anchor_extractor.py — Style analysis extractor for Anchoring Mode.
Spec 018 T-015: F4 Anchoring Mode — AnchorExtractor core.

Analyzes a codebase directory and extracts style constraints across 5 dimensions:
  1. naming      — camelCase / snake_case / PascalCase convention detection
  2. imports     — Python AST import grouping order analysis
  3. test_structure — test framework detection
  4. comment_density — ratio of comment lines to total non-blank lines
  5. abstraction — function complexity analysis

RAR-002: All file reads via PathSafety.
"""
from __future__ import annotations

import ast
import logging
import os
import re
import time
import uuid
from pathlib import Path
from typing import Optional

from ..security.path_safety import PathSafety
from .anchoring_types import AnchoringConstraint

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ANCHOR_TIMEOUT_SECONDS = 30.0

_CAMEL_RE = re.compile(r"\b[a-z][a-zA-Z0-9]*[A-Z][a-zA-Z0-9]*\b")
_SNAKE_RE = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")
_PASCAL_RE = re.compile(r"\b[A-Z][a-z][a-zA-Z0-9]*\b")

_PYTEST_RE = re.compile(r"\bimport pytest\b|\bfrom pytest\b|def test_\w+\s*\(")
_UNITTEST_RE = re.compile(r"\bimport unittest\b|\bfrom unittest\b|class \w+\(.*TestCase\)")
_JEST_RE = re.compile(r"\bimport .* from ['\"]jest['\"]|\bdescribe\(|\bit\(|expect\(")
_MOCHA_RE = re.compile(r"\bimport .* from ['\"]mocha['\"]|\bdescribe\(|\bit\(|chai\.")

# ---------------------------------------------------------------------------
# AnchorExtractor
# ---------------------------------------------------------------------------


class AnchorExtractor:
    """
    Analyzes a codebase directory and extracts AnchoringConstraints.
    """

    def analyze(
        self,
        anchor_path: "Path | str",
        run_id: Optional[str] = None,
    ) -> list[AnchoringConstraint]:
        """
        Analyze anchor_path and return a list of AnchoringConstraints.

        Args:
            anchor_path: Path to the anchor codebase root (user-supplied).
            run_id: Pipeline run UUID. Fresh UUID generated if not provided.

        Returns:
            List of AnchoringConstraint objects. Empty list if path is absent
            or unreadable (AC-013-3: log WARNING, do not raise).
        """
        if run_id is None:
            run_id = str(uuid.uuid4())

        # RAR-002: use PathSafety with os.getcwd() as trusted root since
        # anchor_path is user-supplied and may be anywhere on the filesystem.
        # We normalize without containment assertion so user can point at any
        # accessible directory they own.
        safety = PathSafety(os.getcwd())
        try:
            normalized = safety.normalize(anchor_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[AnchorExtractor] Cannot normalize anchor path '%s': %s", anchor_path, exc)
            return []

        if not os.path.isdir(normalized):
            logger.warning(
                "[AnchorExtractor] Anchor path '%s' is absent or not a directory (AC-013-3).",
                anchor_path,
            )
            return []

        constraints: list[AnchoringConstraint] = []
        deadline = time.monotonic() + ANCHOR_TIMEOUT_SECONDS

        # Collect files via safe_walk (symlinks skipped — RAR-002)
        # We use a PathSafety rooted at the anchor dir itself for walking.
        anchor_safety = PathSafety(normalized)
        files_visited: list[str] = []
        try:
            for fpath in anchor_safety.safe_walk(normalized):
                if time.monotonic() > deadline:
                    logger.warning("[AnchorExtractor] 30-second timeout reached — stopping scan.")
                    break
                files_visited.append(fpath)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[AnchorExtractor] Error walking '%s': %s", normalized, exc)

        if not files_visited:
            logger.warning("[AnchorExtractor] No readable files found under '%s'.", normalized)
            return []

        # Run each dimension
        constraints.extend(self._analyze_naming(files_visited, run_id, deadline))
        constraints.extend(self._analyze_imports(files_visited, run_id, deadline))
        constraints.extend(self._analyze_test_structure(files_visited, run_id, deadline))
        constraints.extend(self._analyze_comment_density(files_visited, run_id, deadline))
        constraints.extend(self._analyze_abstraction(files_visited, run_id, deadline))

        return constraints

    # ------------------------------------------------------------------
    # Dimension: naming
    # ------------------------------------------------------------------

    def _analyze_naming(
        self,
        files: list[str],
        run_id: str,
        deadline: float,
    ) -> list[AnchoringConstraint]:
        """Detect dominant naming convention (camelCase / snake_case / PascalCase)."""
        camel_count = 0
        snake_count = 0
        pascal_count = 0
        representative_file = files[0] if files else ""

        for fpath in files:
            if time.monotonic() > deadline:
                break
            try:
                text = _read_text(fpath)
            except OSError:
                continue
            camel_count += len(_CAMEL_RE.findall(text))
            snake_count += len(_SNAKE_RE.findall(text))
            pascal_count += len(_PASCAL_RE.findall(text))
            representative_file = fpath

        total = camel_count + snake_count + pascal_count
        if total == 0:
            return []

        if snake_count >= camel_count and snake_count >= pascal_count:
            convention = "snake_case"
            pct = int(100 * snake_count / total)
        elif camel_count >= pascal_count:
            convention = "camelCase"
            pct = int(100 * camel_count / total)
        else:
            convention = "PascalCase"
            pct = int(100 * pascal_count / total)

        return [
            AnchoringConstraint(
                constraint_id=f"naming-{uuid.uuid4().hex[:8]}",
                dimension="naming",
                constraint_text=(
                    f"Uses {convention} naming convention "
                    f"(found in {pct}% of identifiers)"
                ),
                source_path=representative_file,
                run_id=run_id,
            )
        ]

    # ------------------------------------------------------------------
    # Dimension: imports
    # ------------------------------------------------------------------

    def _analyze_imports(
        self,
        files: list[str],
        run_id: str,
        deadline: float,
    ) -> list[AnchoringConstraint]:
        """
        Python AST analysis of import grouping order (stdlib → third-party → local).
        SyntaxError is non-blocking — skip the file.
        """
        import_patterns: list[str] = []
        source_file = ""

        for fpath in files:
            if time.monotonic() > deadline:
                break
            if not fpath.endswith(".py"):
                continue
            try:
                text = _read_text(fpath)
                tree = ast.parse(text, filename=fpath)
            except (OSError, SyntaxError):
                continue

            groups = _classify_import_groups(tree)
            if groups:
                import_patterns.append(groups)
                source_file = fpath

        if not import_patterns:
            return []

        dominant = max(set(import_patterns), key=import_patterns.count)
        pct = int(100 * import_patterns.count(dominant) / len(import_patterns))

        return [
            AnchoringConstraint(
                constraint_id=f"imports-{uuid.uuid4().hex[:8]}",
                dimension="imports",
                constraint_text=(
                    f"Uses '{dominant}' import grouping order "
                    f"(observed in {pct}% of Python files)"
                ),
                source_path=source_file,
                run_id=run_id,
            )
        ]

    # ------------------------------------------------------------------
    # Dimension: test_structure
    # ------------------------------------------------------------------

    def _analyze_test_structure(
        self,
        files: list[str],
        run_id: str,
        deadline: float,
    ) -> list[AnchoringConstraint]:
        """Detect test framework (pytest, unittest, jest, mocha)."""
        framework_counts: dict[str, int] = {
            "pytest": 0,
            "unittest": 0,
            "jest": 0,
            "mocha": 0,
        }
        source_file = ""

        for fpath in files:
            if time.monotonic() > deadline:
                break
            try:
                text = _read_text(fpath)
            except OSError:
                continue
            if _PYTEST_RE.search(text):
                framework_counts["pytest"] += 1
                source_file = fpath
            if _UNITTEST_RE.search(text):
                framework_counts["unittest"] += 1
                source_file = fpath
            if _JEST_RE.search(text):
                framework_counts["jest"] += 1
                source_file = fpath
            if _MOCHA_RE.search(text):
                framework_counts["mocha"] += 1
                source_file = fpath

        best = max(framework_counts, key=lambda k: framework_counts[k])
        if framework_counts[best] == 0:
            return []

        total = sum(framework_counts.values())
        pct = int(100 * framework_counts[best] / total) if total else 0

        return [
            AnchoringConstraint(
                constraint_id=f"test_structure-{uuid.uuid4().hex[:8]}",
                dimension="test_structure",
                constraint_text=(
                    f"Uses {best} test framework "
                    f"(detected in {pct}% of test pattern matches)"
                ),
                source_path=source_file,
                run_id=run_id,
            )
        ]

    # ------------------------------------------------------------------
    # Dimension: comment_density
    # ------------------------------------------------------------------

    def _analyze_comment_density(
        self,
        files: list[str],
        run_id: str,
        deadline: float,
    ) -> list[AnchoringConstraint]:
        """
        Calculate ratio of comment lines to total non-blank lines.
        Target: ~15-25%.
        """
        total_lines = 0
        comment_lines = 0
        source_file = ""

        for fpath in files:
            if time.monotonic() > deadline:
                break
            if not fpath.endswith((".py", ".js", ".ts", ".java", ".go", ".rb")):
                continue
            try:
                text = _read_text(fpath)
            except OSError:
                continue
            lines = text.splitlines()
            non_blank = [l for l in lines if l.strip()]
            comments = [l for l in non_blank if l.strip().startswith(("#", "//", "/*", "*"))]
            total_lines += len(non_blank)
            comment_lines += len(comments)
            source_file = fpath

        if total_lines == 0:
            return []

        density_pct = int(100 * comment_lines / total_lines)

        return [
            AnchoringConstraint(
                constraint_id=f"comment_density-{uuid.uuid4().hex[:8]}",
                dimension="comment_density",
                constraint_text=(
                    f"Comment density is {density_pct}% of non-blank lines "
                    f"(target: 15-25%)"
                ),
                source_path=source_file,
                run_id=run_id,
            )
        ]

    # ------------------------------------------------------------------
    # Dimension: abstraction
    # ------------------------------------------------------------------

    def _analyze_abstraction(
        self,
        files: list[str],
        run_id: str,
        deadline: float,
    ) -> list[AnchoringConstraint]:
        """
        Python AST: average function line count as proxy for complexity.
        Non-Python files: regex count of function definitions.
        SyntaxError is non-blocking.
        """
        func_lengths: list[int] = []
        source_file = ""

        for fpath in files:
            if time.monotonic() > deadline:
                break
            try:
                text = _read_text(fpath)
            except OSError:
                continue

            if fpath.endswith(".py"):
                try:
                    tree = ast.parse(text, filename=fpath)
                    for node in ast.walk(tree):
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            length = (node.end_lineno or node.lineno) - node.lineno + 1
                            func_lengths.append(length)
                    source_file = fpath
                except SyntaxError:
                    pass
            else:
                # regex fallback for JS/TS/Java etc.
                fn_matches = re.findall(
                    r"(?:function\s+\w+|(?:def|fn|func)\s+\w+)\s*\(",
                    text,
                )
                func_lengths.extend([10] * len(fn_matches))  # default estimate
                if fn_matches:
                    source_file = fpath

        if not func_lengths:
            return []

        avg_length = int(sum(func_lengths) / len(func_lengths))

        return [
            AnchoringConstraint(
                constraint_id=f"abstraction-{uuid.uuid4().hex[:8]}",
                dimension="abstraction",
                constraint_text=(
                    f"Average function length is {avg_length} lines "
                    f"across {len(func_lengths)} functions"
                ),
                source_path=source_file,
                run_id=run_id,
            )
        ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_text(fpath: str) -> str:
    """Read file text, ignoring encoding errors."""
    with open(fpath, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def _classify_import_groups(tree: ast.Module) -> str:
    """
    Classify the import grouping pattern of a Python module.
    Returns a string like "stdlib->third_party->local" or similar.
    """
    import sys
    stdlib_names = sys.stdlib_module_names if hasattr(sys, "stdlib_module_names") else set()

    groups: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in stdlib_names:
                    groups.append("stdlib")
                else:
                    groups.append("third_party_or_local")
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                groups.append("local")
            else:
                mod = (node.module or "").split(".")[0]
                if mod in stdlib_names:
                    groups.append("stdlib")
                else:
                    groups.append("third_party_or_local")

    if not groups:
        return "no_imports"

    # Detect ordering pattern
    seen: list[str] = []
    for g in groups:
        if not seen or seen[-1] != g:
            seen.append(g)

    return "->".join(seen) if seen else "mixed"
