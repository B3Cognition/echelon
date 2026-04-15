"""constitution_checker.py — Constitutional principle grammar runner.

Implements the structural principle checker described in spec.md § "Constitutional Principle Grammar".

Supported accessor forms:
    sections[title='<title>']                    — top-level section by heading text
    sections[title='<parent>'].subsections[title='<child>']  — nested section
    fr[id='<FR-ID>']                            — functional requirement by ID
    yaml_node['<dotted.key.path>']              — YAML artifact node

Supported predicate types:
    MUST_CONTAIN <literal>
    MUST_NOT_CONTAIN <literal>
    MUST_MATCH_REGEX <regex>
    MUST_NOT_MATCH_REGEX <regex>
    MUST_HAVE_FIELD <field-name>
    MUST_HAVE_NON_EMPTY_FIELD <field-name>

Principles declared as form: prose are skipped (not machine-checkable).

Pure function: no I/O on the critical path except reading artifact files.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class CheckerError(Exception):
    """Base class for checker errors."""


class AccessorError(CheckerError):
    """Raised when an accessor cannot resolve to a node."""

    def __init__(self, accessor: str, reason: str) -> None:
        self.accessor = accessor
        self.reason = reason
        super().__init__(f"AccessorError at '{accessor}': {reason}")


class PredicateError(CheckerError):
    """Raised when a predicate is malformed or unsupported."""

    def __init__(self, predicate: str, reason: str) -> None:
        self.predicate = predicate
        self.reason = reason
        super().__init__(f"PredicateError for '{predicate}': {reason}")


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


class CheckResult(dict):
    """Result of checking a single principle.
    Keys: principle_id, form, verdict, accessor, predicate, resolved_text, reason
    Verdict: PASS | FAIL | SKIP | ERROR
    """


# ---------------------------------------------------------------------------
# Accessor parsing
# ---------------------------------------------------------------------------

# Regex for accessor forms
_SECTIONS_RE = re.compile(r"^sections\[title='([^']+)'\]$")
_SECTIONS_NESTED_RE = re.compile(
    r"^sections\[title='([^']+)'\]\.subsections\[title='([^']+)'\]$"
)
_FR_RE = re.compile(r"^fr\[id='([^']+)'\]$")
_YAML_NODE_RE = re.compile(r"^yaml_node\['([^']+)'\]$")


def _extract_section(text: str, title: str) -> Optional[str]:
    """Extract a section from markdown text by heading title."""
    # Match both # and ## headings
    pattern = re.compile(
        r"^(?:#{1,4})\s+" + re.escape(title) + r"\s*$",
        re.MULTILINE
    )
    match = pattern.search(text)
    if not match:
        return None

    start = match.start()
    level = len(match.group(0)) - len(match.group(0).lstrip("#"))

    # Find the end: next heading at same or higher level
    end_pattern = re.compile(r"^#{1," + str(level) + r"}\s+", re.MULTILINE)
    end_match = end_pattern.search(text, match.end())
    if end_match:
        return text[start:end_match.start()]
    return text[start:]


def _extract_subsection(text: str, parent_title: str, child_title: str) -> Optional[str]:
    """Extract a subsection from markdown text."""
    parent = _extract_section(text, parent_title)
    if parent is None:
        return None
    return _extract_section(parent, child_title)


def _extract_fr(text: str, fr_id: str) -> Optional[str]:
    """Extract a functional requirement block by ID from markdown or YAML text."""
    if fr_id == "*":
        # Return full text for wildcard
        return text

    # Try markdown: look for ## FR-XXX or ### FR-XXX
    pattern = re.compile(
        r"^(?:#{2,4})\s+" + re.escape(fr_id) + r"(?:\s|:)",
        re.MULTILINE
    )
    match = pattern.search(text)
    if match:
        start = match.start()
        level = len(text[start:].split("\n")[0]) - len(text[start:].split("\n")[0].lstrip("#"))
        end_pattern = re.compile(r"^#{1," + str(level) + r"}\s+", re.MULTILINE)
        end_match = end_pattern.search(text, match.end())
        if end_match:
            return text[start:end_match.start()]
        return text[start:]

    # Try inline: look for `FR-XXX:` or `**FR-XXX**`
    inline_pattern = re.compile(
        re.escape(fr_id) + r"[:\s]",
        re.MULTILINE
    )
    match = inline_pattern.search(text)
    if match:
        # Return surrounding context (up to 500 chars)
        start = max(0, match.start() - 50)
        end = min(len(text), match.end() + 500)
        return text[start:end]

    return None


def _resolve_yaml_node(yaml_data: Any, dotted_path: str) -> Any:
    """Resolve a dotted key path in a YAML dict."""
    parts = dotted_path.split(".")
    current = yaml_data
    for part in parts:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
        if current is None:
            return None
    return current


def resolve_accessor(
    accessor: str,
    artifact_text: str,
    artifact_yaml: Any = None,
) -> Optional[str]:
    """Resolve an accessor to a text fragment.

    Args:
        accessor:      The accessor string.
        artifact_text: The full artifact text (markdown).
        artifact_yaml: Parsed YAML of the artifact (for yaml_node accessors).

    Returns:
        Resolved text string, or None if not found.
    """
    # sections[title='...']
    m = _SECTIONS_RE.match(accessor)
    if m:
        return _extract_section(artifact_text, m.group(1))

    # sections[title='...'].subsections[title='...']
    m = _SECTIONS_NESTED_RE.match(accessor)
    if m:
        return _extract_subsection(artifact_text, m.group(1), m.group(2))

    # fr[id='...']
    m = _FR_RE.match(accessor)
    if m:
        return _extract_fr(artifact_text, m.group(1))

    # yaml_node['dotted.key.path']
    m = _YAML_NODE_RE.match(accessor)
    if m:
        if artifact_yaml is None:
            raise AccessorError(accessor, "yaml_node accessor requires parsed YAML (artifact_yaml=None)")
        resolved = _resolve_yaml_node(artifact_yaml, m.group(1))
        if resolved is None:
            return None
        return str(resolved)

    raise AccessorError(accessor, f"Unknown accessor form: {accessor!r}")


# ---------------------------------------------------------------------------
# Predicate evaluation
# ---------------------------------------------------------------------------

_PREDICATE_RE = re.compile(
    r"^(MUST_CONTAIN|MUST_NOT_CONTAIN|MUST_MATCH_REGEX|MUST_NOT_MATCH_REGEX|MUST_HAVE_FIELD|MUST_HAVE_NON_EMPTY_FIELD)\s+(.+)$",
    re.DOTALL
)


def evaluate_predicate(predicate: str, resolved_text: str) -> tuple[bool, str]:
    """Evaluate a predicate against resolved text.

    Returns (passed, reason).
    """
    m = _PREDICATE_RE.match(predicate.strip())
    if not m:
        raise PredicateError(predicate, f"Cannot parse predicate: {predicate!r}")

    pred_type = m.group(1)
    pred_arg = m.group(2).strip()

    if pred_type == "MUST_CONTAIN":
        passed = pred_arg in resolved_text
        reason = f"text {'contains' if passed else 'does not contain'} {pred_arg!r}"
        return passed, reason

    if pred_type == "MUST_NOT_CONTAIN":
        passed = pred_arg not in resolved_text
        reason = f"text {'does not contain' if passed else 'unexpectedly contains'} {pred_arg!r}"
        return passed, reason

    if pred_type == "MUST_MATCH_REGEX":
        try:
            pattern = re.compile(pred_arg, re.MULTILINE | re.DOTALL)
        except re.error as exc:
            raise PredicateError(predicate, f"Invalid regex {pred_arg!r}: {exc}")
        passed = bool(pattern.search(resolved_text))
        reason = f"text {'matches' if passed else 'does not match'} regex {pred_arg!r}"
        return passed, reason

    if pred_type == "MUST_NOT_MATCH_REGEX":
        try:
            pattern = re.compile(pred_arg, re.MULTILINE | re.DOTALL)
        except re.error as exc:
            raise PredicateError(predicate, f"Invalid regex {pred_arg!r}: {exc}")
        passed = not bool(pattern.search(resolved_text))
        reason = f"text {'does not match' if passed else 'unexpectedly matches'} regex {pred_arg!r}"
        return passed, reason

    if pred_type == "MUST_HAVE_FIELD":
        # For structured text: check if field name appears as a key
        pattern = re.compile(r"(?:^|\n)\s*" + re.escape(pred_arg) + r"\s*:", re.MULTILINE)
        passed = bool(pattern.search(resolved_text))
        reason = f"field {pred_arg!r} {'present' if passed else 'absent'}"
        return passed, reason

    if pred_type == "MUST_HAVE_NON_EMPTY_FIELD":
        # Check field appears with non-empty value
        pattern = re.compile(
            r"(?:^|\n)\s*" + re.escape(pred_arg) + r"\s*:\s*(\S+)",
            re.MULTILINE
        )
        m2 = pattern.search(resolved_text)
        if m2 and m2.group(1):
            return True, f"field {pred_arg!r} has non-empty value {m2.group(1)!r}"
        return False, f"field {pred_arg!r} absent or empty"

    # Should not reach here
    raise PredicateError(predicate, f"Unimplemented predicate type: {pred_type!r}")


# ---------------------------------------------------------------------------
# Principle checker
# ---------------------------------------------------------------------------


def check_principle(
    principle: dict[str, Any],
    artifact_text: str,
    artifact_yaml: Any = None,
) -> CheckResult:
    """Check a single constitutional principle against an artifact.

    Args:
        principle:     Principle dict with keys: id, form, text, accessor, predicate.
        artifact_text: Full text of the artifact to check.
        artifact_yaml: Parsed YAML of the artifact (for yaml_node accessors).

    Returns:
        CheckResult dict.
    """
    principle_id = principle.get("id", "unknown")
    form = principle.get("form", "prose")
    accessor = principle.get("accessor", "")
    predicate = principle.get("predicate", "")

    # Skip prose principles
    if form != "structural":
        return CheckResult(
            principle_id=principle_id,
            form=form,
            verdict="SKIP",
            accessor=accessor,
            predicate=predicate,
            resolved_text=None,
            reason=f"form={form!r} — not machine-checkable (only 'structural' is checked)",
        )

    # Resolve accessor
    try:
        resolved = resolve_accessor(accessor, artifact_text, artifact_yaml)
    except AccessorError as exc:
        return CheckResult(
            principle_id=principle_id,
            form=form,
            verdict="ERROR",
            accessor=accessor,
            predicate=predicate,
            resolved_text=None,
            reason=str(exc),
        )

    if resolved is None:
        return CheckResult(
            principle_id=principle_id,
            form=form,
            verdict="FAIL",
            accessor=accessor,
            predicate=predicate,
            resolved_text=None,
            reason=f"Accessor '{accessor}' resolved to None — section/node not found in artifact",
        )

    # Evaluate predicate
    try:
        passed, reason = evaluate_predicate(predicate, resolved)
    except PredicateError as exc:
        return CheckResult(
            principle_id=principle_id,
            form=form,
            verdict="ERROR",
            accessor=accessor,
            predicate=predicate,
            resolved_text=resolved[:200] if resolved else None,
            reason=str(exc),
        )

    return CheckResult(
        principle_id=principle_id,
        form=form,
        verdict="PASS" if passed else "FAIL",
        accessor=accessor,
        predicate=predicate,
        resolved_text=resolved[:200] if resolved else None,
        reason=reason,
    )


# ---------------------------------------------------------------------------
# Batch checker
# ---------------------------------------------------------------------------


def check_constitution(
    principles: list[dict[str, Any]],
    artifact_text: str,
    artifact_yaml: Any = None,
) -> list[CheckResult]:
    """Check all principles against an artifact.

    Returns a list of CheckResult, one per principle.
    Structural principles produce PASS/FAIL/ERROR.
    Prose principles produce SKIP.
    """
    return [check_principle(p, artifact_text, artifact_yaml) for p in principles]


def check_constitution_file(
    constitution_path: Path,
    artifact_path: Path,
) -> list[CheckResult]:
    """Load a constitution file and check all structural principles against an artifact.

    The constitution file is expected to be a YAML file with a top-level 'principles' list.
    """
    try:
        import yaml  # type: ignore
        with constitution_path.open(encoding="utf-8") as f:
            constitution = yaml.safe_load(f)
    except ImportError:
        # PyYAML not available — parse minimal YAML manually
        constitution = {}
    except Exception as exc:
        raise CheckerError(f"Cannot load constitution file {constitution_path}: {exc}")

    if not isinstance(constitution, dict):
        raise CheckerError(f"Constitution file {constitution_path} must be a YAML dict")

    principles = constitution.get("principles", [])
    if not isinstance(principles, list):
        raise CheckerError(f"Constitution file has no 'principles' list")

    artifact_text = artifact_path.read_text(encoding="utf-8")
    artifact_yaml = None
    if artifact_path.suffix in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore
            with artifact_path.open(encoding="utf-8") as f:
                artifact_yaml = yaml.safe_load(f)
        except Exception:
            pass

    return check_constitution(principles, artifact_text, artifact_yaml)
