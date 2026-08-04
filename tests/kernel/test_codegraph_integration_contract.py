"""Contract tests for RE CodeGraph integration wiring."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

EXT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(EXT_ROOT) not in sys.path:
    sys.path.insert(0, str(EXT_ROOT))

from kernel.re_state import complete_dispatch, init_re_state, write_last_dispatch


CODEGRAPH_RUNTIME_DIR = EXT_ROOT / "extension" / "scripts" / "node" / "codegraph"
CODEGRAPH_PACKAGE = "@colbymchenry/codegraph"
CODEGRAPH_VERSION = "1.4.1"


def test_install_script_installs_codegraph_in_shared_runtime_with_npm_ci():
    install_script = (EXT_ROOT / "scripts" / "install.sh").read_text()

    assert 'NODE_RUNTIME_ROOT="${ECHELON_HOME:-$HOME/.echelon}/node"' in install_script
    assert (
        'CODEGRAPH_SOURCE_DIR="$ECHELON_DIR/extension/scripts/node/codegraph"'
        in install_script
    )
    assert 'CODEGRAPH_NODE_DIR="$NODE_RUNTIME_ROOT/codegraph"' in install_script
    assert (
        '_refresh_node_runtime "$CODEGRAPH_SOURCE_DIR" "$CODEGRAPH_NODE_DIR" vendor dist'
        in install_script
    )
    assert '_npm_ci_in_runtime "$CODEGRAPH_NODE_DIR"' in install_script
    assert "CodeGraph bridge" in install_script
    assert 'npm ci --prefix "$CODEGRAPH_NODE_DIR"' not in install_script
    assert 'npm ci --prefix "$CODEGRAPH_SOURCE_DIR"' not in install_script


def test_install_script_supports_optional_codegraph_cli_without_mcp_install():
    install_script = (EXT_ROOT / "scripts" / "install.sh").read_text()

    assert f'CODEGRAPH_CLI_VERSION="{CODEGRAPH_VERSION}"' in install_script
    assert "ECHELON_INSTALL_CODEGRAPH_CLI" in install_script
    assert '"@colbymchenry/codegraph@$CODEGRAPH_CLI_VERSION"' in install_script
    assert "codegraph install" not in install_script
    assert 'command -v codegraph' in install_script


def test_uninstall_script_removes_shared_node_runtimes() -> None:
    uninstall_script = (EXT_ROOT / "scripts" / "uninstall.sh").read_text()

    assert 'ECHELON_HOME="${ECHELON_HOME:-$HOME/.echelon}"' in uninstall_script
    assert 'NODE_RUNTIME_DIR="$ECHELON_HOME/node"' in uninstall_script
    assert 'rm -rf "$NODE_RUNTIME_DIR"' in uninstall_script


def test_codegraph_runtime_is_pinned_to_current_supported_release():
    package = json.loads((CODEGRAPH_RUNTIME_DIR / "package.json").read_text())
    lock = json.loads((CODEGRAPH_RUNTIME_DIR / "package-lock.json").read_text())
    adapter = (CODEGRAPH_RUNTIME_DIR / "codegraph-adapter.js").read_text()
    install_script = (EXT_ROOT / "scripts" / "install.sh").read_text()

    assert package["dependencies"][CODEGRAPH_PACKAGE] == CODEGRAPH_VERSION
    assert lock["packages"][""]["dependencies"][CODEGRAPH_PACKAGE] == CODEGRAPH_VERSION
    assert lock["packages"][f"node_modules/{CODEGRAPH_PACKAGE}"]["version"] == CODEGRAPH_VERSION
    assert f'require("{CODEGRAPH_PACKAGE}")' in adapter
    assert "vendor/codegraph" not in adapter
    assert f'CODEGRAPH_CLI_VERSION="{CODEGRAPH_VERSION}"' in install_script


def test_bridge_emits_more_than_ten_thousand_symbols_without_truncation(
    tmp_path: Path,
) -> None:
    script = """
const bridge = require(process.argv[2]);
const symbols = Array.from({length: 10001}, (_, i) => ({
  symbol_key: `sha256:${String(i).padStart(64, '0')}`,
  qualified_name: `f${i}`,
  name: `f${i}`,
  kind: 'function',
  file_path: `src/f${i}.ts`,
  line_start: 1,
  line_end: 1
}));
const out = bridge.assembleAnalysisOutput({
  repoPath: process.cwd(), symbols, relationships: [], callGraph: [],
  typeHierarchy: [], impactRadius: [], publicSymbols: symbols,
  indexStats: {}, extractionSummary: {languages: [], unsupported_languages: [], total_extracted: 10001}
});
if (
  out.symbols.length !== 10001 ||
  !out.complete ||
  out.counts.discovered_symbols !== 10001 ||
  out.counts.emitted_symbols !== 10001
) process.exit(1);
"""

    script_path = tmp_path / "bridge-contract.js"
    script_path.write_text(script, encoding="utf-8")
    completed = subprocess.run(
        [
            "node",
            str(script_path),
            str(CODEGRAPH_RUNTIME_DIR / "codegraph-bridge.js"),
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def test_bridge_does_not_expose_or_apply_symbol_limits() -> None:
    bridge = (CODEGRAPH_RUNTIME_DIR / "codegraph-bridge.js").read_text()

    for removed_symbol in ("--max-symbols", "DEFAULT_MAX_SYMBOLS", "truncateSymbols"):
        assert removed_symbol not in bridge


def test_adapter_preserves_exact_impact_keys_for_zero_node_id(tmp_path: Path) -> None:
    script = """
