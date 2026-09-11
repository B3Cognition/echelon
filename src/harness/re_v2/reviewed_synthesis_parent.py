"""Authenticate reviewed protocol-2.8 knowledge for workspace synthesis.

This module is an authority adapter only. It does not schedule work, invoke a
provider, or publish output. The existing protocol-2.7 lifecycle owns those
operations after this adapter has frozen an exact synthesis parent.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.protocol_27.authority import ResolvedSynthesisParentV1
from harness.re_v2.protocol_27.model import (
    AcceptedSourceOutcomeV1,
    AcceptedSourceOverviewCatalogV1,
    AcceptedSourceOverviewProjectionV1,
)
from harness.re_v2.protocol_28.context import load_protocol_28_run_context
from harness.re_v2.protocol_28.events import replay_protocol_28
from harness.re_v2.protocol_28.model import KnowledgeValueV1
from harness.re_v2.protocol_28.reconciliation import (
    KnowledgeReconciliationCandidateV1,
    KnowledgeReconciliationReviewV1,
    KnowledgeReconciliationRootV1,
    ReviewedKnowledgeRunRootV1,
)
from harness.re_v2.run_store import load_run_manifest


class ReviewedSynthesisParentError(RuntimeError):
    """Raised when reviewed knowledge is not exact terminal authority."""


@dataclass(frozen=True, slots=True)
class ReviewedSourceKnowledgeProjectionV1(KnowledgeValueV1):
    """Bind one reviewed source root to the Markdown supplied to synthesis."""

    schema_version: int
    source_id: str
    reviewed_run_root_id: str
    source_root_id: str
    work_item_id: str
    candidate_id: str
    review_id: str
    debt_acceptance_ids: tuple[str, ...]
    debt_ids: tuple[str, ...]
    rendered_markdown_hash: str


@dataclass(frozen=True, slots=True)
class ReviewedSourceDebtSummaryV1(KnowledgeValueV1):
    """Exact per-source debt lineage carried into synthesis and publication."""

    schema_version: int
    source_id: str
    source_root_id: str
    debt_acceptance_ids: tuple[str, ...]
    debt_ids: tuple[str, ...]


def resolve_reviewed_synthesis_parent(
    workspace_root: Path,
    from_run: str,
) -> ResolvedSynthesisParentV1:
    """Freeze a terminal reviewed run as an existing synthesis-parent shape."""

    root = Path(workspace_root).resolve()
    run_dir = _run_directory(root, from_run)
    before = load_run_manifest(run_dir)
    try:
        context = load_protocol_28_run_context(run_dir)
        events = context.events.replay()
        state = replay_protocol_28(events)
        if not state.terminal or state.run_root_id is None:
            raise ReviewedSynthesisParentError(
                "synthesis requires terminal reviewed knowledge authority"
            )
        completions = [event for event in events if event.type == "knowledge_run_completed"]
        if len(completions) != 1:
            raise ReviewedSynthesisParentError(
                "synthesis requires one terminal reviewed completion"
            )

        from harness.re_v2.knowledge_revision import load_knowledge_revision

        active = load_knowledge_revision(context)
        if active is None:
            raise ReviewedSynthesisParentError(
                "synthesis requires an active reviewed revision"
            )
        _, view = context.ledger.read_snapshot()
        run_root = view.knowledge_run_roots.get(state.run_root_id)
        if not isinstance(run_root, ReviewedKnowledgeRunRootV1):
            raise ReviewedSynthesisParentError(
                "terminal reviewed run root is unavailable"
            )
        completion = completions[0]
        if (
            completion.payload.get("run_root_id") != run_root.identity
            or completion.payload.get("revision_id") != run_root.revision_id
            or tuple(completion.payload.get("debt_ids", ())) != run_root.debt_ids
            or run_root.revision_manifest_id != active.manifest.identity
            or run_root.authorization_id != active.authorization.identity
            or run_root.snapshot_id != active.authorization.snapshot_id
        ):
            raise ReviewedSynthesisParentError(
                "terminal reviewed completion differs from active authority"
            )

        materializer_hash = _materializer_authority_hash()
        authority_objects: dict[str, bytes] = {}
        overview_payloads: dict[str, bytes] = {}
        outcomes: list[AcceptedSourceOutcomeV1] = []
        projections: list[AcceptedSourceOverviewProjectionV1] = []
        debt_summaries: dict[str, str] = {}
        source_roots = []
        for source_root_id in run_root.source_root_ids:
            source_root = view.knowledge_roots.get(source_root_id)
            if not isinstance(source_root, KnowledgeReconciliationRootV1):
                raise ReviewedSynthesisParentError(
                    "reviewed source root is unavailable"
                )
            if source_root.scope != "source" or source_root.identity != source_root_id:
                raise ReviewedSynthesisParentError(
                    "reviewed source root has invalid scope or identity"
                )
            source_roots.append(source_root)
        if tuple(item.source_id for item in sorted(source_roots, key=lambda item: item.source_id)) != tuple(
            sorted({item.source_id for item in source_roots})
        ):
            raise ReviewedSynthesisParentError(
                "reviewed source roots must exactly and uniquely cover their sources"
            )

        for source_root in sorted(source_roots, key=lambda item: item.source_id):
            candidate = _read_model(
                context,
                source_root.candidate_id,
                KnowledgeReconciliationCandidateV1,
            )
            review = _read_model(
                context,
                source_root.review_id,
                KnowledgeReconciliationReviewV1,
            )
            if review.candidate_id != candidate.identity or review.verdict not in {
                "PASS",
                "ACCEPT_WITH_DEBT",
            }:
                raise ReviewedSynthesisParentError(
                    f"reviewed source is not accepted: {source_root.source_id}"
                )
            markdown = candidate.rendered_markdown.encode("utf-8")
            markdown_hash = content_digest(markdown)
            overview_payloads[markdown_hash] = markdown
            source_projection = ReviewedSourceKnowledgeProjectionV1(
                schema_version=1,
                source_id=source_root.source_id,
                reviewed_run_root_id=run_root.identity,
                source_root_id=source_root.identity,
                work_item_id=source_root.work_item_id,
                candidate_id=candidate.identity,
                review_id=review.identity,
                debt_acceptance_ids=source_root.debt_acceptance_ids,
                debt_ids=source_root.debt_ids,
                rendered_markdown_hash=markdown_hash,
            )
            _add_value(authority_objects, source_projection)

            lower_ids = {
                source_projection.identity,
                source_root.work_item_id,
                *source_root.input_result_ids,
                candidate.identity,
                review.identity,
                source_root.producer_capture_id,
                source_root.reviewer_capture_id,
                *source_root.debt_acceptance_ids,
                *source_root.debt_ids,
            }
            _add_object(context, authority_objects, source_root.identity)
            for object_id in sorted(lower_ids - {source_projection.identity}):
                _add_object(context, authority_objects, object_id)

            debt_manifest_hash = None
            if source_root.debt_ids:
                summary = ReviewedSourceDebtSummaryV1(
                    schema_version=1,
                    source_id=source_root.source_id,
                    source_root_id=source_root.identity,
                    debt_acceptance_ids=source_root.debt_acceptance_ids,
                    debt_ids=source_root.debt_ids,
                )
                _add_value(authority_objects, summary)
                debt_manifest_hash = summary.identity
                debt_summaries[source_root.source_id] = summary.identity

            outcome = AcceptedSourceOutcomeV1(
                schema_version=1,
                source_id=source_root.source_id,
                source_root_key_id=source_root.identity,
                source_root_hash=source_root.identity,
                outcome="partial" if debt_manifest_hash is not None else "complete",
                debt_manifest_hash=debt_manifest_hash,
                lower_authority_ids=tuple(sorted(lower_ids)),
            )
            outcomes.append(outcome)
            projections.append(
                AcceptedSourceOverviewProjectionV1(
                    schema_version=1,
                    source_id=source_root.source_id,
                    selected_layer="reviewed",
                    source_root_key_id=source_root.identity,
                    source_root_hash=source_root.identity,
                    materializer_protocol_version="reviewed-v1",
                    materializer_authority_hash=materializer_hash,
                    content_hash=markdown_hash,
                    object_hash=markdown_hash,
                )
            )

        after = load_run_manifest(run_dir)
        if before != after:
            raise ReviewedSynthesisParentError(
                "reviewed parent manifest changed during authority read"
            )
        catalog = AcceptedSourceOverviewCatalogV1(
            schema_version=1,
            projections=tuple(projections),
        )
        return ResolvedSynthesisParentV1(
            parent_run_id=before.run_id,
            parent_manifest_hash=before.run_manifest_id,
            source_snapshot_id=before.source_snapshot_id,
            partition_manifest_id=before.partition_manifest_id,
            selected_layers={item.source_id: "reviewed" for item in outcomes},
            accepted_sources=tuple(outcomes),
            authority_objects=authority_objects,
            debt_summary_hashes=debt_summaries,
            _context=context,
            _overview_catalog=catalog,
            _overview_payloads=overview_payloads,
            _overview_authorities={
                item.source_id: (item.source_root_key_id, item.content_hash)
                for item in projections
            },
        )
    except ReviewedSynthesisParentError:
        raise
    except Exception as exc:
        raise ReviewedSynthesisParentError(
            f"cannot authenticate terminal reviewed synthesis parent: {exc}"
        ) from exc


def _read_model(context, object_id: str, expected_type):  # type: ignore[no-untyped-def]
    from harness.re_v2.knowledge_revision import _read

    value = _read(context.objects, object_id, expected_type)
    if not isinstance(value, expected_type):
        raise ReviewedSynthesisParentError(
            f"reviewed authority has unexpected type: {object_id}"
        )
    return value


def _add_object(context, target: dict[str, bytes], object_id: str) -> None:
    payload = context.objects.read_blob(object_id)
    if content_digest(payload) != object_id:
        raise ReviewedSynthesisParentError(
            f"reviewed authority object hash mismatch: {object_id}"
        )
    target[object_id] = payload


def _add_value(target: dict[str, bytes], value: KnowledgeValueV1) -> None:
    payload = canonical_json_bytes(value.to_json_dict())
    if content_digest(payload) != value.identity:
        raise ReviewedSynthesisParentError("reviewed adapter identity mismatch")
    target[value.identity] = payload


def _materializer_authority_hash() -> str:
    from harness.re_v2.protocol_22.authorities import implementation_closure_digest

    path = Path(__file__)
    if path.suffix == ".pyc" and path.with_suffix(".py").is_file():
        path = path.with_suffix(".py")
    if path.is_symlink() or not path.is_file():
        raise ReviewedSynthesisParentError(
            "reviewed synthesis materializer authority is unavailable"
        )
    return implementation_closure_digest(
        {"harness/re_v2/reviewed_synthesis_parent.py": path.read_bytes()}
    )


def _run_directory(workspace_root: Path, from_run: str) -> Path:
    if (
        not isinstance(from_run, str)
        or not from_run
        or from_run in {".", ".."}
        or any(
            character
            not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-"
            for character in from_run
        )
    ):
        raise ReviewedSynthesisParentError(f"unsafe parent run ID: {from_run!r}")
    runs = workspace_root / "runs"
    run_dir = runs / from_run
    try:
        if run_dir.resolve().parent != runs.resolve():
            raise ReviewedSynthesisParentError(
                "reviewed parent escaped the workspace run root"
            )
    except OSError as exc:
        raise ReviewedSynthesisParentError(
            f"cannot resolve reviewed parent run: {from_run}"
        ) from exc
    if not run_dir.is_dir() or run_dir.is_symlink():
        raise ReviewedSynthesisParentError(
            f"reviewed parent run does not exist: {from_run}"
        )
    return run_dir


__all__ = (
    "ReviewedSourceDebtSummaryV1",
    "ReviewedSourceKnowledgeProjectionV1",
    "ReviewedSynthesisParentError",
    "resolve_reviewed_synthesis_parent",
)
