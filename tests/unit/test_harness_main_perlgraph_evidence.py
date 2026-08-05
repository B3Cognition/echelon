"""CLI tests for deterministic verify-spec PerlGraph evidence."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("ECHELON_CODEGRAPH_RUNTIME_DIR", None)
    env.pop("ECHELON_PERLGRAPH_RUNTIME_DIR", None)
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
    runtime_dir = (
        project_root
        / ".specify"
        / "extensions"
        / "echelon"
        / "scripts"
        / "node"
        / "perlgraph"
    )
    return _write_fake_perlgraph_cli_at_runtime(runtime_dir, stale_repo=stale_repo)


def _write_fake_perlgraph_cli_at_runtime(
    runtime_dir: Path, *, stale_repo: Path | None = None
) -> Path:
    cli_path = runtime_dir / "dist" / "cli" / "perlgraph.js"
    cli_path.parent.mkdir(parents=True)
    repo_literal = "repoPath" if stale_repo is None else json.dumps(str(stale_repo))
    cli_path.write_text(
        f"""
const fs = require("fs");
const path = require("path");
const crypto = require("crypto");

const args = process.argv.slice(2);
const repoPath = args[args.indexOf("--repo-path") + 1];
const outputPath = args[args.indexOf("--output-path") + 1];
const summaryPath = args[args.indexOf("--summary-path") + 1];
const symbolKey = `sha256:${{crypto.createHash("sha256")
  .update(JSON.stringify(["lib/App.pm", "App::run", "sub", ""]), "utf8")
  .digest("hex")}}`;
