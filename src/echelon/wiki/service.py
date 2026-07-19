"""Atomic lifecycle operations for Echelon's generated human wiki."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal

from echelon.wiki.discovery import SCHEMA_VERSION, canonical_input_hashes, discover_wiki_model
from echelon.wiki.render import RenderResult, WikiRenderError, render_wiki
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


def wiki_output_dir(project_root: Path) -> Path:
    return project_root.resolve() / ".echelon/runtime/wiki"


def _utc_iso(value: datetime) -> str:
    normalized = value.astimezone(timezone.utc).replace(microsecond=0)
    return normalized.isoformat().replace("+00:00", "Z")


def _git(project_root: Path, args: list[str]) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=project_root,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _git_revision(project_root: Path) -> str | None:
    return _git(project_root, ["rev-parse", "HEAD"])


def _git_dirty(project_root: Path) -> bool:
    output = _git(project_root, ["status", "--porcelain", "--", "specs", "re"])
    return bool(output)


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
    project_root: Path,
    generated_at: str,
    inputs: dict[str, str],
    render_result: RenderResult,
    model,
) -> dict[str, object]:
    return {
        MANIFEST_MARKER: True,
        "schema_version": SCHEMA_VERSION,
        "generator_version": GENERATOR_VERSION,
        "generated_at": generated_at,
        "workspace_revision": _git_revision(project_root),
        "workspace_dirty": _git_dirty(project_root),
        "inputs": dict(sorted(inputs.items())),
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
) -> WikiBuildResult:
    """Build and atomically publish a complete local human wiki vault."""
    root = project_root.resolve()
    now = now or (lambda: datetime.now(timezone.utc))
    generated_at = _utc_iso(now())
    output = wiki_output_dir(root)
    runtime = output.parent
    runtime.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".wiki-staging-", dir=runtime))
    try:
        inputs = canonical_input_hashes(root)
        model = discover_wiki_model(root, generated_at=generated_at)
        render_result = render_wiki(model, root, staging)
        broken_required = [
            warning
            for warning in render_result.warnings
            if warning.code == "broken-link" and warning.source_path in render_result.required_pages
        ]
        if broken_required:
            raise WikiRenderError(broken_required[0].message)
        payload = _manifest_payload(root, generated_at, inputs, render_result, model)
        _write_manifest(_manifest_path(staging), payload)
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
    )


def wiki_status(project_root: Path) -> WikiStatusResult:
    """Compare the current canonical inputs with the last valid manifest."""
    root = project_root.resolve()
    output = wiki_output_dir(root)
    revision = _git_revision(root)
    dirty = _git_dirty(root)
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
    previous_raw = manifest["inputs"]
    assert isinstance(previous_raw, dict)
    previous = {str(key): str(value) for key, value in previous_raw.items()}
    current = canonical_input_hashes(root)
    added = tuple(sorted(set(current) - set(previous)))
    removed = tuple(sorted(set(previous) - set(current)))
    changed = tuple(
        sorted(path for path in set(current) & set(previous) if current[path] != previous[path])
    )
    stale = bool(added or removed or changed)
    return WikiStatusResult(
        "stale" if stale else "fresh",
        output,
        revision,
        dirty,
        added,
        changed,
        removed,
        "Run `echelon wiki build`." if stale else "Wiki inputs match the manifest.",
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
    return canonical_input_hashes(project_root)


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
    after = canonical_input_hashes(project_root)
    if after == before:
        return None
    return build_wiki(project_root, now=now)
