"""Controlled roles, real candidate verification, and host-owned publication."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.e2e.controlled_ralph import CHAIN, ControlledGitOps


@pytest.mark.e2e
@pytest.mark.parametrize("missing_case", ["zero", "skipped"])
def test_controlled_observer_never_reports_an_unexecuted_case_as_passed(tmp_path, missing_case):
    root = tmp_path / "project"
    root.mkdir()
    ControlledGitOps._write_project(root)
    test_file = root / "tests/test_app.py"
    if missing_case == "zero":
        test_file.write_text("import unittest\n")
    else:
        test_file.write_text(test_file.read_text().replace(
            "    def test_divide(self):", "    @unittest.skip('not executed')\n    def test_divide(self):",
        ))
    report = tmp_path / "report.json"

    result = subprocess.run(
        [sys.executable, "-B", "tests/emit_coverage_json.py", str(report)],
        cwd=root, capture_output=True, text=True, check=False,
    )

    assert result.returncode != 0
    assert json.loads(report.read_text())["testResults"][0]["assertionResults"][0]["status"] != "passed"


@pytest.mark.e2e
class TestRalphConvergence:
    def test_converges_within_3_outer_iterations(self, controlled_ralph):
        run = controlled_ralph(mode="semi")
        run.initialize(budget=100_000)
        result = run.run(budget=100_000)
        assert result.status == "verified", (result, run.store.read())
        assert result.termination_reason == "converged"
        assert result.outer_iterations <= 3
        assert run.steps == CHAIN + ["tech_writer", "docs_verifier"]
        assert getattr(run.provider, "observer_executions", []), "Required coverage observer must run"
        assert run.gitops.local_merges[-1]["default_branch"] == "main"
        assert run.legacy_stub.call_count == 0

    def test_pr_created_and_promoted_only_after_complete_evidence(self, controlled_ralph):
        run = controlled_ralph(mode="semi")
        run.initialize()
        result = run.run()
        assert result.status == "verified"
        assert run.gitops.pr_created and run.gitops.pr_promoted
        assert result.pr_url == run.gitops.pr_url
        assert "return a / b" in (run.gitops.source / "app.py").read_text()
        spec = run.root / "specs/test-spec"
        assert "| FR-001 | IMPLEMENTED |" in (spec / "fulfillment-report.md").read_text()
        assert "verdict: PASS" in (spec / "docs-verification-report.md").read_text()
        assert (spec / "verified-fulfillment-ledger.json").is_file()
        assert run.provider.executions and all(call[1] == 0 for call in run.provider.executions)
        assert set(run.provider.created) == set(run.provider.destroyed)

    def test_phase_result_keeps_delivery_state_running(self, controlled_ralph):
        run = controlled_ralph()
        run.initialize()
        result = run.run()
        assert result.status == "verified"
        state = run.store.read()
        assert state["status"] == "running"
        assert state["termination_reason"] == "converged"
        assert state["build"]["completed_tasks"] == 1

    def test_iteration_log_records_actual_build_verify_and_docs_repair(self, controlled_ralph):
        run = controlled_ralph()
        run.initialize()
        assert run.run().status == "verified"
        log = run.store.read()["iteration_log"]
        assert {entry["phase"] for entry in log} >= {"build", "verify", "fix"}
        for entry in log:
            assert {"outer_iter", "phase", "exit_code", "passed", "duration_s", "tokens", "timestamp"} <= entry.keys()
        receipts = list((run.root / "runs/evidence/verification").glob("attempt-*.json"))
        assert len(receipts) == len(run.provider.executions)
        assert all(json.loads(path.read_text())["status"] == "passed" for path in receipts)

    def test_exact_usage_includes_fulfillment_and_verifier_without_double_charging(self, controlled_ralph):
        run = controlled_ralph(tokens=37)
        run.initialize()
        result = run.run()
        assert result.status == "verified"
        assert run.executor.inspections, "Fulfillment inspection must actually execute"
        model_usage = 37 * (len(run.executor.calls) + len(run.executor.inspections))
        verifier_usage = sum((len(stdout) + len(stderr)) // 4
                             for _, _, stdout, stderr in run.provider.executions)
        expected = model_usage + verifier_usage
        assert result.tokens_used == run.store.read()["tokens_used"] == expected

    def test_no_source_or_host_changes_before_verified_landing(self, controlled_ralph):
        run = controlled_ralph(reject_reviews=True)
        source = (run.gitops.source / "app.py").read_bytes()
        roles = {path: path.read_bytes() for path in (run.root / ".echelon").rglob("*.md")}
        run.initialize()
        assert run.run().status == "blocked"
        assert (run.gitops.source / "app.py").read_bytes() == source
        assert all(path.read_bytes() == body for path, body in roles.items())
        assert not run.gitops.local_merges
        assert not (run.root / "app.py").exists()

    def test_authoritative_verifier_catches_accepted_bad_candidate_then_repair_converges(self, controlled_ralph):
        # Script an optimistic model review; only the real verifier decides acceptance.
        run = controlled_ralph(wrong_builds=1, mode="semi")
        run.initialize(budget=100_000)
        result = run.run(budget=100_000)
        assert result.status == "verified", (result, run.store.read())
        assert result.inner_iterations >= 2
        assert run.steps == CHAIN * 2 + ["tech_writer", "docs_verifier"]
        assert run.provider.executions[0][1] != 0
        assert "20 != 5" in run.provider.executions[0][3]
        assert run.provider.executions[-1][1] == 0
        repair_prompt = run.executor.calls[4][1]
        assert "controlled_source_repair_v1" in repair_prompt
        assert "20 != 5" in repair_prompt
        assert "return a / b" in Path(run.gitops.source, "app.py").read_text()