const adapter = require(process.argv[2]);
const source = {id: 0, filePath: 'src/source.ts', qualifiedName: 'Source::run', kind: 'function', startLine: 1, endLine: 2};
const target = {id: 1, filePath: 'src/target.ts', qualifiedName: 'Target::run', kind: 'function', startLine: 1, endLine: 2};
const cg = {
  getNodesByKind: (kind) => kind === 'function' ? [source, target] : [],
  getImpactRadius: (nodeId) => nodeId === 0 ? {nodes: new Map([[0, source], [1, target]])} : null
};
adapter.getImpactRadius(cg, [adapter.symbolKey(source)], 3).then((entries) => {
  if (entries[0].symbol_name !== 'Source::run' || entries[0].affected_keys[0] !== adapter.symbolKey(target)) process.exit(1);
});
"""

    script_path = tmp_path / "adapter-impact-contract.js"
    script_path.write_text(script, encoding="utf-8")
    completed = subprocess.run(
        [
            "node",
            str(script_path),
            str(CODEGRAPH_RUNTIME_DIR / "codegraph-adapter.js"),
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def test_shell_ci_uses_a_node_runtime_supported_by_codegraph_sdk():
    workflow = (EXT_ROOT / ".github" / "workflows" / "ci.yml").read_text()

    assert "actions/setup-node@v4" in workflow
    assert 'node-version: "24"' in workflow


def test_run_analysis_uses_shared_runtime_resolver_without_local_npm_repair():
    run_analysis = (
        EXT_ROOT / "extension" / "scripts" / "bash" / "re" / "run-analysis.sh"
    ).read_text()

    assert "node-runtime-resolver.sh" in run_analysis
    assert "echelon_resolve_codegraph_runtime" in run_analysis
    assert 'CODEGRAPH_NODE_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")/node/codegraph"' not in run_analysis
    assert 'npm ci --prefix \\"$CODEGRAPH_NODE_DIR\\"' not in run_analysis
    assert "npm install --prefix scripts/node/codegraph" not in run_analysis


def test_re_state_tracks_codegraph_analysis_artifact_by_default():
    state = init_re_state(output_dir="/custom/re")

    assert state["artifacts"]["codegraph_analysis"] == "/custom/re/codegraph-analysis.json"
    assert state["artifacts"]["codegraph_summary"] == "/custom/re/codegraph-summary.json"


def test_re_state_accepts_codegraph_analysis_artifact_updates():
    state = init_re_state()
    state = write_last_dispatch(state, "re-extract-1-analyze", "speckit-echelon-re-analyzer")

    updated = complete_dispatch(
        state,
        {
            "verdict": "DONE",
            "phase_id": "re-extract-1-analyze",
            "state_updates": {
                "artifacts": {
                    "analysis_json": ".specify/echelon/re/analysis.json",
                    "repos_manifest": ".specify/echelon/re/repos-manifest.json",
                    "cross_repo": None,
                    "codegraph_analysis": ".specify/echelon/re/codegraph-analysis.json",
                    "codegraph_summary": ".specify/echelon/re/codegraph-summary.json",
                }
            },
        },
    )

    assert (
        updated["artifacts"]["codegraph_analysis"]
        == ".specify/echelon/re/codegraph-analysis.json"
    )
    assert (
        updated["artifacts"]["codegraph_summary"]
        == ".specify/echelon/re/codegraph-summary.json"
    )


def test_run_analysis_writes_compact_codegraph_summary():
    run_analysis = (
        EXT_ROOT / "extension" / "scripts" / "bash" / "re" / "run-analysis.sh"
    ).read_text()

    assert "write_codegraph_summary()" in run_analysis
    assert "codegraph-summary.json" in run_analysis


def test_run_analysis_polyrepo_writes_per_repo_codegraph_artifacts():
    run_analysis = (
        EXT_ROOT / "extension" / "scripts" / "bash" / "re" / "run-analysis.sh"
    ).read_text()

    assert '"$REPO_OUTPUT/codegraph-analysis.json"' in run_analysis
    assert '"$REPO_OUTPUT/codegraph-summary.json"' in run_analysis
    assert "write_polyrepo_codegraph_summary()" in run_analysis
    assert '"mode": "polyrepo"' in run_analysis


def test_re_controller_tracks_codegraph_artifacts(tmp_path):
    from harness.re_controller import ReExtractionController

    controller = object.__new__(ReExtractionController)
    controller._run_re_dir = tmp_path / "runs" / "run-1" / "re"
    controller._run_dir = tmp_path / "runs" / "run-1"
    controller._run_re_dir.mkdir(parents=True)
    for name in ("codegraph-analysis.json", "codegraph-summary.json"):
        (controller._run_re_dir / name).write_text("{}\n", encoding="utf-8")

    state = controller._initialize_state()
    artifacts = controller._analysis_result()["state_updates"]["artifacts"]

    assert state["output_dir"] == "runs/run-1/re"
    assert artifacts["codegraph_analysis"].endswith("/codegraph-analysis.json")
    assert artifacts["codegraph_summary"].endswith("/codegraph-summary.json")


def test_re_analyzer_uses_state_output_dir_instead_of_hardcoded_re_path():
    analyzer = (EXT_ROOT / "extension" / "agents" / "re" / "analyzer.md").read_text()

    assert "workspace-manifest.json" in analyzer
    assert "RE_OUTPUT_DIR" in analyzer
    assert "controller-owned analysis step" in analyzer
    assert "NEVER invoke repository discovery" in analyzer
    assert "NEVER derive, invoke, or repair CodeGraph or PerlGraph runtimes" in analyzer
    assert "scripts/node/codegraph/codegraph-bridge.js" not in analyzer
    assert "dist/cli/perlgraph.js" not in analyzer
    assert "Prefer `$RE_OUTPUT_DIR/re-analysis-manifest.json`" in analyzer
    assert "repos-manifest.json" in analyzer
    assert "run-analysis.sh" not in analyzer


def test_re_prompts_prefer_workspace_manifest_with_repos_fallback():
    compatibility_agents = [
        "extension/agents/re/analyzer.md",
        "extension/agents/exploration/scout.md",
        "extension/agents/exploration/golddigger.md",
    ]
    for rel_path in compatibility_agents:
        text = (EXT_ROOT / rel_path).read_text()

        assert "workspace-manifest.json" in text, rel_path
        assert "repos-manifest.json" in text, rel_path
        if rel_path == "extension/agents/re/analyzer.md":
            assert "prefer workspace-manifest.json for standalone extraction" in text
        else:
            assert "Prefer workspace-manifest.json" in text, rel_path
        assert "compatibility fallback" in text, rel_path

    for rel_path in [
        "extension/agents/re/specifier.md",
        "extension/agents/re/verifier.md",
        "extension/agents/re/constituter.md",
    ]:
        text = (EXT_ROOT / rel_path).read_text()
        assert "re-source-index.json" in text or "re-workspace-inputs.json" in text


def test_golddigger_reports_workspace_manifest_as_primary_artifact():
    text = (EXT_ROOT / "extension/agents/exploration/golddigger.md").read_text()

    assert 'manifest: "{RE_OUTPUT_DIR}/workspace-manifest.json"' in text
    assert 'repos_manifest: "{RE_OUTPUT_DIR}/repos-manifest.json"' in text
    assert 'sources_root: "{RE_OUTPUT_DIR}/sources"' in text
    assert 'workspace_root: "{RE_OUTPUT_DIR}/workspace"' in text
    assert 're_overview: "{RE_OUTPUT_DIR}/workspace/overview.md"' in text


def test_workspace_prompts_describe_per_source_codegraph_shape():
    scout = (EXT_ROOT / "extension/agents/exploration/scout.md").read_text()
    specifier = (EXT_ROOT / "extension/agents/re/specifier.md").read_text()

    assert "aggregate index of per-source summaries" in scout
    assert "$RE_OUTPUT_DIR/sources/{source-id}/codegraph-summary.json" in specifier
    assert "$RE_OUTPUT_DIR/sources/{source-id}/codegraph-analysis.json" in specifier


def test_exploration_agents_do_not_hardcode_re_artifact_reads():
    stale = []
    for rel_path in [
        "extension/agents/exploration/golddigger.md",
        "extension/agents/exploration/scout.md",
        "extension/commands/appendices/re-single-phase-command.md",
    ]:
        text = (EXT_ROOT / rel_path).read_text()
        for line_no, line in enumerate(text.splitlines(), start=1):
            if ".specify/echelon/re/" in line and "standalone" not in line and "fallback" not in line:
                stale.append(f"{rel_path}:{line_no}: {line.strip()}")

    assert not stale, "\n".join(stale)
