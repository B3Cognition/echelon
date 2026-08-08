from __future__ import annotations

import json
import os
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from harness.re_controller import ReExtractionController
from harness.re_domain_manifest import DOMAIN_PARTITION_VERSION
from harness.re_planner import ReExecutionPlan
from harness.re_quality_gate import ReQualityReport, ReSpecQualityFailure
from harness.re_semantic_preflight import SemanticPreflightFinding
from harness.squad_provider import SquadAgentResult
from tests.unit.test_re_publication import (
    _deep_spec,
    publish_re_run,
    write_valid_re_run,
)


@pytest.fixture(autouse=True)
def _stub_controller_analysis_script(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ReExtractionController,
        "_run_analysis_script",
        lambda _controller, _plan: None,
    )


class _ShallowSpecifierProvider:
    enforces_workspace_synthesis_boundary = True

    def __init__(self) -> None:
        self.phases: list[str] = []

    def exec_agent(self, project_root: str, prompt: str) -> SquadAgentResult:
        phase = prompt.split("RE phase: ", 1)[1].split("\n", 1)[0]
        self.phases.append(phase)
        if phase == "re-extract-2-specify" and "workspace-synthesis" in prompt:
            re_dir = Path(prompt.split("RE output directory: ", 1)[1].split("\n", 1)[0])
            architecture = json.loads(
                (re_dir / "workspace" / "architecture-map.json").read_text(
                    encoding="utf-8"
                )
            )
            domain_root = re_dir / "workspace" / "domains"
            domain_root.mkdir(parents=True, exist_ok=True)
            for domain_id in sorted(
                {domain["domain_id"] for domain in architecture["domains"]}
            ):
                (domain_root / f"{domain_id}.md").write_text(
                    f"# Workspace domain {domain_id}\n",
                    encoding="utf-8",
                )
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
    marker = "Requested semantic domain: `"
    if marker in prompt:
        requested = prompt.split(marker, 1)[1].split("`", 1)[0]
        domains = [
            domain
            for domain in domains
            if f"{domain['source_id']}/{domain['domain_id']}" == requested
        ]
    return {"schema_version": 1, "domains": domains}


def _unscoped_universal_claim_report(
    spec_path: Path = Path("spec.md"),
) -> ReQualityReport:
    return ReQualityReport(
        passed=False,
        failures=(
            ReSpecQualityFailure(
                source_id="api",
                domain_id="001-re-domain",
                spec_path=spec_path,
                missing_sections=(),
                source_evidence_count=5,
                expected_scenario_count=5,
                scenario_count=5,
                expected_functional_requirement_count=5,
                functional_requirement_count=5,
                expected_non_functional_requirement_count=3,
                non_functional_requirement_count=3,
                semantic_preflight_findings=(
                    SemanticPreflightFinding(
                        code="unscoped_universal_claim",
                        message=(
                            "FR-001 uses a universal claim without exhaustive "
                            "evidence scope"
                        ),
                        references=("`src/handler.ts:12`",),
                    ),
                ),
            ),
        ),
    )


@pytest.mark.unit
def test_unscoped_universal_claim_uses_semantic_repair_limit() -> None:
    controller = object.__new__(ReExtractionController)
    state = {
        "re_convergence_schema_version": 1,
        "re_source_states": {},
        "re_execution_profile": {
            "name": "balanced",
            "max_semantic_repair_rounds": 1,
        },
        "re_source_budgets": {"max_domain_repairs": 3},
    }

    assert controller._target_quality_repair_limit(
        state, _unscoped_universal_claim_report()
    ) == 1


@pytest.mark.unit
def test_structural_target_quality_failure_uses_domain_repair_limit() -> None:
    controller = object.__new__(ReExtractionController)
    state = {
        "re_convergence_schema_version": 1,
        "re_source_states": {},
        "re_execution_profile": {
            "name": "balanced",
            "max_semantic_repair_rounds": 1,
        },
        "re_source_budgets": {"max_domain_repairs": 3},
    }
    report = ReQualityReport(
        passed=False,
        failures=(
            ReSpecQualityFailure(
                source_id="api",
                domain_id="001-re-domain",
                spec_path=Path("spec.md"),
                missing_sections=("Edge Cases",),
                source_evidence_count=5,
            ),
        ),
    )

    assert controller._target_quality_repair_limit(state, report) == 3


@pytest.mark.unit
def test_unscoped_universal_claim_exhaustion_advances_to_next_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api", "worker"))
    _initialize_re_state(run_dir, max_repairs=3)
    state_path = run_dir / "re" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.update(
        {
            "re_convergence_schema_version": 1,
            "re_execution_profile": {
                "name": "balanced",
                "semantic_audit_mode": "all",
                "max_semantic_repair_rounds": 1,
            },
            "re_source_budgets": {
                "max_source_cycles": 2,
                "max_domain_repairs": 3,
                "max_source_reanalysis": 2,
            },
            "re_source_states": {},
        }
    )
    state_path.write_text(json.dumps(state), encoding="utf-8")

    def target_quality(
        _run_re_dir: Path,
        _plan: ReExecutionPlan,
        source_id: str,
        _domain_id: str,
    ) -> ReQualityReport:
        if source_id == "api":
            return _unscoped_universal_claim_report(
                run_dir / "re/sources/api/specs/001-re-domain/spec.md"
            )
        return ReQualityReport(passed=True, failures=())

    monkeypatch.setattr(
        "harness.re_controller.validate_staged_re_domain_quality", target_quality
    )

    class DomainRecordingProvider(_ShallowSpecifierProvider):
        def __init__(self) -> None:
            super().__init__()
            self.specifier_sources: list[str] = []

        def exec_agent(self, project_root: str, prompt: str) -> SquadAgentResult:
            if (
                "RE phase: re-extract-2-specify" in prompt
                and "Source ID: `" in prompt
            ):
                self.specifier_sources.append(
                    prompt.split("Source ID: `", 1)[1].split("`", 1)[0]
                )
            return super().exec_agent(project_root, prompt)

    provider = DomainRecordingProvider()
    result = ReExtractionController(
        provider=provider,
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    ).run()

    assert result.completed
    assert provider.specifier_sources[:3] == ["api", "api", "worker"]
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["re_source_states"]["api"]["status"] == "partial_quality_debt"


@pytest.mark.unit
def test_semantic_validation_continue_reuses_completed_domain(tmp_path: Path) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api", "web"))
    _initialize_re_state(run_dir, max_repairs=2)
    state_path = run_dir / "re" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.update(
        {
            "status": "in_progress",
            "phase": "re-extract-5-validate",
            "re_workspace_synthesis_complete": True,
        }
    )
    state_path.write_text(json.dumps(state), encoding="utf-8")

    class InterruptingValidator(_ShallowSpecifierProvider):
        def __init__(self, *, fail_web: bool) -> None:
            super().__init__()
            self.fail_web = fail_web
            self.validated: list[str] = []

        def exec_agent(self, project_root: str, prompt: str) -> SquadAgentResult:
            phase = prompt.split("RE phase: ", 1)[1].split("\n", 1)[0]
            if phase != "re-extract-5-validate":
                return super().exec_agent(project_root, prompt)
            requested = prompt.split("Requested semantic domain: `", 1)[1].split("`", 1)[0]
            self.phases.append(phase)
            self.validated.append(requested)
            if requested == "web/001-re-domain" and self.fail_web:
                return SquadAgentResult(
                    exit_code=1,
                    echelon_result=None,
                    raw_output="context limit",
                    duration_ms=1,
                    timed_out=False,
                )
            source_id, domain_id = requested.split("/", 1)
            return SquadAgentResult(
                exit_code=0,
                echelon_result={
                    "verdict": "DONE",
                    "state_updates": {},
                    "journal_entries": [],
                    "semantic_quality_review": {
                        "schema_version": 1,
                        "domains": [
                            {
                                "source_id": source_id,
                                "domain_id": domain_id,
                                "verdict": "PASS",
                                "findings": [],
                                "source_evidence": [],
                            }
                        ],
                    },
                },
                raw_output="",
                duration_ms=1,
                timed_out=False,
            )

    first = InterruptingValidator(fail_web=True)
    blocked = ReExtractionController(
        provider=first,
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    ).run()

    assert blocked.blocked_reason == "re_agent_dispatch_failed"
    assert first.validated == ["api/001-re-domain", "web/001-re-domain"]
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert list(persisted["re_semantic_domain_audits"]) == ["api/001-re-domain"]

    continued = InterruptingValidator(fail_web=False)
    result = ReExtractionController(
        provider=continued,
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    ).run()

    assert result.completed
    assert continued.validated == ["web/001-re-domain"]


