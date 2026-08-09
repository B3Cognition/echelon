from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
EXTENSION = ROOT / "extension" / "extension.yml"
CONFIG_TEMPLATE = ROOT / "extension" / "config-template.yml"


def _commands_by_name() -> dict[str, dict]:
    data = yaml.safe_load(EXTENSION.read_text(encoding="utf-8"))
    return {entry["name"]: entry for entry in data["provides"]["commands"]}


def test_cost_tuned_agents_do_not_request_strong_capability() -> None:
    commands = _commands_by_name()

    expected = {
        "echelon.checkpoint": "balanced",
        "echelon.tracker": "balanced",
        "echelon.scout": "balanced",
        "echelon.synthesizer": "balanced",
        "echelon.modeler": "balanced",
        "echelon.validator": "balanced",
        "echelon.sentinel": "balanced",
        "echelon.benchmark": "balanced",
        "echelon.advocate": "balanced",
        "echelon.oracle": "balanced",
        "echelon.maverick": "balanced",
        "echelon.cicd": "balanced",
        "echelon.harness-init": "balanced",
        "echelon.re-analyzer": "balanced",
        "echelon.re-specifier": "balanced",
        "echelon.re-verifier": "balanced",
        "echelon.re-expander": "balanced",
        "echelon.re-validator": "balanced",
        "echelon.re-constituter": "balanced",
        "echelon.re-planner": "balanced",
        "echelon.re-tasker": "balanced",
        "echelon.re-checklister": "fast",
    }

    for name, capability in expected.items():
        assert commands[name]["behavior"]["capability"] == capability


def test_high_risk_agents_keep_strong_capability() -> None:
    commands = _commands_by_name()

    for name in [
        "echelon.commander",
        "echelon.strategist",
        "echelon.cartographer",
        "echelon.sage",
        "echelon.gatekeeper",
        "echelon.architect",
        "echelon.orchestrator",
        "echelon.investigator",
        "echelon.guardian",
        "echelon.implementer",
        "echelon.code-reviewer",
        "echelon.engineering-manager",
        "echelon.change-controller",
        "echelon.debugger",
        "echelon.harness-run",
        "echelon.harness-resume",
    ]:
        assert commands[name]["behavior"]["capability"] == "strong"


def test_runtime_model_config_covers_workflow_tiers() -> None:
    data = yaml.safe_load(CONFIG_TEMPLATE.read_text(encoding="utf-8"))

    models = data["execution"]["models"]
    assert models["re_extraction"] == "sonnet"
    assert models["re_planning"] == "sonnet"
