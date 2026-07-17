"""Contracts for ARCHITECT's Context7 CLI tool integration."""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ARCHITECT = ROOT / "extension" / "agents" / "solution" / "architect.md"
PHASE = ROOT / "extension" / "workflow" / "phases" / "phase3-how.md"
CTX7_NODE_DIR = ROOT / "extension" / "scripts" / "node" / "context7"
CTX7_WRAPPER = ROOT / "extension" / "scripts" / "bash" / "context7-docs.sh"
NODE_RUNTIME_RESOLVER = (
    ROOT / "extension" / "scripts" / "bash" / "node-runtime-resolver.sh"
)


def test_context7_cli_runtime_is_pinned_and_extension_local() -> None:
    package = json.loads((CTX7_NODE_DIR / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((CTX7_NODE_DIR / "package-lock.json").read_text(encoding="utf-8"))

    assert package["private"] is True
    assert package["dependencies"]["ctx7"] == "0.5.3"
    assert lock["packages"][""]["dependencies"]["ctx7"] == "0.5.3"
    assert lock["packages"]["node_modules/ctx7"]["version"] == "0.5.3"
    assert lock["packages"]["node_modules/ctx7"]["bin"]["ctx7"] == "dist/index.js"


def test_install_script_installs_context7_with_npm_ci() -> None:
    install_script = (ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")

    assert 'NODE_RUNTIME_ROOT="${ECHELON_HOME:-$HOME/.echelon}/node"' in install_script
    assert 'CTX7_SOURCE_DIR="$ECHELON_DIR/extension/scripts/node/context7"' in install_script
    assert 'CTX7_NODE_DIR="$NODE_RUNTIME_ROOT/context7"' in install_script
    assert (
        '_refresh_node_runtime "$CTX7_SOURCE_DIR" "$CTX7_NODE_DIR" dist'
        in install_script
    )
    assert '_npm_ci_in_runtime "$CTX7_NODE_DIR"' in install_script
    assert 'npm ci --prefix "$CTX7_NODE_DIR"' not in install_script
    assert "Context7 CLI dependencies installed" in install_script
    assert "context7-mcp" not in install_script


def test_context7_wrapper_execs_extension_local_ctx7() -> None:
    text = CTX7_WRAPPER.read_text(encoding="utf-8")
    mode = CTX7_WRAPPER.stat().st_mode

    assert mode & stat.S_IXUSR
    assert "node-runtime-resolver.sh" in text
    assert "echelon_resolve_context7_runtime" in text
    assert 'CTX7_NODE_DIR="$(dirname "$SCRIPT_DIR")/node/context7"' in text
    assert "SHARED_CTX7_BIN=" not in text
    assert "echelon.context7.v1" in text
    assert '"result": result' in text
    assert 'exec "$CTX7_BIN" "$@"' in text
    assert 'NEW_ID="$(sed -n' in text
    assert '"$CTX7_BIN" docs "$NEW_ID" "$QUERY" "$@"' in text
    assert "context7-mcp" not in text


def test_context7_wrapper_normalizes_json_envelope(tmp_path: Path) -> None:
    fake_ctx7 = tmp_path / "ctx7"
    fake_ctx7.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  library)
    printf '[{"id":"/fake/lib","title":"FakeLib"}]\\n'
    ;;
  docs)
    if [[ "${2:-}" == "/old/lib" ]]; then
      printf 'New ID: /fake/lib\\n'
      exit 1
    fi
    printf '{"codeSnippets":[],"infoSnippets":[{"text":"current docs"}]}\\n'
    ;;
  *)
    echo "unsupported" >&2
    exit 2
    ;;
esac
""",
        encoding="utf-8",
    )
    fake_ctx7.chmod(0o755)
    env = {**os.environ, "ECHELON_CONTEXT7_BIN": str(fake_ctx7)}

    library_proc = subprocess.run(
        [str(CTX7_WRAPPER), "library", "fake lib", "--json"],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    library_payload = json.loads(library_proc.stdout)

    assert library_payload == {
        "schema": "echelon.context7.v1",
        "ok": True,
        "command": "library",
        "query": "fake lib",
        "library_id": None,
        "redirected_from": None,
        "result": [{"id": "/fake/lib", "title": "FakeLib"}],
    }

    docs_proc = subprocess.run(
        [str(CTX7_WRAPPER), "docs", "/old/lib", "cleanup guidance", "--json"],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    docs_payload = json.loads(docs_proc.stdout)

    assert docs_payload == {
        "schema": "echelon.context7.v1",
        "ok": True,
        "command": "docs",
        "query": "cleanup guidance",
        "library_id": "/fake/lib",
        "redirected_from": "/old/lib",
        "result": {
            "codeSnippets": [],
            "infoSnippets": [{"text": "current docs"}],
        },
    }


def test_deployed_context7_wrapper_uses_shared_installed_runtime(tmp_path: Path) -> None:
    deployed_wrapper = (
        tmp_path
        / "project"
        / ".specify"
        / "extensions"
        / "echelon"
        / "scripts"
        / "bash"
        / "context7-docs.sh"
    )
    deployed_wrapper.parent.mkdir(parents=True)
    shutil.copy2(CTX7_WRAPPER, deployed_wrapper)
    shutil.copy2(NODE_RUNTIME_RESOLVER, deployed_wrapper.parent)

    shared_ctx7 = (
        tmp_path
        / "home"
        / ".echelon"
        / "node"
        / "context7"
        / "node_modules"
        / ".bin"
        / "ctx7"
    )
    shared_ctx7.parent.mkdir(parents=True)
    shared_ctx7.write_text(
        "#!/usr/bin/env bash\nprintf '[{\"id\":\"/fake/shared\",\"title\":\"Shared runtime\"}]\\n'\n",
        encoding="utf-8",
    )
    shared_ctx7.chmod(0o755)

    proc = subprocess.run(
        [str(deployed_wrapper), "library", "shared runtime", "--json"],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "HOME": str(tmp_path / "home")},
    )

    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert payload["result"] == [{"id": "/fake/shared", "title": "Shared runtime"}]


def test_architect_uses_context7_cli_wrapper_not_mcp_names() -> None:
    for path in (ARCHITECT, PHASE):
        text = path.read_text(encoding="utf-8")
        assert "context7-docs.sh library" in text
        assert "context7-docs.sh docs" in text
        assert "echelon.context7.v1" in text
        assert "result" in text
        assert "mcp__plugin_context7_context7__resolve-library-id" not in text
        assert "query-docs" not in text
        assert "Context7 MCP" not in text
