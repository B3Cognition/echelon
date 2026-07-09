"""Delivery runtime surface policy."""

from __future__ import annotations


DELIVERY_COMMAND_FILES = frozenset(
    {
        "echelon.build.md",
        "echelon.verify-spec.md",
    }
)

DELIVERY_WORKFLOW_PHASE_PREFIXES = (
    "build-",
    "bugfix-",
    "codegen-",
    "codegenlight-",
    "verify-spec-",
)

DELIVERY_WORKFLOW_PHASE_FILES = frozenset(
    {
        "codegen-A-preamble.md",
        "codegen-resume.md",
        "codegenlight-resume.md",
    }
)


def is_delivery_workflow_phase_path(relative_path) -> bool:
    """Return True when a workflow phase file is safe to expose to delivery agents."""
    parts = tuple(relative_path.parts)
    if len(parts) < 3 or parts[:2] != ("workflow", "phases"):
        return True
    if parts[2] == "appendices":
        return True
    name = parts[-1]
    return name in DELIVERY_WORKFLOW_PHASE_FILES or name.startswith(
        DELIVERY_WORKFLOW_PHASE_PREFIXES
    )
