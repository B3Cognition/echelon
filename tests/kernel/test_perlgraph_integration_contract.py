"""Contract tests for PerlGraph integration wiring."""
from __future__ import annotations

import json
import sys
from pathlib import Path

EXT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(EXT_ROOT) not in sys.path:
    sys.path.insert(0, str(EXT_ROOT))

from kernel.re_state import complete_dispatch, init_re_state, write_last_dispatch


PERLGRAPH_RUNTIME_DIR = EXT_ROOT / "extension" / "scripts" / "node" / "perlgraph"
PERLGRAPH_VERSION = "0.1.0"


def test_install_script_prepares_perlgraph_in_shared_runtime() -> None:
    install_script = (EXT_ROOT / "scripts" / "install.sh").read_text()

    assert 'NODE_RUNTIME_ROOT="${ECHELON_HOME:-$HOME/.echelon}/node"' in install_script
    assert (
        'PERLGRAPH_SOURCE_DIR="$ECHELON_DIR/extension/scripts/node/perlgraph"'
        in install_script
    )
    assert 'PERLGRAPH_NODE_DIR="$NODE_RUNTIME_ROOT/perlgraph"' in install_script
    assert (
        '_refresh_node_runtime "$PERLGRAPH_SOURCE_DIR" "$PERLGRAPH_NODE_DIR" dist'
        in install_script
    )
    assert '_npm_ci_in_runtime "$PERLGRAPH_NODE_DIR"' in install_script
    assert '--include=dev' in _perlgraph_install_section(install_script)
    assert '_npm_run_in_runtime "$PERLGRAPH_NODE_DIR" build' in install_script
    assert 'CXXFLAGS="${CXXFLAGS:--std=c++20}"' in install_script
    assert "PerlGraph" in install_script
    assert "--ignore-scripts" not in _perlgraph_install_section(install_script)
    assert 'npm ci --prefix "$PERLGRAPH_NODE_DIR"' not in install_script
    assert 'npm ci --prefix "$PERLGRAPH_SOURCE_DIR"' not in install_script


def test_perlgraph_runtime_is_pinned_to_release() -> None:
    package = json.loads((PERLGRAPH_RUNTIME_DIR / "package.json").read_text())
    lock = json.loads((PERLGRAPH_RUNTIME_DIR / "package-lock.json").read_text())
    provenance = (PERLGRAPH_RUNTIME_DIR / "ECHELON-PROVENANCE.md").read_text()

    assert package["name"] == "perlgraph"
    assert package["version"] == PERLGRAPH_VERSION
    assert lock["packages"][""]["version"] == PERLGRAPH_VERSION
    assert "git@github.com:B3Cognition/perlgraph.git" in provenance
    assert "34efe5d" in provenance
    assert "package version `0.1.0`" in provenance


def test_re_state_tracks_perlgraph_artifacts_by_default() -> None:
    state = init_re_state(output_dir="/custom/re")

    assert state["artifacts"]["perlgraph_analysis"] == "/custom/re/perlgraph-analysis.json"
    assert state["artifacts"]["perlgraph_summary"] == "/custom/re/perlgraph-summary.json"


def test_re_state_accepts_perlgraph_artifact_updates() -> None:
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
                    "perlgraph_analysis": ".specify/echelon/re/perlgraph-analysis.json",
                    "perlgraph_summary": ".specify/echelon/re/perlgraph-summary.json",
                }
            },
        },
    )

    assert (
        updated["artifacts"]["perlgraph_analysis"]
        == ".specify/echelon/re/perlgraph-analysis.json"
    )
    assert (
        updated["artifacts"]["perlgraph_summary"]
        == ".specify/echelon/re/perlgraph-summary.json"
    )


def test_run_analysis_writes_perlgraph_artifacts() -> None:
    run_analysis = (
        EXT_ROOT / "extension" / "scripts" / "bash" / "re" / "run-analysis.sh"
    ).read_text()

    assert "node-runtime-resolver.sh" in run_analysis
    assert "echelon_resolve_perlgraph_runtime" in run_analysis
    assert 'PERLGRAPH_NODE_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")/node/perlgraph"' not in run_analysis
    assert 'npm ci --prefix \\"$PERLGRAPH_NODE_DIR\\"' not in run_analysis
    assert '"$REPO_OUTPUT/perlgraph-analysis.json"' in run_analysis
    assert '"$REPO_OUTPUT/perlgraph-summary.json"' in run_analysis
    assert '"$OUTPUT_DIR/perlgraph-analysis.json"' in run_analysis
    assert '"$OUTPUT_DIR/perlgraph-summary.json"' in run_analysis
    assert "write_polyrepo_perlgraph_summary()" in run_analysis


def test_re_preflight_tracks_perlgraph_artifacts() -> None:
    preflight = (
        EXT_ROOT / "extension" / "workflow" / "phases" / "re-extract-0-preflight.md"
    ).read_text()

    assert "'perlgraph_analysis': f'{output_dir}/perlgraph-analysis.json'" in preflight
    assert "'perlgraph_summary': f'{output_dir}/perlgraph-summary.json'" in preflight


def test_re_analyze_contract_mentions_perlgraph_outputs() -> None:
    analyze = (
        EXT_ROOT / "extension" / "workflow" / "phases" / "re-extract-1-analyze.md"
    ).read_text()

    assert "{state.output_dir}/perlgraph-analysis.json" in analyze
    assert "{state.output_dir}/perlgraph-summary.json" in analyze
    assert "perlgraph_analysis" in analyze
    assert "perlgraph_summary" in analyze


def test_workspace_prompts_describe_per_source_perlgraph_shape() -> None:
    scout = (EXT_ROOT / "extension" / "agents" / "exploration" / "scout.md").read_text()
    specifier = (EXT_ROOT / "extension" / "agents" / "re" / "specifier.md").read_text()

    assert "PerlGraph" in scout
    assert "$RE_OUTPUT_DIR/sources/{source-id}/perlgraph-summary.json" in specifier
    assert "$RE_OUTPUT_DIR/sources/{source-id}/perlgraph-analysis.json" in specifier
    assert "unsupported_patterns" in specifier
    assert "candidate future PerlGraph improvements" in specifier


def _perlgraph_install_section(install_script: str) -> str:
    start = install_script.find("PerlGraph")
    if start == -1:
        return ""
    end = install_script.find("Context7", start)
    return install_script[start:] if end == -1 else install_script[start:end]
