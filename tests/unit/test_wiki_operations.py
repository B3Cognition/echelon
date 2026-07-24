from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from echelon.wiki.service import build_wiki, wiki_status


pytestmark = pytest.mark.unit


def _workspace(root: Path, *, configured: bool = False) -> Path:
    config = {"sources": [], "wiki": {"include_run_analysis": configured}}
    path = root / ".echelon/config.yml"
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    spec = root / "specs/001-demo"
    spec.mkdir(parents=True)
    (spec / "spec.md").write_text("# Demo\n", encoding="utf-8")
    run = root / "runs/re-1"
    (run / "re/workspace").mkdir(parents=True)
    (run / "state.json").write_text(
        json.dumps({"run_id": "re-1", "run_kind": "re", "status": "blocked"}),
        encoding="utf-8",
    )
    (run / "re/state.json").write_text(
        json.dumps(
            {
                "run_id": "re-1",
                "status": "blocked",
                "phase": "re-extract-5-validate",
                "re_source_states": {},
            }
        ),
        encoding="utf-8",
    )
    spec_run = root / "runs/spec-1"
    spec_run.mkdir(parents=True)
    (spec_run / "state.json").write_text(
        json.dumps(
            {
                "run_id": "spec-1",
                "spec_id": "001-demo",
                "status": "done",
                "phase": "DONE",
                "token_usage": 9,
                "why_fail_count": 1,
            }
        ),
        encoding="utf-8",
    )
    return root


def test_default_wiki_excludes_local_runs(tmp_path: Path) -> None:
    result = build_wiki(_workspace(tmp_path))

    assert not (result.output_dir / "Operations").exists()
    manifest = json.loads((result.output_dir / "manifest.json").read_text())
    assert manifest["operational_inputs"] == {}


def test_include_runs_renders_analysis_without_raw_spans(tmp_path: Path) -> None:
    result = build_wiki(_workspace(tmp_path), include_runs=True)

    page = result.output_dir / "Operations/RE Runs/re-1.md"
    assert page.is_file()
    spec_page = result.output_dir / "Operations/Spec Runs/spec-1.md"
    assert spec_page.is_file()
    assert "Repair loops" in spec_page.read_text(encoding="utf-8")
    assert "Token usage: unavailable (no provider usage telemetry)" in spec_page.read_text(
        encoding="utf-8"
    )
    assert "local and ephemeral" in page.read_text(encoding="utf-8").lower()
    assert (result.output_dir / "Views/Performance.md").is_file()
    assert (result.output_dir / "Views/Spec Repair Loops.md").is_file()
    assert not any(result.output_dir.rglob("spans.jsonl"))


def test_include_runs_marks_partial_token_coverage(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    telemetry = root / "runs/spec-1/telemetry"
    telemetry.mkdir()
    (telemetry / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "workflow": "spec",
                "run_id": "spec-1",
                "trace_id": "a" * 32,
                "profile": {"name": "balanced"},
            }
        ),
        encoding="utf-8",
    )
    spans = [
        {
            "schema_version": 1,
            "trace_id": "a" * 32,
            "span_id": f"{index + 1:016x}",
            "parent_span_id": None,
            "name": "phase1-what",
            "start_time": "2026-07-20T00:00:00Z",
            "end_time": "2026-07-20T00:00:01Z",
            "duration_ms": 1000,
            "status": "OK",
            "attributes": {},
            "token_usage": usage,
        }
        for index, usage in enumerate(
            ({"total_tokens": 10}, {"total_tokens": None})
        )
    ]
    (telemetry / "spans.jsonl").write_text(
        "".join(json.dumps(span) + "\n" for span in spans), encoding="utf-8"
    )

    result = build_wiki(root, include_runs=True)

    page = (result.output_dir / "Operations/Spec Runs/spec-1.md").read_text(
        encoding="utf-8"
    )
    token_view = (result.output_dir / "Views/Token Usage.md").read_text(
        encoding="utf-8"
    )
    assert "Token usage: 10 observed (partial; 1/2 dispatches reported)" in page
    assert "50% (1/2) | partial" in token_view


def test_config_enables_runs_and_explicit_false_overrides_it(tmp_path: Path) -> None:
    root = _workspace(tmp_path, configured=True)

    configured = build_wiki(root)
    assert (configured.output_dir / "Operations/Index.md").is_file()
    overridden = build_wiki(root, include_runs=False)
    assert not (overridden.output_dir / "Operations").exists()


def test_status_distinguishes_operational_staleness(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    build_wiki(root, include_runs=True)
    state_path = root / "runs/re-1/re/state.json"
    state = json.loads(state_path.read_text())
    state["phase"] = "re-extract-6-checklist"
    state_path.write_text(json.dumps(state), encoding="utf-8")

    status = wiki_status(root)

    assert status.state == "stale"
    assert status.operational_stale is True
    assert status.added_inputs == ()
    assert status.changed_inputs == ()
