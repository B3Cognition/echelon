"""A failed documentation operation is settled only by its retained receipts."""

from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from harness.ai_cli_backend import CliRunResult
from harness.delivery_documentation import DeliveryDocumentationRunner
from harness.delivery_slice import DeliverySliceError
from harness.delivery_slice_journal import DeliverySliceJournal
from harness.terminal_documentation_handoff import prove_terminal_documentation_handoff
from tests.unit.test_delivery_documentation import documentation_project
from tests.unit.test_delivery_slice_runner import slice_project


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True,
    ).stdout.strip()


@pytest.fixture
def terminal_handoff_case(documentation_project, tmp_path, request):
    terminal_step = getattr(request, "param", "tech_writer")
    expected_step = "tech_writer" if terminal_step == "ignored_readme" else terminal_step
    def terminal_writer(assignment, payload, _root):
        if assignment["step"] == expected_step:
            payload.update(
                verdict="NEEDS_CONTEXT" if expected_step == "tech_writer" else "BLOCKED",
                summary="need context",
                findings=["source-backed gap"],
            )
        return CliRunResult(0, json.dumps(payload), "", token_usage=7)

    runner, executor, paths = documentation_project(script=terminal_writer)
    source = paths["worktree"]
    spec = paths["spec_dir"]
    build_dir = tmp_path / "runs" / "build-old"
    worktree = build_dir / "worktrees" / "iter-0"
    worktree.parent.mkdir(parents=True)
    shutil.copytree(source, worktree)
    if terminal_step == "ignored_readme":
        (worktree / ".gitignore").write_text("README.md\n")
    _git(worktree, "init", "-q")
    _git(worktree, "config", "user.name", "Test")
    _git(worktree, "config", "user.email", "test@example.invalid")
    _git(worktree, "add", ".")
    _git(worktree, "commit", "-qm", "base")

    run_id = "old-run"
    evidence = build_dir / "state" / "delivery-slices" / hashlib.sha256(
        f"{build_dir.name}:{run_id}".encode(),
    ).hexdigest()
    result = DeliveryDocumentationRunner(executor, runner._project_dir).run(
        **{**paths, "worktree": worktree, "evidence_root": evidence},
        operation_id="docs-op",
        operation_binding=dict(build_id=build_dir.name, delivery_run_id=run_id,
                               spec_id="001-slice", operation_id="docs-op"),
    )
    assert result.reason == f"delivery_documentation_{expected_step}_blocked: need context"
    _git(worktree, "add", "-A")
    if _git(worktree, "status", "--porcelain"):
        _git(worktree, "commit", "-qm", "salvage")
    salvage = _git(worktree, "rev-parse", "HEAD")
    assert _git(worktree, "status", "--porcelain") == ""

    identity = {
        "amendment_id": "001-slice/001", "spec_commit": "a" * 40,
        "target_id": "sources/web", "input_hash": "b" * 64,
    }
    state = {
        "spec_id": "001-slice", "target_id": "sources/web", "build_id": build_dir.name,
        "run_id": run_id,
        "status": "blocked", "termination_reason": "build_blocked",
        "blocked_phase": "implementation", "build_status": "blocked",
        "build_reason": result.reason, "amendment_admission": identity,
        "salvage_commit": salvage,
        "delivery_slice_operation": {
            "id": "docs-op", "kind": "documentation", "progress_applied": False,
            "worktree_path": str(worktree.resolve()),
        },
    }
    state_path = build_dir / "state" / "delivery.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    journal_path = DeliverySliceJournal(evidence, "docs-op").path
    assert journal_path.is_file()
    return state, journal_path, worktree, spec, salvage, build_dir, identity


