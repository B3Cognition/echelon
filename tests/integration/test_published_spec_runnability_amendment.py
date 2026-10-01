"""Disposable native amendment-to-Delivery gate transition."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import yaml

from echelon.runnability_amendment import prepare_runnability_owner, preview_runnability_owner
from echelon.runnability_amendment_transaction import promote_runnability_owner
from harness.delivery_controller import DeliveryController
from harness.delivery_slice import select_delivery_task
from harness.delivery_slice_runner import DeliverySliceRunner
from harness.config import load_config
from harness.gitops import GitOpsManager
from harness.paths import mirror_path
from harness.run_intent import RunIntent
from harness.skills.run_skill import (
    _amended_delivery_completed_tasks, _execute_delivery_run, _fresh_delivery_baseline,
)
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
    assert inherited.task_ids == ("T-001",)
    evidence = tmp_path / "delivery-evidence"
    store = StateStore(evidence, "004-demo")
    store.initialize("fresh-build", "semi")
    store.transition("running")
    DeliveryController._inherit_fresh_task_progress(
        state_store=store, tasks_file=tasks, task_ids=inherited.task_ids,
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


def test_installed_promote_command_recovers_interrupted_transaction(tmp_path: Path) -> None:
    executable = Path(sys.executable).with_name("echelon")
    if not executable.is_file():
        pytest.skip("installed Echelon CLI is unavailable")
    control = _repo(tmp_path)
    prepared = prepare_runnability_owner(control, "004-demo")

    def fault(phase: str) -> None:
        if phase == "after_index":
            raise RuntimeError("injected interruption")

    with pytest.raises(RuntimeError, match="injected interruption"):
        promote_runnability_owner(control, str(prepared["amendment_id"]), fault_hook=fault)
    result = subprocess.run(
        [str(executable), "spec", "amend", "promote", str(prepared["amendment_id"])],
        cwd=control, capture_output=True, text=True, check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert json.loads(result.stdout)["status"] == "promoted"
    assert _git(control, "rev-parse", "HEAD") == prepared["proposed_commit"]


def test_landed_old_checkpoint_inherits_from_pinned_default_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    control = _repo(tmp_path)
    spec = control / "specs/004-demo"
    target = control / "apps/web"
    _git(target, "init", "-b", "main")
    _git(target, "config", "user.name", "Test User")
    _git(target, "config", "user.email", "test@example.com")
    _git(target, "add", "package.json")
    _git(target, "commit", "-m", "accepted old task")
    checkpoint = _git(target, "rev-parse", "HEAD")
    from harness.phase_a_readiness import REQUIRED_PHASE_A_BUILD_INPUTS
    for name in REQUIRED_PHASE_A_BUILD_INPUTS:
        path = spec / name
        if not path.exists():
            path.write_text(f"# {name}\n", encoding="utf-8")
    (spec / "plan-conformance.json").write_text(json.dumps({
        "status": "pass", "findings": [], "sources": ["spec.md", "tasks.md"],
    }), encoding="utf-8")
    _git(control, "add", "specs/004-demo")
    _git(control, "commit", "-m", "publish complete disposable spec inputs")
    tasks = spec / "tasks.md"
    tasks.write_text(tasks.read_text().replace("- [ ] T-001", "- [x] T-001")
                     .replace("**Status:** PENDING", "**Status:** DONE"))
    old_hash = checkpoint_input_hash(spec)
    harness_root = control / "runs/targets/web"
    mirror = mirror_path(harness_root)
    mirror.parent.mkdir(parents=True)
    subprocess.run(["git", "clone", "--bare", str(target), str(mirror)], check=True,
                   capture_output=True)
    state_path = harness_root / "runs/build-old/state/delivery.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(json.dumps({
        "spec_id": "004-demo", "status": "interrupted",
        "checkpoint_commits": [{
            "commit": checkpoint, "task_ids": ["T-001"],
            "checkpoint_input_hash": old_hash,
        }],
    }), encoding="utf-8")
    config = load_config(project_root=control, squad_only=True)
    config.target_repo = str(target)
    gitops = GitOpsManager(config, base_dir=str(harness_root))
    intent = SimpleNamespace(spec_id="004-demo", reset=False, resume=False)
    assert _fresh_delivery_baseline(harness_root, intent, gitops) is None

    prepared = prepare_runnability_owner(control, "004-demo")
    assert prepared["targets"]["apps/web"]["landed_baseline_commit"] == checkpoint
    promoted = promote_runnability_owner(control, str(prepared["amendment_id"]))
    # Native Delivery writes this lifecycle status before amendment admission.
    # When the published Spec had no frontmatter, the exact scope hash changes.
    from harness.spec_frontmatter import write_status
    write_status(spec, "in_progress")
    assert checkpoint_input_hash(spec) != promoted["projected_working_hash"]
    assert _amended_delivery_completed_tasks(
        workspace_root=control, harness_root=harness_root, spec_dir=spec,
        intent=intent, candidate=None, gitops=gitops, config=config,
    ).task_ids == ("T-001",)
    lifecycle_spec = (spec / "spec.md").read_text(encoding="utf-8")
    (spec / "spec.md").write_text(lifecycle_spec.replace("# Demo", "# Changed scope"),
                                   encoding="utf-8")
    from harness.skills.run_skill import RunContextError
    with pytest.raises(RunContextError, match="current Spec input hash differs"):
        _amended_delivery_completed_tasks(
            workspace_root=control, harness_root=harness_root, spec_dir=spec,
            intent=intent, candidate=None, gitops=gitops, config=config,
        )
    (spec / "spec.md").write_text(lifecycle_spec, encoding="utf-8")
    assert promoted["status"] == "promoted"

    monkeypatch.setenv("ECHELON_TARGET_REPO_NAME", "web")
    monkeypatch.setenv("ECHELON_TARGET_REPO_PATH", str(target))
    monkeypatch.setenv("ECHELON_IMPLEMENTATION_TARGET", "apps/web")
    monkeypatch.setenv("ECHELON_DECLARED_TARGETS", "apps/web")
    config.llm.enabled = True
    with patch("harness.delivery_controller.AICodingCliProvider", return_value=object()), \
         patch("harness.delivery_controller.RalphController") as ralph:
        ralph.return_value.run_loop.side_effect = RuntimeError("stop after native admission")
        with pytest.raises(RuntimeError, match="stop after native admission"):
            _execute_delivery_run(
                intent=RunIntent(spec_id="004-demo", auto_merge=False),
                provider=object(), gitops=gitops, harness_root=harness_root,
                workspace_root=control, spec_dir=spec, config=config,
                resume_build_id=None, summary_command="echelon delivery run",
            )
    states = sorted(harness_root.glob("runs/build-*/state/delivery.json"))
    native_paths = [path for path in states
                    if json.loads(path.read_text()).get("amendment_admission")]
    assert len(native_paths) == 1
    native = json.loads(native_paths[0].read_text())
    assert native["inherited_checkpoint_task_ids"] == ["T-001"]
    assert native["amendment_admission"]["amendment_id"] == prepared["amendment_id"]
    assert select_delivery_task(spec) == "T-002"

    with patch("harness.delivery_controller.AICodingCliProvider", return_value=object()), \
         patch("harness.delivery_controller.RalphController") as ralph:
        ralph.return_value.run_loop.side_effect = RuntimeError("stop after native resume")
        with pytest.raises(RuntimeError, match="stop after native resume"):
            _execute_delivery_run(
                intent=RunIntent(spec_id="004-demo", auto_merge=False, resume=True),
                provider=object(), gitops=gitops, harness_root=harness_root,
                workspace_root=control, spec_dir=spec, config=config,
                resume_build_id=native_paths[0].parents[1].name,
                summary_command="echelon delivery resume",
            )
    assert json.loads(native_paths[0].read_text())["amendment_admission"] == native[
        "amendment_admission"
    ]

    _git(target, "commit", "--allow-empty", "-m", "advance landed target baseline")
    _git(mirror, "fetch", str(target), "+refs/heads/main:refs/heads/main")
    assert _fresh_delivery_baseline(harness_root, intent, gitops) is None
    assert _amended_delivery_completed_tasks(
        workspace_root=control, harness_root=harness_root, spec_dir=spec,
        intent=intent, candidate=None, gitops=gitops, config=config,
    ).task_ids == ("T-001",)
