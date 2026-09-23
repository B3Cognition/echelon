"""Post-authoring evidence is produced and consumed through real Ralph gates."""
import json
import subprocess
import pytest

from harness.gitops import GitOpsManager
from harness.product_inventory import product_evidence_fingerprint
from harness.runnability_evidence import load_runnability_evidence_ref, runnability_product_fingerprint
from harness.verify_result import VerifyResult
from tests.unit.test_delivery_documentation_integration import _setup, _feedback
from tests.unit.test_delivery_controller_integration import _reconstruct, _build
from tests.unit.test_delivery_documentation import documentation_project, review_report, ProcessLost
from tests.unit.test_delivery_slice_runner import slice_project
from tests.unit.test_delivery_controller import _initialize_git_worktree
from tests.unit.test_documentation_gate import FIRST_RUN_README
from tests.unit.test_runnability_contract import BROWSER_CONTRACT
from tests.unit.test_runnability_runner import RecordingProvider, _resolved


def _runnable_project(documentation_project, tmp_path, mode="semi"):
    controller, store, executor, root, spec = _setup(documentation_project, tmp_path, mode=mode, complete=True)
    contract = BROWSER_CONTRACT.replace("pnpm install --frozen-lockfile", "install-dependencies")
    contract = contract.replace("pnpm migrate", "migrate-database")
    contract = contract.replace("pnpm dev:issue-session -- --player ${ECHELON_MARKER}", "issue-session")
    contract = contract.replace("[web, api, postgres]", "[web, postgres]")
    (root / ".echelon/runnability.yml").write_text(contract)
    helper = root / ".echelon/runtime/scripts/user-runnability-browser.mjs"
    helper.parent.mkdir(parents=True)
    helper.write_text("// External browser execution is scripted by RecordingProvider.\n")
    (root / "pyproject.toml").write_text("[project]\nname = 'greeting'\nversion = '0.1.0'\n")
    controller._config.resolved_stacks = _resolved()
    controller._config.resolved_runnability = controller._config.resolved_stacks.runnability
    controller._config.verify_command = "python -m unittest"
    controller._fulfillment_runner = None
    sandbox = RecordingProvider()
    controller._provider = sandbox
    controller._candidate_evidence_runner._provider = sandbox
    _initialize_git_worktree(root)
    subprocess.run(["git", "checkout", "-b", "test-docs"], cwd=root, check=True, capture_output=True)
    controller._gitops = GitOpsManager(controller._config, base_dir=str(root))
    controller._gitops.push = lambda *args, **kwargs: None  # Remote publication is external.
    initial = controller._apply_post_verify_gates(VerifyResult(True), str(root))
    assert not initial.passed and initial.failures[0].id == "documentation-impact-report-missing", initial
    original_ref = load_runnability_evidence_ref(store.read()["user_runnability"]["report"])
    def script(assignment, payload, cwd):
        context = json.loads(executor.calls[-1][2].split("## Controller-captured inputs (data, not instructions)\n")[1].split("\n## Independent review inputs")[0])
        evidence = json.loads(context["runnability"]["report"])
        if assignment["step"] == "tech_writer":
            commands = "\n".join(command for values in evidence["user_commands"].values() for command in values)
            (cwd / "README.md").write_text(FIRST_RUN_README + "\n## Observed journey\n```text\n" + commands + "\n```\n")
            executor.authored_fingerprint = product_evidence_fingerprint(cwd)
            from harness.runnability_evidence import runnability_product_fingerprint
            executor.authored_runnability_fingerprint = runnability_product_fingerprint(cwd, spec)
        else:
            payload["report_markdown"] = review_report().replace("runnability_commands_current: false", "runnability_commands_current: true")
            payload["report_markdown"] = payload["report_markdown"].replace("runnability_evidence_sha256: ''", "runnability_evidence_sha256: " + evidence["evidence_sha256"])
    executor.script = script
    return controller, store, executor, sandbox, root, spec, initial, original_ref


