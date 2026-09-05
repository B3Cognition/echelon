"""Exact, immutable residual-debt acceptance for terminal L3 plateaus."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import stat
from types import SimpleNamespace
from typing import Literal

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.ledger import ObjectStore
from harness.re_v2.protocol_22.inputs import _fsync_directory, _write_new_file
from harness.re_v2.protocol_22.schema import load_canonical_object
from harness.re_v2.run_store import ReV2Paths
from harness.re_v2.snapshot import (
    CapturedSnapshot,
    load_snapshot_manifest,
    validate_source_snapshot,
)
from harness.re_v2.workspace_snapshot import (
    ReV2WorkspaceSourceError,
    plan_clean_workspace_sources,
)

from .artifacts import AuditCandidateV1
from .findings import SemanticFindingV1
from .guidance import GuidanceDirectiveV1
from .guidance_status import all_selected_audits_accepted


_POLICY_ID = "re-v2-banzai-residual-debt-v1"
_POINTER_NAME = "residual-debt-acceptance.json"


class Protocol25DebtError(RuntimeError):
    """Raised when residual debt cannot be accepted exactly and safely."""


@dataclass(frozen=True, slots=True)
class DebtGroupV1:
    source_id: str
    finding_class: str
    finding_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.source_id, str) or not self.source_id:
            raise Protocol25DebtError("debt source_id must be nonempty")
        if not isinstance(self.finding_class, str) or not self.finding_class:
            raise Protocol25DebtError("debt finding_class must be nonempty")
        normalized = tuple(self.finding_ids)
        if not normalized or normalized != tuple(sorted(set(normalized))):
            raise Protocol25DebtError("debt finding IDs must be sorted and unique")
        object.__setattr__(self, "finding_ids", normalized)

    def to_json_dict(self) -> dict[str, object]:
        return {
            "finding_class": self.finding_class,
            "finding_ids": list(self.finding_ids),
            "source_id": self.source_id,
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "DebtGroupV1":
        if not isinstance(value, dict) or set(value) != {
            "finding_class",
            "finding_ids",
            "source_id",
        }:
            raise Protocol25DebtError("invalid residual-debt group")
        finding_ids = value["finding_ids"]
        if not isinstance(finding_ids, list) or any(
            not isinstance(item, str) for item in finding_ids
        ):
            raise Protocol25DebtError("invalid residual-debt finding IDs")
        return cls(
            source_id=value["source_id"],  # type: ignore[arg-type]
            finding_class=value["finding_class"],  # type: ignore[arg-type]
            finding_ids=tuple(finding_ids),
        )


@dataclass(frozen=True, slots=True)
class ResidualDebtAcceptanceV1:
    schema_version: Literal[1]
    run_manifest_hash: str
    terminal_event_hash: str
    audit_epoch_id: str
    closure_root_hash: str
    source_root_hashes: tuple[tuple[str, str], ...]
    unresolved_by_source_and_class: tuple[DebtGroupV1, ...]
    deferred_observation_ids: tuple[str, ...]
    guidance_directive_hash: str
    acceptance_policy_id: Literal["re-v2-banzai-residual-debt-v1"]
    source_snapshot_id: str
    selection_id: str
    operation_id: str

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise Protocol25DebtError("residual-debt schema_version must be 1")
        if self.acceptance_policy_id != _POLICY_ID:
            raise Protocol25DebtError("residual-debt acceptance policy is invalid")
        for field in (
            "run_manifest_hash",
            "terminal_event_hash",
            "audit_epoch_id",
            "closure_root_hash",
            "guidance_directive_hash",
            "source_snapshot_id",
            "selection_id",
            "operation_id",
        ):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.startswith("sha256:") or len(value) != 71:
                raise Protocol25DebtError(f"residual-debt {field} must be a sha256 digest")
        roots = tuple(tuple(item) for item in self.source_root_hashes)
        if not roots or roots != tuple(sorted(roots)) or len({item[0] for item in roots}) != len(roots):
            raise Protocol25DebtError("source root hashes must be sorted and unique")
        if any(
            len(item) != 2
            or not isinstance(item[0], str)
            or not item[0]
            or not isinstance(item[1], str)
            or not item[1].startswith("sha256:")
            for item in roots
        ):
            raise Protocol25DebtError("source root hash row is invalid")
        groups = tuple(self.unresolved_by_source_and_class)
        group_keys = tuple((item.source_id, item.finding_class) for item in groups)
        if not groups or group_keys != tuple(sorted(set(group_keys))):
            raise Protocol25DebtError("residual-debt groups must be sorted and unique")
        deferred = tuple(self.deferred_observation_ids)
        if deferred != tuple(sorted(set(deferred))):
            raise Protocol25DebtError("deferred observation IDs must be sorted and unique")
        object.__setattr__(self, "source_root_hashes", roots)
        object.__setattr__(self, "unresolved_by_source_and_class", groups)
        object.__setattr__(self, "deferred_observation_ids", deferred)

    @property
    def identity(self) -> str:
        return content_digest(self.to_json_dict())

    @property
    def unresolved_finding_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                finding_id
                for group in self.unresolved_by_source_and_class
                for finding_id in group.finding_ids
            )
        )

    def to_json_dict(self) -> dict[str, object]:
        return {
            "acceptance_policy_id": self.acceptance_policy_id,
            "audit_epoch_id": self.audit_epoch_id,
            "closure_root_hash": self.closure_root_hash,
            "deferred_observation_ids": list(self.deferred_observation_ids),
            "guidance_directive_hash": self.guidance_directive_hash,
            "operation_id": self.operation_id,
            "run_manifest_hash": self.run_manifest_hash,
            "schema_version": self.schema_version,
            "selection_id": self.selection_id,
            "source_root_hashes": [list(item) for item in self.source_root_hashes],
            "source_snapshot_id": self.source_snapshot_id,
            "terminal_event_hash": self.terminal_event_hash,
            "unresolved_by_source_and_class": [
                item.to_json_dict() for item in self.unresolved_by_source_and_class
            ],
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "ResidualDebtAcceptanceV1":
        fields = {
            "acceptance_policy_id",
            "audit_epoch_id",
            "closure_root_hash",
            "deferred_observation_ids",
            "guidance_directive_hash",
            "operation_id",
            "run_manifest_hash",
            "schema_version",
            "selection_id",
            "source_root_hashes",
            "source_snapshot_id",
            "terminal_event_hash",
            "unresolved_by_source_and_class",
        }
        if not isinstance(value, dict) or set(value) != fields:
            raise Protocol25DebtError("invalid residual-debt acceptance object")
        roots = value["source_root_hashes"]
        groups = value["unresolved_by_source_and_class"]
        deferred = value["deferred_observation_ids"]
        if (
            not isinstance(roots, list)
            or any(not isinstance(item, list) or len(item) != 2 for item in roots)
            or not isinstance(groups, list)
            or not isinstance(deferred, list)
            or any(not isinstance(item, str) for item in deferred)
        ):
            raise Protocol25DebtError("invalid residual-debt acceptance collections")
        return cls(
            schema_version=value["schema_version"],  # type: ignore[arg-type]
            run_manifest_hash=value["run_manifest_hash"],  # type: ignore[arg-type]
            terminal_event_hash=value["terminal_event_hash"],  # type: ignore[arg-type]
            audit_epoch_id=value["audit_epoch_id"],  # type: ignore[arg-type]
            closure_root_hash=value["closure_root_hash"],  # type: ignore[arg-type]
            source_root_hashes=tuple((item[0], item[1]) for item in roots),
            unresolved_by_source_and_class=tuple(
                DebtGroupV1.from_json_dict(item) for item in groups
            ),
            deferred_observation_ids=tuple(deferred),
            guidance_directive_hash=value["guidance_directive_hash"],  # type: ignore[arg-type]
            acceptance_policy_id=value["acceptance_policy_id"],  # type: ignore[arg-type]
            source_snapshot_id=value["source_snapshot_id"],  # type: ignore[arg-type]
            selection_id=value["selection_id"],  # type: ignore[arg-type]
            operation_id=value["operation_id"],  # type: ignore[arg-type]
        )


@dataclass(frozen=True, slots=True)
class _DebtPointerV1:
    schema_version: Literal[1]
    object_hash: str

    def to_json_dict(self) -> dict[str, object]:
        return {"object_hash": self.object_hash, "schema_version": self.schema_version}

    @classmethod
    def from_json_dict(cls, value: object) -> "_DebtPointerV1":
        if (
            not isinstance(value, dict)
            or set(value) != {"object_hash", "schema_version"}
            or value["schema_version"] != 1
            or not isinstance(value["object_hash"], str)
        ):
            raise Protocol25DebtError("invalid persisted residual-debt acceptance pointer")
        return cls(1, value["object_hash"])


def finalize_protocol_25_debt(
    *,
    project_root: Path,
    run_dir: Path,
    require_banzai: bool,
) -> ResidualDebtAcceptanceV1:
    """Accept exactly the authenticated residual debt of one terminal L3 plateau."""
    authority = _reconstruct_authority(Path(run_dir))
    acceptance = _derive_acceptance(authority, require_banzai=require_banzai)
    _validate_clean_workspace(
        project_root=Path(project_root),
        manifest=authority.manifest,
    )
    return _publish_acceptance(Path(run_dir), acceptance)


def load_residual_debt_acceptance(run_dir: Path) -> ResidualDebtAcceptanceV1:
    """Load and authenticate an existing residual-debt acceptance record."""
    paths = ReV2Paths.for_run(Path(run_dir))
    pointer = load_canonical_object(
        _read_regular_nofollow(paths.inputs / _POINTER_NAME),
        _DebtPointerV1.from_json_dict,
    )
    objects = ObjectStore(paths.objects)
    payload = objects.read_blob(pointer.object_hash)
    acceptance = load_canonical_object(payload, ResidualDebtAcceptanceV1.from_json_dict)
    if acceptance.identity != pointer.object_hash:
        raise Protocol25DebtError("persisted residual-debt acceptance hash mismatch")
    return acceptance


def validate_residual_debt_acceptance(
    authority: object,
    acceptance: ResidualDebtAcceptanceV1,
) -> None:
    """Require a persisted record to equal the current replayed terminal authority."""
    expected = _derive_acceptance(authority, require_banzai=True)
    if acceptance != expected:
        raise Protocol25DebtError(
            "persisted residual-debt acceptance differs from replayed authority"
        )


def residual_debt_pointer_path(run_dir: Path) -> Path:
    return ReV2Paths.for_run(Path(run_dir)).inputs / _POINTER_NAME


def _reconstruct_authority(run_dir: Path) -> object:
    # Delayed import prevents status/debt circularity while both share replay authority.
    from .status import _authority

    return _authority(Path(run_dir), None)


def _derive_acceptance(authority: object, *, require_banzai: bool) -> ResidualDebtAcceptanceV1:
    manifest = authority.manifest
    state = authority.state
    replay = authority.replay
    ledger = authority.ledger
    events = tuple(authority.events)
    shared = replay.shared.shared
    if (
        state.terminal_state != "blocked_plateau"
        or not shared.terminal
        or shared.last_type != "run_failed"
        or not events
        or events[-1].type != "run_failed"
        or not replay.plateau_targets
    ):
        raise Protocol25DebtError("residual debt requires a terminal semantic plateau")
    if shared.active is not None or shared.lease_dispatch_id is not None:
        raise Protocol25DebtError("residual debt cannot be accepted during an active dispatch")
    if shared.indeterminate_work_items or getattr(state, "indeterminate_execution", False):
        raise Protocol25DebtError("residual debt cannot be accepted with indeterminate execution")
    if getattr(state, "paused_resource", False):
        raise Protocol25DebtError("residual debt cannot be accepted from a resource pause")
    if getattr(state, "work_item_failed", False):
        raise Protocol25DebtError("residual debt cannot hide a work-item failure")
    if replay.audit_context_preflight_failure_id is not None:
        raise Protocol25DebtError("residual debt cannot hide an audit context preflight failure")
    if replay.semantic_context_projection_failure is not None:
        raise Protocol25DebtError("residual debt cannot hide a semantic projection failure")

    if not all_selected_audits_accepted(
        audit_states=tuple(item.audit_state for item in state.targets),
        selected_target_count=len(authority.graph.audit_target_plans),
    ):
        raise Protocol25DebtError("every selected audit target must be accepted")
    selected_targets = {item.audit_target_id for item in state.targets}
    epoch_id = state.audit_epoch_id
    if epoch_id is None or epoch_id not in ledger.audit_epochs:
        raise Protocol25DebtError("an authenticated frozen audit epoch is required")
    closure_hashes = {
        item
        for item in replay.audit_closure_roots
        if item in ledger.audit_closure_roots
        and ledger.audit_closure_roots[item].audit_epoch_id == epoch_id
    }
    if len(closure_hashes) != 1:
        raise Protocol25DebtError("exactly one accepted audit closure root is required")
    closure_hash = next(iter(closure_hashes))
    closure = ledger.audit_closure_roots[closure_hash]

    selected_sources = set(authority.graph.selected_source_ids)
    source_roots = ledger.l3_source_roots
    if set(source_roots) != selected_sources:
        raise Protocol25DebtError("every selected source root must be accepted")
    if any(
        root.source_id != source_id or root.closure_root_hashes != (closure_hash,)
        for source_id, root in source_roots.items()
    ):
        raise Protocol25DebtError("source root authority disagrees with the final closure root")

    guidance_payload = authority.inputs.human_guidance
    guidance_reference = manifest.human_guidance
    if guidance_payload is None or guidance_reference is None:
        raise Protocol25DebtError("Banzai residual-debt guidance is required")
    guidance = load_canonical_object(guidance_payload, GuidanceDirectiveV1.from_json_dict)
    if content_digest(guidance_payload) != guidance_reference.object_hash:
        raise Protocol25DebtError("guidance directive hash mismatch")
    if require_banzai and (
        guidance.kind != "banzai"
        or not guidance.accept_residual_debt
        or guidance.automatic_successor_limit != 1
        or guidance.successor_index != 1
    ):
        raise Protocol25DebtError("Banzai guidance must explicitly authorize residual debt")
    if guidance.audit_epoch_id != epoch_id or guidance.closure_root_hash is None:
        raise Protocol25DebtError("Banzai guidance is bound to different audit authority")

    source_by_target = {
        target.audit_target_id: target.source_id for target in state.targets
    }
    findings: dict[str, SemanticFindingV1] = {}
    for target_id, candidate_hash in replay.audit_candidates.items():
        if target_id not in selected_targets:
            raise Protocol25DebtError("accepted audit candidate is outside selected audit scope")
        candidate = load_canonical_object(
            authority.objects.read_blob(candidate_hash),
            AuditCandidateV1.from_json_dict,
        )
        if candidate.audit_target_id != target_id:
            raise Protocol25DebtError("accepted audit candidate target mismatch")
        for finding in candidate.findings:
            findings[finding.finding_key_id] = finding

    target_unresolved = {
        finding_id for target in state.targets for finding_id in target.unresolved_finding_ids
    }
    source_unresolved = {
        finding_id for root in source_roots.values() for finding_id in root.unresolved_finding_ids
    }
    closure_unresolved = set(closure.unresolved_finding_ids)
    if not target_unresolved or not (
        target_unresolved
        == source_unresolved
        == closure_unresolved
    ):
        raise Protocol25DebtError("unresolved finding authority is absent or inconsistent")
    if not target_unresolved.issubset(set(guidance.unresolved_finding_ids)):
        raise Protocol25DebtError(
            "unresolved findings exceed the debt authorized by Banzai guidance"
        )
    if target_unresolved - set(findings):
        raise Protocol25DebtError("unresolved findings lack accepted audit authority")

    grouped: dict[tuple[str, str], list[str]] = {}
    for finding_id in sorted(target_unresolved):
        finding = findings[finding_id]
        source_id = source_by_target.get(finding.finding_key.audit_target_id)
        if source_id is None:
            raise Protocol25DebtError("unresolved finding has no selected source authority")
        grouped.setdefault((source_id, finding.finding_key.finding_class), []).append(
            finding_id
        )
    groups = tuple(
        DebtGroupV1(source_id, finding_class, tuple(finding_ids))
        for (source_id, finding_class), finding_ids in sorted(grouped.items())
    )
    closure_deferred = {
        item.observation_id for item in closure.deferred_observations
    }
    source_deferred = {
        item for root in source_roots.values() for item in root.deferred_observation_ids
    }
    state_deferred = set(state.deferred_observation_ids)
    if closure_deferred != source_deferred or source_deferred != state_deferred:
        raise Protocol25DebtError("deferred observation authority is inconsistent")

    operation_id = content_digest(
        {
            "guidance_directive_hash": guidance.identity,
            "kind": "re-v2-residual-debt-acceptance-v1",
            "run_manifest_hash": manifest.run_manifest_id,
            "terminal_event_hash": events[-1].event_hash,
            "unresolved_finding_ids": sorted(target_unresolved),
        }
    )
    return ResidualDebtAcceptanceV1(
        schema_version=1,
        run_manifest_hash=manifest.run_manifest_id,
        terminal_event_hash=events[-1].event_hash,
        audit_epoch_id=epoch_id,
        closure_root_hash=closure_hash,
        source_root_hashes=tuple(
            sorted((source_id, root.identity) for source_id, root in source_roots.items())
        ),
        unresolved_by_source_and_class=groups,
        deferred_observation_ids=tuple(sorted(state_deferred)),
        guidance_directive_hash=guidance.identity,
        acceptance_policy_id=_POLICY_ID,
        source_snapshot_id=manifest.source_snapshot_id,
        selection_id=manifest.selection.identity,
        operation_id=operation_id,
    )


def _publish_acceptance(
    run_dir: Path,
    acceptance: ResidualDebtAcceptanceV1,
) -> ResidualDebtAcceptanceV1:
    paths = ReV2Paths.for_run(run_dir)
    paths.inputs.mkdir(mode=0o700, parents=True, exist_ok=True)
    objects = ObjectStore(paths.objects)
    payload = canonical_json_bytes(acceptance.to_json_dict())
    object_hash = objects.put_blob(payload)
    if object_hash != acceptance.identity:
        raise Protocol25DebtError("residual-debt acceptance object hash mismatch")
    pointer_path = paths.inputs / _POINTER_NAME
    pointer_payload = canonical_json_bytes(_DebtPointerV1(1, object_hash).to_json_dict())
    try:
        _write_new_file(pointer_path, pointer_payload, mode=0o600)
        _fsync_directory(paths.inputs)
    except FileExistsError:
        try:
            existing = load_residual_debt_acceptance(run_dir)
        except Exception as exc:
            raise Protocol25DebtError(
                "persisted residual-debt acceptance is invalid or altered"
            ) from exc
        if existing != acceptance:
            raise Protocol25DebtError(
                "persisted residual-debt acceptance differs from current authority"
            )
        return existing
    return acceptance


def _validate_clean_workspace(*, project_root: Path, manifest: object) -> None:
    configured = os.environ.get("ECHELON_HOME")
    base = Path(configured).expanduser() if configured else Path.home() / ".echelon"
    bundle = (base / "re-v2" / "snapshots" / manifest.source_snapshot_id).resolve(
        strict=False
    )
    snapshot = CapturedSnapshot(
        snapshot_id=manifest.source_snapshot_id,
        kind=manifest.source_snapshot_kind,
        read_root=bundle / "source",
        manifest_path=bundle / "manifest.json",
    )
    try:
        validate_source_snapshot(snapshot)
        snapshot_manifest = load_snapshot_manifest(snapshot)
        components = snapshot_manifest.components
        if components is None:
            raise Protocol25DebtError("source snapshot has no workspace components")
        declarations = tuple(
            SimpleNamespace(
                id=component.source_id,
                path=component.workspace_path,
                git_role=component.git_role,
            )
            for component in components
        )
        plan = plan_clean_workspace_sources(project_root, declarations)
    except Protocol25DebtError:
        raise
    except ReV2WorkspaceSourceError as exc:
        raise Protocol25DebtError(
            "sources must be clean before accepting residual debt; commit, stash "
            "(including untracked files), or revert the source changes, then retry"
        ) from exc
    except Exception as exc:
        raise Protocol25DebtError(f"cannot authenticate the source snapshot: {exc}") from exc
    expected = {
        component.source_id: (
            component.workspace_path,
            component.repository_path,
            component.commit,
        )
        for component in components
    }
    actual = {
        proof.source_id: (
            proof.workspace_path,
            proof.repository_path,
            proof.commit,
        )
        for proof in plan.sources
    }
    if actual != expected:
        raise Protocol25DebtError(
            "source commits changed since the authenticated RE snapshot"
        )


def _read_regular_nofollow(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise Protocol25DebtError(
            f"persisted residual-debt acceptance is unavailable: {exc}"
        ) from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise Protocol25DebtError(
                "persisted residual-debt acceptance is not a regular file"
            )
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 65536)
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)
    finally:
        os.close(descriptor)


__all__ = (
    "DebtGroupV1",
    "Protocol25DebtError",
    "ResidualDebtAcceptanceV1",
    "finalize_protocol_25_debt",
    "load_residual_debt_acceptance",
    "residual_debt_pointer_path",
    "validate_residual_debt_acceptance",
)
