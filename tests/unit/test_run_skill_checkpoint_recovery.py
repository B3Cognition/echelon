from __future__ import annotations

import json
import os
import subprocess
from contextlib import ExitStack
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from harness.ai_cli_backend import CliRunResult
from harness.delivery_documentation import DeliveryDocumentationRunner
from harness.delivery_slice import DeliverySliceError
from harness.delivery_slice_journal import DeliverySliceJournal
from harness.paths import current_build_marker
from harness.skills.run_skill import (
    RunContextError,
    _amended_delivery_completed_tasks,
    _fresh_delivery_baseline,
    _fresh_delivery_completed_tasks,
    _fresh_delivery_repair_task_id,
)
from tests.unit.test_delivery_documentation import documentation_project
from tests.unit.test_delivery_slice_runner import slice_project


def test_amended_admission_restarts_after_terminal_documentation(
    tmp_path: Path, documentation_project, monkeypatch,
) -> None:
    from echelon.runnability_amendment import prepare_runnability_owner
    from echelon.runnability_amendment_transaction import promote_runnability_owner
    from harness.skills.run_skill import _execute_delivery_run
    from harness.task_progress import checkpoint_input_hash
    from tests.unit.test_runnability_amendment import _git, _repo

    repo = _repo(tmp_path)
    spec = repo / "specs/004-demo"
    target_repo = repo / "apps/web"
    _git(target_repo, "init", "-b", "main")
    _git(target_repo, "config", "user.name", "Test User")
    _git(target_repo, "config", "user.email", "test@example.com")
    _git(target_repo, "add", "package.json")
    _git(target_repo, "commit", "-m", "accepted target task")
    accepted = _git(target_repo, "rev-parse", "HEAD")
    tasks = spec / "tasks.md"
    tasks.write_text(tasks.read_text().replace("- [ ] T-001", "- [x] T-001")
                     .replace("**Status:** PENDING", "**Status:** DONE"))
    old_hash = checkpoint_input_hash(spec)
    harness_root = repo / "runs/targets/web"
    accepted_state = harness_root / "runs/build-old/state/delivery.json"
    accepted_state.parent.mkdir(parents=True)
    accepted_state.write_text(json.dumps({
        "spec_id": "004-demo", "status": "interrupted",
        "checkpoint_commits": [{"commit": accepted, "task_ids": ["T-001"],
                                "checkpoint_input_hash": old_hash}],
    }))
    prepared = prepare_runnability_owner(repo, "004-demo")
    promote_runnability_owner(repo, str(prepared["amendment_id"]))

    build_dir = harness_root / "runs/build-docs"
    worktree = build_dir / "worktrees/iter-0"
    worktree.parent.mkdir(parents=True)
    _git(repo, "clone", "-q", str(target_repo), str(worktree))
    _git(worktree, "config", "user.name", "Test User")
    _git(worktree, "config", "user.email", "test@example.com")

    class GitOps:
        @staticmethod
        def commit_is_ancestor(ancestor: str, descendant: str) -> bool:
            return subprocess.run(
                ["git", "merge-base", "--is-ancestor", ancestor, descendant],
                cwd=worktree, check=False,
            ).returncode == 0

    intent = SimpleNamespace(spec_id="004-demo", reset=False, resume=False)
    config = SimpleNamespace(target_repo=str(target_repo))
    def admit(candidate, *, handoff_locks=None):
        return _amended_delivery_completed_tasks(
            workspace_root=repo, harness_root=harness_root, spec_dir=spec,
            intent=intent, candidate=candidate, gitops=GitOps(), config=config,
            handoff_locks=handoff_locks,
        )
    identity = admit(accepted).durable_identity()

    def blocked_writer(assignment, payload, _root):
        if assignment["step"] == "tech_writer":
            payload.update(verdict="NEEDS_CONTEXT", summary="source gap",
                           findings=["source-backed gap"])
        return CliRunResult(0, json.dumps(payload), "", token_usage=7)

    fixture_runner, executor, _fixture_paths = documentation_project(script=blocked_writer)
    run_id = "old-run"
    evidence_root = build_dir / "state/delivery-slices" / hashlib.sha256(
        f"{build_dir.name}:{run_id}".encode(),
    ).hexdigest()
    result = DeliveryDocumentationRunner(executor, fixture_runner._project_dir).run(
        worktree=worktree, spec_dir=spec, evidence_root=evidence_root,
        allowed_task_ids={"T-001"}, changed_files=["package.json"],
        operation_id="docs-op",
    )
    assert result.reason == "delivery_documentation_tech_writer_blocked: source gap"
    _git(worktree, "add", "-A")
    _git(worktree, "commit", "-m", "retained docs candidate")
    salvage = _git(worktree, "rev-parse", "HEAD")
    old_state = {
        "spec_id": "004-demo", "run_id": run_id,
        "status": "blocked", "termination_reason": "build_blocked",
        "blocked_phase": "implementation", "build_status": "blocked",
        "build_reason": result.reason, "amendment_admission": identity,
        "salvage_commit": salvage, "checkpoint_commits": [],
        "delivery_slice_operation": {
            "id": "docs-op", "kind": "documentation", "progress_applied": False,
            "worktree_path": str(worktree.resolve()),
        },
    }
    old_state_path = build_dir / "state/delivery.json"
    old_state_path.write_text(json.dumps(old_state))
    old_bytes = old_state_path.read_bytes()
    journal_path = DeliverySliceJournal(evidence_root, "docs-op").path
    journal_bytes = journal_path.read_bytes()

    with ExitStack() as locks:
        admitted = admit(salvage, handoff_locks=locks)
        assert admitted.task_ids == ("T-001",)
        with pytest.raises(DeliverySliceError, match="delivery_slice_locked"):
            with DeliverySliceJournal(evidence_root, "docs-op"):
                pass
    with DeliverySliceJournal(evidence_root, "docs-op"):
        pass
    assert old_state_path.read_bytes() == old_bytes
    assert journal_path.read_bytes() == journal_bytes

    accepted_bytes = accepted_state.read_bytes()
    accepted_without_checkpoint = json.loads(accepted_bytes)
    accepted_without_checkpoint["checkpoint_commits"] = []
    accepted_state.write_text(json.dumps(accepted_without_checkpoint))
    with pytest.raises(RunContextError, match="unproven task progress: T-001"):
        admit(salvage)
    accepted_state.write_bytes(accepted_bytes)

    monkeypatch.setattr("harness.skills.run_skill._fresh_delivery_baseline", lambda *_: salvage)
    for kind in ("task", "unknown"):
        old_state["delivery_slice_operation"]["kind"] = kind
        old_state_path.write_text(json.dumps(old_state))
        with pytest.raises(RunContextError, match="pending Delivery operation"):
            _execute_delivery_run(
                intent=intent, provider=object(), gitops=GitOps(),
                harness_root=harness_root, workspace_root=repo, spec_dir=spec,
                config=config, resume_build_id=None,
                summary_command="echelon delivery run",
            )
        assert not current_build_marker(harness_root, "004-demo").exists()
    old_state["delivery_slice_operation"]["kind"] = "documentation"
    old_state_path.write_bytes(old_bytes)

    class ReachedController(Exception):
        pass
    real_marker = current_build_marker
    class GuardedMarker:
        def write_text(self, value):
            with pytest.raises(DeliverySliceError, match="delivery_slice_locked"):
                with DeliverySliceJournal(evidence_root, "docs-op"):
                    pass
            return real_marker(harness_root, "004-demo").write_text(value)
    monkeypatch.setattr("harness.skills.run_skill.current_build_marker",
                        lambda *_: GuardedMarker())
    def controller_after_marker(**kwargs):
        assert current_build_marker(harness_root, "004-demo").is_file()
        assert kwargs["fresh_completed_task_ids"] == ("T-001",)
        with DeliverySliceJournal(evidence_root, "docs-op"):
            pass
        raise ReachedController
    monkeypatch.setattr("harness.skills.run_skill.DeliveryController", controller_after_marker)
    with pytest.raises(ReachedController):
        _execute_delivery_run(
            intent=intent, provider=object(), gitops=GitOps(),
            harness_root=harness_root, workspace_root=repo, spec_dir=spec,
            config=config, resume_build_id=None, summary_command="echelon delivery run",
        )
    assert old_state_path.read_bytes() == old_bytes
    assert journal_path.read_bytes() == journal_bytes