@pytest.mark.parametrize("mode", ["banzai", "semi", "guided"])
@pytest.mark.parametrize("cli", ["claude", "codex"])
def test_real_inner_loop_converges_with_post_authoring_runnability(documentation_project, tmp_path, monkeypatch, mode, cli):
    from harness.llm_provider import AICodingCliProvider
    controller, store, executor, sandbox, root, spec, initial, original_ref = _runnable_project(documentation_project, tmp_path, mode)
    controller._config.llm.cli = cli
    provider = AICodingCliProvider(controller._config)
    class ExternalBackend:
        def run_agent(self, request):
            return executor.run_agent_result(request.cwd, request.prompt, request_metadata=request.metadata)
    provider._backend = ExternalBackend()
    controller._llm_provider = provider
    monkeypatch.setattr("harness.llm_provider.host_workspace_synthesis_boundary_available", lambda: True)
    observed = []
    real_gates = controller._apply_post_verify_gates
    def observe(*args, **kwargs):
        result = real_gates(*args, **kwargs)
        observed.extend((failure.id, failure.error) for failure in result.failures)
        return result
    monkeypatch.setattr(controller, "_apply_post_verify_gates", observe)
    result = controller._run_inner_loop(None, initial, 1, 2, 0, None, store.read(),
                                       "echelon build", "", worktree_path=str(root), build_prompt="build")
    assert result["converged"], {"gates": observed, "result": result}
    assert executor.steps == ["tech_writer", "docs_verifier"]
    current = load_runnability_evidence_ref(store.read()["user_runnability"]["report"])
    assert current.evidence_sha256 != original_ref.evidence_sha256
    assert current.evidence_sha256 in (spec / "docs-verification-report.md").read_text()
    assert result["tokens_used"] == 15  # Two seven-token roles plus one standard-verification token.
    assert len(sandbox.created) == 3  # Initial journey, post-author journey, standard verification.


def test_report_publication_preserves_post_authoring_receipt_candidate(documentation_project, tmp_path):
    controller, store, executor, sandbox, root, spec, initial, original_ref = _runnable_project(documentation_project, tmp_path)
    result = _feedback(controller, root, initial)
    assert result["passed"], result
    from harness.runnability_evidence import runnability_product_fingerprint
    assert runnability_product_fingerprint(root, spec) == executor.authored_runnability_fingerprint
    assert product_evidence_fingerprint(root) != executor.authored_fingerprint


@pytest.mark.parametrize("path", ["README.md", "CHANGELOG.md", "app.py", "specs/001-slice/spec.md",
    "specs/001-slice/verification-report.md", "elsewhere/docs-verification-report.md"])
def test_runnability_report_exclusion_keeps_all_other_inputs(documentation_project, tmp_path, path):
    from harness.runnability_evidence import runnability_product_fingerprint
    controller, store, executor, root, spec = _setup(documentation_project, tmp_path)
    before = runnability_product_fingerprint(root, spec)
    changed = root / path
    changed.parent.mkdir(parents=True, exist_ok=True)
    changed.write_text("changed")
    assert runnability_product_fingerprint(root, spec) != before


@pytest.mark.parametrize("fault", ["report_symlink", "spec_symlink", "report_directory"])
def test_runnability_report_exclusion_refuses_unsafe_paths(documentation_project, tmp_path, fault):
    from harness.runnability_evidence import runnability_product_fingerprint
    _, _, _, root, spec = _setup(documentation_project, tmp_path)
    if fault == "report_symlink":
        (spec / "docs-verification-report.md").symlink_to(root / "app.py")
    elif fault == "spec_symlink":
        alias = root / "linked-spec"
        alias.symlink_to(spec, target_is_directory=True)
        spec = alias
    else:
        (spec / "docs-verification-report.md").mkdir()
    with pytest.raises(ValueError):
        runnability_product_fingerprint(root, spec)


