"""Delivery runtime surface policy."""

from __future__ import annotations

from pathlib import Path

import yaml


DELIVERY_COMMAND_FILES = frozenset(
    {
        "echelon.build.md",
        "echelon.verify-spec.md",
    }
)

DELIVERY_EXCLUDED_BASH_FILES = frozenset(
    {
        "belief-freshness-check.sh",
        "finalize-run.sh",
        "journal-append.sh",
        "kb-lock.sh",
        "kb-pending-merge.sh",
        "kb-pending-write.sh",
        "kb-read-init.sh",
        "kb-recover.sh",
        "kb-seed.sh",
        "kb-validate-evolution.sh",
        "kb-write.sh",
        "phase-timing.sh",
        "post-execution-audit.sh",
        "pre-dispatch-gate.sh",
        "prompt-budget.sh",
        "state-backup.sh",
        "validate-journal-entry.sh",
    }
)

DELIVERY_AGENT_DIRS = frozenset(
    {
        "build",
        "control",
    }
)

DELIVERY_BASH_FILES = frozenset(
    {
        "echelon-config-get.sh",
        "endocrine.sh",
        "fix-spa-base.sh",
        "setup-worktree.sh",
        "startup-banner.sh",
        "validate-deploy.sh",
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

DELIVERY_WORKFLOW_DEFINITION_KEYS = frozenset(
    {
        "schema_version",
        "glossary",
        "evidence_hierarchy",
        "conflict_resolution",
        "phases",
        "build",
        "escalation",
        "verify_spec",
        "reopen",
    }
)


def is_delivery_agent_path(relative_path: Path) -> bool:
    """Return True when an agent prompt path is safe to expose to delivery agents."""
    parts = tuple(relative_path.parts)
    if len(parts) < 2 or parts[0] != "agents":
        return True
    return parts[1] in DELIVERY_AGENT_DIRS


def is_delivery_bash_path(relative_path: Path) -> bool:
    """Return True when a top-level bash helper is safe to expose to delivery."""
    parts = tuple(relative_path.parts)
    if len(parts) < 3 or parts[:2] != ("scripts", "bash"):
        return True
    if len(parts) == 3:
        return parts[2] in DELIVERY_BASH_FILES
    return False


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


def prune_delivery_workflow_definition(definition_path: Path) -> None:
    """Prune copied workflow metadata to delivery-safe sections and phases."""
    if not definition_path.exists():
        return
    try:
        data = yaml.safe_load(definition_path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return
    if not isinstance(data, dict):
        return

    pruned = {
        key: value
        for key, value in data.items()
        if key in DELIVERY_WORKFLOW_DEFINITION_KEYS
    }
    phases = pruned.get("phases")
    if isinstance(phases, list):
        pruned["phases"] = [
            phase
            for phase in phases
            if _phase_node_is_delivery_safe(phase)
        ]
    definition_path.write_text(
        yaml.safe_dump(pruned, sort_keys=False),
        encoding="utf-8",
    )


def _phase_node_is_delivery_safe(phase: object) -> bool:
    if not isinstance(phase, dict):
        return False
    spec_file = phase.get("spec_file")
    if isinstance(spec_file, str) and spec_file.strip():
        return is_delivery_workflow_phase_path(Path(spec_file))
    phase_id = str(phase.get("id") or "").strip()
    if not phase_id:
        return False
    return is_delivery_workflow_phase_path(
        Path("workflow") / "phases" / f"{phase_id}.md"
    )
