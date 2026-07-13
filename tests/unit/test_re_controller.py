from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.re_controller import ReExtractionController
from harness.squad_provider import SquadAgentResult
from tests.unit.test_re_publication import _deep_spec, write_valid_re_run


class _ShallowSpecifierProvider:
    def __init__(self) -> None:
        self.phases: list[str] = []

    def exec_agent(self, project_root: str, prompt: str) -> SquadAgentResult:
        phase = prompt.split("RE phase: ", 1)[1].split("\n", 1)[0]
        self.phases.append(phase)
        return SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "DONE",
                "state_updates": {},
                "journal_entries": [],
            },
            raw_output="",
            duration_ms=1,
            timed_out=False,
        )


def _initialize_re_state(run_dir: Path, *, max_repairs: int) -> None:
    path = run_dir / "re" / "state.json"
    state = json.loads(path.read_text(encoding="utf-8"))
    state.update(
        {
            "status": "in_progress",
            "phase": "re-extract-1-analyze",
            "last_dispatch": {
                "phase_id": None,
                "agent": None,
                "post_dispatch_complete": True,
                "dispatched_at": None,
            },
            "coverage_threshold": 80,
            "resolution_threshold": 80,
            "max_verify_expand_iterations": max_repairs,
            "max_validate_iterations": 3,
            "verify_expand_iterations": 0,
            "validate_iterations": 0,
        }
    )
    path.write_text(json.dumps(state), encoding="utf-8")


def _extension_root(root: Path) -> Path:
    extension_root = root / "extension"
    for name in (
        "analyzer",
        "specifier",
        "verifier",
        "expander",
        "validator",
        "checklister",
        "constituter",
    ):
        path = extension_root / "agents" / "re" / f"{name}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {name}\n", encoding="utf-8")
    return extension_root


