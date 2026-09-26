"""Harness-owned proof that required provider outputs came from this dispatch."""

from __future__ import annotations

import hashlib
import json
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
    shadow_write_paths: tuple[Path | None, ...] = ()


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
    shadow_write_paths: tuple[Path | None, ...] = tuple(
        _shadow_target(rule, roots=roots)
        if contract.allow_shadow_recovery
        else None
        for rule in contract.artifacts
    )
    return ResolvedProviderArtifactContract(
        assignment_id=assignment_id,
        contract_sha256=provider_artifact_contract_sha256(contract),
        contract=contract,
        write_paths=write_paths,
        read_paths=read_paths,
        shadow_write_paths=shadow_write_paths,
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


def _shadow_target(
    rule: ProviderArtifactRule,
    *,
    roots: Mapping[str, Path],
) -> Path | None:
    if rule.root != "active_spec":
        return None
    active_spec = roots.get("active_spec")
    squad = roots.get("squad")
    if active_spec is None or squad is None:
        return None
    active_root = Path(active_spec).resolve(strict=False)
    shadow_root = (
        Path(squad).resolve(strict=False) / "specs" / active_root.name
    )
    target = (shadow_root / rule.path).resolve(strict=False)
    if shadow_root != target and shadow_root not in target.parents:
        return None
    return target


def _contract_error(
    assignment_id: str,
    detail: str,
) -> ProviderArtifactContractError:
    return ProviderArtifactContractError(
        f"provider artifact contract {assignment_id!r}: {detail}"
    )
