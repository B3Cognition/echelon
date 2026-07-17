"""CLI tests for deterministic verify-spec CodeGraph evidence."""
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


def _write_fake_bridge(project_root: Path) -> Path:
    runtime_dir = (
        project_root
        / ".specify"
        / "extensions"
        / "echelon"
        / "scripts"
        / "node"
        / "codegraph"
    )
    return _write_fake_bridge_at_runtime(runtime_dir)


def _write_fake_bridge_at_runtime(runtime_dir: Path) -> Path:
    bridge_path = runtime_dir / "codegraph-bridge.js"
    bridge_path.parent.mkdir(parents=True)
    bridge_path.write_text(
        """
const fs = require("fs");
const path = require("path");

const args = process.argv.slice(2);
const repoPath = args[args.indexOf("--repo-path") + 1];
const outputPath = args[args.indexOf("--output-path") + 1];

fs.mkdirSync(path.dirname(outputPath), {recursive: true});
fs.mkdirSync(path.join(repoPath, ".codegraph"), {recursive: true});
fs.writeFileSync(outputPath, JSON.stringify({
  version: "1.0.0",
  generated_at: "2026-06-05T00:00:00Z",
  repo_path: repoPath,
  supported: true,
  index_stats: {index_state: "ready"},
  language_coverage: {swift: 1},
  coverage: {files: 1},
  symbols: [{kind: "function"}, {kind: "function"}, {kind: "class"}],
  call_graph: [
    {caller: "A", callee: "B"},
    {caller: "A", callee: "C"},
    {caller: "D", callee: "B"}
  ]
}));
""".lstrip(),
        encoding="utf-8",
    )
    (runtime_dir / "codegraph-adapter.js").write_text("adapter\n", encoding="utf-8")
    package = runtime_dir / "node_modules/@colbymchenry/codegraph/package.json"
    package.parent.mkdir(parents=True)
    package.write_text("{}\n", encoding="utf-8")
    return bridge_path


def _write_fake_executable(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)
    return path


def _prepend_path(monkeypatch, bin_dir: Path) -> None:
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")


def _write_verify_state(verify_run_dir: Path) -> None:
    verify_run_dir.mkdir(parents=True, exist_ok=True)
    (verify_run_dir / "state.json").write_text(
        json.dumps({"structural_evidence": "pending"}),
        encoding="utf-8",
    )


def _write_fake_codegraph_cli(bin_dir: Path, *, success: bool) -> Path:
    if success:
        script = """
#!/usr/bin/env python3
import json
import pathlib
import sys

args = sys.argv[1:]
output = pathlib.Path(args[args.index("--output") + 1])
repo = pathlib.Path(args[args.index("--path") + 1])
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps({
    "version": "1.0.0",
    "provider": "codegraph-cli",
    "generated_at": "2026-06-17T00:00:00Z",
    "repo_path": str(repo),
    "supported": True,
    "index_stats": {"index_state": "ready"},
    "language_coverage": {"python": "supported"},
    "coverage": {"files": 1},
    "symbols": [{"kind": "function"}, {"kind": "class"}],
    "call_graph": [{"caller": "CliA", "callee": "CliB"}]
}))
""".lstrip()
    else:
        script = """
#!/usr/bin/env python3
import sys
print("cli failed", file=sys.stderr)
sys.exit(7)
""".lstrip()
    return _write_fake_executable(bin_dir / "codegraph", script)


def _write_fake_stale_codegraph_cli(bin_dir: Path, stale_repo: Path) -> Path:
    script = f"""
#!/usr/bin/env python3
import json
import pathlib
import sys

args = sys.argv[1:]
output = pathlib.Path(args[args.index("--output") + 1])
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps({{
    "version": "1.0.0",
    "provider": "stale-codegraph-cli",
    "repo_path": {str(stale_repo)!r},
    "supported": True,
    "index_stats": {{"index_state": "ready"}},
    "symbols": [{{"kind": "function"}}],
    "call_graph": []
}}))
""".lstrip()
    return _write_fake_executable(bin_dir / "codegraph", script)


