"""Real-Git lifecycle coverage for destructive same-identity spec retargeting."""
from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import field
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from echelon.spec_retarget import RetargetError, prepare_spec_retarget
from echelon.spec_retarget_history import advance_retarget_revision, load_retarget_history


pytestmark = pytest.mark.integration


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=check,
        capture_output=True,
        text=True,
    )


@dataclass(frozen=True)
class CommandOutcome:
    exit_code: int
    stdout: str = ""
    stderr: str = ""


@dataclass
class RetargetWorkspace:
    root: Path
    spec_id: str = "001-demo"
    last_checkpoint_id: str | None = field(default=None, init=False)
    other_spec_warning: bool = field(default=False, init=False)

    @property
    def spec_dir(self) -> Path:
        return self.root / "specs" / self.spec_id

    def active_state(self) -> dict[str, object]:
        run_id = (self.root / "runs/.current").read_text(encoding="utf-8").strip()
        return json.loads((self.root / "runs" / run_id / "state.json").read_text())

    def git_head(self) -> str:
        return _git(self.root, "rev-parse", "HEAD").stdout.strip()

    def git_diff_names(self, older: str, newer: str, prefix: str) -> set[str]:
        output = _git(
            self.root,
            "diff",
            "--name-only",
            older,
            newer,
            "--",
            prefix,
        ).stdout
        marker = prefix.rstrip("/") + "/"
        return {
            name.removeprefix(marker)
            for name in output.splitlines()
            if name.startswith(marker)
        }

    @staticmethod
    def _memory_receipt() -> object:
        from echelon.mempalace_retarget import RetargetMemoryReceipt

        return RetargetMemoryReceipt(
            status="not_applicable",
            spec_id="001-demo",
            deleted_count=0,
            deleted_ids=(),
            drawer_set_digest="sha256:" + hashlib.sha256(b"[]").hexdigest(),
            mine_status="not_applicable",
            audit_status="not_applicable",
        )

    def _graph_receipt(self) -> object:
        from echelon.spec_retarget_graph import RetargetGraphReceipt

        return RetargetGraphReceipt(
            spec_id="001-demo",
            spec_status="pass",
            spec_graph_hash="sha256:" + "2" * 64,
            workspace_status="warn" if self.other_spec_warning else "pass",
            workspace_graph_hash="sha256:" + "3" * 64,
            workspace_finding_codes=(
                ("workspace_member_audit_warning:002-other",)
                if self.other_spec_warning
                else ()
            ),
        )

    def _invalidation_receipt(self) -> object:
        from echelon.spec_retarget_graph import RetargetGraphReceipt

        return RetargetGraphReceipt(
            spec_id=self.spec_id,
            spec_status="invalidated",
            spec_graph_hash=None,
            workspace_status="warn" if self.other_spec_warning else "pass",
            workspace_graph_hash="sha256:" + "4" * 64,
            workspace_finding_codes=(
                ("workspace_member_audit_warning:002-other",)
                if self.other_spec_warning
                else ()
            ),
        )

    def snapshot(self) -> tuple[str, tuple[str, ...], tuple[tuple[str, bytes], ...]]:
        files = tuple(
            sorted(
                (
                    path.relative_to(self.root).as_posix(),
                    path.read_bytes(),
                )
                for path in self.root.rglob("*")
                if path.is_file() and ".git" not in path.relative_to(self.root).parts
            )
        )
        return self.git_head(), self.git_staged_names(), files

    def git_staged_names(self) -> tuple[str, ...]:
        return tuple(
            _git(self.root, "diff", "--cached", "--name-only").stdout.splitlines()
        )

    def preview_retarget(self, targets: tuple[str, ...]) -> CommandOutcome:
        try:
            prepare_spec_retarget(
                self.root,
                self.spec_id,
                targets,
                confirm=False,
            )
        except RetargetError as exc:
            return CommandOutcome(1, stderr=str(exc))
        return CommandOutcome(0)

    def add_delivery_evidence(self, evidence: str) -> None:
        if evidence == "phase_b_history":
            path = self.spec_dir / "run-history.json"
            path.write_text(
                json.dumps({"runs": [{"run_id": "build-1", "phase": "B"}]})
                + "\n",
                encoding="utf-8",
            )
        elif evidence == "build_state":
            path = self.root / "runs/build-1/state.json"
            path.parent.mkdir(parents=True)
            path.write_text(
                json.dumps({"spec_id": self.spec_id}) + "\n",
                encoding="utf-8",
            )
        elif evidence == "completed_task":
            path = self.spec_dir / "tasks.md"
            path.write_text(
                "- [x] T-001 complexity=standard phase=build req=FR-001 "
                "depends=none target=services/api\n",
                encoding="utf-8",
            )
        elif evidence == "verification_artifact":
            path = self.spec_dir / "gap-report.md"
            path.write_text("# Verification evidence\n", encoding="utf-8")
        else:  # pragma: no cover - test helper contract
            raise AssertionError(f"unknown evidence: {evidence}")
        _git(self.root, "add", path.relative_to(self.root).as_posix())
        _git(self.root, "commit", "-m", f"add {evidence} evidence")

    def park_before_ready(self) -> None:
        run_id = (self.root / "runs/.current").read_text(encoding="utf-8").strip()
        state_path = self.root / "runs" / run_id / "state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state.update(
            status="running",
            phase="phase3-plan",
            completed_phases=["phase1-what", "phase2-how"],
            ready_to_build=False,
        )
        state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        _git(self.root, "add", state_path.relative_to(self.root).as_posix())
        _git(self.root, "commit", "-m", "park spec before readiness")

    def owned_memory_ids(self) -> tuple[str, ...]:
        retarget = self.active_state()["retarget"]
        receipt = retarget["memory_purge"]
        return tuple(receipt["remaining_owned_ids"])

    def checkout_default_branch(self) -> None:
        _git(self.root, "checkout", "main")

    def add_other_spec_warning(self, spec_id: str) -> None:
        assert spec_id == "002-other"
        other = self.root / "specs" / spec_id
        other.mkdir(parents=True)
        (other / "spec.md").write_text(
            "---\nstatus: planned\n---\n# Other\n",
            encoding="utf-8",
        )
        self.other_spec_warning = True
        _git(self.root, "add", other.relative_to(self.root).as_posix())
        _git(self.root, "commit", "-m", "add unrelated warning spec")

    def run_drop_target(self, target: str) -> CommandOutcome:
        from echelon.cli import _cmd_drop_target

        self.park_before_ready()
        state = self.active_state()
        state["implementation_targets"] = ["services/api", target]
        run_id = str(state["run_id"])
        state_path = self.root / "runs" / run_id / "state.json"
        state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        for directory in (
            self.spec_dir,
            self.root / "runs" / run_id / "specs" / self.spec_id,
        ):
            (directory / "targets.yml").write_text(
                f"targets:\n- services/api\n- {target}\n",
                encoding="utf-8",
            )
        _git(self.root, "add", ".")
        _git(self.root, "commit", "-m", "declare unused target")
        stdout = io.StringIO()
        stderr = io.StringIO()
        try:
            with redirect_stdout(stdout), redirect_stderr(stderr):
                _cmd_drop_target(
                    [self.spec_id, target, "--confirm"],
                    project_root=self.root,
                )
        except SystemExit as exc:
            return CommandOutcome(int(exc.code or 0), stdout.getvalue(), stderr.getvalue())
        return CommandOutcome(0, stdout.getvalue(), stderr.getvalue())

    def target_repository_snapshots(self) -> dict[str, tuple[tuple[str, bytes], ...]]:
        snapshots: dict[str, tuple[tuple[str, bytes], ...]] = {}
        for target in ("services/api", "apps/web"):
            directory = self.root / target
            snapshots[target] = tuple(
                sorted(
                    (path.relative_to(directory).as_posix(), path.read_bytes())
                    for path in directory.rglob("*")
                    if path.is_file()
                )
            )
        return snapshots

    def run_retarget(
        self,
        targets: tuple[str, ...],
        *,
        fail_after: str | None = None,
        stop_before_first_dispatch: bool = False,
        stop_after_invalidation: bool = False,
        crash_after: str | None = None,
    ) -> CommandOutcome:
        from echelon import spec_retarget as subject

        created: list[object] = []
        original_invalidate = subject.invalidate_retarget_artifacts

        def invalidate_then_fail(*args: object, **kwargs: object) -> tuple[str, ...]:
            invalidated = original_invalidate(*args, **kwargs)
            raise OSError("injected failure after artifact invalidation")

        invalidation = (
            patch.object(subject, "invalidate_retarget_artifacts", invalidate_then_fail)
            if fail_after == "artifact_invalidation"
            else patch.object(
                subject,
                "invalidate_retarget_artifacts",
                original_invalidate,
            )
        )
        try:
            with ExitStack() as stack:
                stack.enter_context(invalidation)
                if self.other_spec_warning:
                    stack.enter_context(
                        patch.object(
                            subject,
                            "invalidate_retarget_graphs",
                            return_value=self._invalidation_receipt(),
                        )
                    )
                result = prepare_spec_retarget(
                    self.root,
                    self.spec_id,
                    targets,
                    confirm=True,
                    checkpoint_created=created.append,
                )
        except RetargetError as exc:
            if created:
                self.last_checkpoint_id = str(getattr(created[-1], "id"))
            return CommandOutcome(1, stderr=str(exc))
        assert created
        self.last_checkpoint_id = str(getattr(created[-1], "id"))
        if stop_before_first_dispatch or stop_after_invalidation:
            return CommandOutcome(0)
        try:
            self._complete_retarget(
                result.replacement_run_id,
                crash_after=crash_after,
            )
        except Exception as exc:
            return CommandOutcome(1, stderr=f"{type(exc).__name__}: {exc}")
        return CommandOutcome(
            0,
            stdout=f"echelon spec rewind checkpoint:{self.last_checkpoint_id} --confirm\n",
        )

    def continue_spec(self) -> CommandOutcome:
        state = self.active_state()
        try:
            self._complete_retarget(str(state["run_id"]))
        except Exception as exc:
            return CommandOutcome(1, stderr=f"{type(exc).__name__}: {exc}")
        return CommandOutcome(0)

    def delivery_preflight(self) -> CommandOutcome:
        from harness.phase_a_readiness import validate_phase_a_readiness

        result = validate_phase_a_readiness(self.active_state(), [self.spec_dir])
        return CommandOutcome(0 if result.ready else 1, stderr="\n".join(result.blockers))

    def rewind_printed_checkpoint(
        self,
        failed: CommandOutcome,
        *,
        crash_after_commit: bool = False,
        forbid_replayed_effects: bool = False,
    ) -> CommandOutcome:
        from echelon import cli as legacy_cli

        match = re.search(r"checkpoint:([^\s]+)", failed.stderr)
        checkpoint_id = match.group(1) if match else self.last_checkpoint_id
        assert checkpoint_id is not None
        stdout = io.StringIO()
        stderr = io.StringIO()
        effect_failure = AssertionError("committed recovery effect was replayed")
        with ExitStack() as stack:
            stack.enter_context(
                patch(
                    "echelon.spec_retarget_recovery.purge_retarget_spec_memory",
                    side_effect=effect_failure if forbid_replayed_effects else None,
                    return_value=self._memory_receipt(),
                )
            )
            stack.enter_context(
                patch(
                    "echelon.spec_retarget_recovery.refresh_retarget_spec_memory",
                    side_effect=effect_failure if forbid_replayed_effects else None,
                    return_value=self._memory_receipt(),
                )
            )
            stack.enter_context(
                patch(
                    "echelon.spec_retarget_recovery.finalize_retarget_graphs",
                    side_effect=effect_failure if forbid_replayed_effects else None,
                    return_value=self._graph_receipt(),
                )
            )
            if crash_after_commit:
                stack.enter_context(
                    patch(
                        "echelon.spec_retarget_recovery.persist_recovered_baseline_state",
                        side_effect=OSError("injected crash after recovery commit"),
                    )
                )
            stack.enter_context(redirect_stdout(stdout))
            stack.enter_context(redirect_stderr(stderr))
            try:
                legacy_cli._cmd_rewind(
                    [f"checkpoint:{checkpoint_id}", "--confirm"],
                    self.root,
                )
            except SystemExit as exc:
                return CommandOutcome(int(exc.code or 0), stdout.getvalue(), stderr.getvalue())
        return CommandOutcome(0, stdout.getvalue(), stderr.getvalue())

    def _complete_retarget(
        self,
        replacement_run_id: str | None,
        *,
        crash_after: str | None = None,
    ) -> None:
        """Stand in only for provider dispatch; use the real sealed finalizer."""
        from echelon.spec_retarget_finalization import (
            apply_or_verify_retarget_finalization,
        )

        assert replacement_run_id is not None
        run_dir = self.root / "runs" / replacement_run_id
        state_path = run_dir / "state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        retarget = state["retarget"]
        revision_id = retarget["revision_id"]

        targets = tuple(state["implementation_targets"])
        replacement = {
            "spec.md": (
                "---\nstatus: planned\n---\n# Replacement specification\n\n"
                "- **FR-001**: Build the replacement.\n"
            ),
            "plan.md": "# Replacement plan\n",
            "tasks.md": "".join(
                f"- [ ] T-{index:03d} complexity=standard phase=build "
                f"req=UNMAPPED depends=none target={target}\n"
                for index, target in enumerate(targets, 1)
            ),
        }
        for name, contents in replacement.items():
            (self.spec_dir / name).write_text(contents, encoding="utf-8")
            shadow = run_dir / "specs" / self.spec_id / name
            shadow.parent.mkdir(parents=True, exist_ok=True)
            shadow.write_text(contents, encoding="utf-8")

        if retarget["status"] == "rebuilding":
            advance_retarget_revision(
                self.spec_dir,
                revision_id,
                expected_status="rebuilding",
                status="finalizing",
                updates={},
            )
            retarget["status"] = "finalizing"
            state["status"] = "running"
            state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        else:
            assert retarget["status"] == "finalizing"

        completion_id = "1" * 32
        transaction_root = run_dir / ".controller-completion" / completion_id
        transaction_root.mkdir(parents=True, exist_ok=True)
        prepared = SimpleNamespace(
            intent=SimpleNamespace(completion_id=completion_id),
            _transaction_root=transaction_root,
        )
        memory = self._memory_receipt()
        graph = self._graph_receipt()
        graph_result: object = graph
        if crash_after == "retarget_memory_receipt":
            graph_result = RuntimeError("injected crash after retarget memory receipt")
        with (
            patch(
                "echelon.spec_retarget_finalization.refresh_retarget_spec_memory",
                return_value=memory,
            ),
            patch(
                "echelon.spec_retarget_finalization.finalize_retarget_graphs",
                side_effect=(
                    graph_result
                    if isinstance(graph_result, BaseException)
                    else None
                ),
                return_value=graph,
            ),
        ):
            receipt = apply_or_verify_retarget_finalization(
                prepared,
                project_root=self.root,
                state=state,
                expected_receipt=None,
            )

        retarget["status"] = "complete"
        retarget["finalization_receipt"] = receipt
        retarget.pop("memory_excluded", None)
        state["status"] = "done"
        state["phase"] = "phase4-complete"
        state["completed_phases"] = [
            "phase1-what",
            "phase2-how",
            "phase3-plan",
            "phase4-complete",
        ]
        state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


