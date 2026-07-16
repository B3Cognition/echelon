from __future__ import annotations

from pathlib import Path
import re

import yaml


ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "README.md"
CATALOG = ROOT / "docs" / "agent-role-catalog.md"
EXTENSION_YML = ROOT / "extension" / "extension.yml"
WORKFLOW = ROOT / "extension" / "workflow" / "definition.yaml"
AGENTS_DIR = ROOT / "extension" / "agents"


def _registered_agent_slugs() -> set[str]:
    data = yaml.safe_load(EXTENSION_YML.read_text(encoding="utf-8"))
    slugs: set[str] = set()
    for entry in data["provides"]["commands"]:
        file_path = entry.get("file", "")
        if file_path.startswith("agents/") and file_path.endswith(".md"):
            slugs.add(entry["name"].replace("speckit.echelon.", "speckit-echelon-"))
    return slugs


def _workflow_dispatch_slugs() -> set[str]:
    text = WORKFLOW.read_text(encoding="utf-8")
    return set(re.findall(r"speckit-echelon-[a-z0-9-]+", text))


def _agent_entrypoint_files() -> set[Path]:
    return {
        path for path in AGENTS_DIR.rglob("*.md")
        if "appendices" not in path.parts and "templates" not in path.parts
    }


def test_readme_and_catalog_match_agent_role_inventory() -> None:
    registered = _registered_agent_slugs()
    workflow = _workflow_dispatch_slugs()
    active_manifest = registered & workflow
    manifest_only = registered - workflow
    workflow_only = workflow - registered
    support_files = set(AGENTS_DIR.rglob("*.md")) - _agent_entrypoint_files()

    assert len(registered) == 55
    assert len(active_manifest) == 45
    assert len(manifest_only) == 10
    assert workflow_only == {"speckit-echelon-gatekeeper-assess2"}
    assert len(support_files) == 14

    readme = README.read_text(encoding="utf-8")
    catalog = CATALOG.read_text(encoding="utf-8")

    assert "41-agent" not in readme
    assert "55 registered agent roles" in readme
    assert "45 active-routed manifest roles" in readme
    assert "Agent Role Catalog](docs/agent-role-catalog.md)" in readme

    assert "| Registered agent roles | 55 |" in catalog
    assert "| Active-routed manifest roles | 45 |" in catalog
    assert "| Manifest-only roles | 10 |" in catalog
    assert "| Workflow-only dispatch aliases | 1 |" in catalog
    assert "| Support prompt files | 14 |" in catalog
    assert "`speckit-echelon-gatekeeper-assess2`" in catalog
