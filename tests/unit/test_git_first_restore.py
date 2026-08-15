from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest

from harness.git_first_restore import (
    GitFirstRestoreError,
    GitFirstRestorePlan,
    build_git_first_restore_commit,
    verify_git_first_restore_commit,
)
from harness.proportional_quality import CandidateCheckpointEntry


@dataclass(frozen=True)
class TreeEntry:
    mode: str
    object_type: str
    oid: str


@dataclass
class RestoreRepo:
    root: Path
    run_root: Path
    base_commit: str
    current_bytes: bytes

    def git(
        self,
        *args: str,
        input_bytes: bytes | None = None,
        env: dict[str, str] | None = None,
    ) -> bytes:
        result = subprocess.run(
            ["git", *args],
            cwd=self.root,
            input=input_bytes,
            capture_output=True,
            check=False,
            env={**os.environ, **(env or {})},
        )
        assert result.returncode == 0, result.stderr.decode(errors="replace")
        return result.stdout

    def head(self) -> str:
        return self.git("rev-parse", "HEAD^{commit}").decode().strip()

    def index_tree(self) -> str:
        return self.git("write-tree").decode().strip()

    def spec_bytes(self) -> bytes:
        return (self.root / "specs/001-example/spec.md").read_bytes()

    def blob_oid(self, content: bytes) -> str:
        return self.git("hash-object", "-w", "--stdin", input_bytes=content).decode().strip()

    def selected_entries(
        self,
        *,
        spec_mode: str = "100644",
    ) -> tuple[CandidateCheckpointEntry, ...]:
        entries: list[CandidateCheckpointEntry] = []
        for name, mode, content in (
            ("spec.md", spec_mode, b"#!/bin/sh\n# selected spec\n"),
            ("quality-gates.md", "100644", b"# selected gates\n"),
            ("issues.md", "100644", b"# selected issues\n"),
        ):
            entries.append(
                CandidateCheckpointEntry(
                    path=name,
                    mode=mode,
                    blob_oid=self.blob_oid(content),
                    sha256=hashlib.sha256(content).hexdigest(),
                    content=content,
                )
            )
        return tuple(entries)

    def tree_entry(self, commit: str, path: str) -> TreeEntry | None:
        output = self.git("ls-tree", "-z", commit, "--", path)
        rows = [row for row in output.split(b"\0") if row]
        if not rows:
            return None
        assert len(rows) == 1
        header, actual_path = rows[0].split(b"\t", 1)
        assert actual_path.decode() == path
        mode, object_type, oid = header.decode().split()
        return TreeEntry(mode, object_type, oid)


