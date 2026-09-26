"""Harness-owned proof that required provider outputs came from this dispatch."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal, Mapping


ArtifactMode = Literal["publish", "result_only", "read_only"]
ArtifactRoot = Literal["active_spec", "squad", "proposal"]
ReadRoot = Literal[
    "active_spec", "project", "squad", "context", "runtime", "staging"
]

_ARTIFACT_MODES = frozenset({"publish", "result_only", "read_only"})
_ARTIFACT_ROOTS = frozenset({"active_spec", "squad", "proposal"})
_READ_ROOTS = frozenset(
    {"active_spec", "project", "squad", "context", "runtime", "staging"}
)
_KINDS = frozenset({"file", "directory"})
_REQUIREMENTS = frozenset({"required", "optional"})


class ProviderArtifactContractError(ValueError):
    """A provider assignment declared an invalid filesystem contract."""


@dataclass(frozen=True)
class ProviderArtifactRule:
    root: ArtifactRoot
    path: str
    kind: Literal["file", "directory"]
    requirement: Literal["required", "optional"]


@dataclass(frozen=True)
class ProviderReadRule:
    root: ReadRoot
    path: str
    kind: Literal["file", "directory"]


@dataclass(frozen=True)
class ProviderArtifactContract:
    mode: ArtifactMode
    artifacts: tuple[ProviderArtifactRule, ...]
    read_inputs: tuple[ProviderReadRule, ...] = ()
    allow_shadow_recovery: bool = False


@dataclass(frozen=True)
class ResolvedProviderArtifactContract:
    assignment_id: str
    contract_sha256: str
    contract: ProviderArtifactContract
    write_paths: tuple[Path, ...]
    read_paths: tuple[Path, ...]


def compile_provider_artifact_contract(
    raw: object,
    *,
    assignment_id: str,
) -> ProviderArtifactContract:
    """Compile one strict, immutable provider filesystem contract."""
    if not isinstance(raw, dict):
        raise _contract_error(assignment_id, "contract must be a mapping")
    _reject_unknown_keys(
        raw,
        allowed={"mode", "artifacts", "read_inputs", "allow_shadow_recovery"},
        assignment_id=assignment_id,
        subject="contract",
    )
    mode = _strict_string(raw.get("mode"), assignment_id, "mode")
    if mode not in _ARTIFACT_MODES:
        raise _contract_error(assignment_id, f"unsupported mode {mode!r}")
    allow_shadow_recovery = raw.get("allow_shadow_recovery", False)
    if type(allow_shadow_recovery) is not bool:
        raise _contract_error(
            assignment_id, "allow_shadow_recovery must be a boolean"
        )
    raw_artifacts = raw.get("artifacts", [])
    raw_reads = raw.get("read_inputs", [])
    if type(raw_artifacts) is not list:
        raise _contract_error(assignment_id, "artifacts must be a list")
    if type(raw_reads) is not list:
        raise _contract_error(assignment_id, "read_inputs must be a list")
    if mode != "publish" and raw_artifacts:
        raise _contract_error(
            assignment_id, f"{mode} contracts cannot declare mutable artifacts"
        )

    artifacts = tuple(
        _compile_artifact_rule(item, assignment_id=assignment_id)
        for item in raw_artifacts
    )
    read_inputs = tuple(
        _compile_read_rule(item, assignment_id=assignment_id)
        for item in raw_reads
    )
    _reject_duplicate_or_overlapping_artifacts(
        artifacts,
        assignment_id=assignment_id,
    )
    _reject_duplicate_reads(read_inputs, assignment_id=assignment_id)
    return ProviderArtifactContract(
        mode=mode,
        artifacts=artifacts,
        read_inputs=read_inputs,
        allow_shadow_recovery=allow_shadow_recovery,
    )


def provider_artifact_contract_sha256(
    contract: ProviderArtifactContract,
) -> str:
    payload = {
        "allow_shadow_recovery": contract.allow_shadow_recovery,
        "artifacts": [
            {
                "kind": rule.kind,
                "path": rule.path,
                "requirement": rule.requirement,
                "root": rule.root,
            }
            for rule in contract.artifacts
        ],
        "mode": contract.mode,
        "read_inputs": [
            {"kind": rule.kind, "path": rule.path, "root": rule.root}
            for rule in contract.read_inputs
        ],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def resolve_provider_artifact_contract(
    contract: ProviderArtifactContract,
    *,
    roots: Mapping[str, Path],
    assignment_id: str,
) -> ResolvedProviderArtifactContract:
    write_paths = tuple(
        _resolve_beneath_root(
            roots,
            root_name=rule.root,
            relative_path=rule.path,
            assignment_id=assignment_id,
        )
        for rule in contract.artifacts
    )
    read_paths = tuple(
        _resolve_beneath_root(
            roots,
            root_name=rule.root,
            relative_path=rule.path,
            assignment_id=assignment_id,
        )
        for rule in contract.read_inputs
    )
    return ResolvedProviderArtifactContract(
        assignment_id=assignment_id,
        contract_sha256=provider_artifact_contract_sha256(contract),
        contract=contract,
        write_paths=write_paths,
        read_paths=read_paths,
    )


def permission_metadata(
    resolved_contract: ResolvedProviderArtifactContract,
) -> dict[str, object]:
    """Project a resolved contract into the provider's exact native scope."""
    read_roots: list[str] = []
    for rule, target in zip(
        resolved_contract.contract.read_inputs,
        resolved_contract.read_paths,
        strict=True,
    ):
        _append_unique(read_roots, str(_declared_root(target, rule.path)))
    for rule, target in zip(
        resolved_contract.contract.artifacts,
        resolved_contract.write_paths,
        strict=True,
    ):
        _append_unique(read_roots, str(_declared_root(target, rule.path)))
    return {
        "tool_read_roots": read_roots,
        "tool_write_paths": [str(path) for path in resolved_contract.write_paths],
        "tool_write_scope_exclusive": True,
    }


