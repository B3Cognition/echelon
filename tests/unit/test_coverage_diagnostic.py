import json
import pytest
from pathlib import Path
from types import SimpleNamespace

from harness.verify_result import VerifyResult, FailureEntry, FailureCategory


def setup_review(tmp_path):
    target = tmp_path / "target"
    spec = tmp_path / "specs" / "001-demo"
    target.mkdir()
    spec.mkdir(parents=True)
    (target / "test.ts").write_text("expect(actual).toBe(1);\n")
    (spec / "spec.md").write_text("- **FR-001**: Save one item.\n")
    (spec / "coverage-map.md").write_text("# Coverage\n")
    failure = VerifyResult(passed=False, failures=[FailureEntry(
        FailureCategory.OTHER, "coverage-observation-gaps", "unbound",
    )])
    calls = []
    def execute(cwd, prompt, **kwargs):
        calls.append((cwd, prompt, kwargs))
        return SimpleNamespace(exit_code=0, timed_out=False, stdout=json.dumps({
            "findings": [{"requirement_id": "FR-001", "disposition": "matching_test",
                          "reason": "Tests the saved item count", "evidence": ["test.ts:1"]}]
        }))
    executor = SimpleNamespace(supports_read_only_review=True, run_agent_result=execute)
    return dict(workspace=tmp_path, target=target, spec_dir=spec,
                verify_run_dir=tmp_path / "runs" / "verify-1", result=failure,
                executor=executor, agent_body="TEST GUARDIAN"), calls


def test_diagnostic_is_advisory_bounded_and_does_not_repeat(tmp_path):
    from harness.coverage_diagnostic import run_coverage_diagnostic
    kwargs, calls = setup_review(tmp_path)
    before = (kwargs["spec_dir"] / "coverage-map.md").read_bytes()
    path = run_coverage_diagnostic(**kwargs)
    report = json.loads(path.read_text())
    assert report["status"] == "advisory"
    assert report["findings"][0]["disposition"] == "matching_test"
    assert not kwargs["result"].passed
    assert (kwargs["spec_dir"] / "coverage-map.md").read_bytes() == before
    assert not (kwargs["spec_dir"] / "verified-fulfillment-ledger.json").exists()
    assert run_coverage_diagnostic(**kwargs) == path
    assert len(calls) == 1
    metadata = calls[0][2]["request_metadata"]["prompt_metadata"]
    assert metadata["tool_write_scope_exclusive"] is True
    assert metadata["tool_write_paths"] == []
    assert 0 < calls[0][2]["timeout_ms"] <= 120_000


def test_success_and_unrelated_failure_do_not_dispatch(tmp_path):
    from harness.coverage_diagnostic import run_coverage_diagnostic
    kwargs, calls = setup_review(tmp_path)
    kwargs["result"] = VerifyResult(passed=True)
    assert run_coverage_diagnostic(**kwargs) is None
    kwargs["result"] = VerifyResult(passed=False)
    assert run_coverage_diagnostic(**kwargs) is None
    assert calls == []


def test_unsupported_boundary_skips_provider(tmp_path):
    from harness.coverage_diagnostic import run_coverage_diagnostic
    kwargs, calls = setup_review(tmp_path)
    kwargs["executor"].supports_read_only_review = False
    path = run_coverage_diagnostic(**kwargs)
    assert json.loads(path.read_text())["status"] == "unsupported_read_only_boundary"
    assert calls == []


def test_stale_receipt_skips_provider_without_rewriting_evidence(tmp_path):
    from harness.coverage_diagnostic import run_coverage_diagnostic
    kwargs, calls = setup_review(tmp_path)
    kwargs["result"].verification_evidence = {"candidate_fingerprint": "older-product"}
    path = run_coverage_diagnostic(**kwargs)
    assert json.loads(path.read_text())["status"] == "stale_evidence"
    assert calls == []
    assert kwargs["result"].verification_evidence["candidate_fingerprint"] == "older-product"


def test_diagnostic_rejects_false_completion_and_external_citations(tmp_path):
    from harness.coverage_diagnostic import run_coverage_diagnostic
    kwargs, _ = setup_review(tmp_path)
    kwargs["executor"].run_agent_result = lambda *a, **k: SimpleNamespace(
        exit_code=0, timed_out=False, stdout=json.dumps({"findings": [
            {"requirement_id": "FR-001", "disposition": "complete", "reason": "passed",
             "evidence": ["/etc/passwd:1"]}]}))
    report = json.loads(run_coverage_diagnostic(**kwargs).read_text())
    assert report["status"] == "invalid_output"
    assert report["findings"] == []


