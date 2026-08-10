"""Behavior tests for the extension-local Bash Node runtime resolver."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RESOLVER = ROOT / "runtime" / "scripts" / "bash" / "node-runtime-resolver.sh"


def _isolated_env(**values: str) -> dict[str, str]:
    env = os.environ.copy()
    env.pop("ECHELON_CODEGRAPH_RUNTIME_DIR", None)
    env.pop("ECHELON_PERLGRAPH_RUNTIME_DIR", None)
    env.update(values)
    return env


def _run_resolver(
    function: str,
    local_node_root: Path,
    *,
    env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; "$2" "$3"',
            "bash",
            str(RESOLVER),
            function,
            str(local_node_root),
        ],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def _write_complete_codegraph(runtime: Path) -> None:
    (runtime / "node_modules" / "@colbymchenry" / "codegraph").mkdir(
        parents=True
    )
    (runtime / "codegraph-bridge.js").write_text("bridge\n", encoding="utf-8")
    (runtime / "codegraph-adapter.js").write_text("adapter\n", encoding="utf-8")
    (runtime / "node_modules/@colbymchenry/codegraph/package.json").write_text(
        '{"version":"1.4.1"}\n', encoding="utf-8"
    )
    (runtime / "package.json").write_text(
        json.dumps(
            {
                "echelon_runtime": {
                    "provider_artifact_schema_version": 2,
                    "exact_relationship_endpoints": True,
                    "uncapped_symbols": True,
                }
            }
        ),
        encoding="utf-8",
    )


def _write_complete_perlgraph(runtime: Path) -> None:
    cli = runtime / "dist" / "cli" / "perlgraph.js"
    cli.parent.mkdir(parents=True)
    cli.write_text("#!/usr/bin/env node\n", encoding="utf-8")
    cli.chmod(0o755)
    (runtime / "node_modules").mkdir()


def _write_complete_context7(runtime: Path) -> None:
    cli = runtime / "node_modules" / ".bin" / "ctx7"
    cli.parent.mkdir(parents=True)
    cli.write_text("#!/usr/bin/env node\n", encoding="utf-8")
    cli.chmod(0o755)


def test_codegraph_uses_shared_runtime_when_local_is_source_only(
    tmp_path: Path,
) -> None:
    local_node_root = tmp_path / "project" / "scripts" / "node"
    local = local_node_root / "codegraph"
    local.mkdir(parents=True)
    (local / "codegraph-bridge.js").write_text("source only\n", encoding="utf-8")
    shared = tmp_path / "echelon-home" / "node" / "codegraph"
    _write_complete_codegraph(shared)

    result = _run_resolver(
        "echelon_resolve_codegraph_runtime",
        local_node_root,
        env=_isolated_env(ECHELON_HOME=str(tmp_path / "echelon-home")),
    )

    assert result.returncode == 0, result.stderr
    assert Path(result.stdout.strip()) == shared


def test_isolated_env_drops_ambient_runtime_overrides(
    tmp_path: Path, monkeypatch
) -> None:
    host = tmp_path / "host-codegraph"
    shared = tmp_path / "echelon-home/node/codegraph"
    _write_complete_codegraph(host)
    _write_complete_codegraph(shared)
    monkeypatch.setenv("ECHELON_CODEGRAPH_RUNTIME_DIR", str(host))
    monkeypatch.setenv(
        "ECHELON_PERLGRAPH_RUNTIME_DIR", str(tmp_path / "host-perlgraph")
    )

    env = _isolated_env(ECHELON_HOME=str(tmp_path / "echelon-home"))
    result = _run_resolver(
        "echelon_resolve_codegraph_runtime",
        tmp_path / "project/scripts/node",
        env=env,
    )

    assert "ECHELON_CODEGRAPH_RUNTIME_DIR" not in env
    assert "ECHELON_PERLGRAPH_RUNTIME_DIR" not in env
    assert result.returncode == 0, result.stderr
    assert Path(result.stdout.strip()) == shared


def test_codegraph_uses_shared_runtime_when_local_contract_is_stale(
    tmp_path: Path,
) -> None:
    local_node_root = tmp_path / "project" / "scripts" / "node"
    local = local_node_root / "codegraph"
    shared = tmp_path / "echelon-home" / "node" / "codegraph"
    _write_complete_codegraph(local)
    _write_complete_codegraph(shared)
    (local / "package.json").write_text("{}\n", encoding="utf-8")

    result = _run_resolver(
        "echelon_resolve_codegraph_runtime",
        local_node_root,
        env=_isolated_env(ECHELON_HOME=str(tmp_path / "echelon-home")),
    )

    assert result.returncode == 0, result.stderr
    assert Path(result.stdout.strip()) == shared


def test_codegraph_uses_shared_runtime_when_local_sdk_version_is_wrong(
    tmp_path: Path,
) -> None:
    local_node_root = tmp_path / "project/scripts/node"
    local = local_node_root / "codegraph"
    shared = tmp_path / "echelon-home/node/codegraph"
    _write_complete_codegraph(local)
    _write_complete_codegraph(shared)
    (local / "node_modules/@colbymchenry/codegraph/package.json").write_text(
        '{"version":"1.4.0"}\n', encoding="utf-8"
    )

    result = _run_resolver(
        "echelon_resolve_codegraph_runtime",
        local_node_root,
        env=_isolated_env(ECHELON_HOME=str(tmp_path / "echelon-home")),
    )

    assert result.returncode == 0, result.stderr
    assert Path(result.stdout.strip()) == shared


def test_perlgraph_complete_local_runtime_wins_over_shared(tmp_path: Path) -> None:
    local_node_root = tmp_path / "project" / "scripts" / "node"
    local = local_node_root / "perlgraph"
    shared = tmp_path / "echelon-home" / "node" / "perlgraph"
    _write_complete_perlgraph(local)
    _write_complete_perlgraph(shared)

    result = _run_resolver(
        "echelon_resolve_perlgraph_runtime",
        local_node_root,
        env=_isolated_env(ECHELON_HOME=str(tmp_path / "echelon-home")),
    )

    assert result.returncode == 0, result.stderr
    assert Path(result.stdout.strip()) == local


def test_explicit_incomplete_codegraph_override_fails_without_fallback(
    tmp_path: Path,
) -> None:
    local_node_root = tmp_path / "project" / "scripts" / "node"
    incomplete = tmp_path / "incomplete-codegraph"
    incomplete.mkdir()
    shared = tmp_path / "echelon-home" / "node" / "codegraph"
    _write_complete_codegraph(shared)

    result = _run_resolver(
        "echelon_resolve_codegraph_runtime",
        local_node_root,
        env=_isolated_env(
            ECHELON_HOME=str(tmp_path / "echelon-home"),
            ECHELON_CODEGRAPH_RUNTIME_DIR=str(incomplete),
        ),
    )

    assert result.returncode != 0
    assert "ECHELON_CODEGRAPH_RUNTIME_DIR" in result.stderr
    assert not result.stdout


def test_echelon_home_relocates_context7_runtime(tmp_path: Path) -> None:
    local_node_root = tmp_path / "project" / "scripts" / "node"
    shared = tmp_path / "custom-home" / "node" / "context7"
    _write_complete_context7(shared)

    result = _run_resolver(
        "echelon_resolve_context7_runtime",
        local_node_root,
        env=_isolated_env(ECHELON_HOME=str(tmp_path / "custom-home")),
    )

    assert result.returncode == 0, result.stderr
    assert Path(result.stdout.strip()) == shared
