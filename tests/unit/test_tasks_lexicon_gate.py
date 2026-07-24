from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.tasks_lexicon_gate import run_tasks_lexicon_gate


def _config(
    *,
    enabled: bool = True,
    global_enabled: bool = True,
    on_exhausted: str = "block",
    max_repair_attempts: int = 3,
) -> dict:
    return {
        "lexicon_gate": {
            "enabled": global_enabled,
            "max_repair_attempts": max_repair_attempts,
            "on_exhausted": on_exhausted,
            "glossary_file": "glossary.md",
            "artifacts": {
                "tasks": {
                    "enabled": enabled,
                    "path": "tasks.md",
                    "spec_ref": "requirements.lexicon.md",
                    "report": "tasks-lexicon-report.json",
                }
            },
        }
    }


def _valid_spec() -> str:
    return """ARTIFACT: SPEC
TITLE: Demo

REQ: REQ-001
GIVEN: input exists
WHEN: processing starts
THEN: the system SHALL return output
OUTPUT: output
DEPENDS: none
EXAMPLE: none
"""


def _valid_tasks() -> str:
    return """# Tasks: Demo

## Phase: build

- [ ] T-001 complexity=standard phase=build req=REQ-001 depends=none target=sources/app

  **Title:** Implement output
  **Description:** Implement the output path.
  **Files:**
  - `sources/app/main.py`
  **Test:** a test asserts that the output is returned
  **Acceptance Criteria:**
  - [ ] the output is returned
"""


def _write_valid_plan(spec_dir: Path) -> None:
    spec_dir.mkdir(parents=True)
    (spec_dir / "requirements.lexicon.md").write_text(
        _valid_spec(),
        encoding="utf-8",
    )
    (spec_dir / "tasks.md").write_text(_valid_tasks(), encoding="utf-8")
    (spec_dir / "glossary.md").write_text("", encoding="utf-8")
    for name in ("critical-path.md", "risk-matrix.md", "dependencies.md"):
        (spec_dir / name).write_text(f"# {name}\n", encoding="utf-8")
    (spec_dir / "targets.yml").write_text(
        """schema_version: 1
targets:
  - id: app
    path: sources/app
    role: primary
    branch: 001-demo
""",
        encoding="utf-8",
    )


def _run(
    tmp_path: Path,
    spec_dir: Path,
    *,
    config: dict | None = None,
    previous_attempts: object = 0,
    iteration: object = 0,
    max_iterations: object = 5,
):
    return run_tasks_lexicon_gate(
        project_root=tmp_path,
        spec_dir_ref=str(spec_dir),
        config=config or _config(),
        previous_attempts=previous_attempts,
        workflow_iteration=iteration,
        max_workflow_iterations=max_iterations,
    )


def test_valid_tasks_pass_and_reset_attempts(tmp_path: Path) -> None:
    spec_dir = tmp_path / "specs" / "001-demo"
    _write_valid_plan(spec_dir)

    result = _run(tmp_path, spec_dir, previous_attempts=2)

    assert result.action == "proceed"
    assert result.passed is True
    assert result.attempts == 0
    assert result.findings == 0
    assert result.blocked_reason is None
    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert report == {
        "schema_version": 1,
        "ok": True,
        "tasks": "tasks.md",
        "spec_ref": "requirements.lexicon.md",
        "findings": [],
    }


@pytest.mark.parametrize(
    ("global_enabled", "tasks_enabled"),
    [(False, True), (True, False)],
)
def test_disabled_gate_returns_passing_bypass(
    tmp_path: Path,
    global_enabled: bool,
    tasks_enabled: bool,
) -> None:
    result = run_tasks_lexicon_gate(
        project_root=tmp_path,
        spec_dir_ref="",
        config=_config(
            global_enabled=global_enabled,
            enabled=tasks_enabled,
        ),
        previous_attempts=2,
        workflow_iteration=4,
        max_workflow_iterations=5,
    )

    assert result.action == "proceed"
    assert result.passed is True
    assert result.attempts == 0
    assert result.findings == 0
    assert result.report_path is None


def test_invalid_tasks_request_repair_and_increment_attempts(tmp_path: Path) -> None:
    spec_dir = tmp_path / "specs" / "001-demo"
    _write_valid_plan(spec_dir)
    (spec_dir / "tasks.md").write_text("not TASKS grammar\n", encoding="utf-8")

    result = _run(tmp_path, spec_dir, previous_attempts=1)

    assert result.action == "repair"
    assert result.passed is False
    assert result.attempts == 2
    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert report["ok"] is False
    assert any(item["code"] == "parse-error" for item in report["findings"])


