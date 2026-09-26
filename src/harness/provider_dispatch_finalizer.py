"""Trusted finalization boundary for one Phase A provider dispatch."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import stat
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Literal, Protocol

from harness.prepared_phase_result import detach_squad_agent_result
from harness.provider_output_publication import (
    ResolvedProviderArtifactContract,
    permission_metadata,
)
from harness.squad_provider import SquadAgentResult


ProviderDispatchOutcome = Literal["published", "domain_blocked", "invalid"]
_OUTCOMES = frozenset({"published", "domain_blocked", "invalid"})
_FORGED_RECEIPT_FIELDS = frozenset(
    {
        "provider_output_receipts",
        "provider_dispatch_receipts",
        "provider_dispatch_receipt",
        "provider_receipt",
    }
)


class ProviderDispatchFailure(RuntimeError):
    """The provider result or filesystem evidence could not be accepted."""

    def __init__(self, reason: str, *, details: tuple[str, ...] = ()) -> None:
        self.reason = reason
        self.details = details
        suffix = f": {', '.join(details)}" if details else ""
        super().__init__(f"provider dispatch {reason}{suffix}")


@dataclass(frozen=True)
class ProviderDispatchContext:
    phase_id: str
    assignment_id: str
    occurrence_id: str
    state_revision: int
    contract: ResolvedProviderArtifactContract
    prompt_sha256: str
    prompt_metadata_sha256: str


@dataclass(frozen=True)
class ProviderDispatchReceipt:
    schema_version: int
    dispatch_id: str
    phase_id: str
    assignment_id: str
    occurrence_id: str
    state_revision: int
    contract_sha256: str
    prompt_sha256: str
    prompt_metadata_sha256: str
    outcome: ProviderDispatchOutcome
    outputs: tuple[Mapping[str, object], ...]
    semantic_validator_id: str | None
    semantic_result_sha256: str | None
    provider_attempts_sha256: str
    validated_result_sha256: str

    def as_dict(self) -> dict[str, object]:
        return _json_normalize(self)


@dataclass(frozen=True)
class FinalizedProviderResult:
    result: SquadAgentResult
    receipt: ProviderDispatchReceipt


class ProviderSemanticValidator(Protocol):
    semantic_validator_id: str

    def validate(
        self,
        result: SquadAgentResult,
        receipt: ProviderDispatchReceipt,
    ) -> object:
        ...


@dataclass(frozen=True)
class _MemberSnapshot:
    path: str
    identity_sha256: str
    content_sha256: str


@dataclass(frozen=True)
class _TargetSnapshot:
    kind: str
    identity_sha256: str
    content_sha256: str
    members: tuple[_MemberSnapshot, ...] = ()


@dataclass(frozen=True)
class _Guard:
    context: ProviderDispatchContext
    dispatch_id: str
    canonical_before: tuple[_TargetSnapshot | None, ...]
    shadow_before: tuple[_TargetSnapshot | None, ...]
    root_before: tuple[
        tuple[Path, tuple[str, ...], Mapping[str, tuple[str, str]]], ...
    ]

    @classmethod
    def capture(cls, context: ProviderDispatchContext) -> _Guard:
        contract = context.contract
        canonical = tuple(
            _snapshot_target(path, rule.kind, missing_ok=True)
            for rule, path in zip(
                contract.contract.artifacts,
                contract.write_paths,
                strict=True,
            )
        )
        shadow_paths = _shadow_paths(contract)
        shadow = tuple(
            _snapshot_target(path, rule.kind, missing_ok=True)
            if path is not None
            else None
            for rule, path in zip(
                contract.contract.artifacts,
                shadow_paths,
                strict=True,
            )
        )
        roots = _artifact_roots(contract)
        return cls(
            context=context,
            dispatch_id=secrets.token_hex(16),
            canonical_before=canonical,
            shadow_before=shadow,
            root_before=tuple(
                (
                    root,
                    ignored,
                    MappingProxyType(
                        _root_leaf_manifest(root, ignored=ignored)
                    ),
                )
                for root, ignored in roots
            ),
        )

    def finalize(
        self,
        result: SquadAgentResult,
        *,
        outcome: ProviderDispatchOutcome,
    ) -> tuple[Mapping[str, object], ...]:
        resolved = self.context.contract
        claims = _output_claims(result)
        _reject_claims_outside_contract(resolved, claims)
        self._reject_out_of_scope_mutations()
        if resolved.contract.mode != "publish":
            if claims:
                raise ProviderDispatchFailure(
                    "artifact claims forbidden",
                    details=(resolved.contract.mode,),
                )
            return ()
        if outcome == "invalid":
            return ()

        evidence: list[Mapping[str, object]] = []
        shadow_paths = _shadow_paths(resolved)
        for index, (rule, target) in enumerate(
            zip(
                resolved.contract.artifacts,
                resolved.write_paths,
                strict=True,
            )
        ):
            before = self.canonical_before[index]
            post = _snapshot_target(target, rule.kind, missing_ok=True)
            matching_claims = _matching_claims(
                claims,
                rule_path=rule.path,
                target=target,
                kind=rule.kind,
                shadow_target=shadow_paths[index],
            )
            evidence_kind = "created" if before is None else "replaced"
            shadow_before = self.shadow_before[index]
            shadow_target = shadow_paths[index]
            shadow_post = (
                _snapshot_target(shadow_target, rule.kind, missing_ok=True)
                if shadow_target is not None
                else None
            )
            if (
                not _snapshot_changed(before, post)
                and shadow_target is not None
                and _snapshot_changed(shadow_before, shadow_post)
                and matching_claims
            ):
                _promote_shadow(shadow_target, target, rule.kind)
                post = _snapshot_target(target, rule.kind, missing_ok=True)
                evidence_kind = "shadow_promoted"

            changed = _snapshot_changed(before, post)
            if post is None:
                if outcome == "published" and rule.requirement == "required":
                    raise ProviderDispatchFailure("missing required output", details=(rule.path,))
                if matching_claims:
                    raise ProviderDispatchFailure("missing claimed output", details=(rule.path,))
                continue
            if rule.kind == "directory":
                item = _directory_evidence(
                    rule_path=rule.path,
                    requirement=rule.requirement,
                    before=before,
                    post=post,
                    claims=matching_claims,
                    target=target,
                    outcome=outcome,
                    evidence_kind=evidence_kind,
                )
                if item is not None:
                    evidence.append(item)
                continue
            if changed and not matching_claims:
                raise ProviderDispatchFailure("unclaimed output mutation", details=(rule.path,))
            if matching_claims and not changed:
                raise ProviderDispatchFailure("stale claimed output", details=(rule.path,))
            if outcome == "published" and rule.requirement == "required" and not changed:
                raise ProviderDispatchFailure("stale required output", details=(rule.path,))
            if changed:
                evidence.append(
                    _freeze_mapping(
                        {
                            "root": rule.root,
                            "path": rule.path,
                            "kind": rule.kind,
                            "requirement": rule.requirement,
                            "sha256": post.content_sha256,
                            "preimage_identity_sha256": (
                                before.identity_sha256 if before is not None else None
                            ),
                            "postimage_identity_sha256": post.identity_sha256,
                            "evidence_kind": evidence_kind,
                            "members": (),
                        }
                    )
                )
        return tuple(evidence)

    def _reject_out_of_scope_mutations(self) -> None:
        allowed = tuple(
            (path, rule.kind)
            for rule, path in zip(
                self.context.contract.contract.artifacts,
                self.context.contract.write_paths,
                strict=True,
            )
        )
        violations: list[str] = []
        for root, ignored, before in self.root_before:
            after = _root_leaf_manifest(root, ignored=ignored)
            for relative in sorted(set(before) | set(after)):
                if before.get(relative) == after.get(relative):
                    continue
                changed = root / relative
                if not any(
                    changed == target
                    or (kind == "directory" and target in changed.parents)
                    for target, kind in allowed
                ):
                    violations.append(str(changed))
        if violations:
            raise ProviderDispatchFailure(
                "mutation outside write scope",
                details=tuple(violations),
            )


class ProviderDispatchFinalizer:
    def dispatch(
        self,
        context: ProviderDispatchContext,
        *,
        execute: Callable[[dict[str, object]], SquadAgentResult],
        validate_result: Callable[[SquadAgentResult], SquadAgentResult],
        classify_outcome: Callable[[SquadAgentResult], str],
        semantic_validator: ProviderSemanticValidator | None = None,
    ) -> FinalizedProviderResult:
        guard = _Guard.capture(context)
        raw_result = execute(permission_metadata(context.contract))
        try:
            validated = validate_result(raw_result)
            result = _strip_provider_receipt_fields(validated)
        except Exception as exc:
            raise ProviderDispatchFailure("invalid provider result") from exc
        outcome = classify_outcome(result)
        if outcome not in _OUTCOMES:
            raise ProviderDispatchFailure(
                "invalid outcome classification",
                details=(str(outcome),),
            )
        outputs = guard.finalize(result, outcome=outcome)
        receipt = ProviderDispatchReceipt(
            schema_version=2,
            dispatch_id=guard.dispatch_id,
            phase_id=context.phase_id,
            assignment_id=context.assignment_id,
            occurrence_id=context.occurrence_id,
            state_revision=context.state_revision,
            contract_sha256=context.contract.contract_sha256,
            prompt_sha256=context.prompt_sha256,
            prompt_metadata_sha256=context.prompt_metadata_sha256,
            outcome=outcome,
            outputs=outputs,
            semantic_validator_id=None,
            semantic_result_sha256=None,
            provider_attempts_sha256=_json_digest(result.provider_attempts),
            validated_result_sha256=_validated_result_digest(result),
        )
        if semantic_validator is not None:
            identity = getattr(semantic_validator, "semantic_validator_id", None)
            if type(identity) is not str or not identity:
                raise ProviderDispatchFailure("invalid semantic validator identity")
            try:
                semantic_result = semantic_validator.validate(result, receipt)
                semantic_digest = _json_digest(semantic_result)
            except Exception as exc:
                raise ProviderDispatchFailure("semantic validation failed") from exc
            receipt = replace(
                receipt,
                semantic_validator_id=identity,
                semantic_result_sha256=semantic_digest,
            )
        return FinalizedProviderResult(result=result, receipt=receipt)


def _strip_provider_receipt_fields(result: SquadAgentResult) -> SquadAgentResult:
    detached = detach_squad_agent_result(result)
    payload = detached.echelon_result
    if isinstance(payload, dict):
        for field_name in _FORGED_RECEIPT_FIELDS:
            payload.pop(field_name, None)
    return detached


def _output_claims(result: SquadAgentResult) -> tuple[str, ...]:
    payload = result.echelon_result
    if not isinstance(payload, dict):
        return ()
    raw = payload.get("output_files", [])
    if raw is None:
        return ()
    if type(raw) is not list or any(
        type(item) is not str or not item.strip() for item in raw
    ):
        raise ProviderDispatchFailure("invalid output_files claims")
    return tuple(dict.fromkeys(item.strip().rstrip("/") for item in raw))


def _reject_claims_outside_contract(
    resolved: ResolvedProviderArtifactContract,
    claims: tuple[str, ...],
) -> None:
    shadows = _shadow_paths(resolved)
    unknown = [
        claim
        for claim in claims
        if not any(
            _claim_matches(
                claim,
                rule_path=rule.path,
                target=target,
                kind=rule.kind,
                shadow_target=shadow,
            )
            for rule, target, shadow in zip(
                resolved.contract.artifacts,
                resolved.write_paths,
                shadows,
                strict=True,
            )
        )
    ]
    if unknown:
        raise ProviderDispatchFailure(
            "claim outside contract",
            details=tuple(unknown),
        )


def _matching_claims(
    claims: tuple[str, ...],
    *,
    rule_path: str,
    target: Path,
    kind: str,
    shadow_target: Path | None,
) -> tuple[str, ...]:
    return tuple(
        claim
        for claim in claims
        if _claim_matches(
            claim,
            rule_path=rule_path,
            target=target,
            kind=kind,
            shadow_target=shadow_target,
        )
    )


def _claim_matches(
    claim: str,
    *,
    rule_path: str,
    target: Path,
    kind: str,
    shadow_target: Path | None,
) -> bool:
    candidate = Path(claim)
    if candidate.is_absolute():
        resolved = candidate.resolve(strict=False)
        for base in (target, shadow_target):
            if base is None:
                continue
            if resolved == base or (kind == "directory" and base in resolved.parents):
                return True
        return False
    normalized = PurePosixPath(claim).as_posix()
    return normalized == rule_path or (
        kind == "directory" and normalized.startswith(rule_path.rstrip("/") + "/")
    )


def _directory_evidence(
    *,
    rule_path: str,
    requirement: str,
    before: _TargetSnapshot | None,
    post: _TargetSnapshot,
    claims: tuple[str, ...],
    target: Path,
    outcome: str,
    evidence_kind: str,
) -> Mapping[str, object] | None:
    before_members = {member.path: member for member in before.members} if before else {}
    post_members = {member.path: member for member in post.members}
    disappeared = sorted(set(before_members) - set(post_members))
    if disappeared:
        raise ProviderDispatchFailure(
            "directory members disappeared",
            details=tuple(f"{rule_path}/{item}" for item in disappeared),
        )
    changed = [
        member
        for member in post.members
        if before_members.get(member.path) != member
    ]
    if not changed and claims:
        raise ProviderDispatchFailure("stale directory claim", details=(rule_path,))
    if outcome == "published" and requirement == "required" and not changed:
        raise ProviderDispatchFailure(
            "directory has no current-dispatch leaves",
            details=(rule_path,),
        )
    claimed_members = {
        relative
        for claim in claims
        if (relative := _directory_claim_relative(claim, rule_path, target))
    }
    unclaimed = sorted(member.path for member in changed if member.path not in claimed_members)
    if unclaimed:
        raise ProviderDispatchFailure(
            "unclaimed directory mutation",
            details=tuple(f"{rule_path}/{item}" for item in unclaimed),
        )
    stale_claims = sorted(claimed_members - {member.path for member in changed})
    if stale_claims:
        raise ProviderDispatchFailure(
            "stale directory member claim",
            details=tuple(f"{rule_path}/{item}" for item in stale_claims),
        )
    if not changed:
        return None
    members = tuple(
        _freeze_mapping(
            {
                "path": member.path,
                "sha256": member.content_sha256,
                "identity_sha256": member.identity_sha256,
            }
        )
        for member in sorted(changed, key=lambda item: item.path)
    )
    return _freeze_mapping(
        {
            "root": "active_spec",
            "path": rule_path,
            "kind": "directory",
            "requirement": requirement,
            "sha256": post.content_sha256,
            "preimage_identity_sha256": (
                before.identity_sha256 if before is not None else None
            ),
            "postimage_identity_sha256": post.identity_sha256,
            "evidence_kind": evidence_kind,
            "members": members,
        }
    )


def _directory_claim_relative(claim: str, rule_path: str, target: Path) -> str | None:
    candidate = Path(claim)
    if candidate.is_absolute():
        try:
            relative = candidate.resolve(strict=False).relative_to(target)
        except ValueError:
            return None
        return relative.as_posix() if relative.parts else None
    normalized = PurePosixPath(claim)
    prefix = PurePosixPath(rule_path)
    try:
        relative = normalized.relative_to(prefix)
    except ValueError:
        return None
    return relative.as_posix() if relative.parts else None


def _snapshot_target(
    path: Path | None,
    kind: str,
    *,
    missing_ok: bool,
) -> _TargetSnapshot | None:
    if path is None:
        return None
    try:
        metadata = os.lstat(path)
    except FileNotFoundError:
        if missing_ok:
            return None
        raise ProviderDispatchFailure("missing artifact", details=(str(path),))
    except OSError as exc:
        raise ProviderDispatchFailure("artifact snapshot failed", details=(str(path),)) from exc
    if stat.S_ISLNK(metadata.st_mode):
        raise ProviderDispatchFailure("artifact is a symlink", details=(str(path),))
    if kind == "file":
        if not stat.S_ISREG(metadata.st_mode):
            raise ProviderDispatchFailure("artifact kind mismatch", details=(str(path),))
        digest = _file_sha256(path)
        return _TargetSnapshot(
            kind="file",
            identity_sha256=_identity_sha256(metadata),
            content_sha256=digest,
        )
    if not stat.S_ISDIR(metadata.st_mode):
        raise ProviderDispatchFailure("artifact kind mismatch", details=(str(path),))
    members: list[_MemberSnapshot] = []
    for current_root, directories, filenames in os.walk(path, followlinks=False):
        current = Path(current_root)
        directories.sort()
        filenames.sort()
        for name in directories:
            child = current / name
            child_metadata = os.lstat(child)
            if stat.S_ISLNK(child_metadata.st_mode):
                raise ProviderDispatchFailure("directory contains symlink", details=(str(child),))
            if not stat.S_ISDIR(child_metadata.st_mode):
                raise ProviderDispatchFailure("directory contains special file", details=(str(child),))
        for name in filenames:
            child = current / name
            child_metadata = os.lstat(child)
            if stat.S_ISLNK(child_metadata.st_mode):
                raise ProviderDispatchFailure("directory contains symlink", details=(str(child),))
            if not stat.S_ISREG(child_metadata.st_mode):
                raise ProviderDispatchFailure("directory contains special file", details=(str(child),))
            members.append(
                _MemberSnapshot(
                    path=child.relative_to(path).as_posix(),
                    identity_sha256=_identity_sha256(child_metadata),
                    content_sha256=_file_sha256(child),
                )
            )
    members.sort(key=lambda item: item.path)
    content_sha256 = _json_digest(
        [(member.path, member.content_sha256) for member in members]
    )
    identity_sha256 = _json_digest(
        [(member.path, member.identity_sha256) for member in members]
    )
    return _TargetSnapshot(
        kind="directory",
        identity_sha256=identity_sha256,
        content_sha256=content_sha256,
        members=tuple(members),
    )


def _snapshot_changed(
    before: _TargetSnapshot | None,
    after: _TargetSnapshot | None,
) -> bool:
    return before != after


def _root_leaf_manifest(
    root: Path,
    *,
    ignored: tuple[str, ...] = (),
) -> dict[str, tuple[str, str]]:
    if not root.exists():
        return {}
    manifest: dict[str, tuple[str, str]] = {}
    for current_root, directories, filenames in os.walk(root, followlinks=False):
        current = Path(current_root)
        directories.sort()
        filenames.sort()
        retained_directories: list[str] = []
        for name in directories:
            child = current / name
            metadata = os.lstat(child)
            relative = child.relative_to(root).as_posix()
            if relative in ignored:
                continue
            if stat.S_ISLNK(metadata.st_mode):
                manifest[relative] = ("symlink", _identity_sha256(metadata))
            elif stat.S_ISDIR(metadata.st_mode):
                retained_directories.append(name)
            else:
                manifest[relative] = ("special", _identity_sha256(metadata))
        directories[:] = retained_directories
        for name in filenames:
            child = current / name
            metadata = os.lstat(child)
            relative = child.relative_to(root).as_posix()
            if relative in ignored:
                continue
            if stat.S_ISREG(metadata.st_mode):
                manifest[relative] = (_identity_sha256(metadata), _file_sha256(child))
            elif stat.S_ISLNK(metadata.st_mode):
                manifest[relative] = ("symlink", _identity_sha256(metadata))
            else:
                manifest[relative] = ("special", _identity_sha256(metadata))
    return manifest


def _artifact_roots(
    resolved: ResolvedProviderArtifactContract,
) -> tuple[tuple[Path, tuple[str, ...]], ...]:
    roots: list[tuple[Path, tuple[str, ...]]] = []
    for rule, target in zip(
        resolved.contract.artifacts,
        resolved.write_paths,
        strict=True,
    ):
        root = target
        for _part in PurePosixPath(rule.path).parts:
            root = root.parent
        ignored = (
            (
                "telemetry/events.jsonl",
                "telemetry/phase-timing.lock",
                "telemetry/spans.jsonl",
            )
            if rule.root == "squad"
            else ()
        )
        existing = next(
            (index for index, item in enumerate(roots) if item[0] == root),
            None,
        )
        if existing is None:
            roots.append((root, ignored))
        elif ignored:
            roots[existing] = (root, tuple(sorted(set(roots[existing][1]) | set(ignored))))
    return tuple(roots)


def _shadow_paths(
    resolved: ResolvedProviderArtifactContract,
) -> tuple[Path | None, ...]:
    if resolved.shadow_write_paths:
        return resolved.shadow_write_paths
    return tuple(None for _rule in resolved.contract.artifacts)


def _promote_shadow(shadow: Path, target: Path, kind: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if kind == "file":
        temporary = target.with_name(f".{target.name}.{secrets.token_hex(8)}.tmp")
        shutil.copy2(shadow, temporary, follow_symlinks=False)
        os.replace(temporary, target)
        return
    if target.exists():
        raise ProviderDispatchFailure(
            "shadow directory cannot replace an existing canonical directory",
            details=(str(target),),
        )
    temporary = target.with_name(f".{target.name}.{secrets.token_hex(8)}.tmp")
    shutil.copytree(shadow, temporary, symlinks=False)
    os.replace(temporary, target)


def _identity_sha256(metadata: os.stat_result) -> str:
    return _json_digest(
        (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_mode,
            metadata.st_nlink,
            metadata.st_size,
            metadata.st_mtime_ns,
            metadata.st_ctime_ns,
        )
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ProviderDispatchFailure("artifact read failed", details=(str(path),)) from exc
    return digest.hexdigest()


def _validated_result_digest(result: SquadAgentResult) -> str:
    return _json_digest(
        {
            "echelon_result": result.echelon_result,
            "exit_code": result.exit_code,
            "timed_out": result.timed_out,
            "provider_name": result.provider_name,
            "model_name": result.model_name,
            "token_usage": result.token_usage,
            "cost_usd": result.cost_usd,
        }
    )


def _json_digest(value: object) -> str:
    try:
        payload = json.dumps(
            _json_normalize(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise ProviderDispatchFailure("unbounded receipt value") from exc
    return hashlib.sha256(payload).hexdigest()


def _json_normalize(value: object) -> object:
    if value is None or type(value) in (str, bool, int, float):
        return value
    if isinstance(value, ProviderDispatchReceipt):
        return {
            field: _json_normalize(getattr(value, field))
            for field in value.__dataclass_fields__
        }
    if isinstance(value, Mapping):
        return {
            str(key): _json_normalize(item)
            for key, item in value.items()
        }
    if type(value) in (list, tuple):
        return [_json_normalize(item) for item in value]
    raise TypeError(f"unsupported JSON value {type(value).__name__}")


def _freeze_mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    frozen: dict[str, object] = {}
    for key, item in value.items():
        if isinstance(item, Mapping):
            frozen[key] = _freeze_mapping(item)
        elif type(item) in (list, tuple):
            frozen[key] = tuple(
                _freeze_mapping(child) if isinstance(child, Mapping) else child
                for child in item
            )
        else:
            frozen[key] = item
    return MappingProxyType(frozen)