def test_terminal_writer_receipt_allows_only_handoff_identity(terminal_handoff_case):
    state, journal_path, worktree, spec, candidate, build_dir, identity = terminal_handoff_case
    journal_before = journal_path.read_bytes()
    state_before = (build_dir / "state" / "delivery.json").read_bytes()
    with ExitStack() as locks:
        assert prove_terminal_documentation_handoff(
            state=state, build_dir=build_dir, spec_dir=spec,
            candidate=candidate, amendment_identity=identity, lock_stack=locks,
        ) == ("build-old", "docs-op")
        with pytest.raises(DeliverySliceError, match="delivery_slice_locked"):
            with DeliverySliceJournal(journal_path.parent.parent, "docs-op"):
                pass
    assert journal_path.read_bytes() == journal_before
    assert (build_dir / "state" / "delivery.json").read_bytes() == state_before
    assert _git(worktree, "status", "--porcelain") == ""


@pytest.mark.parametrize("terminal_handoff_case", ["docs_verifier"], indirect=True)
def test_terminal_verifier_blocked_receipt_allows_handoff(terminal_handoff_case):
    assert _prove(terminal_handoff_case) == ("build-old", "docs-op")


def test_copied_terminal_journal_cannot_authorize_other_operation(terminal_handoff_case):
    state, journal_path, _worktree, _spec, _candidate, build_dir, _identity = terminal_handoff_case
    data = json.loads(journal_path.read_text())
    assert data["operation_binding"] == dict(
        build_id=build_dir.name, delivery_run_id=state["run_id"],
        spec_id=state["spec_id"], operation_id="docs-op",
    )
    copied = DeliverySliceJournal(journal_path.parent.parent, "other-op").path
    copied.parent.mkdir(parents=True, exist_ok=True)
    copied.write_bytes(journal_path.read_bytes())
    state["delivery_slice_operation"]["id"] = "other-op"
    (build_dir / "state" / "delivery.json").write_text(json.dumps(state))
    assert _prove(terminal_handoff_case, state=state) is None


@pytest.mark.parametrize("field", ["build_id", "delivery_run_id", "spec_id", "operation_id"])
def test_wrong_terminal_journal_binding_cannot_authorize_handoff(terminal_handoff_case, field):
    _state, journal_path, _worktree, _spec, _candidate, _build, _identity = terminal_handoff_case
    data = json.loads(journal_path.read_text())
    data["operation_binding"][field] += "-other"
    journal_path.write_text(json.dumps(data))
    assert _prove(terminal_handoff_case) is None


@pytest.mark.parametrize("legacy_version", [2, 4])
def test_legacy_terminal_journal_cannot_authorize_handoff(terminal_handoff_case, legacy_version):
    _state, journal_path, _worktree, _spec, _candidate, _build, _identity = terminal_handoff_case
    data = json.loads(journal_path.read_text())
    data["schema_version"] = legacy_version
    data.pop("operation_binding")
    if legacy_version == 2:
        data.pop("rejected_reviews")
    journal_path.write_text(json.dumps(data))
    assert _prove(terminal_handoff_case) is None


def test_unknown_usage_cannot_authorize_handoff(terminal_handoff_case):
    state, journal_path, _worktree, spec, candidate, build_dir, identity = terminal_handoff_case
    data = json.loads(journal_path.read_text())
    data["records"][-1]["token_usage"] = None
    journal_path.write_text(json.dumps(data))
    with ExitStack() as locks:
        assert prove_terminal_documentation_handoff(
            state=state, build_dir=build_dir, spec_dir=spec,
            candidate=candidate, amendment_identity=identity, lock_stack=locks,
        ) is None


def _prove(case, *, state=None, candidate=None, identity=None):
    saved, _journal_path, _worktree, spec, saved_candidate, build_dir, saved_identity = case
    with ExitStack() as locks:
        return prove_terminal_documentation_handoff(
            state=saved if state is None else state, build_dir=build_dir, spec_dir=spec,
            candidate=saved_candidate if candidate is None else candidate,
            amendment_identity=saved_identity if identity is None else identity,
            lock_stack=locks,
        )


