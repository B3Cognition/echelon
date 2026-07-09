"""Target-aware reverse-engineering cache planning."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from echelon.workspace_model import SourceRoot, WorkspaceManifest
from harness.re_cache import cache_hit, cache_source_dir
from harness.re_fingerprint import ReFingerprintProfile, SourceFingerprint, fingerprint_source

RePolicy = Literal[
    "none",
    "cached-only",
    "changed",
    "target-changed",
    "target-only",
    "refresh-all",
]
RePlanAction = Literal["reuse", "refresh", "missing", "exclude"]

VALID_RE_POLICIES: set[str] = {
    "none",
    "cached-only",
    "changed",
    "target-changed",
    "target-only",
    "refresh-all",
}


class RePlanError(ValueError):
    """Raised when RE planning inputs are invalid."""


@dataclass(frozen=True)
class RePlanSource:
    id: str
    path: str
    absolute_path: str
    action: RePlanAction
    fingerprint: SourceFingerprint
    cache_path: str
    dirty: bool
    selected: bool

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "path": self.path,
            "absolute_path": self.absolute_path,
            "action": self.action,
            "fingerprint": {
                "value": self.fingerprint.value,
                "kind": self.fingerprint.kind,
                "dirty": self.fingerprint.dirty,
                "profile_hash": self.fingerprint.profile_hash,
                "git_head": self.fingerprint.git_head,
            },
            "cache_path": self.cache_path,
            "dirty": self.dirty,
            "selected": self.selected,
        }


@dataclass(frozen=True)
class ReExecutionPlan:
    policy: RePolicy
    requested_policy: str
    target_source: str
    sources: tuple[RePlanSource, ...]
    forbidden_source_roots: list[str]
    profile: ReFingerprintProfile

    @property
    def refresh_sources_count(self) -> int:
        return sum(1 for source in self.sources if source.action == "refresh")

    @property
    def selected_sources(self) -> tuple[RePlanSource, ...]:
        return tuple(source for source in self.sources if source.selected)

    @property
    def refresh_sources(self) -> tuple[RePlanSource, ...]:
        return tuple(source for source in self.sources if source.action == "refresh")

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "policy": self.policy,
            "requested_policy": self.requested_policy,
            "target_source": self.target_source,
            "refresh_sources_count": self.refresh_sources_count,
            "forbidden_source_roots": self.forbidden_source_roots,
            "profile": {
                "profile": self.profile.profile,
                "depth": self.profile.depth,
                "max_lines_per_file": self.profile.max_lines_per_file,
                "git_history_limit": self.profile.git_history_limit,
                "codegraph_version": self.profile.codegraph_version,
            },
            "sources": [source.to_json_dict() for source in self.sources],
        }


def resolve_re_policy(target_source: str, requested_policy: str) -> RePolicy:
    """Resolve default and explicit RE policy names."""
    requested = requested_policy.strip()
    if not requested:
        return "target-changed" if target_source.strip() else "changed"
    if requested not in VALID_RE_POLICIES:
        raise RePlanError(
            f"invalid re-policy {requested!r}; expected one of: "
            f"{', '.join(sorted(VALID_RE_POLICIES))}"
        )
    return requested  # type: ignore[return-value]


def build_re_execution_plan(
    *,
    project_root: Path,
    manifest: WorkspaceManifest,
    cache_root: Path,
    target_source: str,
    requested_policy: str,
    profile: ReFingerprintProfile,
) -> ReExecutionPlan:
    """Build a per-source RE execution plan."""
    root = project_root.resolve()
    target = _resolve_target_source(manifest.sources, target_source)
    policy = resolve_re_policy(target.id if target is not None else "", requested_policy)
    forbidden_roots: list[str] = []
    planned: list[RePlanSource] = []

    for source in manifest.sources:
        absolute_path = _source_absolute_path(root, source)
        fingerprint = fingerprint_source(absolute_path, profile)
        hit = cache_hit(cache_root, source.id, fingerprint)
        selected = _source_selected(policy, source, target)
        if not selected:
            action: RePlanAction = "exclude"
        elif policy == "none":
            action = "exclude"
            selected = False
        elif policy == "refresh-all":
            action = "refresh"
        elif policy == "cached-only" and not hit:
            action = "missing"
        elif policy == "target-changed" and target is not None and source.id != target.id and not hit:
            action = "missing"
        elif hit:
            action = "reuse"
        else:
            action = "refresh"

        if policy == "target-only" and target is not None and source.id != target.id:
            forbidden_roots.append(str(absolute_path))

        planned.append(
            RePlanSource(
                id=source.id,
                path=source.path,
                absolute_path=str(absolute_path),
                action=action,
                fingerprint=fingerprint,
                cache_path=str(cache_source_dir(cache_root, source.id, fingerprint)),
                dirty=fingerprint.dirty,
                selected=selected,
            )
        )

    return ReExecutionPlan(
        policy=policy,
        requested_policy=requested_policy,
        target_source=target.id if target is not None else "",
        sources=tuple(planned),
        forbidden_source_roots=forbidden_roots,
        profile=profile,
    )


def _resolve_target_source(
    sources: tuple[SourceRoot, ...],
    target_source: str,
) -> SourceRoot | None:
    raw = target_source.strip()
    if not raw:
        return None
    for source in sources:
        if raw in {source.id, source.path}:
            return source
    raise RePlanError(f"target source {raw!r} is not declared in workspace sources")


def _source_absolute_path(root: Path, source: SourceRoot) -> Path:
    path = Path(source.path)
    return path if path.is_absolute() else root / path


def _source_selected(policy: RePolicy, source: SourceRoot, target: SourceRoot | None) -> bool:
    if policy == "none":
        return False
    if policy == "target-only":
        return target is not None and source.id == target.id
    return True
