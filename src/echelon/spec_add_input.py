"""Controller-owned evidence attachment for parked Phase A spec runs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
from threading import get_ident
from typing import Sequence
from uuid import uuid4

from echelon.product_inputs import (
    ProductInputError,
    attach_product_input_revision,
    parse_input_declaration,
)
from echelon.spec_lifecycle import (
    PhaseAExecutionLock,
    SpecLifecycleLocked,
    SpecRunExecutionLock,
)
from harness.squad_state import SquadStateStore


class SpecAddInputError(RuntimeError):
    """Raised when active-run evidence cannot be appended safely."""


@dataclass(frozen=True)
class SpecAddInputResult:
    run_dir: Path
    attachment_id: str
    added_count: int
    duplicate_count: int
    original_declarations: tuple[dict[str, str], ...]
    attached_declarations: tuple[dict[str, str], ...]
    next_command: str = "echelon spec continue"


def add_input_to_active_run(
    project_root: Path,
    input_values: Sequence[str],
    *,
    command: str = "echelon spec add-input",
) -> SpecAddInputResult:
    """Append declared evidence to the active parked investigation run."""
    root = Path(project_root).resolve()
    declarations = tuple(parse_input_declaration(value) for value in input_values)
    if not declarations:
        raise SpecAddInputError("at least one --input declaration is required")
    run_dir = _find_current_run_dir(root)
    if run_dir is None:
        raise SpecAddInputError("no active squad run found")
    operation_id = f"add-input-{os.getpid()}-{get_ident()}-{uuid4().hex}"
    try:
        with PhaseAExecutionLock.acquire(root, operation_id):
            with SpecRunExecutionLock.acquire(run_dir, operation_id):
                return _add_input_locked(
                    root,
                    run_dir,
                    declarations,
                    command=command,
                )
    except SpecLifecycleLocked as exc:
        raise SpecAddInputError(
            f"cannot add input while execution lease is owned by {exc.operation_id}"
        ) from exc


def _add_input_locked(
    project_root: Path,
    run_dir: Path,
    declarations: Sequence[object],
    *,
    command: str,
) -> SpecAddInputResult:
    store = SquadStateStore(run_dir)
    state = store.load()
    _ensure_eligible_state(state)
    product_inputs = state.get("product_inputs")
    if not isinstance(product_inputs, dict) or not product_inputs:
        raise SpecAddInputError("active run has no Product Input Contract")
    inputs_ref = str(product_inputs.get("inputs_dir") or "").strip()
    if not inputs_ref:
        raise SpecAddInputError("active run Product Input Contract lacks inputs_dir")
    inputs_dir = Path(inputs_ref)
    if not inputs_dir.is_absolute():
        inputs_dir = project_root / inputs_dir
    inputs_dir = inputs_dir.resolve()
    expected_inputs_dir = (run_dir / "inputs").resolve()
    if inputs_dir != expected_inputs_dir:
        raise SpecAddInputError(
            "active run Product Input Contract is not run-local"
        )

    attachment = attach_product_input_revision(
        project_root,
        inputs_dir,
        declarations,  # type: ignore[arg-type]
        command=command,
        evidence_requests=(
            state.get("evidence_requests")
            if isinstance(state.get("evidence_requests"), dict)
            else None
        ),
    )
    original_declarations = tuple(
        {
            "role": str(item.get("role") or ""),
            "location": str(item.get("location") or ""),
        }
        for item in product_inputs.get("declarations", [])
        if isinstance(item, dict)
    )
    attached_declarations = tuple(
        {"role": item.role, "location": item.location}
        for item in declarations  # type: ignore[attr-defined]
    )
    if not attachment.added:
        return SpecAddInputResult(
            run_dir=run_dir,
            attachment_id=attachment.attachment_id,
            added_count=0,
            duplicate_count=len(attachment.duplicates),
            original_declarations=original_declarations,
            attached_declarations=attached_declarations,
        )

    updated = dict(state)
    previous_counts = dict(updated.get("phase_dispatch_counts") or {})
    previous_investigate_count = previous_counts.pop("phase1-investigate", 0)
    updated["phase_dispatch_counts"] = previous_counts
    updated["product_inputs"] = attachment.state_product_inputs(
        project_root,
        product_inputs,
    )
    updated["product_input_attachments"] = attachment.state_attachments(project_root)
    updated["status"] = "running"
    updated["phase"] = "phase1-investigate"
    updated["blocked_reason"] = None
    updated["escalation_question"] = None
    updated["escalation_resolved"] = True
    updated["escalation_resolver"] = command
    updated["add_input_recovery"] = {
        "command": command,
        "attachment_ids": [attachment.attachment_id],
        "previous_blocked_reason": state.get("blocked_reason"),
        "previous_phase1_investigate_dispatch_count": previous_investigate_count,
    }
    store.save(updated)
    return SpecAddInputResult(
        run_dir=run_dir,
        attachment_id=attachment.attachment_id,
        added_count=len(attachment.added),
        duplicate_count=len(attachment.duplicates),
        original_declarations=original_declarations,
        attached_declarations=attached_declarations,
    )


def _ensure_eligible_state(state: dict) -> None:
    if (
        state.get("status") != "blocked"
        or state.get("phase") != "phase1-investigate"
        or state.get("blocked_reason") != "investigation_access_required"
        or state.get("evidence_resolution_status") != "access_required"
    ):
        raise SpecAddInputError(
            "add-input is only available for a parked investigation access checkpoint"
        )


def _find_current_run_dir(project_root: Path) -> Path | None:
    for base_dir in (project_root / "runs", project_root / "squad"):
        current_file = base_dir / ".current"
        if not current_file.exists():
            continue
        run_id = current_file.read_text(encoding="utf-8").strip()
        if not run_id:
            continue
        run_dir = base_dir / run_id
        if (run_dir / "state.json").is_file():
            return run_dir
    candidates = [
        path
        for base_dir in (project_root / "runs", project_root / "squad")
        if base_dir.exists()
        for path in base_dir.iterdir()
        if path.is_dir() and (path / "state.json").is_file()
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: (path / "state.json").stat().st_mtime)
