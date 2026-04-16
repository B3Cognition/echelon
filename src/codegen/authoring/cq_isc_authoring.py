"""
cq_isc_authoring.py — Custom CQ-ISC Authoring Pipeline.
Spec 008: SOAR-Powered Claude Code Software Development Agent
Version: 1.0.0

T-033: Custom CQ-ISC authoring per FR-ISC-CUSTOM-001..005.

Components:
  (a) NL2GenSym pipeline (Category S rules — "generable by LLM"):
        Generator → Critic → Executor → SMEM admission
  (b) Category B guided authoring (behavioral rules — human must provide predicate):
        Rule classification → explanation → WME template → Executor validation
  (c) Authoring estimate display (FR-ISC-CUSTOM-005)
  (d) Policy drift detection via content hash

Category classification:
  Category S: structural/quality rules that mention measurable quantities
               (line counts, cyclomatic complexity, etc.)
               → NL2GenSym can generate a SOAR predicate.
  Category B: behavioral constraints (execution order, transaction rules)
               → requires human-authored SOAR predicate.

FR-ISC-CUSTOM-001: Category S rules auto-translated via Generator-Critic.
FR-ISC-CUSTOM-002: Category B rules guided to human author.
FR-ISC-CUSTOM-003: Executor validation runs SOAR kernel against synthetic WMEs.
FR-ISC-CUSTOM-004: Drift detection on constitution change.
FR-ISC-CUSTOM-005: Authoring estimate shown before BUILD phase.
NFR-USE-003: Authoring interface is plain-English.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Rule categories
# ---------------------------------------------------------------------------

class RuleCategory(str, Enum):
    CATEGORY_S = "S"   # Structural/quality — NL2GenSym pipeline
    CATEGORY_B = "B"   # Behavioral — human-authored predicate


# Admission status
class AdmissionStatus(str, Enum):
    ADMITTED = "admitted"              # passed Executor validation → SMEM
    PENDING_VALIDATION = "pending"     # failed Executor → queued for review
    AWAITING_HUMAN = "awaiting_human"  # Category B — needs human predicate
    REJECTED = "rejected"              # explicitly rejected


# ---------------------------------------------------------------------------
# Keyword sets for Category S vs B classification
# ---------------------------------------------------------------------------

_CATEGORY_S_KEYWORDS = [
    "lines", "length", "complexity", "cyclomatic", "depth", "count",
    "number", "size", "characters", "columns", "parameters", "arguments",
    "imports", "dependencies", "nesting", "return",
    # Code quality anti-patterns (detectable, not behavioral)
    "console.log", "console", "hardcoded", "secret", "eval",
    "test file", "test", "source file",
]

_CATEGORY_B_PATTERNS = [
    r"\bafter\b.*\bbefore\b",
    r"\bmust.*\bcall\b",
    r"\bonly.*\bwhen\b",
    r"\bsequence\b",
    r"\btransaction\b",
    r"\bpayment\b",
    r"\bcommit\b",
    r"\brollback\b",
    r"\bcheck\b.*\bbefore\b",
]


# ---------------------------------------------------------------------------
# Predicate generation (NL2GenSym Generator step)
# ---------------------------------------------------------------------------

# Rule text pattern → SOAR WME predicate (simplified; production uses LLM)
_PREDICATE_TEMPLATES: dict[str, str] = {
    r"function[s]?\s*(?:must\s+be\s+)?(?:less than|<|under|≤|<=)\s*(\d+)\s*line": (
        "(code ^function-length > {n})"
    ),
    r"function[s]?\s*(?:must\s+have\s+)?(?:no more than|≤|<=|<)\s*(\d+)\s*param": (
        "(code ^parameter-count > {n})"
    ),
    r"(?:cyclomatic\s*)?complexity\s*(?:must\s+be\s+)?(?:less than|<|under|≤|<=)\s*(\d+)": (
        "(code ^cyclomatic-complexity > {n})"
    ),
    r"no\s+(?:hard.?coded|hardcoded)\s+secret": (
        "(code ^hardcoded-secret true)"
    ),
    r"no\s+console\.?log": (
        "(code ^console-log true)"
    ),
    r"(?:every|each)\s+(?:source\s+)?file\s+(?:must\s+have|has)\s+(?:a\s+)?test": (
        "(source-file ^test-file-missing true)"
    ),
    r"no\s+eval": (
        "(code ^eval-usage true)"
    ),
    r"import[s]?\s*(?:must\s+be\s+)?(?:no more than|≤|<=|<)\s*(\d+)": (
        "(code ^import-count > {n})"
    ),
}

# Critic corrections (common Generator errors)
_CRITIC_CORRECTIONS: dict[str, str] = {
    ">=": ">",   # "function-length >= 30" → "function-length > 29"
    "==": "=",
}


def _generate_predicate(rule_text: str) -> Optional[str]:
    """
    NL2GenSym Generator step: produce a SOAR predicate from rule text.

    Returns None if no template matches (requires human authoring).
    """
    rule_lower = rule_text.lower()
    for pattern, template in _PREDICATE_TEMPLATES.items():
        m = re.search(pattern, rule_lower, re.IGNORECASE)
        if m:
            # Substitute numeric threshold if present
            try:
                n = int(m.group(1)) - 1  # e.g. "< 30 lines" → "> 29"
                return template.format(n=n)
            except (IndexError, ValueError):
                return template.format(n="?")
    return None


def _critic_review(predicate: str) -> str:
    """
    NL2GenSym Critic step: review and correct common Generator errors.

    Returns corrected predicate.
    """
    corrected = predicate
    for wrong, right in _CRITIC_CORRECTIONS.items():
        corrected = corrected.replace(wrong, right)
    return corrected


# ---------------------------------------------------------------------------
# Executor validation (FR-ISC-CUSTOM-003)
# ---------------------------------------------------------------------------

_VALID_SOAR_ATTRIBUTES = {
    "function-length", "parameter-count", "cyclomatic-complexity",
    "hardcoded-secret", "console-log", "test-file-missing", "eval-usage",
    "import-count", "nesting-depth", "return-count",
}

_VALID_WME_OBJECTS = {"code", "source-file", "module", "test-file"}


def executor_validate(predicate: str, strict: bool = True) -> tuple[bool, str]:
    """
    Executor step: validate the predicate against synthetic test WMEs.

    FR-ISC-CUSTOM-003: Runs SOAR kernel against synthetic WMEs.

    Here: structural validation (production version runs SOAR binary).
    Returns (valid, reason).

    Args:
        predicate: The SOAR predicate string.
        strict:    If True, validate wme_obj and attribute against known sets
                   (used for Category S predicates).
                   If False, only validate WME structure (used for Category B
                   predicates with user-defined attributes).
    """
    # Must be enclosed in ( )
    m = re.match(r"\((\S+)\s+\^(\S+)\s+(.+)\)", predicate.strip())
    if not m:
        return False, f"Predicate '{predicate}' does not match WME pattern (object ^attr value)."

    wme_obj = m.group(1)
    attribute = m.group(2)
    value = m.group(3).strip()

    if strict:
        if wme_obj not in _VALID_WME_OBJECTS:
            return False, f"Unknown WME object '{wme_obj}'. Expected one of {_VALID_WME_OBJECTS}."
        if attribute not in _VALID_SOAR_ATTRIBUTES:
            return False, f"Unknown WME attribute '{attribute}'. Expected one of {_VALID_SOAR_ATTRIBUTES}."

    # WME object must still be in the known set even for non-strict mode
    if not strict and wme_obj not in _VALID_WME_OBJECTS:
        return False, f"Unknown WME object '{wme_obj}'. Expected one of {_VALID_WME_OBJECTS}."

    if not value:
        return False, "WME value must be non-empty."

    # Attribute must be a valid identifier (kebab-case or snake_case)
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9\-_]*$", attribute):
        return False, f"Attribute '{attribute}' must be a valid identifier."

    return True, "Predicate passes structural Executor validation."


# ---------------------------------------------------------------------------
# Category classification
# ---------------------------------------------------------------------------

def classify_rule(rule_text: str) -> RuleCategory:
    """
    Classify a constitution rule as Category S or Category B.

    Category S: rule mentions measurable structural/quality quantities.
    Category B: rule describes behavioral constraints (execution order, etc.).
    """
    rule_lower = rule_text.lower()

    # Category B indicators take precedence
    for pattern in _CATEGORY_B_PATTERNS:
        if re.search(pattern, rule_lower, re.IGNORECASE):
            return RuleCategory.CATEGORY_B

    # Category S: mentions measurable quantities
    for kw in _CATEGORY_S_KEYWORDS:
        if kw in rule_lower:
            return RuleCategory.CATEGORY_S

    # Default to Category B (safer — requires human authoring)
    return RuleCategory.CATEGORY_B


# ---------------------------------------------------------------------------
# CQ-ISC authoring entry
# ---------------------------------------------------------------------------

@dataclass
class AuthoredEntry:
    """
    A custom CQ-ISC entry produced by the authoring pipeline.

    FR-ISC-CUSTOM-001..003: Category S generated, Category B human-authored.
    """
    cq_isc_id: str
    rule_text: str
    category: RuleCategory
    soar_predicate: Optional[str]
    constraint_class: str = "CUSTOM"
    language_scope: str = "all"
    admission_status: AdmissionStatus = AdmissionStatus.PENDING_VALIDATION
    executor_valid: bool = False
    executor_reason: str = ""
    generator_output: Optional[str] = None
    critic_output: Optional[str] = None

    def to_library_entry(self) -> dict[str, str]:
        """Serialize for insertion into CQ-ISC library."""
        return {
            "cq_isc_id": self.cq_isc_id,
            "rule_text": self.rule_text,
            "soar_predicate": self.soar_predicate or "",
            "constraint_class": self.constraint_class,
            "language_scope": self.language_scope,
            "law_drift_status": "active",
        }


# ---------------------------------------------------------------------------
# Policy drift detection (FR-ISC-CUSTOM-004)
# ---------------------------------------------------------------------------

def compute_content_hash(text: str) -> str:
    """Compute SHA-256 of the source-authority section of a constitution."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class DriftDetector:
    """
    FR-ISC-CUSTOM-004: Detect policy drift when the constitution changes.

    Compares current content hash of the source-authority section
    against the last known hash.
    """
    _hashes: dict[str, str] = field(default_factory=dict)  # rule_id → hash

    def record(self, rule_id: str, rule_text: str) -> None:
        """Record the current hash for a rule."""
        self._hashes[rule_id] = compute_content_hash(rule_text)

    def detect(self, rule_id: str, rule_text: str) -> bool:
        """Return True if the rule has drifted since it was last recorded."""
        current = compute_content_hash(rule_text)
        prior = self._hashes.get(rule_id)
        return prior is not None and current != prior

    def has_any_drift(self, rules: dict[str, str]) -> bool:
        """Return True if any rule in the dict has drifted."""
        return any(self.detect(rid, text) for rid, text in rules.items())


