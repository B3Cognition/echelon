"""One ownership boundary for state-store transaction identities."""

from __future__ import annotations

import re
from collections.abc import Iterable


PENDING_EXTERNAL_PUBLICATION_KEY = "pending_external_publication"
PENDING_CONTROLLER_COMPLETION_KEY = "pending_controller_completion"
_PENDING_EXTERNAL_PUBLICATION_KEYS = frozenset(
    {
        "schema_version",
        "transaction_id",
        "manifest_sha256",
    }
)
_PENDING_CONTROLLER_COMPLETION_KEYS = frozenset(
    {
        "schema_version",
        "completion_id",
        "intent_sha256",
        "publication_binding_sha256",
        "receipts_sha256",
        "origin",
        "step",
    }
)
_TRANSACTION_ID_PATTERN = re.compile(r"\A[0-9a-f]{32}\Z")
_MANIFEST_SHA256_PATTERN = re.compile(r"\A[0-9a-f]{64}\Z")
_COMPLETION_ORIGINS = frozenset({"routed", "terminal"})
_COMPLETION_STEPS = frozenset(
    {
        "awaiting_publication",
        "journal",
        "timing",
        "checkpoint",
        "context",
        "mining",
        "complete",
    }
)

CAS_AND_RUN_IDENTITY_KEYS = frozenset(
    {
        "run_id",
        "state_revision",
        "created_at",
        "updated_at",
        "squad_dir",
        "staging_dir",
        "context_dir",
        "mode",
        "autonomy_mode",
        "max_iterations",
        "token_budget",
        "user_message",
        "user_request",
        "implementation_targets",
        "product_inputs",
    }
)

ROUTING_AND_HISTORY_IDENTITY_KEYS = frozenset(
    {
        "phase",
        "last_dispatch",
        "completed_phases",
        "phase_dispatch_counts",
        "iteration",
        "increment_iteration",
        "manual_phase_run",
        "manual_phase_runs",
        "conditional_skip",
        "record_completion",
        "convergence_detected",
        "convergence_forced",
        "product_input_mapping_repair",
        "product_input_mapping_repair_attempts",
        "phase_dispatch_limit_phase",
        "phase_dispatch_limit",
        "cartographer_resume_existing_spec",
        "why3_verdict",
        "assess2_verdict",
    }
)

LIFECYCLE_AND_DIAGNOSTIC_KEYS = frozenset(
    {
        "status",
        "blocked_reason",
        "blocked_detail",
        "blocked_context",
        "controller_contract_error",
        "recovery_instruction",
        "blocked_decision",
        "resume_metadata",
        "resume_answer",
        "escalation_resolved",
        "escalation_resolver",
        "escalation_selected_option",
        "interrupted_phase",
        "provider_limit_message",
        "phase_a_readiness_blockers",
        "constitution_guard_reason",
        "published_re_context",
        "phase_dispatch_limit_recovery",
        "lexicon_gate_exhausted",
        "lexicon_repair_no_artifact_progress",
        "quality_gate_remediation_no_artifact_progress",
        "tasks_lexicon_gate_exhausted",
        PENDING_EXTERNAL_PUBLICATION_KEY,
        PENDING_CONTROLLER_COMPLETION_KEY,
        "external_publication_failure",
    }
)

ATOMIC_STORE_CONTROL_KEYS = frozenset(
    {
        "token_usage",
        "cost_usd",
        "cancel_requested",
        "why_fail_count",
        "convergence_guard_fire_count",
    }
)

PHASE_A_IDENTITY_KEYS = frozenset(
    {
        "spec_id",
        "spec_number",
        "spec_dir",
        "published_spec_dir",
        "feature_branch",
        "phase_a_default_branch",
        "phase_a_base_commit",
        "specify_feature_directory",
    }
)

CONTROLLER_COMPLETION_RECEIPT_KEYS = frozenset(
    {
        "controller_completion_failure",
        "last_terminal_completion",
        "phase_a_active_source_sha256",
        "phase_a_published_postimage_sha256",
    }
)

STORE_OWNED_TRANSACTION_KEYS = frozenset().union(
    CAS_AND_RUN_IDENTITY_KEYS,
    ROUTING_AND_HISTORY_IDENTITY_KEYS,
    LIFECYCLE_AND_DIAGNOSTIC_KEYS,
    ATOMIC_STORE_CONTROL_KEYS,
    PHASE_A_IDENTITY_KEYS,
    CONTROLLER_COMPLETION_RECEIPT_KEYS,
)

