"""CLI tests for deterministic verify-spec PerlGraph evidence."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    src_path = str(Path(__file__).resolve().parents[2] / "src")
    env["PYTHONPATH"] = (
        src_path
        if not env.get("PYTHONPATH")
        else f"{src_path}{os.pathsep}{env['PYTHONPATH']}"
    )
    return subprocess.run(
        [sys.executable, "-m", "harness", *args],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def _write_verify_state(verify_run_dir: Path) -> None:
    verify_run_dir.mkdir(parents=True, exist_ok=True)
    (verify_run_dir / "state.json").write_text(
        json.dumps({"perlgraph_evidence": "pending"}),
        encoding="utf-8",
    )


def _write_fake_perlgraph_cli(project_root: Path, *, stale_repo: Path | None = None) -> Path:
    cli_path = (
        project_root
        / ".specify"
        / "extensions"
        / "echelon"
        / "scripts"
        / "node"
        / "perlgraph"
        / "dist"
        / "cli"
        / "perlgraph.js"
    )
    cli_path.parent.mkdir(parents=True)
    repo_literal = "repoPath" if stale_repo is None else json.dumps(str(stale_repo))
    cli_path.write_text(
        f"""
const fs = require("fs");
const path = require("path");

const args = process.argv.slice(2);
const repoPath = args[args.indexOf("--repo-path") + 1];
const outputPath = args[args.indexOf("--output-path") + 1];
const summaryPath = args[args.indexOf("--summary-path") + 1];
const analysis = {{
  schema_version: 1,
  tool: "perlgraph",
  generated_at: "2026-07-14T00:00:00Z",
  repo_path: {repo_literal},
  supported: true,
  language_coverage: {{".pm": "supported"}},
  symbols: [{{kind: "sub", file_path: "lib/App.pm", qualified_name: "App::run"}}],
  relationships: [],
  call_graph: [{{source: "App::run", target: "App::helper", confidence: "high", provenance: ["fixture"]}}],
  module_graph: [],
  unsupported_patterns: [],
  parse_failures: [],
  index_stats: {{index_state: "ready", symbol_count: 1, relationship_count: 1}}
}};
const summary = {{
  schema_version: 1,
  tool: "perlgraph",
  generated_at: analysis.generated_at,
  repo_path: analysis.repo_path,
  index_state: "ready",
  index_stats: analysis.index_stats,
  symbol_kinds: [{{kind: "sub", count: 1}}],
  relationship_kinds: [],
  top_callers: [{{symbol: "App::run", outgoing_calls: 1}}],
  top_callees: [{{symbol: "App::helper", incoming_calls: 1}}],
  top_modules: [],
  dynamic_risk: {{count: 0, patterns: []}}
}};
fs.mkdirSync(path.dirname(outputPath), {{recursive: true}});
fs.writeFileSync(outputPath, JSON.stringify(analysis));
fs.writeFileSync(summaryPath, JSON.stringify(summary));
""".lstrip(),
        encoding="utf-8",
    )
    return cli_path


def test_write_perlgraph_evidence_cli_writes_analysis_and_summary(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    _write_fake_perlgraph_cli(project_root)
    verify_run_dir = tmp_path / "runs" / "verify-spec-001"
    _write_verify_state(verify_run_dir)
    spec_dir = project_root / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)

    result = _run(
        [
            "write-perlgraph-evidence",
            str(project_root),
            str(verify_run_dir),
            str(spec_dir),
        ]
    )

    assert result.returncode == 0, result.stderr
    assert (verify_run_dir / "perlgraph-analysis.json").exists()
    summary = json.loads((verify_run_dir / "perlgraph-summary.json").read_text())
    assert summary["tool"] == "perlgraph"
    assert summary["index_state"] == "ready"
    state = json.loads((verify_run_dir / "state.json").read_text())
    assert state["perlgraph_evidence"] == "ready"
    assert state["perlgraph_summary_path"] == str(verify_run_dir / "perlgraph-summary.json")


def test_write_perlgraph_evidence_rejects_stale_repo_path(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    stale_repo = tmp_path / "old-iter"
    stale_repo.mkdir()
    _write_fake_perlgraph_cli(project_root, stale_repo=stale_repo)
    verify_run_dir = tmp_path / "runs" / "verify-spec-001"
    _write_verify_state(verify_run_dir)
    spec_dir = project_root / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)

    result = _run(
        [
            "write-perlgraph-evidence",
            str(project_root),
            str(verify_run_dir),
            str(spec_dir),
        ]
    )

    assert result.returncode == 1
    error = (verify_run_dir / "perlgraph-error.txt").read_text()
    assert "PerlGraph CLI failed." in error
    summary = json.loads((verify_run_dir / "perlgraph-summary.json").read_text())
    assert summary["structural_evidence"] == "degraded"
    state = json.loads((verify_run_dir / "state.json").read_text())
    assert state["perlgraph_evidence"] == "degraded"


def test_write_perlgraph_evidence_degrades_when_runtime_missing(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    verify_run_dir = tmp_path / "runs" / "verify-spec-001"
    _write_verify_state(verify_run_dir)
    spec_dir = project_root / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)

    result = _run(
        [
            "write-perlgraph-evidence",
            str(project_root),
            str(verify_run_dir),
            str(spec_dir),
        ]
    )

    assert result.returncode == 1
    assert (verify_run_dir / "perlgraph-error.txt").exists()
    summary = json.loads((verify_run_dir / "perlgraph-summary.json").read_text())
    assert summary["evidence_quality"] == "manual_fallback_required"
    assert summary["tool"] == "perlgraph"