def test_amended_admission_uses_only_real_target_checkpoint(tmp_path: Path) -> None:
    from echelon.runnability_amendment import prepare_runnability_owner
    from echelon.runnability_amendment_transaction import promote_runnability_owner
    from harness.task_progress import checkpoint_input_hash
    from tests.unit.test_runnability_amendment import _git, _repo

    repo = _repo(tmp_path)
    spec = repo / "specs/004-demo"
    target_repo = repo / "apps/web"
    _git(target_repo, "init", "-b", "main")
    _git(target_repo, "config", "user.name", "Test User")
    _git(target_repo, "config", "user.email", "test@example.com")
    _git(target_repo, "add", "package.json")
    _git(target_repo, "commit", "-m", "target candidate")
    tasks = spec / "tasks.md"
    tasks.write_text(tasks.read_text().replace("- [ ] T-001", "- [x] T-001")
                     .replace("**Status:** PENDING", "**Status:** DONE"))
    candidate = _git(target_repo, "rev-parse", "HEAD")
    harness_root = repo / "runs/targets/web"
    state_path = harness_root / "runs/build-old/state/delivery.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(json.dumps({
        "spec_id": "004-demo", "status": "interrupted",
        "checkpoint_commits": [{
            "commit": candidate, "task_ids": ["T-001"],
            "checkpoint_input_hash": checkpoint_input_hash(spec),
        }],
    }))
    prepared = prepare_runnability_owner(repo, "004-demo")
    promote_runnability_owner(repo, str(prepared["amendment_id"]))

    class GitOps:
        @staticmethod
        def commit_is_ancestor(ancestor: str, descendant: str) -> bool:
            return subprocess.run(
                ["git", "merge-base", "--is-ancestor", ancestor, descendant],
                cwd=target_repo, check=False,
            ).returncode == 0

    intent = SimpleNamespace(spec_id="004-demo", reset=False, resume=False)
    config = SimpleNamespace(target_repo=str(repo / "apps/web"))
    admitted = lambda: _amended_delivery_completed_tasks(
        workspace_root=repo, harness_root=harness_root, spec_dir=spec,
        intent=intent, candidate=candidate, gitops=GitOps(), config=config,
    )
    assert admitted().task_ids == ("T-001",)
    config.target_repo = "apps/web"
    assert admitted().task_ids == ("T-001",)
    projected_tasks = tasks.read_bytes()
    amendment_identity = admitted().durable_identity()

    admitted_state_path = harness_root / "runs/build-amended/state/delivery.json"
    admitted_state_path.parent.mkdir(parents=True)
    admitted_state_path.write_text(json.dumps({
        "spec_id": "004-demo", "status": "interrupted",
        "amendment_admission": amendment_identity,
    }))
    assert _amended_delivery_completed_tasks(
        workspace_root=repo, harness_root=harness_root, spec_dir=spec,
        intent=SimpleNamespace(spec_id="004-demo", reset=False, resume=True),
        candidate=None, gitops=GitOps(), config=config,
        resume_build_id="build-amended",
    ).task_ids == ()
    with pytest.raises(RunContextError, match="resume build was not admitted"):
        _amended_delivery_completed_tasks(
            workspace_root=repo, harness_root=harness_root, spec_dir=spec,
            intent=SimpleNamespace(spec_id="004-demo", reset=False, resume=True),
            candidate=None, gitops=GitOps(), config=config,
            resume_build_id="build-old",
        )
    _git(target_repo, "commit", "--allow-empty", "-m", "accepted amended task")
    descendant = _git(target_repo, "rev-parse", "HEAD")
    tasks.write_text(tasks.read_text().replace("- [ ] T-002", "- [x] T-002")
                     .replace("**Status:** PENDING", "**Status:** DONE"))
    with pytest.raises(RunContextError, match="unproven task progress: T-002"):
        _amended_delivery_completed_tasks(
            workspace_root=repo, harness_root=harness_root, spec_dir=spec,
            intent=intent, candidate=descendant, gitops=GitOps(), config=config,
        )
    admitted_state_path.write_text(json.dumps({
        "spec_id": "004-demo", "status": "interrupted",
        "amendment_admission": amendment_identity,
        "checkpoint_commits": [{
            "commit": descendant, "task_ids": ["T-002"],
            "checkpoint_input_hash": checkpoint_input_hash(spec),
        }],
    }))
    assert _amended_delivery_completed_tasks(
        workspace_root=repo, harness_root=harness_root, spec_dir=spec,
        intent=intent, candidate=descendant, gitops=GitOps(), config=config,
    ).task_ids == ("T-001", "T-002")
    tasks.write_bytes(projected_tasks)
    admitted_state_path.unlink()

    state = json.loads(state_path.read_text())
    state["delivery_slice_operation"] = {"id": "sealed-original", "progress_applied": False}
    state_path.write_text(json.dumps(state))
    with pytest.raises(RunContextError, match="pending Delivery operation"):
        admitted()
    from harness.skills.run_skill import _execute_delivery_run
    with pytest.raises(RunContextError, match="pending Delivery operation"):
        _execute_delivery_run(
            intent=intent, provider=object(), gitops=GitOps(),
            harness_root=harness_root, workspace_root=repo, spec_dir=spec,
            config=config, resume_build_id=None, summary_command="echelon delivery run",
        )
    assert not current_build_marker(harness_root, "004-demo").exists()
    state.pop("delivery_slice_operation")
    state["checkpoint_commits"] = []
    state_path.write_text(json.dumps(state))
    with pytest.raises(RunContextError, match="unproven task progress"):
        admitted()

    amendment_state = Path(str(prepared["state_path"]))
    amended = json.loads(amendment_state.read_text())
    amended["old_task_ids"] = ["T-999"]
    amendment_state.write_text(json.dumps(amended))
    with pytest.raises(RunContextError, match="older task definitions"):
        admitted()
    amended["old_task_ids"] = ["T-001"]
    amended["spec_id"] = "foreign-spec"
    amendment_state.write_text(json.dumps(amended))
    with pytest.raises(RunContextError, match="identity"):
        admitted()


