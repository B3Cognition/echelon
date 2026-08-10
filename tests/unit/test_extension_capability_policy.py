from pathlib import Path

import yaml

from harness.prompt_markdown import read_prompt_markdown


ROOT = Path(__file__).resolve().parents[2]
CONFIG_TEMPLATE = ROOT / "runtime" / "config-template.yml"


def _prose_by_name() -> dict[str, dict]:
    prose: dict[str, dict] = {}
    for directory in (ROOT / "prosaic/subagents", ROOT / "prosaic/commands"):
        for path in directory.glob("*.md"):
            metadata = read_prompt_markdown(path).metadata
            name = metadata.get("name")
            if isinstance(name, str):
                prose[name] = metadata
    return prose


def test_cost_tuned_agents_do_not_request_strong_capability() -> None:
    prose = _prose_by_name()

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
        assert prose[name]["model_tier"] == capability


def test_high_risk_agents_keep_strong_capability() -> None:
    prose = _prose_by_name()

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
        assert prose[name]["model_tier"] == "strong"


def test_runtime_model_config_covers_workflow_tiers() -> None:
    data = yaml.safe_load(CONFIG_TEMPLATE.read_text(encoding="utf-8"))

    models = data["execution"]["models"]
    assert models["re_extraction"] == "sonnet"
    assert models["re_planning"] == "sonnet"