@pytest.mark.parametrize("mutation", [
    "missing", "malformed", "pending", "provider_error", "pass", "fail",
    "wrong_build", "wrong_kind", "wrong_operation", "wrong_run", "wrong_reason", "wrong_admission",
    "wrong_salvage", "wrong_candidate", "dirty", "changed_document", "changed_source",
])
def test_unsettled_or_mismatched_receipt_cannot_authorize_handoff(
    terminal_handoff_case, mutation,
):
    state, journal_path, worktree, _spec, candidate, build_dir, identity = terminal_handoff_case
    state = dict(state)
    data = json.loads(journal_path.read_text())
    if mutation == "missing":
        journal_path.unlink()
    elif mutation == "malformed":
        journal_path.write_text("{malformed")
    elif mutation == "pending":
        data["records"][-1].update(result=None, candidate_after=None, token_usage=None)
    elif mutation == "provider_error":
        data["records"][-1].update(
            result=None, candidate_after=None, error="provider exited", token_usage=7,
        )
    elif mutation in {"pass", "fail"}:
        data["records"][-1]["result"]["verdict"] = mutation.upper()
    elif mutation == "wrong_build":
        state["build_id"] = "build-other"
    elif mutation == "wrong_kind":
        state["delivery_slice_operation"] = {
            **state["delivery_slice_operation"], "kind": "task",
        }
    elif mutation == "wrong_operation":
        state["delivery_slice_operation"] = {
            **state["delivery_slice_operation"], "id": "other-operation",
        }
    elif mutation == "wrong_run":
        state["run_id"] = "other-run"
    elif mutation == "wrong_reason":
        state["build_reason"] = "delivery_documentation_tech_writer_blocked: other"
    elif mutation == "wrong_admission":
        state["amendment_admission"] = {**identity, "input_hash": "c" * 64}
    elif mutation == "wrong_salvage":
        state["salvage_commit"] = "c" * 40
    elif mutation == "wrong_candidate":
        candidate = "c" * 40
    elif mutation == "dirty":
        (worktree / "untracked.txt").write_text("not in salvage")
    elif mutation == "changed_document":
        (worktree / "README.md").write_text("changed after receipt")
        _git(worktree, "add", "README.md")
        _git(worktree, "commit", "-qm", "changed document")
        state["salvage_commit"] = candidate = _git(worktree, "rev-parse", "HEAD")
    elif mutation == "changed_source":
        (worktree / "app.py").write_text("changed after receipt")
        _git(worktree, "add", "app.py")
        _git(worktree, "commit", "-qm", "changed source")
        state["salvage_commit"] = candidate = _git(worktree, "rev-parse", "HEAD")
    if mutation in {"pending", "provider_error", "pass", "fail"}:
        journal_path.write_text(json.dumps(data))
    if mutation in {"wrong_build", "wrong_kind", "wrong_operation", "wrong_run", "wrong_reason", "wrong_admission",
                    "wrong_salvage", "changed_document", "changed_source"}:
        (build_dir / "state" / "delivery.json").write_text(json.dumps(state))
    assert _prove(terminal_handoff_case, state=state, candidate=candidate) is None


def test_live_state_owner_cannot_authorize_handoff(terminal_handoff_case):
    _state, _journal, _worktree, _spec, _candidate, build_dir, _identity = terminal_handoff_case
    (build_dir / "state" / "delivery.lock").write_text(f"pid={os.getpid()}\n")
    assert _prove(terminal_handoff_case) is None


def test_locked_journal_cannot_authorize_handoff(terminal_handoff_case):
    _state, journal_path, _worktree, _spec, _candidate, _build, _identity = terminal_handoff_case
    with DeliverySliceJournal(journal_path.parent.parent, "docs-op"):
        assert _prove(terminal_handoff_case) is None


@pytest.mark.parametrize("terminal_handoff_case", ["ignored_readme"], indirect=True)
def test_changed_ignored_readme_cannot_authorize_handoff(terminal_handoff_case):
    _state, _journal, worktree, _spec, _candidate, _build, _identity = terminal_handoff_case
    assert _git(worktree, "status", "--porcelain", "--untracked-files=all") == ""
    assert _prove(terminal_handoff_case) == ("build-old", "docs-op")
    (worktree / "README.md").write_text("changed ignored bytes")
    assert _git(worktree, "status", "--porcelain", "--untracked-files=all") == ""
    assert _prove(terminal_handoff_case) is None
