from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.re_controller import ReExtractionController
from harness.squad_provider import SquadAgentResult
from tests.unit.test_re_publication import _deep_spec, write_valid_re_run


@pytest.fixture(autouse=True)
def _stub_controller_analysis_script(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ReExtractionController,
        "_run_analysis_script",
        lambda _controller, _plan: None,
    )


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
        "re-extract-2-specify",
        "re-extract-2-specify",
    ]
    state = json.loads((run_dir / "re" / "state.json").read_text(encoding="utf-8"))
    assert state["re_quality_repair_attempts"] == 1
    assert state["re_quality_gate_report"].endswith("quality/deep-spec-gate.json")


@pytest.mark.unit
def test_failed_repair_passes_are_rescheduled_until_their_bound(tmp_path: Path) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    _initialize_re_state(run_dir, max_repairs=2)
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
    assert provider.phases == ["re-extract-2-specify"] * 3
    state = json.loads((run_dir / "re" / "state.json").read_text(encoding="utf-8"))
    assert state["re_quality_repair_attempts"] == 2


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
    assert provider.phases == ["re-extract-2-specify"]


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
    assert state["phase"] == "re-extract-2-specify"
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
    assert state["phase"] == "re-extract-2-specify"


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
        "re-extract-2-specify",
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
        "re-extract-2-specify",
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
def test_controller_dispatches_one_specifier_call_for_each_required_domain(
    tmp_path: Path,
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    _initialize_re_state(run_dir, max_repairs=1)
    source_root = tmp_path / "sources" / "api"
    for root in ("apps/public-api", "apps/worker"):
        directory = source_root / root
        directory.mkdir(parents=True)
        for number in range(1, 6):
            (directory / f"file-{number}.ts").write_text("export {};\n", encoding="utf-8")
    manifest = run_dir / "re" / "sources" / "api" / "domain-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source_id": "api",
                "source_path": "sources/api",
                "domains": [
                    {
                        "domain_id": "001-re-public-api",
                        "root": "apps/public-api",
                        "source_file_count": 5,
                        "source_line_count": 5,
                    },
                    {
                        "domain_id": "002-re-worker",
                        "root": "apps/worker",
                        "source_file_count": 5,
                        "source_line_count": 5,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    specs_root = run_dir / "re" / "sources" / "api" / "specs"
    for path in specs_root.glob("*"):
        if path.is_dir():
            __import__("shutil").rmtree(path)

    class DomainProvider(_ShallowSpecifierProvider):
        def __init__(self) -> None:
            super().__init__()
            self.domain_targets: list[str] = []

        def exec_agent(self, project_root: str, prompt: str) -> SquadAgentResult:
            result = super().exec_agent(project_root, prompt)
            if "Generate exactly one deep source-domain spec" in prompt:
                domain_id = prompt.split("Domain ID: `", 1)[1].split("`", 1)[0]
                root = prompt.split("Owned source root: `", 1)[1].split("`", 1)[0]
                self.domain_targets.append(domain_id)
                evidence = "\n".join(
                    f"- `{root}/file-{number}.ts:1`" for number in range(1, 6)
                )
                (specs_root / domain_id).mkdir(parents=True, exist_ok=True)
                (specs_root / domain_id / "spec.md").write_text(
                    "\n".join(
                        [
                            f"# {domain_id}",
                            "## User Scenarios & Testing",
                            "Scenario coverage.",
                            "## Requirements (Functional)",
                            "Functional behavior.",
                            "## Key Entities",
                            "Domain entities.",
                            "## Edge Cases",
                            "Observed failure paths.",
                            "## Source Evidence",
                            evidence,
                        ]
                    )
                    + "\n",
                    encoding="utf-8",
                )
            phase = self.phases[-1]
            updates: dict[str, int] = {}
            if phase == "re-extract-3-verify":
                updates["coverage_pct"] = 80
            if phase == "re-extract-5-validate":
                updates["resolution_pct"] = 80
            return SquadAgentResult(
                exit_code=result.exit_code,
                echelon_result={"verdict": "DONE", "state_updates": updates, "journal_entries": []},
                raw_output="",
                duration_ms=1,
                timed_out=False,
            )

    provider = DomainProvider()
    result = ReExtractionController(
        provider=provider,
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    ).run()

    assert result.completed
    assert provider.domain_targets == ["001-re-public-api", "002-re-worker"]
    assert (specs_root / "001-re-public-api" / "spec.md").is_file()
    assert (specs_root / "002-re-worker" / "spec.md").is_file()


@pytest.mark.unit
def test_controller_ignores_non_routing_repair_metadata_from_a_done_agent(
    tmp_path: Path,
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    _initialize_re_state(run_dir, max_repairs=1)

    class RepairMetadataProvider(_ShallowSpecifierProvider):
        def exec_agent(self, project_root: str, prompt: str) -> SquadAgentResult:
            result = super().exec_agent(project_root, prompt)
            phase = self.phases[-1]
            updates: dict[str, object] = {"repair_action": "deep_spec_gate_repair"}
            if phase == "re-extract-3-verify":
                updates["coverage_pct"] = 80
            if phase == "re-extract-5-validate":
                updates["resolution_pct"] = 80
            return SquadAgentResult(
                exit_code=0,
                echelon_result={"verdict": "DONE", "state_updates": updates, "journal_entries": []},
                raw_output="",
                duration_ms=1,
                timed_out=False,
            )

    result = ReExtractionController(
        provider=RepairMetadataProvider(),
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    ).run()

    assert result.completed


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


@pytest.mark.unit
def test_quality_repair_snapshot_allows_creation_of_a_missing_target_spec(
    tmp_path: Path,
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    missing_spec = (
        run_dir / "re" / "sources" / "api" / "specs" / "001-re-domain" / "spec.md"
    )
    missing_spec.unlink()
    controller = ReExtractionController(
        provider=_ShallowSpecifierProvider(),
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    )

    before = controller._non_target_snapshot([missing_spec])
    missing_spec.parent.mkdir(parents=True, exist_ok=True)
    missing_spec.write_text(_deep_spec("api", "v1"), encoding="utf-8")
    after = controller._non_target_snapshot([missing_spec])

    assert before == after


@pytest.mark.unit
@pytest.mark.parametrize("filename", ("ECHELON_RESULT.yaml", "REPAIR_RESULT.yaml"))
def test_quality_repair_snapshot_ignores_provider_result_capture(
    tmp_path: Path, filename: str
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    controller = ReExtractionController(
        provider=_ShallowSpecifierProvider(),
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    )
    spec = run_dir / "re" / "sources" / "api" / "specs" / "001-re-domain" / "spec.md"

    before = controller._non_target_snapshot([spec])
    (run_dir / "re" / filename).write_text(
        "echelon_result:\n  verdict: DONE\n",
        encoding="utf-8",
    )
    after = controller._non_target_snapshot([spec])

    assert before == after


@pytest.mark.unit
def test_quality_repair_snapshot_rejects_nested_result_capture(tmp_path: Path) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    controller = ReExtractionController(
        provider=_ShallowSpecifierProvider(),
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    )
    spec = run_dir / "re" / "sources" / "api" / "specs" / "001-re-domain" / "spec.md"

    before = controller._non_target_snapshot([spec])
    nested_capture = run_dir / "re" / "sources" / "api" / "REPAIR_RESULT.yaml"
    nested_capture.write_text("echelon_result:\n  verdict: DONE\n", encoding="utf-8")
    after = controller._non_target_snapshot([spec])

    assert before != after


@pytest.mark.unit
def test_controller_prepares_an_empty_target_spec_before_specifier_dispatch(
    tmp_path: Path,
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    _initialize_re_state(run_dir, max_repairs=0)
    spec = run_dir / "re" / "sources" / "api" / "specs" / "001-re-domain" / "spec.md"
    spec.unlink()

    class ObservingProvider(_ShallowSpecifierProvider):
        def exec_agent(self, project_root: str, prompt: str) -> SquadAgentResult:
            result = super().exec_agent(project_root, prompt)
            if self.phases[-1] == "re-extract-2-specify":
                assert spec.is_file()
                assert spec.read_text(encoding="utf-8") == ""
            return result

    result = ReExtractionController(
        provider=ObservingProvider(),
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    ).run()

    assert result.blocked_reason == "re_deep_spec_gate_failed"
