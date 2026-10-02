from __future__ import annotations

from pathlib import Path
import re

import yaml


ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "README.md"
CATALOG = ROOT / "docs" / "agent-role-catalog.md"
WORKFLOW = ROOT / "runtime" / "workflow" / "definition.yaml"
SUBAGENTS_DIR = ROOT / "prosaic" / "subagents"
SUPPORT_DIR = ROOT / "prosaic" / "agents"
AGENT_ID_RE = re.compile(r"echelon\.[a-z0-9-]+")


def _prosaic_agent_ids() -> set[str]:
    return {path.stem for path in SUBAGENTS_DIR.glob("*.md")}


def _collect_workflow_agent_ids(value: object) -> set[str]:
    ids: set[str] = set()
    if isinstance(value, dict):
        for field in ("agent", "id"):
            agent_id = value.get(field)
            if isinstance(agent_id, str) and AGENT_ID_RE.fullmatch(agent_id):
                ids.add(agent_id)
        for child in value.values():
            ids.update(_collect_workflow_agent_ids(child))
    elif isinstance(value, list):
        for child in value:
            ids.update(_collect_workflow_agent_ids(child))
    return ids


def _workflow_dispatch_ids() -> set[str]:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return _collect_workflow_agent_ids(workflow)


def test_readme_and_catalog_match_agent_role_inventory() -> None:
    available = _prosaic_agent_ids()
    dispatched = _workflow_dispatch_ids()
    direct_use = available - dispatched
    missing = dispatched - available
    support_files = set(SUPPORT_DIR.rglob("*.md"))

    assert missing == set()
    assert len(support_files) == 14

    readme = README.read_text(encoding="utf-8")
    catalog = CATALOG.read_text(encoding="utf-8")

    assert f"{len(available)} neutral Prosaic agent roles" in readme
    assert f"{len(dispatched)} workflow-referenced roles" in readme
    assert f"{len(direct_use)} roles outside that graph" in readme
    assert "three disabled internal knowledge roles" in readme
    assert "Agent Role Catalog](docs/agent-role-catalog.md)" in readme

    assert f"| Neutral Prosaic agent roles | {len(available)} |" in catalog
    assert f"| Workflow-referenced roles | {len(dispatched)} |" in catalog
    assert f"| Roles outside the workflow graph | {len(direct_use)} |" in catalog
    assert "| Support prose files | 14 |" in catalog
    graph_inventory = catalog.split("## Workflow-Referenced Roles", 1)[1].split(
        "## Roles Outside The Workflow Graph", 1
    )[0]
    outside_inventory = catalog.split("## Roles Outside The Workflow Graph", 1)[1]
    assert set(AGENT_ID_RE.findall(graph_inventory)) == dispatched
    assert set(AGENT_ID_RE.findall(outside_inventory)) == direct_use
    assert set(AGENT_ID_RE.findall(catalog)) == available
    assert "extension/extension.yml" not in catalog
    assert "speckit-echelon" not in catalog