def test_write_codegraph_evidence_cli_writes_analysis_and_summary(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    _write_fake_bridge(project_root)
    verify_run_dir = tmp_path / "runs" / "verify-spec-001"
    _write_verify_state(verify_run_dir)
    spec_dir = project_root / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)

    result = _run(
        [
            "write-codegraph-evidence",
            str(project_root),
            str(verify_run_dir),
            str(spec_dir),
        ]
    )

    assert result.returncode == 0, result.stderr
    assert (verify_run_dir / "codegraph-analysis.json").exists()
    summary = json.loads((verify_run_dir / "codegraph-summary.json").read_text())
    assert summary["index_state"] == "ready"
    assert summary["symbol_kinds"][0] == {"kind": "function", "count": 2}
    assert summary["top_callers"][0] == {"symbol": "A", "outgoing_calls": 2}
    assert summary["top_callees"][0] == {"symbol": "B", "incoming_calls": 2}
    state = json.loads((verify_run_dir / "state.json").read_text())
    assert state["structural_evidence"] == "ready"
    assert not (project_root / ".codegraph").exists()


def test_write_codegraph_evidence_uses_installed_bridge_when_global_cli_exists(
    tmp_path: Path, monkeypatch
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    _write_fake_bridge(project_root)
    _write_fake_codegraph_cli(tmp_path / "bin", success=True)
    _prepend_path(monkeypatch, tmp_path / "bin")
    verify_run_dir = tmp_path / "runs" / "verify-spec-001"
    error_path = verify_run_dir / "codegraph-error.txt"
    _write_verify_state(verify_run_dir)
    error_path.write_text("stale", encoding="utf-8")
    spec_dir = project_root / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)

    result = _run(
        [
            "write-codegraph-evidence",
            str(project_root),
            str(verify_run_dir),
            str(spec_dir),
        ]
    )

    assert result.returncode == 0, result.stderr
    analysis = json.loads((verify_run_dir / "codegraph-analysis.json").read_text())
    summary = json.loads((verify_run_dir / "codegraph-summary.json").read_text())
    assert "provider" not in analysis
    assert summary["top_callers"][0] == {"symbol": "A", "outgoing_calls": 2}
    assert not error_path.exists()


def test_write_codegraph_evidence_uses_shared_runtime(
    tmp_path: Path, monkeypatch
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    echelon_home = tmp_path / "echelon-home"
    _write_fake_bridge_at_runtime(echelon_home / "node/codegraph")
    monkeypatch.setenv("ECHELON_HOME", str(echelon_home))
    verify_run_dir = tmp_path / "runs" / "verify-spec-001"
    _write_verify_state(verify_run_dir)
    spec_dir = project_root / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)

    result = _run(
        [
            "write-codegraph-evidence",
            str(project_root),
            str(verify_run_dir),
            str(spec_dir),
        ]
    )

    assert result.returncode == 0, result.stderr
    summary = json.loads((verify_run_dir / "codegraph-summary.json").read_text())
    assert summary["index_state"] == "ready"


def test_write_codegraph_evidence_rejects_stale_cli_repo_path_and_regenerates(
    tmp_path: Path, monkeypatch
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    stale_repo = tmp_path / "old-iter"
    stale_repo.mkdir()
    _write_fake_bridge(project_root)
    _write_fake_stale_codegraph_cli(tmp_path / "bin", stale_repo)
    _prepend_path(monkeypatch, tmp_path / "bin")
    verify_run_dir = tmp_path / "runs" / "verify-spec-001"
    _write_verify_state(verify_run_dir)
    spec_dir = project_root / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)

    result = _run(
        [
            "write-codegraph-evidence",
            str(project_root),
            str(verify_run_dir),
            str(spec_dir),
        ]
    )

    assert result.returncode == 0, result.stderr
    analysis = json.loads((verify_run_dir / "codegraph-analysis.json").read_text())
    summary = json.loads((verify_run_dir / "codegraph-summary.json").read_text())
    assert analysis.get("provider") != "stale-codegraph-cli"
    assert Path(summary["repo_path"]) == project_root