def test_unrelated_amendment_leaves_exact_hash_delivery_path_unchanged(tmp_path: Path) -> None:
    from tests.unit.test_runnability_amendment import _git, _repo

    repo = _repo(tmp_path)
    generic = repo / ".git/echelon/amendments/004-demo/001/state.json"
    generic.parent.mkdir(parents=True)
    generic.write_text(json.dumps({
        "kind": "product_input", "spec_id": "004-demo", "status": "prepared",
    }))
    _git(repo, "switch", "main")
    _git(repo, "branch", "-D", "004-demo")
    spec = repo / "specs/004-demo"
    intent = SimpleNamespace(spec_id="004-demo", reset=False, resume=False)

    assert _amended_delivery_completed_tasks(
        workspace_root=repo, harness_root=repo / "runs/targets/web",
        spec_dir=spec, intent=intent, candidate=None, gitops=object(),
        config=SimpleNamespace(target_repo=str(repo / "apps/web")),
    ) is None


def _write_state(
    root: Path,
    build_id: str,
    *,
    status: str,
    checkpoint: str | None = None,
    termination_reason: str | None = None,
) -> Path:
    state_dir = root / "runs" / build_id / "state"
    state_dir.mkdir(parents=True)
    payload: dict[str, object] = {
        "spec_id": "012",
        "status": status,
        "termination_reason": termination_reason,
    }
    if checkpoint is not None:
        payload["checkpoint_commits"] = [{"commit": checkpoint}]
    path = state_dir / "delivery.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _intent() -> SimpleNamespace:
    return SimpleNamespace(
        spec_id="012",
        reset=False,
        resume=False,
    )


