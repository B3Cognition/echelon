"""Atomic lifecycle operations for Echelon's generated human wiki."""

from __future__ import annotations

import json
import shutil
import tempfile
import uuid
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal

from echelon.wiki.catalog_source import WikiCatalogSource, wiki_catalog_source
from echelon.wiki.discovery import SCHEMA_VERSION, canonical_input_hashes, discover_wiki_model
from echelon.wiki.render import RenderResult, WikiRenderError, render_wiki
from echelon.wiki.operations import render_operations
from echelon.telemetry.re_adapter import operational_input_hashes
from harness.config import get_full_resolved_config


GENERATOR_VERSION = 1
MANIFEST_NAME = "manifest.json"
MANIFEST_MARKER = "echelon_human_wiki"


class WikiBuildError(RuntimeError):
    """Raised when a vault cannot be built or safely published."""


class WikiCleanError(RuntimeError):
    """Raised when cleanup cannot prove it owns the target directory."""


@dataclass(frozen=True)
class WikiBuildResult:
    output_dir: Path
    home_path: Path
    input_count: int
    output_count: int
    warning_count: int
    catalog_branch: str | None
    catalog_revision: str | None


@dataclass(frozen=True)
class WikiStatusResult:
    state: Literal["absent", "fresh", "stale", "invalid"]
    output_dir: Path
    workspace_revision: str | None
    workspace_dirty: bool
    added_inputs: tuple[str, ...]
    changed_inputs: tuple[str, ...]
    removed_inputs: tuple[str, ...]
    message: str
    operational_stale: bool = False
    operational_added_inputs: tuple[str, ...] = ()
    operational_changed_inputs: tuple[str, ...] = ()
    operational_removed_inputs: tuple[str, ...] = ()


def wiki_output_dir(project_root: Path) -> Path:
    return project_root.resolve() / ".echelon/runtime/wiki"


def _utc_iso(value: datetime) -> str:
    normalized = value.astimezone(timezone.utc).replace(microsecond=0)
    return normalized.isoformat().replace("+00:00", "Z")


def _manifest_path(output_dir: Path) -> Path:
    return output_dir / MANIFEST_NAME


def _load_valid_manifest(output_dir: Path) -> dict[str, object] | None:
    path = _manifest_path(output_dir)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    if data.get(MANIFEST_MARKER) is not True:
        return None
    if data.get("schema_version") != SCHEMA_VERSION:
        return None
    inputs = data.get("inputs")
    outputs = data.get("outputs")
    if not isinstance(inputs, dict) or not isinstance(outputs, list):
        return None
    return data


def _manifest_payload(
    source: WikiCatalogSource,
    generated_at: str,
    inputs: dict[str, str],
    render_result: RenderResult,
    model,
    operational_inputs: dict[str, str],
    include_runs: bool,
) -> dict[str, object]:
    return {
        MANIFEST_MARKER: True,
        "schema_version": SCHEMA_VERSION,
        "generator_version": GENERATOR_VERSION,
        "generated_at": generated_at,
        "catalog_branch": source.branch,
        "workspace_revision": source.revision,
        "workspace_dirty": source.dirty,
        "inputs": dict(sorted(inputs.items())),
        "canonical_inputs": dict(sorted(inputs.items())),
        "operational_inputs": dict(sorted(operational_inputs.items())),
        "operational_included": include_runs,
        "outputs": list(render_result.output_pages),
        "relationships": [asdict(edge) for edge in model.relationships],
        "warnings": [asdict(warning) for warning in render_result.warnings],
    }


def _write_manifest(path: Path, payload: dict[str, object]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _publish_staging(staging: Path, output: Path) -> None:
    backup: Path | None = None
    if output.exists():
        if _load_valid_manifest(output) is None:
            raise WikiBuildError(
                f"refusing to replace directory without a valid Echelon wiki manifest: {output}"
            )
        backup = output.parent / f".wiki-backup-{uuid.uuid4().hex}"
        output.rename(backup)
    try:
        staging.rename(output)
    except Exception:
        if backup is not None and backup.exists() and not output.exists():
            backup.rename(output)
        raise
    if backup is not None:
        shutil.rmtree(backup)


def build_wiki(
    project_root: Path,
    *,
    now: Callable[[], datetime] | None = None,
    include_runs: bool | None = None,
) -> WikiBuildResult:
    """Build and atomically publish a complete local human wiki vault."""
    root = project_root.resolve()
    now = now or (lambda: datetime.now(timezone.utc))
    generated_at = _utc_iso(now())
    output = wiki_output_dir(root)
    runtime = output.parent
    runtime.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".wiki-staging-", dir=runtime))
    resolved = get_full_resolved_config(root)
    wiki_config = resolved.get("wiki") if isinstance(resolved.get("wiki"), dict) else {}
    resolved_include_runs = (
        bool(wiki_config.get("include_run_analysis", False))
        if include_runs is None
        else include_runs
    )
    operational_inputs: dict[str, str] = {}
    try:
        with wiki_catalog_source(root) as source:
            model = replace(
                discover_wiki_model(source.source_root, generated_at=generated_at),
                workspace_name=root.name,
                workspace_root=str(root),
            )
            inputs = canonical_input_hashes(
                source.source_root, artifacts=model.artifacts
            )
            render_result = render_wiki(model, source.source_root, staging)
            if resolved_include_runs:
                operation_pages = render_operations(root, staging)
                render_result = replace(
                    render_result,
                    output_pages=tuple(
                        sorted(set(render_result.output_pages) | set(operation_pages))
                    ),
                )
                operational_inputs = operational_input_hashes(root / "runs")
            broken_required = [
                warning
                for warning in render_result.warnings
                if warning.code == "broken-link"
                and warning.source_path in render_result.required_pages
            ]
            if broken_required:
                raise WikiRenderError(broken_required[0].message)
            payload = _manifest_payload(
                source,
                generated_at,
                inputs,
                render_result,
                model,
                operational_inputs,
                resolved_include_runs,
            )
            _write_manifest(_manifest_path(staging), payload)
            catalog_branch = source.branch
            catalog_revision = source.revision
        _publish_staging(staging, output)
    except Exception as exc:
        if staging.exists():
            shutil.rmtree(staging)
        if isinstance(exc, WikiBuildError):
            raise
        raise WikiBuildError(str(exc)) from exc
    return WikiBuildResult(
        output_dir=output,
        home_path=output / "Home.md",
        input_count=len(inputs),
        output_count=len(render_result.output_pages) + 1,
        warning_count=len(render_result.warnings),
        catalog_branch=catalog_branch,
        catalog_revision=catalog_revision,
    )