const analysis = {{
  schema_version: 2,
  tool: "perlgraph",
  tool_version: "0.1.0",
  generated_at: "2026-07-14T00:00:00Z",
  repo_path: {repo_literal},
  supported: true,
  provider_status: "ready",
  complete: true,
  counts: {{discovered_files: 1, emitted_files: 1, discovered_symbols: 1, emitted_symbols: 1, discovered_relationships: 0, emitted_relationships: 0, unresolved_relationships: 0, parse_failures: 0, parse_diagnostics: 0, dynamic_patterns: 0}},
  capabilities: {{language: "perl", supported_extensions: [".pm"], exact_symbol_keys: true, exact_relationship_endpoints: true, unresolved_relationship_diagnostics: true}},
  language_coverage: {{".pm": "supported"}},
  symbols: [{{symbol_key: symbolKey, kind: "sub", file_path: "lib/App.pm", qualified_name: "App::run", name: "run", signature: "", line_start: 1, line_end: 1}}],
  relationships: [],
  unresolved_relationships: [],
  call_graph: [],
  module_graph: [],
  unsupported_patterns: [],
  parse_failures: [],
  parse_diagnostics: [],
  index_stats: {{index_state: "ready", symbol_count: 1, relationship_count: 1}}
}};
const summary = {{
  schema_version: 2,
  tool: "perlgraph",
  tool_version: analysis.tool_version,
  repo_path: analysis.repo_path,
  provider_status: analysis.provider_status,
  complete: analysis.complete,
  counts: analysis.counts,
  capabilities: analysis.capabilities,
  diagnostics: {{unresolved_relationships: analysis.unresolved_relationships, parse_failures: analysis.parse_failures, parse_diagnostics: analysis.parse_diagnostics, unsupported_patterns: analysis.unsupported_patterns}}
}};
fs.mkdirSync(path.dirname(outputPath), {{recursive: true}});
fs.writeFileSync(outputPath, JSON.stringify(analysis));
fs.writeFileSync(summaryPath, JSON.stringify(summary));
""".lstrip(),
        encoding="utf-8",
    )
    cli_path.chmod(0o755)
    (runtime_dir / "node_modules").mkdir()
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
    assert summary["provider_status"] == "ready"
    state = json.loads((verify_run_dir / "state.json").read_text())
    assert state["perlgraph_evidence"] == "ready"
    assert state["perlgraph_summary_path"] == str(verify_run_dir / "perlgraph-summary.json")


def test_delivery_commands_finalize_exact_run_local_topology_receipt(
    tmp_path: Path, monkeypatch
) -> None:
    from tests.unit.test_harness_main_codegraph_evidence import _write_fake_bridge

    workspace = tmp_path / "workspace"
    source = workspace / "sources/api"
    source.mkdir(parents=True)
    (workspace / ".echelon").mkdir()
    (workspace / ".echelon/config.yml").write_text(
        "workspace:\n  sources:\n    - id: api\n      path: sources/api\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-b", "main"], cwd=source, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=source, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=source, check=True)
    (source / "src").mkdir()
    (source / "src/app.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "src/app.py"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-m", "feature"], cwd=source, check=True, capture_output=True)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=source,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    _write_fake_bridge(source)
    _write_fake_perlgraph_cli(source)
    monkeypatch.setenv(
        "ECHELON_CODEGRAPH_RUNTIME_DIR", str(tmp_path / "host-codegraph")
    )
    host_perlgraph = tmp_path / "host-perlgraph"
    _write_fake_perlgraph_cli_at_runtime(
        host_perlgraph, stale_repo=tmp_path / "host-repo"
    )
    monkeypatch.setenv("ECHELON_PERLGRAPH_RUNTIME_DIR", str(host_perlgraph))
    spec_dir = workspace / "specs/909-delivery-topology"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("---\nstatus: ready_to_land\n---\n", encoding="utf-8")
    verify_run = workspace / "runs/verify-spec-909-20260804-120000"
    verify_run.mkdir(parents=True)
    (verify_run / "state.json").write_text(
        json.dumps(
            {
                "spec_id": "909-delivery-topology",
                "verify_scope": "full",
                "status": "in_progress",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ECHELON_WORKSPACE_ROOT", str(workspace))
    monkeypatch.setenv("ECHELON_SOURCE_ID", "api")
    monkeypatch.setenv("ECHELON_SOURCE_ROOT", str(source))

    codegraph = _run(
        ["write-codegraph-evidence", str(source), str(verify_run), str(spec_dir)]
    )
    perlgraph = _run(
        ["write-perlgraph-evidence", str(source), str(verify_run), str(spec_dir)]
    )
    finalized = _run(
        [
            "write-topology-evidence-receipt",
            str(source),
            str(verify_run),
            str(spec_dir),
        ]
    )

    assert codegraph.returncode == 0, codegraph.stderr
    assert perlgraph.returncode == 0, perlgraph.stderr
    assert finalized.returncode == 0, finalized.stderr
    receipt = json.loads((verify_run / "topology-receipt.json").read_text())
    assert receipt["schema_version"] == 1
    assert receipt["source_id"] == "api"
    assert receipt["source_path"] == "sources/api"
    assert receipt["spec_id"] == "909-delivery-topology"
    assert receipt["verify_scope"] == "full"
    assert receipt["analyzed_commit"] == head
    assert receipt["source_fingerprint"]["git_head"] == head
    assert receipt["source_fingerprint"]["dirty"] is False
    assert receipt["provenance"] == {
        "kind": "delivery",
        "run_dir": "runs/verify-spec-909-20260804-120000",
    }
    assert list(receipt["providers"]) == ["codegraph", "perlgraph"]
    assert receipt["providers"]["codegraph"]["tool_version"] == "1.4.1"
    assert receipt["providers"]["codegraph"]["status"] == "complete"
    assert receipt["providers"]["codegraph"]["complete"] is True
    assert receipt["providers"]["perlgraph"]["tool_version"] == "0.1.0"
    assert receipt["providers"]["perlgraph"]["status"] == "ready"
    for provider in ("codegraph", "perlgraph"):
        for artifact in ("analysis", "summary"):
            path = verify_run / f"{provider}-{artifact}.json"
            assert receipt["providers"][provider]["artifacts"][artifact] == {
                "path": path.name,
                "sha256": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(),
            }
    state = json.loads((verify_run / "state.json").read_text())
    assert state["topology_evidence"] == "ready"
    assert state["status"] == "in_progress"
    assert "completed_at" not in state


def test_topology_receipt_is_written_when_both_providers_are_unavailable(
    tmp_path: Path, monkeypatch
) -> None:
    workspace = tmp_path / "workspace"
    source = workspace / "sources/api"
    source.mkdir(parents=True)
    (workspace / ".echelon").mkdir()
    (workspace / ".echelon/config.yml").write_text(
        "workspace:\n  sources:\n    - id: api\n      path: sources/api\n",
        encoding="utf-8",
    )
    spec_dir = workspace / "specs/909-delivery-topology"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")
    verify_run = workspace / "runs/verify-spec-909-unavailable"
    verify_run.mkdir(parents=True)
    (verify_run / "state.json").write_text(
        json.dumps(
            {
                "spec_id": "909-delivery-topology",
                "verify_scope": "full",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ECHELON_WORKSPACE_ROOT", str(workspace))
    monkeypatch.setenv("ECHELON_SOURCE_ID", "api")
    monkeypatch.setenv("ECHELON_SOURCE_ROOT", str(source))

    finalized = _run(
        [
            "write-topology-evidence-receipt",
            str(source),
            str(verify_run),
            str(spec_dir),
        ]
    )

    assert finalized.returncode == 0, finalized.stderr
    receipt = json.loads((verify_run / "topology-receipt.json").read_text())
    assert {
        provider: row["status"] for provider, row in receipt["providers"].items()
    } == {"codegraph": "unavailable", "perlgraph": "unavailable"}
    state = json.loads((verify_run / "state.json").read_text())
    assert state["topology_evidence"] == "unavailable"


def test_write_perlgraph_evidence_uses_shared_runtime(
    tmp_path: Path, monkeypatch
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    echelon_home = tmp_path / "echelon-home"
    _write_fake_perlgraph_cli_at_runtime(echelon_home / "node/perlgraph")
    monkeypatch.setenv("ECHELON_HOME", str(echelon_home))
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
    summary = json.loads((verify_run_dir / "perlgraph-summary.json").read_text())
    assert summary["provider_status"] == "ready"


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


def test_write_perlgraph_evidence_degrades_when_runtime_missing(
    tmp_path: Path, monkeypatch
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setenv("ECHELON_HOME", str(tmp_path / "empty-echelon-home"))
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