@pytest.mark.parametrize("spec_id", ["999", "", None])
def test_recovery_ignores_foreign_or_unbound_spec(tmp_path, spec_id):
    path = _write_state(tmp_path, "build-other", status="blocked", checkpoint="a" * 40, termination_reason="build_blocked")
    payload = json.loads(path.read_text())
    payload["spec_id"] = spec_id
    path.write_text(json.dumps(payload))
    assert _fresh_delivery_baseline(tmp_path, _intent()) is None


def test_legacy_checkpoint_does_not_restore_unbound_task_completion(tmp_path):
    path = _write_state(tmp_path, "build-old", status="interrupted", checkpoint="a" * 40)
    payload = json.loads(path.read_text())
    payload["checkpoint_commits"][0]["task_ids"] = ["T-001"]
    path.write_text(json.dumps(payload))
    gitops = SimpleNamespace(commit_is_ancestor=lambda *args: True)
    assert _fresh_delivery_completed_tasks(tmp_path, _intent(), "a" * 40, gitops) == ()


def test_checkpoint_progress_requires_unchanged_definitions(tmp_path):
    from harness.task_progress import checkpoint_input_hash

    spec = tmp_path / "specs/012"
    spec.mkdir(parents=True)
    (spec / "spec.md").write_text("Original requirement\n")
    (spec / "tasks.md").write_text("- [ ] T-001 implement original\n  **Status:** PENDING\n  - [ ] original acceptance\n")
    digest = checkpoint_input_hash(spec)
    path = _write_state(tmp_path, "build-old", status="interrupted", checkpoint="a" * 40)
    payload = json.loads(path.read_text())
    payload["checkpoint_commits"][0].update(task_ids=["T-001"], checkpoint_input_hash=digest)
    path.write_text(json.dumps(payload))
    gitops = SimpleNamespace(commit_is_ancestor=lambda *args: True)
    def recover():
        return _fresh_delivery_completed_tasks(tmp_path, _intent(), "a" * 40, gitops, spec_dir=spec)
    assert recover() == ("T-001",)
    (spec / "tasks.md").write_text("- [x] T-001 implement original\n  **Status:** DONE\n  - [x] original acceptance\n")
    assert recover() == ("T-001",)
    (spec / "spec.md").write_text("Changed requirement\n")
    assert recover() == ()
    (spec / "spec.md").write_text("Original requirement\n")
    (spec / "tasks.md").write_text("- [ ] T-001 implement original\n  **Status:** DEFERRED\n  - [ ] original acceptance\n")
    assert recover() == ()
    (spec / "tasks.md").write_text("- [ ] T-001 implement DIFFERENT\n  **Status:** PENDING\n")
    assert recover() == ()


