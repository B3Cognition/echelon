import subprocess
import sys
from pathlib import Path

from scripts.python import detect_patterns, emit_score_deltas, failing_run_audit, replay
from scripts.python.seed_from_archive import default_archive_root


REPO_ROOT = Path(__file__).resolve().parents[2]
ANALYZERS = (
    "emit_score_deltas.py",
    "detect_patterns.py",
    "failing_run_audit.py",
)


def test_analyzers_default_only_to_repository_runs(tmp_path, monkeypatch):
    (tmp_path / "squad").mkdir()
    (tmp_path / ".specify" / "squad").mkdir(parents=True)
    for module in (emit_score_deltas, detect_patterns, failing_run_audit):
        monkeypatch.setattr(module, "EXT_DIR", tmp_path)
        assert module._default_runs_root() == tmp_path / "runs"


def test_archive_utilities_default_only_to_runs_archive(tmp_path):
    legacy = tmp_path / ".specify" / "squad" / "archive"
    legacy.mkdir(parents=True)

    assert default_archive_root(tmp_path) == tmp_path / "runs" / "archive"
    assert replay.default_archive_root(tmp_path) == tmp_path / "runs" / "archive"


def test_replay_loads_workspace_echelon_config(tmp_path):
    archive_dir = tmp_path / "runs" / "archive" / "spec-001"
    archive_dir.mkdir(parents=True)
    config = tmp_path / ".echelon" / "config.yml"
    config.parent.mkdir()
    config.write_text("convergence:\n  max_iterations: 9\n", encoding="utf-8")

    assert replay._load_config(archive_dir)["convergence"]["max_iterations"] == 9


def test_analyzer_cli_uses_runs_root_vocabulary():
    for script_name in ANALYZERS:
        completed = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "python" / script_name), "--help"],
            text=True,
            capture_output=True,
            check=False,
        )
        assert completed.returncode == 0
        assert "--runs-root" in completed.stdout
        assert "squad" not in completed.stdout.lower()
