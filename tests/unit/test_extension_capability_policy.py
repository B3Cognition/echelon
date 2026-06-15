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
        "speckit.echelon.checkpoint": "balanced",
        "speckit.echelon.tracker": "balanced",
        "speckit.echelon.scout": "balanced",
        "speckit.echelon.synthesizer": "balanced",
        "speckit.echelon.modeler": "balanced",
        "speckit.echelon.validator": "balanced",
        "speckit.echelon.sentinel": "balanced",
        "speckit.echelon.benchmark": "balanced",
        "speckit.echelon.advocate": "balanced",
        "speckit.echelon.oracle": "balanced",
        "speckit.echelon.maverick": "balanced",
        "speckit.echelon.cicd": "balanced",
        "speckit.echelon.harness-init": "balanced",
        "speckit.echelon.re-analyzer": "balanced",
        "speckit.echelon.re-specifier": "balanced",
        "speckit.echelon.re-verifier": "balanced",
        "speckit.echelon.re-expander": "balanced",
        "speckit.echelon.re-validator": "balanced",
        "speckit.echelon.re-constituter": "balanced",
        "speckit.echelon.re-planner": "balanced",
        "speckit.echelon.re-tasker": "balanced",
        "speckit.echelon.re-checklister": "fast",
    }

    for name, capability in expected.items():
        assert commands[name]["behavior"]["capability"] == capability


def test_high_risk_agents_keep_strong_capability() -> None:
    commands = _commands_by_name()

    for name in [
        "speckit.echelon.commander",
        "speckit.echelon.strategist",
        "speckit.echelon.cartographer",
        "speckit.echelon.sage",
        "speckit.echelon.gatekeeper",
        "speckit.echelon.architect",
        "speckit.echelon.orchestrator",
        "speckit.echelon.investigator",
        "speckit.echelon.guardian",
        "speckit.echelon.implementer",
        "speckit.echelon.code-reviewer",
        "speckit.echelon.engineering-manager",
        "speckit.echelon.change-controller",
        "speckit.echelon.debugger",
        "speckit.echelon.harness-run",
        "speckit.echelon.harness-resume",
    ]:
        assert commands[name]["behavior"]["capability"] == "strong"


def test_runtime_model_config_covers_workflow_tiers() -> None:
    data = yaml.safe_load(CONFIG_TEMPLATE.read_text(encoding="utf-8"))

    models = data["execution"]["models"]
    assert models["re_extraction"] == "sonnet"
    assert models["re_planning"] == "sonnet"
