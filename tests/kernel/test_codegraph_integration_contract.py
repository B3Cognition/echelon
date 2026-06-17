"""Contract tests for RE CodeGraph integration wiring."""
from __future__ import annotations

import sys
from pathlib import Path

EXT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(EXT_ROOT) not in sys.path:
    sys.path.insert(0, str(EXT_ROOT))

from kernel.re_state import complete_dispatch, init_re_state, write_last_dispatch


def test_install_script_installs_re_node_dependencies_with_npm_ci():
    install_script = (EXT_ROOT / "scripts" / "install.sh").read_text()

    assert "RE_NODE_DIR=" in install_script
    assert 'npm ci --prefix "$RE_NODE_DIR"' in install_script
    assert "CodeGraph bridge" in install_script


def test_install_script_supports_optional_codegraph_cli_without_mcp_install():
    install_script = (EXT_ROOT / "scripts" / "install.sh").read_text()

    assert 'CODEGRAPH_CLI_VERSION="1.0.1"' in install_script
    assert "ECHELON_INSTALL_CODEGRAPH_CLI" in install_script
    assert '"@colbymchenry/codegraph@$CODEGRAPH_CLI_VERSION"' in install_script
    assert "codegraph install" not in install_script
    assert 'command -v codegraph' in install_script


def test_run_analysis_points_to_extension_node_install_path():
    run_analysis = (
        EXT_ROOT / "extension" / "scripts" / "bash" / "re" / "run-analysis.sh"
    ).read_text()

    assert 'RE_NODE_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")/node/re"' in run_analysis
    assert 'npm ci --prefix \\"$RE_NODE_DIR\\"' in run_analysis
    assert "npm install --prefix scripts/node/re" not in run_analysis


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


def test_re_preflight_prefers_active_run_output_dir_and_tracks_codegraph_artifacts():
    preflight = (
        EXT_ROOT / "extension" / "workflow" / "phases" / "re-extract-0-preflight.md"
    ).read_text()

    assert "runs/.current" in preflight
    assert "runs/{run_id}/re" in preflight
    assert "state_path = Path(output_dir) / 'state.json'" in preflight
    assert "'codegraph_analysis': f'{output_dir}/codegraph-analysis.json'" in preflight
    assert "'codegraph_summary': f'{output_dir}/codegraph-summary.json'" in preflight


def test_re_analyzer_uses_state_output_dir_instead_of_hardcoded_re_path():
    analyzer = (EXT_ROOT / "extension" / "agents" / "re" / "analyzer.md").read_text()

    assert "RE_OUTPUT_DIR" in analyzer
    assert '"$EXTENSION_PATH/scripts/bash/re/run-analysis.sh" "$RE_OUTPUT_DIR" "$RE_OUTPUT_DIR/repos-manifest.json"' in analyzer
    assert '"$EXTENSION_PATH/scripts/bash/re/discover-repos.sh" "$RE_OUTPUT_DIR/repos-manifest.json"' in analyzer
    assert '"$EXTENSION_PATH/scripts/bash/re/run-analysis.sh" ".specify/echelon/re"' not in analyzer


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
