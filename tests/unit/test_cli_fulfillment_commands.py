from echelon import cli


def test_verify_spec_command_registered():
    assert cli.SKILL_MAP["verify-spec"] == "echelon.verify-spec"
    assert "verify-spec <spec_id>" in cli.USAGE


def test_reopen_command_registered():
    assert cli.SKILL_MAP["reopen"] == "echelon.reopen"
    assert "reopen  <spec_id>" in cli.USAGE
