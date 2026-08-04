"""Target-aware reverse-engineering cache planning."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Mapping

from echelon.workspace_model import SourceRoot, WorkspaceManifest
from harness.re_cache import cache_source_dir
from harness.re_fingerprint import ReFingerprintProfile, SourceFingerprint, fingerprint_source
from harness.re_registry import (
    PublishedReIndex,
    published_source_is_current,
    published_source_is_usable,
)
from harness.re_quality_contract import QUALITY_CONTRACT_VERSION

RePolicy = Literal[
    "none",
    "cached-only",
    "changed",
    "target-changed",
    "target-only",
    "refresh-all",
]
RePlanAction = Literal["reuse", "refresh", "missing", "exclude", "skip-empty"]
ReSourceClassification = Literal["current", "refresh", "empty", "unavailable"]

VALID_RE_POLICIES: set[str] = {
    "none",
    "cached-only",
    "changed",
    "target-changed",
    "target-only",
    "refresh-all",
}
VALID_RE_ACTIONS = {"reuse", "refresh", "missing", "exclude", "skip-empty"}
VALID_RE_CLASSIFICATIONS = {"current", "refresh", "empty", "unavailable"}
_SAFE_SOURCE_ID = re.compile(r"^[A-Za-z0-9._-]+$")


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
    classification: ReSourceClassification

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "path": self.path,
            "absolute_path": self.absolute_path,
            "action": self.action,
            "fingerprint": self.fingerprint.to_json_dict(),
            "cache_path": self.cache_path,
            "dirty": self.dirty,
            "selected": self.selected,
            "classification": self.classification,
        }

    @classmethod
    def from_json_dict(cls, data: Mapping[str, object]) -> "RePlanSource":
        source_id = _required_string(data, "id")
        if not _SAFE_SOURCE_ID.fullmatch(source_id):
            raise RePlanError(f"invalid source ID: {source_id!r}")
        action = data.get("action")
        if action not in VALID_RE_ACTIONS:
            raise RePlanError(f"invalid RE action for {source_id}: {action!r}")
        fingerprint_raw = data.get("fingerprint")
        if not isinstance(fingerprint_raw, Mapping):
            raise RePlanError(f"fingerprint for {source_id} must be an object")
        try:
            fingerprint = SourceFingerprint.from_json_dict(fingerprint_raw)
        except ValueError as exc:
            raise RePlanError(f"invalid fingerprint for {source_id}: {exc}") from exc
        dirty = data.get("dirty")
        selected = data.get("selected")
        if not isinstance(dirty, bool) or not isinstance(selected, bool):
            raise RePlanError(f"dirty and selected must be booleans for {source_id}")
        if dirty != fingerprint.dirty:
            raise RePlanError(f"dirty flag mismatch for {source_id}")
        classification = data.get("classification")
        if classification is None:
            classification = _classification_from_action(action)
        if classification not in VALID_RE_CLASSIFICATIONS:
            raise RePlanError(
                f"invalid RE classification for {source_id}: {classification!r}"
            )
        return cls(
            id=source_id,
            path=_required_string(data, "path"),
            absolute_path=_required_string(data, "absolute_path"),
            action=action,
            fingerprint=fingerprint,
            cache_path=_required_string(data, "cache_path"),
            dirty=dirty,
            selected=selected,
            classification=classification,
        )


@dataclass(frozen=True)
class ReExecutionPlan:
    policy: RePolicy
    requested_policy: str
    target_source: str
    sources: tuple[RePlanSource, ...]
    forbidden_source_roots: list[str]
    profile: ReFingerprintProfile
    removed_sources: tuple[str, ...] = ()
    analysis_required: bool = False
    workspace_synthesis_required: bool = False
    publication_required: bool = False

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
            "profile": self.profile.to_json_dict(),
            "sources": [source.to_json_dict() for source in self.sources],
            "removed_sources": list(self.removed_sources),
            "analysis_required": self.analysis_required,
            "workspace_synthesis_required": self.workspace_synthesis_required,
            "publication_required": self.publication_required,
        }

    @classmethod
    def from_json_dict(cls, data: Mapping[str, object]) -> "ReExecutionPlan":
        schema_version = data.get("schema_version")
        if schema_version != 1:
            raise RePlanError(f"unsupported RE plan schema_version: {schema_version!r}")
        policy = data.get("policy")
        if policy not in VALID_RE_POLICIES:
            raise RePlanError(f"invalid RE plan policy: {policy!r}")
        profile_raw = data.get("profile")
        if not isinstance(profile_raw, Mapping):
            raise RePlanError("RE plan profile must be an object")
        try:
            profile = ReFingerprintProfile.from_json_dict(profile_raw)
        except ValueError as exc:
            raise RePlanError(f"invalid RE profile: {exc}") from exc

        raw_sources = data.get("sources")
        if not isinstance(raw_sources, list):
            raise RePlanError("RE plan sources must be a list")
        sources: list[RePlanSource] = []
        seen: set[str] = set()
        for raw_source in raw_sources:
            if not isinstance(raw_source, Mapping):
                raise RePlanError("RE plan source must be an object")
            source = RePlanSource.from_json_dict(raw_source)
            if source.id in seen:
                raise RePlanError(f"duplicate source ID in RE plan: {source.id}")
            if (
                source.classification != "unavailable"
                and source.fingerprint.profile_hash != profile.profile_hash()
            ):
                raise RePlanError(f"profile hash mismatch for source {source.id}")
            seen.add(source.id)
            sources.append(source)

        raw_forbidden = data.get("forbidden_source_roots", [])
        if not isinstance(raw_forbidden, list) or any(
            not isinstance(item, str) for item in raw_forbidden
        ):
            raise RePlanError("forbidden_source_roots must be a list of strings")
        raw_removed = data.get("removed_sources", [])
        if not isinstance(raw_removed, list) or any(
            not isinstance(item, str) or not _SAFE_SOURCE_ID.fullmatch(item)
            for item in raw_removed
        ):
            raise RePlanError("removed_sources must contain safe source IDs")

        derived_analysis = any(source.action == "refresh" for source in sources)
        derived_synthesis = derived_analysis or bool(raw_removed) or any(
            source.action == "skip-empty" for source in sources
        )
        analysis_required = _optional_bool(data, "analysis_required", derived_analysis)
        synthesis_required = _optional_bool(
            data, "workspace_synthesis_required", derived_synthesis
        )
        publication_required = _optional_bool(
            data, "publication_required", synthesis_required
        )
        if publication_required and not synthesis_required:
            raise RePlanError("publication_required requires workspace synthesis")

        plan = cls(
            policy=policy,
            requested_policy=_string_value(data, "requested_policy"),
            target_source=_string_value(data, "target_source"),
            sources=tuple(sources),
            forbidden_source_roots=list(raw_forbidden),
            profile=profile,
            removed_sources=tuple(raw_removed),
            analysis_required=analysis_required,
            workspace_synthesis_required=synthesis_required,
            publication_required=publication_required,
        )
        serialized_count = data.get("refresh_sources_count")
        if serialized_count is not None and serialized_count != plan.refresh_sources_count:
            raise RePlanError("refresh_sources_count does not match source actions")
        return plan


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
    target_source: str,
    requested_policy: str,
    profile: ReFingerprintProfile,
    published_index: PublishedReIndex | None = None,
    cache_root: Path | None = None,
    force_selected_refresh: bool = False,
    reuse_published: bool = True,
) -> ReExecutionPlan:
    """Build a per-source RE execution plan."""
    root = project_root.resolve()
    cache_root = cache_root or (root / "re" / ".cache")
    source_ids = [source.id for source in manifest.sources]
    if len(source_ids) != len(set(source_ids)):
        raise RePlanError("duplicate source IDs in workspace manifest")
    target = resolve_re_target_source(manifest.sources, target_source)
    policy = resolve_re_policy(target.id if target is not None else "", requested_policy)
    if force_selected_refresh and (target is None or policy != "target-only"):
        raise RePlanError(
            "force_selected_refresh requires target-only policy and one target source"
        )
    target_empty = target is not None and _source_empty(target)
    forbidden_roots: list[str] = []
    planned: list[RePlanSource] = []

    for source in manifest.sources:
        absolute_path = _source_absolute_path(root, source)
        source_exists = absolute_path.exists()
        published = published_index.sources.get(source.id) if published_index else None
        targeted_sibling = bool(
            force_selected_refresh
            and policy == "target-only"
            and target is not None
            and source.id != target.id
        )
        forced_reuse = bool(
            targeted_sibling
            and reuse_published
            and published is not None
            and published_index is not None
            and published_source_is_usable(root, published_index, source.id)
        )
        if forced_reuse or (not source_exists and published is not None):
            fingerprint = SourceFingerprint(
                value=published.fingerprint,
                kind="file-tree",
                dirty=False,
                profile_hash=published.profile_hash,
            )
        else:
            fingerprint = fingerprint_source(absolute_path, profile)
        source_empty = source_exists and _source_empty(source)
        current = bool(
            published_index
            and source_exists
            and published_source_is_current(
                root,
                published_index,
                source.id,
                source_path=source.path,
                fingerprint=fingerprint.value,
                profile_hash=fingerprint.profile_hash,
                expect_empty=source_empty,
                quality_contract_version=QUALITY_CONTRACT_VERSION,
            )
        )
        selected = _source_selected(policy, source, target)
        if (
            policy == "target-changed"
            and target_empty
            and target is not None
            and source.id != target.id
        ):
            selected = False
        if not selected:
            if forced_reuse:
                action: RePlanAction = "reuse"
            elif targeted_sibling:
                action = "missing"
            else:
                action = "exclude"
        elif policy == "none":
            action = "exclude"
            selected = False
        elif not source_exists:
            action = "missing"
        elif source_empty:
            reconstruct_empty = (
                not reuse_published and policy not in {"none", "cached-only"}
            )
            action = (
                "skip-empty"
                if force_selected_refresh or reconstruct_empty or not current
                else "reuse"
            )
        elif force_selected_refresh:
            action = "refresh"
        elif not reuse_published and policy not in {"none", "cached-only"}:
            action = "refresh"
        elif policy == "refresh-all":
            action = "refresh"
        elif policy == "cached-only" and not current:
            action = "missing"
        elif (
            policy == "target-changed"
            and target is not None
            and source.id != target.id
            and not current
        ):
            action = "missing"
        elif current:
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
                classification=(
                    "current"
                    if forced_reuse
                    else _source_classification(
                        source_exists=source_exists,
                        source_empty=source_empty,
                        current=current,
                    )
                ),
            )
        )

    removed_sources = (
        tuple(sorted(set(published_index.sources) - set(source_ids)))
        if (
            published_index is not None
            and policy != "none"
            and not force_selected_refresh
        )
        else ()
    )
    analysis_required = any(source.action == "refresh" for source in planned)
    workspace_synthesis_required = bool(removed_sources) or analysis_required or any(
        source.action == "skip-empty" for source in planned
    )
    return ReExecutionPlan(
        policy=policy,
        requested_policy=requested_policy,
        target_source=target.id if target is not None else "",
        sources=tuple(planned),
        forbidden_source_roots=forbidden_roots,
        profile=profile,
        removed_sources=removed_sources,
        analysis_required=analysis_required,
        workspace_synthesis_required=workspace_synthesis_required,
        publication_required=workspace_synthesis_required,
    )


def resolve_re_target_source(
    sources: tuple[SourceRoot, ...],
    target_source: str,
) -> SourceRoot | None:
    raw = target_source.strip()
    if not raw:
        return None
    selector = PurePosixPath(raw)
    if (
        "\\" in raw
        or "\x00" in raw
        or selector.is_absolute()
        or any(part == ".." for part in selector.parts)
    ):
        raise RePlanError(f"unsafe target source selector: {raw!r}")
    matches = tuple(source for source in sources if raw in {source.id, source.path})
    if len(matches) > 1:
        candidates = ", ".join(sorted(source.id for source in matches))
        raise RePlanError(
            f"ambiguous target source {raw!r}; matches declared sources: {candidates}"
        )
    if matches:
        return matches[0]
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


def _source_empty(source: SourceRoot) -> bool:
    return source.source_file_count <= 0


def _source_classification(
    *,
    source_exists: bool,
    source_empty: bool,
    current: bool,
) -> ReSourceClassification:
    if not source_exists:
        return "unavailable"
    if source_empty:
        return "empty"
    if current:
        return "current"
    return "refresh"


def _classification_from_action(action: object) -> ReSourceClassification:
    if action == "reuse":
        return "current"
    if action == "skip-empty":
        return "empty"
    return "refresh"


def _required_string(data: Mapping[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RePlanError(f"{key} must be a non-empty string")
    return value.strip()


def _string_value(data: Mapping[str, object], key: str) -> str:
    value = data.get(key, "")
    if not isinstance(value, str):
        raise RePlanError(f"{key} must be a string")
    return value


def _optional_bool(data: Mapping[str, object], key: str, default: bool) -> bool:
    value = data.get(key, default)
    if not isinstance(value, bool):
        raise RePlanError(f"{key} must be a boolean")
    return value
