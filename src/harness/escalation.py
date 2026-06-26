"""EscalationHandler — escalation file writing and resume protocol.

Per data-model Escalation entity:
  question, context, options_considered, recommended_answer, category,
  spec_id, strategy_id, timestamp, last_verify_result.

Per FR-LOOP-005: write escalation .md file, print terminal banner,
  support resume with answer.
"""

from __future__ import annotations

import logging
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def print_escalation_sticky_banner(spec_id: str, strategy_id: str, esc_file: str) -> None:
    """Print a structured blocked banner to stderr when an escalation is still pending."""
    from echelon.ui import banner as _banner
    _banner(
        "HARNESS — ESCALATION PENDING",
        [
            ("spec", spec_id),
            ("strategy", strategy_id),
            ("escalation", esc_file),
            ("answer with", "/speckit-harness-resume"),
            ("discard with", f"echelon harness run {spec_id} --reset"),
        ],
        file=sys.stderr,
    )


VALID_CATEGORIES = {
    "same_failure_repeat",
    "spec_guard_violation",
    "why_quality_regression",
    "budget_exhaustion",
    "infra_failure",
    "no_progress",
}


class InvalidCategoryError(Exception):
    """Raised when an invalid escalation category is used."""


class EscalationHandler:
    """Handles escalation protocol for the ralph-loop.

    When the ralph-loop hits a blocker:
    1. Write escalation file with question/context
    2. Print terminal banner to stderr
    3. Return file path for state storage
    4. Support resume via check_resume/resume methods
    """

    def __init__(self, base_dir: str) -> None:
        """Initialize EscalationHandler.

        Args:
            base_dir: Base directory for escalation files.
                      Files go to {base_dir}/escalations/
        """
        self.base_dir = Path(base_dir)
        self.escalations_dir = self.base_dir / "escalations"

    def _ensure_dir(self) -> None:
        """Create escalation directory if needed."""
        self.escalations_dir.mkdir(parents=True, exist_ok=True)

    def escalate(
        self,
        spec_id: str,
        strategy_id: str,
        category: str,
        context: str,
        *,
        question: str = "",
        options_considered: Optional[List[str]] = None,
        recommended_answer: Optional[str] = None,
        last_verify_result: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Write escalation file and return its path.

        Args:
            spec_id: Spec being executed.
            strategy_id: Strategy variant.
            category: Escalation category (must be valid).
            context: Current state description.
            question: What decision is needed from the human.
            options_considered: What the loop considered before escalating.
            recommended_answer: Optional suggestion from the loop.
            last_verify_result: Most recent verify output as dict.

        Returns:
            Path to the escalation file.

        Raises:
            InvalidCategoryError: If category is not valid.
        """
        if category not in VALID_CATEGORIES:
            raise InvalidCategoryError(
                f"Invalid escalation category '{category}'. "
                f"Must be one of: {sorted(VALID_CATEGORIES)}"
            )

        self._ensure_dir()

        timestamp = datetime.now(timezone.utc)
        timestamp_str = timestamp.strftime("%Y%m%dT%H%M%SZ")
        filename = f"{spec_id}-{strategy_id}-{timestamp_str}.md"
        filepath = self.escalations_dir / filename

        if not question:
            question = _default_question(category, context)

        if options_considered is None:
            options_considered = []

        # Build escalation file content
        content = _render_escalation_file(
            spec_id=spec_id,
            strategy_id=strategy_id,
            category=category,
            question=question,
            context=context,
            options_considered=options_considered,
            recommended_answer=recommended_answer,
            last_verify_result=last_verify_result,
            timestamp=timestamp.isoformat(),
        )

        filepath.write_text(content, encoding="utf-8")

        # Print terminal banner to stderr
        _print_banner(category, question, context, file=sys.stderr)

        logger.info("Escalation file written: %s", filepath)
        return str(filepath)

    def check_resume(self, escalation_file: str) -> Optional[str]:
        """Check if a resume answer has been provided.

        Looks for a `## Answer` section in the escalation file.

        Args:
            escalation_file: Path to the escalation file.

        Returns:
            Answer text if found, None otherwise.
        """
        path = Path(escalation_file)
        if not path.exists():
            return None

        text = path.read_text(encoding="utf-8")
        # Match "## Answer" only at start of a line (not inline references)
        marker = "\n## Answer"
        idx = text.find(marker)
        if idx == -1:
            # Also check if file starts with it (unlikely but correct)
            if text.startswith("## Answer"):
                idx = 0
            else:
                return None

        answer_start = idx + len(marker) if idx > 0 else len("## Answer")
        answer = text[answer_start:]
        next_heading = answer.find("\n## ")
        if next_heading != -1:
            answer = answer[:next_heading]
        answer = answer.strip()
        if not answer:
            return None
        return answer

    def resume(self, escalation_file: str, answer: str) -> None:
        """Record resume answer by appending to escalation file.

        Args:
            escalation_file: Path to the escalation file.
            answer: The answer text to append.
        """
        path = Path(escalation_file)
        existing = path.read_text(encoding="utf-8")

        # Append answer section
        answered_at = datetime.now(timezone.utc).isoformat()
        metadata = {
            "schema_version": 1,
            "answer_type": "free_text",
            "answer": answer,
            "answered_at": answered_at,
            "answered_by": "user",
            "source": "speckit-harness-resume",
        }
        resume_content = (
            f"\n\n## Answer\n\n"
            f"{answer}\n\n"
            f"*Answered at: {answered_at}*\n\n"
            f"## Resume Metadata\n\n"
            f"```json\n"
            f"{json.dumps(metadata, indent=2)}\n"
            f"```\n"
        )
        path.write_text(existing + resume_content, encoding="utf-8")
        logger.info("Resume answer recorded in: %s", escalation_file)


# --- Private helpers ---


def _default_question(category: str, context: str) -> str:
    """Generate a default question based on category."""
    questions = {
        "same_failure_repeat": (
            "The same failure has occurred 3 or more times consecutively. "
            "How should the loop proceed?"
        ),
        "spec_guard_violation": (
            "A spec guard violation was detected. "
            "The generated code violates the specification or constitution. "
            "What should be changed?"
        ),
        "why_quality_regression": (
            "Understanding quality has regressed. "
            "How should the spec or approach be adjusted?"
        ),
        "budget_exhaustion": (
            "The token budget is nearly exhausted. "
            "Should the loop continue with a higher budget, "
            "or accept current results?"
        ),
        "infra_failure": (
            "An infrastructure failure occurred (Docker, git, network). "
            "How should the loop recover?"
        ),
    }
    return questions.get(category, f"Escalation in category '{category}': {context}")


def _render_escalation_file(
    *,
    spec_id: str,
    strategy_id: str,
    category: str,
    question: str,
    context: str,
    options_considered: List[str],
    recommended_answer: Optional[str],
    last_verify_result: Optional[Dict[str, Any]],
    timestamp: str,
) -> str:
    """Render escalation file content in markdown format."""
    lines = [
        f"# Escalation: {category}",
        "",
        f"**Spec:** {spec_id}",
        f"**Strategy:** {strategy_id}",
        f"**Category:** {category}",
        f"**Timestamp:** {timestamp}",
        "",
        "---",
        "",
        "## Question",
        "",
        question,
        "",
        "## Context",
        "",
        context,
        "",
    ]

    if options_considered:
        lines.append("## Options Considered")
        lines.append("")
        for opt in options_considered:
            lines.append(f"- {opt}")
        lines.append("")

    if recommended_answer:
        lines.append("## Recommended Answer")
        lines.append("")
        lines.append(recommended_answer)
        lines.append("")

    metadata: Dict[str, Any] = {
        "schema_version": 1,
        "answer_type": "free_text",
        "question": question,
        "category": category,
        "spec_id": spec_id,
        "strategy_id": strategy_id,
        "blocked_at": timestamp,
    }
    if options_considered:
        metadata["options_considered"] = options_considered
    if recommended_answer:
        metadata["recommended_answer"] = recommended_answer
        metadata["default_answer"] = recommended_answer

    lines.append("## Decision Metadata")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(metadata, indent=2))
    lines.append("```")
    lines.append("")

    if last_verify_result:
        lines.append("## Last Verify Result")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(last_verify_result, indent=2))
        lines.append("```")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("*To resume, run `/speckit-harness-resume` with your answer,")
    lines.append("or append a `## Answer` section to this file.*")
    lines.append("")

    return "\n".join(lines)


def _print_banner(
    category: str,
    question: str,
    context: str,
    *,
    file: Any = None,
    width: int = 80,
) -> None:
    """Print escalation terminal banner."""
    from echelon.ui import banner as _banner
    if file is None:
        file = sys.stderr
    _banner(
        f"HARNESS — BLOCKED ({category})",
        [
            ("question", question),
            ("context", context[:200] + ("..." if len(context) > 200 else "")),
            ("next step", "Run /speckit-harness-resume with your answer"),
        ],
        file=file,
    )
