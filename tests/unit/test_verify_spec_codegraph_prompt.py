"""Prompt contract tests for verify-spec CodeGraph evidence."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent.parent
PHASE_DIR = ROOT / "extension" / "workflow" / "phases"


def test_verify_spec_init_records_project_root_for_deterministic_commands() -> None:
    text = (PHASE_DIR / "verify-spec-1-init.md").read_text(encoding="utf-8")

    assert "- `project_root`" in text


def test_verify_spec_codegraph_uses_deterministic_harness_command() -> None:
    text = (PHASE_DIR / "verify-spec-2-codegraph.md").read_text(encoding="utf-8")

    assert (
        'python -m harness write-codegraph-evidence "{project_root}" '
        '"{verify_run_dir}" "{spec_dir}"'
    ) in text
    assert "{verify_run_dir}/codegraph-analysis.json" in text
    assert "{verify_run_dir}/codegraph-summary.json" in text


def test_verify_spec_codegraph_forbids_prompt_side_discovery() -> None:
    text = (PHASE_DIR / "verify-spec-2-codegraph.md").read_text(encoding="utf-8")

    assert "NEVER locate, inspect, or infer CodeGraph bridge invocation" in text
    assert "do not attempt fallback discovery" in text
