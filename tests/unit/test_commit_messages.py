from echelon.commit_messages import EchelonCommitMetadata, build_echelon_commit_message


def test_build_echelon_commit_message_adds_standard_trailers() -> None:
    message = build_echelon_commit_message(
        "echelon-checkpoint: 001-demo phase3-plan",
        EchelonCommitMetadata(
            origin="phase-a",
            action="checkpoint",
            spec_id="001-demo",
            run_id="squad-20260704-123456",
            phase="phase3-plan",
        ),
    )

    assert message.startswith("echelon-checkpoint: 001-demo phase3-plan\n\n")
    assert "Co-authored-by: Echelon <echelon@b3cognition.dev>" in message
    assert "Echelon-Origin: phase-a" in message
    assert "Echelon-Action: checkpoint" in message
    assert "Echelon-Spec: 001-demo" in message
    assert "Echelon-Run: squad-20260704-123456" in message
    assert "Echelon-Phase: phase3-plan" in message


def test_build_echelon_commit_message_omits_empty_optional_trailers() -> None:
    message = build_echelon_commit_message(
        "chore: initialize echelon workspace",
        EchelonCommitMetadata(origin="workspace", action="init"),
    )

    assert "Echelon-Origin: workspace" in message
    assert "Echelon-Action: init" in message
    assert "Echelon-Spec:" not in message
    assert "Echelon-Phase:" not in message


def test_build_echelon_commit_message_rejects_blank_required_fields() -> None:
    try:
        build_echelon_commit_message(
            "",
            EchelonCommitMetadata(origin="phase-a", action="checkpoint"),
        )
    except ValueError as exc:
        assert "subject" in str(exc)
    else:
        raise AssertionError("blank subject should fail")


def test_completion_checkpoint_commit_message_adds_exact_identity_trailers() -> None:
    message = build_echelon_commit_message(
        "echelon-checkpoint: 001-demo phase3-plan",
        EchelonCommitMetadata(
            origin="phase-a",
            action="checkpoint",
            spec_id="001-demo",
            run_id="squad-20260723-123456",
            phase="phase3-plan",
            next_phase="phase3-consensus",
            checkpoint_id="phase3-plan",
            completion_id="a" * 32,
        ),
    )

    assert "Echelon-Next-Phase: phase3-consensus" in message
    assert f"Echelon-Completion: {'a' * 32}" in message


def test_legacy_commit_message_omits_completion_checkpoint_trailers() -> None:
    message = build_echelon_commit_message(
        "echelon-checkpoint: 001-demo phase3-plan",
        EchelonCommitMetadata(
            origin="phase-a",
            action="checkpoint",
            spec_id="001-demo",
            run_id="squad-20260723-123456",
            phase="phase3-plan",
            checkpoint_id="phase3-plan",
        ),
    )

    assert "Echelon-Next-Phase:" not in message
    assert "Echelon-Completion:" not in message