@pytest.mark.unit
def test_semantic_audit_spec_fingerprint_invalidates_only_changed_domain(
    tmp_path: Path,
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api", "web"))
    controller = ReExtractionController(
        provider=_ShallowSpecifierProvider(),
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    )
    plan = ReExecutionPlan.from_json_dict(
        json.loads((run_dir / "re" / "re-execution-plan.json").read_text())
    )
    state: dict[str, object] = {}
    for target in controller._semantic_validation_targets(plan):
        controller._store_semantic_domain_audit(
            state,
            plan,
            target,
            {
                "source_id": target["source_id"],
                "domain_id": target["domain_id"],
                "verdict": "PASS",
                "findings": [],
                "source_evidence": [],
            },
        )
    api_spec = run_dir / "re/sources/api/specs/001-re-domain/spec.md"
    api_spec.write_text(api_spec.read_text() + "\nChanged requirement.\n")

    assert controller._next_semantic_validation_target(state, plan) == {
        "source_id": "api",
        "domain_id": "001-re-domain",
    }


@pytest.mark.unit
def test_semantic_audit_skips_domains_without_staged_specs(tmp_path: Path) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api", "web"))
    missing_spec = run_dir / "re/sources/web/specs/001-re-domain/spec.md"
    missing_spec.unlink()
    controller = ReExtractionController(
        provider=_ShallowSpecifierProvider(),
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    )
    plan = ReExecutionPlan.from_json_dict(
        json.loads((run_dir / "re" / "re-execution-plan.json").read_text())
    )

    assert controller._semantic_validation_targets(plan) == [
        {"source_id": "api", "domain_id": "001-re-domain"}
    ]
    assert controller._semantic_expected_domains(plan) == {
        ("api", "001-re-domain")
    }


@pytest.mark.unit
def test_semantic_audit_source_fingerprint_invalidates_affected_source(
    tmp_path: Path,
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api", "web"))
    controller = ReExtractionController(
        provider=_ShallowSpecifierProvider(),
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    )
    plan = ReExecutionPlan.from_json_dict(
        json.loads((run_dir / "re" / "re-execution-plan.json").read_text())
    )
    state: dict[str, object] = {}
    for target in controller._semantic_validation_targets(plan):
        controller._store_semantic_domain_audit(
            state,
            plan,
            target,
            {
                "source_id": target["source_id"],
                "domain_id": target["domain_id"],
                "verdict": "PASS",
                "findings": [],
                "source_evidence": [],
            },
        )
    api, web = plan.sources
    changed_api = replace(
        api, fingerprint=replace(api.fingerprint, value="changed-source")
    )
    changed_plan = replace(plan, sources=(changed_api, web))

    assert controller._next_semantic_validation_target(state, changed_plan) == {
        "source_id": "api",
        "domain_id": "001-re-domain",
    }


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
def test_controller_does_not_start_dispatch_at_token_ceiling(tmp_path: Path) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    _initialize_re_state(run_dir, max_repairs=3)
    state_path = run_dir / "re/state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["re_execution_profile"] = {
        "name": "balanced",
        "hard_token_limit": 5_000_000,
        "hard_active_minutes": 180,
    }
    state["re_token_usage"] = 5_000_000
    state_path.write_text(json.dumps(state), encoding="utf-8")
    provider = _ShallowSpecifierProvider()

    result = ReExtractionController(
        provider=provider,
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    ).run()

    assert result.blocked_reason == "re_token_budget_exhausted"
    assert provider.phases == []


@pytest.mark.unit
def test_fast_profile_disables_semantic_dispatch_and_repairs() -> None:
    state = {
        "re_execution_profile": {
            "name": "fast",
            "semantic_audit_mode": "none",
            "max_semantic_repair_rounds": 0,
        }
    }
    controller = object.__new__(ReExtractionController)

    assert controller._semantic_audit_enabled(state) is False
    assert controller._semantic_repair_limit(state) == 0


@pytest.mark.unit
def test_controller_records_dispatch_tokens_and_content_free_spans(tmp_path: Path) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    _initialize_re_state(run_dir, max_repairs=3)
    state_path = run_dir / "re/state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["re_execution_profile"] = {
        "name": "balanced",
        "hard_token_limit": 5_000_000,
        "hard_active_minutes": 180,
    }
    state_path.write_text(json.dumps(state), encoding="utf-8")

    class MeteredProvider(_ShallowSpecifierProvider):
        def exec_agent(self, project_root: str, prompt: str) -> SquadAgentResult:
            result = super().exec_agent(project_root, prompt)
            result.token_usage = 12
            result.token_usage_details = {"input_tokens": 10, "output_tokens": 2}
            result.provider_name = "codex"
            result.model_name = "gpt-test"
            return result

    result = ReExtractionController(
        provider=MeteredProvider(),
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    ).run()

    assert result.completed
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert persisted["re_token_usage"] > 0
    ledger = (run_dir / "telemetry/spans.jsonl").read_text(encoding="utf-8")
    assert '"gen_ai.provider.name":"codex"' in ledger
    assert '"gen_ai.usage.input_tokens":10' in ledger
    assert '"gen_ai.usage.output_tokens":2' in ledger
    assert "RE phase:" not in ledger


def _strand_completed_workspace_synthesis(
    run_dir: Path,
    *,
    scoped: bool = True,
) -> None:
    state_path = run_dir / "re" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.update(
        {
            "status": "blocked",
            "phase": "re-extract-2-specify",
            "blocked_reason": "re_agent_result_invalid",
            "re_agent_result_detail": (
                "state_updates key 're_workspace_synthesis_complete' is not allowed"
            ),
            "last_dispatch": {
                "phase_id": "re-extract-2-specify",
                "agent": "specifier",
                "post_dispatch_complete": False,
                "dispatched_at": "2026-07-18T06:36:15Z",
            },
            "mode": "workspace",
            "coverage_threshold": 99,
            "resolution_threshold": 99,
            "max_verify_expand_iterations": 5,
            "max_validate_iterations": 5,
            "verify_expand_iterations": 0,
            "validate_iterations": 0,
            "re_convergence_schema_version": 1,
            "re_source_convergence_quality_contract_version": 1,
            "re_source_coverage_repair_protocol_version": 1,
            "re_semantic_quality_review_protocol_version": 2,
            "re_target_quality_protocol_version": 1,
            "re_source_budgets": {
                "max_source_cycles": 5,
                "max_domain_repairs": 5,
                "max_source_reanalysis": 5,
            },
            "re_source_order": ["api"],
            "re_source_states": {
                "api": {
                    "status": "passed",
                    "source_cycles": 1,
                    "domain_repairs": {},
                    "source_reanalysis": 0,
                    "coverage_pct": 100,
                }
            },
            "re_specification_targets": [{"kind": "workspace-synthesis"}],
            "re_workspace_synthesis_complete": False,
            "re_domain_partition_version": DOMAIN_PARTITION_VERSION,
        }
    )
    if scoped:
        state["re_workspace_synthesis_scope_protocol_version"] = 1
    state_path.write_text(json.dumps(state), encoding="utf-8")


@pytest.mark.unit
def test_specification_targets_discard_agent_state_updates() -> None:
    payload = {
        "verdict": "DONE",
        "state_updates": {
            "domains": ["api"],
            "re_workspace_synthesis_complete": True,
        },
    }

    sanitized = ReExtractionController._agent_result_without_controller_keys(
        payload,
        {"kind": "workspace-synthesis"},
    )

    assert sanitized["state_updates"] == {}


