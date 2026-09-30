import pytest

from harness.proportional_quality import (
    QualityCandidateIntegrityError,
    sage_banzai_eligibility,
    validate_sage_resolution_guidance,
)


@pytest.mark.parametrize('value,expected', [('yes', True), ('no', False),
    ('yes — measured correction', True), ('no — user decision', False)])
def test_retained_eligibility_is_explicit(value, expected):
    assert sage_banzai_eligibility(f'- **Banzai eligible:** {value}\n', allow_legacy=True) is expected


@pytest.mark.parametrize('value', ['yes — explanation', 'maybe', 'yes or no', 'yes please', 'yes —'])
def test_new_reports_require_standalone_value(value):
    with pytest.raises(QualityCandidateIntegrityError):
        sage_banzai_eligibility(f'- **Banzai eligible:** {value}\n')


def test_duplicate_values_are_not_authority():
    with pytest.raises(QualityCandidateIntegrityError):
        sage_banzai_eligibility('- **Banzai eligible:** yes\n- **Banzai eligible:** no\n', allow_legacy=True)


@pytest.mark.parametrize('value', ['maybe', 'yes or no', 'yes please', 'yes —'])
def test_legacy_read_does_not_infer_authority(value):
    with pytest.raises(QualityCandidateIntegrityError):
        sage_banzai_eligibility(f'- **Banzai eligible:** {value}\n', allow_legacy=True)


def test_authoring_validates_supplied_guidance_before_recovery():
    report = ('### ISS-000001: Correction\n### Resolution Guidance\n'
              '- **Decision required:** correct name\n- **Suggested option:** correct it\n'
              '- **Evidence basis:** measured mismatch\n- **Banzai eligible:** yes — explanation\n')
    with pytest.raises(QualityCandidateIntegrityError):
        validate_sage_resolution_guidance(report)
    validate_sage_resolution_guidance(report.replace('yes — explanation', 'yes\n- **Banzai rationale:** explanation'))


def test_authoring_rejects_duplicate_guidance_for_same_issue():
    guidance = ('### Resolution Guidance\n- **Decision required:** correction\n'
                '- **Suggested option:** repair\n- **Evidence basis:** source\n'
                '- **Banzai eligible:** yes\n')
    with pytest.raises(QualityCandidateIntegrityError, match='duplicate'):
        validate_sage_resolution_guidance('### ISS-000001: Correction\n' + guidance + guidance)


def test_managed_why2_rejects_inline_value_before_publication():
    from harness.discovery_semantics import validate_discovery_reply
    from tests.unit.test_managed_spec_contract import assignment, routing
    bound = assignment('why2', 'author')
    value = {**bound.identity(), 'action': 'final', 'routing': routing('why2'),
        'artifacts': {'quality-gates.md': '# Quality gates\n', 'issues.md':
            '### ISS-000001: Correction\n### Resolution Guidance\n'
            '- **Decision required:** correction\n- **Suggested option:** repair\n'
            '- **Evidence basis:** source\n- **Banzai eligible:** yes — explanation\n'}}
    with pytest.raises(ValueError, match='Banzai eligible'):
        validate_discovery_reply(value, bound)


@pytest.mark.parametrize('reason,expected', [
    ('phase_dispatch_limit_evidence_malformed', 'could not read valid'),
    ('phase_dispatch_limit_evidence_ineligible', 'no explicitly eligible'),
    ('phase_dispatch_limit_evidence_too_many_candidates', 'bounded recovery option count'),
])
def test_recovery_note_distinguishes_invalid_and_ineligible_evidence(reason, expected):
    from echelon.spec_service import _recovery_action_from_instruction
    from harness.recovery_instruction import RecoveryInstruction, RecoveryKind
    instruction = RecoveryInstruction(kind=RecoveryKind.MANUAL_DIAGNOSIS,
        reason_code=reason, phase='', requires_human_input=False)
    action = _recovery_action_from_instruction(instruction, run_state={}, project_root=None)
    assert expected in action.note
    assert 'exhausted' not in action.note
