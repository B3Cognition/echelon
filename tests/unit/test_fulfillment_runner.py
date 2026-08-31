"""Tests for fulfillment verification prompt orchestration."""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from harness.fulfillment_runner import FULFILLMENT_VERIFIER_VERSION, FulfillmentRunner
from harness.llm_provider import AICodingCliProvider
from harness.product_inventory import product_evidence_fingerprint
from harness.prosaic_prompt_loader import ProsaicCommandArtifact, ProsaicPromptLoader
from harness.verification_evidence import VerificationStage
from harness.verification_evidence import write_verification_receipt
from kernel.fulfillment import read_fulfillment_metadata


def _write_verify_skill(root):
    commands_dir = root / ".echelon" / "prosaic" / "commands"
    commands_dir.mkdir(parents=True)
    (commands_dir / "echelon.verify-spec.md").write_text(
        "---\ndescription: Verify spec\n---\nverify {{args}}\n",
        encoding="utf-8",
    )


@pytest.fixture(autouse=True)
def _inspect_verify_spec_with_prosaic(monkeypatch):
    monkeypatch.setattr(
        ProsaicPromptLoader,
        "load_command",
        lambda _self, _command_id: ProsaicCommandArtifact(
            frontmatter={"description": "Verify spec"},
            body="verify {{args}}",
        ),
    )


