from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from harness.dirty_adjudicator import (
    adjudicate_dirty_worktree,
    dirty_summary_text,
)


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _init_repo(repo: Path) -> None:
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "base")


@pytest.mark.unit
def test_clean_worktree_returns_clean(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)

    result = adjudicate_dirty_worktree(repo)

    assert result.status == "clean"
    assert result.summary == {
        "total": 0,
        "committed": 0,
        "ignored": 0,
        "left": 0,
        "blocked": 0,
    }


@pytest.mark.unit
def test_tracked_evidence_file_is_marked_for_commit(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    results = repo / "test-results"
    results.mkdir()
    (results / "verify.json").write_text('{"ok": true}\n', encoding="utf-8")
    _git(repo, "add", "test-results/verify.json")
    _git(repo, "commit", "-m", "add evidence")
    (results / "verify.json").write_text('{"ok": true, "fresh": true}\n', encoding="utf-8")

    result = adjudicate_dirty_worktree(repo)

    assert result.status == "applied"
    assert result.summary["committed"] == 1
    assert result.decisions[0].path == "test-results/verify.json"
    assert result.decisions[0].classification == "commit"


@pytest.mark.unit
def test_untracked_cache_file_updates_gitignore(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    cache = repo / ".pytest_cache" / "v" / "cache"
    cache.mkdir(parents=True)
    (cache / "nodeids").write_text("tests/test_demo.py::test_demo\n", encoding="utf-8")

    result = adjudicate_dirty_worktree(repo)

    assert result.status == "applied"
    assert result.summary["ignored"] == 1
    assert "/.pytest_cache/v/cache/nodeids" in (repo / ".gitignore").read_text(
        encoding="utf-8"
    )
    assert _git(repo, "status", "--short", "--", ".pytest_cache") == ""


class _FakeLlm:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def run_prompt_result(self, *_args: object, **_kwargs: object) -> object:
        return SimpleNamespace(exit_code=0, stdout=json.dumps(self.payload), stderr="")


@pytest.mark.unit
def test_tracked_python_cache_is_removed_even_when_llm_says_leave(
    tmp_path: Path,
) -> None:
    """Generated tracked bytecode must not block a verified delivery publish."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    cache = repo / "__pycache__"
    cache.mkdir()
    pyc = cache / "test_demo.cpython-311.pyc"
    pyc.write_bytes(b"old bytecode")
    _git(repo, "add", str(pyc.relative_to(repo)))
    _git(repo, "commit", "-m", "track generated cache")
    pyc.write_bytes(b"new bytecode")
    llm = _FakeLlm(
        {
            "decisions": [
                {
                    "path": "__pycache__/test_demo.cpython-311.pyc",
                    "classification": "leave",
                    "confidence": 0.99,
                    "reason": "tracked cache cannot be ignored",
                }
            ]
        }
    )

    result = adjudicate_dirty_worktree(repo, llm_provider=llm)

    assert result.status == "applied"
    assert result.blocked is False
    assert result.decisions[0].classification == "commit"
    assert result.decisions[0].action == "removed_tracked_cache"
    assert result.decisions[0].source == "deterministic"
    assert not pyc.exists()
    assert "/__pycache__/test_demo.cpython-311.pyc" in (
        repo / ".gitignore"
    ).read_text(encoding="utf-8")
    assert _git(repo, "status", "--short", "--", str(pyc.relative_to(repo))) == (
        "D __pycache__/test_demo.cpython-311.pyc"
    )


@pytest.mark.unit
def test_llm_can_classify_untracked_evidence_for_commit(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    output = repo / "verification-output.txt"
    output.write_text("full verification transcript\n", encoding="utf-8")
    llm = _FakeLlm(
        {
            "decisions": [
                {
                    "path": "verification-output.txt",
                    "classification": "commit",
                    "confidence": 0.96,
                    "reason": "durable verification evidence",
                }
            ]
        }
    )

    result = adjudicate_dirty_worktree(repo, llm_provider=llm)

    assert result.llm_used is True
    assert result.summary["committed"] == 1
    assert result.decisions[0].source == "llm"
    assert result.decisions[0].reason == "durable verification evidence"


@pytest.mark.unit
def test_safety_rail_blocks_llm_ignore_of_source_like_path(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    src = repo / "src"
    src.mkdir()
    (src / "feature.py").write_text("print('new')\n", encoding="utf-8")
    llm = _FakeLlm(
        {
            "decisions": [
                {
                    "path": "src/feature.py",
                    "classification": "ignore",
                    "confidence": 0.99,
                    "reason": "mistaken cache",
                }
            ]
        }
    )

    result = adjudicate_dirty_worktree(repo, llm_provider=llm)

    assert result.status == "blocked"
    assert result.summary["blocked"] == 1
    assert result.decisions[0].source == "safety_rail"
    assert "unsafe ignore" in result.decisions[0].reason


@pytest.mark.unit
def test_llm_leave_decision_blocks_commit_path(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "ambiguous.dump").write_text("unknown\n", encoding="utf-8")
    llm = _FakeLlm(
        {
            "decisions": [
                {
                    "path": "ambiguous.dump",
                    "classification": "leave",
                    "confidence": 0.9,
                    "reason": "ambiguous local artifact",
                }
            ]
        }
    )

    result = adjudicate_dirty_worktree(repo, llm_provider=llm)

    assert result.status == "blocked"
    assert result.blocked is True
    assert result.summary["left"] == 1


@pytest.mark.unit
def test_excluded_verification_artifacts_do_not_block_commit_path(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    results = repo / "test-results"
    results.mkdir()
    artifact = results / "error-context.md"
    artifact.write_text("old run\n", encoding="utf-8")
    _git(repo, "add", "test-results/error-context.md")
    _git(repo, "commit", "-m", "track historical test artifact")
    artifact.unlink()
    llm = _FakeLlm(
        {
            "decisions": [
                {
                    "path": "test-results/error-context.md",
                    "classification": "leave",
                    "confidence": 0.99,
                    "reason": "tracked artifact deletion is ambiguous",
                }
            ]
        }
    )

    result = adjudicate_dirty_worktree(
        repo,
        llm_provider=llm,
        exclude_paths=("test-results/**",),
    )

    assert result.status == "clean"
    assert result.blocked is False
    assert result.decisions == ()
    assert result.summary["total"] == 0


@pytest.mark.unit
def test_invalid_llm_output_falls_back_to_deterministic_policy(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    cache = repo / ".ruff_cache" / "cache"
    cache.mkdir(parents=True)
    (cache / "x").write_text("cache\n", encoding="utf-8")
    llm = _FakeLlm({"decisions": [{"path": ".ruff_cache/cache/x", "classification": "ignore"}]})

    result = adjudicate_dirty_worktree(repo, llm_provider=llm)

    assert result.llm_used is True
    assert result.summary["ignored"] == 1
    assert result.decisions[0].source == "deterministic"


@pytest.mark.unit
def test_dirty_summary_text_renders_counts() -> None:
    text = dirty_summary_text(
        {
            "summary": {
                "total": 4,
                "committed": 2,
                "ignored": 1,
                "left": 0,
                "blocked": 1,
            }
        }
    )

    assert text == "dirty: 2 committed, 1 ignored, 0 left, 1 blocked"
