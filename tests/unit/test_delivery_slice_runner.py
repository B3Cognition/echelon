"""Exercise real gate routing, files, Prosaic loading, and bound results."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml

from harness.ai_cli_backend import CliRunResult


@pytest.fixture
def slice_project(tmp_path, monkeypatch):
    project = tmp_path / "project"
    spec = project / "specs/001-slice"
    spec.mkdir(parents=True)
    (spec / "spec.md").write_text("# Spec\nFR-1: return a greeting.\n")
    (spec / "tasks.md").write_text(
        "- [ ] T-001 complexity=standard phase=build req=FR-1 depends=none\n"
        "  **Acceptance Criteria:**\n  - [ ] Return hello\n"
        "- [ ] T-002 complexity=standard phase=build req=FR-2 depends=T-001\n")
    (project / "app.py").write_text("def hello(): return None\n")
    agents = project / ".echelon/prosaic/subagents"
    agents.mkdir(parents=True)
    source = Path(__file__).resolve().parents[2] / "prosaic/subagents"
    for name in ("implementer", "spec-guard", "code-reviewer", "test-guardian"):
        path = source / f"echelon.delivery-{name}.md"
        shutil.copyfile(path, agents / path.name)
    real_run = subprocess.run

    def inspect(argv, **kwargs):
        if argv[:2] != ["prosaic", "inspect"]:
            return real_run(argv, **kwargs)
        text = (Path(argv[argv.index("--source") + 1]) / argv[2]).read_text()
        _, frontmatter, body = text.split("---", 2)
        return subprocess.CompletedProcess(argv, 0, json.dumps({
            "id": argv[2], "type": "subagent", "frontmatter": yaml.safe_load(frontmatter),
            "body": body.strip(),
        }), "")

    monkeypatch.setattr("harness.prosaic_prompt_loader.subprocess.run", inspect)
    return project, spec, tmp_path / "evidence"


class ScriptedExecutor:
    supports_read_only_review = True

    def __init__(self, script=None):
        self.script = script
        self.calls = []

    def run_agent_result(self, cwd, prompt, *, request_metadata, **kwargs):
        assignment = request_metadata["delivery_assignment"]
        self.calls.append((dict(assignment), request_metadata["prompt_metadata"], prompt))
        if assignment["step"] == "implementer":
            Path(cwd, "app.py").write_text(f"def hello(): return 'hello {len(self.calls)}'\n")
        verdict = {"implementer": "DONE", "spec_guard": "PASS", "code_reviewer": "APPROVED",
                   "test_guardian": "PASS"}[assignment["step"]]
        payload = {**assignment, "verdict": verdict, "summary": "Inspected the assigned task", "findings": []}
        if self.script:
            override = self.script(assignment, payload, Path(cwd))
            if isinstance(override, CliRunResult):
                return override
        return CliRunResult(0, json.dumps(payload), "", token_usage=7)


def _run(fixture, executor, **kwargs):
    from harness.delivery_slice_runner import DeliverySliceRunner
    project, spec, evidence = fixture
    return DeliverySliceRunner(executor, project).run(
        worktree=project, spec_dir=spec, evidence_root=evidence, **kwargs)


def _steps(executor):
    return [call[0]["step"] for call in executor.calls]


def test_only_three_sequential_approvals_accept_one_task(slice_project):
    executor = ScriptedExecutor()
    result = _run(slice_project, executor)
    assert result.succeeded and result.task_ids == ["T-001"], result.reason
    assert _steps(executor) == ["implementer", "spec_guard", "code_reviewer", "test_guardian"]
    assert result.token_usage == 28
    assert executor.calls[0][0]["candidate_fingerprint"] != executor.calls[1][0]["candidate_fingerprint"]
    assert len({call[0]["candidate_fingerprint"] for call in executor.calls[1:]}) == 1
    for _, metadata, _ in executor.calls[1:]:
        assert metadata["tool_write_scope_exclusive"] is True
        assert metadata["tool_write_paths"] == []
    assert "- [ ] T-001" in (slice_project[1] / "tasks.md").read_text()
    assert len(list(slice_project[2].rglob("result.json"))) == 4


def test_browser_capture_request_is_durable_and_cannot_accept_task(slice_project):
    def request_capture(assignment, payload, root):
        if assignment["step"] == "implementer":
            payload.update(
                verdict="BROWSER_EVIDENCE_REQUIRED",
                summary="Pinned visual baselines need sandbox captures",
                browser_evidence_request={"purpose": "baseline_capture"},
            )

    first = ScriptedExecutor(request_capture)
    result = _run(slice_project, first)

    assert result.status == "blocked" and result.task_ids == []
    assert result.reason == "delivery_browser_evidence_requested: baseline_capture"
    assert _steps(first) == ["implementer"]
    assert "BROWSER_EVIDENCE_REQUIRED" in first.calls[0][2]
    assert "browser_evidence_request" in first.calls[0][2]
    assert "Reserve NEEDS_CONTEXT for genuinely missing information" in first.calls[0][2]
    journal_path = next(slice_project[2].rglob("journal.json"))
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    assert journal["records"][0]["result"]["browser_evidence_request"] == {
        "purpose": "baseline_capture"
    }
    replay = ScriptedExecutor()
    resumed = _run(slice_project, replay)
    assert resumed.reason == result.reason and resumed.task_ids == []
    assert not replay.calls


def test_browser_request_returns_scoped_capture_to_same_task_before_review(slice_project):
    from harness.product_inventory import product_evidence_fingerprint
    from harness.verify_result import VerifyResult
    from harness.visual_ralph import BrowserBaselineCapture

    requested = False

    def request_once(assignment, payload, root):
        nonlocal requested
        if assignment["step"] == "implementer" and not requested:
            requested = True
            payload.update(
                verdict="BROWSER_EVIDENCE_REQUIRED",
                summary="Pinned baseline needs sandbox capture",
                browser_evidence_request={"purpose": "baseline_capture"},
            )

    captures = []

    def capture(worktree):
        captures.append(worktree)
        return BrowserBaselineCapture(
            candidate_fingerprint=product_evidence_fingerprint(Path(worktree)),
            verification=VerifyResult(passed=False),
            images={"tests/e2e/demo.spec.ts-snapshots/pitch-chromium.png": b"proposal"},
        )

    executor = ScriptedExecutor(request_once)
    result = _run(slice_project, executor, browser_baseline_capture=capture)

    assert result.succeeded and result.task_ids == ["T-001"], result.reason
    assert captures == [str(slice_project[0].resolve())]
    assert _steps(executor) == [
        "implementer", "implementer", "spec_guard", "code_reviewer", "test_guardian",
    ]
    assert executor.calls[0][0]["task_id"] == executor.calls[1][0]["task_id"]
    retained_root = next(slice_project[2].rglob("browser-baselines/*/*/artifacts"))
    assert executor.calls[1][1]["tool_read_roots"] == [str(retained_root)]
    assert "pitch-chromium.png" in executor.calls[1][2]
    assert (retained_root / "0001.png").read_bytes() == b"proposal"
    assert all("pitch-chromium.png" not in prompt for _, _, prompt in executor.calls[2:])


def test_browser_capture_resumes_from_retained_evidence_without_recapturing(slice_project):
    from harness.product_inventory import product_evidence_fingerprint
    from harness.verify_result import VerifyResult
    from harness.visual_ralph import BrowserBaselineCapture

    stop = False

    def request(assignment, payload, root):
        if assignment["step"] == "implementer":
            payload.update(
                verdict="BROWSER_EVIDENCE_REQUIRED", summary="Need browser capture",
                browser_evidence_request={"purpose": "baseline_capture"},
            )

    def capture(worktree):
        nonlocal stop
        stop = True
        return BrowserBaselineCapture(
            candidate_fingerprint=product_evidence_fingerprint(Path(worktree)),
            verification=VerifyResult(passed=False),
            images={"tests/e2e/demo.spec.ts-snapshots/pitch-chromium.png": b"proposal"},
        )

    first = ScriptedExecutor(request)
    interrupted = _run(
        slice_project, first, operation_id="capture-op",
        browser_baseline_capture=capture, stop_requested=lambda: stop,
    )
    assert interrupted.status == "blocked" and interrupted.reason == "delivery_slice_cancelled"
    assert _steps(first) == ["implementer"]

    def forbidden_recapture(_worktree):
        raise AssertionError("retained proposal must be replayed")

    replay = ScriptedExecutor()
    resumed = _run(
        slice_project, replay, operation_id="capture-op", journal_required=True,
        browser_baseline_capture=forbidden_recapture,
    )
    assert resumed.succeeded and resumed.task_ids == ["T-001"], resumed.reason
    assert _steps(replay) == ["implementer", "spec_guard", "code_reviewer", "test_guardian"]
    assert "pitch-chromium.png" in replay.calls[0][2]


def test_browser_capture_replay_rejects_altered_image_before_dispatch(slice_project):
    from harness.product_inventory import product_evidence_fingerprint
    from harness.verify_result import VerifyResult
    from harness.visual_ralph import BrowserBaselineCapture

    stop = False

    def request(assignment, payload, root):
        if assignment["step"] == "implementer":
            payload.update(
                verdict="BROWSER_EVIDENCE_REQUIRED", summary="Need browser capture",
                browser_evidence_request={"purpose": "baseline_capture"},
            )

    def capture(worktree):
        nonlocal stop
        stop = True
        return BrowserBaselineCapture(
            candidate_fingerprint=product_evidence_fingerprint(Path(worktree)),
            verification=VerifyResult(passed=False),
            images={"tests/e2e/demo.spec.ts-snapshots/pitch-chromium.png": b"proposal"},
        )

    first = _run(
        slice_project, ScriptedExecutor(request), operation_id="capture-op",
        browser_baseline_capture=capture, stop_requested=lambda: stop,
    )
    assert first.reason == "delivery_slice_cancelled"
    next(slice_project[2].rglob("artifacts/0001.png")).write_bytes(b"changed")

    replay = ScriptedExecutor()
    result = _run(
        slice_project, replay, operation_id="capture-op", journal_required=True,
        browser_baseline_capture=lambda _worktree: pytest.fail("must not recapture"),
    )
    assert result.status == "blocked" and "digest mismatch" in result.reason
    assert replay.calls == []


@pytest.mark.parametrize("owner_verdict", ["BLOCKED", "NEEDS_CONTEXT"])
def test_browser_capture_never_overrides_followup_owner_block(slice_project, owner_verdict):
    from harness.product_inventory import product_evidence_fingerprint
    from harness.verify_result import VerifyResult
    from harness.visual_ralph import BrowserBaselineCapture

    calls = 0

    def decide(assignment, payload, root):
        nonlocal calls
        if assignment["step"] == "implementer":
            calls += 1
            if calls == 1:
                payload.update(
                    verdict="BROWSER_EVIDENCE_REQUIRED", summary="Need capture",
                    browser_evidence_request={"purpose": "baseline_capture"},
                )
            else:
                payload.update(verdict=owner_verdict, summary="Owner input still required")

    def capture(worktree):
        return BrowserBaselineCapture(
            candidate_fingerprint=product_evidence_fingerprint(Path(worktree)),
            verification=VerifyResult(passed=False),
            images={"tests/e2e/demo.spec.ts-snapshots/pitch-chromium.png": b"proposal"},
        )

    executor = ScriptedExecutor(decide)
    result = _run(slice_project, executor, browser_baseline_capture=capture)
    assert result.status == "blocked" and result.task_ids == []
    assert result.reason == f"delivery_implementer_blocked: Owner input still required"
    assert _steps(executor) == ["implementer", "implementer"]


def test_browser_capture_request_cannot_loop_indefinitely(slice_project):
    from harness.product_inventory import product_evidence_fingerprint
    from harness.verify_result import VerifyResult
    from harness.visual_ralph import BrowserBaselineCapture

    def request(assignment, payload, root):
        if assignment["step"] == "implementer":
            payload.update(
                verdict="BROWSER_EVIDENCE_REQUIRED", summary="Still need capture",
                browser_evidence_request={"purpose": "baseline_capture"},
            )

    def capture(worktree):
        return BrowserBaselineCapture(
            candidate_fingerprint=product_evidence_fingerprint(Path(worktree)),
            verification=VerifyResult(passed=False),
            images={"tests/e2e/demo.spec.ts-snapshots/pitch-chromium.png": b"proposal"},
        )

    executor = ScriptedExecutor(request)
    result = _run(slice_project, executor, browser_baseline_capture=capture)
    assert result.status == "blocked" and result.reason == "delivery_browser_evidence_request_repeated"
    assert result.task_ids == [] and _steps(executor) == ["implementer", "implementer"]


def test_no_image_browser_capture_returns_to_same_implementer_then_recaptures(slice_project):
    from harness.product_inventory import product_evidence_fingerprint
    from harness.verify_result import VerifyResult
    from harness.visual_ralph import BrowserBaselineCapture

    implementation_calls = 0
    captures = []

    def implement(assignment, payload, root):
        nonlocal implementation_calls
        if assignment["step"] != "implementer":
            return
        implementation_calls += 1
        if implementation_calls == 2:
            assert "no snapshot image" in executor.calls[-1][2]
            assert "snapshot assertion" in executor.calls[-1][2]
            assert executor.calls[-1][1]["tool_read_roots"] == []
            (root / "snapshot.spec.ts").write_text("expect(page).toHaveScreenshot()\n")
        if implementation_calls <= 2:
            payload.update(verdict="BROWSER_EVIDENCE_REQUIRED", summary="Need capture",
                           browser_evidence_request={"purpose": "baseline_capture"})

    def capture(worktree):
        root = Path(worktree)
        has_test = (root / "snapshot.spec.ts").exists()
        captures.append(has_test)
        return BrowserBaselineCapture(
            candidate_fingerprint=product_evidence_fingerprint(root),
            verification=VerifyResult(passed=True),
            images={"tests/e2e/demo.spec.ts-snapshots/pitch-chromium.png": b"image"}
            if has_test else {},
        )

    executor = ScriptedExecutor(implement)
    result = _run(slice_project, executor, browser_baseline_capture=capture)

    assert result.succeeded and result.task_ids == ["T-001"], result.reason
    assert captures == [False, True]
    assert _steps(executor) == ["implementer"] * 3 + [
        "spec_guard", "code_reviewer", "test_guardian",
    ]
    assert "pitch-chromium.png" in executor.calls[2][2]
    assert all("pitch-chromium.png" not in prompt for _, _, prompt in executor.calls[3:])
    journal = json.loads(next(slice_project[2].rglob("journal.json")).read_text())
    assert len([record for record in journal["records"] if "browser_evidence" in record]) == 2


def test_no_image_browser_capture_cannot_become_approval_without_recapture(slice_project):
    from harness.product_inventory import product_evidence_fingerprint
    from harness.verify_result import VerifyResult
    from harness.visual_ralph import BrowserBaselineCapture

    requested = False

    def request_once(assignment, payload, root):
        nonlocal requested
        if assignment["step"] == "implementer" and not requested:
            requested = True
            payload.update(verdict="BROWSER_EVIDENCE_REQUIRED", summary="Need capture",
                           browser_evidence_request={"purpose": "baseline_capture"})

    def capture(worktree):
        return BrowserBaselineCapture(
            candidate_fingerprint=product_evidence_fingerprint(Path(worktree)),
            verification=VerifyResult(passed=True), images={},
        )

    executor = ScriptedExecutor(request_once)
    result = _run(slice_project, executor, browser_baseline_capture=capture)

    assert result.status == "blocked" and result.task_ids == []
    assert result.reason == "delivery_browser_snapshot_recapture_required"
    assert _steps(executor) == ["implementer", "implementer"]


def test_no_image_capture_replays_without_recapture_and_second_empty_capture_blocks(slice_project):
    from harness.product_inventory import product_evidence_fingerprint
    from harness.verify_result import VerifyResult
    from harness.visual_ralph import BrowserBaselineCapture

    stop = False
    captures = 0

    def request(assignment, payload, root):
        if assignment["step"] == "implementer":
            payload.update(verdict="BROWSER_EVIDENCE_REQUIRED", summary="Need capture",
                           browser_evidence_request={"purpose": "baseline_capture"})

    def capture(worktree):
        nonlocal captures, stop
        captures += 1
        if captures == 1:
            stop = True
        return BrowserBaselineCapture(
            candidate_fingerprint=product_evidence_fingerprint(Path(worktree)),
            verification=VerifyResult(passed=True), images={},
        )

    first = _run(
        slice_project, ScriptedExecutor(request), operation_id="empty-capture-op",
        browser_baseline_capture=capture, stop_requested=lambda: stop,
    )
    assert first.reason == "delivery_slice_cancelled" and captures == 1

    stop = False
    replay = ScriptedExecutor(request)
    result = _run(
        slice_project, replay, operation_id="empty-capture-op", journal_required=True,
        browser_baseline_capture=capture,
    )
    assert result.status == "blocked" and result.reason == "delivery_browser_capture_no_snapshots_after_retry"
    assert captures == 2
    assert _steps(replay) == ["implementer"]
    assert "no snapshot image" in replay.calls[0][2]
    journal = json.loads(next(slice_project[2].rglob("journal.json")).read_text())
    assert len([record for record in journal["records"] if "browser_evidence" in record]) == 2


def test_polyrepo_slice_projects_workspace_paths_into_target_worktree(slice_project):
    project, spec, evidence = slice_project
    (spec / "tasks.md").write_text(
        "- [ ] T-001 complexity=standard phase=build req=FR-1 depends=none "
        "target=sources/demo\n"
        "\n"
        "  **Files:**\n"
        "  - `sources/demo/app.py` - Implement the greeting.\n"
        "\n"
        "  **Acceptance Criteria:**\n"
        "  - [ ] Return hello\n",
        encoding="utf-8",
    )
    executor = ScriptedExecutor()

    from harness.delivery_slice_runner import DeliverySliceRunner
    result = DeliverySliceRunner(executor, project).run(
        worktree=project,
        spec_dir=spec,
        evidence_root=evidence,
        implementation_target="sources/demo",
    )

    assert result.succeeded, result.reason
    assert all(
        '"canonical_prefix": "sources/demo/"' in prompt
        and '"sources/demo/app.py": "app.py"' in prompt
        and '"forbidden_nested_root": "sources/demo"' in prompt
        for _, _, prompt in executor.calls
    )


def test_polyrepo_slice_preserves_repository_relative_task_paths(slice_project):
    project, spec, evidence = slice_project
    (spec / "tasks.md").write_text(
        "- [ ] T-001 complexity=standard phase=build req=FR-1 depends=none "
        "target=sources/demo\n"
        "\n"
        "  **Files:**\n"
        "  - `src/app.py` - Implement the greeting.\n",
        encoding="utf-8",
    )
    executor = ScriptedExecutor()

    from harness.delivery_slice_runner import DeliverySliceRunner
    result = DeliverySliceRunner(executor, project).run(
        worktree=project,
        spec_dir=spec,
        evidence_root=evidence,
        implementation_target="sources/demo",
    )

    assert result.succeeded, result.reason
    assert all(
        '"src/app.py": "src/app.py"' in prompt
        for _, _, prompt in executor.calls
    )


def test_reviewers_receive_new_candidate_tests_outside_declared_task_files(slice_project):
    project, spec, _ = slice_project
    (spec / "tasks.md").write_text(
        "- [ ] T-001 complexity=standard phase=build req=FR-1 depends=none\n"
        "  **Files:**\n  - `app.py` - Implement the greeting.\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    subprocess.run(["git", "add", "app.py"], cwd=project, check=True)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com",
         "commit", "-qm", "baseline"],
        cwd=project, check=True,
    )

    def add_candidate_tests(assignment, payload, root):
        if assignment["step"] == "implementer":
            tests = root / "tests/integration"
            tests.mkdir(parents=True)
            (tests / "main-entry.test.ts").write_text("// entry coverage\n")
            (tests / "outcomes-style.test.ts").write_text("// outcome coverage\n")

    executor = ScriptedExecutor(add_candidate_tests)
    result = _run(slice_project, executor)

    assert result.succeeded, result.reason
    for _, _, prompt in executor.calls[1:]:
        assert '"tests/integration/main-entry.test.ts"' in prompt
        assert '"tests/integration/outcomes-style.test.ts"' in prompt
        assert "not approval evidence or an expanded task scope" in prompt


def test_reviewers_receive_committed_candidate_tests_outside_declared_task_files(slice_project):
    project, spec, _ = slice_project
    (spec / "tasks.md").write_text(
        "- [ ] T-001 complexity=standard phase=build req=FR-1 depends=none\n"
        "  **Files:**\n  - `app.py` - Implement the greeting.\n",
        encoding="utf-8",
    )
    tests = project / "tests/integration"
    tests.mkdir(parents=True)
    (tests / "main-entry.test.ts").write_text("// entry coverage\n")
    (tests / "outcomes-style.test.ts").write_text("// outcome coverage\n")
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    subprocess.run(["git", "add", "app.py", "tests/integration"], cwd=project, check=True)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com",
         "commit", "-qm", "salvaged candidate"],
        cwd=project, check=True,
    )

    executor = ScriptedExecutor()
    result = _run(slice_project, executor)

    assert result.succeeded, result.reason
    for _, _, prompt in executor.calls[1:]:
        assert '"tests/integration/main-entry.test.ts"' in prompt
        assert '"tests/integration/outcomes-style.test.ts"' in prompt


def test_candidate_inventory_bounds_large_changed_file_lists(tmp_path):
    from harness.delivery_slice_runner import _candidate_file_inventory

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "baseline.txt").write_text("baseline\n")
    subprocess.run(["git", "add", "baseline.txt"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com",
         "commit", "-qm", "baseline"],
        cwd=tmp_path, check=True,
    )
    for index in range(205):
        (tmp_path / f"file-{index:03}.txt").write_text("candidate\n")

    inventory = _candidate_file_inventory(tmp_path)

    assert inventory is not None
    assert len(inventory["changed_paths"]) == 200
    assert inventory["changed_paths_truncated"] is True


def test_polyrepo_slice_rejects_selected_task_from_another_target(slice_project):
    project, spec, evidence = slice_project
    (spec / "tasks.md").write_text(
        "- [ ] T-001 complexity=standard phase=build req=FR-1 depends=none "
        "target=sources/demo\n",
        encoding="utf-8",
    )
    executor = ScriptedExecutor()

    from harness.delivery_slice_runner import DeliverySliceRunner
    result = DeliverySliceRunner(executor, project).run(
        worktree=project,
        spec_dir=spec,
        evidence_root=evidence,
        implementation_target="sources/other",
    )

    assert result.status == "blocked"
    assert result.reason == (
        "delivery task T-001 target sources/demo does not match "
        "implementation target sources/other"
    )
    assert executor.calls == []


def test_polyrepo_slice_rejects_unsafe_implementation_target(slice_project):
    project, spec, evidence = slice_project
    (spec / "tasks.md").write_text(
        "- [ ] T-001 complexity=standard phase=build req=FR-1 depends=none "
        "target=../other\n",
        encoding="utf-8",
    )
    executor = ScriptedExecutor()

    from harness.delivery_slice_runner import DeliverySliceRunner
    result = DeliverySliceRunner(executor, project).run(
        worktree=project,
        spec_dir=spec,
        evidence_root=evidence,
        implementation_target="../other",
    )

    assert result.status == "blocked"
    assert result.reason == "invalid implementation target: ../other"
    assert executor.calls == []


def test_polyrepo_slice_rejects_selected_task_file_outside_target(slice_project):
    project, spec, evidence = slice_project
    (spec / "tasks.md").write_text(
        "- [ ] T-001 complexity=standard phase=build req=FR-1 depends=none "
        "target=sources/demo\n"
        "\n"
        "  **Files:**\n"
        "  - `sources/other/app.py` - Wrong repository.\n",
        encoding="utf-8",
    )
    executor = ScriptedExecutor()

    from harness.delivery_slice_runner import DeliverySliceRunner
    result = DeliverySliceRunner(executor, project).run(
        worktree=project,
        spec_dir=spec,
        evidence_root=evidence,
        implementation_target="sources/demo",
    )

    assert result.status == "blocked"
    assert result.reason == (
        "delivery task T-001 file sources/other/app.py is outside "
        "implementation target sources/demo"
    )
    assert executor.calls == []


def test_polyrepo_slice_rejects_file_owned_by_arbitrary_sibling_target(
    slice_project,
):
    project, spec, evidence = slice_project
    (spec / "tasks.md").write_text(
        "- [ ] T-001 complexity=standard phase=build req=FR-1 depends=none "
        "target=apps/api\n"
        "\n"
        "  **Files:**\n"
        "  - `apps/web/src/app.ts` - Wrong repository.\n",
        encoding="utf-8",
    )
    executor = ScriptedExecutor()

    from harness.delivery_slice_runner import DeliverySliceRunner
    result = DeliverySliceRunner(executor, project).run(
        worktree=project,
        spec_dir=spec,
        evidence_root=evidence,
        implementation_target="apps/api",
        declared_targets=["apps/api", "apps/web"],
    )

    assert result.status == "blocked"
    assert result.reason == (
        "delivery task T-001 file apps/web/src/app.ts is outside "
        "implementation target apps/api"
    )
    assert executor.calls == []


def test_polyrepo_slice_uses_most_specific_overlapping_target_owner(
    slice_project,
):
    project, spec, evidence = slice_project
    (spec / "tasks.md").write_text(
        "- [ ] T-001 complexity=standard phase=build req=FR-1 depends=none "
        "target=apps\n"
        "\n"
        "  **Files:**\n"
        "  - `apps/web/src/app.ts` - Owned by the nested repository.\n",
        encoding="utf-8",
    )
    executor = ScriptedExecutor()

    from harness.delivery_slice_runner import DeliverySliceRunner
    result = DeliverySliceRunner(executor, project).run(
        worktree=project,
        spec_dir=spec,
        evidence_root=evidence,
        implementation_target="apps",
        declared_targets=["apps", "apps/web"],
    )

    assert result.status == "blocked"
    assert result.reason == (
        "delivery task T-001 file apps/web/src/app.ts is outside "
        "implementation target apps"
    )
    assert executor.calls == []


def test_polyrepo_slice_rejects_traversal_in_selected_task_file(slice_project):
    project, spec, evidence = slice_project
    (spec / "tasks.md").write_text(
        "- [ ] T-001 complexity=standard phase=build req=FR-1 depends=none "
        "target=sources/demo\n"
        "\n"
        "  **Files:**\n"
        "  - `../sources/demo/app.py` - Escapes the workspace root.\n",
        encoding="utf-8",
    )
    executor = ScriptedExecutor()

    from harness.delivery_slice_runner import DeliverySliceRunner
    result = DeliverySliceRunner(executor, project).run(
        worktree=project,
        spec_dir=spec,
        evidence_root=evidence,
        implementation_target="sources/demo",
    )

    assert result.status == "blocked"
    assert result.reason == "invalid delivery task T-001 file path ../sources/demo/app.py"
    assert executor.calls == []


def test_polyrepo_slice_validates_labeled_file_bullets(slice_project):
    project, spec, evidence = slice_project
    (spec / "tasks.md").write_text(
        "- [ ] T-001 complexity=standard phase=build req=FR-1 depends=none "
        "target=sources/demo\n"
        "\n"
        "  **Files:**\n"
        "  - **Modify:** `../sources/demo/app.py` - Escapes the workspace root.\n",
        encoding="utf-8",
    )
    executor = ScriptedExecutor()

    from harness.delivery_slice_runner import DeliverySliceRunner
    result = DeliverySliceRunner(executor, project).run(
        worktree=project,
        spec_dir=spec,
        evidence_root=evidence,
        implementation_target="sources/demo",
    )

    assert result.status == "blocked"
    assert result.reason == "invalid delivery task T-001 file path ../sources/demo/app.py"
    assert executor.calls == []


@pytest.mark.parametrize("bullet", ["*", "+"])
def test_polyrepo_slice_validates_standard_markdown_file_bullets(
    slice_project, bullet,
):
    project, spec, evidence = slice_project
    (spec / "tasks.md").write_text(
        "- [ ] T-001 complexity=standard phase=build req=FR-1 depends=none "
        "target=sources/demo\n"
        "\n"
        "  **Files:**\n"
        f"  {bullet} **Modify:** `../sources/demo/app.py` - Escapes the root.\n",
        encoding="utf-8",
    )
    executor = ScriptedExecutor()

    from harness.delivery_slice_runner import DeliverySliceRunner
    result = DeliverySliceRunner(executor, project).run(
        worktree=project,
        spec_dir=spec,
        evidence_root=evidence,
        implementation_target="sources/demo",
    )

    assert result.status == "blocked"
    assert result.reason == "invalid delivery task T-001 file path ../sources/demo/app.py"
    assert executor.calls == []


def test_polyrepo_slice_rejects_unparseable_file_bullet(slice_project):
    project, spec, evidence = slice_project
    (spec / "tasks.md").write_text(
        "- [ ] T-001 complexity=standard phase=build req=FR-1 depends=none "
        "target=sources/demo\n"
        "\n"
        "  **Files:**\n"
        "  - src/app.py - Missing canonical path delimiters.\n",
        encoding="utf-8",
    )
    executor = ScriptedExecutor()

    from harness.delivery_slice_runner import DeliverySliceRunner
    result = DeliverySliceRunner(executor, project).run(
        worktree=project,
        spec_dir=spec,
        evidence_root=evidence,
        implementation_target="sources/demo",
    )

    assert result.status == "blocked"
    assert result.reason == "invalid delivery task T-001 Files entry"
    assert executor.calls == []


def test_polyrepo_slice_ignores_fenced_task_examples_when_projecting_paths(
    slice_project,
):
    project, spec, evidence = slice_project
    (spec / "tasks.md").write_text(
        "- [ ] T-001 complexity=standard phase=build req=FR-1 depends=none "
        "target=sources/demo\n"
        "\n"
        "```md\n"
        "- [ ] T-999 complexity=standard phase=example req=FR-X depends=none "
        "target=sources/other\n"
        "\n"
        "  **Files:**\n"
        "  - `sources/other/example.py` - Documentation example only.\n"
        "```\n"
        "\n"
        "  **Files:**\n"
        "  - `sources/demo/app.py` - Implement the greeting.\n",
        encoding="utf-8",
    )
    executor = ScriptedExecutor()

    from harness.delivery_slice_runner import DeliverySliceRunner
    result = DeliverySliceRunner(executor, project).run(
        worktree=project,
        spec_dir=spec,
        evidence_root=evidence,
        implementation_target="sources/demo",
    )

    assert result.succeeded, result.reason
    assert all(
        '"sources/demo/app.py": "app.py"' in prompt
        and "sources/other/example.py" not in prompt.split(
            "## Candidate path projection (controller authority)", 1
        )[1].split("## Read-only specification inputs", 1)[0]
        for _, _, prompt in executor.calls
    )


def test_polyrepo_slice_rejects_recreated_target_prefix_after_implementation(
    slice_project,
):
    project, spec, evidence = slice_project
    (spec / "tasks.md").write_text(
        "- [ ] T-001 complexity=standard phase=build req=FR-1 depends=none "
        "target=sources/demo\n"
        "\n"
        "  **Files:**\n"
        "  - `sources/demo/app.py` - Implement the greeting.\n",
        encoding="utf-8",
    )

    def recreate_prefix(assignment, payload, root):
        if assignment["step"] == "implementer":
            nested = root / "sources" / "demo"
            nested.mkdir(parents=True)
            (nested / "app.py").write_text("wrong root\n", encoding="utf-8")

    executor = ScriptedExecutor(recreate_prefix)

    from harness.delivery_slice_runner import DeliverySliceRunner
    result = DeliverySliceRunner(executor, project).run(
        worktree=project,
        spec_dir=spec,
        evidence_root=evidence,
        implementation_target="sources/demo",
    )

    assert result.status == "blocked"
    assert result.reason == "delivery_nested_target_modified: sources/demo"
    assert _steps(executor) == ["implementer"]


@pytest.mark.parametrize("failed_step,negative", [("spec_guard", "FAIL"),
    ("code_reviewer", "CHANGES_REQUESTED"), ("test_guardian", "FAIL")])
def test_repair_invalidates_every_prior_approval(slice_project, failed_step, negative):
    failed = False
    def script(assignment, payload, root):
        nonlocal failed
        if assignment["step"] == failed_step and not failed:
            payload.update(verdict=negative, findings=["app.py:1 returns incorrect text"])
            failed = True
    executor = ScriptedExecutor(script)
    result = _run(slice_project, executor)
    chain = ["implementer", "spec_guard", "code_reviewer", "test_guardian"]
    assert _steps(executor) == chain * 2
    assert result.succeeded and result.task_ids == ["T-001"], result.reason
    assert "incorrect text" in executor.calls[len(chain)][2]


def test_collects_all_required_review_failures_before_one_repair(slice_project):
    failed_once: set[str] = set()
    findings = {
        "spec_guard": "spec.md:1 requirement mismatch",
        "code_reviewer": "app.py:1 implementation defect",
        "test_guardian": "tests/test_app.py:1 missing regression coverage",
    }

    def script(assignment, payload, root):
        step = assignment["step"]
        if step == "implementer" or step in failed_once:
            return
        failed_once.add(step)
        payload.update(
            verdict={
                "spec_guard": "FAIL",
                "code_reviewer": "CHANGES_REQUESTED",
                "test_guardian": "FAIL",
            }[step],
            summary=f"{step} rejected the candidate",
            findings=[findings[step]],
        )

    executor = ScriptedExecutor(script)

    result = _run(slice_project, executor)

    chain = ["implementer", "spec_guard", "code_reviewer", "test_guardian"]
    assert result.succeeded and result.task_ids == ["T-001"], result.reason
    assert _steps(executor) == chain * 2
    repair_prompt = executor.calls[len(chain)][2]
    assert all(finding in repair_prompt for finding in findings.values())


def test_host_binds_fingerprints_and_preserves_the_review_decision(slice_project):
    finding = "app.py:1 still returns the wrong greeting"
    rejected = False

    def script(assignment, payload, root):
        nonlocal rejected
        if assignment["step"] != "code_reviewer" or rejected:
            return
        rejected = True
        payload.update(
            candidate_fingerprint=assignment["candidate_fingerprint"][:48],
            input_fingerprint=assignment["input_fingerprint"][:50],
            verdict="CHANGES_REQUESTED",
            summary="The candidate still needs one repair",
            findings=[finding],
        )

    executor = ScriptedExecutor(script)

    result = _run(slice_project, executor)

    chain = ["implementer", "spec_guard", "code_reviewer", "test_guardian"]
    assert result.succeeded and result.task_ids == ["T-001"], result.reason
    assert _steps(executor) == chain * 2
    assert finding in executor.calls[len(chain)][2]
    journal_path = next(slice_project[2].rglob("journal.json"))
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    review = journal["records"][2]
    raw = json.loads(review["raw_result"])
    assert raw["input_fingerprint"] != review["assignment"]["input_fingerprint"]
    assert review["result"]["input_fingerprint"] == review["assignment"]["input_fingerprint"]
    assert review["result"]["verdict"] == "CHANGES_REQUESTED"
    assert review["result"]["findings"] == [finding]


def test_four_failed_repairs_block_without_degraded_progress(slice_project):
    def script(assignment, payload, root):
        if assignment["step"] == "spec_guard":
            payload.update(verdict="FAIL", findings=["app.py:1 wrong implementation"])
    executor = ScriptedExecutor(script)
    result = _run(slice_project, executor)
    chain = ["implementer", "spec_guard", "code_reviewer", "test_guardian"]
    assert _steps(executor) == chain * 5
    assert result.status == "blocked" and not result.task_ids
    assert "repair_limit" in result.reason
    assert result.token_usage == 140


def test_third_repair_can_accept_after_three_rejected_review_rounds(slice_project):
    rejected_rounds = 0

    def script(assignment, payload, root):
        nonlocal rejected_rounds
        if assignment["step"] == "spec_guard" and rejected_rounds < 3:
            rejected_rounds += 1
            payload.update(verdict="FAIL", findings=["app.py:1 wrong implementation"])

    executor = ScriptedExecutor(script)
    result = _run(slice_project, executor)

    chain = ["implementer", "spec_guard", "code_reviewer", "test_guardian"]
    assert result.succeeded and result.task_ids == ["T-001"], result.reason
    assert rejected_rounds == 3
    assert _steps(executor) == chain * 4
    assert result.token_usage == 112


def test_fourth_repair_can_accept_after_four_rejected_review_rounds(slice_project):
    rejected_rounds = 0

    def reject_four_rounds(assignment, payload, root):
        nonlocal rejected_rounds
        if assignment["step"] == "spec_guard" and rejected_rounds < 4:
            rejected_rounds += 1
            payload.update(verdict="FAIL", findings=["app.py:1 wrong implementation"])

    executor = ScriptedExecutor(reject_four_rounds)
    result = _run(slice_project, executor)

    chain = ["implementer", "spec_guard", "code_reviewer", "test_guardian"]
    assert result.succeeded and result.task_ids == ["T-001"], result.reason
    assert rejected_rounds == 4
    assert _steps(executor) == chain * 5
    assert result.token_usage == 140


def test_four_rejected_rounds_replay_only_one_new_round(slice_project, monkeypatch):
    def reject(assignment, payload, root):
        if assignment["step"] == "spec_guard":
            payload.update(verdict="FAIL", findings=["app.py:1 wrong implementation"])

    first_executor = ScriptedExecutor(reject)
    with monkeypatch.context() as old_cap:
        old_cap.setattr("harness.delivery_slice_runner.MAX_GATE_ROUNDS", 4)
        old_cap.setattr("harness.delivery_slice_journal.MAX_GATE_ROUNDS", 4)
        first = _run(slice_project, first_executor)
    assert first.status == "blocked" and not first.task_ids
    assert len(first_executor.calls) == 16

    resumed_executor = ScriptedExecutor()
    resumed = _run(slice_project, resumed_executor, journal_required=True)

    assert resumed.succeeded and resumed.task_ids == ["T-001"], resumed.reason
    assert _steps(resumed_executor) == [
        "implementer", "spec_guard", "code_reviewer", "test_guardian",
    ]
    assert resumed.token_usage == 140
    journal = json.loads(next(slice_project[2].rglob("journal.json")).read_text())
    assert len(journal["records"]) == 20


def test_exhausted_repair_journal_resumes_with_only_new_round_dispatches(slice_project):
    def reject(assignment, payload, root):
        if assignment["step"] == "spec_guard":
            payload.update(verdict="FAIL", findings=["app.py:1 wrong implementation"])

    first_executor = ScriptedExecutor(reject)
    first = _run(
        slice_project, first_executor,
        stop_requested=lambda: len(first_executor.calls) >= 12,
    )
    assert first.status == "blocked" and not first.task_ids
    assert len(first_executor.calls) == 12

    resumed_executor = ScriptedExecutor()
    resumed = _run(slice_project, resumed_executor, journal_required=True)

    assert resumed.succeeded and resumed.task_ids == ["T-001"], resumed.reason
    assert _steps(resumed_executor) == [
        "implementer", "spec_guard", "code_reviewer", "test_guardian",
    ]
    assert resumed.token_usage == 112
    journal = json.loads(next(slice_project[2].rglob("journal.json")).read_text())
    assert len(journal["records"]) == 16


@pytest.mark.parametrize("fault", ["degraded", "skip", "stale", "malformed", "exit", "timeout",
                                  "candidate_mutation", "spec_mutation", "blocked"])
def test_invalid_review_stops_without_following_gate(slice_project, fault):
    def script(assignment, payload, root):
        if assignment["step"] != "code_reviewer":
            return
        if fault == "degraded": payload["verdict"] = "DEGRADED"
        if fault == "skip": payload["verdict"] = "SKIP"
        if fault == "stale": payload["dispatch_id"] = "previous-call"
        if fault == "malformed": return CliRunResult(0, "done", "", token_usage=7)
        if fault == "exit": return CliRunResult(1, json.dumps(payload), "failed", token_usage=7)
        if fault == "timeout": return CliRunResult(0, json.dumps(payload), "", timed_out=True, token_usage=7)
        if fault == "candidate_mutation": (root / "app.py").write_text("reviewer edited product")
        if fault == "spec_mutation": (slice_project[1] / "spec.md").write_text("weakened spec")
        if fault == "blocked": payload["verdict"] = "BLOCKED"
    executor = ScriptedExecutor(script)
    result = _run(slice_project, executor)
    assert result.status == "blocked" and not result.task_ids
    assert _steps(executor) == ["implementer", "spec_guard", "code_reviewer"]
    assert result.token_usage == 21


def test_implementer_cannot_rewrite_task_scope(slice_project):
    def script(assignment, payload, root):
        (slice_project[1] / "tasks.md").write_text("all tasks done")
    executor = ScriptedExecutor(script)
    assert _run(slice_project, executor).status == "blocked"
    assert _steps(executor) == ["implementer"]


def test_unsupported_provider_blocks_before_implementation(slice_project):
    executor = ScriptedExecutor()
    executor.supports_read_only_review = False
    result = _run(slice_project, executor)
    assert result.status == "blocked" and not executor.calls
    assert "read_only" in result.reason


def test_missing_later_role_blocks_before_implementation(slice_project):
    (slice_project[0] / ".echelon/prosaic/subagents/echelon.delivery-test-guardian.md").unlink()
    executor = ScriptedExecutor()
    result = _run(slice_project, executor)
    assert result.status == "blocked" and not executor.calls


def test_cancellation_between_steps_never_accepts_slice(slice_project):
    executor = ScriptedExecutor()
    result = _run(slice_project, executor, stop_requested=lambda: bool(executor.calls))
    assert result.status == "blocked" and not result.task_ids
    assert _steps(executor) == ["implementer"]
    journal = json.loads(next(slice_project[2].rglob("journal.json")).read_text())
    assert journal["records"][0]["result"]["verdict"] == "DONE"
    assert journal["records"][0]["candidate_after"]
    assert journal["records"][0]["error"] is None

    resumed_executor = ScriptedExecutor()
    resumed = _run(slice_project, resumed_executor, journal_required=True)
    assert resumed.succeeded and resumed.task_ids == ["T-001"], resumed.reason
    assert _steps(resumed_executor) == ["spec_guard", "code_reviewer", "test_guardian"]


def test_prior_marker_and_receipts_cannot_substitute_for_new_reviews(slice_project):
    first = ScriptedExecutor()
    assert _run(slice_project, first).succeeded
    (slice_project[0] / ".harness-build-status.json").write_text('{"status":"done"}')
    second = ScriptedExecutor()
    assert _run(slice_project, second, operation_id="new-operation").succeeded
    assert _steps(second) == ["implementer", "spec_guard", "code_reviewer", "test_guardian"]
    assert {x[0]["dispatch_id"] for x in first.calls}.isdisjoint(x[0]["dispatch_id"] for x in second.calls)


@pytest.mark.parametrize("path", ["specs/001-slice/user-clarifications.md",
                                  "specs/001-slice/harness-run-history.json",
                                  ".echelon/config.yml",
                                  ".echelon/prosaic/subagents/echelon.delivery-spec-guard.md"])
def test_implementation_cannot_modify_protected_inputs(slice_project, path):
    target = slice_project[0] / path
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_text("Must preserve this instruction")
    def script(assignment, payload, root):
        if assignment["step"] == "implementer":
            target.write_text("Changed by implementer")
    executor = ScriptedExecutor(script)
    result = _run(slice_project, executor)
    assert result.status == "blocked" and not result.task_ids
    assert _steps(executor) == ["implementer"]


def test_user_clarifications_are_embedded_and_implementation_keeps_source_write_access(slice_project):
    (slice_project[1] / "user-clarifications.md").write_text("Never return a Spanish greeting.")
    executor = ScriptedExecutor()
    assert _run(slice_project, executor).succeeded
    assert all("Never return a Spanish greeting" in call[2] for call in executor.calls)
    implementation_metadata = executor.calls[0][1]
    assert str(slice_project[0]) not in implementation_metadata["tool_read_roots"]
    assert str(slice_project[1]) in implementation_metadata["tool_forbidden_roots"]


def test_budget_exhaustion_prevents_another_provider_dispatch(slice_project):
    executor = ScriptedExecutor()
    result = _run(slice_project, executor, token_budget=7)
    assert result.status == "blocked" and not result.task_ids
    assert result.token_usage == 7
    assert "budget_exhausted" in result.reason
    assert _steps(executor) == ["implementer"]


@pytest.mark.parametrize("budget", [None, 100])
def test_missing_usage_is_unknown_and_cannot_spend_a_finite_budget(slice_project, budget):
    def script(assignment, payload, root):
        return CliRunResult(0, json.dumps(payload), "", token_usage=None)
    executor = ScriptedExecutor(script)
    result = _run(slice_project, executor, token_budget=budget)
    assert result.token_usage is None
    if budget is not None:
        assert result.status == "blocked" and not result.task_ids
        assert "usage_unknown" in result.reason
        assert _steps(executor) == ["implementer"]
    else:
        assert result.succeeded


def test_symlinked_candidate_configuration_cannot_authorize_external_writes(slice_project, tmp_path):
    from harness.delivery_slice_runner import DeliverySliceRunner
    project, spec, evidence = slice_project
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    (candidate / "app.py").write_text("original")
    (candidate / ".echelon").symlink_to(project / ".echelon", target_is_directory=True)
    external_contract = project / ".echelon/runnability.yml"
    external_contract.write_text("original contract")
    def escape(assignment, payload, root):
        (root / ".echelon/runnability.yml").write_text("modified outside worktree")
    executor = ScriptedExecutor(escape)
    result = DeliverySliceRunner(executor, project).run(
        worktree=candidate, spec_dir=spec, evidence_root=evidence)
    assert result.status == "blocked" and not executor.calls
    assert external_contract.read_text() == "original contract"
