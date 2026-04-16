"""
mode.py — Greenfield invocation mode.
Spec 008: SOAR-Powered Claude Code Software Development Agent
Version: 1.0.0

T-032: Greenfield mode (no target-path, intent only).

FR-RE-007: Replace the RE phase with a domain research step:
  (a) Identify reference architectures for the described domain.
  (b) Infer language/framework stack from intent if not specified.
  (c) Produce minimal staging artifacts (mental-model, boundaries).
  (d) Prompt user for acceptance criteria if none stated.
  (e) Produce |I_D| estimate from acceptance criteria.

FR-ISC-DEFAULT-001: Greenfield uses the default CQ-ISC seed library.
FR-CMD-002: Greenfield mode activated when --intent is provided without --target-path.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Stack profiles (FR-RE-007)
# ---------------------------------------------------------------------------

class LanguageStack(str, Enum):
    TYPESCRIPT = "typescript"
    PYTHON = "python"
    GO = "go"
    JAVA = "java"
    JAVASCRIPT = "javascript"
    UNKNOWN = "unknown"


# Intent keyword → language stack mapping (heuristic-based, FR-RE-007)
_STACK_KEYWORDS: dict[LanguageStack, list[str]] = {
    LanguageStack.TYPESCRIPT: [
        "typescript", "ts", "react", "next.js", "nextjs", "angular", "vue",
        "node.js", "nodejs", "express", "nest.js", "nestjs", "deno",
        "rest api", "graphql", "fastify",
    ],
    LanguageStack.PYTHON: [
        "python", "django", "flask", "fastapi", "sqlalchemy", "celery",
        "pandas", "numpy", "scikit", "pytest", "pydantic",
        "ml", "machine learning", "data science",
    ],
    LanguageStack.GO: [
        "go", "golang", "gin", "echo", "fiber", "grpc", "protobuf",
        "kubernetes", "k8s", "microservice",
    ],
    LanguageStack.JAVA: [
        "java", "spring", "spring boot", "maven", "gradle", "junit",
        "hibernate", "jpa", "jakarta", "enterprise",
    ],
    LanguageStack.JAVASCRIPT: [
        "javascript", "js", "vanilla js", "commonjs",
    ],
}

# Domain → reference architecture lookup (simplified; production would use INVESTIGATOR)
_DOMAIN_REFERENCE_ARCHITECTURES: dict[str, str] = {
    "rest api": "REST API with layered architecture: controller → service → repository",
    "crud": "CRUD service: HTTP endpoints → business layer → persistence layer",
    "microservice": "Microservice: API gateway → service mesh → individual services",
    "cli": "CLI tool: argument parser → command dispatcher → output formatter",
    "worker": "Worker service: queue consumer → processor → result emitter",
    "data pipeline": "ETL pipeline: source adapter → transformer → sink adapter",
}


# ---------------------------------------------------------------------------
# Staging artifacts (FR-RE-007c)
# ---------------------------------------------------------------------------

@dataclass
class GreenfieldStagingArtifacts:
    """
    Minimal staging artifacts produced by greenfield RE phase.

    FR-RE-007: produced from intent description without brownfield codebase.
    """
    intent: str
    detected_stack: LanguageStack
    mental_model: str
    boundaries: list[str]
    reference_architecture: Optional[str]
    acceptance_criteria: list[str]
    id_estimate: int
    requires_ac_prompt: bool     # True if user must be prompted for AC


# ---------------------------------------------------------------------------
# Stack detection (FR-RE-007b)
# ---------------------------------------------------------------------------

def detect_stack(intent: str) -> LanguageStack:
    """
    Infer the language/framework stack from intent text.

    Uses word-boundary keyword matching; falls back to UNKNOWN if ambiguous.
    Returns the stack with the highest keyword match score.
    """
    intent_lower = intent.lower()

    scores: dict[LanguageStack, int] = {}
    for stack, keywords in _STACK_KEYWORDS.items():
        score = 0
        for kw in keywords:
            # Use word boundary for single-word keywords to avoid
            # "java" matching inside "javascript"
            pattern = r"\b" + re.escape(kw) + r"\b"
            if re.search(pattern, intent_lower):
                score += 1
        if score > 0:
            scores[stack] = score

    if not scores:
        return LanguageStack.UNKNOWN

    # Return stack with highest keyword score
    return max(scores, key=lambda s: scores[s])


# ---------------------------------------------------------------------------
# Domain research (FR-RE-007a)
# ---------------------------------------------------------------------------

def lookup_reference_architecture(intent: str) -> Optional[str]:
    """
    Look up a reference architecture for the described domain.

    In production: calls INVESTIGATOR agent or WebSearch.
    Here: heuristic keyword lookup against _DOMAIN_REFERENCE_ARCHITECTURES.
    """
    intent_lower = intent.lower()
    for domain, architecture in _DOMAIN_REFERENCE_ARCHITECTURES.items():
        if domain in intent_lower:
            return architecture
    return None


def infer_domain(intent: str) -> str:
    """Return the primary domain keyword detected in the intent."""
    intent_lower = intent.lower()
    for domain in _DOMAIN_REFERENCE_ARCHITECTURES:
        if domain in intent_lower:
            return domain
    return "general software service"


# ---------------------------------------------------------------------------
# Acceptance criteria detection (FR-RE-007d)
# ---------------------------------------------------------------------------

def has_acceptance_criteria(intent: str) -> bool:
    """
    Detect whether the intent statement includes acceptance criteria.

    Heuristic: looks for patterns like "given/when/then", numbered lists,
    "must", "should", "so that", "acceptance criteria".
    """
    patterns = [
        r"\bgiven\b.*\bwhen\b.*\bthen\b",
        r"acceptance criteria",
        r"\b(must|should)\b.{1,80}\b(pass|work|return|produce|validate|require)\b",
        r"^\s*\d+\.",               # numbered list
        r"so that",
    ]
    intent_lower = intent.lower()
    return any(re.search(p, intent_lower, re.MULTILINE) for p in patterns)


def extract_acceptance_criteria(intent: str) -> list[str]:
    """
    Extract acceptance criteria from the intent text.

    Returns list of criterion strings (may be empty).
    """
    criteria: list[str] = []

    # Pattern: lines starting with a number or "AC:"
    for line in intent.splitlines():
        line = line.strip()
        if re.match(r"^\d+\.", line) or line.lower().startswith("ac:"):
            criteria.append(line)

    # Pattern: "must ... " clauses
    if not criteria:
        for m in re.finditer(r"(?:must|should)\s+([^.;]+)[.;]", intent, re.IGNORECASE):
            criteria.append(m.group(0).strip())

    return criteria


# ---------------------------------------------------------------------------
# |I_D| estimation from acceptance criteria (FR-RE-007e)
# ---------------------------------------------------------------------------

def estimate_id_from_criteria(acceptance_criteria: list[str]) -> int:
    """
    Estimate |I_D| from the stated acceptance criteria.

    Strategy: each criterion maps to ≈1 requirement.
    Minimum estimate is 1.
    """
    if not acceptance_criteria:
        return 1
    return max(1, len(acceptance_criteria))


# ---------------------------------------------------------------------------
# Greenfield pipeline
# ---------------------------------------------------------------------------

class GreenfieldMode:
    """
    Greenfield mode: run codegen without a brownfield codebase.

    FR-CMD-002: Activated when --intent provided without --target-path.
    FR-RE-007: Replaces the RE phase with domain research.
    FR-ISC-DEFAULT-001: Uses default CQ-ISC seed library.
    """

    def __init__(self, default_library: Optional[list[dict]] = None) -> None:
        self.default_library = default_library or []

    def prepare(
        self,
        intent: str,
        stack_override: Optional[str] = None,
        explicit_acceptance_criteria: Optional[list[str]] = None,
    ) -> GreenfieldStagingArtifacts:
        """
        Execute the greenfield RE phase from intent text.

        Args:
            intent:                    The user's intent description.
            stack_override:            If provided, skip stack detection.
            explicit_acceptance_criteria: If provided, skip AC prompt.

        Returns:
            GreenfieldStagingArtifacts ready for the BUILD phase.
        """
        # (a) Reference architecture lookup
        reference_arch = lookup_reference_architecture(intent)
        domain = infer_domain(intent)

        # (b) Stack detection
        if stack_override:
            detected_stack = LanguageStack(stack_override.lower())
        else:
            detected_stack = detect_stack(intent)

        # (c) Mental model and boundaries from intent
        mental_model = self._build_mental_model(intent, domain, detected_stack, reference_arch)
        boundaries = self._infer_boundaries(intent, detected_stack)

        # (d) Acceptance criteria
        if explicit_acceptance_criteria is not None:
            acceptance_criteria = explicit_acceptance_criteria
            requires_ac_prompt = False
        elif has_acceptance_criteria(intent):
            acceptance_criteria = extract_acceptance_criteria(intent)
            requires_ac_prompt = False
        else:
            acceptance_criteria = []
            requires_ac_prompt = True

        # (e) |I_D| estimate
        id_estimate = estimate_id_from_criteria(acceptance_criteria)

        return GreenfieldStagingArtifacts(
            intent=intent,
            detected_stack=detected_stack,
            mental_model=mental_model,
            boundaries=boundaries,
            reference_architecture=reference_arch,
            acceptance_criteria=acceptance_criteria,
            id_estimate=id_estimate,
            requires_ac_prompt=requires_ac_prompt,
        )

    def _build_mental_model(
        self,
        intent: str,
        domain: str,
        stack: LanguageStack,
        reference_arch: Optional[str],
    ) -> str:
        model = f"Domain: {domain}\nStack: {stack.value}\nIntent: {intent[:200]}"
        if reference_arch:
            model += f"\nReference architecture: {reference_arch}"
        return model

    def _infer_boundaries(self, intent: str, stack: LanguageStack) -> list[str]:
        """Infer module/service boundaries from the intent."""
        boundaries: list[str] = []

        # Common patterns
        if re.search(r"\bendpoint|route|api\b", intent, re.IGNORECASE):
            boundaries.append("HTTP API layer")
        if re.search(r"\bdatabase|db|persist|storage\b", intent, re.IGNORECASE):
            boundaries.append("Persistence layer")
        if re.search(r"\bauth|authentication|login\b", intent, re.IGNORECASE):
            boundaries.append("Authentication module")
        if re.search(r"\bqueue|worker|job|task\b", intent, re.IGNORECASE):
            boundaries.append("Background job system")

        if not boundaries:
            boundaries.append("Core business logic")

        return boundaries