def _declared_root(target: Path, relative_path: str) -> Path:
    root = target
    for _part in PurePosixPath(relative_path).parts:
        root = root.parent
    return root


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def _compile_artifact_rule(
    raw: object,
    *,
    assignment_id: str,
) -> ProviderArtifactRule:
    if not isinstance(raw, dict):
        raise _contract_error(assignment_id, "artifact rule must be a mapping")
    _reject_unknown_keys(
        raw,
        allowed={"root", "path", "kind", "requirement"},
        assignment_id=assignment_id,
        subject="artifact rule",
    )
    root = _strict_string(raw.get("root"), assignment_id, "artifact root")
    path = _safe_relative_path(raw.get("path"), assignment_id, "artifact path")
    kind = _strict_string(raw.get("kind"), assignment_id, "artifact kind")
    requirement = _strict_string(
        raw.get("requirement"), assignment_id, "artifact requirement"
    )
    if root not in _ARTIFACT_ROOTS:
        raise _contract_error(assignment_id, f"unsupported artifact root {root!r}")
    if kind not in _KINDS:
        raise _contract_error(assignment_id, f"unsupported artifact kind {kind!r}")
    if requirement not in _REQUIREMENTS:
        raise _contract_error(
            assignment_id, f"unsupported artifact requirement {requirement!r}"
        )
    return ProviderArtifactRule(
        root=root,
        path=path,
        kind=kind,
        requirement=requirement,
    )


def _compile_read_rule(raw: object, *, assignment_id: str) -> ProviderReadRule:
    if not isinstance(raw, dict):
        raise _contract_error(assignment_id, "read rule must be a mapping")
    _reject_unknown_keys(
        raw,
        allowed={"root", "path", "kind"},
        assignment_id=assignment_id,
        subject="read rule",
    )
    root = _strict_string(raw.get("root"), assignment_id, "read root")
    path = _safe_relative_path(raw.get("path"), assignment_id, "read path")
    kind = _strict_string(raw.get("kind"), assignment_id, "read kind")
    if root not in _READ_ROOTS:
        raise _contract_error(assignment_id, f"unsupported read root {root!r}")
    if kind not in _KINDS:
        raise _contract_error(assignment_id, f"unsupported read kind {kind!r}")
    return ProviderReadRule(root=root, path=path, kind=kind)


def _reject_unknown_keys(
    raw: Mapping[object, object],
    *,
    allowed: set[str],
    assignment_id: str,
    subject: str,
) -> None:
    unknown = sorted(str(key) for key in raw if key not in allowed)
    if unknown:
        raise _contract_error(
            assignment_id, f"{subject} has unknown keys: {', '.join(unknown)}"
        )