# ---------------------------------------------------------------------------
# Authoring estimate display (FR-ISC-CUSTOM-005)
# ---------------------------------------------------------------------------

def authoring_estimate(
    category_s_count: int,
    category_b_count: int,
    nl2gensym_accuracy: float = 0.75,
) -> str:
    """
    FR-ISC-CUSTOM-005: Display authoring estimate in plain English before BUILD.

    Returns human-readable estimate string.
    """
    s_auto = int(category_s_count * nl2gensym_accuracy)
    s_review = category_s_count - s_auto

    lines = [
        f"CQ-ISC Authoring Estimate",
        f"─────────────────────────",
        f"Category S rules (auto-generated):   {category_s_count}",
        f"  ├─ Expected to auto-validate:       {s_auto} (~{int(nl2gensym_accuracy*100)}% accuracy)",
        f"  └─ Expected to need human review:   {s_review}",
        f"Category B rules (human authoring):  {category_b_count}",
        f"  └─ Each requires manual predicate authoring",
        f"",
        f"Total rules ready for SMEM after review: ~{s_auto + category_b_count}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Authoring pipeline
# ---------------------------------------------------------------------------

class CQISCAuthoringPipeline:
    """
    Full custom CQ-ISC authoring pipeline.

    FR-ISC-CUSTOM-001: Category S → NL2GenSym (Generator → Critic → Executor).
    FR-ISC-CUSTOM-002: Category B → guided human authoring.
    FR-ISC-CUSTOM-003: Executor validates all predicates before SMEM admission.
    FR-ISC-CUSTOM-004: Drift detection on constitution change.
    FR-ISC-CUSTOM-005: Authoring estimate before BUILD.
    """

    def __init__(self, id_prefix: str = "CQ-ISC-CUSTOM") -> None:
        self.id_prefix = id_prefix
        self._counter: int = 0
        self.drift_detector = DriftDetector()

    def _next_id(self, constraint_class: str) -> str:
        self._counter += 1
        abbrev = constraint_class.upper()[:5]
        return f"{self.id_prefix}-{abbrev}-{self._counter:03d}"

    def process_rule(
        self,
        rule_text: str,
        constraint_class: str = "STRUCTURAL",
        language_scope: str = "all",
        human_predicate: Optional[str] = None,
    ) -> AuthoredEntry:
        """
        Process one constitution rule through the authoring pipeline.

        For Category S: runs Generator → Critic → Executor.
        For Category B: requires human_predicate; validates with Executor.

        Returns AuthoredEntry with admission status.
        """
        category = classify_rule(rule_text)
        cq_isc_id = self._next_id(constraint_class)

        entry = AuthoredEntry(
            cq_isc_id=cq_isc_id,
            rule_text=rule_text,
            category=category,
            soar_predicate=None,
            constraint_class=constraint_class,
            language_scope=language_scope,
        )

        if category == RuleCategory.CATEGORY_S:
            # (a) NL2GenSym Generator
            generated = _generate_predicate(rule_text)
            entry.generator_output = generated

            if generated is None:
                # Generator failed → pending validation queue
                entry.admission_status = AdmissionStatus.PENDING_VALIDATION
                entry.executor_reason = "Generator could not produce a predicate."
                return entry

            # (b) Critic review
            corrected = _critic_review(generated)
            entry.critic_output = corrected

            # (c) Executor validation
            valid, reason = executor_validate(corrected)
            entry.executor_valid = valid
            entry.executor_reason = reason

            if valid:
                entry.soar_predicate = corrected
                entry.admission_status = AdmissionStatus.ADMITTED
            else:
                entry.soar_predicate = corrected
                entry.admission_status = AdmissionStatus.PENDING_VALIDATION

        elif category == RuleCategory.CATEGORY_B:
            entry.admission_status = AdmissionStatus.AWAITING_HUMAN

            if human_predicate:
                # Run Executor on human-provided predicate (non-strict: allows custom attrs)
                valid, reason = executor_validate(human_predicate, strict=False)
                entry.executor_valid = valid
                entry.executor_reason = reason
                entry.soar_predicate = human_predicate

                if valid:
                    entry.admission_status = AdmissionStatus.ADMITTED
                else:
                    entry.admission_status = AdmissionStatus.PENDING_VALIDATION

        return entry

    def process_batch(
        self,
        rules: list[dict[str, str]],
    ) -> list[AuthoredEntry]:
        """
        Process a batch of constitution rules.

        Each rule dict: {"text": str, "class": str, "language_scope": str,
                         "human_predicate": Optional[str]}.
        """
        results: list[AuthoredEntry] = []
        for rule in rules:
            entry = self.process_rule(
                rule_text=rule.get("text", ""),
                constraint_class=rule.get("class", "STRUCTURAL"),
                language_scope=rule.get("language_scope", "all"),
                human_predicate=rule.get("human_predicate"),
            )
            results.append(entry)
        return results

    def category_b_explanation(self, rule_text: str) -> str:
        """
        FR-ISC-CUSTOM-002: Explain why a rule is Category B and provide WME template.

        NFR-USE-003: Plain-English explanation.
        """
        return (
            f"Rule classified as CATEGORY B (behavioral constraint):\n"
            f"  '{rule_text}'\n\n"
            f"Category B rules describe execution order, transaction constraints,\n"
            f"or other behavioral properties that cannot be inferred from code\n"
            f"structure alone. The NL2GenSym pipeline cannot auto-generate a\n"
            f"predicate — you must provide one manually.\n\n"
            f"WME template for SOAR:\n"
            f"  (code ^<attribute> <value>)\n\n"
            f"Example predicates:\n"
            f"  (code ^fraud-check-called false)\n"
            f"  (code ^audit-log-missing true)\n\n"
            f"Provide your predicate via the --predicate flag or interactive prompt.\n"
        )