@pytest.mark.unit
def test_shallow_specification_runs_only_bounded_repair_before_blocking(
    tmp_path: Path,
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    _initialize_re_state(run_dir, max_repairs=1)
    spec = run_dir / "re" / "sources" / "api" / "specs" / "001-re-domain" / "spec.md"
    spec.write_text("# Architecture summary\n", encoding="utf-8")
    provider = _ShallowSpecifierProvider()
    extension_root = _extension_root(tmp_path)

    result = ReExtractionController(
        provider=provider,
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=extension_root,
    ).run()

    assert result.blocked_reason == "re_deep_spec_gate_failed"
    assert provider.phases == [
        "re-extract-1-analyze",
        "re-extract-2-specify",
        "re-extract-2-specify",
    ]
    state = json.loads((run_dir / "re" / "state.json").read_text(encoding="utf-8"))
    assert state["re_quality_repair_attempts"] == 1
    assert state["re_quality_gate_report"].endswith("quality/deep-spec-gate.json")


@pytest.mark.unit
def test_zero_repair_limit_blocks_before_repair_dispatch(tmp_path: Path) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    _initialize_re_state(run_dir, max_repairs=0)
    spec = run_dir / "re" / "sources" / "api" / "specs" / "001-re-domain" / "spec.md"
    spec.write_text("# Architecture summary\n", encoding="utf-8")
    provider = _ShallowSpecifierProvider()

    result = ReExtractionController(
        provider=provider,
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    ).run()

    assert result.blocked_reason == "re_deep_spec_gate_failed"
    assert provider.phases == ["re-extract-1-analyze", "re-extract-2-specify"]


@pytest.mark.unit
def test_controller_initializes_missing_re_state_before_first_dispatch(
    tmp_path: Path,
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    (run_dir / "re" / "state.json").unlink()

    class BlockingProvider(_ShallowSpecifierProvider):
        def exec_agent(self, project_root: str, prompt: str) -> SquadAgentResult:
            phase = prompt.split("RE phase: ", 1)[1].split("\n", 1)[0]
            self.phases.append(phase)
            return SquadAgentResult(
                exit_code=0,
                echelon_result={
                    "verdict": "BLOCKED",
                    "state_updates": {},
                    "journal_entries": [],
                },
                raw_output="",
                duration_ms=1,
                timed_out=False,
            )

    provider = BlockingProvider()
    result = ReExtractionController(
        provider=provider,
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    ).run()

    assert result.blocked_reason == "re_agent_dispatch_failed"
    state = json.loads((run_dir / "re" / "state.json").read_text(encoding="utf-8"))
    assert state["phase"] == "re-extract-1-analyze"
    assert state["status"] == "blocked"


@pytest.mark.unit
def test_controller_reinitializes_legacy_state_before_first_dispatch(
    tmp_path: Path,
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))

    class BlockingProvider(_ShallowSpecifierProvider):
        def exec_agent(self, project_root: str, prompt: str) -> SquadAgentResult:
            phase = prompt.split("RE phase: ", 1)[1].split("\n", 1)[0]
            self.phases.append(phase)
            return SquadAgentResult(
                exit_code=0,
                echelon_result={
                    "verdict": "BLOCKED",
                    "state_updates": {},
                    "journal_entries": [],
                },
                raw_output="",
                duration_ms=1,
                timed_out=False,
            )

    provider = BlockingProvider()
    extension_root = _extension_root(tmp_path)

    result = ReExtractionController(
        provider=provider,
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=extension_root,
    ).run()

    assert result.blocked_reason == "re_agent_dispatch_failed"
    state = json.loads((run_dir / "re" / "state.json").read_text(encoding="utf-8"))
    assert state["run_id"] == run_dir.name
    assert state["phase"] == "re-extract-1-analyze"


@pytest.mark.unit
def test_repaired_specification_advances_to_all_downstream_re_phases(
    tmp_path: Path,
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    _initialize_re_state(run_dir, max_repairs=1)
    spec = run_dir / "re" / "sources" / "api" / "specs" / "001-re-domain" / "spec.md"
    spec.write_text("# Architecture summary\n", encoding="utf-8")

    class RepairingProvider(_ShallowSpecifierProvider):
        def exec_agent(self, project_root: str, prompt: str) -> SquadAgentResult:
            result = super().exec_agent(project_root, prompt)
            phase = self.phases[-1]
            updates: dict[str, int] = {}
            if phase == "re-extract-2-specify" and self.phases.count(phase) == 2:
                spec.write_text(_deep_spec("api", "v1"), encoding="utf-8")
            if phase == "re-extract-3-verify":
                updates["coverage_pct"] = 80
            if phase == "re-extract-5-validate":
                updates["resolution_pct"] = 80
            return SquadAgentResult(
                exit_code=result.exit_code,
                echelon_result={
                    "verdict": "DONE",
                    "state_updates": updates,
                    "journal_entries": [],
                },
                raw_output=result.raw_output,
                duration_ms=result.duration_ms,
                timed_out=result.timed_out,
            )

    provider = RepairingProvider()
    result = ReExtractionController(
        provider=provider,
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    ).run()

    assert result.completed
    assert provider.phases == [
        "re-extract-1-analyze",
        "re-extract-2-specify",
        "re-extract-2-specify",
        "re-extract-3-verify",
        "re-extract-5-validate",
        "re-extract-6-checklist",
        "re-extract-7-constitute",
    ]


@pytest.mark.unit
def test_below_threshold_coverage_runs_expander_then_reverifies(
    tmp_path: Path,
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    _initialize_re_state(run_dir, max_repairs=2)

    class CoverageLoopProvider(_ShallowSpecifierProvider):
        def exec_agent(self, project_root: str, prompt: str) -> SquadAgentResult:
            result = super().exec_agent(project_root, prompt)
            phase = self.phases[-1]
            updates: dict[str, int] = {}
            if phase == "re-extract-3-verify":
                updates["coverage_pct"] = 70 if self.phases.count(phase) == 1 else 80
                updates["verify_expand_iterations"] = 999
            if phase == "re-extract-5-validate":
                updates["resolution_pct"] = 80
            return SquadAgentResult(
                exit_code=result.exit_code,
                echelon_result={
                    "verdict": "DONE",
                    "state_updates": updates,
                    "journal_entries": [],
                },
                raw_output=result.raw_output,
                duration_ms=result.duration_ms,
                timed_out=result.timed_out,
            )

    provider = CoverageLoopProvider()
    result = ReExtractionController(
        provider=provider,
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    ).run()

    assert result.completed
    assert provider.phases == [
        "re-extract-1-analyze",
        "re-extract-2-specify",
        "re-extract-3-verify",
        "re-extract-4-expand",
        "re-extract-3-verify",
        "re-extract-5-validate",
        "re-extract-6-checklist",
        "re-extract-7-constitute",
    ]
    state = json.loads((run_dir / "re" / "state.json").read_text(encoding="utf-8"))
    assert state["verify_expand_iterations"] == 1


@pytest.mark.unit
def test_quality_repair_cannot_modify_source_analysis(tmp_path: Path) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    _initialize_re_state(run_dir, max_repairs=1)
    source_dir = run_dir / "re" / "sources" / "api"
    spec = source_dir / "specs" / "001-re-domain" / "spec.md"
    spec.write_text("# Architecture summary\n", encoding="utf-8")

    class MutatingRepairProvider(_ShallowSpecifierProvider):
        def exec_agent(self, project_root: str, prompt: str) -> SquadAgentResult:
            result = super().exec_agent(project_root, prompt)
            if (
                self.phases[-1] == "re-extract-2-specify"
                and self.phases.count("re-extract-2-specify") == 2
            ):
                spec.write_text(_deep_spec("api", "v1"), encoding="utf-8")
                (source_dir / "analysis.json").write_text("{\"rewritten\": true}\n", encoding="utf-8")
            return result

    result = ReExtractionController(
        provider=MutatingRepairProvider(),
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    ).run()

    assert result.blocked_reason == "re_quality_repair_modified_immutable_input"


@pytest.mark.unit
def test_quality_repair_cannot_create_non_target_workspace_output(tmp_path: Path) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    _initialize_re_state(run_dir, max_repairs=1)
    spec = run_dir / "re" / "sources" / "api" / "specs" / "001-re-domain" / "spec.md"
    spec.write_text("# Architecture summary\n", encoding="utf-8")

    class MutatingRepairProvider(_ShallowSpecifierProvider):
        def exec_agent(self, project_root: str, prompt: str) -> SquadAgentResult:
            result = super().exec_agent(project_root, prompt)
            if (
                self.phases[-1] == "re-extract-2-specify"
                and self.phases.count("re-extract-2-specify") == 2
            ):
                spec.write_text(_deep_spec("api", "v1"), encoding="utf-8")
                (run_dir / "re" / "workspace" / "unexpected.md").write_text(
                    "not a repair target\n", encoding="utf-8"
                )
            return result

    result = ReExtractionController(
        provider=MutatingRepairProvider(),
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    ).run()

    assert result.blocked_reason == "re_quality_repair_modified_non_target_output"
