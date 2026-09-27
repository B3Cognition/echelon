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


def test_two_failed_repairs_block_without_degraded_progress(slice_project):
    def script(assignment, payload, root):
        if assignment["step"] == "spec_guard":
            payload.update(verdict="FAIL", findings=["app.py:1 wrong implementation"])
    executor = ScriptedExecutor(script)
    result = _run(slice_project, executor)
    chain = ["implementer", "spec_guard", "code_reviewer", "test_guardian"]
    assert _steps(executor) == chain * 3
    assert result.status == "blocked" and not result.task_ids
    assert "repair_limit" in result.reason
    assert result.token_usage == 84


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
