"""Pure schema-4 lifecycle identities and immutable guidance authority."""

from __future__ import annotations

from pathlib import Path
from typing import Literal
import unicodedata

from harness.re_v2.canonical import content_digest
from harness.re_v2.protocol_22.schema import (
    Protocol22SchemaError,
    digest_value,
    safe_id,
    sorted_unique_digests,
)
from harness.re_v2.protocol_24.model import SelectionScopeV1


RunModeV1 = Literal[
    "new-audit-epoch",
    "audit-successor",
    "closure-successor",
]
_RUN_MODES = frozenset(
    {"new-audit-epoch", "audit-successor", "closure-successor"}
)


def normalize_guidance_answer(answer: object) -> str:
    """Return bounded NFC guidance suitable for immutable publication."""
    if not isinstance(answer, str):
        raise ValueError("guidance answer must be text")
    normalized = unicodedata.normalize(
        "NFC",
        answer.replace("\r\n", "\n").replace("\r", "\n"),
    ).strip()
    if not normalized:
        raise ValueError("guidance answer must be nonempty")
    if len(normalized.encode("utf-8", errors="strict")) > 8192:
        raise ValueError("guidance answer must be at most 8192 UTF-8 bytes")
    if any(
        unicodedata.category(character) == "Cc" and character != "\n"
        for character in normalized
    ):
        raise ValueError("guidance answer contains unsupported control characters")
    return normalized


def guidance_id_for(
    *,
    parent_manifest_hash: str,
    parent_terminal_event_hash: str,
    accepted_audit_candidate_hashes: tuple[str, ...],
    unresolved_audit_target_ids: tuple[str, ...],
    audit_epoch_id: str | None,
    closure_root_hash: str | None,
    unresolved_finding_ids: tuple[str, ...],
    answer: str,
) -> str:
    """Hash guidance with the exact blocked authority it is allowed to affect."""
    try:
        digest_value(parent_manifest_hash, "guidance parent manifest")
        digest_value(parent_terminal_event_hash, "guidance parent terminal event")
        candidates = sorted_unique_digests(
            accepted_audit_candidate_hashes,
            "guidance accepted audit candidates",
        )
        targets = sorted_unique_digests(
            unresolved_audit_target_ids,
            "guidance unresolved audit targets",
        )
        findings = sorted_unique_digests(
            unresolved_finding_ids,
            "guidance unresolved findings",
        )
        if audit_epoch_id is not None:
            digest_value(audit_epoch_id, "guidance audit epoch")
        if closure_root_hash is not None:
            digest_value(closure_root_hash, "guidance closure root")
    except Protocol22SchemaError as exc:
        raise ValueError(str(exc)) from exc
    pre_epoch = audit_epoch_id is None and closure_root_hash is None
    if pre_epoch:
        if not candidates or not targets or findings:
            raise ValueError(
                "pre-epoch guidance requires retained candidates and unresolved targets"
            )
    elif (
        audit_epoch_id is None
        or closure_root_hash is None
        or not findings
        or targets
    ):
        raise ValueError(
            "closure guidance requires epoch, closure root, and unresolved findings"
        )
    payload = {
        "accepted_audit_candidate_hashes": list(candidates),
        "answer": normalize_guidance_answer(answer),
        "audit_epoch_id": audit_epoch_id,
        "closure_root_hash": closure_root_hash,
        "parent_manifest_hash": parent_manifest_hash,
        "parent_terminal_event_hash": parent_terminal_event_hash,
        "schema_version": 1,
        "unresolved_audit_target_ids": list(targets),
        "unresolved_finding_ids": list(findings),
    }
    return content_digest(payload)


