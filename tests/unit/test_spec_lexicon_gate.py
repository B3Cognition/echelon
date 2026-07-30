from pathlib import Path

import pytest

from harness.spec_lexicon_gate import run_spec_lexicon_gate


@pytest.mark.unit
@pytest.mark.parametrize(
    "config",
    [
        {"lexicon_gate": {"enabled": False}},
        {
            "lexicon_gate": {
                "enabled": True,
                "artifacts": {"spec": {"enabled": False}},
            }
        },
    ],
)
def test_disabled_spec_gate_is_pending_without_certificate_metadata(
    tmp_path: Path,
    config: dict[str, object],
) -> None:
    result = run_spec_lexicon_gate(
        project_root=tmp_path,
        spec_dir_ref="",
        config=config,
        previous_attempts=7,
    )

    assert result.evaluation == "pending"
    assert result.passed is None
    assert result.attempts == 0
    assert result.findings is None
    assert result.report_path is None
    assert result.state_updates() == {
        "lexicon_evaluation": "pending",
        "lexicon_attempts": 0,
    }