@pytest.mark.unit
def test_new_budget_prefers_checkpoint_from_dead_running_delivery(tmp_path: Path) -> None:
    older = "a" * 40
    newest = "b" * 40
    _write_state(
        tmp_path,
        "build-older",
        status="blocked",
        checkpoint=older,
        termination_reason="outer_cap",
    )
    latest = _write_state(
        tmp_path,
        "build-newest",
        status="running",
        checkpoint=newest,
    )
    latest.with_suffix(".lock").write_text(
        "pid=999999999\ntimestamp=now\nrun_id=dead\n",
        encoding="utf-8",
    )
    marker = current_build_marker(tmp_path, "012")
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("build-newest", encoding="utf-8")

    assert _fresh_delivery_baseline(tmp_path, _intent()) == newest


@pytest.mark.unit
def test_new_budget_refuses_to_compete_with_live_running_delivery(tmp_path: Path) -> None:
    latest = _write_state(
        tmp_path,
        "build-newest",
        status="running",
        checkpoint="b" * 40,
    )
    latest.with_suffix(".lock").write_text(
        f"pid={os.getpid()}\ntimestamp=now\nrun_id=live\n",
        encoding="utf-8",
    )
    marker = current_build_marker(tmp_path, "012")
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("build-newest", encoding="utf-8")

    with pytest.raises(RunContextError, match="already active"):
        _fresh_delivery_baseline(tmp_path, _intent())