def test_timeout_does_not_change_original_failure(tmp_path):
    from harness.coverage_diagnostic import run_coverage_diagnostic
    kwargs, _ = setup_review(tmp_path)
    kwargs["executor"].run_agent_result = lambda *a, **k: SimpleNamespace(
        exit_code=1, timed_out=True, stdout="")
    report = json.loads(run_coverage_diagnostic(**kwargs).read_text())
    assert report["status"] == "provider_failed"
    assert report["provider_failure"] == {"exit_code": 1, "timed_out": True, "stderr_tail": ""}
    assert kwargs["result"].failures[0].id == "coverage-observation-gaps"


@pytest.mark.parametrize("citation", ["/etc/passwd:1", "../outside.ts:1", "test.ts:999", "test.ts:0"])
def test_matching_test_cannot_cite_outside_candidate(tmp_path, citation):
    from harness.coverage_diagnostic import run_coverage_diagnostic
    kwargs, _ = setup_review(tmp_path)
    kwargs["executor"].run_agent_result = lambda *a, **k: SimpleNamespace(
        exit_code=0, timed_out=False, stdout=json.dumps({"findings": [
            {"requirement_id": "FR-001", "disposition": "matching_test", "reason": "assertion",
             "evidence": [citation]}]}))
    assert json.loads(run_coverage_diagnostic(**kwargs).read_text())["status"] == "invalid_output"


def test_changed_candidate_invalidates_advice(tmp_path):
    from harness.coverage_diagnostic import run_coverage_diagnostic
    kwargs, _ = setup_review(tmp_path)
    def execute(*a, **k):
        (kwargs["target"] / "test.ts").write_text("changed\n")
        return SimpleNamespace(exit_code=0, timed_out=False, stdout='{"findings": []}')
    kwargs["executor"].run_agent_result = execute
    assert json.loads(run_coverage_diagnostic(**kwargs).read_text())["status"] == "inputs_changed"


def test_requirement_budget_does_not_claim_omitted_rows_reviewed(tmp_path):
    from harness.coverage_diagnostic import run_coverage_diagnostic
    kwargs, _ = setup_review(tmp_path)
    (kwargs["spec_dir"] / "spec.md").write_text("\n".join(
        f"- **FR-{n:03}**: Save item {n}." for n in range(1, 26)))
    report = json.loads(run_coverage_diagnostic(**kwargs).read_text())
    assert report["reviewed_requirement_ids"] == ["FR-001"]
    assert len(report["unreviewed_requirement_ids"]) == 24


def test_workspace_target_diagnostic_does_not_invalidate_itself(tmp_path):
    from harness.coverage_diagnostic import run_coverage_diagnostic
    kwargs, calls = setup_review(tmp_path)
    kwargs["target"] = tmp_path
    (tmp_path / "test.ts").write_text("expect(actual).toBe(1);\n")
    path = run_coverage_diagnostic(**kwargs)
    assert json.loads(path.read_text())["status"] == "advisory"
    assert run_coverage_diagnostic(**kwargs) == path
    assert len(calls) == 1


def test_diagnostic_scopes_to_unresolved_requirement_beyond_budget(tmp_path):
    from harness.coverage_diagnostic import run_coverage_diagnostic
    kwargs, calls = setup_review(tmp_path)
    (kwargs["spec_dir"] / "spec.md").write_text("\n".join(
        f"- **FR-{n:03}**: Save item {n}." for n in range(1, 26)))
    kwargs["result"].failures[0].details["requirements"] = {"FR-025": "unmapped"}
    kwargs["executor"].run_agent_result = lambda *a, **k: SimpleNamespace(
        exit_code=0, timed_out=False, stdout='{"findings": []}')
    report = json.loads(run_coverage_diagnostic(**kwargs).read_text())
    assert report["unreviewed_requirement_ids"] == ["FR-025"]


