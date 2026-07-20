"""Tests for deterministic echelon_result schema validation."""
import re
import sys
from pathlib import Path

import pytest
import yaml

EXT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(EXT_ROOT) not in sys.path:
    sys.path.insert(0, str(EXT_ROOT))

from harness.echelon_result_schema import (  # noqa: E402
    ALLOWED_VERDICTS,
    EchelonResultContract,
    EchelonResultValidationError,
    validate_echelon_result,
    validate_echelon_result_contract,
)


def test_valid_result_is_normalized_without_mutating_input():
    payload = {
        "verdict": "DONE",
        "state_updates": {"coverage_pct": 72},
        "journal_entries": [{"type": "quality_check"}],
    }

    normalized = validate_echelon_result(payload)

    assert normalized == payload
    assert normalized is not payload


def test_known_routing_verdicts_are_supported():
    for verdict in ("CHANGES_REQUESTED", "DRIFT", "NEEDS_CONTEXT", "STOP_AND_ASK"):
        normalized = validate_echelon_result(
            {
                "verdict": verdict,
                "state_updates": (
                    {
                        "status": "blocked",
                        "blocked_reason": "user intent needs clarification",
                        "escalation_question": "Which target should Echelon use?",
                    }
                    if verdict == "STOP_AND_ASK"
                    else {}
                ),
            }
        )
        assert normalized["verdict"] == verdict


def test_workflow_condition_verdicts_are_supported_by_schema():
    definition = yaml.safe_load(
        (EXT_ROOT / "extension" / "workflow" / "definition.yaml").read_text(
            encoding="utf-8"
        )
    )
    verdicts = set()
    for phase in definition.get("phases") or []:
        for transition in phase.get("transitions") or []:
            condition = transition.get("condition")
            if not isinstance(condition, str):
                continue
            verdicts.update(
                re.findall(r"\bverdict\s*=\s*([A-Z][A-Z0-9_]*)", condition)
            )
            for match in re.finditer(r"\bverdict\s+in\s+\[([^\]]+)\]", condition):
                verdicts.update(
                    value.strip()
                    for value in match.group(1).split(",")
                    if re.fullmatch(r"[A-Z][A-Z0-9_]*", value.strip())
                )

    assert not sorted(verdicts - ALLOWED_VERDICTS)


def test_bad_top_level_type_is_rejected():
    with pytest.raises(EchelonResultValidationError, match="must be an object"):
        validate_echelon_result(["not", "an", "object"])


def test_missing_verdict_is_rejected():
    with pytest.raises(EchelonResultValidationError, match="verdict"):
        validate_echelon_result({"state_updates": {}})


def test_non_string_verdict_is_rejected():
    with pytest.raises(EchelonResultValidationError, match="verdict"):
        validate_echelon_result({"verdict": 123, "state_updates": {}})


def test_unsupported_verdict_is_rejected():
    with pytest.raises(EchelonResultValidationError, match="unsupported verdict"):
        validate_echelon_result({"verdict": "MAYBE", "state_updates": {}})


def test_missing_state_updates_defaults_for_non_blocking_verdict():
    assert validate_echelon_result({"verdict": "PASS"})["state_updates"] == {}


def test_blocked_result_requires_state_updates():
    with pytest.raises(EchelonResultValidationError, match="state_updates"):
        validate_echelon_result({"verdict": "BLOCKED"})


def test_stop_and_ask_result_requires_escalation_question():
    with pytest.raises(EchelonResultValidationError, match="escalation_question"):
        validate_echelon_result({
            "verdict": "STOP_AND_ASK",
            "state_updates": {
                "status": "blocked",
                "blocked_reason": "user intent needs clarification",
            },
        })


def test_stop_and_ask_result_requires_blocked_status():
    with pytest.raises(EchelonResultValidationError, match="status"):
        validate_echelon_result({
            "verdict": "STOP_AND_ASK",
            "state_updates": {
                "blocked_reason": "user intent needs clarification",
                "escalation_question": "Which target should Echelon use?",
            },
        })


def test_stop_and_ask_result_requires_blocked_reason():
    with pytest.raises(EchelonResultValidationError, match="blocked_reason"):
        validate_echelon_result({
            "verdict": "STOP_AND_ASK",
            "state_updates": {
                "status": "blocked",
                "escalation_question": "Which target should Echelon use?",
            },
        })


def test_bad_state_updates_type_is_rejected():
    with pytest.raises(EchelonResultValidationError, match="state_updates"):
        validate_echelon_result({"verdict": "DONE", "state_updates": []})


def test_bad_journal_entries_type_is_rejected():
    with pytest.raises(EchelonResultValidationError, match="journal_entries"):
        validate_echelon_result({
            "verdict": "DONE",
            "state_updates": {},
            "journal_entries": {},
        })


def test_product_input_updates_require_the_canonical_traceability_fields():
    with pytest.raises(EchelonResultValidationError, match="input_unit_id"):
        validate_echelon_result({
            "verdict": "DONE",
            "state_updates": {},
            "product_input_updates": [{
                "unit": "IN-REQ-123",
                "disposition": "adopted",
                "mapped": ["FR-001"],
                "rationale": "Natural-language aliases must not bypass the contract.",
            }],
        })


