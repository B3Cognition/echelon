from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG_TEMPLATE = ROOT / "runtime" / "config-template.yml"


def test_runtime_model_config_covers_workflow_tiers() -> None:
    data = yaml.safe_load(CONFIG_TEMPLATE.read_text(encoding="utf-8"))

    models = data["execution"]["models"]
    assert models["re_extraction"] == "sonnet"
    assert models["re_planning"] == "sonnet"
