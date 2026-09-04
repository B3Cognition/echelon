"""Closed deterministic policy for protocol-2.8 exhaustive planning."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from harness.re_v2.canonical import content_digest
from harness.re_v2.protocol_22.schema import (
    Protocol22SchemaError,
    digest_value,
    exact_object,
    literal,
)


DOMAIN_CATEGORIES = (
    "public-surfaces",
    "state-models-transformations-invariants",
    "boundaries-integrations-protocols-dependencies",
    "failure-retry-recovery-degraded-behavior",
    "configuration-controls-security-permissions",
    "observability-operations-lifecycle",
    "negative-space",
)

SOURCE_CATEGORIES = (
    "source-composition",
    "cross-domain-boundaries",
    "source-configuration-security",
    "source-operations-lifecycle",
    "source-negative-space",
)


class Protocol28PolicyError(Protocol22SchemaError):
    """Raised when an exhaustive policy departs from the reviewed contract."""


def _schema(function, *args):  # type: ignore[no-untyped-def]
    try:
        return function(*args)
    except Protocol28PolicyError:
        raise
    except (Protocol22SchemaError, TypeError, ValueError) as exc:
        raise Protocol28PolicyError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class ExhaustivePolicyV1:
    """Content-addressed policy whose fixed bounds determine L4 work identity."""

    schema_version: int
    raw_shard_byte_limit: int
    max_primary_subjects: int
    max_supporting_subjects: int
    max_primary_records: int
    max_supporting_records: int
    max_context_bytes: int
    max_candidate_output_bytes: int
    max_rendered_markdown_bytes: int
    max_conservative_tokens: int
    max_entries_per_target: int
    max_entries_per_run: int
    producer_attempt_limit: int
    producer_contract_retry_limit: int
    verifier_contract_retry_limit: int
    identical_outcome_early_stop: int
    producer_contract_hash: str
    verifier_contract_hash: str
    domain_categories: tuple[str, ...]
    source_categories: tuple[str, ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "raw_shard_byte_limit",
        "max_primary_subjects",
        "max_supporting_subjects",
        "max_primary_records",
        "max_supporting_records",
        "max_context_bytes",
        "max_candidate_output_bytes",
        "max_rendered_markdown_bytes",
        "max_conservative_tokens",
        "max_entries_per_target",
        "max_entries_per_run",
        "producer_attempt_limit",
        "producer_contract_retry_limit",
        "verifier_contract_retry_limit",
        "identical_outcome_early_stop",
        "producer_contract_hash",
        "verifier_contract_hash",
        "domain_categories",
        "source_categories",
    )

    def __post_init__(self) -> None:
        fixed = {
            "schema_version": 1,
            "raw_shard_byte_limit": 65_536,
            "max_primary_subjects": 16,
            "max_supporting_subjects": 32,
            "max_primary_records": 64,
            "max_supporting_records": 128,
            "max_context_bytes": 131_072,
            "max_candidate_output_bytes": 65_536,
            "max_rendered_markdown_bytes": 98_304,
            "max_conservative_tokens": 131_072,
            "max_entries_per_target": 512,
            "max_entries_per_run": 16_384,
            "producer_attempt_limit": 3,
            "producer_contract_retry_limit": 0,
            "verifier_contract_retry_limit": 1,
            "identical_outcome_early_stop": 2,
        }
        for field, expected in fixed.items():
            _schema(literal, getattr(self, field), expected, f"ExhaustivePolicyV1.{field}")
        for field in ("producer_contract_hash", "verifier_contract_hash"):
            _schema(digest_value, getattr(self, field), f"ExhaustivePolicyV1.{field}")
        _schema(
            literal,
            self.domain_categories,
            DOMAIN_CATEGORIES,
            "ExhaustivePolicyV1.domain_categories",
        )
        _schema(
            literal,
            self.source_categories,
            SOURCE_CATEGORIES,
            "ExhaustivePolicyV1.source_categories",
        )

    @property
    def identity(self) -> str:
        return content_digest(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {
            **{
                field: getattr(self, field)
                for field in self.FIELDS
                if field not in {"domain_categories", "source_categories"}
            },
            "domain_categories": list(self.domain_categories),
            "source_categories": list(self.source_categories),
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "ExhaustivePolicyV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(
            **{
                field: (
                    tuple(raw[field])
                    if field in {"domain_categories", "source_categories"}
                    and isinstance(raw[field], (list, tuple))
                    else raw[field]
                )
                for field in cls.FIELDS
            }
        )


def build_initial_exhaustive_policy(
    *,
    producer_contract_hash: str | None = None,
    verifier_contract_hash: str | None = None,
) -> ExhaustivePolicyV1:
    """Return the immutable first-release exhaustive policy."""
    return ExhaustivePolicyV1(
        schema_version=1,
        raw_shard_byte_limit=65_536,
        max_primary_subjects=16,
        max_supporting_subjects=32,
        max_primary_records=64,
        max_supporting_records=128,
        max_context_bytes=131_072,
        max_candidate_output_bytes=65_536,
        max_rendered_markdown_bytes=98_304,
        max_conservative_tokens=131_072,
        max_entries_per_target=512,
        max_entries_per_run=16_384,
        producer_attempt_limit=3,
        producer_contract_retry_limit=0,
        verifier_contract_retry_limit=1,
        identical_outcome_early_stop=2,
        producer_contract_hash=(
            producer_contract_hash
            if producer_contract_hash is not None
            else content_digest(b"re-v2-l4-producer-contract-v1")
        ),
        verifier_contract_hash=(
            verifier_contract_hash
            if verifier_contract_hash is not None
            else content_digest(b"re-v2-l4-verifier-contract-v1")
        ),
        domain_categories=DOMAIN_CATEGORIES,
        source_categories=SOURCE_CATEGORIES,
    )