@pytest.mark.unit
def test_new_budget_refuses_dirty_interrupted_candidate_without_retention(
    tmp_path: Path,
) -> None:
    """Do not silently replace a loose interrupted candidate with an older checkpoint."""
    _write_state(
        tmp_path, "build-older", status="blocked", checkpoint="a" * 40,
        termination_reason="outer_cap",
    )
    latest = _write_state(
        tmp_path, "build-newest", status="interrupted",
        termination_reason="user_cancel",
    )
    worktree = latest.parent.parent / "worktrees" / "iter-0"
    worktree.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=worktree, check=True)
    (worktree / "app.ts").write_text("initial\n", encoding="utf-8")
    subprocess.run(["git", "add", "app.ts"], cwd=worktree, check=True)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
         "commit", "-qm", "initial"],
        cwd=worktree, check=True,
    )
    (worktree / "app.ts").write_text("unretained candidate\n", encoding="utf-8")
    state = json.loads(latest.read_text(encoding="utf-8"))
    state["delivery_slice_operation"] = {
        "id": "slice-1", "worktree_path": str(worktree), "progress_applied": False,
    }
    latest.write_text(json.dumps(state), encoding="utf-8")
    marker = current_build_marker(tmp_path, "012")
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("build-newest", encoding="utf-8")

    with pytest.raises(RunContextError, match="uncommitted candidate"):
        _fresh_delivery_baseline(tmp_path, _intent())


@pytest.mark.unit
def test_newer_retained_salvage_supersedes_older_dirty_interruption(
    tmp_path: Path,
) -> None:
    """Historical loose work cannot veto a newer retained delivery lineage."""
    older = _write_state(
        tmp_path, "build-older", status="interrupted",
        termination_reason="user_cancel",
    )
    worktree = older.parent.parent / "worktrees" / "iter-0"
    worktree.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=worktree, check=True)
    (worktree / "loose.txt").write_text("old candidate\n", encoding="utf-8")
    state = json.loads(older.read_text(encoding="utf-8"))
    state["delivery_slice_operation"] = {
        "id": "old-slice", "worktree_path": str(worktree), "progress_applied": False,
    }
    older.write_text(json.dumps(state), encoding="utf-8")
    older_state = json.loads(older.read_text(encoding="utf-8"))
    older_state["checkpoint_commits"] = [{"commit": "a" * 40}]
    older.write_text(json.dumps(older_state), encoding="utf-8")
    newer = _write_state(
        tmp_path, "build-newer", status="interrupted",
        termination_reason="user_cancel",
    )
    newer_state = json.loads(newer.read_text(encoding="utf-8"))
    newer_state["salvage_commit"] = "b" * 40
    newer.write_text(json.dumps(newer_state), encoding="utf-8")
    marker = current_build_marker(tmp_path, "012")
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("build-newer", encoding="utf-8")

    gitops = SimpleNamespace(
        get_clean_worktree_head=lambda *args, **kwargs: "b" * 40,
        commit_is_ancestor=lambda parent, child: (parent, child) in {
            ("a" * 40, "b" * 40), ("b" * 40, "b" * 40),
        },
        commit_is_ancestor_of_default=lambda commit: False,
    )
    assert _fresh_delivery_baseline(tmp_path, _intent(), gitops) == "b" * 40


