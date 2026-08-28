"""Request identity and exact child reuse for protocol-2.7 synthesis."""

from __future__ import annotations

import json
from pathlib import Path

from harness.re_v2.protocol_27.authority import (
    Protocol27AuthorityError,
    ResolvedSynthesisParentV1,
)
from harness.re_v2.protocol_27.model import (
    PartialSourceAcceptanceV1,
    RunManifestV6,
    SynthesisBudgetPolicyV1,
    SynthesisRequestV1,
)
from harness.re_v2.run_store import load_run_manifest


class Protocol27LifecycleError(RuntimeError):
    """Raised when synthesis creation or exact reuse cannot proceed."""


def synthesis_request(
    parent: ResolvedSynthesisParentV1,
    budget_policy: SynthesisBudgetPolicyV1,
    *,
    expected_v2_index_hash: str,
    expected_compatibility_generation: int,
) -> SynthesisRequestV1:
    if not isinstance(parent, ResolvedSynthesisParentV1):
        raise Protocol27LifecycleError("synthesis request requires resolved parent authority")
    if not isinstance(budget_policy, SynthesisBudgetPolicyV1):
        raise Protocol27LifecycleError("synthesis request requires a synthesis budget policy")
    return SynthesisRequestV1(
        schema_version=1,
        parent_manifest_hash=parent.parent_manifest_hash,
        accepted_source_outcome_ids=tuple(
            sorted(item.identity for item in parent.accepted_sources)
        ),
        accepted_partial_source_ids=tuple(
            item.source_id for item in parent.accepted_sources if item.outcome == "partial"
        ),
        budget_policy_hash=budget_policy.identity,
        expected_v2_index_hash=expected_v2_index_hash,
        expected_compatibility_generation=expected_compatibility_generation,
    )


def partial_acceptance_for(
    parent: ResolvedSynthesisParentV1,
    source_id: str,
    request: SynthesisRequestV1,
) -> PartialSourceAcceptanceV1:
    source = next(
        (item for item in parent.accepted_sources if item.source_id == source_id),
        None,
    )
    if source is None:
        raise Protocol27AuthorityError(f"unknown partial source: {source_id}")
    if source.outcome != "partial" or source.debt_manifest_hash is None:
        raise Protocol27AuthorityError(
            f"complete source cannot be accepted as partial: {source_id}"
        )
    summary_hash = parent.debt_summary_hashes.get(source_id)
    if summary_hash is None:
        raise Protocol27AuthorityError(
            f"partial source has no authenticated debt summary: {source_id}"
        )
    if source_id not in request.accepted_partial_source_ids:
        raise Protocol27AuthorityError(
            f"request does not accept partial source: {source_id}"
        )
    return PartialSourceAcceptanceV1(
        schema_version=1,
        parent_run_id=parent.parent_run_id,
        parent_manifest_hash=parent.parent_manifest_hash,
        source_id=source.source_id,
        source_root_key_id=source.source_root_key_id,
        source_root_hash=source.source_root_hash,
        debt_manifest_hash=source.debt_manifest_hash,
        debt_summary_hash=summary_hash,
        operation_id=request.request_id,
    )


def partial_acceptances_for(
    parent: ResolvedSynthesisParentV1,
    request: SynthesisRequestV1,
) -> tuple[PartialSourceAcceptanceV1, ...]:
    expected = tuple(
        item.source_id for item in parent.accepted_sources if item.outcome == "partial"
    )
    if request.parent_manifest_hash != parent.parent_manifest_hash:
        raise Protocol27AuthorityError("request parent manifest does not match authority")
    if request.accepted_partial_source_ids != expected:
        raise Protocol27AuthorityError(
            "request partial acceptance set differs from parent authority"
        )
    return tuple(partial_acceptance_for(parent, source_id, request) for source_id in expected)


def find_exact_protocol_27_child(
    workspace_root: Path,
    request_id: str,
) -> Path | None:
    runs = Path(workspace_root).resolve() / "runs"
    if not runs.is_dir():
        return None
    matches: list[Path] = []
    for candidate in sorted(runs.iterdir(), key=lambda item: item.name):
        manifest_path = candidate / "v2" / "run.json"
        if candidate.is_symlink() or not manifest_path.is_file() or manifest_path.is_symlink():
            continue
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(raw, dict) or (
            raw.get("schema_version"), raw.get("engine_protocol_version")
        ) != (6, "2.7"):
            continue
        try:
            manifest = load_run_manifest(candidate)
        except Exception as exc:
            raise Protocol27AuthorityError(
                f"invalid protocol-2.7 child manifest: {candidate.name}"
            ) from exc
        if isinstance(manifest, RunManifestV6) and manifest.request_id == request_id:
            matches.append(candidate)
    if len(matches) > 1:
        raise Protocol27AuthorityError(
            "multiple protocol-2.7 children share one exact request identity"
        )
    return matches[0] if matches else None


def run_synthesis_child(*_args: object, **_kwargs: object) -> None:
    """Task-12 lifecycle seam; deliberately unavailable before child creation exists."""
    raise Protocol27LifecycleError(
        "protocol-2.7 synthesis execution is not registered yet"
    )


__all__ = (
    "Protocol27LifecycleError",
    "find_exact_protocol_27_child",
    "partial_acceptance_for",
    "partial_acceptances_for",
    "run_synthesis_child",
    "synthesis_request",
)

