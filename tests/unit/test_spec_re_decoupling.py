from __future__ import annotations

from pathlib import Path

import pytest

from harness.squad_executors import _render_published_re_context


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.unit
def test_spec_workflow_has_no_embedded_re_dispatches() -> None:
    workflow = (ROOT / "extension/workflow/definition.yaml").read_text(
        encoding="utf-8"
    )
    init = (ROOT / "extension/workflow/phases/init.md").read_text(encoding="utf-8")
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
    scout = (ROOT / "extension/agents/exploration/scout.md").read_text(
        encoding="utf-8"
    )
    cartographer = (ROOT / "extension/agents/exploration/cartographer.md").read_text(
        encoding="utf-8"
    )

    assert "PUBLISHED_RE_STATUS=attached" in scout
    assert "NEVER run reverse engineering" in scout
    assert "Mode 2 Deep Dive Requests" not in cartographer


@pytest.mark.unit
def test_prompt_renders_attached_snapshot_not_canonical_re_tree(tmp_path: Path) -> None:
    snapshot = tmp_path / "runs/spec-1/context/published-re"
    prompt = _render_published_re_context(
        {
            "published_re_context": {
                "status": "attached",
                "generation": 7,
                "snapshot_root": str(snapshot),
                "artifacts": {"manifest": str(snapshot / "index.json")},
            }
        }
    )

    assert "PUBLISHED_RE_GENERATION=7" in prompt
    assert str(snapshot / "index.json") in prompt
    assert "read-only evidence" in prompt
    assert "mutable canonical re/ tree" in prompt
