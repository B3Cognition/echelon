"""
anchoring_evaluator.py — Code evaluation against anchoring constraints.
Spec 018 T-016: F4 Anchoring Mode — AnchoringEvaluator.

Evaluates generated code against AnchoringConstraints extracted from the
anchor codebase. Produces AnchoringViolation objects when code deviates
from established style conventions.

AC-014-new-2a: AnchoringViolation.to_wme_dict() produces CQ-ISC-compatible
               WME dicts — violations are indistinguishable from CQ-ISC
               violations in the GATE phase output.
AC-014-new-3:  When constraints is empty, log 'tier_anchor_gate: unavailable'
               and return empty list.
"""
from __future__ import annotations

import ast
import logging
import re
from typing import TYPE_CHECKING

from .anchoring_types import AnchoringConstraint, AnchoringViolation

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Naming convention patterns
# ---------------------------------------------------------------------------

_SNAKE_RE = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")
_CAMEL_RE = re.compile(r"\b[a-z][a-zA-Z0-9]*[A-Z][a-zA-Z0-9]*\b")
_PASCAL_RE = re.compile(r"\b[A-Z][a-z][a-zA-Z0-9]*\b")

_CONVENTION_PATTERNS: dict[str, re.Pattern] = {
    "snake_case": _SNAKE_RE,
    "camelCase": _CAMEL_RE,
    "PascalCase": _PASCAL_RE,
}

# Comment density target band
_COMMENT_DENSITY_LOW = 5   # below this is a violation (too sparse)
_COMMENT_DENSITY_HIGH = 40  # above this is a violation (too dense)


# ---------------------------------------------------------------------------
# AnchoringEvaluator
# ---------------------------------------------------------------------------