def _strict_string(value: object, assignment_id: str, subject: str) -> str:
    if type(value) is not str or not value:
        raise _contract_error(assignment_id, f"{subject} must be a non-empty string")
    return value


def _safe_relative_path(value: object, assignment_id: str, subject: str) -> str:
    raw = _strict_string(value, assignment_id, subject)
    relative = PurePosixPath(raw)
    if (
        relative.is_absolute()
        or any(part in {"", ".", ".."} for part in relative.parts)
        or relative.as_posix() != raw
    ):
        raise _contract_error(assignment_id, f"{subject} must be a safe POSIX path")
    return raw


def _reject_duplicate_or_overlapping_artifacts(
    rules: tuple[ProviderArtifactRule, ...],
    *,
    assignment_id: str,
) -> None:
    for index, rule in enumerate(rules):
        left = PurePosixPath(rule.path)
        for other in rules[index + 1 :]:
            if rule.root != other.root:
                continue
            right = PurePosixPath(other.path)
            if left == right or left in right.parents or right in left.parents:
                raise _contract_error(
                    assignment_id,
                    f"mutable artifact targets overlap: {rule.path!r} and "
                    f"{other.path!r}",
                )


def _reject_duplicate_reads(
    rules: tuple[ProviderReadRule, ...],
    *,
    assignment_id: str,
) -> None:
    targets = [(rule.root, rule.path) for rule in rules]
    if len(targets) != len(set(targets)):
        raise _contract_error(assignment_id, "read inputs contain duplicate targets")


def _resolve_beneath_root(
    roots: Mapping[str, Path],
    *,
    root_name: str,
    relative_path: str,
    assignment_id: str,
) -> Path:
    raw_root = roots.get(root_name)
    if raw_root is None:
        raise _contract_error(
            assignment_id, f"root {root_name!r} is not available for resolution"
        )
    root = Path(raw_root).resolve(strict=False)
    target = (root / relative_path).resolve(strict=False)
    if target != root and root not in target.parents:
        raise _contract_error(
            assignment_id,
            f"resolved path {relative_path!r} escapes root {root_name!r}",
        )
    return target


def _contract_error(
    assignment_id: str,
    detail: str,
) -> ProviderArtifactContractError:
    return ProviderArtifactContractError(
        f"provider artifact contract {assignment_id!r}: {detail}"
    )


@dataclass(frozen=True)
class ProviderOutputSpec:
    """One exact output path and its required filesystem kind."""

    path: str
    kind: str = "file"

    def __post_init__(self) -> None:
        relative = PurePosixPath(self.path)
        if (
            self.kind not in {"file", "directory"}
            or not self.path
            or relative.is_absolute()
            or any(part in {"", ".", ".."} for part in relative.parts)
            or relative.as_posix() != self.path
        ):
            raise ValueError("invalid provider output specification")


@dataclass(frozen=True)
class ProviderOutputFailure:
    """Bounded publication failure grouped by recovery behavior."""

    missing: tuple[str, ...] = ()
    undeclared: tuple[str, ...] = ()
    stale: tuple[str, ...] = ()
    unpublished: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProviderOutputFinalization:
    receipt: Mapping[str, object] | None
    failure: ProviderOutputFailure | None


@dataclass(frozen=True)
class _ArtifactSnapshot:
    identity_sha256: str
    content_sha256: str