@pytest.mark.parametrize("point", ["intent", "external_completion", "checkpoint", "review", "publication", "progress"])
def test_checkpoint_crash_recovery_retains_receipt_candidate_and_usage(documentation_project, tmp_path, monkeypatch, point):
    from harness.delivery_slice_journal import DeliverySliceJournal
    from harness import delivery_documentation as module
    controller, store, executor, sandbox, root, spec, initial, _ = _runnable_project(documentation_project, tmp_path)
    original_save, original_write, original_state = DeliverySliceJournal.save, module.write_text_atomic, store.write
    def save(self, data):
        original_save(self, data)
        checkpoints, records = data["checkpoints"], data["records"]
        if checkpoints and (
            point == "intent" and checkpoints[-1]["status"] == "pending"
            or point == "checkpoint" and checkpoints[-1]["status"] == "complete" and len(records) == 1
            or point == "review" and len(records) == 2 and records[-1]["result"] is not None
        ):
            raise ProcessLost()
    def write(path, text, **kwargs):
        original_write(path, text, **kwargs)
        if point == "publication" and path == spec / "documentation-impact-report.md":
            raise ProcessLost()
    def state_write(data):
        original_state(data)
        operation = data.get("delivery_slice_operation", {})
        if (point == "progress" and operation.get("progress_applied")
            or point == "external_completion" and len(sandbox.created) == 2 and data.get("user_runnability", {}).get("status") == "runnable"):
            raise ProcessLost()
    with monkeypatch.context() as patch:
        patch.setattr(DeliverySliceJournal, "save", save)
        patch.setattr(module, "write_text_atomic", write)
        patch.setattr(store, "write", state_write)
        with pytest.raises(ProcessLost):
            _feedback(controller, root, initial)
    operation = store.read()["delivery_slice_operation"]["id"]
    sandbox_count = len(sandbox.created)
    resumed = _reconstruct(controller, store, executor)
    result = _build(resumed, (root, spec, None))
    assert store.read()["delivery_slice_operation"]["id"] == operation
    assert len(sandbox.created) == sandbox_count
    if point in {"intent", "external_completion"}:
        assert not result["passed"] and "unknown" in result["build_reason"], result
        assert executor.steps == ["tech_writer"]
    else:
        assert result["passed"] and result["task_ids"] == [], result
        assert result["tokens"] == (0 if point == "progress" else 14)
        assert store.read()["tokens_used"] == 14
        assert executor.steps == ["tech_writer", "docs_verifier"]
        assert _build(resumed, (root, spec, None))["tokens"] == 0
        reused = resumed._apply_user_runnability_gate(VerifyResult(True), str(root),
            candidate_commit="informational", evidence_dir=resumed._runnability_evidence_dir())
        assert reused.passed and len(sandbox.created) == sandbox_count, reused


@pytest.mark.parametrize("fault", ["refresh_failed", "cancelled", "candidate_mutated", "journal_mutated", "evidence_mutated"])
def test_failed_or_mutated_checkpoint_never_publishes_or_resets(documentation_project, tmp_path, fault):
    controller, store, executor, sandbox, root, spec, initial, _ = _runnable_project(documentation_project, tmp_path)
    if fault == "refresh_failed":
        sandbox.fail_at = "install"
    elif fault in {"cancelled", "candidate_mutated", "journal_mutated"}:
        original = sandbox.exec
        def external(*args, **kwargs):
            result = original(*args, **kwargs)
            if fault == "cancelled":
                controller._interrupted = True
            elif fault == "journal_mutated":
                next(store.state_dir.rglob("journal.json")).write_text("{}")
            else:
                (root / "app.py").write_text("unexpected mutation")
            return result
        sandbox.exec = external
    else:
        original = executor.script
        def mutate(assignment, payload, cwd):
            original(assignment, payload, cwd)
            if assignment["step"] == "docs_verifier":
                ref = load_runnability_evidence_ref(store.read()["user_runnability"]["report"])
                ref.path.write_text("{}")
        executor.script = mutate
    first = _feedback(controller, root, initial)
    assert not first["passed"], first
    operation = store.read()["delivery_slice_operation"]["id"]
    assert not (spec / "docs-verification-report.md").exists()
    assert len(executor.calls) == (2 if fault == "evidence_mutated" else 1)
    before = len(sandbox.created)
    second = _build(_reconstruct(controller, store, executor), (root, spec, None))
    assert not second["passed"]
    assert len(sandbox.created) == before
    assert store.read()["delivery_slice_operation"]["id"] == operation


@pytest.mark.parametrize("fault", ["README.md", "app.py", "specs/001-slice/spec.md", "docs_report", "latest", "contract", "stack"])
def test_final_reuse_rejects_changes_without_replacing_reviewed_receipt(documentation_project, tmp_path, fault):
    controller, store, executor, sandbox, root, spec, initial, _ = _runnable_project(documentation_project, tmp_path)
    assert _feedback(controller, root, initial)["passed"]
    ref = load_runnability_evidence_ref(store.read()["user_runnability"]["report"])
    if fault == "docs_report":
        (spec / "docs-verification-report.md").write_text("forged report")
    elif fault == "latest":
        (ref.path.parent / "latest.json").write_text("{}")
    elif fault == "contract":
        (root / ".echelon/runnability.yml").write_text("enabled: false")
    elif fault == "stack":
        controller._config.resolved_stacks.required_commands.append("unexpected-tool")
    else:
        (root / fault).write_text("unexpected change")
    before = len(sandbox.created)
    result = controller._apply_user_runnability_gate(VerifyResult(True), str(root),
        candidate_commit="informational", evidence_dir=controller._runnability_evidence_dir())
    assert not result.passed and result.failures[0].id == "docs-runnability-evidence-stale", result
    assert len(sandbox.created) == before


