"""Disposable native amendment-to-Delivery gate transition."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest
import yaml

from echelon.runnability_amendment import prepare_runnability_owner, preview_runnability_owner
from echelon.runnability_amendment_transaction import promote_runnability_owner
from harness.delivery_controller import DeliveryController
from harness.delivery_slice import select_delivery_task
from harness.delivery_slice_runner import DeliverySliceRunner
from harness.skills.run_skill import _amended_delivery_completed_tasks
from harness.state import StateStore
from harness.task_progress import checkpoint_input_hash
from tests.unit.test_delivery_slice_runner import ScriptedExecutor
from tests.unit.test_runnability_amendment import _git, _repo


def test_published_plan_amendment_enters_only_new_task_with_fresh_four_role_receipts(
    tmp_path: Path, monkeypatch,
) -> None:
    control = _repo(tmp_path)
    spec = control / "specs/004-demo"
    target = control / "apps/web"
    _git(target, "init", "-b", "main")
    _git(target, "config", "user.name", "Test User")
    _git(target, "config", "user.email", "test@example.com")
    _git(target, "add", "package.json")
    _git(target, "commit", "-m", "candidate")
    candidate = _git(target, "rev-parse", "HEAD")
    tasks = spec / "tasks.md"
    tasks.write_text(tasks.read_text().replace("- [ ] T-001", "- [x] T-001")
                     .replace("**Status:** PENDING", "**Status:** DONE"))
    old_progress = tasks.read_bytes()
    old_hash = checkpoint_input_hash(spec)
    harness_root = control / "runs/targets/web"
    state_path = harness_root / "runs/build-old/state/delivery.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(json.dumps({
        "spec_id": "004-demo", "status": "interrupted",
        "checkpoint_commits": [{
            "commit": candidate, "task_ids": ["T-001"],
            "checkpoint_input_hash": old_hash,
        }],
    }))

    preview = preview_runnability_owner(control, "004-demo")
    assert preview["new_task_ids"] == ["T-002"]
    assert tasks.read_bytes() == old_progress
    prepared = prepare_runnability_owner(control, "004-demo")
    assert tasks.read_bytes() == old_progress
    promoted = promote_runnability_owner(control, str(prepared["amendment_id"]))
    assert promoted["status"] == "promoted"
    assert b"- [x] T-001" in tasks.read_bytes()
    assert b"- [ ] T-002" in tasks.read_bytes()
    assert checkpoint_input_hash(spec) == promoted["projected_working_hash"]

    class TargetGitOps:
        @staticmethod
        def commit_is_ancestor(ancestor: str, descendant: str) -> bool:
            return subprocess.run(
                ["git", "merge-base", "--is-ancestor", ancestor, descendant],
                cwd=target, check=False,
            ).returncode == 0

    inherited = _amended_delivery_completed_tasks(
        workspace_root=control, harness_root=harness_root, spec_dir=spec,
        intent=SimpleNamespace(spec_id="004-demo", reset=False, resume=False),
        candidate=candidate, gitops=TargetGitOps(),
        config=SimpleNamespace(target_repo=str(target)),
    )
    assert inherited == ("T-001",)
    evidence = tmp_path / "delivery-evidence"
    store = StateStore(evidence, "004-demo")
    store.initialize("fresh-build", "semi")
    store.transition("running")
    DeliveryController._inherit_fresh_task_progress(
        state_store=store, tasks_file=tasks, task_ids=inherited,
    )
    assert store.read()["inherited_checkpoint_task_ids"] == ["T-001"]
    assert select_delivery_task(spec) == "T-002"

    agents = control / ".echelon/prosaic/subagents"
    agents.mkdir(parents=True)
    source = Path(__file__).resolve().parents[2] / "prosaic/subagents"
    for role in ("implementer", "spec-guard", "code-reviewer", "test-guardian"):
        shutil.copyfile(source / f"echelon.delivery-{role}.md",
                        agents / f"echelon.delivery-{role}.md")
    real_run = subprocess.run

    def inspect(argv, **kwargs):
        if argv[:2] != ["prosaic", "inspect"]:
            return real_run(argv, **kwargs)
        content = (Path(argv[argv.index("--source") + 1]) / argv[2]).read_text()
        _, frontmatter, body = content.split("---", 2)
        return subprocess.CompletedProcess(argv, 0, json.dumps({
            "id": argv[2], "type": "subagent",
            "frontmatter": yaml.safe_load(frontmatter), "body": body.strip(),
        }), "")

    monkeypatch.setattr("harness.prosaic_prompt_loader.subprocess.run", inspect)

    def implement_contract(assignment, payload, root):
        if assignment["step"] == "implementer":
            contract = root / ".echelon/runnability.yml"
            contract.parent.mkdir(parents=True, exist_ok=True)
            contract.write_text("schema_version: 1\n")

    executor = ScriptedExecutor(implement_contract)
    result = DeliverySliceRunner(executor, control).run(
        worktree=target, spec_dir=spec, evidence_root=evidence,
        allowed_task_ids={"T-002"}, implementation_target="apps/web",
        declared_targets=["apps/web"], operation_id="fresh-owner-task",
    )
    assert result.reason == "delivery_gates_passed"
    assert result.task_ids == ["T-002"]
    journal = json.loads(next(evidence.rglob("journal.json")).read_text())
    records = journal["records"]
    assert [record["assignment"]["step"] for record in records] == [
        "implementer", "spec_guard", "code_reviewer", "test_guardian",
    ]
    assert len({record["assignment"]["dispatch_id"] for record in records}) == 4


def test_installed_cli_previews_prepares_and_promotes_in_disposable_workspace(
    tmp_path: Path,
) -> None:
    executable = Path(sys.executable).with_name("echelon")
    if not executable.is_file():
        pytest.skip("installed Echelon CLI is unavailable")
    control = _repo(tmp_path)
    spec = control / "specs/004-demo"
    tasks = spec / "tasks.md"
    tasks.write_text(tasks.read_text().replace("- [ ] T-001", "- [x] T-001")
                     .replace("**Status:** PENDING", "**Status:** DONE"))
    old_progress = tasks.read_bytes()
    old_ref = _git(control, "rev-parse", "HEAD")

    def command(*args: str) -> dict[str, object]:
        result = subprocess.run(
            [str(executable), "spec", "amend", *args], cwd=control,
            capture_output=True, text=True, check=False,
        )
        assert result.returncode == 0, result.stderr or result.stdout
        return json.loads(result.stdout)

    preview = command("004-demo", "Add required runnability owner",
                      "--runnability-owner", "--dry-run")
    assert preview["new_task_ids"] == ["T-002"]
    assert tasks.read_bytes() == old_progress
    assert _git(control, "rev-parse", "HEAD") == old_ref
    prepared = command("004-demo", "Add required runnability owner", "--runnability-owner")
    assert prepared["status"] == "prepared"
    assert tasks.read_bytes() == old_progress
    assert _git(control, "rev-parse", "HEAD") == old_ref
    promoted = command("promote", str(prepared["amendment_id"]))
    assert promoted["status"] == "promoted"
    assert _git(control, "rev-parse", "HEAD") == promoted["proposed_commit"]
    assert b"- [x] T-001" in tasks.read_bytes()
    assert b"- [ ] T-002" in tasks.read_bytes()