@pytest.mark.parametrize(
    "missing_name",
    ["tasks.md", "critical-path.md", "risk-matrix.md", "dependencies.md"],
)
def test_missing_plan_output_is_repairable(
    tmp_path: Path,
    missing_name: str,
) -> None:
    spec_dir = tmp_path / "specs" / "001-demo"
    _write_valid_plan(spec_dir)
    (spec_dir / missing_name).unlink()

    result = _run(tmp_path, spec_dir)

    assert result.action == "repair"
    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert any(
        finding["code"] == "missing-plan-output"
        and finding["artifact"] == missing_name
        for finding in report["findings"]
    )


def test_missing_spec_reference_is_repairable(tmp_path: Path) -> None:
    spec_dir = tmp_path / "specs" / "001-demo"
    _write_valid_plan(spec_dir)
    (spec_dir / "requirements.lexicon.md").unlink()

    result = _run(tmp_path, spec_dir)

    assert result.action == "repair"
    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert any(
        finding["code"] == "missing-spec-ref"
        for finding in report["findings"]
    )


def test_invalid_target_ownership_is_repairable(tmp_path: Path) -> None:
    spec_dir = tmp_path / "specs" / "001-demo"
    _write_valid_plan(spec_dir)
    (spec_dir / "tasks.md").write_text(
        _valid_tasks().replace("target=sources/app", "target=sources/other"),
        encoding="utf-8",
    )

    result = _run(tmp_path, spec_dir)

    assert result.action == "repair"
    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    codes = {item["code"] for item in report["findings"]}
    assert "undeclared-target" in codes


@pytest.mark.parametrize(
    ("on_exhausted", "expected"),
    [("warn", "proceed_with_warning"), ("block", "block")],
)
def test_attempt_exhaustion_policy_is_explicit(
    tmp_path: Path,
    on_exhausted: str,
    expected: str,
) -> None:
    spec_dir = tmp_path / "specs" / "001-demo"
    _write_valid_plan(spec_dir)
    (spec_dir / "tasks.md").write_text("invalid\n", encoding="utf-8")

    result = _run(
        tmp_path,
        spec_dir,
        config=_config(on_exhausted=on_exhausted),
        previous_attempts=2,
    )

    assert result.action == expected
    assert result.attempts == 3
    assert result.passed is False
    if expected == "block":
        assert result.blocked_reason == "lexicon_gate_exhausted"


def test_iteration_exhaustion_uses_warning_policy(tmp_path: Path) -> None:
    spec_dir = tmp_path / "specs" / "001-demo"
    _write_valid_plan(spec_dir)
    (spec_dir / "tasks.md").write_text("invalid\n", encoding="utf-8")

    result = _run(
        tmp_path,
        spec_dir,
        config=_config(on_exhausted="warn"),
        iteration=5,
        max_iterations=5,
    )

    assert result.action == "proceed_with_warning"
    assert result.attempts == 1


def test_missing_controller_context_blocks_without_incrementing_attempts(
    tmp_path: Path,
) -> None:
    result = run_tasks_lexicon_gate(
        project_root=tmp_path,
        spec_dir_ref="",
        config=_config(),
        previous_attempts=2,
        workflow_iteration=0,
        max_workflow_iterations=5,
    )

    assert result.action == "block"
    assert result.passed is False
    assert result.attempts == 2
    assert result.report_path is None
    assert result.blocked_reason == "tasks_lexicon_spec_dir_missing"


def test_custom_configured_paths_are_used(tmp_path: Path) -> None:
    spec_dir = tmp_path / "specs" / "001-demo"
    _write_valid_plan(spec_dir)
    (spec_dir / "tasks.md").rename(spec_dir / "work-items.md")
    (spec_dir / "requirements.lexicon.md").rename(spec_dir / "requirements.md")
    config = _config()
    config["lexicon_gate"]["artifacts"]["tasks"].update(
        {
            "path": "work-items.md",
            "spec_ref": "requirements.md",
            "report": "evidence/tasks-report.json",
        }
    )

    result = _run(tmp_path, spec_dir, config=config)

    assert result.action == "proceed"
    assert result.report_path == spec_dir / "evidence" / "tasks-report.json"


def test_report_write_failure_blocks_without_incrementing_attempts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec_dir = tmp_path / "specs" / "001-demo"
    _write_valid_plan(spec_dir)

    def fail_write(_path, _payload):
        raise OSError("disk full")

    monkeypatch.setattr(
        "harness.tasks_lexicon_gate.write_json_atomic",
        fail_write,
    )

    result = _run(tmp_path, spec_dir, previous_attempts=2)

    assert result.action == "block"
    assert result.attempts == 2
    assert result.blocked_reason == "tasks_lexicon_evidence_write_failed"
    assert "disk full" in result.detail