def _write_spec_inputs(spec_dir, *, tasks: str = "# Tasks\n") -> None:
    spec_dir.mkdir(parents=True, exist_ok=True)
    (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")
    (spec_dir / "plan.md").write_text("# Plan\n", encoding="utf-8")
    (spec_dir / "tasks.md").write_text(tasks, encoding="utf-8")


def _write_matching_audit(root, spec_id: str = "spec-001") -> None:
    run_dir = root / "runs" / f"verify-spec-{spec_id}-20260615"
    run_dir.mkdir(parents=True)
    (run_dir / "requirement-audit.md").write_text(
        "| ID | Category | Source | Requirement | Acceptance Signal |\n"
        "|---|---|---|---|---|\n"
        "| FR-001 | FR | spec.md | Build one thing | Test one thing |\n",
        encoding="utf-8",
    )


def _write_matching_report(report) -> None:
    report.write_text(
        "| ID | Status | Evidence | Confidence | Notes |\n"
        "|---|---|---|---|---|\n"
        "| FR-001 | IMPLEMENTED | src/a.py | high | ok |\n",
        encoding="utf-8",
    )


def _write_passing_fulfillment_receipt(
    root,
    worktree,
    *,
    sequence: int = 1,
    started_at: str = "2026-08-31T00:00:00Z",
    stdout: bytes = b"passed\n",
):
    fingerprint = product_evidence_fingerprint(worktree)
    return write_verification_receipt(
        evidence_dir=root / "runs" / "build-1" / "evidence" / "default",
        spec_id="spec-001",
        strategy_id="default",
        build_id="build-1",
        candidate_commit="abc123",
        fingerprint_before=fingerprint,
        fingerprint_after=fingerprint,
        verifier_source="configured",
        stages=[
            VerificationStage(
                name="verify",
                command=("pnpm", "verify"),
                exit_code=0,
                duration_ms=1,
                stdout=stdout,
                stderr=b"",
            )
        ],
        attempt_sequence=sequence,
        sensitive_environment={},
        started_at=started_at,
    )


@pytest.mark.unit
class TestFulfillmentRunner:
    def test_verifier_version_invalidates_pre_split_ledgers(self):
        assert FULFILLMENT_VERIFIER_VERSION == "verified-ledger-v2-codegraph-candidates"

    def test_refresh_builds_verify_spec_prompt_and_runs_provider(self, tmp_path):
        _write_verify_skill(tmp_path)
        spec_dir = tmp_path / "specs" / "spec-001-demo"
        _write_spec_inputs(spec_dir)
        report = spec_dir / "fulfillment-report.md"
        provider = MagicMock()
        provider.cli = "claude"

        def write_report(_worktree_path: str, _prompt: str) -> int:
            report.write_text("# Fulfillment\n", encoding="utf-8")
            return 0

        provider.exec_prompt.side_effect = write_report

        with patch("harness.fulfillment_runner._current_git_commit", return_value="abc123"):
            result = FulfillmentRunner(provider).refresh(str(tmp_path), "spec-001")

        assert result.exit_code == 0
        assert result.status == "refreshed"
        assert result.used_cache is False
        provider.exec_prompt.assert_called_once()
        worktree_path, prompt = provider.exec_prompt.call_args.args
        assert worktree_path == str(tmp_path)
        assert "You are COMMANDER" in prompt
        assert "verify spec-001" in prompt

    def test_refresh_embeds_verify_spec_phase_context_without_discovery(
        self, tmp_path
    ):
        _write_verify_skill(tmp_path)
        phase_dir = (
            tmp_path
            / ".echelon"
            / "runtime"
            / "workflow"
            / "phases"
        )
        phase_dir.mkdir(parents=True)
        (phase_dir / "verify-spec-1-init.md").write_text(
            "python -m harness init-verify-spec-run \"{project_root}\" "
            "\"{spec_id}\" \"{spec_dir}\"\n",
            encoding="utf-8",
        )
        spec_dir = tmp_path / "specs" / "spec-001-demo"
        _write_spec_inputs(spec_dir)
        report = spec_dir / "fulfillment-report.md"
        provider = MagicMock()
        provider.cli = "claude"

        def write_report(_worktree_path: str, _prompt: str) -> int:
            report.write_text("# Fulfillment\n", encoding="utf-8")
            return 0

        provider.exec_prompt.side_effect = write_report

        with patch("harness.fulfillment_runner._current_git_commit", return_value="abc123"):
            result = FulfillmentRunner(provider).refresh(str(tmp_path), "spec-001")

        assert result.status == "refreshed"
        _worktree_path, prompt = provider.exec_prompt.call_args.args
        assert "Direct verify-spec invocation guard" in prompt
        assert "Do not search for or read `.claude/skills`" in prompt
        assert "workflow phase\nfiles" in prompt
        assert "## Embedded Verify-Spec Phase Context" in prompt
        assert "### verify-spec-1-init.md" in prompt
        assert "python -m harness init-verify-spec-run" in prompt

    def test_refresh_returns_127_when_verify_spec_skill_missing(self, tmp_path):
        provider = MagicMock()
        provider.cli = "claude"

        result = FulfillmentRunner(provider).refresh(str(tmp_path), "spec-001")

        assert result.exit_code == 127
        assert result.status == "missing_skill"
        assert result.used_cache is False
        provider.exec_prompt.assert_not_called()

    def test_refresh_reports_provider_session_limit_without_using_stale_report(
        self, tmp_path
    ):
        _write_verify_skill(tmp_path)
        spec_dir = tmp_path / "specs" / "spec-001-demo"
        _write_spec_inputs(spec_dir)
        report = spec_dir / "fulfillment-report.md"
        report.write_text(
            "---\n"
            "verify_scope: full\n"
            "verified_commit: old123\n"
            "---\n"
            "| ID | Status | Evidence |\n"
            "| --- | --- | --- |\n"
            "| FR-001 | MISSING | stale skeleton evidence |\n",
            encoding="utf-8",
        )

        provider = MagicMock()
        provider.cli = "claude"
        provider.exec_prompt.return_value = 1
        provider.last_stdout = "You've hit your session limit · resets 1:30pm"

        with patch("harness.fulfillment_runner._current_git_commit", return_value="new456"):
            result = FulfillmentRunner(provider).refresh(str(tmp_path), "spec-001")

        assert result.status == "provider_session_limit"
        assert result.exit_code == 1
        assert result.used_cache is False
        assert result.report_path == str(report)
        assert "session limit" in result.reason
        assert "old123" in result.reason
        assert "new456" in result.reason
        assert read_fulfillment_metadata(report)["verified_commit"] == "old123"

    def test_refresh_trims_provider_session_limit_transcript(self, tmp_path):
        _write_verify_skill(tmp_path)
        spec_dir = tmp_path / "specs" / "spec-001-demo"
        _write_spec_inputs(spec_dir)
        report = spec_dir / "fulfillment-report.md"
        report.write_text(
            "---\n"
            "verify_scope: full\n"
            "verified_commit: old123\n"
            "---\n"
            "| ID | Status | Evidence |\n"
            "| --- | --- | --- |\n"
            "| FR-001 | IMPLEMENTED | stale evidence |\n",
            encoding="utf-8",
        )

        provider = MagicMock()
        provider.cli = "claude"
        provider.exec_prompt.return_value = 1
        provider.last_stdout = (
            "I'll start by exploring the spec directory.\n"
            "Now dispatching mapper agents and reading source files.\n"
            "You've hit your session limit · resets 4:40pm (Europe/Prague)\n"
        )

        with patch("harness.fulfillment_runner._current_git_commit", return_value="new456"):
            result = FulfillmentRunner(provider).refresh(str(tmp_path), "spec-001")

        assert result.status == "provider_session_limit"
        assert result.reason.startswith(
            "You've hit your session limit · resets 4:40pm (Europe/Prague)"
        )
        assert "I'll start by exploring" not in result.reason
        assert "mapper agents" not in result.reason
        assert "old123" in result.reason
        assert "new456" in result.reason

    def test_refresh_stamps_latest_fulfillment_report_on_success(self, tmp_path):
        _write_verify_skill(tmp_path)
        spec_dir = tmp_path / "specs" / "spec-001-demo"
        _write_spec_inputs(spec_dir)
        report = spec_dir / "fulfillment-report.md"

        provider = MagicMock()
        provider.cli = "claude"

        def write_report(_worktree_path: str, _prompt: str) -> int:
            report.write_text("# Fulfillment\n", encoding="utf-8")
            return 0

        provider.exec_prompt.side_effect = write_report

        with patch("harness.fulfillment_runner._current_git_commit", return_value="abc123"):
            result = FulfillmentRunner(provider).refresh(str(tmp_path), "spec-001")

        assert result.exit_code == 0
        assert result.status == "refreshed"
        assert result.scope == "full"
        assert result.reason == "full verify-spec completed"
        assert result.report_path == str(report)
        assert isinstance(result.cache_key, str)
        metadata = read_fulfillment_metadata(report)
        assert metadata["spec_id"] == "spec-001"
        assert metadata["verified_commit"] == "abc123"
        assert metadata["verify_scope"] == "full"
        assert isinstance(metadata["spec_input_hash"], str)
        assert isinstance(metadata["implementation_input_hash"], str)
        assert isinstance(metadata["verify_cache_key"], str)

    def test_refresh_writes_verified_fulfillment_ledger_on_success(self, tmp_path):
        _write_verify_skill(tmp_path)
        spec_dir = tmp_path / "specs" / "spec-001-demo"
        _write_spec_inputs(spec_dir)
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "a.py").write_text("print('ok')\n", encoding="utf-8")
        (tmp_path / "test-results").mkdir()
        (tmp_path / "test-results" / "runtime.json").write_text(
            '{"ok": false}\n',
            encoding="utf-8",
        )
        report = spec_dir / "fulfillment-report.md"

        provider = MagicMock()
        provider.cli = "claude"

        def write_report(_worktree_path: str, _prompt: str) -> int:
            report.write_text(
                "| ID | Status | Evidence | Confidence | Notes |\n"
                "|---|---|---|---|---|\n"
                "| FR-001 | IMPLEMENTED | src/a.py | high | ok |\n"
                "| FR-002 | UNVERIFIED | test-results/runtime.json | low | no gate |\n",
                encoding="utf-8",
            )
            return 0

        provider.exec_prompt.side_effect = write_report

        with patch("harness.fulfillment_runner._current_git_commit", return_value="abc123"):
            result = FulfillmentRunner(provider).refresh(str(tmp_path), "spec-001")

        ledger_path = spec_dir / "verified-fulfillment-ledger.json"
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        assert result.verified_ledger == {
            "reused": 1,
            "rechecked": 1,
            "invalidated": 0,
            "unresolved": 1,
        }
        assert ledger["schema_version"] == 1
        assert [row["requirement_id"] for row in ledger["rows"]] == ["FR-001", "FR-002"]
        assert ledger["rows"][0]["artifact_hashes"]["src/a.py"]
        assert ledger["rows"][1]["status"] == "UNVERIFIED"

    def test_refresh_assembles_no_fallback_report_without_provider_when_artifacts_exist(
        self, tmp_path
    ):
        spec_dir = tmp_path / "specs" / "spec-001-demo"
        _write_spec_inputs(spec_dir)
        verify_run_dir = tmp_path / "runs" / "verify-spec-spec-001-20260715"
        verify_run_dir.mkdir(parents=True)
        (verify_run_dir / "state.json").write_text("{}", encoding="utf-8")
        (verify_run_dir / "canonical-requirements.json").write_text(
            json.dumps({"requirements": [{"id": "FR-001"}]}),
            encoding="utf-8",
        )
        (verify_run_dir / "requirement-audit.md").write_text(
            "# Requirement Audit\n\n"
            "| ID | Category | Source | Requirement | Acceptance Signal |\n"
            "| --- | --- | --- | --- | --- |\n"
            "| FR-001 | functional | spec.md | Build one thing | Test one thing |\n",
            encoding="utf-8",
        )
        (verify_run_dir / "implementation-map.md").write_text(
            "# Implementation Map\n\n"
            "schema_version: 2\n\n"
            "| ID | Verified Implementation Evidence | Verified Test Evidence | CodeGraph Candidates | Candidate Disposition | Evidence Kind | Evidence Strength | Runtime Threshold | Confidence | Notes |\n"
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
            "| FR-001 | src/a.py | tests/test_a.py::test_a | app.a | accepted | source_and_test | strong | false | high | |\n",
            encoding="utf-8",
        )
        report = spec_dir / "fulfillment-report.md"
        report.write_text(
            "---\nverified_commit: old123\nverify_scope: full\n---\n"
            "| ID | Status | Evidence |\n"
            "| --- | --- | --- |\n"
            "| FR-001 | IMPLEMENTED | stale |\n",
            encoding="utf-8",
        )
        provider = MagicMock()
        provider.cli = "claude"

        with patch("harness.fulfillment_runner._current_git_commit", return_value="head456"):
            result = FulfillmentRunner(provider).refresh(str(tmp_path), "spec-001")

        assert result.status == "refreshed"
        assert result.reason == "full verify-spec completed from deterministic artifacts"
        provider.exec_prompt.assert_not_called()
        text = report.read_text(encoding="utf-8")
        assert "| FR-001 | IMPLEMENTED | prepass:source_and_test_strong |" in text
        metadata = read_fulfillment_metadata(report)
        assert metadata["verified_commit"] == "head456"
        assert metadata["verify_scope"] == "full"

    def test_refresh_rejects_mapping_artifacts_written_outside_verify_roots(
        self, tmp_path
    ):
        _write_verify_skill(tmp_path)
        spec_dir = tmp_path / "specs" / "spec-001-demo"
        _write_spec_inputs(spec_dir)
        _write_matching_audit(tmp_path)
        report = spec_dir / "fulfillment-report.md"

        provider = MagicMock()
        provider.cli = "claude"

        def write_report(_worktree_path: str, _prompt: str) -> int:
            _write_matching_report(report)
            provider.last_stdout = (
                "  ▷ Bash: copy mapping summary\n"
                "  ⎿  wrote /tmp/mapping_summary.txt\n"
                "  ▷ Bash: copy requirements mapping\n"
                "  ⎿  copied to "
                "/Users/michalbachorik/work/requirements_mapping_905_import_prose\n"
            )
            return 0

        provider.exec_prompt.side_effect = write_report

        with patch("harness.fulfillment_runner._current_git_commit", return_value="abc123"):
            result = FulfillmentRunner(provider).refresh(str(tmp_path), "spec-001")

        assert result.status == "failed"
        assert result.exit_code == 2
        assert "verify-spec artifact write outside allowed roots" in result.reason
        assert "/tmp/mapping_summary.txt" in result.reason

    def test_refresh_accepts_workspace_verify_run_from_target_scoped_runtime(
        self, tmp_path
    ):
        workspace = tmp_path / "workspace"
        runtime_root = workspace / "runs" / "targets" / "prosaic"
        worktree = runtime_root / "runs" / "build-1" / "worktrees" / "default" / "iter-0"
        spec_dir = workspace / "specs" / "spec-001-demo"
        _write_verify_skill(worktree)
        _write_spec_inputs(spec_dir)
        _write_matching_audit(workspace)
        report = spec_dir / "fulfillment-report.md"
        active_run = workspace / "runs" / "spec-20260708-123456"
        active_run.mkdir(parents=True, exist_ok=True)
        (workspace / "runs" / ".current").write_text(
            active_run.name, encoding="utf-8"
        )
        artifact = (
            active_run
            / "verify-spec"
            / "spec-001"
            / "implementation-map.md"
        )
        provider = MagicMock(cli="claude")

        def write_report(_worktree_path: str, _prompt: str) -> int:
            _write_matching_report(report)
            provider.last_stdout = (
                "  ▷ Bash: write implementation map\n"
                f"  ⎿  wrote {artifact}\n"
            )
            return 0

        provider.exec_prompt.side_effect = write_report

        with patch("harness.fulfillment_runner._current_git_commit", return_value="abc123"):
            result = FulfillmentRunner(provider).refresh(
                str(worktree),
                "spec-001",
                spec_dir=spec_dir,
                orchestration_root=runtime_root,
            )

        assert result.status == "refreshed"

    def test_target_scoped_refresh_grants_only_fulfillment_artifact_paths(
        self, tmp_path
    ):
        workspace = tmp_path / "workspace"
        worktree = workspace / "runs" / "targets" / "web" / "worktree"
        spec_dir = workspace / "specs" / "spec-001-demo"
        _write_verify_skill(worktree)
        _write_spec_inputs(spec_dir)
        report = spec_dir / "fulfillment-report.md"
        provider = object.__new__(AICodingCliProvider)
        provider._cli = "codex"
        provider.last_stdout = ""
        provider.last_stderr = ""
        receipt = _write_passing_fulfillment_receipt(
            tmp_path / "target-runtime", worktree
        )

        def run_prompt(_worktree_path, _prompt, **_kwargs):
            _write_matching_report(report)
            return MagicMock(exit_code=0)

        provider.run_prompt_result = MagicMock(side_effect=run_prompt)

        with patch("harness.fulfillment_runner._current_git_commit", return_value="abc123"):
            result = FulfillmentRunner(provider).refresh(
                str(worktree),
                "spec-001",
                spec_dir=spec_dir,
                orchestration_root=workspace,
                verification_evidence=receipt.as_mapping(),
            )

        assert result.status == "refreshed"
        metadata = provider.run_prompt_result.call_args.kwargs["request_metadata"]
        prompt_metadata = metadata["prompt_metadata"]
        assert prompt_metadata["tool_read_roots"] == [
            str(worktree),
            str(spec_dir),
            str(receipt.path.parent),
        ]
        assert prompt_metadata["tool_write_paths"][:2] == [
            str(spec_dir / "fulfillment-report.md"),
            str(spec_dir / "fulfillment-gaps.md"),
        ]
        assert len(prompt_metadata["tool_write_paths"]) == 3
        verify_run_dir = prompt_metadata["tool_write_paths"][2]
        assert verify_run_dir.startswith(str(workspace / "runs"))
        assert verify_run_dir != str(workspace / "runs")
        assert str(receipt.path.parent) not in prompt_metadata["tool_write_paths"]

    def test_tampered_verification_evidence_fails_before_provider(self, tmp_path):
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        spec_dir = tmp_path / "specs" / "spec-001-demo"
        _write_spec_inputs(spec_dir)
        receipt = _write_passing_fulfillment_receipt(tmp_path, worktree)
        receipt.path.write_text("{}", encoding="utf-8")
        provider = object.__new__(AICodingCliProvider)
        provider._cli = "codex"
        provider.last_stdout = ""
        provider.last_stderr = ""
        provider.run_prompt_result = MagicMock()

        with patch("harness.fulfillment_runner._current_git_commit", return_value="abc123"):
            result = FulfillmentRunner(provider).refresh(
                str(worktree),
                "spec-001",
                spec_dir=spec_dir,
                orchestration_root=tmp_path,
                verification_evidence=receipt.as_mapping(),
            )

        assert result.status == "failed"
        assert "verification evidence" in result.reason
        provider.run_prompt_result.assert_not_called()

    def test_stable_verification_evidence_digest_controls_cache(self, tmp_path):
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        _write_verify_skill(worktree)
        spec_dir = tmp_path / "specs" / "spec-001-demo"
        _write_spec_inputs(spec_dir)
        _write_matching_audit(tmp_path)
        report = spec_dir / "fulfillment-report.md"
        provider = MagicMock(cli="claude")

        def write_report(_worktree_path: str, _prompt: str) -> int:
            _write_matching_report(report)
            return 0

        provider.exec_prompt.side_effect = write_report
        runner = FulfillmentRunner(provider)
        first_receipt = _write_passing_fulfillment_receipt(tmp_path, worktree)

        with patch("harness.fulfillment_runner._current_git_commit", return_value="abc123"):
            first = runner.refresh(
                str(worktree), "spec-001", spec_dir=spec_dir,
                orchestration_root=tmp_path,
                verification_evidence=first_receipt.as_mapping(),
            )
            second_receipt = _write_passing_fulfillment_receipt(
                tmp_path, worktree, sequence=2,
                started_at="2026-08-31T00:01:00Z",
            )
            second = runner.refresh(
                str(worktree), "spec-001", spec_dir=spec_dir,
                orchestration_root=tmp_path,
                verification_evidence=second_receipt.as_mapping(),
            )
            changed_receipt = _write_passing_fulfillment_receipt(
                tmp_path, worktree, sequence=3,
                started_at="2026-08-31T00:02:00Z", stdout=b"different pass\n",
            )
            third = runner.refresh(
                str(worktree), "spec-001", spec_dir=spec_dir,
                orchestration_root=tmp_path,
                verification_evidence=changed_receipt.as_mapping(),
            )

        assert first.status == "refreshed"
        assert second.status == "cached"
        assert third.status == "refreshed"
        assert provider.exec_prompt.call_count == 2
        metadata = read_fulfillment_metadata(report)
        assert metadata["verification_evidence_sha256"] == (
            changed_receipt.evidence_sha256
        )
        ledger = json.loads(
            (spec_dir / "verified-fulfillment-ledger.json").read_text(
                encoding="utf-8"
            )
        )
        assert all(
            changed_receipt.evidence_sha256 in row["verifier_version"]
            for row in ledger["rows"]
        )

    def test_refresh_rejects_mapping_artifact_in_sibling_source_root(self, tmp_path):
        workspace = tmp_path / "workspace"
        worktree = workspace / "runs" / "targets" / "prosaic" / "worktree"
        spec_dir = workspace / "specs" / "spec-001-demo"
        _write_verify_skill(worktree)
        _write_spec_inputs(spec_dir)
        _write_matching_audit(workspace)
        report = spec_dir / "fulfillment-report.md"
        sibling_artifact = workspace / "sources" / "ruler" / "implementation-map.md"
        provider = MagicMock(cli="claude")

        def write_report(_worktree_path: str, _prompt: str) -> int:
            _write_matching_report(report)
            provider.last_stdout = (
                "  ▷ Bash: write implementation map\n"
                f"  ⎿  wrote {sibling_artifact}\n"
            )
            return 0

        provider.exec_prompt.side_effect = write_report

        with patch("harness.fulfillment_runner._current_git_commit", return_value="abc123"):
            result = FulfillmentRunner(provider).refresh(
                str(worktree),
                "spec-001",
                spec_dir=spec_dir,
                orchestration_root=workspace,
            )

        assert result.status == "failed"
        assert "verify-spec artifact write outside allowed roots" in result.reason
        assert str(sibling_artifact) in result.reason

    def test_refresh_rejects_fulfillment_report_outside_spec_dir(self, tmp_path):
        workspace = tmp_path / "workspace"
        worktree = workspace / "runs" / "targets" / "prosaic" / "worktree"
        spec_dir = workspace / "specs" / "spec-001-demo"
        _write_verify_skill(worktree)
        _write_spec_inputs(spec_dir)
        _write_matching_audit(workspace)
        report = spec_dir / "fulfillment-report.md"
        invalid_report = workspace / "sources" / "prosaic" / "fulfillment-report.md"
        provider = MagicMock(cli="claude")

        def write_report(_worktree_path: str, _prompt: str) -> int:
            _write_matching_report(report)
            provider.last_stdout = (
                "  ▷ Write: write fulfillment report\n"
                f"  ⎿  wrote {invalid_report}\n"
            )
            return 0

        provider.exec_prompt.side_effect = write_report

        with patch("harness.fulfillment_runner._current_git_commit", return_value="abc123"):
            result = FulfillmentRunner(provider).refresh(
                str(worktree),
                "spec-001",
                spec_dir=spec_dir,
                orchestration_root=workspace,
            )

        assert result.status == "failed"
        assert "verify-spec artifact write outside allowed roots" in result.reason
        assert str(invalid_report) in result.reason

    def test_refresh_ignores_summary_text_that_is_not_a_tool_write(self, tmp_path):
        _write_verify_skill(tmp_path)
        spec_dir = tmp_path / "specs" / "spec-001-demo"
        _write_spec_inputs(spec_dir)
        _write_matching_audit(tmp_path)
        report = spec_dir / "fulfillment-report.md"
        provider = MagicMock(cli="claude")

        def write_report(_worktree_path: str, _prompt: str) -> int:
            _write_matching_report(report)
            provider.last_stdout = (
                "Wrote /tmp/implementation-map.md with a parser-conformant table.\n"
            )
            return 0

        provider.exec_prompt.side_effect = write_report

        with patch("harness.fulfillment_runner._current_git_commit", return_value="abc123"):
            result = FulfillmentRunner(provider).refresh(str(tmp_path), "spec-001")

        assert result.status == "refreshed"

    def test_refresh_rejects_success_when_report_is_not_current_after_stamp(
        self, tmp_path
    ):
        _write_verify_skill(tmp_path)
        spec_dir = tmp_path / "specs" / "spec-001-demo"
        _write_spec_inputs(spec_dir)
        report = spec_dir / "fulfillment-report.md"

        provider = MagicMock()
        provider.cli = "claude"

        def write_report(_worktree_path: str, _prompt: str) -> int:
            report.write_text("# Fulfillment\n", encoding="utf-8")
            return 0

        provider.exec_prompt.side_effect = write_report

        with (
            patch("harness.fulfillment_runner._current_git_commit", return_value="abc123"),
            patch("harness.fulfillment_runner._stamp_latest_report"),
        ):
            result = FulfillmentRunner(provider).refresh(str(tmp_path), "spec-001")

        assert result.exit_code == 2
        assert result.status == "failed"
        assert result.reason == "full verify-spec report was not stamped for current HEAD"
        assert result.report_path == str(report)
        assert read_fulfillment_metadata(report) == {}

    def test_refresh_rejects_report_with_ids_not_in_requirement_audit(self, tmp_path):
        skill_dir = tmp_path / ".echelon" / "prosaic" / "commands"
        skill_dir.mkdir(parents=True)
        (skill_dir / "echelon.verify-spec.md").write_text(
            "---\nname: echelon.verify-spec\n---\nverify {{args}}\n",
            encoding="utf-8",
        )
        spec_dir = tmp_path / "specs" / "spec-001-demo"
        _write_spec_inputs(spec_dir)
        report = spec_dir / "fulfillment-report.md"
        run_dir = tmp_path / "runs" / "verify-spec-spec-001-20260614"
        run_dir.mkdir(parents=True)
        (run_dir / "requirement-audit.md").write_text(
            "| ID | Category | Source | Requirement | Acceptance Signal |\n"
            "|---|---|---|---|---|\n"
            "| FR-001 | FR | spec.md | Build one thing | Test one thing |\n",
            encoding="utf-8",
        )

        provider = MagicMock()
        provider.cli = "claude"

        def write_mismatched_report(_worktree_path: str, _prompt: str) -> int:
            report.write_text(
                "| ID | Status | Evidence | Confidence | Notes |\n"
                "|---|---|---|---|---|\n"
                "| FR-001 | IMPLEMENTED | src/a.py | high | ok |\n"
                "| FR-999 | IMPLEMENTED | src/b.py | high | invented row |\n",
                encoding="utf-8",
            )
            return 0

        provider.exec_prompt.side_effect = write_mismatched_report

        with patch("harness.fulfillment_runner._current_git_commit", return_value="abc123"):
            result = FulfillmentRunner(provider).refresh(str(tmp_path), "spec-001")

        assert result.exit_code == 2
        assert result.status == "failed"
        assert read_fulfillment_metadata(report) == {}

    def test_refresh_fails_when_report_drops_canonical_inventory_row(self, tmp_path):
        skill_dir = tmp_path / ".echelon" / "prosaic" / "commands"
        skill_dir.mkdir(parents=True)
        (skill_dir / "echelon.verify-spec.md").write_text(
            "---\nname: echelon.verify-spec\n---\nverify {{args}}\n",
            encoding="utf-8",
        )
        spec_dir = tmp_path / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text("- FR-001\n- FR-002\n", encoding="utf-8")
        report = spec_dir / "fulfillment-report.md"
        run_dir = tmp_path / "runs" / "verify-spec-spec-001-20260616"
        run_dir.mkdir(parents=True)
        (run_dir / "canonical-requirements.json").write_text(
            '{"requirements":[{"id":"FR-001"},{"id":"FR-002"}]}\n',
            encoding="utf-8",
        )
        (run_dir / "requirement-audit.md").write_text(
            "| ID | Category |\n"
            "| --- | --- |\n"
            "| FR-001 | functional |\n",
            encoding="utf-8",
        )

        provider = MagicMock()
        provider.cli = "claude"

        def write_report_missing_inventory_row(_worktree_path: str, _prompt: str) -> int:
            report.write_text(
                "| ID | Status | Evidence | Confidence | Notes |\n"
                "|---|---|---|---|---|\n"
                "| FR-001 | IMPLEMENTED | src/a.py | high | ok |\n",
                encoding="utf-8",
            )
            return 0

        provider.exec_prompt.side_effect = write_report_missing_inventory_row

        with patch("harness.fulfillment_runner._current_git_commit", return_value="abc123"):
            result = FulfillmentRunner(provider).refresh(str(tmp_path), "spec-001")

        assert result.exit_code == 2
        assert result.status == "failed"
        assert read_fulfillment_metadata(report) == {}

    def test_refresh_rejects_large_audit_scope_drop_without_scope_change(self, tmp_path):
        skill_dir = tmp_path / ".echelon" / "prosaic" / "commands"
        skill_dir.mkdir(parents=True)
        (skill_dir / "echelon.verify-spec.md").write_text(
            "---\nname: echelon.verify-spec\n---\nverify {{args}}\n",
            encoding="utf-8",
        )
        spec_dir = tmp_path / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")
        report = spec_dir / "fulfillment-report.md"

        previous = tmp_path / "runs" / "verify-spec-spec-001-previous"
        current = tmp_path / "runs" / "verify-spec-spec-001-current"
        previous.mkdir(parents=True)
        current.mkdir(parents=True)
        previous_rows = "\n".join(
            f"| FR-{index:03d} | FR | spec.md | R | A |" for index in range(1, 101)
        )
        current_rows = "\n".join(
            f"| FR-{index:03d} | FR | spec.md | R | A |" for index in range(1, 61)
        )
        (previous / "requirement-audit.md").write_text(
            "| ID | Category | Source | Requirement | Acceptance Signal |\n"
            "| --- | --- | --- | --- | --- |\n"
            f"{previous_rows}\n",
            encoding="utf-8",
        )
        (current / "requirement-audit.md").write_text(
            "| ID | Category | Source | Requirement | Acceptance Signal |\n"
            "| --- | --- | --- | --- | --- |\n"
            f"{current_rows}\n",
            encoding="utf-8",
        )
        os.utime(spec_dir / "spec.md", (50, 50))
        os.utime(previous / "requirement-audit.md", (100, 100))
        os.utime(current / "requirement-audit.md", (200, 200))

        provider = MagicMock()
        provider.cli = "claude"

        def write_matching_current_report(_worktree_path: str, _prompt: str) -> int:
            report.write_text(
                "| ID | Status | Evidence | Confidence | Notes |\n"
                "| --- | --- | --- | --- | --- |\n"
                + "\n".join(
                    f"| FR-{index:03d} | IMPLEMENTED | src/a.py | high | ok |"
                    for index in range(1, 61)
                )
                + "\n",
                encoding="utf-8",
            )
            return 0

        provider.exec_prompt.side_effect = write_matching_current_report

        with patch("harness.fulfillment_runner._current_git_commit", return_value="abc123"):
            result = FulfillmentRunner(provider).refresh(str(tmp_path), "spec-001")

        assert result.exit_code == 2
        assert result.status == "failed"
        assert read_fulfillment_metadata(report) == {}

    def test_refresh_allows_large_audit_scope_drop_after_spec_change(self, tmp_path):
        skill_dir = tmp_path / ".echelon" / "prosaic" / "commands"
        skill_dir.mkdir(parents=True)
        (skill_dir / "echelon.verify-spec.md").write_text(
            "---\nname: echelon.verify-spec\n---\nverify {{args}}\n",
            encoding="utf-8",
        )
        spec_dir = tmp_path / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text("# Changed Spec\n", encoding="utf-8")
        report = spec_dir / "fulfillment-report.md"

        previous = tmp_path / "runs" / "verify-spec-spec-001-previous"
        current = tmp_path / "runs" / "verify-spec-spec-001-current"
        previous.mkdir(parents=True)
        current.mkdir(parents=True)
        (previous / "requirement-audit.md").write_text(
            "| ID | Category | Source | Requirement | Acceptance Signal |\n"
            "| --- | --- | --- | --- | --- |\n"
            + "\n".join(
                f"| FR-{index:03d} | FR | spec.md | R | A |" for index in range(1, 101)
            )
            + "\n",
            encoding="utf-8",
        )
        (current / "requirement-audit.md").write_text(
            "| ID | Category | Source | Requirement | Acceptance Signal |\n"
            "| --- | --- | --- | --- | --- |\n"
            + "\n".join(
                f"| FR-{index:03d} | FR | spec.md | R | A |" for index in range(1, 61)
            )
            + "\n",
            encoding="utf-8",
        )
        os.utime(previous / "requirement-audit.md", (100, 100))
        os.utime(spec_dir / "spec.md", (150, 150))
        os.utime(current / "requirement-audit.md", (200, 200))

        provider = MagicMock()
        provider.cli = "claude"

        def write_matching_current_report(_worktree_path: str, _prompt: str) -> int:
            report.write_text(
                "| ID | Status | Evidence | Confidence | Notes |\n"
                "| --- | --- | --- | --- | --- |\n"
                + "\n".join(
                    f"| FR-{index:03d} | IMPLEMENTED | src/a.py | high | ok |"
                    for index in range(1, 61)
                )
                + "\n",
                encoding="utf-8",
            )
            return 0

        provider.exec_prompt.side_effect = write_matching_current_report

        with patch("harness.fulfillment_runner._current_git_commit", return_value="abc123"):
            result = FulfillmentRunner(provider).refresh(str(tmp_path), "spec-001")

        assert result.exit_code == 0
        assert result.status == "refreshed"
        assert read_fulfillment_metadata(report)["verified_commit"] == "abc123"

    def test_refresh_uses_orchestration_spec_dir_for_polyrepo_runs(self, tmp_path):
        worktree = tmp_path / "runs" / "build-1" / "worktrees" / "default" / "iter-0"
        skill_dir = worktree / ".echelon" / "prosaic" / "commands"
        skill_dir.mkdir(parents=True)
        (skill_dir / "echelon.verify-spec.md").write_text(
            "---\nname: echelon.verify-spec\n---\nverify {{args}}\n",
            encoding="utf-8",
        )
        orchestration_root = tmp_path / "polyrepo"
        spec_dir = orchestration_root / "specs" / "spec-001-demo"
        _write_spec_inputs(spec_dir)
        (orchestration_root / "runs").mkdir(parents=True)
        (orchestration_root / "runs" / ".current").write_text(
            "spec-20260708-123456",
            encoding="utf-8",
        )
        (orchestration_root / "runs" / "spec-20260708-123456").mkdir()
        (worktree / "runs").mkdir(parents=True)
        (worktree / "runs" / ".current").write_text(
            "target-build-run",
            encoding="utf-8",
        )
        _write_matching_audit(orchestration_root)
        target_audit = worktree / "runs" / "verify-spec-spec-001-target"
        target_audit.mkdir(parents=True)
        (target_audit / "requirement-audit.md").write_text(
            "| ID | Category | Source | Requirement | Acceptance Signal |\n"
            "|---|---|---|---|---|\n"
            "| FR-999 | FR | spec.md | Wrong target audit | Should not be used |\n",
            encoding="utf-8",
        )
        report = spec_dir / "fulfillment-report.md"

        provider = MagicMock()
        provider.cli = "claude"

        def write_report(_worktree_path: str, _prompt: str) -> int:
            _write_matching_report(report)
            return 0

        provider.exec_prompt.side_effect = write_report

        with patch("harness.fulfillment_runner._current_git_commit", return_value="abc123"):
            result = FulfillmentRunner(provider).refresh(
                str(worktree),
                "spec-001",
                orchestration_root=orchestration_root,
            )

        assert result.exit_code == 0
        assert result.status == "refreshed"
        _worktree_path, prompt = provider.exec_prompt.call_args.args
        assert f"verify spec-001 spec_dir={spec_dir}" in prompt
        metadata = read_fulfillment_metadata(report)
        assert metadata["spec_id"] == "spec-001"
        assert metadata["verified_commit"] == "abc123"
        assert metadata["verify_run_id"] == "spec-20260708-123456"

    def test_polyrepo_refresh_uses_orchestration_workflow_and_forwards_reconcile(
        self, tmp_path
    ):
        workspace = tmp_path / "workspace"
        target = workspace / "sources" / "prosaic"
        target.mkdir(parents=True)
        _write_verify_skill(workspace)
        phase_dir = (
            workspace
            / ".echelon"
            / "runtime"
            / "workflow"
            / "phases"
        )
        phase_dir.mkdir(parents=True)
        (phase_dir / "verify-spec-1-init.md").write_text(
            "ORCHESTRATION_PHASE_SENTINEL\n",
            encoding="utf-8",
        )
        spec_dir = workspace / "specs" / "906-cli-output-styling"
        _write_spec_inputs(spec_dir)
        _write_matching_audit(workspace, "906-cli-output-styling")
        report = spec_dir / "fulfillment-report.md"
        provider = MagicMock()
        provider.cli = "claude"

        def write_report(_worktree_path: str, _prompt: str) -> int:
            _write_matching_report(report)
            return 0

        provider.exec_prompt.side_effect = write_report
        runner = FulfillmentRunner(provider)

        with patch("harness.fulfillment_runner._current_git_commit", return_value="abc123"):
            first = runner.refresh(
                str(target),
                "906-cli-output-styling",
                spec_dir=spec_dir,
                orchestration_root=workspace,
            )
            reconciled = runner.refresh(
                str(target),
                "906-cli-output-styling",
                spec_dir=spec_dir,
                orchestration_root=workspace,
                reconcile=True,
                dry_run=True,
            )

        assert first.status == "refreshed"
        assert reconciled.status == "refreshed"
        assert provider.exec_prompt.call_count == 2
        worktree_path, prompt = provider.exec_prompt.call_args.args
        assert worktree_path == str(target)
        assert "ORCHESTRATION_PHASE_SENTINEL" in prompt
        assert f"spec_dir={spec_dir}" in prompt
        assert "--reconcile" in prompt
        assert "--dry-run" in prompt

    def test_refresh_rejects_dry_run_without_reconcile(self, tmp_path):
        _write_verify_skill(tmp_path)
        spec_dir = tmp_path / "specs" / "spec-001-demo"
        _write_spec_inputs(spec_dir)
        provider = MagicMock()
        provider.cli = "claude"

        result = FulfillmentRunner(provider).refresh(
            str(tmp_path),
            "spec-001",
            dry_run=True,
        )

        assert result.status == "failed"
        assert result.exit_code == 2
        assert result.reason == "dry_run requires reconcile"
        provider.exec_prompt.assert_not_called()
        assert not (spec_dir / "fulfillment-report.md").exists()

    def test_refresh_uses_cached_full_report_when_commit_and_spec_hash_match(self, tmp_path):
        _write_verify_skill(tmp_path)
        spec_dir = tmp_path / "specs" / "spec-001-demo"
        _write_spec_inputs(spec_dir)
        _write_matching_audit(tmp_path)
        report = spec_dir / "fulfillment-report.md"
        provider = MagicMock()
        provider.cli = "claude"

        def write_report(_worktree_path: str, _prompt: str) -> int:
            _write_matching_report(report)
            return 0

        provider.exec_prompt.side_effect = write_report
        runner = FulfillmentRunner(provider)

        with patch("harness.fulfillment_runner._current_git_commit", return_value="abc123"):
            first = runner.refresh(str(tmp_path), "spec-001")
            second = runner.refresh(str(tmp_path), "spec-001")

        assert first.status == "refreshed"
        assert second.status == "cached"
        assert second.scope == "full"
        assert second.reason == "full verify-spec cache hit"
        assert second.report_path == str(report)
        assert isinstance(second.cache_key, str)
        assert second.verified_ledger == {
            "reused": 1,
            "rechecked": 0,
            "invalidated": 0,
            "unresolved": 0,
        }
        assert second.exit_code == 0
        assert second.used_cache is True
        provider.exec_prompt.assert_called_once()

    def test_refresh_invalidates_cache_when_tasks_change(self, tmp_path):
        _write_verify_skill(tmp_path)
        spec_dir = tmp_path / "specs" / "spec-001-demo"
        _write_spec_inputs(spec_dir)
        _write_matching_audit(tmp_path)
        report = spec_dir / "fulfillment-report.md"
        provider = MagicMock()
        provider.cli = "claude"

        def write_report(_worktree_path: str, _prompt: str) -> int:
            _write_matching_report(report)
            return 0

        provider.exec_prompt.side_effect = write_report
        runner = FulfillmentRunner(provider)

        with patch("harness.fulfillment_runner._current_git_commit", return_value="abc123"):
            first = runner.refresh(str(tmp_path), "spec-001")
            (spec_dir / "tasks.md").write_text("# Tasks\n- [ ] T001\n", encoding="utf-8")
            second = runner.refresh(str(tmp_path), "spec-001")

        assert first.status == "refreshed"
        assert second.status == "refreshed"
        assert second.used_cache is False
        assert provider.exec_prompt.call_count == 2

    def test_refresh_invalidates_cache_when_source_changes_without_commit_change(self, tmp_path):
        _write_verify_skill(tmp_path)
        spec_dir = tmp_path / "specs" / "spec-001-demo"
        _write_spec_inputs(spec_dir)
        _write_matching_audit(tmp_path)
        source = tmp_path / "src" / "demo.py"
        source.parent.mkdir()
        source.write_text("VALUE = 1\n", encoding="utf-8")
        report = spec_dir / "fulfillment-report.md"
        provider = MagicMock()
        provider.cli = "claude"

        def write_report(_worktree_path: str, _prompt: str) -> int:
            _write_matching_report(report)
            return 0

        provider.exec_prompt.side_effect = write_report
        runner = FulfillmentRunner(provider)

        with patch("harness.fulfillment_runner._current_git_commit", return_value="abc123"):
            first = runner.refresh(str(tmp_path), "spec-001")
            source.write_text("VALUE = 2\n", encoding="utf-8")
            second = runner.refresh(str(tmp_path), "spec-001")

        assert first.status == "refreshed"
        assert second.status == "refreshed"
        assert second.used_cache is False
        assert provider.exec_prompt.call_count == 2

    def test_refresh_invalidates_cache_when_root_source_changes_without_commit_change(
        self, tmp_path
    ):
        _write_verify_skill(tmp_path)
        spec_dir = tmp_path / "specs" / "spec-001-demo"
        _write_spec_inputs(spec_dir)
        _write_matching_audit(tmp_path)
        source = tmp_path / "hello.py"
        source.write_text("print('hello')\n", encoding="utf-8")
        report = spec_dir / "fulfillment-report.md"
        provider = MagicMock()
        provider.cli = "claude"

        def write_report(_worktree_path: str, _prompt: str) -> int:
            _write_matching_report(report)
            return 0

        provider.exec_prompt.side_effect = write_report
        runner = FulfillmentRunner(provider)

        with patch("harness.fulfillment_runner._current_git_commit", return_value="abc123"):
            first = runner.refresh(str(tmp_path), "spec-001")
            source.write_text("print('hello world')\n", encoding="utf-8")
            second = runner.refresh(str(tmp_path), "spec-001")

        assert first.status == "refreshed"
        assert second.status == "refreshed"
        assert second.used_cache is False
        assert provider.exec_prompt.call_count == 2

    def test_refresh_invalidates_cache_when_root_measured_evidence_changes(
        self, tmp_path
    ):
        _write_verify_skill(tmp_path)
        spec_dir = tmp_path / "specs" / "spec-001-demo"
        _write_spec_inputs(spec_dir)
        _write_matching_audit(tmp_path)
        evidence = tmp_path / "runtime-verification-evidence.json"
        evidence.write_text('{"passed": false}\n', encoding="utf-8")
        report = spec_dir / "fulfillment-report.md"
        provider = MagicMock()
        provider.cli = "claude"

        def write_report(_worktree_path: str, _prompt: str) -> int:
            _write_matching_report(report)
            return 0

        provider.exec_prompt.side_effect = write_report
        runner = FulfillmentRunner(provider)

        with patch("harness.fulfillment_runner._current_git_commit", return_value="abc123"):
            first = runner.refresh(str(tmp_path), "spec-001")
            evidence.write_text('{"passed": true}\n', encoding="utf-8")
            second = runner.refresh(str(tmp_path), "spec-001")

        assert first.status == "refreshed"
        assert second.status == "refreshed"
        assert second.used_cache is False
        assert provider.exec_prompt.call_count == 2

    def test_refresh_invalidates_cache_when_measured_test_result_changes(self, tmp_path):
        _write_verify_skill(tmp_path)
        spec_dir = tmp_path / "specs" / "spec-001-demo"
        _write_spec_inputs(spec_dir)
        _write_matching_audit(tmp_path)
        artifact = tmp_path / "test-results" / "import-fidelity-sc004.json"
        artifact.parent.mkdir()
        artifact.write_text('{"pass": false, "silentLossTotal": 1}\n', encoding="utf-8")
        report = spec_dir / "fulfillment-report.md"
        provider = MagicMock()
        provider.cli = "claude"

        def write_report(_worktree_path: str, _prompt: str) -> int:
            _write_matching_report(report)
            return 0

        provider.exec_prompt.side_effect = write_report
        runner = FulfillmentRunner(provider)

        with patch("harness.fulfillment_runner._current_git_commit", return_value="abc123"):
            first = runner.refresh(str(tmp_path), "spec-001")
            artifact.write_text('{"pass": true, "silentLossTotal": 0}\n', encoding="utf-8")
            second = runner.refresh(str(tmp_path), "spec-001")

        assert first.status == "refreshed"
        assert second.status == "refreshed"
        assert second.used_cache is False
        assert provider.exec_prompt.call_count == 2

    def test_refresh_invalidates_cache_when_commit_changes(self, tmp_path):
        _write_verify_skill(tmp_path)
        spec_dir = tmp_path / "specs" / "spec-001-demo"
        _write_spec_inputs(spec_dir)
        _write_matching_audit(tmp_path)
        report = spec_dir / "fulfillment-report.md"
        provider = MagicMock()
        provider.cli = "claude"

        def write_report(_worktree_path: str, _prompt: str) -> int:
            _write_matching_report(report)
            return 0

        provider.exec_prompt.side_effect = write_report
        runner = FulfillmentRunner(provider)

        with patch(
            "harness.fulfillment_runner._current_git_commit",
            side_effect=["abc123", "def456", "def456"],
        ):
            first = runner.refresh(str(tmp_path), "spec-001")
            second = runner.refresh(str(tmp_path), "spec-001")

        assert first.status == "refreshed"
        assert second.status == "refreshed"
        assert provider.exec_prompt.call_count == 2

    def test_refresh_does_not_use_cache_without_metadata(self, tmp_path):
        _write_verify_skill(tmp_path)
        spec_dir = tmp_path / "specs" / "spec-001-demo"
        _write_spec_inputs(spec_dir)
        _write_matching_audit(tmp_path)
        report = spec_dir / "fulfillment-report.md"
        _write_matching_report(report)
        provider = MagicMock()
        provider.cli = "claude"
        provider.exec_prompt.return_value = 0

        with patch("harness.fulfillment_runner._current_git_commit", return_value="abc123"):
            result = FulfillmentRunner(provider).refresh(str(tmp_path), "spec-001")

        assert result.status == "refreshed"
        provider.exec_prompt.assert_called_once()

    def test_refresh_does_not_use_cache_when_artifact_validation_fails(self, tmp_path):
        _write_verify_skill(tmp_path)
        spec_dir = tmp_path / "specs" / "spec-001-demo"
        _write_spec_inputs(spec_dir)
        _write_matching_audit(tmp_path)
        report = spec_dir / "fulfillment-report.md"
        provider = MagicMock()
        provider.cli = "claude"

        def write_report(_worktree_path: str, _prompt: str) -> int:
            _write_matching_report(report)
            return 0

        provider.exec_prompt.side_effect = write_report
        runner = FulfillmentRunner(provider)

        with patch("harness.fulfillment_runner._current_git_commit", return_value="abc123"):
            first = runner.refresh(str(tmp_path), "spec-001")
            report.write_text(
                report.read_text(encoding="utf-8")
                + "| FR-999 | IMPLEMENTED | src/b.py | high | invented row |\n",
                encoding="utf-8",
            )
            second = runner.refresh(str(tmp_path), "spec-001")

        assert first.status == "refreshed"
        assert second.status == "refreshed"
        assert provider.exec_prompt.call_count == 2

    def test_scoped_refresh_passes_impacted_ids_and_merges_report(self, tmp_path):
        _write_verify_skill(tmp_path)
        spec_dir = tmp_path / "specs" / "spec-001-demo"
        _write_spec_inputs(
            spec_dir,
            tasks=(
                "- [x] T-001 complexity=standard phase=base req=FR-001 depends=none\n"
                "- [x] T-002 complexity=standard phase=base req=FR-002 depends=T-001\n"
            ),
        )
        report = spec_dir / "fulfillment-report.md"
        report.write_text(
            "---\nverify_scope: full\nverified_commit: base123\n---\n"
            "| ID | Status | Evidence | Confidence | Notes |\n"
            "| --- | --- | --- | --- | --- |\n"
            "| FR-001 | IMPLEMENTED | src/a.swift | high | keep |\n"
            "| FR-002 | PARTIAL | src/b.swift | medium | replace |\n",
            encoding="utf-8",
        )
        provider = MagicMock()
        provider.cli = "claude"

        def write_scoped_report(_worktree_path: str, _prompt: str) -> int:
            report.write_text(
                "| ID | Status | Evidence | Confidence | Notes |\n"
                "| --- | --- | --- | --- | --- |\n"
                "| FR-002 | IMPLEMENTED | src/b.swift | high | fixed |\n",
                encoding="utf-8",
            )
            return 0

        provider.exec_prompt.side_effect = write_scoped_report

        with patch("harness.fulfillment_runner._current_git_commit", return_value="head456"):
            result = FulfillmentRunner(provider).refresh(
                str(tmp_path),
                "spec-001",
                scope="scoped",
                completed_task_ids=["T-002"],
            )

        assert result.status == "refreshed"
        assert result.scope == "scoped"
        assert result.reason == "scoped verify-spec completed"
        _worktree_path, prompt = provider.exec_prompt.call_args.args
        assert "verify spec-001" in prompt
        assert "scope=scoped" in prompt
        assert "scoped_ids=FR-001,FR-002" in prompt
        text = report.read_text(encoding="utf-8")
        assert "verify_scope: scoped" in text
        assert "base_full_verify_commit: base123" in text
        assert "| FR-001 | IMPLEMENTED | src/a.swift | high | keep |" in text
        assert "| FR-002 | IMPLEMENTED | src/b.swift | high | fixed |" in text

    def test_scoped_refresh_bootstraps_full_report_when_baseline_is_missing(
        self, tmp_path
    ):
        _write_verify_skill(tmp_path)
        spec_dir = tmp_path / "specs" / "spec-001-demo"
        _write_spec_inputs(
            spec_dir,
            tasks="- [x] T-001 complexity=standard phase=base req=FR-001 depends=none\n",
        )
        report = spec_dir / "fulfillment-report.md"
        provider = MagicMock()
        provider.cli = "claude"

        def write_full_report(_worktree_path: str, prompt: str) -> int:
            assert "scope=scoped" not in prompt
            report.write_text(
                "| ID | Status | Evidence | Confidence | Notes |\n"
                "| --- | --- | --- | --- | --- |\n"
                "| FR-001 | IMPLEMENTED | hello.py | high | bootstrapped |\n",
                encoding="utf-8",
            )
            return 0

        provider.exec_prompt.side_effect = write_full_report

        with patch("harness.fulfillment_runner._current_git_commit", return_value="head456"):
            result = FulfillmentRunner(provider).refresh(
                str(tmp_path),
                "spec-001",
                scope="scoped",
                completed_task_ids=["T-001"],
            )

        assert result.status == "refreshed"
        assert result.scope == "full"
        assert result.reason == "full verify-spec completed"
        metadata = read_fulfillment_metadata(report)
        assert metadata["verified_commit"] == "head456"
        assert metadata["verify_scope"] == "full"

    def test_scoped_refresh_rechecks_unresolved_ledger_rows_only(self, tmp_path):
        _write_verify_skill(tmp_path)
        spec_dir = tmp_path / "specs" / "spec-001-demo"
        _write_spec_inputs(spec_dir)
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "a.swift").write_text("let a = 1\n", encoding="utf-8")
        (tmp_path / "src" / "b.swift").write_text("let b = 1\n", encoding="utf-8")
        report = spec_dir / "fulfillment-report.md"
        provider = MagicMock()
        provider.cli = "claude"

        def write_full_report(_worktree_path: str, _prompt: str) -> int:
            report.write_text(
                "| ID | Status | Evidence | Confidence | Notes |\n"
                "| --- | --- | --- | --- | --- |\n"
                "| FR-001 | IMPLEMENTED | src/a.swift | high | reusable |\n"
                "| FR-002 | UNVERIFIED | src/b.swift | low | needs proof |\n",
                encoding="utf-8",
            )
            return 0

        def write_scoped_report(_worktree_path: str, _prompt: str) -> int:
            report.write_text(
                "| ID | Status | Evidence | Confidence | Notes |\n"
                "| --- | --- | --- | --- | --- |\n"
                "| FR-002 | IMPLEMENTED | src/b.swift | high | measured |\n",
                encoding="utf-8",
            )
            return 0

        calls = 0

        def exec_prompt(worktree_path: str, prompt: str) -> int:
            nonlocal calls
            calls += 1
            if calls == 1:
                return write_full_report(worktree_path, prompt)
            return write_scoped_report(worktree_path, prompt)

        provider.exec_prompt.side_effect = exec_prompt
        runner = FulfillmentRunner(provider)

        with patch("harness.fulfillment_runner._current_git_commit", return_value="head456"):
            full = runner.refresh(str(tmp_path), "spec-001")
            scoped = runner.refresh(
                str(tmp_path),
                "spec-001",
                scope="scoped",
                completed_task_ids=[],
            )

        assert full.status == "refreshed"
        assert scoped.status == "refreshed"
        assert scoped.verified_ledger == {
            "reused": 1,
            "rechecked": 1,
            "invalidated": 0,
            "unresolved": 1,
        }
        _worktree_path, prompt = provider.exec_prompt.call_args.args
        assert "scope=scoped" in prompt
        assert "scoped_ids=FR-002" in prompt
        assert "scoped_ids=FR-001" not in prompt
        text = report.read_text(encoding="utf-8")
        assert "| FR-001 | IMPLEMENTED | src/a.swift | high | reusable |" in text
        assert "| FR-002 | IMPLEMENTED | src/b.swift | high | measured |" in text

    def test_scoped_refresh_skips_provider_when_no_impacted_ids(self, tmp_path):
        _write_verify_skill(tmp_path)
        spec_dir = tmp_path / "specs" / "spec-001-demo"
        _write_spec_inputs(spec_dir)
        report = spec_dir / "fulfillment-report.md"
        report.write_text(
            "---\nverify_scope: full\nverified_commit: head456\n---\n"
            "| ID | Status | Evidence | Confidence | Notes |\n"
            "| --- | --- | --- | --- | --- |\n"
            "| FR-001 | IMPLEMENTED | src/a.swift | high | keep |\n",
            encoding="utf-8",
        )
        provider = MagicMock()
        provider.cli = "claude"

        with patch("harness.fulfillment_runner._current_git_commit", return_value="head456"):
            result = FulfillmentRunner(provider).refresh(
                str(tmp_path),
                "spec-001",
                scope="scoped",
                completed_task_ids=[],
            )

        assert result.status == "cached"
        assert result.scope == "scoped"
        assert result.reason == "scoped verify-spec skipped; no impacted requirements"
        provider.exec_prompt.assert_not_called()

    def test_scoped_refresh_reuses_ledger_when_commit_changes_but_inputs_do_not(
        self, tmp_path
    ):
        _write_verify_skill(tmp_path)
        spec_dir = tmp_path / "specs" / "spec-001-demo"
        _write_spec_inputs(spec_dir)
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "a.swift").write_text("let a = 1\n", encoding="utf-8")
        report = spec_dir / "fulfillment-report.md"
        provider = MagicMock()
        provider.cli = "claude"

        def write_full_report(_worktree_path: str, _prompt: str) -> int:
            report.write_text(
                "| ID | Status | Evidence | Confidence | Notes |\n"
                "| --- | --- | --- | --- | --- |\n"
                "| FR-001 | IMPLEMENTED | src/a.swift | high | reusable |\n",
                encoding="utf-8",
            )
            return 0

        provider.exec_prompt.side_effect = write_full_report
        runner = FulfillmentRunner(provider)

        with patch(
            "harness.fulfillment_runner._current_git_commit",
            side_effect=["old123", "new456"],
        ):
            full = runner.refresh(str(tmp_path), "spec-001")
            scoped = runner.refresh(
                str(tmp_path),
                "spec-001",
                scope="scoped",
                completed_task_ids=[],
            )

        assert full.status == "refreshed"
        assert scoped.status == "cached"
        assert scoped.scope == "scoped"
        assert scoped.reason == "scoped verify-spec reused verified ledger"
        assert scoped.verified_ledger == {
            "reused": 1,
            "rechecked": 0,
            "invalidated": 0,
            "unresolved": 0,
        }
        provider.exec_prompt.assert_called_once()
        metadata = read_fulfillment_metadata(report)
        assert metadata["verified_commit"] == "new456"
        assert metadata["verify_scope"] == "scoped"
        assert metadata["base_full_verify_commit"] == "old123"
        assert "| FR-001 | IMPLEMENTED | src/a.swift | high | reusable |" in report.read_text(
            encoding="utf-8"
        )

    def test_scoped_refresh_falls_back_to_full_when_report_is_stale(self, tmp_path):
        _write_verify_skill(tmp_path)
        spec_dir = tmp_path / "specs" / "spec-001-demo"
        _write_spec_inputs(spec_dir)
        report = spec_dir / "fulfillment-report.md"
        report.write_text(
            "---\nverify_scope: full\nverified_commit: old123\n---\n"
            "| ID | Status | Evidence | Confidence | Notes |\n"
            "| --- | --- | --- | --- | --- |\n"
            "| FR-001 | IMPLEMENTED | src/a.swift | high | keep |\n",
            encoding="utf-8",
        )
        provider = MagicMock()
        provider.cli = "claude"

        def write_full_report(_worktree_path: str, prompt: str) -> int:
            assert "scope=scoped" not in prompt
            report.write_text(
                "| ID | Status | Evidence | Confidence | Notes |\n"
                "| --- | --- | --- | --- | --- |\n"
                "| FR-001 | IMPLEMENTED | src/a.swift | high | refreshed |\n",
                encoding="utf-8",
            )
            return 0

        provider.exec_prompt.side_effect = write_full_report

        with patch("harness.fulfillment_runner._current_git_commit", return_value="head456"):
            result = FulfillmentRunner(provider).refresh(
                str(tmp_path),
                "spec-001",
                scope="scoped",
                completed_task_ids=[],
            )

        assert result.status == "refreshed"
        assert result.scope == "full"
        assert result.reason == "full verify-spec completed"
        metadata = read_fulfillment_metadata(report)
        assert metadata["verified_commit"] == "head456"
        assert metadata["verify_scope"] == "full"

    def test_scoped_refresh_preserves_explicit_spec_dir_when_falling_back_to_full(
        self, tmp_path
    ):
        _write_verify_skill(tmp_path)
        spec_dir = tmp_path / "authoritative-spec-root" / "spec-001-demo"
        _write_spec_inputs(spec_dir)
        report = spec_dir / "fulfillment-report.md"
        report.write_text(
            "---\nverify_scope: full\nverified_commit: old123\n---\n"
            "| ID | Status | Evidence | Confidence | Notes |\n"
            "| --- | --- | --- | --- | --- |\n"
            "| FR-001 | IMPLEMENTED | src/a.swift | high | keep |\n",
            encoding="utf-8",
        )
        provider = MagicMock()
        provider.cli = "claude"

        def write_full_report(_worktree_path: str, prompt: str) -> int:
            assert "scope=scoped" not in prompt
            assert f"spec_dir={spec_dir}" in prompt
            report.write_text(
                "| ID | Status | Evidence | Confidence | Notes |\n"
                "| --- | --- | --- | --- | --- |\n"
                "| FR-001 | IMPLEMENTED | src/a.swift | high | refreshed |\n",
                encoding="utf-8",
            )
            return 0

        provider.exec_prompt.side_effect = write_full_report

        with patch("harness.fulfillment_runner._current_git_commit", return_value="head456"):
            result = FulfillmentRunner(provider).refresh(
                str(tmp_path),
                "spec-001",
                spec_dir=spec_dir,
                scope="scoped",
                completed_task_ids=[],
            )

        assert result.status == "refreshed"
        assert result.scope == "full"
