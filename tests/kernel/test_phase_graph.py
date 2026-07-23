"""Tests for PhaseGraph — loads workflow/definition.yaml."""
import sys
from pathlib import Path

EXT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(EXT_ROOT) not in sys.path:
    sys.path.insert(0, str(EXT_ROOT))

from harness.phase_graph import PhaseGraph

DEFINITION = EXT_ROOT / "extension/workflow/definition.yaml"
EXT_YML = EXT_ROOT / "extension/extension.yml"


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
        assert self.graph.get("phase1-lexicon").transitions[-1]["to"] == why2_gate.id
        assert why2_gate.transitions == [{"to": "phase1-why2", "condition": "always"}]
        assert self.graph.get("phase3-plan").transitions[-1]["to"] == why3_gate.id
        assert why3_gate.transitions == [{"to": "phase3-consensus", "condition": "always"}]

    def test_spec_lexicon_runs_in_visible_provider_free_node(self):
        what = self.graph.get("phase1-what")
        lexicon = self.graph.get("phase1-lexicon")

        assert what.transitions == [{"to": "phase1-lexicon", "condition": "always"}]
        assert lexicon.type == "deterministic_lexicon"
        assert lexicon.lexicon_artifact == "spec"
        assert lexicon.allowed_state_updates == []
        assert set(lexicon.controller_state_updates) == {
            "lexicon_evaluation",
            "lexicon_pass",
            "lexicon_attempts",
            "lexicon_findings",
            "lexicon_report",
            "lexicon_warning_waiver",
        }
        assert lexicon.transitions == [
            {
                "to": "phase1-what",
                "condition": (
                    "lexicon_gate.enabled AND lexicon_evaluation = pending "
                    "AND iteration < max_iterations"
                ),
                "action": "increment_iteration",
            },
            {
                "to": "phase1-what",
                "condition": (
                    "lexicon_gate.enabled AND lexicon_evaluation = failed "
                    "AND lexicon_attempts < lexicon_gate.max_repair_attempts "
                    "AND iteration < max_iterations"
                ),
                "action": "increment_iteration",
            },
            {"to": "phase1-understanding", "condition": "always"},
        ]

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
    assert contracts["PLAN2"]["allowed_state_updates"] == [
        "tasks_lexicon_attempts",
    ]
    assert "total_tasks" not in contracts["PLAN2"]["allowed_state_updates"]


def test_phase2_governance_verdicts_are_controller_owned():
    graph = PhaseGraph(DEFINITION, EXT_YML)
    gates = {
        "phase2-decide": "feasibility_structural_pass",
        "phase2-tracker-alignment": "intent_alignment_check_structural_pass",
    }

    for phase_id, pass_key in gates.items():
        node = graph.get(phase_id)
        assert pass_key not in (node.allowed_state_updates or [])
        assert pass_key in node.controller_state_updates
        assert "governance_gate_exhausted" in node.controller_state_updates


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
    }
    assert controller_fields.isdisjoint(node.allowed_state_updates or [])
    assert set(node.controller_state_updates) == controller_fields


def test_phase3_plan_reserves_tasks_lexicon_verdict_for_the_controller():
    graph = PhaseGraph(DEFINITION, EXT_YML)
    node = graph.get("phase3-plan")

    assert "tasks_lexicon_attempts" in node.allowed_state_updates
    assert "tasks_lexicon_pass" not in node.allowed_state_updates
    assert node.controller_state_updates == [
        "tasks_lexicon_pass",
        "tasks_lexicon_findings",
        "tasks_lexicon_report",
    ]


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
