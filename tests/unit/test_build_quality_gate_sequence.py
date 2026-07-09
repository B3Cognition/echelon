from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
DEFINITION = ROOT / "extension" / "workflow" / "definition.yaml"
COMMANDER = ROOT / "extension" / "agents" / "control" / "commander.md"
BUILD_COMMAND = ROOT / "extension" / "commands" / "echelon.build.md"
BUILD_IMPLEMENT = ROOT / "extension" / "workflow" / "phases" / "build-2-implement.md"


def _workflow_nodes() -> dict[str, dict]:
    data = yaml.safe_load(DEFINITION.read_text(encoding="utf-8"))
    return {node["id"]: node for node in data["phases"]}


def test_build_quality_gate_graph_is_sequential() -> None:
    nodes = _workflow_nodes()

    assert nodes["build-3-spec-guard"]["type"] == "agent"
    assert nodes["build-4-code-review"]["type"] == "agent"
    assert nodes["build-5-test-guard"]["type"] == "agent"
    assert nodes["build-3-spec-guard"]["transitions"][0]["to"] == "build-4-code-review"
    assert nodes["build-4-code-review"]["transitions"][0]["to"] == "build-5-test-guard"
    assert nodes["build-5-test-guard"]["transitions"][0]["to"] == "build-6-progress"


def test_build_quality_gate_prompt_contract_forbids_parallel_or_vacuity_skips() -> None:
    commander_text = COMMANDER.read_text(encoding="utf-8")
    build_command_text = BUILD_COMMAND.read_text(encoding="utf-8")
    build_text = BUILD_IMPLEMENT.read_text(encoding="utf-8")
    combined = f"{build_command_text}\n{build_text}"

    assert "Build Quality Gate Sequencing" not in commander_text
    assert "skip CODE REVIEWER/TEST GUARDIAN by vacuity" not in commander_text
    assert (
        "When running under `echelon delivery run`, follow build gate workflow transitions sequentially"
        in build_command_text
    )
    assert "Quality gates are sequential hard gates, not a parallel batch" in combined
    assert (
        "NEVER dispatch SPEC GUARD, CODE REVIEWER, and TEST GUARDIAN in one parallel batch"
        in combined
    )
    assert "NEVER skip CODE REVIEWER or TEST GUARDIAN by vacuity" in combined
    assert "workflow-approved skip" in combined