class AnchoringEvaluator:
    """
    Evaluates generated code against a list of AnchoringConstraints.

    Three analysis methods:
      1. regex — naming convention constraints
      2. ast   — structural constraints (Python only)
      3. line-density — comment density constraints
    """

    def evaluate(
        self,
        code_text: str,
        constraints: list[AnchoringConstraint],
    ) -> list[AnchoringViolation]:
        """
        Evaluate code_text against each constraint.

        Args:
            code_text: The generated code to evaluate.
            constraints: Constraints extracted from the anchor codebase.

        Returns:
            List of AnchoringViolation objects (empty if no violations).
            Returns empty list and logs warning when constraints is empty
            (AC-014-new-3).
        """
        if not constraints:
            logger.warning("tier_anchor_gate: unavailable — no anchoring constraints loaded")
            return []

        violations: list[AnchoringViolation] = []

        for constraint in constraints:
            dim = constraint.dimension

            if dim == "naming":
                violations.extend(
                    self._evaluate_naming(code_text, constraint)
                )
            elif dim == "imports":
                violations.extend(
                    self._evaluate_ast_imports(code_text, constraint)
                )
            elif dim == "comment_density":
                violations.extend(
                    self._evaluate_comment_density(code_text, constraint)
                )
            elif dim in ("test_structure", "abstraction"):
                violations.extend(
                    self._evaluate_ast_structure(code_text, constraint)
                )

        return violations

    # ------------------------------------------------------------------
    # Method 1: regex — naming convention
    # ------------------------------------------------------------------

    def _evaluate_naming(
        self,
        code_text: str,
        constraint: AnchoringConstraint,
    ) -> list[AnchoringViolation]:
        """
        Check that identifiers in code_text follow the convention specified
        in the constraint. A violation is raised when the opposite convention
        is strongly detected.
        """
        violations: list[AnchoringViolation] = []
        text_lower = constraint.constraint_text.lower()

        # Determine the expected convention from constraint text
        if "snake_case" in text_lower:
            expected = "snake_case"
            opposite_patterns = [("camelCase", _CAMEL_RE)]
        elif "camelcase" in text_lower:
            expected = "camelCase"
            opposite_patterns = [("snake_case", _SNAKE_RE)]
        elif "pascalcase" in text_lower:
            expected = "PascalCase"
            opposite_patterns = [("camelCase", _CAMEL_RE), ("snake_case", _SNAKE_RE)]
        else:
            return []

        lines = code_text.splitlines()
        for line_no, line in enumerate(lines, start=1):
            for convention_name, pattern in opposite_patterns:
                matches = pattern.findall(line)
                if matches:
                    violations.append(
                        AnchoringViolation(
                            constraint_id=constraint.constraint_id,
                            dimension=constraint.dimension,
                            matched_text=matches[0],
                            line=line_no,
                        )
                    )
                    break  # one violation per line per constraint is enough

        return violations

    # ------------------------------------------------------------------
    # Method 2: ast — structural constraints
    # ------------------------------------------------------------------

    def _evaluate_ast_imports(
        self,
        code_text: str,
        constraint: AnchoringConstraint,
    ) -> list[AnchoringViolation]:
        """
        Python AST analysis: check import grouping.
        SyntaxError → no violations (non-blocking).
        """
        try:
            tree = ast.parse(code_text)
        except SyntaxError:
            return []

        # Collect top-level import nodes in source order (ast.body preserves order)
        import_nodes = [
            n for n in tree.body
            if isinstance(n, (ast.Import, ast.ImportFrom))
        ]
        if not import_nodes:
            return []

        # Classify each import in source order
        import sys
        stdlib_names = sys.stdlib_module_names if hasattr(sys, "stdlib_module_names") else set()

        groups: list[tuple[str, int]] = []
        for node in import_nodes:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    groups.append(("stdlib" if root in stdlib_names else "other", node.lineno))
            elif isinstance(node, ast.ImportFrom):
                if node.level and node.level > 0:
                    groups.append(("local", node.lineno))
                else:
                    mod = (node.module or "").split(".")[0]
                    groups.append(("stdlib" if mod in stdlib_names else "other", node.lineno))

        # Detect if stdlib imports appear AFTER non-stdlib (other/local) imports
        # (violation: the expected order is stdlib → third-party → local)
        violations: list[AnchoringViolation] = []
        non_stdlib_line: int | None = None
        for group_type, line_no in groups:
            # Record first non-stdlib import line
            if group_type in ("other", "local") and non_stdlib_line is None:
                non_stdlib_line = line_no
            # If a stdlib import appears AFTER a non-stdlib import, that's a violation
            if group_type == "stdlib" and non_stdlib_line is not None:
                violations.append(
                    AnchoringViolation(
                        constraint_id=constraint.constraint_id,
                        dimension=constraint.dimension,
                        matched_text="stdlib import after non-stdlib import",
                        line=line_no,
                    )
                )
                break

        return violations

    def _evaluate_ast_structure(
        self,
        code_text: str,
        constraint: AnchoringConstraint,
    ) -> list[AnchoringViolation]:
        """
        Generic AST structural check for test_structure and abstraction.
        SyntaxError → no violations (non-blocking).
        """
        try:
            ast.parse(code_text)
        except SyntaxError:
            return []
        # Structure is valid Python — no structural violations by default
        return []

    # ------------------------------------------------------------------
    # Method 3: line-density — comment density
    # ------------------------------------------------------------------

    def _evaluate_comment_density(
        self,
        code_text: str,
        constraint: AnchoringConstraint,
    ) -> list[AnchoringViolation]:
        """
        Count ratio of comment lines to non-blank lines.
        Violation if density falls outside [LOW, HIGH] band.
        """
        lines = code_text.splitlines()
        non_blank = [l for l in lines if l.strip()]
        if not non_blank:
            return []

        comment_lines = [
            l for l in non_blank
            if l.strip().startswith(("#", "//", "/*", "*"))
        ]
        density_pct = int(100 * len(comment_lines) / len(non_blank))

        if density_pct < _COMMENT_DENSITY_LOW:
            return [
                AnchoringViolation(
                    constraint_id=constraint.constraint_id,
                    dimension=constraint.dimension,
                    matched_text=f"comment density {density_pct}% is below threshold {_COMMENT_DENSITY_LOW}%",
                    line=1,
                )
            ]
        if density_pct > _COMMENT_DENSITY_HIGH:
            return [
                AnchoringViolation(
                    constraint_id=constraint.constraint_id,
                    dimension=constraint.dimension,
                    matched_text=f"comment density {density_pct}% exceeds threshold {_COMMENT_DENSITY_HIGH}%",
                    line=1,
                )
            ]
        return []
