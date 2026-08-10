from pathlib import Path

from scripts.uca004_runner import _AUTHORIZED_OVERLAYS


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_unused_ca_overlays_are_quarantined_from_runtime_paths():
    assert not (REPO_ROOT / "scripts" / "ca" / "goal_stack.py").exists()
    assert not (REPO_ROOT / "scripts" / "ca" / "episodic_memory.py").exists()
    assert not (REPO_ROOT / "scripts" / "ca" / "gwt_workspace.py").exists()
    assert (REPO_ROOT / "todo" / "ca-overlays" / "goal_stack.py").is_file()
    assert (REPO_ROOT / "todo" / "ca-overlays" / "episodic_memory.py").is_file()
    assert (REPO_ROOT / "todo" / "ca-overlays" / "gwt_workspace.py").is_file()


def test_quarantined_overlays_are_not_authorized_for_deployment():
    assert "scripts/ca/goal_stack.py" not in _AUTHORIZED_OVERLAYS
    assert "scripts/ca/episodic_memory.py" not in _AUTHORIZED_OVERLAYS
    assert "scripts/ca/gwt_workspace.py" not in _AUTHORIZED_OVERLAYS


def test_quarantine_note_records_review_boundary():
    note = (REPO_ROOT / "todo" / "ca-overlays" / "README.md").read_text(
        encoding="utf-8"
    )
    assert "not part of the Echelon runtime" in note
    assert "Review before reactivation" in note