@pytest.fixture
def retarget_workspace(tmp_path: Path) -> RetargetWorkspace:
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.email", "echelon@example.test")
    _git(tmp_path, "config", "user.name", "Echelon Tests")
    (tmp_path / "README.md").write_text("fixture\n", encoding="utf-8")
    _git(tmp_path, "add", "README.md")
    _git(tmp_path, "commit", "-m", "base")
    base_commit = _git(tmp_path, "rev-parse", "HEAD").stdout.strip()
    _git(tmp_path, "checkout", "-b", "001-demo")

    for target in ("services/api", "apps/web"):
        (tmp_path / target).mkdir(parents=True)
        (tmp_path / target / "README.md").write_text(
            f"{target}\n",
            encoding="utf-8",
        )
    (tmp_path / ".echelon").mkdir()
    (tmp_path / ".echelon/config.yml").write_text("sources: []\n", encoding="utf-8")

    spec_dir = tmp_path / "specs/001-demo"
    spec_dir.mkdir(parents=True)
    artifacts = {
        "spec.md": (
            "---\nstatus: planned\n---\n# Baseline specification\n\n"
            "- **FR-001**: Build the API.\n"
        ),
        "plan.md": "# Baseline plan\n",
        "tasks.md": (
            "- [ ] T-001 complexity=standard phase=build req=FR-001 "
            "depends=none target=services/api\n"
        ),
        "targets.yml": "targets:\n  - services/api\n",
    }
    for name, contents in artifacts.items():
        (spec_dir / name).write_text(contents, encoding="utf-8")

    from echelon.spec_graph import build_spec_graph, write_spec_graph
    from echelon.spec_graph_audit import audit_spec_graph, write_spec_graph_audit
    from echelon.workspace_graph import build_workspace_graph, write_workspace_graph
    from echelon.workspace_graph_audit import (
        audit_workspace_graph,
        write_workspace_graph_audit,
    )

    write_spec_graph(build_spec_graph(tmp_path, spec_dir), spec_dir)
    write_spec_graph_audit(audit_spec_graph(tmp_path, spec_dir), spec_dir)
    workspace_graph = build_workspace_graph(tmp_path)
    write_workspace_graph(workspace_graph.graph, tmp_path)
    write_workspace_graph_audit(
        audit_workspace_graph(tmp_path, workspace_graph),
        tmp_path,
    )

    run_dir = tmp_path / "runs/squad-001-1"
    shadow = run_dir / "specs/001-demo"
    shadow.mkdir(parents=True)
    for name, contents in artifacts.items():
        (shadow / name).write_text(contents, encoding="utf-8")
    state = {
        "run_id": "squad-001-1",
        "spec_id": "001-demo",
        "feature_branch": "001-demo",
        "spec_dir": "runs/squad-001-1/specs/001-demo",
        "published_spec_dir": "specs/001-demo",
        "spec_number": "001",
        "phase_a_default_branch": "001-demo",
        "phase_a_base_commit": base_commit,
        "implementation_targets": ["services/api"],
        "user_message": "Build account search",
        "autonomy_mode": "semi",
        "status": "done",
        "phase": "phase3-plan",
        "completed_phases": ["phase1-what", "phase2-how", "phase3-plan"],
        "published_re_context": {"status": "absent"},
        "ignore_re": False,
        "requested_re_sources": [],
    }
    (run_dir / "state.json").write_text(json.dumps(state, indent=2) + "\n")
    (tmp_path / "runs/.current").write_text("squad-001-1\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "ready baseline")
    _git(tmp_path, "branch", "-f", "main", "HEAD")
    return RetargetWorkspace(tmp_path)


def test_ready_spec_retargets_in_place_and_records_old_to_new_diff(
    retarget_workspace: RetargetWorkspace,
) -> None:
    baseline_spec_id = retarget_workspace.spec_id

    outcome = retarget_workspace.run_retarget(("apps/web",))

    state = retarget_workspace.active_state()
    history = load_retarget_history(retarget_workspace.spec_dir)
    assert outcome.exit_code == 0
    assert state["spec_id"] == baseline_spec_id
    assert state["retarget"]["status"] == "complete"
    assert state["implementation_targets"] == ["apps/web"]
    replacement_commit = state["retarget"]["finalization_receipt"]["replacement_commit"]
    assert replacement_commit == retarget_workspace.git_head()
    assert retarget_workspace.git_diff_names(
        history.revisions[-1].checkpoint_commit,
        replacement_commit,
        f"specs/{baseline_spec_id}",
    ) >= {"spec.md", "plan.md", "tasks.md", "targets.yml", "retarget-history.json"}
    assert history.revisions[-1].replacement_commit == replacement_commit
    raw_history = json.loads(
        (retarget_workspace.spec_dir / "retarget-history.json").read_text(
            encoding="utf-8"
        )
    )
    # A commit cannot contain its own OID. The raw terminal row stays committed
    # with a null field; readers derive the unique verified reachable commit.
    assert raw_history["revisions"][-1]["replacement_commit"] is None
    clone = retarget_workspace.root.parent / "completion-clone"
    _git(retarget_workspace.root.parent, "clone", str(retarget_workspace.root), str(clone))
    assert (
        load_retarget_history(clone / "specs" / baseline_spec_id)
        .revisions[-1]
        .replacement_commit
        == replacement_commit
    )
    selected_status = _git(
        retarget_workspace.root,
        "status",
        "--porcelain",
        "--",
        f"specs/{baseline_spec_id}",
    ).stdout.splitlines()
    assert [
        line
        for line in selected_status
        if f"specs/{baseline_spec_id}/.echelon/" not in line
    ] == []
    assert _git(
        retarget_workspace.root,
        "show",
        f"HEAD:specs/{baseline_spec_id}/retarget-history.json",
    ).stdout == (retarget_workspace.spec_dir / "retarget-history.json").read_text(
        encoding="utf-8"
    )


def test_failed_retarget_recovers_only_through_checkpoint(
    retarget_workspace: RetargetWorkspace,
) -> None:
    failed = retarget_workspace.run_retarget(
        ("apps/web",),
        fail_after="artifact_invalidation",
    )

    assert failed.exit_code == 1
    assert "echelon spec rewind checkpoint:" in failed.stderr
    assert retarget_workspace.delivery_preflight().exit_code == 1

    recovered = retarget_workspace.rewind_printed_checkpoint(failed)

    assert recovered.exit_code == 0, recovered.stderr
    assert retarget_workspace.active_state()["implementation_targets"] == ["services/api"]
    history = load_retarget_history(retarget_workspace.spec_dir)
    assert history.revisions[-1].status == "recovered"
    assert history.revisions[-1].recovery_commit == retarget_workspace.git_head()
    raw_history = json.loads(
        (retarget_workspace.spec_dir / "retarget-history.json").read_text(
            encoding="utf-8"
        )
    )
    # Recovery uses the same reachable-history derivation, so replay readers see
    # the OID without creating a post-commit tracked modification.
    assert raw_history["revisions"][-1]["recovery_commit"] is None
    clone = retarget_workspace.root.parent / "recovery-clone"
    _git(retarget_workspace.root.parent, "clone", str(retarget_workspace.root), str(clone))
    assert (
        load_retarget_history(clone / "specs" / retarget_workspace.spec_id)
        .revisions[-1]
        .recovery_commit
        == retarget_workspace.git_head()
    )
    selected_status = _git(
        retarget_workspace.root,
        "status",
        "--porcelain",
        "--",
        f"specs/{retarget_workspace.spec_id}",
    ).stdout.splitlines()
    assert [
        line
        for line in selected_status
        if f"specs/{retarget_workspace.spec_id}/.echelon/" not in line
    ] == []
    assert _git(
        retarget_workspace.root,
        "show",
        f"HEAD:specs/{retarget_workspace.spec_id}/retarget-history.json",
    ).stdout == (
        retarget_workspace.spec_dir / "retarget-history.json"
    ).read_text(encoding="utf-8")


def test_recovery_commit_crash_retries_without_replaying_effects_and_state_validates(
    retarget_workspace: RetargetWorkspace,
) -> None:
    from jsonschema import Draft7Validator

    failed = retarget_workspace.run_retarget(
        ("apps/web",),
        fail_after="artifact_invalidation",
    )
    first = retarget_workspace.rewind_printed_checkpoint(
        failed,
        crash_after_commit=True,
    )

    assert first.exit_code == 1
    recovery_head = retarget_workspace.git_head()
    second = retarget_workspace.rewind_printed_checkpoint(
        failed,
        forbid_replayed_effects=True,
    )

    assert second.exit_code == 0, second.stderr
    assert retarget_workspace.git_head() == recovery_head
    state = retarget_workspace.active_state()
    schema = json.loads(
        (Path(__file__).parents[2] / "templates/state-schema.json").read_text(
            encoding="utf-8"
        )
    )
    assert list(Draft7Validator(schema).iter_errors(state)) == []
    repeated = retarget_workspace.rewind_printed_checkpoint(
        failed,
        forbid_replayed_effects=True,
    )
    assert repeated.exit_code == 0, repeated.stderr
    assert retarget_workspace.git_head() == recovery_head
    history = load_retarget_history(retarget_workspace.spec_dir)
    assert len(history.revisions) == 1
    assert history.revisions[-1].recovery_commit == recovery_head


def test_recovery_refuses_and_preserves_staged_user_edit_to_generated_filename(
    retarget_workspace: RetargetWorkspace,
) -> None:
    failed = retarget_workspace.run_retarget(
        ("apps/web",),
        fail_after="artifact_invalidation",
    )
    user_bytes = b"user-authored spec recovery notes\n"
    spec = retarget_workspace.spec_dir / "spec.md"
    spec.write_bytes(user_bytes)
    _git(retarget_workspace.root, "add", "specs/001-demo/spec.md")
    staged_before = retarget_workspace.git_staged_names()

    refused = retarget_workspace.rewind_printed_checkpoint(failed)

    assert refused.exit_code == 1
    assert spec.read_bytes() == user_bytes
    assert retarget_workspace.git_staged_names() == staged_before
    assert "specs/001-demo/spec.md" in staged_before


def _mutate_history_updated_at(path: Path) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["revisions"][-1]["updated_at"] = "2026-08-05T12:34:56+00:00"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_user_staging_bytes(path: Path) -> None:
    path.write_bytes(b"user-owned staging bytes\n")


@pytest.mark.parametrize(
    ("relative_path", "mutate"),
    (
        ("retarget-history.json", _mutate_history_updated_at),
        (".spec.md.retarget-recovery", _write_user_staging_bytes),
    ),
)
def test_recovery_preserves_staged_edits_to_reserved_controller_names(
    retarget_workspace: RetargetWorkspace,
    relative_path: str,
    mutate: object,
) -> None:
    failed = retarget_workspace.run_retarget(
        ("apps/web",),
        fail_after="artifact_invalidation",
    )
    path = retarget_workspace.spec_dir / relative_path
    original = path.read_bytes() if path.exists() else None
    assert callable(mutate)
    mutate(path)
    user_bytes = path.read_bytes()
    assert user_bytes != original
    _git(retarget_workspace.root, "add", f"specs/001-demo/{relative_path}")
    staged_before = retarget_workspace.git_staged_names()

    refused = retarget_workspace.rewind_printed_checkpoint(failed)

    assert refused.exit_code == 1
    assert path.read_bytes() == user_bytes
    assert retarget_workspace.git_staged_names() == staged_before


@pytest.mark.parametrize(
    "delivery_evidence",
    ("phase_b_history", "build_state", "completed_task", "verification_artifact"),
)
def test_any_delivery_evidence_rejects_retarget(
    retarget_workspace: RetargetWorkspace,
    delivery_evidence: str,
) -> None:
    retarget_workspace.add_delivery_evidence(delivery_evidence)
    before = retarget_workspace.snapshot()

    outcome = retarget_workspace.preview_retarget(("apps/web",))

    assert outcome.exit_code == 1
    assert "retarget_delivery_already_started" in outcome.stderr
    assert "echelon spec run" in outcome.stderr
    assert retarget_workspace.snapshot() == before


def test_retarget_preserves_unrelated_dirty_bytes_and_staging(
    retarget_workspace: RetargetWorkspace,
) -> None:
    dirty = retarget_workspace.root / "notes/private.txt"
    staged = retarget_workspace.root / "notes/staged.txt"
    dirty.parent.mkdir()
    dirty.write_bytes(b"private\n")
    staged.write_bytes(b"staged\n")
    _git(retarget_workspace.root, "add", "notes/staged.txt")
    staged_before = retarget_workspace.git_staged_names()

    outcome = retarget_workspace.run_retarget(("apps/web",))

    assert outcome.exit_code == 0, outcome.stderr
    assert dirty.read_bytes() == b"private\n"
    assert staged.read_bytes() == b"staged\n"
    assert retarget_workspace.git_staged_names() == staged_before


def test_pre_ready_spec_rebuilds_with_complete_multi_target_set(
    retarget_workspace: RetargetWorkspace,
) -> None:
    retarget_workspace.park_before_ready()

    outcome = retarget_workspace.run_retarget(("apps/web", "services/api"))

    assert outcome.exit_code == 0, outcome.stderr
    assert retarget_workspace.active_state()["implementation_targets"] == [
        "apps/web",
        "services/api",
    ]


def test_owned_memory_is_absent_before_first_replacement_dispatch(
    retarget_workspace: RetargetWorkspace,
) -> None:
    outcome = retarget_workspace.run_retarget(
        ("apps/web",),
        stop_before_first_dispatch=True,
    )

    assert outcome.exit_code == 0, outcome.stderr
    state = retarget_workspace.active_state()
    assert state["retarget"]["memory_excluded"] is True
    assert retarget_workspace.owned_memory_ids() == ()


def test_invalidation_removes_old_graph_edges_and_single_spec_workspace_graph(
    retarget_workspace: RetargetWorkspace,
) -> None:
    from echelon.workspace_graph import workspace_graph_path

    assert (retarget_workspace.spec_dir / "spec-artifact-graph.json").is_file()
    assert workspace_graph_path(retarget_workspace.root).is_file()

    outcome = retarget_workspace.run_retarget(
        ("apps/web",),
        stop_after_invalidation=True,
    )

    assert outcome.exit_code == 0, outcome.stderr
    assert not (
        retarget_workspace.spec_dir / "spec-artifact-graph.json"
    ).exists()
    assert not workspace_graph_path(retarget_workspace.root).exists()


def test_finalization_crash_replays_one_revision(
    retarget_workspace: RetargetWorkspace,
) -> None:
    first = retarget_workspace.run_retarget(
        ("apps/web",),
        crash_after="retarget_memory_receipt",
    )

    assert first.exit_code == 1
    resumed = retarget_workspace.continue_spec()

    assert resumed.exit_code == 0, resumed.stderr
    history = load_retarget_history(retarget_workspace.spec_dir)
    assert len(history.revisions) == 1
    assert history.revisions[-1].status == "complete"


def test_active_branch_mismatch_is_read_only(
    retarget_workspace: RetargetWorkspace,
) -> None:
    retarget_workspace.checkout_default_branch()
    before = retarget_workspace.snapshot()

    result = retarget_workspace.preview_retarget(("apps/web",))

    assert result.exit_code == 1
    assert "echelon spec switch" in result.stderr
    assert retarget_workspace.snapshot() == before


def test_unrelated_workspace_warning_does_not_block_selected_spec(
    retarget_workspace: RetargetWorkspace,
) -> None:
    retarget_workspace.add_other_spec_warning("002-other")

    outcome = retarget_workspace.run_retarget(("apps/web",))

    assert outcome.exit_code == 0, outcome.stderr
    graph = retarget_workspace.active_state()["retarget"]["finalization_receipt"][
        "graph"
    ]
    assert graph["workspace_status"] == "warn"
    assert graph["workspace_finding_codes"] == [
        "workspace_member_audit_warning:002-other"
    ]


def test_drop_target_stays_available_for_unused_target(
    retarget_workspace: RetargetWorkspace,
) -> None:
    result = retarget_workspace.run_drop_target("apps/web")

    assert result.exit_code == 0, result.stderr
    assert len(load_retarget_history(retarget_workspace.spec_dir).revisions) == 0


def test_retarget_does_not_mutate_target_repositories(
    retarget_workspace: RetargetWorkspace,
) -> None:
    before = retarget_workspace.target_repository_snapshots()

    result = retarget_workspace.run_retarget(("apps/web", "services/api"))

    assert result.exit_code == 0, result.stderr
    assert retarget_workspace.target_repository_snapshots() == before
