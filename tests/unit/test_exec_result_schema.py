"""Tests for ExecResult schema validation.

5 tests per test-strategy 3.1:
- Valid ExecResult deserializes correctly
- Missing field raises SchemaViolationError
- Null exit_code raises SchemaViolationError
- Default fill for missing resource_stats
- Special exit codes recognized
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.errors import SchemaViolationError
from harness.exec_result import (
    EXIT_FORCE_KILL,
    EXIT_OOM,
    EXIT_PID_LIMIT,
    EXIT_STORAGE_LIMIT,
    EXIT_TIMEOUT,
    ExecResult,
)


FIXTURES = Path(__file__).parent.parent / "fixtures" / "exec-results"


def _load_fixture(name: str) -> dict:
    with open(FIXTURES / name) as f:
        return json.load(f)


@pytest.mark.unit
class TestExecResultFromDict:
    """Test ExecResult.from_dict validation."""

    def test_valid_success_deserializes(self) -> None:
        data = _load_fixture("valid-success.json")
        result = ExecResult.from_dict(data)
        assert result.exit_code == 0
        assert "42 tests passed" in result.stdout
        assert result.duration_ms == 12345
        assert result.resource_stats is not None
        assert result.resource_stats.peak_memory_bytes == 104857600
        assert result.truncated is False

    def test_missing_exit_code_raises_schema_violation(self) -> None:
        data = _load_fixture("invalid-missing-field.json")
        with pytest.raises(SchemaViolationError, match="exit_code"):
            ExecResult.from_dict(data)

    def test_null_exit_code_raises_schema_violation(self) -> None:
        data = _load_fixture("invalid-null-exit-code.json")
        with pytest.raises(SchemaViolationError, match="exit_code"):
            ExecResult.from_dict(data)

    def test_missing_resource_stats_defaults_to_none(self) -> None:
        data = _load_fixture("valid-timeout.json")
        result = ExecResult.from_dict(data)
        assert result.resource_stats is None
        assert result.exit_code == EXIT_TIMEOUT

    def test_special_exit_codes_recognized(self) -> None:
        for code, name in [
            (EXIT_TIMEOUT, "timeout"),
            (EXIT_FORCE_KILL, "force-kill"),
            (EXIT_OOM, "OOM"),
            (EXIT_PID_LIMIT, "PID limit"),
            (EXIT_STORAGE_LIMIT, "storage limit"),
        ]:
            result = ExecResult.from_dict({
                "exit_code": code,
                "stdout": "",
                "stderr": "",
                "duration_ms": 100,
            })
            assert result.is_special_exit
            assert result.special_exit_reason == name
