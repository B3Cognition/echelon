"""Tests for BuildResult dataclass."""
from __future__ import annotations
import pytest
from harness.build_result import BuildResult


@pytest.mark.unit
class TestBuildResult:
    def test_succeeded_when_status_done(self):
        r = BuildResult(exit_code=0, status="done", impasse_file=None,
                        stdout="", stderr="", duration_ms=100)
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
