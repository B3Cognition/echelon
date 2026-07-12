from pathlib import Path

from tests.contract.static_contracts import (
    validate_auditor_calibration_dashboard_contract,
    validate_auditor_internalization_contract,
    validate_auditor_internalizer_split_contract,
    validate_build_phase_constitution_preflight_contract,
    validate_cartographer_tool_usage_contract,
    validate_code_reviewer_confidence_filter_contract,
    validate_guardian_mode_config_naming_contract,
    validate_lexicon_derived_spec_contract,
    validate_re_source_ownership_contract,
    validate_commander_loading_contract,
    validate_commander_routing_mandate_contract,
    validate_commander_token_tracking_contract,
    validate_constitution_context_pack_contract,
    validate_constitution_source_of_truth_contract,
    validate_guardian_always_on_contract,
    validate_implementer_eval_protocol_contract,
    validate_sage_contradiction_types_contract,
    validate_sage_decisions_schema_contract,
    validate_sage_understanding_followup_contract,
    validate_sentinel_flakiness_contract,
    validate_state_schema_build_qa_split_contract,
    validate_veteran_project_scoping_contract,
)


ROOT = Path(__file__).resolve().parents[2]


def test_commander_loading_contract() -> None:
    assert validate_commander_loading_contract(ROOT) == []


def test_commander_routing_mandate_contract() -> None:
    assert validate_commander_routing_mandate_contract(ROOT) == []


def test_guardian_always_on_contract() -> None:
    assert validate_guardian_always_on_contract(ROOT) == []


def test_guardian_mode_config_naming_contract() -> None:
    assert validate_guardian_mode_config_naming_contract(ROOT) == []


def test_lexicon_derived_spec_contract() -> None:
    assert validate_lexicon_derived_spec_contract(ROOT) == []


def test_build_phase_constitution_preflight_contract() -> None:
    assert validate_build_phase_constitution_preflight_contract(ROOT) == []


def test_constitution_source_of_truth_contract() -> None:
    assert validate_constitution_source_of_truth_contract(ROOT) == []


def test_constitution_context_pack_contract() -> None:
    assert validate_constitution_context_pack_contract(ROOT) == []


def test_cartographer_tool_usage_contract() -> None:
    assert validate_cartographer_tool_usage_contract(ROOT) == []


def test_code_reviewer_confidence_filter_contract() -> None:
    assert validate_code_reviewer_confidence_filter_contract(ROOT) == []


def test_commander_token_tracking_contract() -> None:
    assert validate_commander_token_tracking_contract(ROOT) == []


def test_implementer_eval_protocol_contract() -> None:
    assert validate_implementer_eval_protocol_contract(ROOT) == []


def test_sentinel_flakiness_contract() -> None:
    assert validate_sentinel_flakiness_contract(ROOT) == []


def test_sage_contradiction_types_contract() -> None:
    assert validate_sage_contradiction_types_contract(ROOT) == []


def test_sage_decisions_schema_contract() -> None:
    assert validate_sage_decisions_schema_contract(ROOT) == []


def test_sage_understanding_followup_contract() -> None:
    assert validate_sage_understanding_followup_contract(ROOT) == []


def test_veteran_project_scoping_contract() -> None:
    assert validate_veteran_project_scoping_contract(ROOT) == []


def test_re_source_ownership_contract() -> None:
    assert validate_re_source_ownership_contract(ROOT) == []


def test_auditor_internalizer_split_contract() -> None:
    assert validate_auditor_internalizer_split_contract(ROOT) == []


def test_auditor_internalization_contract() -> None:
    assert validate_auditor_internalization_contract(ROOT) == []


def test_auditor_calibration_dashboard_contract() -> None:
    assert validate_auditor_calibration_dashboard_contract(ROOT) == []


def test_state_schema_build_qa_split_contract() -> None:
    assert validate_state_schema_build_qa_split_contract(ROOT) == []
