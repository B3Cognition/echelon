from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _readme() -> str:
    return (ROOT / "README.md").read_text(encoding="utf-8")


def test_readme_documents_rewind_continue_recovery() -> None:
    text = _readme()

    assert "echelon spec rewind <phase-id>" in text
    assert "missing_echelon_result" in text
    assert "missing_phase_outputs" in text
    assert "echelon spec continue" in text


def test_readme_documents_active_run_artifact_contract() -> None:
    text = _readme()

    assert "runs/.current" in text
    assert "runs/<run>/specs/<id>" in text
    assert "canonical `specs/<id>`" in text
    assert "build harness reads canonical `specs/<id>`" in text
    assert "never guesses the newest `specs/*`" in text


def test_readme_documents_journal_single_writer_contract() -> None:
    text = _readme()

    assert "`echelon_result.journal_entries`" in text
    assert "`echelon_result.state_updates`" in text
    assert "must not use Write, Edit, Bash redirection, `cat >>`, or `tee`" in text
    assert "only writer to `reasoning-journal.jsonl` and `state.json`" in text


def test_readme_documents_fulfillment_deferred_semantics() -> None:
    text = _readme()

    assert "`verify: deferred`" in text
    assert "`fulfillment refresh: cached`" in text
    assert "not a failed build" in text
    assert "full fulfillment evidence is still required before convergence or land" in text


def test_readme_documents_harness_history() -> None:
    text = _readme()

    assert "HARNESS HISTORY" in text
    assert "tracked runs, checkpoint state, and token/cost totals" in text


def test_readme_documents_podman_harness_runtime() -> None:
    text = _readme()

    assert "### Container Runtime" in text
    assert "ECHELON_CONTAINER_CLI=podman echelon delivery init" in text
    assert "harness.container_cli" in text
    assert "podman machine start" in text


def test_readme_has_single_artifacts_intro() -> None:
    text = _readme()

    assert text.count("Start with `specs/<id>-*/ARTIFACTS.md`.") == 1