def test_product_input_updates_accept_a_phase_one_mapping_without_tasks():
    result = validate_echelon_result({
        "verdict": "DONE",
        "state_updates": {},
        "product_input_updates": [{
            "input_unit_id": "IN-REQ-123",
            "disposition": "included",
            "rationale": "Captured by the specification.",
            "spec_ids": ["FR-001", "AC-001"],
            "task_ids": [],
            "targets": [],
        }],
    })

    assert result["product_input_updates"][0]["input_unit_id"] == "IN-REQ-123"


def test_reserved_harness_state_key_is_rejected():
    with pytest.raises(EchelonResultValidationError, match="last_dispatch"):
        validate_echelon_result({
            "verdict": "DONE",
            "state_updates": {"last_dispatch": {"phase_id": "fake"}},
        })


def test_state_update_key_outside_allowlist_is_rejected():
    with pytest.raises(EchelonResultValidationError, match="not allowed"):
        validate_echelon_result(
            {
                "verdict": "DONE",
                "state_updates": {"unexpected": True},
            },
            allowed_state_update_keys={"coverage_pct"},
        )


def test_empty_state_updates_are_allowed_by_empty_allowlist():
    result = validate_echelon_result(
        {"verdict": "DONE", "state_updates": {}},
        allowed_state_update_keys=set(),
    )

    assert result["state_updates"] == {}


def test_quality_scores_pass_must_be_boolean():
    with pytest.raises(EchelonResultValidationError, match="quality_scores\\[0\\]\\.pass"):
        validate_echelon_result(
            {
                "verdict": "FAIL",
                "state_updates": {
                    "quality_scores": [{"pass": "WHY2-iter-0"}],
                },
            },
            allowed_state_update_keys={"quality_scores"},
        )


def test_result_contract_quarantines_reporting_fields_but_keeps_routing_state():
    contract = EchelonResultContract(
        allowed_state_update_keys=frozenset({"tasks_lexicon_pass"}),
        required_state_update_keys=frozenset({"tasks_lexicon_pass"}),
        state_update_types={"tasks_lexicon_pass": "boolean"},
        allowed_verdicts=frozenset({"COMPLETE", "BLOCKED"}),
        unexpected_state_updates="quarantine",
    )
    payload = {
        "verdict": "COMPLETE",
        "state_updates": {
            "tasks_lexicon_pass": True,
            "phase3_plan_verdict": "COMPLETE",
            "critical_path_length_days": 118,
            "total_tasks": 61,
            "parallelizable_tasks": 40,
            "high_risk_tasks": 9,
            "blocking_gates": [],
            "test_automation_coverage": 0.92,
        },
    }

    outcome = validate_echelon_result_contract(payload, contract)

    assert outcome.result["state_updates"] == {"tasks_lexicon_pass": True}
    assert set(outcome.quarantined_state_updates) == {
        "phase3_plan_verdict",
        "critical_path_length_days",
        "total_tasks",
        "parallelizable_tasks",
        "high_risk_tasks",
        "blocking_gates",
        "test_automation_coverage",
    }


def test_result_contract_rejects_missing_required_routing_state():
    contract = EchelonResultContract(
        allowed_state_update_keys=frozenset({"tasks_lexicon_pass"}),
        required_state_update_keys=frozenset({"tasks_lexicon_pass"}),
        state_update_types={"tasks_lexicon_pass": "boolean"},
    )

    with pytest.raises(EchelonResultValidationError, match="required state_updates"):
        validate_echelon_result_contract(
            {"verdict": "COMPLETE", "state_updates": {"tasks_lexicon_pas": True}},
            contract,
        )


def test_result_contract_rejects_invalid_routing_state_type():
    contract = EchelonResultContract(
        allowed_state_update_keys=frozenset({"tasks_lexicon_attempts"}),
        required_state_update_keys=frozenset({"tasks_lexicon_attempts"}),
        state_update_types={"tasks_lexicon_attempts": "integer"},
    )

    with pytest.raises(EchelonResultValidationError, match="must be an integer"):
        validate_echelon_result_contract(
            {
                "verdict": "COMPLETE",
                "state_updates": {"tasks_lexicon_attempts": "two"},
            },
            contract,
        )


def test_result_contract_rejects_phase_invalid_verdict():
    contract = EchelonResultContract(
        allowed_state_update_keys=frozenset(),
        allowed_verdicts=frozenset({"PASS", "FAIL", "BLOCKED"}),
    )

    with pytest.raises(EchelonResultValidationError, match="not allowed for this dispatch"):
        validate_echelon_result_contract(
            {"verdict": "COMPLETE", "state_updates": {}},
            contract,
        )


def test_result_contract_rejects_invented_state_status_value():
    contract = EchelonResultContract(
        allowed_state_update_keys=frozenset({"status"}),
        state_update_types={"status": "string"},
        state_update_enums={"status": frozenset({"running", "blocked", "done"})},
    )

    with pytest.raises(EchelonResultValidationError, match="must be one of"):
        validate_echelon_result_contract(
            {"verdict": "DONE", "state_updates": {"status": "almost_finished"}},
            contract,
        )