TRUSTED_ROUTING_EFFECT_KEYS = frozenset(
    {
        "status",
        "blocked_reason",
        "controller_contract_error",
        "recovery_instruction",
        "blocked_decision",
        "resume_metadata",
        "escalation_resolved",
        "escalation_resolver",
        "iteration",
        "phase_dispatch_counts",
        "why_fail_count",
        "convergence_guard_fire_count",
        "convergence_detected",
        "convergence_forced",
        "product_input_mapping_repair",
        "product_input_mapping_repair_attempts",
        "phase_dispatch_limit_phase",
        "phase_dispatch_limit",
        "phase_dispatch_limit_recovery",
        "cartographer_resume_existing_spec",
        "lexicon_repair_no_artifact_progress",
        "quality_gate_remediation_no_artifact_progress",
        PENDING_EXTERNAL_PUBLICATION_KEY,
        PENDING_CONTROLLER_COMPLETION_KEY,
        *PHASE_A_IDENTITY_KEYS,
    }
)

# Durable publication completion is the only path allowed to remove its
# exact-marker state. Other trusted routing effects retain their existing
# update and removal authority.
TRUSTED_ROUTING_REMOVAL_KEYS = (
    TRUSTED_ROUTING_EFFECT_KEYS
    - {
        PENDING_EXTERNAL_PUBLICATION_KEY,
        PENDING_CONTROLLER_COMPLETION_KEY,
    }
)

# These fields are valid provider control syntax, but never ordinary provider
# state ownership. The controller extracts and promotes them before sealing.
PROVIDER_CONTROL_INTENT_KEYS = frozenset(
    {
        "status",
        "blocked_reason",
    }
)


def store_owned_update_keys(keys: Iterable[str]) -> frozenset[str]:
    """Return transaction-owned keys from an already detached update map."""
    return frozenset(keys) & STORE_OWNED_TRANSACTION_KEYS


def validate_pending_external_publication(
    value: object,
) -> dict[str, object]:
    """Return a detached exact-schema durable publication marker."""
    if (
        type(value) is not dict
        or frozenset(dict.keys(value))
        != _PENDING_EXTERNAL_PUBLICATION_KEYS
    ):
        raise ValueError(
            "pending external publication marker must have exact fields"
        )
    schema_version = dict.__getitem__(value, "schema_version")
    transaction_id = dict.__getitem__(value, "transaction_id")
    manifest_sha256 = dict.__getitem__(value, "manifest_sha256")
    if type(schema_version) is not int or schema_version != 1:
        raise ValueError(
            "pending external publication schema version is invalid"
        )
    if (
        type(transaction_id) is not str
        or _TRANSACTION_ID_PATTERN.fullmatch(transaction_id) is None
    ):
        raise ValueError(
            "pending external publication transaction id is invalid"
        )
    if (
        type(manifest_sha256) is not str
        or _MANIFEST_SHA256_PATTERN.fullmatch(manifest_sha256) is None
    ):
        raise ValueError(
            "pending external publication manifest digest is invalid"
        )
    return {
        "schema_version": schema_version,
        "transaction_id": transaction_id,
        "manifest_sha256": manifest_sha256,
    }


def validate_pending_controller_completion(
    value: object,
) -> dict[str, object]:
    """Return a detached exact-schema durable completion marker."""
    if (
        type(value) is not dict
        or frozenset(dict.keys(value))
        != _PENDING_CONTROLLER_COMPLETION_KEYS
    ):
        raise ValueError(
            "pending controller completion marker must have exact fields"
        )
    schema_version = dict.__getitem__(value, "schema_version")
    completion_id = dict.__getitem__(value, "completion_id")
    intent_sha256 = dict.__getitem__(value, "intent_sha256")
    publication_binding_sha256 = dict.__getitem__(
        value,
        "publication_binding_sha256",
    )
    receipts_sha256 = dict.__getitem__(value, "receipts_sha256")
    origin = dict.__getitem__(value, "origin")
    step = dict.__getitem__(value, "step")
    if type(schema_version) is not int or schema_version != 1:
        raise ValueError(
            "pending controller completion schema version is invalid"
        )
    if (
        type(completion_id) is not str
        or _TRANSACTION_ID_PATTERN.fullmatch(completion_id) is None
    ):
        raise ValueError(
            "pending controller completion id is invalid"
        )
    for field_name, digest in (
        ("intent", intent_sha256),
        ("publication binding", publication_binding_sha256),
        ("receipts", receipts_sha256),
    ):
        if (
            type(digest) is not str
            or _MANIFEST_SHA256_PATTERN.fullmatch(digest) is None
        ):
            raise ValueError(
                f"pending controller completion {field_name} digest is invalid"
            )
    if type(origin) is not str or origin not in _COMPLETION_ORIGINS:
        raise ValueError(
            "pending controller completion origin is invalid"
        )
    if type(step) is not str or step not in _COMPLETION_STEPS:
        raise ValueError(
            "pending controller completion step is invalid"
        )
    return {
        "schema_version": schema_version,
        "completion_id": completion_id,
        "intent_sha256": intent_sha256,
        "publication_binding_sha256": publication_binding_sha256,
        "receipts_sha256": receipts_sha256,
        "origin": origin,
        "step": step,
    }
