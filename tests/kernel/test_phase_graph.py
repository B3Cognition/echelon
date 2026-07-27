"""Tests for PhaseGraph — loads workflow/definition.yaml."""
import sys
from pathlib import Path

import pytest
import yaml

EXT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(EXT_ROOT) not in sys.path:
    sys.path.insert(0, str(EXT_ROOT))

from harness.controller_state_contracts import (
    ControllerContractRegistryError,
    validate_controller_result,
)
from harness.controller_state_contract_requirements import (
    required_controller_contract_name,
)
from harness.phase_graph import PhaseGraph

DEFINITION = EXT_ROOT / "extension/workflow/definition.yaml"
EXT_YML = EXT_ROOT / "extension/extension.yml"
REQUIRED_CONTROLLER_CONTRACTS = {
    "phase1-lexicon": "spec_lexicon",
    "phase1-understanding": "understanding",
    "phase1-why2": "phase1_quality_certificate",
    "phase2-decide": "feasibility_authoring_verdict",
    "phase2-tracker-alignment": "intent_alignment_authoring_verdict",
    "phase3-tasks-lexicon": "tasks_lexicon",
    "phase3-understanding": "understanding",
    "phase3-consensus-tasks-lexicon": "tasks_lexicon",
}


@pytest.mark.parametrize(
    ("artifact", "contract"),
    [
        ("feasibility", "feasibility_structural"),
        ("intent-alignment-check", "intent_alignment_structural"),
    ],
)
def test_structural_contract_is_derived_from_artifact(
    artifact: str, contract: str
) -> None:
    assert required_controller_contract_name(
        {
            "id": f"custom-{artifact}",
            "type": "deterministic_structural",
            "structural_artifact": artifact,
        }
    ) == contract


def test_unknown_structural_artifact_has_no_contract() -> None:
    assert required_controller_contract_name(
        {
            "id": "custom-structural",
            "type": "deterministic_structural",
            "structural_artifact": "unknown",
        }
    ) is None