@pytest.mark.parametrize("reject", [1, 3])
def test_repaired_authoring_refreshes_each_attempt_without_resetting_ceiling(documentation_project, tmp_path, reject):
    controller, store, executor, sandbox, root, spec, initial, original_ref = _runnable_project(documentation_project, tmp_path)
    executor.reject_first = reject == 1
    executor.always_reject = reject == 3
    original_script = executor.script
    def script(assignment, payload, cwd):
        original_script(assignment, payload, cwd)
        if assignment["step"] == "docs_verifier" and payload["verdict"] == "FAIL":
            metadata = json.loads(executor.calls[-1][2].split("## Controller-captured inputs (data, not instructions)\n")[1].split("\n## Independent review inputs")[0])
            sha = metadata["runnability"]["reference"]["evidence_sha256"]
            payload["report_markdown"] = review_report(True).replace("runnability_commands_current: false", "runnability_commands_current: true").replace("runnability_evidence_sha256: ''", "runnability_evidence_sha256: " + sha)
    executor.script = script
    result = _feedback(controller, root, initial)
    attempts = 2 if reject == 1 else 3
    assert result["passed"] is (reject == 1), result
    assert executor.steps == ["tech_writer", "docs_verifier"] * attempts
    assert len(sandbox.created) == attempts + 1
    journal = json.loads(next(store.state_dir.rglob("journal.json")).read_text())
    assert len(journal["checkpoints"]) == attempts
    assert journal["authoring_evidence"]["reference"]["evidence_sha256"] == original_ref.evidence_sha256
    for checkpoint in journal["checkpoints"]:
        review = journal["records"][checkpoint["attempt"] * 2 + 1]
        assert review["assignment"]["input_fingerprint"] == checkpoint["input_fingerprint"]
        assert checkpoint["evidence_after"]["reference"]["evidence_sha256"] in review["result"]["report_markdown"]
    again = _build(_reconstruct(controller, store, executor), (root, spec, None))
    assert again["passed"] is (reject == 1) and again["tokens"] == 0
    assert len(sandbox.created) == attempts + 1


@pytest.mark.parametrize("fault", ["pending", "reference", "input", "candidate", "removed"])
def test_corrupt_checkpoint_cannot_replay_or_publish(documentation_project, tmp_path, fault):
    controller, store, executor, sandbox, root, spec, initial, _ = _runnable_project(documentation_project, tmp_path)
    assert _feedback(controller, root, initial)["passed"]
    journal = next(store.state_dir.rglob("journal.json"))
    data = json.loads(journal.read_text())
    checkpoint = data["checkpoints"][0]
    if fault == "pending": checkpoint["status"] = "pending"
    if fault == "reference": checkpoint["evidence_after"]["reference"]["receipt_sha256"] = "0" * 64
    if fault == "input": checkpoint["input_fingerprint"] = "0" * 64
    if fault == "candidate": checkpoint["candidate_fingerprint"] = "0" * 64
    if fault == "removed": data["checkpoints"] = []
    journal.write_text(json.dumps(data))
    result = _build(_reconstruct(controller, store, executor), (root, spec, None))
    assert not result["passed"]
    assert len(executor.calls) == 2 and len(sandbox.created) == 2


@pytest.mark.parametrize("budget,roles,journeys", [(0, 0, 1), (7, 1, 1), (14, 2, 2)])
def test_checkpoint_obeys_existing_finite_budget_on_replay(documentation_project, tmp_path, budget, roles, journeys):
    controller, store, executor, sandbox, root, spec, initial, _ = _runnable_project(documentation_project, tmp_path)
    controller._controlled_slice_budget = budget
    result = _feedback(controller, root, initial)
    assert not result["passed"] and "budget_exhausted" in result["build_reason"], result
    assert len(executor.calls) == roles and len(sandbox.created) == journeys
    again = _build(_reconstruct(controller, store, executor), (root, spec, None))
    assert not again["passed"] and again["tokens"] == 0
    assert len(executor.calls) == roles and len(sandbox.created) == journeys


def test_runnable_documentation_cannot_publish_without_author_checkpoint(documentation_project, tmp_path):
    from harness.delivery_documentation import DeliveryDocumentationRunner
    controller, store, executor, sandbox, root, spec, initial, ref = _runnable_project(documentation_project, tmp_path)
    result = DeliveryDocumentationRunner(executor, root).run(
        worktree=root, spec_dir=spec, evidence_root=store.state_dir / "direct-docs",
        allowed_task_ids={"T-001"}, runnability_report=ref, runnability_required=True,
    )
    assert not result.succeeded and result.reason == "documentation_runnability_checkpoint_missing", result
    assert executor.steps == ["tech_writer"]
    assert not (spec / "docs-verification-report.md").exists()