@pytest.mark.unit
def test_fresh_delivery_recovers_only_checkpointed_tasks_on_baseline_ancestry(
    tmp_path: Path,
) -> None:
    ancestor = "a" * 40
    baseline = "b" * 40
    unrelated = "c" * 40
    first = _write_state(
        tmp_path,
        "build-first",
        status="running",
        checkpoint=ancestor,
    )
    first_payload = json.loads(first.read_text(encoding="utf-8"))
    first_payload.update(
        {
            "spec_id": "012",
            "build": {
                "task_results": {
                    "T-001": {"status": "DONE"},
                    "T-099": {"status": "DONE"},
                }
            },
        }
    )
    first_payload["checkpoint_commits"][0]["task_ids"] = ["T-001"]
    first.write_text(json.dumps(first_payload), encoding="utf-8")

    latest = _write_state(
        tmp_path,
        "build-latest",
        status="interrupted",
        checkpoint=baseline,
    )
    latest_payload = json.loads(latest.read_text(encoding="utf-8"))
    latest_payload.update({"spec_id": "012"})
    latest_payload["checkpoint_commits"][0]["task_ids"] = ["T-002"]
    latest_payload["build"] = {
        "task_results": {
            "T-002": {"status": "DONE"},
            # Provider-reported but never checkpointed: must not be inherited.
            "T-003": {"status": "DONE"},
        }
    }
    latest.write_text(json.dumps(latest_payload), encoding="utf-8")

    other = _write_state(
        tmp_path,
        "build-unrelated",
        status="interrupted",
        checkpoint=unrelated,
    )
    other_payload = json.loads(other.read_text(encoding="utf-8"))
    other_payload.update({"spec_id": "012"})
    other_payload["checkpoint_commits"][0]["task_ids"] = ["T-004"]
    other.write_text(json.dumps(other_payload), encoding="utf-8")

    from harness.task_progress import checkpoint_input_hash

    spec = tmp_path / "specs/012"
    spec.mkdir(parents=True)
    (spec / "tasks.md").write_text("- [ ] T-001 original task\n")
    for path in (first, latest, other):
        payload = json.loads(path.read_text())
        payload["checkpoint_commits"][0]["checkpoint_input_hash"] = checkpoint_input_hash(spec)
        path.write_text(json.dumps(payload))

    class GitOps:
        @staticmethod
        def commit_is_ancestor(commit: str, descendant: str) -> bool:
            return descendant == baseline and commit in {ancestor, baseline}

    recovered = _fresh_delivery_completed_tasks(
        tmp_path,
        _intent(),
        baseline,
        GitOps(),
        spec_dir=spec,
    )

    assert recovered == ("T-001", "T-002")


@pytest.mark.unit
def test_fresh_delivery_repair_target_comes_from_latest_retained_task_checkpoint(
    tmp_path: Path,
) -> None:
    from harness.task_progress import checkpoint_input_hash

    spec = tmp_path / "specs/012"
    spec.mkdir(parents=True)
    (spec / "tasks.md").write_text("- [ ] T-001 first\n- [ ] T-002 second\n")
    digest = checkpoint_input_hash(spec)
    older = "a" * 40
    latest = "b" * 40
    baseline = "c" * 40
    unrelated = "d" * 40
    for build_id, commit, task_id in (
        ("build-001", older, "T-002"),
        ("build-002", latest, "T-001"),
        ("build-003", unrelated, "T-099"),
    ):
        state_path = _write_state(tmp_path, build_id, status="blocked", checkpoint=commit)
        payload = json.loads(state_path.read_text())
        payload["checkpoint_commits"][0].update(
            task_ids=[task_id], checkpoint_input_hash=digest,
        )
        state_path.write_text(json.dumps(payload))

    class GitOps:
        @staticmethod
        def commit_is_ancestor(commit: str, descendant: str) -> bool:
            return descendant == baseline and commit in {older, latest}

    assert _fresh_delivery_repair_task_id(
        tmp_path, _intent(), baseline, GitOps(), spec_dir=spec,
        completed_task_ids=("T-001", "T-002"),
    ) == "T-001"

    (spec / "tasks.md").write_text("- [ ] T-001 changed\n- [ ] T-002 second\n")
    assert _fresh_delivery_repair_task_id(
        tmp_path, _intent(), baseline, GitOps(), spec_dir=spec,
        completed_task_ids=("T-001", "T-002"),
    ) is None
