from __future__ import annotations

from dataclasses import replace

import pytest

from harness.re_v2.canonical import content_digest
from harness.re_v2.protocol_25.preflight import (
    AuditContextPreflightEntryV1,
    AuditContextPreflightFailureV1,
    AuditContextPreflightResultV1,
    Protocol25PreflightError,
)
from tests.re_v2_protocol_22_fixtures import digest


def _entry(seed: str = "a") -> AuditContextPreflightEntryV1:
    return AuditContextPreflightEntryV1(
        schema_version=1,
        audit_target_id=digest(f"target:{seed}"),
        work_item_id=digest(f"work:{seed}"),
        context_hash=digest(f"context:{seed}"),
        canonical_json_bytes=58_051,
    )


def _failure() -> AuditContextPreflightFailureV1:
    return AuditContextPreflightFailureV1(
        schema_version=1,
        audit_target_id=digest("target:source"),
        work_item_id=digest("work:source"),
        scope_kind="source",
        source_id="pressbox-search-soccer-api",
        domain_key=None,
        reason_code="semantic_context_byte_ceiling_exceeded",
        projection_class="semantic-audit-context",
        measured_canonical_json_bytes=2_701_823,
        max_canonical_json_bytes=196_608,
        provider_dispatch_count=0,
    )


def test_preflight_values_round_trip_canonically() -> None:
    entry = _entry()
    failure = _failure()
    passed = AuditContextPreflightResultV1(
        schema_version=1,
        entries=(entry,),
        failure=None,
        max_canonical_json_bytes=196_608,
    )
    failed = AuditContextPreflightResultV1(
        schema_version=1,
        entries=(),
        failure=failure,
        max_canonical_json_bytes=196_608,
    )

    assert AuditContextPreflightEntryV1.from_json_dict(entry.to_json_dict()) == entry
    assert AuditContextPreflightFailureV1.from_json_dict(
        failure.to_json_dict()
    ) == failure
    assert AuditContextPreflightResultV1.from_json_dict(passed.to_json_dict()) == passed
    assert AuditContextPreflightResultV1.from_json_dict(failed.to_json_dict()) == failed
    assert entry.identity == content_digest(entry.to_json_dict())
    assert failure.identity == content_digest(failure.to_json_dict())


def test_preflight_failure_requires_zero_dispatch_and_exact_ceiling_relation() -> None:
    failure = _failure()

    with pytest.raises(Protocol25PreflightError, match="zero provider"):
        replace(failure, provider_dispatch_count=1)
    with pytest.raises(Protocol25PreflightError, match="exceed"):
        replace(failure, measured_canonical_json_bytes=196_608)
    with pytest.raises(Protocol25PreflightError, match="domain_key"):
        replace(failure, scope_kind="domain", domain_key=None)
    with pytest.raises(Protocol25PreflightError, match="reason"):
        replace(failure, reason_code="unknown")


def test_preflight_result_is_exactly_success_or_failure() -> None:
    entry = _entry()
    failure = _failure()

    with pytest.raises(Protocol25PreflightError, match="success or failure"):
        AuditContextPreflightResultV1(1, (entry,), failure, 196_608)
    with pytest.raises(Protocol25PreflightError, match="success or failure"):
        AuditContextPreflightResultV1(1, (), None, 196_608)
    reverse_order = tuple(
        sorted((_entry("a"), _entry("b")), key=lambda item: item.audit_target_id, reverse=True)
    )
    with pytest.raises(Protocol25PreflightError, match="ordered"):
        AuditContextPreflightResultV1(1, reverse_order, None, 196_608)
