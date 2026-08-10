from __future__ import annotations

from pathlib import Path

import pytest

from harness.squad_executors import _render_published_re_context


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.unit
def test_spec_workflow_has_no_embedded_re_dispatches() -> None:
    workflow = (ROOT / "runtime/workflow/definition.yaml").read_text(
        encoding="utf-8"
    )
    init = (ROOT / "runtime/workflow/phases/init.md").read_text(encoding="utf-8")
    executors = (ROOT / "src/harness/squad_executors.py").read_text(
        encoding="utf-8"
    )

    assert "golddigger_mode1" not in workflow
    assert "golddigger_mode2_queue" not in workflow
    assert "golddigger_requests" not in workflow
    assert "ReExtractionController" not in executors
    assert "golddigger_mode" not in executors
    assert "dispatch GOLDDIGGER" not in init
    assert "Never dispatch reverse engineering from the spec workflow" in init


@pytest.mark.unit
def test_spec_agents_use_published_re_as_read_only_context() -> None:
    scout = (ROOT / "prosaic/subagents/echelon.scout.md").read_text(
        encoding="utf-8"
    )
    cartographer = (ROOT / "prosaic/subagents/echelon.cartographer.md").read_text(
        encoding="utf-8"
    )

    assert "PUBLISHED_RE_STATUS=attached" in scout
    assert "NEVER run reverse engineering" in scout
    assert "Mode 2 Deep Dive Requests" not in cartographer


@pytest.mark.unit
def test_shared_agent_contract_has_paired_published_re_first_rules() -> None:
    executors = (ROOT / "src/harness/squad_executors.py").read_text(
        encoding="utf-8"
    )

    assert "ALWAYS inspect the Published Reverse Engineering Context block" in executors
    assert "NEVER ignore Published Reverse Engineering Context" in executors
    assert "ALWAYS read the workspace RE briefing" in executors
    assert "NEVER skip the workspace RE briefing" in executors
    assert "ALWAYS read matched source RE briefings" in executors
    assert "NEVER answer those questions from raw source search alone" in executors


@pytest.mark.unit
def test_prompt_renders_attached_snapshot_not_canonical_re_tree(tmp_path: Path) -> None:
    snapshot = tmp_path / "runs/spec-1/context/published-re"
    workspace_brief = snapshot / "RE-WORKSPACE-BRIEF.md"
    source_brief = snapshot / "RE-SOURCE-api-BRIEF.md"
    workspace_brief.parent.mkdir(parents=True)
    workspace_brief.write_text("# Workspace RE\n\nContracts.\n", encoding="utf-8")
    source_brief.write_text("# Source RE\n\nAPI facts.\n", encoding="utf-8")
    prompt = _render_published_re_context(
        {
            "published_re_context": {
                "status": "attached",
                "generation": 7,
                "snapshot_root": str(snapshot),
                "artifacts": {"manifest": str(snapshot / "index.json")},
                "rendered_briefings": {
                    "workspace": str(workspace_brief),
                    "sources": {"api": str(source_brief)},
                },
            }
        }
    )

    assert "PUBLISHED_RE_GENERATION=7" in prompt
    assert str(snapshot / "index.json") in prompt
    assert "# Workspace RE" in prompt
    assert "# Source RE" in prompt
    assert "read-only evidence" in prompt
    assert "mutable canonical re/ tree" in prompt