@pytest.mark.unit
def test_workspace_synthesis_prompt_declares_file_only_result_contract(
    tmp_path: Path,
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    controller = ReExtractionController(
        provider=_ShallowSpecifierProvider(),
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    )

    prompt = controller._specification_target_prompt({"kind": "workspace-synthesis"})

    assert "state_updates: {}" in prompt
    assert "controller-owned" in prompt


@pytest.mark.unit
def test_workspace_synthesis_prompt_names_exact_decisions_and_forbids_live_roots(
    tmp_path: Path,
) -> None:
    run_dir = write_valid_re_run(
        tmp_path,
        ("api", "web", "docs"),
        actions={"api": "refresh", "web": "reuse", "docs": "skip-empty"},
        removed_sources=("legacy",),
    )
    controller = ReExtractionController(
        provider=_ShallowSpecifierProvider(),
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    )

    prompt = controller._specification_target_prompt({"kind": "workspace-synthesis"})

    assert "Refreshed source IDs: `api`" in prompt
    assert "Reused source IDs: `web`" in prompt
    assert "Empty source IDs: `docs`" in prompt
    assert "Missing/excluded source IDs:" in prompt
    assert "Removed source IDs: `legacy`" in prompt
    assert "configured live source root" in prompt
    assert "inspect, search, count, summarize, or cite" in prompt
    assert "reused source's canonical input" in prompt
    assert "return BLOCKED" in prompt


@pytest.mark.unit
def test_workspace_synthesis_metadata_uses_only_authenticated_re_inputs(
    tmp_path: Path,
) -> None:
    baseline = write_valid_re_run(tmp_path, ("web",), run_id="run-1")
    publish_re_run(tmp_path, baseline)
    run_dir = write_valid_re_run(
        tmp_path,
        ("api", "web"),
        run_id="run-2",
        actions={"api": "refresh", "web": "reuse"},
    )
    controller = ReExtractionController(
        provider=_ShallowSpecifierProvider(),
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    )
    plan = controller._load_plan()

    metadata = controller._prompt_metadata_for_target(
        plan, {"kind": "workspace-synthesis"}
    )

    assert metadata["tool_read_roots"] == [
        str((run_dir / "re").resolve()),
        str((tmp_path / "re" / "sources" / "web").resolve()),
        str((tmp_path / "re" / "workspace").resolve()),
    ]
    live_roots = {str(Path(source.absolute_path).resolve()) for source in plan.sources}
    assert live_roots.isdisjoint(metadata["tool_read_roots"])
    assert set(metadata["tool_forbidden_roots"]) == live_roots
    assert metadata["tool_write_paths"] == [
        str((run_dir / "re" / "sources" / "api" / "architecture.md").resolve()),
        str((run_dir / "re" / "sources" / "api" / "components.md").resolve()),
        str((run_dir / "re" / "sources" / "api" / "contracts.md").resolve()),
        str((run_dir / "re" / "sources" / "api" / "overview.md").resolve()),
        str((run_dir / "re" / "workspace" / "contracts.md").resolve()),
        str(
            (
                run_dir
                / "re"
                / "workspace"
                / "domains"
                / "001-re-domain.md"
            ).resolve()
        ),
        str(
            (
                run_dir
                / "re"
                / "workspace"
                / "domains"
                / "001-re-src.md"
            ).resolve()
        ),
        str((run_dir / "re" / "workspace" / "overview.md").resolve()),
        str((run_dir / "re" / "workspace" / "relationships.md").resolve()),
    ]


@pytest.mark.unit
def test_workspace_synthesis_metadata_rejects_untrusted_workspace_input_path(
    tmp_path: Path,
) -> None:
    baseline = write_valid_re_run(tmp_path, ("web",), run_id="run-1")
    publish_re_run(tmp_path, baseline)
    run_dir = write_valid_re_run(
        tmp_path,
        ("api", "web"),
        run_id="run-2",
        actions={"api": "refresh", "web": "reuse"},
    )
    inputs_path = run_dir / "re" / "re-workspace-inputs.json"
    inputs = json.loads(inputs_path.read_text(encoding="utf-8"))
    web = next(item for item in inputs["sources"] if item["id"] == "web")
    web["input_path"] = str(tmp_path / "sources" / "web")
    inputs_path.write_text(json.dumps(inputs), encoding="utf-8")
    controller = ReExtractionController(
        provider=_ShallowSpecifierProvider(),
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    )

    with pytest.raises(ValueError, match="workspace inputs do not match the execution plan"):
        controller._prompt_metadata_for_target(
            controller._load_plan(), {"kind": "workspace-synthesis"}
        )


@pytest.mark.unit
@pytest.mark.parametrize("action", ["missing", "exclude"])
def test_workspace_synthesis_metadata_does_not_require_unavailable_inputs(
    tmp_path: Path,
    action: str,
) -> None:
    run_dir = write_valid_re_run(
        tmp_path,
        ("api", "unavailable"),
        actions={"api": "refresh", "unavailable": action},
    )
    controller = ReExtractionController(
        provider=_ShallowSpecifierProvider(),
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    )

    metadata = controller._prompt_metadata_for_target(
        controller._load_plan(), {"kind": "workspace-synthesis"}
    )

    assert metadata["tool_read_roots"] == [str((run_dir / "re").resolve())]
    assert str((tmp_path / "sources" / "unavailable").resolve()) not in metadata[
        "tool_read_roots"
    ]


@pytest.mark.unit
@pytest.mark.parametrize("action", ["missing", "exclude"])
def test_workspace_synthesis_metadata_includes_usable_retained_inputs(
    tmp_path: Path,
    action: str,
) -> None:
    baseline = write_valid_re_run(tmp_path, ("retained",), run_id="run-1")
    publish_re_run(tmp_path, baseline)
    run_dir = write_valid_re_run(
        tmp_path,
        ("api", "retained"),
        run_id="run-2",
        actions={"api": "refresh", "retained": action},
    )
    controller = ReExtractionController(
        provider=_ShallowSpecifierProvider(),
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    )

    metadata = controller._prompt_metadata_for_target(
        controller._load_plan(), {"kind": "workspace-synthesis"}
    )

    assert str((tmp_path / "re" / "sources" / "retained").resolve()) in metadata[
        "tool_read_roots"
    ]


@pytest.mark.unit
def test_workspace_synthesis_metadata_rejects_symlinked_write_parent(
    tmp_path: Path,
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    staged_source = run_dir / "re" / "sources" / "api"
    shutil.rmtree(staged_source)
    staged_source.symlink_to(tmp_path / "sources" / "api", target_is_directory=True)
    controller = ReExtractionController(
        provider=_ShallowSpecifierProvider(),
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    )

    with pytest.raises(ValueError, match="symlinked workspace synthesis path"):
        controller._prompt_metadata_for_target(
            controller._load_plan(), {"kind": "workspace-synthesis"}
        )


@pytest.mark.unit
def test_workspace_synthesis_metadata_rejects_run_internal_output_symlink(
    tmp_path: Path,
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    output = run_dir / "re" / "workspace" / "overview.md"
    output.unlink()
    output.symlink_to(run_dir / "re" / "state.json")
    controller = ReExtractionController(
        provider=_ShallowSpecifierProvider(),
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    )

    with pytest.raises(ValueError, match="symlinked workspace synthesis path"):
        controller._prompt_metadata_for_target(
            controller._load_plan(), {"kind": "workspace-synthesis"}
        )


@pytest.mark.unit
def test_workspace_synthesis_metadata_rejects_hardlinked_output(
    tmp_path: Path,
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    output = run_dir / "re" / "workspace" / "overview.md"
    output.unlink()
    os.link(tmp_path / "sources" / "api" / "src" / "file-1.ts", output)
    controller = ReExtractionController(
        provider=_ShallowSpecifierProvider(),
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    )

    with pytest.raises(ValueError, match="hardlinked workspace synthesis path"):
        controller._prompt_metadata_for_target(
            controller._load_plan(), {"kind": "workspace-synthesis"}
        )


@pytest.mark.unit
def test_workspace_synthesis_metadata_rejects_unsafe_domain_id(
    tmp_path: Path,
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    architecture_path = run_dir / "re" / "workspace" / "architecture-map.json"
    architecture = json.loads(architecture_path.read_text(encoding="utf-8"))
    architecture["domains"][0]["domain_id"] = "../../outside"
    architecture_path.write_text(json.dumps(architecture), encoding="utf-8")
    controller = ReExtractionController(
        provider=_ShallowSpecifierProvider(),
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    )

    with pytest.raises(ValueError, match="unsafe workspace synthesis component"):
        controller._prompt_metadata_for_target(
            controller._load_plan(), {"kind": "workspace-synthesis"}
        )


@pytest.mark.unit
def test_workspace_synthesis_blocks_before_dispatch_when_canonical_input_is_missing(
    tmp_path: Path,
) -> None:
    baseline = write_valid_re_run(tmp_path, ("web",), run_id="run-1")
    publish_re_run(tmp_path, baseline)
    run_dir = write_valid_re_run(
        tmp_path,
        ("api", "web"),
        run_id="run-2",
        actions={"api": "refresh", "web": "reuse"},
    )
    (tmp_path / "re" / "sources" / "web" / "manifest.json").unlink()
    _initialize_re_state(run_dir, max_repairs=1)

    provider = _ShallowSpecifierProvider()
    result = ReExtractionController(
        provider=provider,
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    ).run()

    assert result.blocked_reason == "re_workspace_synthesis_inputs_invalid"
    assert result.blocked_detail is not None
    assert "canonical input" in result.blocked_detail
    assert provider.phases.count("re-extract-2-specify") == 1


@pytest.mark.unit
def test_workspace_synthesis_retry_prompt_includes_controller_feedback(
    tmp_path: Path,
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    controller = ReExtractionController(
        provider=_ShallowSpecifierProvider(),
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    )
    state = {
        "re_agent_result_detail": (
            "workspace synthesis has missing or empty artifacts: "
            "workspace/domains/001-re-domain.md"
        )
    }
    plan = ReExecutionPlan.from_json_dict(
        json.loads(
            (run_dir / "re" / "re-execution-plan.json").read_text(
                encoding="utf-8"
            )
        )
    )

    prompt = controller._prompt_for(
        "re-extract-2-specify",
        state,
        plan,
        {"kind": "workspace-synthesis"},
    )

    assert "Controller Validation Feedback" in prompt
    assert "Repair only these missing workspace-synthesis output files" in prompt
    assert "workspace/domains/001-re-domain.md" in prompt
    assert str((run_dir / "re" / "sources" / "api" / "overview.md").resolve()) not in prompt


@pytest.mark.unit
def test_workspace_synthesis_retry_metadata_allows_only_missing_outputs(
    tmp_path: Path,
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    controller = ReExtractionController(
        provider=_ShallowSpecifierProvider(),
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    )
    plan = controller._load_plan()
    state = {
        "re_agent_result_detail": (
            "workspace synthesis has missing or empty artifacts: "
            "workspace/domains/001-re-domain.md"
        )
    }

    metadata = controller._prompt_metadata_for_target(
        plan, {"kind": "workspace-synthesis"}, state
    )

    assert metadata["tool_write_paths"] == [
        str((run_dir / "re/workspace/domains/001-re-domain.md").resolve())
    ]


@pytest.mark.unit
def test_workspace_synthesis_prompt_lists_every_exact_required_output(
    tmp_path: Path,
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    controller = ReExtractionController(
        provider=_ShallowSpecifierProvider(),
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    )
    plan = controller._load_plan()

    prompt = controller._prompt_for(
        "re-extract-2-specify",
        {},
        plan,
        {"kind": "workspace-synthesis"},
    )

    assert "Required workspace-synthesis output files" in prompt
    for path in (
        run_dir / "re/sources/api/overview.md",
        run_dir / "re/sources/api/architecture.md",
        run_dir / "re/sources/api/contracts.md",
        run_dir / "re/sources/api/components.md",
        run_dir / "re/workspace/overview.md",
        run_dir / "re/workspace/relationships.md",
        run_dir / "re/workspace/contracts.md",
        run_dir / "re/workspace/domains/001-re-domain.md",
    ):
        assert f"- `{path.resolve()}`" in prompt


@pytest.mark.unit
def test_continue_recovers_valid_completed_workspace_synthesis_without_redispatch(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    _strand_completed_workspace_synthesis(run_dir)
    provider = _ShallowSpecifierProvider()

    result = ReExtractionController(
        provider=provider,
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    ).run()

    assert result.completed
    assert "re-extract-2-specify" not in provider.phases
    assert provider.phases == [
        "re-extract-5-validate",
        "re-extract-6-checklist",
        "re-extract-7-constitute",
    ]
    state = json.loads((run_dir / "re" / "state.json").read_text(encoding="utf-8"))
    assert state["re_workspace_synthesis_complete"] is True
    assert state["last_dispatch"]["post_dispatch_complete"] is True
    assert "re_agent_result_detail" not in state
    assert "recovered completed workspace synthesis" in capsys.readouterr().out


@pytest.mark.unit
def test_continue_redispatches_legacy_unscoped_workspace_synthesis(
    tmp_path: Path,
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    _strand_completed_workspace_synthesis(run_dir, scoped=False)
    provider = _ShallowSpecifierProvider()

    result = ReExtractionController(
        provider=provider,
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    ).run()

    assert result.completed
    assert provider.phases.count("re-extract-2-specify") == 1
    state = json.loads((run_dir / "re" / "state.json").read_text(encoding="utf-8"))
    assert state["re_workspace_synthesis_scope_protocol_version"] == 1


@pytest.mark.unit
def test_workspace_synthesis_blocks_after_automatic_repair_is_exhausted(
    tmp_path: Path,
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    _strand_completed_workspace_synthesis(run_dir)
    (run_dir / "re" / "workspace" / "domains" / "001-re-domain.md").unlink()

    class IncompleteWorkspaceProvider(_ShallowSpecifierProvider):
        def exec_agent(self, project_root: str, prompt: str) -> SquadAgentResult:
            result = super().exec_agent(project_root, prompt)
            if self.phases[-1] == "re-extract-2-specify":
                (
                    run_dir
                    / "re"
                    / "workspace"
                    / "domains"
                    / "001-re-domain.md"
                ).unlink(missing_ok=True)
            return result

    provider = IncompleteWorkspaceProvider()

    result = ReExtractionController(
        provider=provider,
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    ).run()

    assert not result.completed
    assert result.blocked_reason == "re_workspace_synthesis_incomplete"
    assert provider.phases.count("re-extract-2-specify") == 2
    assert result.blocked_detail is not None
    assert "workspace/domains/001-re-domain.md" in result.blocked_detail
    state = json.loads((run_dir / "re" / "state.json").read_text(encoding="utf-8"))
    assert state["re_workspace_synthesis_repair_attempts"] == 1


@pytest.mark.unit
def test_workspace_synthesis_automatically_repairs_missing_artifacts(
    tmp_path: Path,
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    _strand_completed_workspace_synthesis(run_dir)
    missing = run_dir / "re" / "workspace" / "domains" / "001-re-domain.md"
    missing.unlink()

    class RepairOnceWorkspaceProvider(_ShallowSpecifierProvider):
        def exec_agent(self, project_root: str, prompt: str) -> SquadAgentResult:
            result = super().exec_agent(project_root, prompt)
            if self.phases.count("re-extract-2-specify") == 1:
                missing.unlink(missing_ok=True)
            return result

    provider = RepairOnceWorkspaceProvider()
    result = ReExtractionController(
        provider=provider,
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    ).run()

    assert result.completed
    assert provider.phases.count("re-extract-2-specify") == 2
    state = json.loads((run_dir / "re" / "state.json").read_text(encoding="utf-8"))
    assert state["re_workspace_synthesis_repair_attempts"] == 1
    assert state["re_workspace_synthesis_complete"] is True


@pytest.mark.unit
@pytest.mark.parametrize("action", ["reuse", "skip-empty"])
def test_workspace_synthesis_rejects_staged_non_refresh_source_artifacts(
    tmp_path: Path,
    action: str,
) -> None:
    if action == "reuse":
        baseline = write_valid_re_run(tmp_path, ("sibling",), run_id="run-1")
        publish_re_run(tmp_path, baseline)
    run_dir = write_valid_re_run(
        tmp_path,
        ("api", "sibling"),
        run_id="run-2",
        actions={"api": "refresh", "sibling": action},
    )
    forbidden = run_dir / "re" / "sources" / "sibling"
    shutil.rmtree(forbidden, ignore_errors=True)
    _initialize_re_state(run_dir, max_repairs=1)

    class OutOfScopeWorkspaceProvider(_ShallowSpecifierProvider):
        def exec_agent(self, project_root: str, prompt: str) -> SquadAgentResult:
            result = super().exec_agent(project_root, prompt)
            if self.phases[-1] == "re-extract-2-specify" and "workspace-synthesis" in prompt:
                forbidden.mkdir(parents=True)
                (forbidden / "overview.md").write_text(
                    "# Out-of-scope synthesis\n", encoding="utf-8"
                )
            return result

    provider = OutOfScopeWorkspaceProvider()
    result = ReExtractionController(
        provider=provider,
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    ).run()

    assert result.blocked_reason == "re_workspace_synthesis_incomplete"
    assert result.blocked_detail is not None
    assert "non-refresh source artifacts" in result.blocked_detail
    assert "sources/sibling" in result.blocked_detail
    state = json.loads((run_dir / "re" / "state.json").read_text(encoding="utf-8"))
    assert state["re_workspace_synthesis_complete"] is False


@pytest.mark.unit
def test_workspace_synthesis_removes_preexisting_non_refresh_source_artifacts(
    tmp_path: Path,
) -> None:
    baseline = write_valid_re_run(tmp_path, ("sibling",), run_id="run-1")
    publish_re_run(tmp_path, baseline)
    run_dir = write_valid_re_run(
        tmp_path,
        ("api", "sibling"),
        run_id="run-2",
        actions={"api": "refresh", "sibling": "reuse"},
    )
    forbidden = run_dir / "re" / "sources" / "sibling"
    forbidden.mkdir(parents=True)
    (forbidden / "overview.md").write_text(
        "# Stranded out-of-scope synthesis\n", encoding="utf-8"
    )
    _initialize_re_state(run_dir, max_repairs=1)

    class CleanWorkspaceProvider(_ShallowSpecifierProvider):
        def exec_agent(self, project_root: str, prompt: str) -> SquadAgentResult:
            if "workspace-synthesis" in prompt:
                assert not forbidden.exists()
            return super().exec_agent(project_root, prompt)

    result = ReExtractionController(
        provider=CleanWorkspaceProvider(),
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    ).run()

    assert result.completed
    assert not forbidden.exists()


@pytest.mark.unit
def test_workspace_synthesis_blocks_provider_without_enforced_file_scopes(
    tmp_path: Path,
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    _initialize_re_state(run_dir, max_repairs=1)

    class UnscopedProvider(_ShallowSpecifierProvider):
        supports_prompt_metadata = True
        enforces_workspace_synthesis_boundary = False

        def __init__(self) -> None:
            super().__init__()
            self.workspace_dispatched = False

        def exec_agent(
            self, project_root: str, prompt: str, **kwargs: object
        ) -> SquadAgentResult:
            del kwargs
            if "workspace-synthesis" in prompt:
                self.workspace_dispatched = True
            return super().exec_agent(project_root, prompt)

    provider = UnscopedProvider()
    result = ReExtractionController(
        provider=provider,
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    ).run()

    assert result.blocked_reason == "re_workspace_synthesis_scope_unsupported"
    assert provider.workspace_dispatched is False


@pytest.mark.unit
def test_target_only_empty_source_completes_from_canonical_inputs_without_discovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = write_valid_re_run(tmp_path, ("sibling",), run_id="run-1")
    publish_re_run(tmp_path, baseline)
    run_dir = write_valid_re_run(
        tmp_path,
        ("sibling", "empty"),
        run_id="run-2",
        actions={"sibling": "reuse", "empty": "skip-empty"},
    )
    plan_path = run_dir / "re" / "re-execution-plan.json"
    plan = ReExecutionPlan.from_json_dict(
        json.loads(plan_path.read_text(encoding="utf-8"))
    )
    plan = replace(
        plan,
        policy="target-only",
        requested_policy="target-only",
        target_source="empty",
        sources=tuple(
            replace(source, selected=source.id == "empty") for source in plan.sources
        ),
        analysis_required=False,
    )
    plan_path.write_text(json.dumps(plan.to_json_dict()), encoding="utf-8")
    shutil.rmtree(run_dir / "re" / "sources" / "empty")
    shutil.rmtree(tmp_path / "sources" / "sibling")
    (run_dir / "re" / "quality" / "semantic-quality-review.json").unlink()
    _initialize_re_state(run_dir, max_repairs=1)

    monkeypatch.setattr(
        "harness.re_controller.discover_source_domains",
        lambda source: pytest.fail("target-only empty flow discovered a source root"),
    )

    class MetadataCapturingProvider(_ShallowSpecifierProvider):
        supports_prompt_metadata = True

        def __init__(self) -> None:
            super().__init__()
            self.metadata: list[object] = []

        def exec_agent(
            self, project_root: str, prompt: str, **kwargs: object
        ) -> SquadAgentResult:
            self.metadata.append(kwargs.get("prompt_metadata"))
            return super().exec_agent(project_root, prompt)

    provider = MetadataCapturingProvider()
    result = ReExtractionController(
        provider=provider,
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    ).run()

    assert result.completed
    assert "re-extract-1-analyze" not in provider.phases
    workspace_metadata = next(
        item
        for item in provider.metadata
        if isinstance(item, dict)
        and str(tmp_path / "re" / "sources" / "sibling")
        in item.get("tool_read_roots", [])
    )
    assert str(tmp_path / "sources" / "sibling") not in workspace_metadata[
        "tool_read_roots"
    ]
    assert workspace_metadata["tool_write_paths"] == [
        str((run_dir / "re" / "workspace" / "contracts.md").resolve()),
        str((run_dir / "re" / "workspace" / "overview.md").resolve()),
        str((run_dir / "re" / "workspace" / "relationships.md").resolve()),
    ]
    assert not (run_dir / "re" / "sources" / "empty").exists()
    semantic_report = json.loads(
        (run_dir / "re" / "quality" / "semantic-quality-review.json").read_text(
            encoding="utf-8"
        )
    )
    assert semantic_report["passed"] is True
    assert semantic_report["failures"] == []


@pytest.mark.unit
def test_workspace_source_convergence_migration_upgrades_legacy_quality_contract() -> None:
    state = {
        "mode": "workspace",
        "coverage_threshold": 80,
        "resolution_threshold": 80,
        "max_verify_expand_iterations": 3,
        "max_validate_iterations": 3,
        "re_agent_result_detail": "stale previous dispatch failure",
    }

    assert ReExtractionController._migrate_workspace_source_convergence(state)

    assert state["coverage_threshold"] == 99
    assert state["resolution_threshold"] == 99
    assert state["max_verify_expand_iterations"] == 5
    assert state["max_validate_iterations"] == 5
    assert state["re_source_convergence_quality_contract_version"] == 1
    assert "re_agent_result_detail" not in state


@pytest.mark.unit
def test_source_convergence_quality_upgrade_applies_to_an_already_migrated_run() -> None:
    state = {
        "mode": "workspace",
        "re_convergence_schema_version": 1,
        "re_source_states": {},
        "coverage_threshold": 80,
        "resolution_threshold": 80,
        "max_verify_expand_iterations": 3,
        "max_validate_iterations": 3,
    }

    assert ReExtractionController._upgrade_source_convergence_quality_contract(state)

    assert state["coverage_threshold"] == 99
    assert state["resolution_threshold"] == 99
    assert state["max_verify_expand_iterations"] == 5
    assert state["max_validate_iterations"] == 5
    assert state["re_source_convergence_quality_contract_version"] == 1


@pytest.mark.unit
def test_semantic_quality_review_protocol_upgrade_clears_stale_invalid_attempts() -> None:
    state = {
        "phase": "re-extract-5-validate",
        "status": "blocked",
        "blocked_reason": "re_semantic_quality_review_invalid",
        "re_semantic_review_invalid_attempts": 5,
        "re_semantic_review_invalid_error": (
            "semantic quality review REPAIR findings need valid source evidence"
        ),
        "re_agent_result_detail": (
            "semantic quality review REPAIR findings need valid source evidence"
        ),
    }

    assert ReExtractionController._upgrade_semantic_quality_review_protocol(state)

    assert state["re_semantic_quality_review_protocol_version"] == 2
    assert "re_semantic_review_invalid_attempts" not in state
    assert "re_semantic_review_invalid_error" not in state
    assert "re_agent_result_detail" not in state
    assert state["blocked_reason"] == "re_semantic_quality_review_invalid"


@pytest.mark.unit
def test_source_local_convergence_prints_source_start_and_ready_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api", "web"))
    _initialize_re_state(run_dir, max_repairs=1)
    state_path = run_dir / "re" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.update(
        {
            "re_convergence_schema_version": 1,
            "re_source_budgets": {
                "max_source_cycles": 5,
                "max_domain_repairs": 5,
                "max_source_reanalysis": 5,
            },
            "re_source_states": {},
        }
    )
    state_path.write_text(json.dumps(state), encoding="utf-8")

    result = ReExtractionController(
        provider=_ShallowSpecifierProvider(),
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    ).run()

    assert result.completed
    output = capsys.readouterr().out
    assert "[re] source: api" in output
    assert "[re] source measured: api - 100.0% coverage" in output
    assert "[re] source ready: api" in output
    assert "[re] source: web" in output
    assert "[re] source measured: web - 100.0% coverage" in output
    assert "[re] source ready: web" in output
    assert "coverage (" in output


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
def test_source_domain_target_cleans_agent_scratch_artifacts_without_blocking(
    tmp_path: Path,
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    _initialize_re_state(run_dir, max_repairs=1)
    target_dir = run_dir / "re" / "sources" / "api" / "specs" / "001-re-domain"
    (target_dir / "stale-backup.md").write_text("stale\n", encoding="utf-8")

    class ScratchWritingProvider(_ShallowSpecifierProvider):
        def exec_agent(self, project_root: str, prompt: str) -> SquadAgentResult:
            result = super().exec_agent(project_root, prompt)
            phase = self.phases[-1]
            if (
                phase == "re-extract-2-specify"
                and "Domain ID: `001-re-domain`" in prompt
            ):
                (target_dir / "spec_backup.md").write_text("scratch\n", encoding="utf-8")
                scratch_dir = target_dir / "temporary"
                scratch_dir.mkdir()
                (scratch_dir / "notes.md").write_text("scratch\n", encoding="utf-8")
            if phase == "re-extract-3-verify":
                result.echelon_result["state_updates"] = {"coverage_pct": 100}
            if phase == "re-extract-5-validate":
                result.echelon_result["state_updates"] = {"resolution_pct": 100}
            return result

    result = ReExtractionController(
        provider=ScratchWritingProvider(),
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    ).run()

    assert result.completed
    assert sorted(path.name for path in target_dir.iterdir()) == ["spec.md"]
    state = json.loads((run_dir / "re" / "state.json").read_text(encoding="utf-8"))
    cleanup = state["re_target_artifact_cleanup"]
    assert cleanup == [
        {
            "stage": "pre-dispatch",
            "source_id": "api",
            "domain_id": "001-re-domain",
            "paths": ["sources/api/specs/001-re-domain/stale-backup.md"],
        },
        {
            "stage": "post-dispatch",
            "source_id": "api",
            "domain_id": "001-re-domain",
            "paths": [
                "sources/api/specs/001-re-domain/spec_backup.md",
                "sources/api/specs/001-re-domain/temporary",
            ],
        }
    ]


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
def test_source_local_convergence_measures_first_source_before_dispatching_second(
    tmp_path: Path,
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api", "web"))
    _initialize_re_state(run_dir, max_repairs=1)
    state_path = run_dir / "re" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.update(
        {
            "re_convergence_schema_version": 1,
            "re_source_budgets": {
                "max_source_cycles": 5,
                "max_domain_repairs": 5,
                "max_source_reanalysis": 5,
            },
            "re_source_states": {},
        }
    )
    state_path.write_text(json.dumps(state), encoding="utf-8")

    class SourceOrderProvider(_ShallowSpecifierProvider):
        def __init__(self) -> None:
            super().__init__()
            self.specifier_sources: list[str] = []

        def exec_agent(self, project_root: str, prompt: str) -> SquadAgentResult:
            if "RE phase: re-extract-2-specify" in prompt and "Source ID: `" in prompt:
                source_id = prompt.split("Source ID: `", 1)[1].split("`", 1)[0]
                self.specifier_sources.append(source_id)
                if source_id == "web":
                    current = json.loads(state_path.read_text(encoding="utf-8"))
                    assert current["re_source_states"]["api"]["status"] == "passed"
                    assert (run_dir / "re" / "quality" / "sources" / "api.json").is_file()
            return super().exec_agent(project_root, prompt)

    provider = SourceOrderProvider()
    result = ReExtractionController(
        provider=provider,
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    ).run()

    assert result.completed
    assert provider.specifier_sources == ["api", "web"]


@pytest.mark.unit
def test_source_local_domain_budget_records_partial_quality_debt_instead_of_blocking(
    tmp_path: Path,
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    _initialize_re_state(run_dir, max_repairs=0)
    spec = run_dir / "re" / "sources" / "api" / "specs" / "001-re-domain" / "spec.md"
    spec.write_text("# Architecture summary\n", encoding="utf-8")
    state_path = run_dir / "re" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.update(
        {
            "re_convergence_schema_version": 1,
            "re_source_budgets": {
                "max_source_cycles": 5,
                "max_domain_repairs": 0,
                "max_source_reanalysis": 5,
            },
            "re_source_states": {},
        }
    )
    state_path.write_text(json.dumps(state), encoding="utf-8")

    result = ReExtractionController(
        provider=_ShallowSpecifierProvider(),
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    ).run()

    assert result.completed
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["re_source_states"]["api"]["status"] == "partial_quality_debt"
    assert state["re_quality_debt_sources"] == ["api"]
    report_path = Path(
        state["re_source_states"]["api"]["quality_debt_report"]
    )
    assert report_path == run_dir / "re/quality/sources/api.json"
    assert json.loads(report_path.read_text(encoding="utf-8"))["source_id"] == "api"


@pytest.mark.unit
def test_source_local_cycle_budget_records_uncited_files_as_quality_debt(
    tmp_path: Path,
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    _initialize_re_state(run_dir, max_repairs=1)
    (tmp_path / "sources" / "api" / "src" / "orphan.ts").write_text(
        "export const orphan = true;\n", encoding="utf-8"
    )
    state_path = run_dir / "re" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.update(
        {
            "coverage_threshold": 99,
            "re_convergence_schema_version": 1,
            "re_source_budgets": {
                "max_source_cycles": 0,
                "max_domain_repairs": 5,
                "max_source_reanalysis": 5,
            },
            "re_source_states": {},
        }
    )
    state_path.write_text(json.dumps(state), encoding="utf-8")

    result = ReExtractionController(
        provider=_ShallowSpecifierProvider(),
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    ).run()

    assert result.completed
    state = json.loads(state_path.read_text(encoding="utf-8"))
    source = state["re_source_states"]["api"]
    assert source["status"] == "partial_quality_debt"
    assert source["coverage_pct"] == pytest.approx(83.3333333333)
    assert state["re_quality_debt_sources"] == ["api"]


@pytest.mark.unit
def test_source_coverage_repair_targets_receive_owned_and_unowned_orphans(
    tmp_path: Path,
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    _initialize_re_state(run_dir, max_repairs=1)
    controller = ReExtractionController(
        provider=_ShallowSpecifierProvider(),
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    )
    plan = ReExecutionPlan.from_json_dict(
        json.loads((run_dir / "re" / "re-execution-plan.json").read_text(encoding="utf-8"))
    )

    targets = controller._source_repair_targets(
        plan,
        "api",
        ("src/orphan.ts", "root-support.ts"),
        (),
    )

    assert targets == [
        {
            "kind": "source-domain",
            "source_id": "api",
            "domain_id": "001-re-domain",
            "root": "src",
            "orphan_paths": ["src/orphan.ts"],
        },
        {
            "kind": "source-support",
            "source_id": "api",
            "orphan_paths": ["root-support.ts"],
        },
    ]
    domain_prompt = controller._specification_target_prompt(targets[0])
    support_prompt = controller._specification_target_prompt(targets[1])
    assert "Source coverage repair" in domain_prompt
    assert "src/orphan.ts" in domain_prompt
    assert "source supporting-artifacts register" in support_prompt
    assert "root-support.ts" in support_prompt


@pytest.mark.unit
def test_re_prompt_includes_pending_human_resume_answer(tmp_path: Path) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    controller = ReExtractionController(
        provider=_ShallowSpecifierProvider(),
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    )
    plan = controller._load_plan()

    prompt = controller._prompt_for(
        "re-extract-1-analyze",
        {"resume_answer": "Use the public v2 contract"},
        plan,
    )

    assert "## Human Resume Answer" in prompt
    assert "Use the public v2 contract" in prompt


@pytest.mark.unit
def test_re_prompt_appends_phase_and_canonical_result_contract(tmp_path: Path) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    controller = ReExtractionController(
        provider=_ShallowSpecifierProvider(),
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    )
    plan = controller._load_plan()

    prompt = controller._prompt_for(
        "re-extract-2-specify",
        {},
        plan,
        {
            "kind": "source-domain",
            "source_id": "api",
            "domain_id": "001-re-domain",
            "root": "src",
        },
    )

    assert "## RE Result Contract" in prompt
    assert "Set `phase_id: re-extract-2-specify`." in prompt
    assert "Allowed verdicts for this RE dispatch are `DONE` and `BLOCKED`." in prompt
    assert "Canonical echelon_result contract" in prompt
    assert "NEVER wrap this block in markdown fences" in prompt


@pytest.mark.unit
def test_source_domain_prompt_injects_canonical_paths_and_exact_gate_findings(
    tmp_path: Path,
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    controller = ReExtractionController(
        provider=_ShallowSpecifierProvider(),
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    )
    plan = controller._load_plan()
    source_root = Path(plan.refresh_sources[0].absolute_path)
    target = {
        "kind": "source-domain",
        "source_id": "api",
        "domain_id": "001-re-domain",
        "root": "src",
    }
    report_path = (
        run_dir
        / "re"
        / "quality"
        / "targets"
        / "api"
        / "001-re-domain.json"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(
            {
                "passed": False,
                "failures": [
                    {
                        "invalid_source_evidence": ["`pyproject.toml:1`"],
                        "functional_requirements_without_evidence": ["FR-007"],
                        "semantic_preflight_findings": [
                            {"message": "Universal claim lacks exhaustive evidence"}
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    prompt = controller._specification_target_prompt(target)
    metadata = controller._prompt_metadata_for_target(plan, target)

    assert f"Source repository root: `{source_root}`" in prompt
    assert f"Absolute owned domain root: `{source_root / 'src'}`" in prompt
    assert "Do not look for source code below the RE output directory" in prompt
    assert "Invalid source evidence: `pyproject.toml:1`" in prompt
    assert "Functional requirements without evidence: FR-007" in prompt
    assert "Universal claim lacks exhaustive evidence" in prompt
    assert metadata["tool_read_roots"] == [
        str((run_dir / "re").resolve()),
        str((source_root / "src").resolve()),
    ]
    assert metadata["tool_write_paths"] == [
        str(
            (
                run_dir
                / "re"
                / "sources"
                / "api"
                / "specs"
                / "001-re-domain"
                / "spec.md"
            ).resolve()
        )
    ]


@pytest.mark.unit
def test_target_quality_failure_reports_active_repair_budget(capsys) -> None:
    ReExtractionController._report_target_quality_failure(
        "api",
        "001-re-domain",
        attempts=1,
        budget=1,
        agent_block_detail=None,
    )
    assert "repair attempt 1/1" in capsys.readouterr().out

    ReExtractionController._report_target_quality_failure(
        "api",
        "001-re-domain",
        attempts=2,
        budget=1,
        agent_block_detail=None,
    )
    assert "repair budget exhausted (1/1)" in capsys.readouterr().out


@pytest.mark.unit
def test_re_controller_passes_result_contract_to_capable_provider(
    tmp_path: Path,
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    _initialize_re_state(run_dir, max_repairs=1)

    class ContractCapturingProvider(_ShallowSpecifierProvider):
        supports_result_contract = True
        supports_prompt_metadata = True

        def __init__(self) -> None:
            super().__init__()
            self.contracts: list[object] = []
            self.prompt_metadata: list[object] = []

        def exec_agent(
            self, project_root: str, prompt: str, **kwargs: object
        ) -> SquadAgentResult:
            self.contracts.append(kwargs.get("result_contract"))
            self.prompt_metadata.append(kwargs.get("prompt_metadata"))
            result = super().exec_agent(project_root, prompt)
            phase = self.phases[-1]
            if phase == "re-extract-3-verify":
                result.echelon_result["state_updates"] = {"coverage_pct": 80}
            if phase == "re-extract-5-validate":
                result.echelon_result["state_updates"] = {"resolution_pct": 80}
            return result

    provider = ContractCapturingProvider()
    result = ReExtractionController(
        provider=provider,
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    ).run()

    assert result.completed
    assert provider.contracts
    first_contract = provider.contracts[0]
    assert first_contract is not None
    assert first_contract.allowed_verdicts == frozenset({"DONE", "BLOCKED"})
    assert first_contract.allowed_state_update_keys == frozenset()
    source_metadata = next(
        item
        for item in provider.prompt_metadata
        if isinstance(item, dict) and item.get("tool_write_paths")
    )
    assert len(source_metadata["tool_read_roots"]) == 2
    assert source_metadata["tool_write_paths"][0].endswith("/spec.md")


@pytest.mark.unit
@pytest.mark.parametrize(
    "phase",
    [
        "re-extract-2-specify",
        "re-extract-3-verify",
        "re-extract-4-expand",
        "re-extract-5-validate",
        "re-extract-6-checklist",
        "re-extract-7-constitute",
    ],
)
def test_re_authoring_result_contracts_are_file_only(phase: str) -> None:
    contract = ReExtractionController._result_contract_for_phase(phase)

    assert contract.allowed_state_update_keys == frozenset()
    assert "Return `state_updates: {}`" in (
        ReExtractionController._phase_result_contract_prompt(phase)
    )


@pytest.mark.unit
def test_retarget_marker_inventory_is_controller_owned(tmp_path: Path) -> None:
    from harness.re_controller import discover_retarget_markers

    strategy = tmp_path / "re" / "workspace" / "strategy"
    (strategy / "adrs").mkdir(parents=True)
    (strategy / "constitution.md").write_text(
        "# Constitution\n\nStack: [REQUIRES INPUT]\n",
        encoding="utf-8",
    )
    (strategy / "migration-strategy.md").write_text(
        "# Migration\n\nOwner: [REQUIRES INPUT]\n",
        encoding="utf-8",
    )
    (strategy / "adrs" / "ADR-001.md").write_text(
        "# ADR\n\nDecision: [REQUIRES INPUT]\n",
        encoding="utf-8",
    )
    (strategy / "ignored.md").write_text(
        "Outside contract: [REQUIRES INPUT]\n",
        encoding="utf-8",
    )

    inventory = discover_retarget_markers(tmp_path / "re")

    assert inventory["count"] == 3
    assert [item["path"] for item in inventory["markers"]] == [
        "workspace/strategy/adrs/ADR-001.md",
        "workspace/strategy/constitution.md",
        "workspace/strategy/migration-strategy.md",
    ]
    assert all(item["line"] == 3 for item in inventory["markers"])
    assert all("[REQUIRES INPUT]" in item["context"] for item in inventory["markers"])


@pytest.mark.unit
def test_re_specifier_prose_does_not_delegate_check_domain_to_agent() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    paths = [
        repo_root / "extension" / "agents" / "re" / "specifier.md",
        repo_root
        / "extension"
        / "workflow"
        / "phases"
        / "re-extract-2-specify.md",
    ]

    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert "echelon re check-domain" not in text


@pytest.mark.unit
def test_re_prose_avoids_provider_specific_cli_tool_instructions() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    paths = [
        *(
            repo_root / "extension" / "agents" / "re"
        ).glob("*.md"),
        *(
            repo_root / "extension" / "workflow" / "phases"
        ).glob("re-*.md"),
    ]
    forbidden = (
        "Bash Command Guidelines",
        "Bash tool",
        "Glob tool",
        "Read tool",
        "Grep tool",
        "run-analysis.sh",
        "command -v jq",
        "sys.stdout.write",
        "specify extension config resolve",
        "verify with Glob",
        "```bash",
    )

    for path in paths:
        text = path.read_text(encoding="utf-8")
        for phrase in forbidden:
            assert phrase not in text, f"{path} contains {phrase!r}"


@pytest.mark.unit
def test_specification_post_dispatch_runs_controller_quality_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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
    state["re_specification_targets"] = [target]
    calls: list[tuple[Path, str, str]] = []

    def fake_validate(
        run_re_dir: Path,
        loaded_plan: ReExecutionPlan,
        source_id: str,
        domain_id: str,
    ) -> ReQualityReport:
        calls.append((run_re_dir, source_id, domain_id))
        assert loaded_plan is plan
        return ReQualityReport(passed=True, failures=())

    monkeypatch.setattr(
        "harness.re_controller.validate_staged_re_domain_quality",
        fake_validate,
    )

    result = controller._run_specification_target_post_dispatch(state, plan, target)

    assert result is None
    assert calls == [(run_dir / "re", "api", "001-re-domain")]
    assert state["re_specification_targets"] == []


@pytest.mark.unit
def test_source_coverage_repair_protocol_migrates_active_legacy_queue(
    tmp_path: Path,
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    _initialize_re_state(run_dir, max_repairs=1)
    (tmp_path / "sources" / "api" / "src" / "orphan.ts").write_text(
        "export const orphan = true;\n", encoding="utf-8"
    )
    controller = ReExtractionController(
        provider=_ShallowSpecifierProvider(),
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    )
    plan = ReExecutionPlan.from_json_dict(
        json.loads((run_dir / "re" / "re-execution-plan.json").read_text(encoding="utf-8"))
    )
    state = json.loads((run_dir / "re" / "state.json").read_text(encoding="utf-8"))
    state.update(
        {
            "mode": "workspace",
            "phase": "re-extract-2-specify",
            "coverage_threshold": 99,
            "re_convergence_schema_version": 1,
            "re_source_states": {
                "api": {
                    "status": "active",
                    "source_cycles": 4,
                    "domain_repairs": {},
                    "source_reanalysis": 0,
                    "quality_report": str(
                        run_dir / "re" / "quality" / "sources" / "api.json"
                    ),
                }
            },
            "re_source_order": ["api"],
            "re_active_source_id": "api",
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

    assert controller._upgrade_source_coverage_repair_protocol(state, plan)

    assert state["re_source_coverage_repair_protocol_version"] == 1
    assert state["re_specification_targets"][0]["orphan_paths"] == ["src/orphan.ts"]


@pytest.mark.unit
def test_source_coverage_repair_protocol_reclaims_legacy_quality_debt(
    tmp_path: Path,
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    _initialize_re_state(run_dir, max_repairs=1)
    (tmp_path / "sources" / "api" / "src" / "orphan.ts").write_text(
        "export const orphan = true;\n", encoding="utf-8"
    )
    controller = ReExtractionController(
        provider=_ShallowSpecifierProvider(),
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    )
    plan = ReExecutionPlan.from_json_dict(
        json.loads((run_dir / "re" / "re-execution-plan.json").read_text(encoding="utf-8"))
    )
    state = json.loads((run_dir / "re" / "state.json").read_text(encoding="utf-8"))
    state.update(
        {
            "mode": "workspace",
            "phase": "re-extract-2-specify",
            "coverage_threshold": 99,
            "re_convergence_schema_version": 1,
            "re_source_states": {
                "api": {
                    "status": "partial_quality_debt",
                    "source_cycles": 5,
                    "domain_repairs": {"001-re-domain": 5},
                    "source_reanalysis": 0,
                }
            },
            "re_source_order": ["api"],
            "re_quality_debt_sources": ["api"],
            "re_specification_targets": [],
        }
    )

    assert controller._upgrade_source_coverage_repair_protocol(state, plan)

    source = state["re_source_states"]["api"]
    assert source["status"] == "active"
    assert source["source_cycles"] == 0
    assert source["domain_repairs"] == {}
    assert state["re_active_source_id"] == "api"
    assert state["re_specification_targets"][0]["orphan_paths"] == ["src/orphan.ts"]
    assert state["re_quality_debt_sources"] == []


@pytest.mark.unit
def test_source_coverage_repair_converges_domain_and_supporting_artifacts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    _initialize_re_state(run_dir, max_repairs=1)
    state_path = run_dir / "re" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.update(
        {
            "coverage_threshold": 99,
            "re_convergence_schema_version": 1,
            "re_source_budgets": {
                "max_source_cycles": 5,
                "max_domain_repairs": 5,
                "max_source_reanalysis": 5,
            },
            "re_source_states": {},
        }
    )
    state_path.write_text(json.dumps(state), encoding="utf-8")
    source_root = tmp_path / "sources" / "api"
    (source_root / "src" / "orphan.ts").write_text(
        "export const orphan = true;\n", encoding="utf-8"
    )
    (source_root / "root-support.ts").write_text(
        "export const support = true;\n", encoding="utf-8"
    )
    spec = run_dir / "re" / "sources" / "api" / "specs" / "001-re-domain" / "spec.md"

    class CoverageRepairProvider(_ShallowSpecifierProvider):
        def exec_agent(self, project_root: str, prompt: str) -> SquadAgentResult:
            result = super().exec_agent(project_root, prompt)
            if "Source coverage repair:" in prompt:
                spec.write_text(
                    spec.read_text(encoding="utf-8")
                    + "\nAdditional source evidence: `src/orphan.ts:1`\n",
                    encoding="utf-8",
                )
            if "Controller-Owned Source Supporting-Artifacts Target" in prompt:
                (run_dir / "re" / "sources" / "api" / "supporting-artifacts.md").write_text(
                    "# Supporting Artifacts\n\n"
                    "## Source Evidence\n\n"
                    "- `root-support.ts:1` provides runtime support.\n",
                    encoding="utf-8",
                )
                result.echelon_result["state_updates"] = {"sources": ["support"]}
            return result

    result = ReExtractionController(
        provider=CoverageRepairProvider(),
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    ).run()

    assert result.completed
    state = json.loads((run_dir / "re" / "state.json").read_text(encoding="utf-8"))
    assert state["re_source_states"]["api"]["status"] == "passed"
    assert state["re_source_states"]["api"]["coverage_pct"] == 100
    assert (run_dir / "re" / "sources" / "api" / "supporting-artifacts.md").is_file()
    output = capsys.readouterr().out
    assert "[re] source measured: api - " in output
    assert "[re] source repair: api - cycle 1/5;" in output


@pytest.mark.unit
def test_re_max_inner_override_raises_all_source_local_budgets(tmp_path: Path) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    _initialize_re_state(run_dir, max_repairs=1)
    outer_state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    outer_state["re_max_inner"] = 10
    (run_dir / "state.json").write_text(json.dumps(outer_state), encoding="utf-8")
    controller = ReExtractionController(
        provider=_ShallowSpecifierProvider(),
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    )
    state = json.loads((run_dir / "re" / "state.json").read_text(encoding="utf-8"))

    plan = ReExecutionPlan.from_json_dict(
        json.loads((run_dir / "re" / "re-execution-plan.json").read_text(encoding="utf-8"))
    )

    assert controller._apply_re_budget_override(state, plan)
    assert state["re_source_budgets"] == {
        "max_source_cycles": 10,
        "max_domain_repairs": 10,
        "max_source_reanalysis": 10,
    }


@pytest.mark.unit
def test_re_max_inner_override_reactivates_quality_debt_without_resetting_budget(
    tmp_path: Path,
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    _initialize_re_state(run_dir, max_repairs=1)
    (tmp_path / "sources" / "api" / "src" / "orphan.ts").write_text(
        "export const orphan = true;\n", encoding="utf-8"
    )
    outer_state_path = run_dir / "state.json"
    outer_state = json.loads(outer_state_path.read_text(encoding="utf-8"))
    outer_state["re_max_inner"] = 10
    outer_state_path.write_text(json.dumps(outer_state), encoding="utf-8")
    state_path = run_dir / "re" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.update(
        {
            "mode": "workspace",
            "status": "blocked",
            "blocked_reason": "re_source_quality_debt",
            "phase": "re-extract-5-validate",
            "coverage_threshold": 99,
            "resolution_threshold": 99,
            "max_validate_iterations": 5,
            "re_convergence_schema_version": 1,
            "re_source_convergence_quality_contract_version": 1,
            "re_source_coverage_repair_protocol_version": 1,
            "re_target_quality_protocol_version": 1,
            "re_source_budgets": {
                "max_source_cycles": 5,
                "max_domain_repairs": 5,
                "max_source_reanalysis": 5,
            },
            "re_source_states": {
                "api": {
                    "status": "partial_quality_debt",
                    "source_cycles": 5,
                    "domain_repairs": {"001-re-domain": 5},
                    "source_reanalysis": 5,
                }
            },
            "re_source_order": ["api"],
            "re_quality_debt_sources": ["api"],
            "re_workspace_synthesis_complete": True,
        }
    )
    state_path.write_text(json.dumps(state), encoding="utf-8")
    spec = run_dir / "re" / "sources" / "api" / "specs" / "001-re-domain" / "spec.md"

    class BudgetRecoveryProvider(_ShallowSpecifierProvider):
        def __init__(self) -> None:
            super().__init__()
            self.repair_prompts: list[str] = []

        def exec_agent(self, project_root: str, prompt: str) -> SquadAgentResult:
            result = super().exec_agent(project_root, prompt)
            phase = self.phases[-1]
            if phase == "re-extract-2-specify" and "Source coverage repair:" in prompt:
                self.repair_prompts.append(prompt)
                spec.write_text(
                    spec.read_text(encoding="utf-8")
                    + "\nRecovered coverage evidence: `src/orphan.ts:1`\n",
                    encoding="utf-8",
                )
            if phase == "re-extract-3-verify":
                result.echelon_result["state_updates"] = {"coverage_pct": 99}
            return result

    provider = BudgetRecoveryProvider()
    result = ReExtractionController(
        provider=provider,
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    ).run()

    assert result.completed
    assert len(provider.repair_prompts) == 1
    assert "`src/orphan.ts`" in provider.repair_prompts[0]
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["re_source_states"]["api"]["status"] == "passed"
    assert state["re_source_states"]["api"]["source_cycles"] == 6
    assert state["re_source_states"]["api"]["domain_repairs"] == {
        "001-re-domain": 5
    }
    assert state["re_quality_debt_sources"] == []
    assert "re_pending_source_repair_targets" not in state


@pytest.mark.unit
def test_re_max_inner_override_reclaims_semantic_debt_only_after_a_genuine_raise(
    tmp_path: Path,
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    _initialize_re_state(run_dir, max_repairs=1)
    outer_state_path = run_dir / "state.json"
    outer_state = json.loads(outer_state_path.read_text(encoding="utf-8"))
    outer_state["re_max_inner"] = 10
    outer_state_path.write_text(json.dumps(outer_state), encoding="utf-8")
    controller = ReExtractionController(
        provider=_ShallowSpecifierProvider(),
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    )
    plan = ReExecutionPlan.from_json_dict(
        json.loads((run_dir / "re" / "re-execution-plan.json").read_text(encoding="utf-8"))
    )
    state = json.loads((run_dir / "re" / "state.json").read_text(encoding="utf-8"))
    state.update(
        {
            "mode": "workspace",
            "phase": "re-extract-5-validate",
            "coverage_threshold": 99,
            "re_convergence_schema_version": 1,
            "re_source_budgets": {
                "max_source_cycles": 10,
                "max_domain_repairs": 10,
                "max_source_reanalysis": 10,
            },
            "re_source_states": {
                "api": {
                    "status": "partial_quality_debt",
                    "source_cycles": 5,
                    "domain_repairs": {"001-re-domain": 5},
                    "source_reanalysis": 5,
                    "re_quality_debt_semantic_failures": [
                        {
                            "domain_id": "001-re-domain",
                            "reason": "semantic_quality_incomplete",
                        }
                    ],
                }
            },
            "re_source_order": ["api"],
            "re_quality_debt_sources": ["api"],
        }
    )

    assert not controller._apply_re_budget_override(state, plan)
    assert state["re_source_states"]["api"]["status"] == "partial_quality_debt"
    assert "re_specification_targets" not in state

    outer_state["re_max_inner"] = 11
    outer_state_path.write_text(json.dumps(outer_state), encoding="utf-8")

    assert controller._apply_re_budget_override(state, plan)
    assert state["re_source_states"]["api"]["status"] == "active"
    assert state["re_source_states"]["api"]["source_cycles"] == 6
    assert state["re_source_states"]["api"]["coverage_pct"] == 100
    assert state["re_specification_targets"] == [
        {
            "kind": "source-domain",
            "source_id": "api",
            "domain_id": "001-re-domain",
            "root": "src",
        }
    ]


@pytest.mark.unit
def test_source_local_semantic_repair_requeues_only_the_failing_source(
    tmp_path: Path,
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api", "web"))
    _initialize_re_state(run_dir, max_repairs=2)
    state_path = run_dir / "re" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.update(
        {
            "re_convergence_schema_version": 1,
            "re_source_budgets": {
                "max_source_cycles": 5,
                "max_domain_repairs": 5,
                "max_source_reanalysis": 5,
            },
            "re_source_states": {},
        }
    )
    state_path.write_text(json.dumps(state), encoding="utf-8")

    class SemanticRepairProvider(_ShallowSpecifierProvider):
        def __init__(self) -> None:
            super().__init__()
            self.specifier_sources: list[str] = []
            self.workspace_synthesis_count = 0

        def exec_agent(self, project_root: str, prompt: str) -> SquadAgentResult:
            phase = prompt.split("RE phase: ", 1)[1].split("\n", 1)[0]
            if (
                phase == "re-extract-2-specify"
                and "Generate source overviews, source-owned synthesis, and workspace synthesis only" in prompt
            ):
                self.workspace_synthesis_count += 1
            if phase == "re-extract-2-specify" and "Source ID: `" in prompt:
                self.specifier_sources.append(
                    prompt.split("Source ID: `", 1)[1].split("`", 1)[0]
                )
            result = super().exec_agent(project_root, prompt)
            if phase == "re-extract-5-validate" and self.phases.count(phase) == 1:
                result.echelon_result["semantic_quality_review"] = {
                    "schema_version": 1,
                    "domains": [
                        {
                            "source_id": "api",
                            "domain_id": "001-re-domain",
                            "verdict": "REPAIR",
                            "findings": ["The observed retry behavior is not documented."],
                            "source_evidence": ["`src/file-1.ts:1`"],
                        },
                    ],
                }
            return result

    provider = SemanticRepairProvider()
    result = ReExtractionController(
        provider=provider,
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    ).run()

    assert result.completed
    assert provider.specifier_sources == ["api", "web", "api"]
    assert provider.workspace_synthesis_count == 2


@pytest.mark.unit
def test_controller_preserves_agent_block_reason_after_initializing_re_state(
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
                    "blocked_reason": "source analysis required before specification",
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

    assert result.blocked_reason == (
        "re_agent_blocked: source analysis required before specification"
    )
    state = json.loads((run_dir / "re" / "state.json").read_text(encoding="utf-8"))
    assert state["phase"] == "re-extract-2-specify"
    assert state["status"] == "blocked"
    assert state["re_agent_result_detail"] == "source analysis required before specification"
    assert state["last_dispatch"]["post_dispatch_complete"] is True


@pytest.mark.unit
def test_controller_keeps_transport_failure_separate_from_agent_block(
    tmp_path: Path,
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))

    class BlockingProvider(_ShallowSpecifierProvider):
        def exec_agent(self, project_root: str, prompt: str) -> SquadAgentResult:
            phase = prompt.split("RE phase: ", 1)[1].split("\n", 1)[0]
            self.phases.append(phase)
            return SquadAgentResult(
                exit_code=1,
                echelon_result=None,
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
    assert state["last_dispatch"]["post_dispatch_complete"] is False


@pytest.mark.unit
def test_agent_dispatch_failure_records_provider_error_detail(tmp_path: Path) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))

    class BlockingProvider(_ShallowSpecifierProvider):
        def exec_agent(self, project_root: str, prompt: str) -> SquadAgentResult:
            return SquadAgentResult(
                exit_code=1,
                echelon_result=None,
                raw_output="",
                stderr="OpenAI-compatible API key file is not readable: ~/.omlx_token",
                duration_ms=1,
                timed_out=False,
            )

    result = ReExtractionController(
        provider=BlockingProvider(),
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    ).run()

    assert result.blocked_reason == "re_agent_dispatch_failed"
    state = json.loads((run_dir / "re" / "state.json").read_text(encoding="utf-8"))
    assert state["re_agent_result_detail"] == (
        "agent exited with code 1; OpenAI-compatible API key file is not "
        "readable: ~/.omlx_token"
    )


@pytest.mark.unit
def test_agent_blocked_deep_spec_gate_failure_enters_bounded_repair_loop(
    tmp_path: Path,
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    _initialize_re_state(run_dir, max_repairs=1)
    state_path = run_dir / "re" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.update(
        {
            "mode": "workspace",
            "re_convergence_schema_version": 1,
            "re_source_budgets": {
                "max_source_cycles": 5,
                "max_domain_repairs": 5,
                "max_source_reanalysis": 5,
            },
            "re_source_states": {},
        }
    )
    state_path.write_text(json.dumps(state), encoding="utf-8")
    spec = run_dir / "re" / "sources" / "api" / "specs" / "001-re-domain" / "spec.md"
    spec.write_text("# Architecture summary\n", encoding="utf-8")

    class GateBlockingProvider(_ShallowSpecifierProvider):
        def exec_agent(self, project_root: str, prompt: str) -> SquadAgentResult:
            result = super().exec_agent(project_root, prompt)
            phase = self.phases[-1]
            if phase == "re-extract-2-specify" and self.phases.count(phase) == 1:
                return SquadAgentResult(
                    exit_code=0,
                    echelon_result={
                        "verdict": "BLOCKED",
                        "state_updates": {},
                        "journal_entries": [],
                        "blocked_reason": "deterministic deep-spec gate reported missing evidence",
                    },
                    raw_output="",
                    duration_ms=1,
                    timed_out=False,
                )
            if phase == "re-extract-2-specify" and self.phases.count(phase) == 2:
                spec.write_text(_deep_spec("api", "v1"), encoding="utf-8")
            updates: dict[str, int] = {}
            if phase == "re-extract-3-verify":
                updates["coverage_pct"] = 80
            if phase == "re-extract-5-validate":
                updates["resolution_pct"] = 80
            return SquadAgentResult(
                exit_code=result.exit_code,
                echelon_result={**result.echelon_result, "state_updates": updates},
                raw_output=result.raw_output,
                duration_ms=result.duration_ms,
                timed_out=result.timed_out,
            )

    provider = GateBlockingProvider()
    result = ReExtractionController(
        provider=provider,
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    ).run()

    assert result.completed
    # Two source-domain attempts plus the mandatory workspace-synthesis target.
    assert provider.phases.count("re-extract-2-specify") == 3
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["re_source_states"]["api"]["domain_repairs"] == {
        "001-re-domain": 1
    }
    assert "re_agent_result_detail" not in state
    assert state["last_dispatch"]["post_dispatch_complete"] is True


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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    _initialize_re_state(run_dir, max_repairs=2)

    measurements = iter((70, 100))

    def measured_coverage(self, state, plan):
        state["coverage_pct"] = next(measurements)
        return None

    monkeypatch.setattr(
        ReExtractionController,
        "_refresh_controller_coverage",
        measured_coverage,
    )

    provider = _ShallowSpecifierProvider()
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
    (run_dir / "re" / "sources" / "api" / "supporting-artifacts.md").write_text(
        "# Supporting Artifacts\n\n"
        + "\n".join(f"- `src/file-{number}.ts:1`" for number in range(1, 6))
        + "\n",
        encoding="utf-8",
    )

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
                                "## Behavior Coverage",
                                "| Category | Status | Observed Scope | Source Evidence |",
                                "|---|---|---|---|",
                                f"| public operations | observed | API behavior | `{root}/file-1.ts:1` |",
                                "| configuration keys | not-observed | none found | — |",
                                f"| errors and recovery | observed | failure paths | `{root}/file-2.ts:1` |",
                                f"| boundaries and edge cases | observed | API edges | `{root}/file-3.ts:1` |",
                                "| operator-visible behavior | not-observed | none found | — |",
                                "| tests | not-observed | none found | — |",
                                f"| evidence scope | observed | owned domain | `{root}/file-4.ts:1` |",
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
def test_controller_ignores_agent_status_updates_for_re_lifecycle(
    tmp_path: Path,
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    _initialize_re_state(run_dir, max_repairs=1)

    class LifecycleStatusProvider(_ShallowSpecifierProvider):
        def exec_agent(self, project_root: str, prompt: str) -> SquadAgentResult:
            result = super().exec_agent(project_root, prompt)
            phase = self.phases[-1]
            updates: dict[str, object] = {"status": "done"}
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
        provider=LifecycleStatusProvider(),
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    ).run()

    state = json.loads((run_dir / "re" / "state.json").read_text(encoding="utf-8"))
    assert result.completed
    assert state["status"] == "done"
    assert state["phase"] == "re-extract-7-constitute"


@pytest.mark.unit
def test_semantic_quality_repair_returns_only_the_failed_domain_to_specifier(
    tmp_path: Path,
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    _initialize_re_state(run_dir, max_repairs=1)
    spec = run_dir / "re" / "sources" / "api" / "specs" / "001-re-domain" / "spec.md"

    class SemanticRepairProvider(_ShallowSpecifierProvider):
        def __init__(self) -> None:
            super().__init__()
            self.repair_prompt = ""

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
                and "Controller-Owned Semantic Repair Packet" in prompt
            ):
                self.repair_prompt = prompt
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
    assert "Controller-Owned Semantic Repair Packet" in provider.repair_prompt
    assert "FR-001 omits the observed retry exhaustion behavior." in provider.repair_prompt
    assert "`src/file-1.ts:1`" in provider.repair_prompt
    state = json.loads((run_dir / "re" / "state.json").read_text(encoding="utf-8"))
    assert state["re_quality_repair_attempts"] == 1
    assert state["re_semantic_quality_report"].endswith("quality/semantic-quality-review.json")


@pytest.mark.unit
def test_invalid_semantic_review_retries_with_controller_validation_feedback(
    tmp_path: Path,
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    _initialize_re_state(run_dir, max_repairs=1)

    class InvalidThenValidSemanticReviewProvider(_ShallowSpecifierProvider):
        def __init__(self) -> None:
            super().__init__()
            self.semantic_prompts: list[str] = []

        def exec_agent(self, project_root: str, prompt: str) -> SquadAgentResult:
            result = super().exec_agent(project_root, prompt)
            if self.phases[-1] == "re-extract-3-verify":
                result.echelon_result["state_updates"] = {"coverage_pct": 80}
            if self.phases[-1] != "re-extract-5-validate":
                return result
            self.semantic_prompts.append(prompt)
            if len(self.semantic_prompts) == 1:
                result.echelon_result["semantic_quality_review"] = {
                    "schema_version": 1,
                    "domains": [
                        {
                            "source_id": "api",
                            "domain_id": "001-re-domain",
                            "verdict": "REPAIR",
                            "findings": ["FR-001 omits retry exhaustion."],
                            "source_evidence": [
                                "src/file-1.ts (path referenced but not validated)"
                            ],
                        }
                    ],
                }
            return result

    provider = InvalidThenValidSemanticReviewProvider()
    result = ReExtractionController(
        provider=provider,
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    ).run()

    assert result.completed
    assert len(provider.semantic_prompts) == 2
    assert "## Controller Validation Feedback" in provider.semantic_prompts[1]
    assert "semantic quality review invalid for api/001-re-domain" in (
        provider.semantic_prompts[1]
    )
    assert "src/file-1.ts (path referenced but not validated)" in (
        provider.semantic_prompts[1]
    )
    state = json.loads((run_dir / "re" / "state.json").read_text(encoding="utf-8"))
    assert "re_semantic_review_invalid_attempts" not in state
    assert "re_semantic_review_invalid_error" not in state


@pytest.mark.unit
def test_semantic_validator_prompt_lists_required_domain_inventory(
    tmp_path: Path,
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    _initialize_re_state(run_dir, max_repairs=1)

    class CapturingProvider(_ShallowSpecifierProvider):
        def __init__(self) -> None:
            super().__init__()
            self.semantic_prompt = ""

        def exec_agent(self, project_root: str, prompt: str) -> SquadAgentResult:
            result = super().exec_agent(project_root, prompt)
            if self.phases[-1] == "re-extract-3-verify":
                result.echelon_result["state_updates"] = {"coverage_pct": 80}
            if self.phases[-1] == "re-extract-5-validate":
                self.semantic_prompt = prompt
            return result

    provider = CapturingProvider()
    result = ReExtractionController(
        provider=provider,
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    ).run()

    assert result.completed
    assert "## Requested Semantic Domain" in provider.semantic_prompt
    assert "Requested semantic domain: `api/001-re-domain`" in provider.semantic_prompt
    assert "Do not write RE_VALIDATOR_RESULT.yaml" in provider.semantic_prompt


@pytest.mark.unit
def test_invalid_semantic_review_blocks_only_after_validation_budget_exhausts(
    tmp_path: Path,
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    _initialize_re_state(run_dir, max_repairs=1)
    state_path = run_dir / "re" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["max_validate_iterations"] = 2
    state_path.write_text(json.dumps(state), encoding="utf-8")

    class AlwaysInvalidSemanticReviewProvider(_ShallowSpecifierProvider):
        def exec_agent(self, project_root: str, prompt: str) -> SquadAgentResult:
            result = super().exec_agent(project_root, prompt)
            if self.phases[-1] == "re-extract-3-verify":
                result.echelon_result["state_updates"] = {"coverage_pct": 80}
            if self.phases[-1] == "re-extract-5-validate":
                result.echelon_result["semantic_quality_review"] = {
                    "schema_version": 1,
                    "domains": [
                        {
                            "source_id": "api",
                            "domain_id": "001-re-domain",
                            "verdict": "REPAIR",
                            "findings": ["FR-001 omits retry exhaustion."],
                            "source_evidence": ["src/file-1.ts (not a citation)"],
                        }
                    ],
                }
            return result

    provider = AlwaysInvalidSemanticReviewProvider()
    result = ReExtractionController(
        provider=provider,
        project_root=tmp_path,
        run_dir=run_dir,
        extension_root=_extension_root(tmp_path),
    ).run()

    assert not result.completed
    assert result.blocked_reason == "re_semantic_quality_review_invalid"
    assert result.blocked_detail is not None
    assert "semantic quality review invalid for api/001-re-domain" in (
        result.blocked_detail
    )
    assert provider.phases.count("re-extract-5-validate") == 2
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["re_semantic_review_invalid_attempts"] == 2
    assert "semantic quality review invalid for api/001-re-domain" in (
        state["re_semantic_review_invalid_error"]
    )
    assert "src/file-1.ts (not a citation)" in state["re_semantic_review_invalid_error"]


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
