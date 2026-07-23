"""One ownership boundary for state-store transaction identities."""

from __future__ import annotations

from collections.abc import Iterable


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
        "tasks_lexicon_gate_exhausted",
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

STORE_OWNED_TRANSACTION_KEYS = frozenset().union(
    CAS_AND_RUN_IDENTITY_KEYS,
    ROUTING_AND_HISTORY_IDENTITY_KEYS,
    LIFECYCLE_AND_DIAGNOSTIC_KEYS,
    ATOMIC_STORE_CONTROL_KEYS,
    PHASE_A_IDENTITY_KEYS,
)

TRUSTED_ROUTING_EFFECT_KEYS = frozenset(
    {
        "status",
        "blocked_reason",
        "controller_contract_error",
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
        *PHASE_A_IDENTITY_KEYS,
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
