"""Tests for BuildResult dataclass."""
from __future__ import annotations
import pytest
from harness.build_result import BuildResult, recover_done_result_from_output


@pytest.mark.unit
class TestBuildResult:
    def test_succeeded_when_status_done(self):
        r = BuildResult(exit_code=0, status="done", impasse_file=None,
                        stdout="", stderr="", duration_ms=100)
        assert r.succeeded is True
        assert r.is_impasse is False

    @pytest.mark.parametrize("status", ["BUILD_DONE", "iteration_done", "partial", "progress"])
    def test_progress_status_aliases_count_as_success(self, status):
        r = BuildResult(exit_code=0, status=status, impasse_file=None,
                        stdout="", stderr="", duration_ms=100)
        assert r.status == "done"
        assert r.succeeded is True
        assert r.is_impasse is False

    def test_is_impasse_when_status_impasse(self):
        r = BuildResult(exit_code=0, status="impasse",
                        impasse_file="codegen-impasse.md",
                        stdout="", stderr="", duration_ms=100)
        assert r.succeeded is False
        assert r.is_impasse is True

    def test_unknown_status_not_succeeded(self):
        r = BuildResult(exit_code=0, status="unknown", impasse_file=None,
                        stdout="", stderr="", duration_ms=100)
        assert r.succeeded is False
        assert r.is_impasse is False

    def test_from_status_file_done(self, tmp_path):
        p = tmp_path / "status.json"
        p.write_text('{"status": "done"}')
        r = BuildResult.from_status_file(p, exit_code=0, stdout="", stderr="", duration_ms=50)
        assert r.status == "done"
        assert r.impasse_file is None

    def test_from_status_file_normalizes_progress_alias(self, tmp_path):
        p = tmp_path / "status.json"
        p.write_text('{"status": "iteration_done", "reason": "implemented verified subset"}')
        r = BuildResult.from_status_file(p, exit_code=0, stdout="", stderr="", duration_ms=50)
        assert r.status == "done"
        assert r.succeeded is True
        assert r.reason == "implemented verified subset"

    def test_from_status_file_reads_completed_task_ids(self, tmp_path):
        p = tmp_path / "status.json"
        p.write_text(
            '{"status": "done", "completed_task_ids": ["T-001", "T-002", " "]}'
        )

        r = BuildResult.from_status_file(
            p, exit_code=0, stdout="", stderr="", duration_ms=50
        )

        assert r.task_ids == ["T-001", "T-002"]

    def test_from_status_file_impasse(self, tmp_path):
        p = tmp_path / "status.json"
        p.write_text('{"status": "impasse", "impasse_file": "codegen-impasse.md"}')
        r = BuildResult.from_status_file(p, exit_code=0, stdout="", stderr="", duration_ms=50)
        assert r.status == "impasse"
        assert r.impasse_file == "codegen-impasse.md"

    def test_from_status_file_missing_returns_unknown(self, tmp_path):
        p = tmp_path / "missing.json"
        r = BuildResult.from_status_file(p, exit_code=0, stdout="", stderr="", duration_ms=50)
        assert r.status == "unknown"

    def test_from_status_file_malformed_returns_unknown(self, tmp_path):
        p = tmp_path / "status.json"
        p.write_text("not json{{{")
        r = BuildResult.from_status_file(p, exit_code=0, stdout="", stderr="", duration_ms=50)
        assert r.status == "unknown"

    def test_from_status_file_non_dict_json_returns_unknown(self, tmp_path):
        p = tmp_path / "status.json"
        p.write_text('"done"')  # valid JSON, but not an object
        r = BuildResult.from_status_file(p, exit_code=0, stdout="", stderr="", duration_ms=50)
        assert r.status == "unknown"

    def test_recovers_completed_task_ids_from_final_json_output(self):
        stdout = """
Build slice complete.

```json
{
  "status": "complete",
  "state_updates": {
    "last_verify_result": "pass",
    "completed_task_ids": ["T-001", "T-002", " "]
  },
  "verification": {"tests": "passed"}
}
```
"""

        r = recover_done_result_from_output(
            stdout=stdout,
            stderr="",
            exit_code=0,
            duration_ms=50,
        )

        assert r is not None
        assert r.status == "done"
        assert r.task_ids == ["T-001", "T-002"]
        assert "final JSON output" in (r.reason or "")

    def test_does_not_recover_from_prose_only_task_ids(self):
        r = recover_done_result_from_output(
            stdout='completed_task_ids: ["T-001"]',
            stderr="",
            exit_code=0,
            duration_ms=50,
        )

        assert r is None

    def test_does_not_recover_failed_json_status(self):
        r = recover_done_result_from_output(
            stdout='```json\n{"status":"blocked","completed_task_ids":["T-001"]}\n```',
            stderr="",
            exit_code=0,
            duration_ms=50,
        )

        assert r is None