def _write_structural_graph(
    tmp_path: Path, mutation: str | None = None
) -> tuple[Path, Path]:
    registry = tmp_path / "contracts.yaml"
    registry.write_bytes(
        (
            EXT_ROOT / "extension/workflow/controller-state-contracts.yaml"
        ).read_bytes()
    )
    phase: dict[str, object] = {
        "id": "custom-structural",
        "type": "deterministic_structural",
        "structural_artifact": "feasibility",
        "allowed_state_updates": [],
        "controller_state_contract": "feasibility_structural",
        "transitions": [
            {"to": "author", "condition": "structural_action = repair"},
            {"to": "blocked", "condition": "structural_action = block"},
            {
                "to": "done",
                "condition": (
                    "structural_action in [proceed, proceed_with_warning] "
                    "AND feasibility_verdict = PASS"
                ),
            },
        ],
    }
    if mutation == "missing_artifact":
        phase.pop("structural_artifact")
    elif mutation == "unknown_artifact":
        phase["structural_artifact"] = "unknown"
    elif mutation == "agent":
        phase["agent"] = "provider"
    elif mutation == "agents":
        phase["agents"] = [{"id": "provider"}]
    elif mutation == "allowlist":
        phase["allowed_state_updates"] = ["provider_field"]
    elif mutation == "wrong_contract":
        phase["controller_state_contract"] = "intent_alignment_structural"
    elif mutation == "missing_repair":
        phase["transitions"] = phase["transitions"][1:]
    elif mutation == "missing_block":
        phase["transitions"] = [
            phase["transitions"][0],
            phase["transitions"][2],
        ]
    elif mutation == "missing_forward":
        phase["transitions"] = phase["transitions"][:2]
    definition = tmp_path / "definition.yaml"
    definition.write_text(
        yaml.safe_dump(
            {
                "controller_state_contracts_file": registry.name,
                "phases": [
                    phase,
                    {"id": "author", "type": "terminal"},
                    {"id": "blocked", "type": "terminal"},
                    {"id": "done", "type": "terminal"},
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    extension = tmp_path / "extension.yml"
    extension.write_text("provides: {commands: []}\n", encoding="utf-8")
    return definition, extension


def test_phase_graph_parses_explicit_structural_artifact(tmp_path: Path) -> None:
    definition, extension = _write_structural_graph(tmp_path)

    node = PhaseGraph(definition, extension).get("custom-structural")

    assert node.structural_artifact == "feasibility"


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_artifact",
        "unknown_artifact",
        "agent",
        "agents",
        "allowlist",
        "wrong_contract",
        "missing_repair",
        "missing_block",
        "missing_forward",
    ],
)
def test_phase_graph_rejects_malformed_structural_node(
    tmp_path: Path, mutation: str
) -> None:
    definition, extension = _write_structural_graph(tmp_path, mutation)

    with pytest.raises(ControllerContractRegistryError):
        PhaseGraph(definition, extension)


class TestPhaseGraph:
    graph = PhaseGraph(DEFINITION, EXT_YML)

    def test_loads_init_phase(self):
        node = self.graph.get("init")
        assert node.id == "init"

    def test_entry_phase_is_init(self):
        assert self.graph.entry_phase() == "init"

    def test_phase1_discover_type_agent(self):
        node = self.graph.get("phase1-discover")
        assert node.type == "agent"
        assert node.agent == "speckit-echelon-scout"

    def test_unknown_phase_raises(self):
        import pytest
        with pytest.raises(KeyError):
            self.graph.get("does-not-exist")

    def test_phase3_consensus_is_staged_parallel(self):
        node = self.graph.get("phase3-consensus")
        assert node.type == "staged_parallel"
        assert len(node.agents) >= 2

    def test_understanding_runs_in_provider_free_nodes_before_sage(self):
        why2_gate = self.graph.get("phase1-understanding")
        why3_gate = self.graph.get("phase3-understanding")

        assert why2_gate.type == "deterministic_understanding"
        assert why2_gate.understanding_target == "phase1-why2"
        assert why3_gate.type == "deterministic_understanding"
        assert why3_gate.understanding_target == "phase3-consensus"
        assert self.graph.get("phase1-what").transitions[-1]["to"] == why2_gate.id
        assert why2_gate.transitions == [{"to": "phase1-why2", "condition": "always"}]
        tasks_gate = self.graph.get("phase3-tasks-lexicon")
        assert self.graph.get("phase3-plan").transitions[-1]["to"] == tasks_gate.id
        assert tasks_gate.transitions[-1]["to"] == why3_gate.id
        assert why3_gate.transitions == [{"to": "phase3-consensus", "condition": "always"}]

    def test_spec_lexicon_derivation_and_validation_are_separate_nodes(self):
        what = self.graph.get("phase1-what")
        why2 = self.graph.get("phase1-why2")
        derive = self.graph.get("phase1-lexicon-derive")
        lexicon = self.graph.get("phase1-lexicon")

        assert what.transitions == [
            {
                "to": "phase1-investigate",
                "condition": "evidence_resolution_status = pending",
            },
            {"to": "phase1-understanding", "condition": "always"},
        ]
        assert set(what.required_state_updates) == {"evidence_resolution_status"}
        assert set(what.allowed_verdicts) == {"DONE", "FAIL"}
        assert what.evidence_routing == "requests"
        assert why2.transitions[-2] == {
            "to": "phase1-lexicon-derive",
            "condition": (
                "verdict = PASS AND no_CRITICAL_issues "
                "AND quality_gates.pass"
            ),
        }
        assert derive.type == "agent"
        assert derive.agent == "speckit-echelon-lexicon-deriver"
        assert derive.outputs == ["requirements.lexicon.md"]
        assert derive.allowed_state_updates == []
        assert set(derive.allowed_verdicts or []) == {"DONE", "FAIL"}
        assert derive.transitions == [
            {"to": "phase1-lexicon", "condition": "always"},
        ]
        assert lexicon.type == "deterministic_lexicon"
        assert lexicon.lexicon_artifact == "spec"
        assert lexicon.allowed_state_updates == []
        assert lexicon.controller_state_update_keys == {
            "lexicon_evaluation",
            "lexicon_pass",
            "lexicon_attempts",
            "lexicon_findings",
            "lexicon_report",
            "lexicon_warning_waiver",
            "blocked_reason",
        }
        assert lexicon.transitions == [
            {
                "to": "phase1-lexicon-derive",
                "condition": (
                    "lexicon_gate.spec_enabled AND lexicon_evaluation = pending "
                    "AND iteration < max_iterations"
                ),
                "action": "increment_iteration",
            },
            {
                "to": "phase1-lexicon-derive",
                "condition": (
                    "lexicon_gate.spec_enabled AND lexicon_evaluation = failed "
                    "AND lexicon_attempts < lexicon_gate.max_repair_attempts "
                    "AND iteration < max_iterations"
                ),
                "action": "increment_iteration",
            },
            {"to": "checkpoint-assess", "condition": "always"},
        ]

    def test_why2_requires_structured_finding_routes(self):
        why2 = self.graph.get("phase1-why2")

        assert set(why2.required_state_updates) == {
            "evidence_resolution_status",
            "finding_routes",
        }
        assert why2.state_update_enums["evidence_resolution_status"] == [
            "not_required",
            "pending",
        ]
        assert set(why2.allowed_verdicts) == {"PASS", "FAIL", "STOP_AND_ASK"}
        assert why2.evidence_routing == "finding_routes"

    def test_phase_timing_windows_are_controller_metadata(self):
        decide = self.graph.get("phase2-decide")
        specialists = self.graph.get("phase3-specialists")
        plan = self.graph.get("phase3-plan")
        finalize = self.graph.get("phase4-document")

        assert decide.timing_window_start == "phase2-decide"
        assert decide.budget_seconds == 1800
        assert specialists.timing_window_transition == {
            "close": "phase2-decide",
            "open": "phase3-solution",
            "open_budget_seconds": 2400,
        }
        assert plan.timing_window_transition == {
            "close": "phase3-solution",
            "open": "phase4-build",
            "open_budget_seconds": 7200,
        }
        assert finalize.timing_window_transition == {"close": "phase4-build"}

    def test_sage_cannot_write_controller_certified_quality_scores(self):
        why2 = self.graph.get("phase1-why2")
        consensus = self.graph.get("phase3-consensus")
        why3 = next(agent for agent in consensus.agents if agent.get("mode") == "WHY3")

        assert "quality_scores" not in (why2.allowed_state_updates or [])
        assert "quality_scores" not in why3.get("allowed_state_updates", [])
        assert "quality_scores" not in (consensus.allowed_state_updates or [])

    def test_why2_context_pack_uses_authoritative_artifact_paths(self):
        context_pack = set(self.graph.get("phase1-why2").context_pack)

        assert "{spec_dir}/spec.md" in context_pack
        assert "{spec_dir}/assumptions.md" in context_pack
        assert ".specify/memory/constitution.md" in context_pack
        assert "spec.md" not in context_pack
        assert "constitution.md" not in context_pack
        assert "assumptions.md" not in context_pack

    def test_why2_routes_external_evidence_requests_to_phase1_investigate(self):
        why2 = self.graph.get("phase1-why2")
        investigate = self.graph.get("phase1-investigate")

        assert why2.transitions[0] == {
            "to": "phase1-investigate",
            "condition": "evidence_resolution_status = pending",
        }
        assert {"evidence_resolution_status", "evidence_requests"}.issubset(
            why2.allowed_state_updates or []
        )
        assert investigate.type == "agent"
        assert investigate.agent == "speckit-echelon-investigator"
        assert investigate.transitions == [
            {
                "to": "phase1-what",
                "condition": "evidence_resolution_status in [validated, conflicting]",
            },
            {
                "to": "terminal-blocked",
                "condition": "evidence_resolution_status in [inconclusive, access_required]",
            },
        ]

    def test_phase3_consensus_context_packs_cover_spec_plan_and_tasks(self):
        """Consensus agents must receive enough artifacts to validate plan/tasks."""
        node = self.graph.get("phase3-consensus")
        agents = {agent["mode"]: agent for agent in node.agents}

        why3_pack = set(agents["WHY3"]["context_pack"])
        assess2_pack = set(agents["ASSESS2"]["context_pack"])
        plan2_pack = set(agents["PLAN2"]["context_pack"])

        assert {
            "{spec_dir}/spec.md",
            "{spec_dir}/plan.md",
            "{spec_dir}/research.md",
            "{spec_dir}/data-model.md",
            "{spec_dir}/contracts/",
            "{spec_dir}/tasks.md",
            "{spec_dir}/test-strategy.md",
            "{spec_dir}/coverage-map.md",
        }.issubset(why3_pack)

        assert {
            "{spec_dir}/spec.md",
            "{spec_dir}/plan.md",
            "{spec_dir}/research.md",
            "{spec_dir}/data-model.md",
            "{spec_dir}/contracts/",
            "{spec_dir}/tasks.md",
            "{spec_dir}/test-strategy.md",
            "{spec_dir}/coverage-map.md",
            "{spec_dir}/estimates.md",
            "{spec_dir}/mvp-scope.md",
            ".specify/memory/constitution.md",
            "extension/templates/estimates-template.md",
        }.issubset(assess2_pack)

        assert {
            "{spec_dir}/spec.md",
            "{spec_dir}/plan.md",
            "{spec_dir}/research.md",
            "{spec_dir}/data-model.md",
            "{spec_dir}/contracts/",
            "{spec_dir}/tasks.md",
            "{spec_dir}/test-strategy.md",
            "{spec_dir}/coverage-map.md",
            "{spec_dir}/critical-path.md",
            "{spec_dir}/risk-matrix.md",
            "{spec_dir}/dependencies.md",
            "{spec_dir}/implementability-report.md",
            "{spec_dir}/quality-gates.md",
            "{spec_dir}/issues.md",
        }.issubset(plan2_pack)

    def test_phase3_sentinel_receives_all_required_how_and_quality_inputs(self):
        node = self.graph.get("phase3-sentinel")

        assert {
            "spec.md",
            "plan.md",
            "research.md",
            "data-model.md",
            "contracts/",
            "quality-gates.md",
        }.issubset(set(node.context_pack))

    def test_why2_does_not_require_later_test_design_artifacts(self):
        sage = (EXT_ROOT / "extension/agents/exploration/sage.md").read_text(
            encoding="utf-8"
        )

        assert "Flakiness Management Validation (WHY3 only)" in sage
        assert "WHY2 must not require `test-strategy.md` or `coverage-map.md`" in sage

    def test_sentinel_does_not_require_plan_tasks_before_plan_phase(self):
        sentinel_phase = (
            EXT_ROOT / "extension/workflow/phases/phase3-sentinel.md"
        ).read_text(encoding="utf-8")

        assert "target-owned task" not in sentinel_phase
        assert "`task_ids: []`" in sentinel_phase
        assert "Always proceed with reduced confidence" not in sentinel_phase
        assert "phase failure" in sentinel_phase

    def test_phase1_discover_has_pre_dispatch(self):
        node = self.graph.get("phase1-discover")
        assert len(node.pre_dispatch) > 0

    def test_phase1_discover_preserves_declared_outputs(self):
        node = self.graph.get("phase1-discover")
        assert "glossary.md" in node.outputs
        assert "mental-model.md" in node.outputs

    def test_phase1_what_reads_fresh_user_clarifications_from_run_staging(self):
        node = self.graph.get("phase1-what")

        assert "{staging_dir}/user-clarifications.md" in node.context_pack

    def test_phase1_what_receives_evidence_resolution_artifacts(self):
        context_pack = set(self.graph.get("phase1-what").context_pack)

        assert "{spec_dir}/evidence-resolution.md" in context_pack
        assert "{spec_dir}/evidence-grades.md" in context_pack

    def test_phase1_modeler_loads_node_condition_and_greenfield_skip(self):
        node = self.graph.get("phase1-modeler")
        assert node.condition == "mode = brownfield"
        assert node.on_greenfield == {"action": "skip_agent_proceed_to_next"}

    def test_transitions_present(self):
        node = self.graph.get("phase1-discover")
        assert len(node.transitions) > 0
        assert all("to" in t for t in node.transitions)
        assert all("condition" in t for t in node.transitions)

    def test_agent_file_lookup(self):
        path = self.graph.agent_file("speckit-echelon-scout")
        assert path is not None
        assert "scout" in path

    def test_all_agent_phases_have_resolvable_files(self):
        missing = []
        for phase_id in self.graph.all_phase_ids():
            node = self.graph.get(phase_id)
            if node.type == "agent" and node.agent:
                rel = self.graph.agent_file(node.agent)
                if rel:
                    full = EXT_ROOT / "extension" / rel
                    if not full.exists():
                        missing.append((phase_id, rel))
        assert missing == [], f"Agent files missing: {missing}"


def test_chief_registered_in_extension():
    """CHIEF must be registered in extension.yml so phase_graph resolves it."""
    import yaml
    from pathlib import Path
    ext = yaml.safe_load(
        (Path(__file__).parent.parent.parent / "extension/extension.yml").read_text()
    )
    commands = ext.get("provides", {}).get("commands", [])
    names = [c["name"] for c in commands]
    assert "speckit.echelon.chief" in names, "speckit.echelon.chief not in extension.yml provides.commands"
    chief = next(c for c in commands if c["name"] == "speckit.echelon.chief")
    assert chief["file"] == "agents/control/chief.md"
    assert chief["behavior"]["execution"] == "agent"


def test_phase1_constitution_uses_chief():
    """phase1-constitution must dispatch CHIEF, not COMMANDER."""
    graph = PhaseGraph(DEFINITION, EXT_YML)
    node = graph.get("phase1-constitution")
    assert node.type == "agent", f"Expected type=agent, got {node.type!r}"
    assert node.agent == "speckit-echelon-chief", f"Expected speckit-echelon-chief, got {node.agent!r}"
    # Must resolve to an actual file
    rel = graph.agent_file("speckit-echelon-chief")
    assert rel is not None, "speckit-echelon-chief not resolved by agent_file()"
    assert rel == "agents/control/chief.md"


def test_phase1_constitution_context_pack_has_staging_artifacts():
    """phase1-constitution must include all 5 staging artifacts in context_pack."""
    graph = PhaseGraph(DEFINITION, EXT_YML)
    node = graph.get("phase1-constitution")
    pack = " ".join(node.context_pack)
    assert "glossary" in pack
    assert "mental-model" in pack
    assert "boundaries" in pack
    assert "assumptions" in pack
    assert "user-intent" in pack


def test_phase1_context_packs_include_generated_context_files():
    graph = PhaseGraph(DEFINITION, EXT_YML)

    discover_pack = set(graph.get("phase1-discover").context_pack)
    synthesizer_pack = set(graph.get("phase1-synthesizer").context_pack)
    modeler_pack = set(graph.get("phase1-modeler").context_pack)
    what_pack = set(graph.get("phase1-what").context_pack)

    assert "{context_dir}/prior-spec-context.md" in discover_pack
    assert "{context_dir}/stale-memory-report.md" in discover_pack

    expected_full_pack = {
        "{context_dir}/prior-spec-context.md",
        "{context_dir}/current-feature-context.md",
        "{context_dir}/stale-memory-report.md",
    }
    assert expected_full_pack.issubset(synthesizer_pack)
    assert expected_full_pack.issubset(modeler_pack)
    assert expected_full_pack.issubset(what_pack)

    specialists = graph.get("phase3-specialists")
    specialist_packs = {
        agent["id"]: set(agent.get("context_pack", []))
        for agent in specialists.agents
        if agent["id"] in {"speckit-echelon-guardian", "speckit-echelon-investigator"}
    }
    assert expected_full_pack.issubset(specialist_packs["speckit-echelon-guardian"])
    assert expected_full_pack.issubset(
        specialist_packs["speckit-echelon-investigator"]
    )


def test_phase_graph_preserves_allowed_state_updates(tmp_path: Path):
    definition = tmp_path / "definition.yaml"
    extension_yml = tmp_path / "extension.yml"

    definition.write_text(
        """
phases:
  - id: phase1-discover
    type: agent
    agent: speckit-echelon-scout
    outputs:
      - spec.md
    allowed_state_updates:
      - quality_scores
      - golddigger_requests
    required_state_updates:
      - quality_scores
    state_update_types:
      quality_scores: quality_scores
    state_update_enums:
      golddigger_requests: [none, needed]
    allowed_verdicts: [PASS, FAIL, BLOCKED]
    transitions:
      - to: done
        condition: always
""",
        encoding="utf-8",
    )
    extension_yml.write_text("provides: {commands: []}\n", encoding="utf-8")

    graph = PhaseGraph(definition, extension_yml)

    assert graph.get("phase1-discover").allowed_state_updates == [
        "quality_scores",
        "golddigger_requests",
    ]
    assert graph.get("phase1-discover").required_state_updates == ["quality_scores"]
    assert graph.get("phase1-discover").state_update_types == {
        "quality_scores": "quality_scores"
    }
    assert graph.get("phase1-discover").state_update_enums == {
        "golddigger_requests": ["none", "needed"]
    }
    assert graph.get("phase1-discover").allowed_verdicts == [
        "PASS",
        "FAIL",
        "BLOCKED",
    ]


def _write_controller_boundary_graph(
    tmp_path: Path,
    *,
    allowlist: object,
    nested_field: str | None,
) -> tuple[Path, Path]:
    """Write one direct-PhaseGraph controller-boundary fixture."""

    registry = tmp_path / "contracts.yaml"
    registry.write_bytes(
        (
            EXT_ROOT
            / "extension/workflow/controller-state-contracts.yaml"
        ).read_bytes()
    )
    phase: dict[str, object] = {
        "id": "start",
        "type": "agent",
        "allowed_state_updates": [],
        "controller_state_contract": "spec_lexicon",
        "transitions": [{"to": "DONE", "condition": "always"}],
    }
    if nested_field is None:
        phase["allowed_state_updates"] = allowlist
    else:
        phase["type"] = "staged_parallel"
        phase[nested_field] = [
            {"id": "nested", "allowed_state_updates": allowlist}
        ]
    definition = tmp_path / "definition.yaml"
    definition.write_text(
        yaml.safe_dump(
            {
                "controller_state_contracts_file": registry.name,
                "phases": [phase, {"id": "DONE", "type": "terminal"}],
            }
        ),
        encoding="utf-8",
    )
    extension_yml = tmp_path / "extension.yml"
    extension_yml.write_text(
        "provides: {commands: []}\n",
        encoding="utf-8",
    )
    return definition, extension_yml


@pytest.mark.parametrize("nested_field", (None, "agents", "pre_dispatch"))
def test_phase_graph_rejects_null_allowlist_for_controller_boundary(
    tmp_path: Path,
    nested_field: str | None,
) -> None:
    definition, extension_yml = _write_controller_boundary_graph(
        tmp_path,
        allowlist=None,
        nested_field=nested_field,
    )

    with pytest.raises(
        ControllerContractRegistryError,
        match="allowed_state_updates.*list",
    ):
        PhaseGraph(definition, extension_yml)


@pytest.mark.parametrize("nested_field", (None, "agents", "pre_dispatch"))
@pytest.mark.parametrize(
    "unsafe_allowlist",
    ([123], [""], ["lexicon_pass"]),
)
def test_phase_graph_rejects_unsafe_controller_boundary_allowlist(
    tmp_path: Path,
    nested_field: str | None,
    unsafe_allowlist: list[object],
) -> None:
    definition, extension_yml = _write_controller_boundary_graph(
        tmp_path,
        allowlist=unsafe_allowlist,
        nested_field=nested_field,
    )

    with pytest.raises(ControllerContractRegistryError):
        PhaseGraph(definition, extension_yml)


def test_phase3_consensus_declares_per_agent_result_contracts():
    graph = PhaseGraph(DEFINITION, EXT_YML)
    node = graph.get("phase3-consensus")
    contracts = {entry["mode"]: entry for entry in node.agents}

    assert contracts["WHY3"]["allowed_state_updates"] == []
    assert contracts["WHY3"].get("required_state_updates", []) == []
    assert contracts["ASSESS2"]["allowed_state_updates"] == [
        "gate_decision",
        "phase_recommendation",
        "implementability_metrics",
    ]
    assert contracts["PLAN2"]["allowed_state_updates"] == []
    assert "total_tasks" not in contracts["PLAN2"]["allowed_state_updates"]


def test_phase2_governance_verdicts_are_controller_owned():
    graph = PhaseGraph(DEFINITION, EXT_YML)
    gates = {
        "phase2-decide": "feasibility_verdict",
        "phase2-tracker-alignment": "intent_alignment_verdict",
    }

    for phase_id, pass_key in gates.items():
        node = graph.get(phase_id)
        assert pass_key not in (node.allowed_state_updates or [])
        assert pass_key in node.controller_state_update_keys
        assert "governance_gate_exhausted" not in node.controller_state_update_keys


def test_phase1_lexicon_reserves_verdict_fields_for_the_controller():
    graph = PhaseGraph(DEFINITION, EXT_YML)
    node = graph.get("phase1-lexicon")

    controller_fields = {
        "lexicon_evaluation",
        "lexicon_pass",
        "lexicon_attempts",
        "lexicon_findings",
        "lexicon_report",
        "lexicon_warning_waiver",
        "blocked_reason",
    }
    assert controller_fields.isdisjoint(node.allowed_state_updates or [])
    assert node.controller_state_update_keys == controller_fields


def test_tasks_lexicon_runs_in_two_visible_provider_free_nodes():
    graph = PhaseGraph(DEFINITION, EXT_YML)
    first = graph.get("phase3-tasks-lexicon")
    second = graph.get("phase3-consensus-tasks-lexicon")

    assert graph.get("phase3-plan").transitions == [
        {"to": first.id, "condition": "always"}
    ]
    assert graph.get("phase3-consensus").transitions == [
        {"to": second.id, "condition": "always"}
    ]
    controller_fields = {
        "tasks_lexicon_action",
        "tasks_lexicon_pass",
        "tasks_lexicon_attempts",
        "tasks_lexicon_findings",
        "tasks_lexicon_report",
        "blocked_reason",
    }
    for node in (first, second):
        assert node.type == "deterministic_lexicon"
        assert node.lexicon_artifact == "tasks"
        assert node.allowed_state_updates == []
        assert node.controller_state_update_keys == controller_fields


def test_shared_controller_contracts_are_compiled_once() -> None:
    graph = PhaseGraph(DEFINITION, EXT_YML)
    first = graph.get("phase3-tasks-lexicon").controller_state_contract
    second = graph.get("phase3-consensus-tasks-lexicon").controller_state_contract

    assert first is second
    assert first is graph.controller_contract("tasks_lexicon")
    assert first.name == "tasks_lexicon"
    assert first.state_update_keys == {
        "tasks_lexicon_action",
        "tasks_lexicon_pass",
        "tasks_lexicon_attempts",
        "tasks_lexicon_findings",
        "tasks_lexicon_report",
        "blocked_reason",
    }

    understanding_first = graph.get(
        "phase1-understanding"
    ).controller_state_contract
    understanding_second = graph.get(
        "phase3-understanding"
    ).controller_state_contract
    assert understanding_first is understanding_second
    assert understanding_first is graph.controller_contract("understanding")
    assert understanding_first.name == "understanding"
    assert understanding_first.state_update_keys == {
        "quality_scores",
        "understanding_evidence",
        "blocked_reason",
    }


def test_production_contracts_own_exact_existing_controller_field_inventory() -> None:
    graph = PhaseGraph(DEFINITION, EXT_YML)
    expected = {
        "spec_lexicon": {
            "lexicon_evaluation",
            "lexicon_pass",
            "lexicon_attempts",
            "lexicon_findings",
            "lexicon_report",
            "lexicon_warning_waiver",
            "blocked_reason",
        },
        "tasks_lexicon": {
            "tasks_lexicon_action",
            "tasks_lexicon_pass",
            "tasks_lexicon_attempts",
            "tasks_lexicon_findings",
            "tasks_lexicon_report",
            "blocked_reason",
        },
        "understanding": {
            "quality_scores",
            "understanding_evidence",
            "blocked_reason",
        },
        "phase1_quality_certificate": {
            "spec_quality_certificate",
        },
        "feasibility_structural": {
            "structural_action",
            "feasibility_structural_pass",
            "feasibility_structural_attempts",
            "feasibility_structural_findings",
            "feasibility_structural_report",
            "governance_gate_exhausted",
        },
        "intent_alignment_structural": {
            "structural_action",
            "intent_alignment_check_structural_pass",
            "intent_alignment_check_structural_attempts",
            "intent_alignment_check_structural_findings",
            "intent_alignment_check_structural_report",
            "governance_gate_exhausted",
        },
    }

    assert {
        name: graph.controller_contract(name).state_update_keys
        for name in expected
    } == expected
    assert len(set().union(*expected.values())) == 25


def test_production_contracts_reject_incomplete_success_results() -> None:
    graph = PhaseGraph(DEFINITION, EXT_YML)

    assert validate_controller_result(
        graph.controller_contract("spec_lexicon"),
        "DONE",
        {},
    )
    assert validate_controller_result(
        graph.controller_contract("understanding"),
        "DONE",
        {},
    )


@pytest.mark.parametrize(
    ("contract_name", "verdict", "updates"),
    [
        (
            "spec_lexicon",
            "DONE",
            {"lexicon_evaluation": "pending", "lexicon_attempts": 0},
        ),
        (
            "spec_lexicon",
            "DONE",
            {
                "lexicon_evaluation": "passed",
                "lexicon_attempts": 0,
                "lexicon_pass": True,
                "lexicon_findings": 0,
                "lexicon_report": "spec-lexicon-report.json",
            },
        ),
        (
            "tasks_lexicon",
            "DONE",
            {
                "tasks_lexicon_action": "block",
                "tasks_lexicon_pass": False,
                "tasks_lexicon_attempts": 1,
                "tasks_lexicon_findings": 1,
                "tasks_lexicon_report": "tasks-lexicon-report.json",
                "blocked_reason": "lexicon_gate_exhausted",
            },
        ),
        (
            "understanding",
            "DONE",
            {
                "quality_scores": [{"pass": True, "source": "harness"}],
                "understanding_evidence": {
                    "phase": "phase1-why2",
                    "iteration": 0,
                    "status": "completed",
                    "path": "understanding.json",
                    "digest": "abc123",
                    "pass": True,
                    "failing_gates": [],
                    "error": None,
                },
            },
        ),
        (
            "understanding",
            "BLOCKED",
            {
                "understanding_evidence": {
                    "phase": "phase1-why2",
                    "iteration": 0,
                    "status": "error",
                    "path": None,
                    "digest": None,
                    "pass": None,
                    "failing_gates": [],
                    "error": "analysis failed",
                },
                "blocked_reason": "analysis failed",
            },
        ),
        (
            "feasibility_structural",
            "PASS",
            {
                "structural_action": "proceed",
                "feasibility_structural_pass": True,
                "feasibility_structural_attempts": 0,
                "feasibility_structural_findings": 0,
            },
        ),
        (
            "intent_alignment_structural",
            "WARN",
            {
                "structural_action": "proceed_with_warning",
                "intent_alignment_check_structural_pass": False,
                "intent_alignment_check_structural_attempts": 1,
                "intent_alignment_check_structural_findings": 2,
                "intent_alignment_check_structural_report": "intent-report.json",
                "governance_gate_exhausted": "intent-alignment-check",
            },
        ),
    ],
)
def test_production_contracts_accept_valid_semantic_branches(
    contract_name: str,
    verdict: str,
    updates: dict[str, object],
) -> None:
    graph = PhaseGraph(DEFINITION, EXT_YML)

    assert not validate_controller_result(
        graph.controller_contract(contract_name),
        verdict,
        updates,
    )


@pytest.mark.parametrize(
    ("contract_name", "updates"),
    [
        (
            "spec_lexicon",
            {
                "lexicon_evaluation": "pending",
                "lexicon_attempts": 0,
                "lexicon_pass": False,
            },
        ),
        (
            "spec_lexicon",
            {
                "lexicon_evaluation": "passed",
                "lexicon_attempts": 0,
                "lexicon_pass": True,
                "lexicon_findings": 1,
                "lexicon_report": "report.json",
            },
        ),
        (
            "tasks_lexicon",
            {
                "tasks_lexicon_action": "proceed",
                "tasks_lexicon_pass": False,
                "tasks_lexicon_attempts": 0,
                "tasks_lexicon_findings": 0,
            },
        ),
        (
            "tasks_lexicon",
            {
                "tasks_lexicon_action": "block",
                "tasks_lexicon_pass": False,
                "tasks_lexicon_attempts": 1,
                "tasks_lexicon_findings": 0,
            },
        ),
        (
            "understanding",
            {
                "quality_scores": [{"pass": "yes"}],
                "understanding_evidence": {
                    "status": "completed",
                    "iteration": 0,
                    "digest": "abc",
                    "path": "report.json",
                    "pass": True,
                },
            },
        ),
        (
            "understanding",
            {
                "understanding_evidence": {
                    "status": "error",
                    "iteration": 0,
                    "error": "analysis failed",
                },
            },
        ),
        (
            "feasibility_structural",
            {
                "feasibility_structural_pass": False,
                "feasibility_structural_attempts": 1,
                "feasibility_structural_findings": 1,
            },
        ),
        (
            "intent_alignment_structural",
            {
                "intent_alignment_check_structural_pass": False,
                "intent_alignment_check_structural_attempts": 1,
                "governance_gate_exhausted": "feasibility",
            },
        ),
    ],
)
def test_production_contracts_reject_semantic_invariant_violations(
    contract_name: str,
    updates: dict[str, object],
) -> None:
    graph = PhaseGraph(DEFINITION, EXT_YML)

    assert validate_controller_result(
        graph.controller_contract(contract_name),
        "DONE",
        updates,
    )


@pytest.mark.parametrize(
    ("contract_name", "verdict", "updates"),
    [
        (
            "understanding",
            "DONE",
            {
                "understanding_evidence": {
                    "status": "error",
                    "iteration": 0,
                    "error": "analysis failed",
                },
                "blocked_reason": "analysis failed",
            },
        ),
        ("understanding", "BLOCKED", {}),
        (
            "understanding",
            "BLOCKED",
            {
                "quality_scores": [{"pass": True}],
                "understanding_evidence": {
                    "status": "completed",
                    "iteration": 0,
                    "digest": "abc",
                    "path": "report.json",
                    "pass": True,
                },
            },
        ),
        ("spec_lexicon", "BLOCKED", {}),
        ("tasks_lexicon", "BLOCKED", {}),
        (
            "spec_lexicon",
            "DONE",
            {
                "lexicon_evaluation": "pending",
                "lexicon_attempts": 0,
                "lexicon_findings": 1,
            },
        ),
        (
            "feasibility_structural",
            "PASS",
            {
                "feasibility_structural_pass": True,
                "feasibility_structural_attempts": 3,
                "governance_gate_exhausted": "feasibility",
            },
        ),
        (
            "intent_alignment_structural",
            "ALIGNED",
            {
                "intent_alignment_check_structural_pass": True,
                "intent_alignment_check_structural_attempts": 3,
                "governance_gate_exhausted": "intent-alignment-check",
            },
        ),
    ],
    ids=[
        "understanding-success-with-error-evidence",
        "understanding-empty-blocked",
        "understanding-blocked-with-completed-evidence",
        "spec-lexicon-empty-blocked",
        "tasks-lexicon-empty-blocked",
        "spec-lexicon-pending-with-findings",
        "feasibility-pass-with-exhaustion",
        "alignment-pass-with-exhaustion",
    ],
)
def test_production_contracts_fail_closed_across_discriminator_branches(
    contract_name: str,
    verdict: str,
    updates: dict[str, object],
) -> None:
    graph = PhaseGraph(DEFINITION, EXT_YML)

    assert validate_controller_result(
        graph.controller_contract(contract_name),
        verdict,
        updates,
    )


def test_controller_node_outputs_contain_artifacts_only() -> None:
    graph = PhaseGraph(DEFINITION, EXT_YML)

    assert graph.get("phase1-lexicon").outputs == [
        "spec-lexicon-report.json",
    ]
    for phase_id in (
        "phase3-tasks-lexicon",
        "phase3-consensus-tasks-lexicon",
    ):
        assert graph.get(phase_id).outputs == [
            "tasks-lexicon-report.json",
        ]


def test_phase_graph_rejects_unknown_controller_contract(tmp_path: Path) -> None:
    registry = tmp_path / "contracts.yaml"
    registry.write_text(
        yaml.safe_dump({
            "schema_version": 1,
            "contracts": {
                "known": {
                    "$schema": "https://json-schema.org/draft/2020-12/schema",
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["verdict", "state_updates"],
                    "properties": {
                        "verdict": {"type": "string"},
                        "state_updates": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {"known": {"type": "boolean"}},
                        },
                    },
                }
            },
        }),
        encoding="utf-8",
    )
    definition = tmp_path / "definition.yaml"
    definition.write_text(
        yaml.safe_dump({
            "controller_state_contracts_file": registry.name,
            "phases": [{
                "id": "start",
                "controller_state_contract": "missing",
            }],
        }),
        encoding="utf-8",
    )
    extension_yml = tmp_path / "extension.yml"
    extension_yml.write_text("provides: {commands: []}\n", encoding="utf-8")

    with pytest.raises(
        ControllerContractRegistryError,
        match="unknown controller state contract 'missing'",
    ):
        PhaseGraph(definition, extension_yml)


@pytest.mark.parametrize(
    ("phase_id", "expected_contract"),
    sorted(REQUIRED_CONTROLLER_CONTRACTS.items()),
)
@pytest.mark.parametrize("mutation", ["missing", "mismatched"])
def test_phase_graph_requires_exact_contract_for_controller_role(
    tmp_path: Path,
    phase_id: str,
    expected_contract: str,
    mutation: str,
) -> None:
    raw = yaml.safe_load(DEFINITION.read_text(encoding="utf-8"))
    phase = next(item for item in raw["phases"] if item["id"] == phase_id)
    if mutation == "missing":
        phase.pop("controller_state_contract")
    else:
        phase["controller_state_contract"] = (
            "tasks_lexicon"
            if expected_contract != "tasks_lexicon"
            else "understanding"
        )
    definition = tmp_path / "definition.yaml"
    definition.write_text(
        yaml.safe_dump(raw, sort_keys=False),
        encoding="utf-8",
    )
    registry = DEFINITION.parent / "controller-state-contracts.yaml"
    (tmp_path / registry.name).write_text(
        registry.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    with pytest.raises(
        ControllerContractRegistryError,
        match=(
            f"phase {phase_id!r} requires controller state contract "
            f"{expected_contract!r}"
        ),
    ):
        PhaseGraph(definition, EXT_YML)


def test_phase_graph_requires_registry_for_controller_producing_type(
    tmp_path: Path,
) -> None:
    definition = tmp_path / "definition.yaml"
    definition.write_text(
        yaml.safe_dump(
            {
                "phases": [
                    {
                        "id": "custom-understanding",
                        "type": "deterministic_understanding",
                        "allowed_state_updates": [],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        ControllerContractRegistryError,
        match="controller-producing phases require",
    ):
        PhaseGraph(definition, EXT_YML)


def test_provider_nodes_do_not_own_tasks_lexicon_state():
    graph = PhaseGraph(DEFINITION, EXT_YML)
    plan = graph.get("phase3-plan")
    consensus = graph.get("phase3-consensus")

    assert not {
        key
        for key in (plan.allowed_state_updates or [])
        if key.startswith("tasks_lexicon_")
    }
    assert not {
        key
        for key in consensus.controller_state_update_keys
        if key.startswith("tasks_lexicon_")
    }
    plan2 = next(entry for entry in consensus.agents if entry["mode"] == "PLAN2")
    assert not {
        key
        for key in plan2["allowed_state_updates"]
        if key.startswith("tasks_lexicon_")
    }


def test_experimental_artifact_quality_phases_are_registered():
    graph = PhaseGraph(DEFINITION, EXT_YML)

    expected = {
        "phase-exp-constitution-quality": {
            "agent": "speckit-echelon-chief",
            "updates": {
                "constitution_quality_pass",
                "constitution_quality_attempts",
                "constitution_quality_findings",
                "blocked_reason",
                "status",
            },
        },
        "phase-exp-tasks-quality": {
            "agent": "speckit-echelon-orchestrator",
            "updates": {
                "tasks_quality_pass",
                "tasks_quality_attempts",
                "tasks_quality_findings",
                "blocked_reason",
                "status",
            },
        },
        "phase-exp-adr-quality": {
            "agent": "speckit-echelon-architect",
            "updates": {
                "adr_quality_pass",
                "adr_quality_attempts",
                "adr_quality_findings",
                "blocked_reason",
                "status",
            },
        },
    }

    for phase_id, contract in expected.items():
        node = graph.get(phase_id)
        assert node.type == "agent"
        assert node.agent == contract["agent"]
        assert set(node.allowed_state_updates or []) == contract["updates"]
        assert node.transitions == [{"to": "done", "condition": "always"}]
