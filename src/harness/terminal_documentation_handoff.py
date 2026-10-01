"""Receipt-backed admission for a settled failed documentation operation."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import re
import subprocess

from harness.delivery_documentation import (
    _documentation_candidate_fingerprint, _source_fingerprint,
)
from harness.delivery_documentation_contract import validate_journal
from harness.delivery_slice import DeliverySliceError
from harness.delivery_slice_journal import DeliverySliceJournal
from harness.state import state_lock_owner_is_alive


_COMMIT = re.compile(r"[0-9a-f]{40}\Z")


def _git(worktree: Path, *args: str) -> str | None:
    completed = subprocess.run(
        ["git", *args], cwd=worktree, capture_output=True, text=True,
        timeout=30, check=False,
    )
    return completed.stdout.strip() if completed.returncode == 0 else None


def prove_terminal_documentation_handoff(
    *, state: Mapping[str, object], build_dir: Path, spec_dir: Path,
    candidate: str, amendment_identity: Mapping[str, str], lock_stack: ExitStack,
) -> tuple[str, str] | None:
    """Prove a failed docs dispatch is terminal without accepting its output.

    The caller holds ``lock_stack`` through fresh-build marker reservation.
    Failure grants no lineage exemption; old receipts remain unchanged.
    """
    try:
        operation = state.get("delivery_slice_operation")
        run_id = state.get("run_id")
        build_id = build_dir.name
        spec_id = amendment_identity.get("amendment_id", "").partition("/")[0]
        if (
            state.get("build_id") != build_id
            or state.get("spec_id") != spec_id
            or state.get("target_id") != amendment_identity.get("target_id")
            or state.get("amendment_admission") != dict(amendment_identity)
            or state.get("status") != "blocked"
            or state.get("termination_reason") != "build_blocked"
            or state.get("blocked_phase") != "implementation"
            or state.get("build_status") != "blocked"
            or not isinstance(run_id, str) or not run_id
            or not isinstance(operation, Mapping)
            or operation.get("kind") != "documentation"
            or operation.get("progress_applied") is not False
        ):
            return None
        operation_id = operation.get("id")
        if not isinstance(operation_id, str) or not operation_id:
            return None

        state_path = build_dir / "state" / "delivery.json"
        if state_lock_owner_is_alive(state_path):
            return None
        persisted = json.loads(state_path.read_text(encoding="utf-8"))
        if (not isinstance(persisted, dict)
                or any(state.get(key) != value for key, value in persisted.items())
                or set(state).difference(persisted, {"build_id", "target_id"})):
            return None

        candidate_path = operation.get("worktree_path")
        if not isinstance(candidate_path, str):
            return None
        worktree = Path(candidate_path)
        worktrees_root = build_dir / "worktrees"
        if (not worktree.is_absolute() or worktree.is_symlink()
                or worktree.parent.resolve(strict=True) != worktrees_root.resolve(strict=True)
                or not worktree.is_dir()
                or _git(worktree, "rev-parse", "--show-toplevel") != str(worktree.resolve())):
            return None
        salvage = state.get("salvage_commit")
        if (not isinstance(candidate, str) or _COMMIT.fullmatch(candidate) is None
                or not isinstance(salvage, str) or candidate != salvage
                or _git(worktree, "status", "--porcelain", "--untracked-files=all") != ""
                or _git(worktree, "rev-parse", "HEAD") != candidate):
            return None

        evidence_root = build_dir / "state" / "delivery-slices" / hashlib.sha256(
            f"{build_id}:{run_id}".encode(),
        ).hexdigest()
        journal = DeliverySliceJournal(evidence_root, operation_id, validator=validate_journal)
        if not journal.path.is_file() or journal.path.is_symlink():
            return None
        data = lock_stack.enter_context(journal).load(required=True)
        expected_binding = {
            "build_id": build_id,
            "delivery_run_id": run_id,
            "spec_id": spec_id,
            "operation_id": operation_id,
        }
        if data["schema_version"] != 5 or data["operation_binding"] != expected_binding:
            return None
        records = data["records"]
        if not records or data["publication"] is not None:
            return None
        last = records[-1]
        result = last["result"]
        step = last["assignment"]["step"]
        if (last["error"] is not None or not isinstance(result, dict)
                or result.get("verdict") not in (
                    {"BLOCKED", "NEEDS_CONTEXT"} if step == "tech_writer" else {"BLOCKED"}
                )
                or any(type(record["token_usage"]) is not int
                       for record in [*records, *data.get("rejected_reviews", [])])
                or state.get("build_reason") !=
                    f"delivery_documentation_{step}_blocked: {result.get('summary')}"):
            return None
        if (data["source_fingerprint"] != _source_fingerprint(worktree, spec_dir)
                or last["candidate_after"] != _documentation_candidate_fingerprint(
                    worktree, spec_dir)):
            return None
        return build_id, operation_id
    except (DeliverySliceError, OSError, ValueError, TypeError, KeyError,
            subprocess.SubprocessError):
        return None
