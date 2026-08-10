"""Install Echelon's versioned Prosaic package sources into one workspace."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
from typing import Callable, Sequence


_CONFIG_FILENAMES = ("prosaic.config.yaml", "prosaic.config.yml", ".prosaic.yaml")


class ProsaicBundleInstallError(RuntimeError):
    """Raised before changing a workspace that owns its own Prosaic config."""


@dataclass(frozen=True)
class ProsaicBundleInstallReport:
    prose_source: Path
    runtime_source: Path


RunCommand = Callable[..., object]


def install_prosaic_bundle(
    project_root: Path,
    *,
    echelon_root: Path | None = None,
    run: RunCommand = subprocess.run,
) -> ProsaicBundleInstallReport:
    """Stage Echelon sources and deploy its prose and runtime packages.

    Prosaic deliberately resolves package source and destination paths below a
    single project root.  The staged copies are consequently retained beneath
    ``.echelon/packages`` and refreshed only by this explicit migration option.
    """

    project_root = project_root.resolve()
    source_root = _bundle_source_root(echelon_root)
    _reject_workspace_config(project_root)

    prose_source = project_root / ".echelon" / "packages" / "echelon-prose"
    runtime_source = project_root / ".echelon" / "packages" / "echelon-runtime"
    _replace_managed_tree(source_root / "prosaic", prose_source)
    _replace_managed_tree(source_root / "runtime", runtime_source)

    config_path = project_root / "prosaic.config.yaml"
    config_path.write_text(_package_config(), encoding="utf-8")
    try:
        _run(run, ["prosaic", "package", "deploy", "echelon-prose"], project_root)
        _run(run, ["prosaic", "package", "deploy", "echelon-runtime"], project_root)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ProsaicBundleInstallError(f"Prosaic package installation failed: {exc}") from exc
    finally:
        config_path.unlink(missing_ok=True)

    return ProsaicBundleInstallReport(prose_source=prose_source, runtime_source=runtime_source)


def _bundle_source_root(echelon_root: Path | None) -> Path:
    if echelon_root is not None:
        return echelon_root.resolve()

    packaged = Path(__file__).resolve().parent / "bundles"
    if (packaged / "prosaic").is_dir() and (packaged / "runtime").is_dir():
        return packaged

    return Path(__file__).resolve().parents[2]


def _reject_workspace_config(project_root: Path) -> None:
    existing = [name for name in _CONFIG_FILENAMES if (project_root / name).exists()]
    if existing:
        joined = ", ".join(existing)
        raise ProsaicBundleInstallError(
            f"Cannot install Echelon Prosaic bundles: existing Prosaic configuration at {joined}."
        )


def _replace_managed_tree(source: Path, destination: Path) -> None:
    if not source.is_dir():
        raise ProsaicBundleInstallError(f"Echelon bundle source is missing: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.with_name(f".{destination.name}.staging")
    shutil.rmtree(staging, ignore_errors=True)
    shutil.copytree(source, staging, copy_function=shutil.copy2)
    shutil.rmtree(destination, ignore_errors=True)
    staging.replace(destination)


def _package_config() -> str:
    return """packages:
  - id: echelon-prose
    sourceRoot: .echelon/packages/echelon-prose
    destinationRoot: .echelon/prosaic
  - id: echelon-runtime
    sourceRoot: .echelon/packages/echelon-runtime
    destinationRoot: .echelon/runtime
"""


def _run(run: RunCommand, command: Sequence[str], cwd: Path) -> None:
    run(list(command), cwd=cwd, check=True)