@dataclass(frozen=True)
class ProviderOutputGuard:
    """Capture required outputs before dispatch and finalize them afterwards."""

    project_root: Path
    spec_dir: Path
    phase_id: str
    state_revision: int
    dispatch_id: str
    specs: tuple[ProviderOutputSpec, ...]
    baseline: tuple[_ArtifactSnapshot | None, ...]

    @classmethod
    def capture(
        cls,
        *,
        project_root: Path,
        spec_dir: Path,
        phase_id: str,
        state_revision: int,
        specs: tuple[ProviderOutputSpec, ...],
    ) -> "ProviderOutputGuard":
        root = Path(project_root).resolve(strict=False)
        output_root = Path(spec_dir).resolve(strict=False)
        return cls(
            project_root=root,
            spec_dir=output_root,
            phase_id=str(phase_id),
            state_revision=int(state_revision),
            dispatch_id=secrets.token_hex(16),
            specs=specs,
            baseline=tuple(
                _snapshot(output_root / spec.path, spec.kind) for spec in specs
            ),
        )

    def finalize(self, payload: object) -> ProviderOutputFinalization:
        claimed = self._claimed_paths(payload)
        missing: list[str] = []
        undeclared: list[str] = []
        stale: list[str] = []
        unpublished: list[str] = []
        outputs: list[dict[str, object]] = []

        for spec, before in zip(self.specs, self.baseline, strict=True):
            target = self.spec_dir / spec.path
            after = _snapshot(target, spec.kind)
            if after is None:
                display = _display_path(spec)
                missing.append(display)
                unpublished.append(display)
                continue
            if target.resolve(strict=False) not in claimed:
                display = _display_path(spec)
                undeclared.append(display)
                unpublished.append(display)
                continue
            if after == before:
                stale.append(_display_path(spec))
                continue
            outputs.append(
                {
                    "path": spec.path,
                    "kind": spec.kind,
                    "sha256": after.content_sha256,
                }
            )

        if missing or undeclared or stale:
            return ProviderOutputFinalization(
                receipt=None,
                failure=ProviderOutputFailure(
                    missing=tuple(missing),
                    undeclared=tuple(undeclared),
                    stale=tuple(stale),
                    unpublished=tuple(unpublished),
                ),
            )
        return ProviderOutputFinalization(
            receipt={
                "schema_version": 1,
                "dispatch_id": self.dispatch_id,
                "phase_id": self.phase_id,
                "state_revision": self.state_revision,
                "outputs": outputs,
            },
            failure=None,
        )

    def _claimed_paths(self, payload: object) -> set[Path]:
        if not isinstance(payload, dict):
            return set()
        raw_outputs = payload.get("output_files")
        if not isinstance(raw_outputs, list):
            return set()
        claimed: set[Path] = set()
        for raw in raw_outputs:
            if not isinstance(raw, str) or not raw.strip():
                continue
            candidate = Path(raw.strip().rstrip("/"))
            candidates = (
                (candidate,)
                if candidate.is_absolute()
                else (
                    self.project_root / candidate,
                    self.spec_dir / candidate,
                )
            )
            claimed.update(path.resolve(strict=False) for path in candidates)
        return claimed


def _display_path(spec: ProviderOutputSpec) -> str:
    return f"{spec.path}/" if spec.kind == "directory" else spec.path


def _snapshot(path: Path, kind: str) -> _ArtifactSnapshot | None:
    try:
        metadata = os.lstat(path)
        if stat.S_ISLNK(metadata.st_mode):
            return None
        if kind == "file":
            if not stat.S_ISREG(metadata.st_mode):
                return None
            content_sha256 = _file_sha256(path)
            members: list[object] = []
        else:
            if not stat.S_ISDIR(metadata.st_mode):
                return None
            content_sha256, members = _directory_snapshot(path)
        identity = {
            "root": _metadata_identity(metadata),
            "members": members,
        }
        return _ArtifactSnapshot(
            identity_sha256=hashlib.sha256(
                json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            content_sha256=content_sha256,
        )
    except (OSError, UnicodeError, ValueError):
        return None


def _directory_snapshot(root: Path) -> tuple[str, list[object]]:
    members: list[object] = []
    content = hashlib.sha256()
    for current_root, directories, filenames in os.walk(root, followlinks=False):
        current = Path(current_root)
        directories.sort()
        filenames.sort()
        for name in (*directories, *filenames):
            candidate = current / name
            metadata = os.lstat(candidate)
            if stat.S_ISLNK(metadata.st_mode):
                raise ValueError("provider output contains a symlink")
            relative = candidate.relative_to(root).as_posix()
            if stat.S_ISDIR(metadata.st_mode):
                entry_sha256 = ""
                entry_kind = "directory"
            elif stat.S_ISREG(metadata.st_mode):
                entry_sha256 = _file_sha256(candidate)
                entry_kind = "file"
                content.update(relative.encode())
                content.update(b"\0")
                content.update(entry_sha256.encode())
                content.update(b"\0")
            else:
                raise ValueError("provider output has an unsupported file type")
            members.append(
                {
                    "path": relative,
                    "kind": entry_kind,
                    "identity": _metadata_identity(metadata),
                    "sha256": entry_sha256,
                }
            )
    return content.hexdigest(), members


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _metadata_identity(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )
