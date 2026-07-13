from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from harness.re_controller import ReExtractionController
from harness.re_domain_manifest import DOMAIN_PARTITION_VERSION
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
        payload: dict[str, object] = {
            "verdict": "DONE",
            "state_updates": {},
            "journal_entries": [],
        }
        if phase == "re-extract-5-validate":
            payload["semantic_quality_review"] = _passing_semantic_quality_review(prompt)
        return SquadAgentResult(
            exit_code=0,
            echelon_result=payload,
            raw_output="",
            duration_ms=1,
            timed_out=False,
        )


def _passing_semantic_quality_review(prompt: str) -> dict[str, object]:
    re_dir = Path(prompt.split("RE output directory: ", 1)[1].split("\n", 1)[0])
    domains: list[dict[str, object]] = []
    for manifest_path in sorted((re_dir / "sources").glob("*/domain-manifest.json")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        source_id = manifest["source_id"]
        for domain in manifest["domains"]:
            domains.append(
                {
                    "source_id": source_id,
                    "domain_id": domain["domain_id"],
                    "verdict": "PASS",
                    "findings": [],
                    "source_evidence": [],
                }
            )
    return {"schema_version": 1, "domains": domains}


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
            "re_domain_partition_version": DOMAIN_PARTITION_VERSION,
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

    assert result.blocked_reason == "re_domain_deep_spec_gate_failed"
    assert provider.phases == [
        "re-extract-2-specify",
        "re-extract-2-specify",
    ]
    state = json.loads((run_dir / "re" / "state.json").read_text(encoding="utf-8"))
    assert state["re_domain_quality_attempts"] == {"api/001-re-domain": 2}
    assert state["re_target_quality_gate_report"].endswith(
        "quality/targets/api/001-re-domain.json"
    )


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

    assert result.blocked_reason == "re_domain_deep_spec_gate_failed"
    assert provider.phases == ["re-extract-2-specify"] * 3
    state = json.loads((run_dir / "re" / "state.json").read_text(encoding="utf-8"))
    assert state["re_domain_quality_attempts"] == {"api/001-re-domain": 3}


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

    assert result.blocked_reason == "re_domain_deep_spec_gate_failed"
    assert provider.phases == ["re-extract-2-specify"]


def test_controller_passes_architecture_order_to_each_domain_specifier(
    tmp_path: Path,
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    _initialize_re_state(run_dir, max_repairs=1)

    class CapturingProvider(_ShallowSpecifierProvider):
        def __init__(self) -> None:
            super().__init__()
            self.prompts: list[str] = []

        def exec_agent(self, project_root: str, prompt: str) -> SquadAgentResult:
            self.prompts.append(prompt)
            result = super().exec_agent(project_root, prompt)
            if "RE phase: re-extract-3-verify" in prompt:
                result.echelon_result["state_updates"] = {"coverage_pct": 100}
            return result

    provider = CapturingProvider()
    result = ReExtractionController(
        provider=provider,
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    ).run()

    assert result.completed
    specification_prompt = next(
        prompt for prompt in provider.prompts if "RE phase: re-extract-2-specify" in prompt
    )
    assert "Architecture composition is controller-owned and read-only." in specification_prompt
    assert "migration wave `1`" in specification_prompt
    assert (run_dir / "re" / "workspace" / "architecture-map.json").is_file()
    assert (run_dir / "re" / "workspace" / "domain-catalog.md").is_file()


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
def test_legacy_specification_resume_queues_invalid_specs_before_dispatch(
    tmp_path: Path,
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api", "web"))
    _initialize_re_state(run_dir, max_repairs=1)
    state_path = run_dir / "re" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.update(
        {
            "phase": "re-extract-2-specify",
            "re_specification_targets": [
                {
                    "kind": "source-domain",
                    "source_id": "web",
                    "domain_id": "001-re-domain",
                    "root": "src",
                }
            ],
            "re_domain_quality_attempts": {"api/001-re-domain": 5},
        }
    )
    state_path.write_text(json.dumps(state), encoding="utf-8")
    (run_dir / "re" / "sources" / "api" / "specs" / "001-re-domain" / "spec.md").write_text(
        "# Architecture summary\n", encoding="utf-8"
    )

    controller = ReExtractionController(
        provider=_ShallowSpecifierProvider(),
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    )
    state = json.loads(state_path.read_text(encoding="utf-8"))

    assert controller._ensure_target_quality_protocol(state, controller._load_plan()) is None
    assert state["re_target_quality_protocol_version"] == 1
    assert state["re_specification_targets"] == [
        {
            "kind": "source-domain",
            "source_id": "api",
            "domain_id": "001-re-domain",
            "root": "src",
        }
    ]
    assert "re_domain_quality_attempts" not in state
    assert state["re_quality_gate_report"].endswith("quality/deep-spec-gate.json")


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
                    **result.echelon_result,
                    "state_updates": updates,
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
                    **result.echelon_result,
                    "state_updates": updates,
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
                scenarios = "\n\n".join(
                    (
                        f"### Scenario {number}: API behavior {number}\n\n"
                        f"Source Evidence: `{root}/file-{((number - 1) % 5) + 1}.ts:1`\n\n"
                        "Given valid input, When the API is invoked, Then the result is returned."
                    )
                    for number in range(1, 6)
                )
                functional_requirements = "\n\n".join(
                    (
                        f"### FR-{number:03d}: API requirement {number}\n\n"
                        f"Source Evidence: `{root}/file-{((number - 1) % 5) + 1}.ts:1`"
                    )
                    for number in range(1, 8)
                )
                non_functional_requirements = "\n\n".join(
                    (
                        f"### NFR-{number:03d}: API constraint {number}\n\n"
                        f"Source Evidence: `{root}/file-{((number - 1) % 5) + 1}.ts:1`"
                    )
                    for number in range(1, 4)
                )
                (specs_root / domain_id).mkdir(parents=True, exist_ok=True)
                (specs_root / domain_id / "spec.md").write_text(
                    "\n".join(
                        [
                            f"# {domain_id}",
                            "## User Scenarios & Testing",
                            scenarios,
                            "## Requirements (Functional)",
                            functional_requirements,
                            "## Requirements (Non-Functional)",
                            non_functional_requirements,
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
                echelon_result={**result.echelon_result, "state_updates": updates},
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
                echelon_result={**result.echelon_result, "state_updates": updates},
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
def test_semantic_quality_repair_returns_only_the_failed_domain_to_specifier(
    tmp_path: Path,
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    _initialize_re_state(run_dir, max_repairs=1)
    spec = run_dir / "re" / "sources" / "api" / "specs" / "001-re-domain" / "spec.md"

    class SemanticRepairProvider(_ShallowSpecifierProvider):
        def exec_agent(self, project_root: str, prompt: str) -> SquadAgentResult:
            result = super().exec_agent(project_root, prompt)
            phase = self.phases[-1]
            payload = dict(result.echelon_result)
            updates: dict[str, int] = {}
            if phase == "re-extract-3-verify":
                updates["coverage_pct"] = 80
            if phase == "re-extract-5-validate":
                review = _passing_semantic_quality_review(prompt)
                if self.phases.count(phase) == 1:
                    review["domains"] = [
                        {
                            "source_id": "api",
                            "domain_id": "001-re-domain",
                            "verdict": "REPAIR",
                            "findings": [
                                "FR-001 omits the observed retry exhaustion behavior."
                            ],
                            "source_evidence": ["`src/file-1.ts:1`"],
                        }
                    ]
                payload["semantic_quality_review"] = review
            if (
                phase == "re-extract-2-specify"
                and self.phases.count(phase) == 3
            ):
                spec.write_text(
                    spec.read_text(encoding="utf-8")
                    + "\nRetry exhaustion is documented from `src/file-1.ts:1`.\n",
                    encoding="utf-8",
                )
            payload["state_updates"] = updates
            return SquadAgentResult(
                exit_code=0,
                echelon_result=payload,
                raw_output="",
                duration_ms=1,
                timed_out=False,
            )

    provider = SemanticRepairProvider()
    result = ReExtractionController(
        provider=provider,
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    ).run()

    assert result.completed
    assert provider.phases.count("re-extract-2-specify") == 3
    assert provider.phases.count("re-extract-5-validate") == 2
    assert "Retry exhaustion is documented" in spec.read_text(encoding="utf-8")
    state = json.loads((run_dir / "re" / "state.json").read_text(encoding="utf-8"))
    assert state["re_quality_repair_attempts"] == 1
    assert state["re_semantic_quality_report"].endswith("quality/semantic-quality-review.json")


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
@pytest.mark.parametrize(
    "filename",
    ("ECHELON_RESULT.yaml", "REPAIR_RESULT.yaml", "echelon_result.json", ".DS_Store"),
)
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
def test_architecture_overlay_refreshes_active_repair_snapshot(tmp_path: Path) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    _initialize_re_state(run_dir, max_repairs=1)
    controller = ReExtractionController(
        provider=_ShallowSpecifierProvider(),
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    )
    plan = controller._load_plan()
    state = json.loads((run_dir / "re" / "state.json").read_text(encoding="utf-8"))
    (run_dir / "re" / "workspace" / "architecture-map.json").unlink()
    (run_dir / "re" / "workspace" / "domain-catalog.md").unlink()
    target = {
        "kind": "source-domain",
        "source_id": "api",
        "domain_id": "001-re-domain",
        "root": "src",
    }
    report = controller._target_quality_report(plan, target)
    assert report is not None
    state.update(
        {
            "phase": "re-extract-2-specify",
            "re_target_quality_repair_snapshot": controller._repair_snapshot(report),
        }
    )
    controller._save_state(state)

    assert controller._ensure_architecture_overlay(state, plan) is None
    assert (run_dir / "re" / "workspace" / "architecture-map.json").is_file()
    assert (run_dir / "re" / "workspace" / "domain-catalog.md").is_file()
    assert (
        controller._repair_snapshot_failure(
            state, "re_target_quality_repair_snapshot"
        )
        is None
    )


@pytest.mark.unit
def test_architecture_overlay_does_not_mask_non_target_change(tmp_path: Path) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    _initialize_re_state(run_dir, max_repairs=1)
    controller = ReExtractionController(
        provider=_ShallowSpecifierProvider(),
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    )
    plan = controller._load_plan()
    state = json.loads((run_dir / "re" / "state.json").read_text(encoding="utf-8"))
    (run_dir / "re" / "workspace" / "architecture-map.json").unlink()
    (run_dir / "re" / "workspace" / "domain-catalog.md").unlink()
    target = {
        "kind": "source-domain",
        "source_id": "api",
        "domain_id": "001-re-domain",
        "root": "src",
    }
    report = controller._target_quality_report(plan, target)
    assert report is not None
    state["re_target_quality_repair_snapshot"] = controller._repair_snapshot(report)
    (run_dir / "re" / "workspace").mkdir(parents=True, exist_ok=True)
    (run_dir / "re" / "workspace" / "unexpected.md").write_text(
        "not controller output\n", encoding="utf-8"
    )

    assert (
        controller._ensure_architecture_overlay(state, plan)
        == "re_quality_repair_modified_non_target_output"
    )


@pytest.mark.unit
def test_architecture_overlay_migrates_legacy_finder_snapshot(tmp_path: Path) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    _initialize_re_state(run_dir, max_repairs=1)
    controller = ReExtractionController(
        provider=_ShallowSpecifierProvider(),
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    )
    plan = controller._load_plan()
    state = json.loads((run_dir / "re" / "state.json").read_text(encoding="utf-8"))
    target = {
        "kind": "source-domain",
        "source_id": "api",
        "domain_id": "001-re-domain",
        "root": "src",
    }
    report = controller._target_quality_report(plan, target)
    assert report is not None
    snapshot = controller._repair_snapshot(report)
    outputs = snapshot["non_target_outputs"]
    assert isinstance(outputs, dict)
    outputs.pop("workspace/architecture-map.json", None)
    outputs.pop("workspace/domain-catalog.md", None)
    outputs[".DS_Store"] = "legacy-finder-metadata"
    state["re_target_quality_repair_snapshot"] = snapshot

    assert controller._ensure_architecture_overlay(state, plan) is None
    assert (
        controller._repair_snapshot_failure(
            state, "re_target_quality_repair_snapshot"
        )
        is None
    )


@pytest.mark.unit
def test_quality_repair_allows_root_echelon_result_capture(tmp_path: Path) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    _initialize_re_state(run_dir, max_repairs=1)
    spec = run_dir / "re" / "sources" / "api" / "specs" / "001-re-domain" / "spec.md"
    spec.write_text("# Incomplete\n", encoding="utf-8")

    class CaptureWritingProvider(_ShallowSpecifierProvider):
        def exec_agent(self, project_root: str, prompt: str) -> SquadAgentResult:
            result = super().exec_agent(project_root, prompt)
            phase = self.phases[-1]
            payload = dict(result.echelon_result)
            updates: dict[str, int] = {}
            if phase == "re-extract-2-specify" and self.phases.count(phase) == 2:
                spec.write_text(_deep_spec("api", "v1"), encoding="utf-8")
                (run_dir / "re" / "echelon_result.json").write_text(
                    '{"echelon_result": {"verdict": "DONE"}}\n',
                    encoding="utf-8",
                )
            if phase == "re-extract-3-verify":
                updates["coverage_pct"] = 80
            payload["state_updates"] = updates
            return SquadAgentResult(
                exit_code=0,
                echelon_result=payload,
                raw_output="",
                duration_ms=1,
                timed_out=False,
            )

    result = ReExtractionController(
        provider=CaptureWritingProvider(),
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    ).run()

    assert result.completed


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

    assert result.blocked_reason == "re_domain_deep_spec_gate_failed"


@pytest.mark.unit
def test_legacy_specification_resume_migrates_a_changed_domain_partition(
    tmp_path: Path,
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    source_root = tmp_path / "sources" / "api"
    shutil.rmtree(source_root / "src")
    (source_root / "package.json").write_text("{}\n", encoding="utf-8")
    for root in ("pages", "shared"):
        directory = source_root / root
        directory.mkdir()
        (directory / "one.ts").write_text("export {};\n", encoding="utf-8")
        (directory / "two.ts").write_text("export {};\n", encoding="utf-8")

    old_spec = run_dir / "re" / "sources" / "api" / "specs" / "001-re-domain" / "spec.md"
    state_path = run_dir / "re" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.update(
        {
            "status": "in_progress",
            "phase": "re-extract-2-specify",
            "last_dispatch": {
                "phase_id": None,
                "agent": None,
                "post_dispatch_complete": True,
                "dispatched_at": None,
            },
            "max_verify_expand_iterations": 0,
            "re_specification_targets": [
                {
                    "kind": "source-domain",
                    "source_id": "api",
                    "domain_id": "001-re-domain",
                    "root": "src",
                }
            ],
        }
    )
    state.pop("re_domain_partition_version", None)
    state_path.write_text(json.dumps(state), encoding="utf-8")

    provider = _ShallowSpecifierProvider()
    result = ReExtractionController(
        provider=provider,
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    ).run()

    assert result.blocked_reason == "re_domain_deep_spec_gate_failed"
    assert old_spec.is_file() is False
    manifest = json.loads(
        (run_dir / "re" / "sources" / "api" / "domain-manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["partition_version"] == DOMAIN_PARTITION_VERSION
    assert [domain["root"] for domain in manifest["domains"]] == ["pages", "shared"]
    resumed_state = json.loads(state_path.read_text(encoding="utf-8"))
    assert resumed_state["re_domain_partition_version"] == DOMAIN_PARTITION_VERSION
    assert resumed_state["re_specification_targets"][0]["domain_id"] == "001-re-pages"


@pytest.mark.unit
def test_legacy_analysis_resume_removes_obsolete_specs_for_a_changed_partition(
    tmp_path: Path,
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    source_root = tmp_path / "sources" / "api"
    shutil.rmtree(source_root / "src")
    (source_root / "package.json").write_text("{}\n", encoding="utf-8")
    for root in ("pages", "shared"):
        directory = source_root / root
        directory.mkdir()
        (directory / "one.ts").write_text("export {};\n", encoding="utf-8")
        (directory / "two.ts").write_text("export {};\n", encoding="utf-8")

    old_spec = run_dir / "re" / "sources" / "api" / "specs" / "001-re-domain" / "spec.md"
    state_path = run_dir / "re" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.update(
        {
            "status": "in_progress",
            "phase": "re-extract-1-analyze",
            "re_specification_targets": [],
        }
    )
    state.pop("re_domain_partition_version", None)
    state_path.write_text(json.dumps(state), encoding="utf-8")

    controller = ReExtractionController(
        provider=_ShallowSpecifierProvider(),
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    )

    result = controller._advance("re-extract-1-analyze", state, controller._load_plan())

    assert result is None
    assert old_spec.is_file() is False
    assert state["re_domain_partition_version"] == DOMAIN_PARTITION_VERSION
    assert [target["domain_id"] for target in state["re_specification_targets"]] == [
        "001-re-pages",
        "002-re-shared",
    ]
