from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_echelon_commit_paths_use_shared_commit_message_builder() -> None:
    files = [
        ROOT / "src/harness/ralph.py",
        ROOT / "src/echelon/workspace_git_migration.py",
        ROOT / "src/echelon/workspace_source_split_migration.py",
        ROOT / "src/harness/land.py",
    ]
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert "build_echelon_commit_message" in text, str(path)


def test_no_new_raw_harness_checkpoint_subjects_without_trailers() -> None:
    text = (ROOT / "src/harness/ralph.py").read_text(encoding="utf-8")
    assert "harness-checkpoint:" in text
    assert "EchelonCommitMetadata" in text
