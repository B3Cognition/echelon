"""Static contracts for the run-local artifact layout documented to agents."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_run_command_documents_current_runs_layout() -> None:
    text = (ROOT / "prosaic/commands/echelon.run.md").read_text(encoding="utf-8")

    assert "runs/<run-id>/state.json" in text
    assert "runs/.current" in text
    assert "squad/<run-id>" not in text


def test_init_does_not_archive_or_wipe_run_local_staging() -> None:
    text = (ROOT / "runtime/workflow/phases/init.md").read_text(encoding="utf-8")

    assert "${SQUAD_DIR}/archive" not in text
    assert 'rm -rf "${STAGING_DIR}"' not in text


def test_finalize_preserves_run_local_staging_and_state() -> None:
    text = (ROOT / "runtime/workflow/phases/phase4-document.md").read_text(
        encoding="utf-8"
    )

    assert "${SQUAD_DIR}/archive" not in text
    assert 'rm -rf "${STAGING_DIR}"' not in text
    assert "Run directory preserved" in text