def test_write_codegraph_evidence_falls_back_to_bridge_when_cli_fails(
    tmp_path: Path, monkeypatch
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    _write_fake_bridge(project_root)
    _write_fake_codegraph_cli(tmp_path / "bin", success=False)
    _prepend_path(monkeypatch, tmp_path / "bin")
    verify_run_dir = tmp_path / "runs" / "verify-spec-001"
    _write_verify_state(verify_run_dir)
    spec_dir = project_root / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)

    result = _run(
        [
            "write-codegraph-evidence",
            str(project_root),
            str(verify_run_dir),
            str(spec_dir),
        ]
    )

    assert result.returncode == 0, result.stderr
    analysis = json.loads((verify_run_dir / "codegraph-analysis.json").read_text())
    summary = json.loads((verify_run_dir / "codegraph-summary.json").read_text())
    assert "provider" not in analysis
    assert summary["top_callers"][0] == {"symbol": "A", "outgoing_calls": 2}
    state = json.loads((verify_run_dir / "state.json").read_text())
    assert state["structural_evidence"] == "ready"
    assert not (verify_run_dir / "codegraph-error.txt").exists()


def test_write_codegraph_evidence_cli_preserves_existing_codegraph_dir(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    _write_fake_bridge(project_root)
    codegraph_dir = project_root / ".codegraph"
    codegraph_dir.mkdir()
    marker = codegraph_dir / "keep.txt"
    marker.write_text("existing", encoding="utf-8")
    verify_run_dir = tmp_path / "runs" / "verify-spec-001"
    _write_verify_state(verify_run_dir)
    spec_dir = project_root / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)

    result = _run(
        [
            "write-codegraph-evidence",
            str(project_root),
            str(verify_run_dir),
            str(spec_dir),
        ]
    )

    assert result.returncode == 0, result.stderr
    assert marker.read_text(encoding="utf-8") == "existing"


def test_write_codegraph_evidence_reports_missing_resolved_runtime(
    tmp_path: Path, monkeypatch
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setenv("ECHELON_HOME", str(tmp_path / "empty-echelon-home"))
    _write_fake_codegraph_cli(tmp_path / "bin", success=False)
    _prepend_path(monkeypatch, tmp_path / "bin")
    verify_run_dir = tmp_path / "runs" / "verify-spec-001"
    _write_verify_state(verify_run_dir)
    spec_dir = project_root / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)

    result = _run(
        [
            "write-codegraph-evidence",
            str(project_root),
            str(verify_run_dir),
            str(spec_dir),
        ]
    )

    assert result.returncode != 0
    error = (verify_run_dir / "codegraph-error.txt").read_text(encoding="utf-8")
    assert ".specify/extensions/echelon/scripts/node/codegraph" in error
    assert "empty-echelon-home/node/codegraph" in error
    assert "CodeGraph runtime is unavailable" in error
    summary = json.loads((verify_run_dir / "codegraph-summary.json").read_text())
    assert summary["structural_evidence"] == "degraded"
    assert summary["evidence_quality"] == "manual_fallback_required"
    assert summary["diagnostic_artifact"] == str(verify_run_dir / "codegraph-error.txt")
    state = json.loads((verify_run_dir / "state.json").read_text())
    assert state["structural_evidence"] == "degraded"
    assert state["codegraph_evidence_quality"] == "manual_fallback_required"
    assert state["codegraph_summary_path"] == str(verify_run_dir / "codegraph-summary.json")


def test_write_codegraph_evidence_cli_requires_init_owned_state(
    tmp_path: Path, monkeypatch
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    _write_fake_bridge(project_root)
    _write_fake_codegraph_cli(tmp_path / "bin", success=True)
    _prepend_path(monkeypatch, tmp_path / "bin")
    verify_run_dir = tmp_path / "runs" / "verify-spec-001"
    spec_dir = project_root / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)

    result = _run(
        [
            "write-codegraph-evidence",
            str(project_root),
            str(verify_run_dir),
            str(spec_dir),
        ]
    )

    assert result.returncode == 1
    assert "state.json missing for verify-spec run:" in result.stderr
    assert not (verify_run_dir / "codegraph-analysis.json").exists()
    assert not (verify_run_dir / "codegraph-summary.json").exists()
