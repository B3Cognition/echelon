"""Resolve installer-managed Node runtimes for primary-workspace commands."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Callable


class NodeRuntimeResolutionError(RuntimeError):
    """Raised when no complete runtime exists at an allowed location."""


@dataclass(frozen=True)
class _RuntimeSpec:
    display_name: str
    directory_name: str
    override_name: str
    entrypoint: Path
    is_ready: Callable[[Path], bool]


def _codegraph_is_ready(runtime: Path) -> bool:
    sdk_package_path = (
        runtime
        / "node_modules"
        / "@colbymchenry"
        / "codegraph"
        / "package.json"
    )
    if not (
        (runtime / "codegraph-bridge.js").is_file()
        and (runtime / "codegraph-adapter.js").is_file()
        and sdk_package_path.is_file()
    ):
        return False
    try:
        package = json.loads((runtime / "package.json").read_text(encoding="utf-8"))
        sdk_package = json.loads(sdk_package_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (
        package.get("echelon_runtime")
        == {
            "provider_artifact_schema_version": 2,
            "exact_relationship_endpoints": True,
            "uncapped_symbols": True,
        }
        and sdk_package.get("version") == "1.4.1"
    )


def _perlgraph_is_ready(runtime: Path) -> bool:
    cli = runtime / "dist" / "cli" / "perlgraph.js"
    return cli.is_file() and os.access(cli, os.X_OK) and (runtime / "node_modules").is_dir()


_CODEGRAPH = _RuntimeSpec(
    display_name="CodeGraph",
    directory_name="codegraph",
    override_name="ECHELON_CODEGRAPH_RUNTIME_DIR",
    entrypoint=Path("codegraph-bridge.js"),
    is_ready=_codegraph_is_ready,
)

_PERLGRAPH = _RuntimeSpec(
    display_name="PerlGraph",
    directory_name="perlgraph",
    override_name="ECHELON_PERLGRAPH_RUNTIME_DIR",
    entrypoint=Path("dist/cli/perlgraph.js"),
    is_ready=_perlgraph_is_ready,
)


def resolve_codegraph_bridge(
    project_root: Path,
    *,
    env: Mapping[str, str] | None = None,
) -> Path:
    """Return the bridge from a complete deployed or shared CodeGraph runtime."""
    return _resolve_entrypoint(project_root, _CODEGRAPH, env=env)


def resolve_perlgraph_cli(
    project_root: Path,
    *,
    env: Mapping[str, str] | None = None,
) -> Path:
    """Return the CLI from a complete deployed or shared PerlGraph runtime."""
    return _resolve_entrypoint(project_root, _PERLGRAPH, env=env)


def _resolve_entrypoint(
    project_root: Path,
    spec: _RuntimeSpec,
    *,
    env: Mapping[str, str] | None,
) -> Path:
    environment = os.environ if env is None else env
    override = environment.get(spec.override_name)
    if override:
        runtime = Path(override).expanduser()
        if spec.is_ready(runtime):
            return runtime / spec.entrypoint
        raise NodeRuntimeResolutionError(
            f"{spec.display_name} runtime override {spec.override_name} is incomplete: "
            f"{runtime}\nRerun Echelon's installer or correct the explicit override."
        )

    local_runtime = (
        project_root.resolve()
        / ".echelon"
        / "runtime"
        / "scripts"
        / "node"
        / spec.directory_name
    )
    shared_runtime = _echelon_home(environment) / "node" / spec.directory_name
    for runtime in (local_runtime, shared_runtime):
        if spec.is_ready(runtime):
            return runtime / spec.entrypoint

    raise NodeRuntimeResolutionError(
        f"{spec.display_name} runtime is unavailable.\n"
        f"Checked local runtime: {local_runtime}\n"
        f"Checked shared runtime: {shared_runtime}\n"
        "Run Echelon's installer: bash <echelon-checkout>/scripts/install.sh"
    )


def _echelon_home(env: Mapping[str, str]) -> Path:
    if env.get("ECHELON_HOME"):
        return Path(env["ECHELON_HOME"]).expanduser()
    if env.get("HOME"):
        return Path(env["HOME"]).expanduser() / ".echelon"
    return Path.home() / ".echelon"
