"""CLI tests for deterministic verify-spec CodeGraph evidence."""
from __future__ import annotations

import json
import hashlib
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
const crypto = require("crypto");

const args = process.argv.slice(2);
const repoPath = args[args.indexOf("--repo-path") + 1];
const outputPath = args[args.indexOf("--output-path") + 1];
const symbolKey = (filePath, qualifiedName, kind) =>
  `sha256:${crypto.createHash("sha256")
    .update(JSON.stringify([filePath, qualifiedName, kind, ""]), "utf8")
    .digest("hex")}`;
const a = symbolKey("src/a.ts", "A", "function");
const b = symbolKey("src/b.ts", "B", "function");
const c = symbolKey("src/c.ts", "C", "class");
const d = symbolKey("src/d.ts", "D", "class");

fs.mkdirSync(path.dirname(outputPath), {recursive: true});
fs.mkdirSync(path.join(repoPath, ".codegraph"), {recursive: true});
fs.writeFileSync(outputPath, JSON.stringify({
  schema_version: 2,
  version: "2.0.0",
  tool: "codegraph",
  tool_version: "1.4.1",
  provider_status: "complete",
  complete: true,
  counts: {
    discovered_symbols: 4,
    emitted_symbols: 4,
    excluded_symbols: 0,
    discovered_relationships: 3,
    emitted_relationships: 3,
    excluded_relationships: 0
  },
  diagnostics: {unresolved_relationships: []},
  generated_at: "2026-06-05T00:00:00Z",
  repo_path: repoPath,
  supported: true,
  index_stats: {index_state: "ready"},
  language_coverage: {swift: 1},
  coverage: {files: 1},
  symbols: [
    {symbol_key: a, qualified_name: "A", name: "A", file_path: "src/a.ts", line_start: 1, line_end: 1, kind: "function"},
    {symbol_key: b, qualified_name: "B", name: "B", file_path: "src/b.ts", line_start: 1, line_end: 1, kind: "function"},
    {symbol_key: c, qualified_name: "C", name: "C", file_path: "src/c.ts", line_start: 1, line_end: 1, kind: "class"},
    {symbol_key: d, qualified_name: "D", name: "D", file_path: "src/d.ts", line_start: 1, line_end: 1, kind: "class"}
  ],
  relationships: [
    {kind: "calls", source_key: a, target_key: b, source_name: "A", target_name: "B"},
    {kind: "calls", source_key: a, target_key: c, source_name: "A", target_name: "C"},
    {kind: "calls", source_key: d, target_key: b, source_name: "D", target_name: "B"}
  ],
  call_graph: [
    {caller_key: a, callee_key: b, caller_name: "A", callee_name: "B"},
    {caller_key: a, callee_key: c, caller_name: "A", callee_name: "C"},
    {caller_key: d, callee_key: b, caller_name: "D", callee_name: "B"}
  ],
  type_hierarchy: [],
  impact_radius: []
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


def test_analysis_is_usable_requires_complete_schema_two_artifact(tmp_path: Path) -> None:
    from harness.codegraph_evidence import _analysis_is_usable

    analysis_path = tmp_path / "codegraph-analysis.json"
    analysis_path.write_text(
        json.dumps({"symbols": []}),
        encoding="utf-8",
    )

    assert not _analysis_is_usable(analysis_path)


def test_analysis_is_usable_rejects_noncanonical_symbol_locators(tmp_path: Path) -> None:
    from harness.codegraph_evidence import _analysis_is_usable

    def analysis_for(file_path: str, symbol_key: str) -> dict:
        return {
            "schema_version": 2,
            "version": "2.0.0",
            "tool": "codegraph",
            "tool_version": "1.4.1",
            "provider_status": "complete",
            "complete": True,
            "counts": {
                "discovered_symbols": 1,
                "emitted_symbols": 1,
                "excluded_symbols": 0,
                "discovered_relationships": 0,
                "emitted_relationships": 0,
                "excluded_relationships": 0,
            },
            "diagnostics": {"unresolved_relationships": []},
            "symbols": [
                {
                    "symbol_key": symbol_key,
                    "qualified_name": "demo.run",
                    "name": "run",
                    "kind": "function",
                    "file_path": file_path,
                    "line_start": 1,
                    "line_end": 1,
                }
            ],
            "relationships": [],
            "call_graph": [],
            "type_hierarchy": [],
            "impact_radius": [],
        }

    def canonical_key(file_path: str) -> str:
        locator = json.dumps(
            [file_path, "demo.run", "function", ""],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return "sha256:" + hashlib.sha256(locator.encode("utf-8")).hexdigest()

    analysis_path = tmp_path / "codegraph-analysis.json"
    analysis_path.write_text(
        json.dumps(analysis_for("src/demo.py", canonical_key("src/demo.py"))),
        encoding="utf-8",
    )
    assert _analysis_is_usable(analysis_path)

    analysis_path.write_text(
        json.dumps(analysis_for("src/demo.py", "sha256:" + "0" * 64)),
        encoding="utf-8",
    )
    assert not _analysis_is_usable(analysis_path)

    analysis_path.write_text(
        json.dumps(
            analysis_for("src/../demo.py", canonical_key("src/../demo.py"))
        ),
        encoding="utf-8",
    )
    assert not _analysis_is_usable(analysis_path)

    analysis_path.write_text(
        json.dumps(analysis_for("/tmp/demo.py", canonical_key("/tmp/demo.py"))),
        encoding="utf-8",
    )
    assert not _analysis_is_usable(analysis_path)


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
    assert set(summary) == {
        "schema_version",
        "tool",
        "tool_version",
        "provider_status",
        "complete",
        "counts",
        "diagnostics",
    }
    assert summary["tool"] == "codegraph"
    assert summary["counts"]["emitted_symbols"] == 4
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
    assert summary["counts"]["emitted_relationships"] == 3
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
    assert summary["provider_status"] == "complete"


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
    assert summary["tool"] == "codegraph"


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
    assert summary["counts"]["emitted_relationships"] == 3
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