@pytest.fixture
def repo(tmp_path: Path) -> RestoreRepo:
    root = tmp_path / "repo"
    run_root = tmp_path / "run-artifacts"
    root.mkdir()
    run_root.mkdir()
    subprocess.run(
        ["git", "init", "-q", "-b", "main"],
        cwd=root,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Restore Test"],
        cwd=root,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "restore@example.test"],
        cwd=root,
        check=True,
    )
    spec_dir = root / "specs/001-example"
    spec_dir.mkdir(parents=True)
    current = b"# current spec\n"
    (root / "README.md").write_bytes(b"unowned base\n")
    (spec_dir / "spec.md").write_bytes(current)
    (spec_dir / "quality-gates.md").write_bytes(b"# current gates\n")
    (spec_dir / "issues.md").write_bytes(b"# current issues\n")
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "base"],
        cwd=root,
        check=True,
        env={
            **os.environ,
            "GIT_AUTHOR_DATE": "2026-08-14T12:00:00+02:00",
            "GIT_COMMITTER_DATE": "2026-08-14T12:00:00+02:00",
        },
    )
    base = subprocess.run(
        ["git", "rev-parse", "HEAD^{commit}"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return RestoreRepo(root, run_root, base, current)


def _build(repo: RestoreRepo, **overrides: object) -> GitFirstRestorePlan:
    values: dict[str, object] = {
        "project_root": repo.root,
        "journal_root": repo.run_root,
        "completion_id": "quality-restore-1",
        "base_commit": repo.base_commit,
        "selected_candidate_id": "quality-candidate-0",
        "selected_manifest_sha256": "a" * 64,
        "selected_entries": repo.selected_entries(spec_mode="100755"),
        "run_id": "spec-run",
        "spec_id": "001-example",
        "next_phase": "checkpoint-assess",
    }
    values.update(overrides)
    return build_git_first_restore_commit(**values)  # type: ignore[arg-type]


def test_restore_commit_preserves_selected_modes_blobs_and_unowned_tree(
    repo: RestoreRepo,
) -> None:
    initial_index = repo.index_tree()
    selected = repo.selected_entries(spec_mode="100755")

    plan = _build(repo, selected_entries=selected)

    spec_path = "specs/001-example/spec.md"
    target_spec = repo.tree_entry(plan.target_commit, spec_path)
    assert target_spec == TreeEntry("100755", "blob", selected[0].blob_oid)
    assert repo.tree_entry(plan.target_commit, "README.md") == repo.tree_entry(
        repo.base_commit,
        "README.md",
    )
    assert plan.base_tree == initial_index
    planned_spec = next(entry for entry in plan.entries if entry.path == spec_path)
    assert planned_spec.target_mode == "100755"
    assert planned_spec.target_blob_oid == selected[0].blob_oid
    assert repo.head() == repo.base_commit
    assert repo.index_tree() == initial_index
    assert repo.spec_bytes() == repo.current_bytes
    assert list(repo.run_root.iterdir()) == []
    verify_git_first_restore_commit(repo.root, plan)
    json.dumps(asdict(plan), sort_keys=True)


def test_restore_commit_is_deterministic_across_git_config_changes(
    repo: RestoreRepo,
) -> None:
    selected = repo.selected_entries()
    first = _build(repo, selected_entries=selected)
    repo.git("config", "user.name", "Different User")
    repo.git("config", "user.email", "different@example.test")

    second = _build(repo, selected_entries=selected)

    assert second == first


@pytest.mark.parametrize("mode", ["120000", "040000"])
def test_restore_commit_rejects_symlink_and_tree_entries(
    repo: RestoreRepo,
    mode: str,
) -> None:
    entries = list(repo.selected_entries())
    entries[0] = replace(entries[0], mode=mode)

    with pytest.raises(GitFirstRestoreError, match="regular blob"):
        _build(repo, selected_entries=tuple(entries))


@pytest.mark.parametrize("malformation", ["missing", "extra"])
def test_restore_commit_rejects_missing_or_extra_owned_artifacts(
    repo: RestoreRepo,
    malformation: str,
) -> None:
    entries = list(repo.selected_entries())
    if malformation == "missing":
        entries = [entry for entry in entries if entry.path != "issues.md"]
    else:
        content = b"not candidate owned\n"
        entries.append(
            CandidateCheckpointEntry(
                path="README.md",
                mode="100644",
                blob_oid=repo.blob_oid(content),
                sha256=hashlib.sha256(content).hexdigest(),
                content=content,
            )
        )

    with pytest.raises(GitFirstRestoreError, match="owned artifact paths"):
        _build(repo, selected_entries=tuple(entries))


def test_restore_commit_rejects_wrong_selected_digest(repo: RestoreRepo) -> None:
    entries = list(repo.selected_entries())
    entries[0] = replace(entries[0], sha256="f" * 64)

    with pytest.raises(GitFirstRestoreError, match="digest"):
        _build(repo, selected_entries=tuple(entries))


@pytest.mark.parametrize("state", ["dirty", "staged"])
def test_restore_commit_rejects_dirty_or_staged_base(
    repo: RestoreRepo,
    state: str,
) -> None:
    path = repo.root / "specs/001-example/spec.md"
    path.write_bytes(b"drift\n")
    if state == "staged":
        repo.git("add", "specs/001-example/spec.md")

    with pytest.raises(GitFirstRestoreError, match="base.*clean"):
        _build(repo)


def test_restore_commit_rejects_changed_base_head(repo: RestoreRepo) -> None:
    repo.git("commit", "--allow-empty", "-m", "moved head")

    with pytest.raises(GitFirstRestoreError, match="base commit.*HEAD"):
        _build(repo)


def test_verifier_rejects_an_unowned_tree_change(repo: RestoreRepo) -> None:
    plan = _build(repo)
    changed_readme = repo.blob_oid(b"changed unowned\n")
    index_path = repo.run_root / "malicious.index"
    env = {"GIT_INDEX_FILE": str(index_path)}
    repo.git("read-tree", plan.target_commit, env=env)
    repo.git(
        "update-index",
        "--cacheinfo",
        "100644",
        changed_readme,
        "README.md",
        env=env,
    )
    target_tree = repo.git("write-tree", env=env).decode().strip()
    message = repo.git("show", "-s", "--format=%B", plan.target_commit)
    target_commit = repo.git(
        "commit-tree",
        target_tree,
        "-p",
        plan.base_commit,
        input_bytes=message,
        env={
            "GIT_AUTHOR_NAME": "Echelon",
            "GIT_AUTHOR_EMAIL": "echelon@local",
            "GIT_COMMITTER_NAME": "Echelon",
            "GIT_COMMITTER_EMAIL": "echelon@local",
            "GIT_AUTHOR_DATE": "2026-08-14T12:00:00+02:00",
            "GIT_COMMITTER_DATE": "2026-08-14T12:00:00+02:00",
        },
    ).decode().strip()
    malicious = replace(
        plan,
        target_commit=target_commit,
        target_tree=target_tree,
    )

    with pytest.raises(GitFirstRestoreError, match="unowned tree"):
        verify_git_first_restore_commit(repo.root, malicious)


def test_verifier_rejects_wrong_parent_or_message(repo: RestoreRepo) -> None:
    plan = _build(repo)
    wrong = repo.git(
        "commit-tree",
        plan.target_tree,
        "-p",
        plan.base_commit,
        input_bytes=b"not a restore checkpoint\n",
        env={
            "GIT_AUTHOR_NAME": "Echelon",
            "GIT_AUTHOR_EMAIL": "echelon@local",
            "GIT_COMMITTER_NAME": "Echelon",
            "GIT_COMMITTER_EMAIL": "echelon@local",
            "GIT_AUTHOR_DATE": "2026-08-14T12:00:00+02:00",
            "GIT_COMMITTER_DATE": "2026-08-14T12:00:00+02:00",
        },
    ).decode().strip()

    with pytest.raises(GitFirstRestoreError, match="message"):
        verify_git_first_restore_commit(
            repo.root,
            replace(plan, target_commit=wrong),
        )


def test_verifier_binds_selected_candidate_and_manifest(repo: RestoreRepo) -> None:
    plan = _build(repo)

    with pytest.raises(GitFirstRestoreError, match="message"):
        verify_git_first_restore_commit(
            repo.root,
            replace(plan, selected_candidate_id="quality-candidate-1"),
        )
    with pytest.raises(GitFirstRestoreError, match="message"):
        verify_git_first_restore_commit(
            repo.root,
            replace(plan, selected_manifest_sha256="b" * 64),
        )