def wiki_status(project_root: Path) -> WikiStatusResult:
    """Compare the current canonical inputs with the last valid manifest."""
    root = project_root.resolve()
    output = wiki_output_dir(root)
    with wiki_catalog_source(root) as source:
        revision = source.revision
        dirty = source.dirty
        if not output.exists():
            return WikiStatusResult(
                "absent", output, revision, dirty, (), (), (), "Run `echelon wiki build`."
            )
        manifest = _load_valid_manifest(output)
        if manifest is None:
            return WikiStatusResult(
                "invalid",
                output,
                revision,
                dirty,
                (),
                (),
                (),
                "The output directory is not a valid Echelon wiki; inspect it before removal.",
            )
        previous_raw = manifest.get("canonical_inputs", manifest["inputs"])
        assert isinstance(previous_raw, dict)
        previous = {str(key): str(value) for key, value in previous_raw.items()}
        current = canonical_input_hashes(source.source_root)
        added = tuple(sorted(set(current) - set(previous)))
        removed = tuple(sorted(set(previous) - set(current)))
        changed = tuple(
            sorted(
                path
                for path in set(current) & set(previous)
                if current[path] != previous[path]
            )
        )
        previous_operational_raw = manifest.get("operational_inputs", {})
        previous_operational = (
            {str(key): str(value) for key, value in previous_operational_raw.items()}
            if isinstance(previous_operational_raw, dict)
            else {}
        )
        current_operational = (
            operational_input_hashes(root / "runs")
            if manifest.get("operational_included") is True
            else {}
        )
        operational_added = tuple(
            sorted(set(current_operational) - set(previous_operational))
        )
        operational_removed = tuple(
            sorted(set(previous_operational) - set(current_operational))
        )
        operational_changed = tuple(
            sorted(
                path
                for path in set(current_operational) & set(previous_operational)
                if current_operational[path] != previous_operational[path]
            )
        )
        operational_stale = bool(
            operational_added or operational_removed or operational_changed
        )
        stale = bool(added or removed or changed or operational_stale)
        return WikiStatusResult(
            "stale" if stale else "fresh",
            output,
            revision,
            dirty,
            added,
            changed,
            removed,
            "Run `echelon wiki build`." if stale else "Wiki inputs match the manifest.",
            operational_stale,
            operational_added,
            operational_changed,
            operational_removed,
        )


def clean_wiki(project_root: Path) -> Path | None:
    """Remove only a manifest-owned generated vault."""
    output = wiki_output_dir(project_root)
    if not output.exists():
        return None
    if _load_valid_manifest(output) is None:
        raise WikiCleanError(
            f"refusing to remove directory without a valid Echelon wiki manifest: {output}"
        )
    shutil.rmtree(output)
    return output


def capture_input_snapshot(project_root: Path) -> dict[str, str] | None:
    """Return input hashes only when a valid wiki already exists."""
    output = wiki_output_dir(project_root)
    if _load_valid_manifest(output) is None:
        return None
    with wiki_catalog_source(project_root) as source:
        return canonical_input_hashes(source.source_root)


def _auto_refresh_enabled(project_root: Path) -> bool:
    resolved = get_full_resolved_config(project_root)
    wiki = resolved.get("wiki")
    if isinstance(wiki, dict) and wiki.get("auto_refresh") is False:
        return False
    return True


def refresh_after_changed_command(
    project_root: Path,
    before: dict[str, str] | None,
    *,
    now: Callable[[], datetime] | None = None,
) -> WikiBuildResult | None:
    """Rebuild an existing vault only when this command changed its inputs."""
    if before is None or not _auto_refresh_enabled(project_root):
        return None
    with wiki_catalog_source(project_root) as source:
        after = canonical_input_hashes(source.source_root)
    before_artifacts = {
        path: digest
        for path, digest in before.items()
        if path.startswith(("specs/", "re/"))
    }
    after_artifacts = {
        path: digest
        for path, digest in after.items()
        if path.startswith(("specs/", "re/"))
    }
    if after_artifacts == before_artifacts:
        return None
    return build_wiki(project_root, now=now)