def semantic_request_id_v2(
    *,
    lineage_root_run_id: str,
    lineage_root_manifest_hash: str,
    direct_parent_run_id: str,
    direct_parent_manifest_hash: str,
    direct_parent_terminal_event_hash: str,
    source_snapshot_id: str,
    partition_manifest_id: str,
    selection: SelectionScopeV1,
    run_mode: RunModeV1,
    artifact_policy_hash: str,
    executor_contract_hash: str,
    audit_policy_hash: str,
    accepted_audit_target_ids: tuple[str, ...],
    frozen_audit_epoch_id: str | None,
    closure_root_hash: str | None,
    guidance_hash: str | None,
) -> str:
    """Identify an exact L3 request independently of mutable authorization."""
    if not isinstance(selection, SelectionScopeV1):
        raise ValueError("semantic request requires SelectionScopeV1")
    if run_mode not in _RUN_MODES:
        raise ValueError("semantic request run mode is unsupported")
    try:
        safe_id(lineage_root_run_id, "lineage root run ID")
        safe_id(direct_parent_run_id, "direct parent run ID")
        for field, value in (
            ("lineage root manifest", lineage_root_manifest_hash),
            ("direct parent manifest", direct_parent_manifest_hash),
            ("direct parent terminal event", direct_parent_terminal_event_hash),
            ("source snapshot", source_snapshot_id),
            ("partition manifest", partition_manifest_id),
            ("artifact policy", artifact_policy_hash),
            ("executor contract", executor_contract_hash),
            ("audit policy", audit_policy_hash),
        ):
            digest_value(value, field)
        targets = sorted_unique_digests(
            accepted_audit_target_ids,
            "accepted audit target IDs",
        )
        for field, value in (
            ("frozen audit epoch", frozen_audit_epoch_id),
            ("closure root", closure_root_hash),
            ("guidance", guidance_hash),
        ):
            if value is not None:
                digest_value(value, field)
    except Protocol22SchemaError as exc:
        raise ValueError(str(exc)) from exc
    if run_mode == "new-audit-epoch":
        if targets or any(
            value is not None
            for value in (frozen_audit_epoch_id, closure_root_hash, guidance_hash)
        ):
            raise ValueError("new audit epoch cannot bind successor-only authority")
    elif run_mode == "audit-successor":
        if (
            guidance_hash is None
            or frozen_audit_epoch_id is not None
            or closure_root_hash is not None
        ):
            raise ValueError("audit successor authority is inconsistent")
    elif (
        guidance_hash is None
        or frozen_audit_epoch_id is None
        or closure_root_hash is None
    ):
        raise ValueError("closure successor authority is incomplete")
    return content_digest(
        {
            "accepted_audit_target_ids": list(targets),
            "artifact_policy_hash": artifact_policy_hash,
            "audit_policy_hash": audit_policy_hash,
            "closure_root_hash": closure_root_hash,
            "direct_parent_manifest_hash": direct_parent_manifest_hash,
            "direct_parent_run_id": direct_parent_run_id,
            "direct_parent_terminal_event_hash": direct_parent_terminal_event_hash,
            "executor_contract_hash": executor_contract_hash,
            "frozen_audit_epoch_id": frozen_audit_epoch_id,
            "guidance_hash": guidance_hash,
            "lineage_root_manifest_hash": lineage_root_manifest_hash,
            "lineage_root_run_id": lineage_root_run_id,
            "partition_manifest_id": partition_manifest_id,
            "run_mode": run_mode,
            "schema_version": 2,
            "selection": selection.to_json_dict(),
            "source_snapshot_id": source_snapshot_id,
            "target_layer": "L3",
        }
    )


def find_exact_protocol_25_child(
    workspace_root: Path,
    semantic_request_id: str,
) -> Path | None:
    """Return an exact immutable semantic request regardless of mutable state."""
    from harness.re_v2.run_store import load_run_manifest

    from .model import RunManifestV4

    try:
        digest_value(semantic_request_id, "semantic request ID")
    except Protocol22SchemaError as exc:
        raise ValueError(str(exc)) from exc
    runs = workspace_root.resolve() / "runs"
    if not runs.exists():
        return None
    if runs.is_symlink() or not runs.is_dir():
        raise ValueError("workspace runs path is unsafe")
    for candidate in sorted(runs.iterdir(), key=lambda path: path.name):
        if (
            not candidate.name.startswith("re-")
            or candidate.is_symlink()
            or not candidate.is_dir()
            or not (candidate / "v2" / "run.json").is_file()
        ):
            continue
        manifest = load_run_manifest(candidate)
        if (
            isinstance(manifest, RunManifestV4)
            and manifest.semantic_request_id == semantic_request_id
        ):
            return candidate
    return None


__all__ = (
    "find_exact_protocol_25_child",
    "guidance_id_for",
    "normalize_guidance_answer",
    "semantic_request_id_v2",
)
