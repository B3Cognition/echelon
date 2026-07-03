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

    def test_phase3_consensus_context_packs_cover_spec_plan_and_tasks(self):
        """Consensus agents must receive enough artifacts to validate plan/tasks."""
        node = self.graph.get("phase3-consensus")
        agents = {agent["mode"]: agent for agent in node.agents}

        why3_pack = set(agents["WHY3"]["context_pack"])
        assess2_pack = set(agents["ASSESS2"]["context_pack"])
        plan2_pack = set(agents["PLAN2"]["context_pack"])

        assert {
            "spec.md",
            "plan.md",
            "research.md",
            "data-model.md",
            "contracts/",
            "tasks.md",
            "test-strategy.md",
            "coverage-map.md",
        }.issubset(why3_pack)

        assert {
            "spec.md",
            "plan.md",
            "research.md",
            "data-model.md",
            "contracts/",
            "tasks.md",
            "test-strategy.md",
            "coverage-map.md",
            "estimates.md",
            "mvp-scope.md",
            "constitution.md",
        }.issubset(assess2_pack)

        assert {
            "spec.md",
            "plan.md",
            "research.md",
            "data-model.md",
            "contracts/",
            "tasks.md",
            "test-strategy.md",
            "coverage-map.md",
            "critical-path.md",
            "risk-matrix.md",
            "dependencies.md",
            "implementability-report.md",
            "quality-gates.md",
            "issues.md",
        }.issubset(plan2_pack)

    def test_phase1_discover_has_pre_dispatch(self):
        node = self.graph.get("phase1-discover")
        assert len(node.pre_dispatch) > 0

    def test_phase1_discover_preserves_declared_outputs(self):
        node = self.graph.get("phase1-discover")
        assert "glossary.md" in node.outputs
        assert "mental-model.md" in node.outputs

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
