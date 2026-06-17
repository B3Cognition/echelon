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
    bridge_path = (
        project_root
        / ".specify"
        / "extensions"
        / "echelon"
        / "scripts"
        / "node"
        / "re"
        / "codegraph-bridge.js"
    )
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
    return bridge_path


def _write_fake_executable(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)
    return path


def _prepend_path(monkeypatch, bin_dir: Path) -> None:
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")


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


def test_write_codegraph_evidence_cli_writes_analysis_and_summary(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    _write_fake_bridge(project_root)
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

    assert result.returncode == 0, result.stderr
    assert (verify_run_dir / "codegraph-analysis.json").exists()
    summary = json.loads((verify_run_dir / "codegraph-summary.json").read_text())
    assert summary["index_state"] == "ready"
    assert summary["symbol_kinds"][0] == {"kind": "function", "count": 2}
    assert summary["top_callers"][0] == {"symbol": "A", "outgoing_calls": 2}
    assert summary["top_callees"][0] == {"symbol": "B", "incoming_calls": 2}
    assert not (project_root / ".codegraph").exists()


def test_write_codegraph_evidence_prefers_codegraph_cli_when_available(
    tmp_path: Path, monkeypatch
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    _write_fake_bridge(project_root)
    _write_fake_codegraph_cli(tmp_path / "bin", success=True)
    _prepend_path(monkeypatch, tmp_path / "bin")
    verify_run_dir = tmp_path / "runs" / "verify-spec-001"
    error_path = verify_run_dir / "codegraph-error.txt"
    error_path.parent.mkdir(parents=True)
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
    assert analysis["provider"] == "codegraph-cli"
    assert summary["top_callers"][0] == {"symbol": "CliA", "outgoing_calls": 1}
    assert not error_path.exists()


def test_write_codegraph_evidence_falls_back_to_bridge_when_cli_fails(
    tmp_path: Path, monkeypatch
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    _write_fake_bridge(project_root)
    _write_fake_codegraph_cli(tmp_path / "bin", success=False)
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

    assert result.returncode == 0, result.stderr
    analysis = json.loads((verify_run_dir / "codegraph-analysis.json").read_text())
    summary = json.loads((verify_run_dir / "codegraph-summary.json").read_text())
    assert "provider" not in analysis
    assert summary["top_callers"][0] == {"symbol": "A", "outgoing_calls": 2}
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


def test_write_codegraph_evidence_cli_uses_fixed_installed_bridge_path(
    tmp_path: Path, monkeypatch
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    _write_fake_codegraph_cli(tmp_path / "bin", success=False)
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

    assert result.returncode != 0
    error = (verify_run_dir / "codegraph-error.txt").read_text(encoding="utf-8")
    assert "CodeGraph CLI failed." in error
    assert "exit_code: 7" in error
    assert ".specify/extensions/echelon/scripts/node/re/codegraph-bridge.js" in error
    assert "fixed installed extension path" in error