def test_later_timeout_keeps_durably_saved_first_batch(tmp_path):
    from harness.coverage_diagnostic import run_coverage_diagnostic
    kwargs, _ = setup_review(tmp_path)
    (kwargs["spec_dir"] / "spec.md").write_text(
        "- **FR-001**: Save one item.\n- **FR-002**: Restore item.\n")
    original = kwargs["executor"].run_agent_result
    calls = []
    def execute(cwd, prompt, **options):
        calls.append(prompt)
        if len(calls) == 1:
            return original(cwd, prompt, **options)
        saved = json.loads(next(kwargs["verify_run_dir"].rglob("report.json")).read_text())
        assert saved["reviewed_requirement_ids"] == ["FR-001"]
        assert saved["findings"][0]["requirement_id"] == "FR-001"
        return SimpleNamespace(exit_code=-1, timed_out=True, stdout="", stderr="deadline")
    kwargs["executor"].run_agent_result = execute
    report = json.loads(run_coverage_diagnostic(**kwargs).read_text())
    assert len(calls) == 2
    assert report["status"] == "advisory"
    assert report["stop_reason"] == "budget_exhausted"
    assert report["reviewed_requirement_ids"] == ["FR-001"]
    assert report["unreviewed_requirement_ids"] == ["FR-002"]
    assert report["provider_failure"]["timed_out"] is True


def test_overall_deadline_does_not_restart_for_each_batch(tmp_path, monkeypatch):
    import harness.coverage_diagnostic as diagnostic
    kwargs, _ = setup_review(tmp_path)
    (kwargs["spec_dir"] / "spec.md").write_text(
        "- **FR-001**: Save one item.\n- **FR-002**: Restore item.\n- **FR-003**: Delete item.\n")
    clock = [0.0]
    monkeypatch.setattr(diagnostic, "monotonic", lambda: clock[0], raising=False)
    timeouts = []
    def execute(cwd, prompt, **options):
        timeouts.append(options["timeout_ms"])
        identity = f"FR-{len(timeouts):03}"
        clock[0] += 70
        return SimpleNamespace(exit_code=0, timed_out=False, stdout=json.dumps({
            "findings": [{"requirement_id": identity, "disposition": "matching_test",
                          "reason": "count assertion", "evidence": ["test.ts:1"]}]}))
    kwargs["executor"].run_agent_result = execute
    report = json.loads(diagnostic.run_coverage_diagnostic(**kwargs).read_text())
    assert timeouts == [120_000, 50_000]
    assert report["stop_reason"] == "budget_exhausted"
    assert report["reviewed_requirement_ids"] == ["FR-001", "FR-002"]
    assert report["unreviewed_requirement_ids"] == ["FR-003"]


@pytest.mark.parametrize("failure", ["malformed", "changed", "changed_exception", "unreadable"])
def test_later_invalid_batch_never_adds_unvalidated_findings(tmp_path, failure):
    from harness.coverage_diagnostic import run_coverage_diagnostic
    kwargs, _ = setup_review(tmp_path)
    (kwargs["spec_dir"] / "spec.md").write_text(
        "- **FR-001**: Save one item.\n- **FR-002**: Restore item.\n")
    original = kwargs["executor"].run_agent_result
    calls = []
    def execute(cwd, prompt, **options):
        calls.append(prompt)
        if len(calls) == 1:
            return original(cwd, prompt, **options)
        if failure in {"changed", "changed_exception"}:
            (kwargs["target"] / "test.ts").write_text("changed\n")
        if failure == "changed_exception":
            raise RuntimeError("provider stopped")
        if failure == "unreadable":
            (kwargs["spec_dir"] / "spec.md").write_bytes(b"\xff")
        return SimpleNamespace(exit_code=0, timed_out=False, stdout="not JSON")
    kwargs["executor"].run_agent_result = execute
    report = json.loads(run_coverage_diagnostic(**kwargs).read_text())
    assert len(calls) == 2
    if failure != "malformed":
        assert report["status"] == "inputs_changed"
        assert report["findings"] == []
        assert report["reviewed_requirement_ids"] == []
    else:
        assert report["status"] == "advisory"
        assert report["stop_reason"] == "invalid_output"
        assert report["reviewed_requirement_ids"] == ["FR-001"]
    assert "FR-002" in report["unreviewed_requirement_ids"]
    if failure == "malformed":
        assert run_coverage_diagnostic(**kwargs) == next(kwargs["verify_run_dir"].rglob("report.json"))
        assert len(calls) == 2
