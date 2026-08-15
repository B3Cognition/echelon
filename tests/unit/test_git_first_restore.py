from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess

import pytest

import harness.git_first_restore as git_first_restore_module
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

    def checkpoint_rows(self) -> list[dict[str, object]]:
        ledger = self.root / "specs/001-example/.echelon/checkpoints.json"
        if not ledger.exists():
            return []
        payload = json.loads(ledger.read_text(encoding="utf-8"))
        return [
            row
            for row in payload["checkpoints"]
            if row["phase"] == "phase1-quality-candidate-restored"
        ]

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


def _apply(
    repo: RestoreRepo,
    plan: GitFirstRestorePlan,
    *,
    expected_receipt: object | None = None,
):
    return git_first_restore_module.apply_or_recover_git_first_restore(
        project_root=repo.root,
        spec_dir=repo.root / "specs/001-example",
        journal_root=repo.run_root,
        plan=plan,
        run_id="spec-run",
        spec_id="001-example",
        next_phase="checkpoint-assess",
        expected_receipt=expected_receipt,
    )


def _restore_plan(repo: RestoreRepo) -> GitFirstRestorePlan:
    return _build(repo, completion_id="1" * 32)


def _assert_target_state(repo: RestoreRepo, plan: GitFirstRestorePlan) -> None:
    assert repo.head() == plan.target_commit
    assert repo.index_tree() == plan.target_tree
    for entry in plan.entries:
        path = repo.root / entry.path
        metadata = path.lstat()
        assert stat.S_ISREG(metadata.st_mode)
        assert not path.is_symlink()
        assert stat.S_IMODE(metadata.st_mode) == int(entry.target_mode[-3:], 8)
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry.target_sha256


def _replace_commit_bytes(repo: RestoreRepo, commit: str, content: bytes) -> str:
    return repo.git(
        "hash-object",
        "-t",
        "commit",
        "-w",
        "--stdin",
        input_bytes=content,
    ).decode().strip()


def _mutated_commit(repo: RestoreRepo, plan: GitFirstRestorePlan, kind: str) -> str:
    raw = repo.git("cat-file", "commit", plan.target_commit)
    if kind == "author":
        changed = raw.replace(
            b"author Echelon <echelon@local> ",
            b"author Other <other@example.test> ",
            1,
        )
    elif kind == "committer-date":
        changed = re.sub(
            rb"(?m)^(committer [^\n]+ )([0-9]+)( [+-][0-9]{4})$",
            lambda match: (
                match.group(1)
                + str(int(match.group(2)) + 1).encode("ascii")
                + match.group(3)
            ),
            raw,
            count=1,
        )
    elif kind == "run":
        changed = raw.replace(b"Echelon-Run: spec-run", b"Echelon-Run: other-run", 1)
    elif kind == "next-phase":
        changed = raw.replace(
            b"Echelon-Next-Phase: checkpoint-assess",
            b"Echelon-Next-Phase: another-phase",
            1,
        )
    elif kind == "extra-header":
        changed = raw.replace(b"\n\n", b"\nencoding ISO-8859-1\n\n", 1)
    else:  # pragma: no cover - test helper contract
        raise AssertionError(kind)
    assert changed != raw
    return _replace_commit_bytes(repo, plan.target_commit, changed)


def _target_with_added_empty_tree(
    repo: RestoreRepo,
    plan: GitFirstRestorePlan,
) -> tuple[str, str]:
    empty_tree = repo.git("mktree", input_bytes=b"").decode().strip()
    root_entries = repo.git("ls-tree", plan.target_tree)
    changed_tree = repo.git(
        "mktree",
        input_bytes=(
            root_entries
            + f"040000 tree {empty_tree}\tempty-unowned\n".encode("ascii")
        ),
    ).decode().strip()
    raw = repo.git("cat-file", "commit", plan.target_commit)
    changed_commit = raw.replace(
        f"tree {plan.target_tree}\n".encode("ascii"),
        f"tree {changed_tree}\n".encode("ascii"),
        1,
    )
    assert changed_commit != raw
    return changed_tree, _replace_commit_bytes(repo, plan.target_commit, changed_commit)


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


def test_restore_commit_is_deterministic_across_commit_encoding_config(
    repo: RestoreRepo,
) -> None:
    selected = repo.selected_entries()
    first = _build(repo, selected_entries=selected)
    repo.git("config", "i18n.commitEncoding", "ISO-8859-1")

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
    raw_commit = repo.git("cat-file", "commit", plan.target_commit)
    changed_commit = raw_commit.replace(
        f"tree {plan.target_tree}\n".encode("ascii"),
        f"tree {target_tree}\n".encode("ascii"),
        1,
    )
    assert changed_commit != raw_commit
    target_commit = _replace_commit_bytes(repo, plan.target_commit, changed_commit)
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


@pytest.mark.parametrize(
    "mutation",
    ["author", "committer-date", "run", "next-phase", "extra-header"],
)
def test_verifier_requires_exact_deterministic_commit_authority(
    repo: RestoreRepo,
    mutation: str,
) -> None:
    plan = _build(repo)
    replacement_commit = _mutated_commit(repo, plan, mutation)

    with pytest.raises(GitFirstRestoreError, match="exact authority"):
        verify_git_first_restore_commit(
            repo.root,
            replace(plan, target_commit=replacement_commit),
        )


def test_verifier_rejects_added_empty_unowned_tree(repo: RestoreRepo) -> None:
    plan = _build(repo)
    changed_tree, changed_commit = _target_with_added_empty_tree(repo, plan)

    with pytest.raises(GitFirstRestoreError, match="unowned tree"):
        verify_git_first_restore_commit(
            repo.root,
            replace(
                plan,
                target_tree=changed_tree,
                target_commit=changed_commit,
            ),
        )


def test_restore_builder_rechecks_the_exact_active_ref(
    repo: RestoreRepo,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_commit_tree = git_first_restore_module._commit_tree_deterministically

    def switch_ref_after_commit(*args, **kwargs) -> str:
        commit = real_commit_tree(*args, **kwargs)
        repo.git("branch", "other", repo.base_commit)
        repo.git("symbolic-ref", "HEAD", "refs/heads/other")
        return commit

    monkeypatch.setattr(
        git_first_restore_module,
        "_commit_tree_deterministically",
        switch_ref_after_commit,
    )

    with pytest.raises(GitFirstRestoreError, match="active ref changed"):
        _build(repo)


def test_restore_builder_preserves_active_index_bytes(repo: RestoreRepo) -> None:
    index_path = Path(repo.git("rev-parse", "--git-path", "index").decode().strip())
    if not index_path.is_absolute():
        index_path = repo.root / index_path
    index_before = index_path.read_bytes()
    spec_path = repo.root / "specs/001-example/spec.md"
    metadata = spec_path.stat()
    os.utime(
        spec_path,
        ns=(metadata.st_atime_ns, metadata.st_mtime_ns + 2_000_000_000),
    )

    _build(repo)

    assert index_path.read_bytes() == index_before


@pytest.mark.parametrize(
    "crash_point",
    (
        "after_journal",
        "after_first_exchange",
        "after_all_exchanges",
        "after_ref_update",
        "after_index_update",
        "before_receipt",
    ),
)
def test_public_retry_converges_git_first_restore_once(
    repo: RestoreRepo,
    monkeypatch: pytest.MonkeyPatch,
    crash_point: str,
) -> None:
    plan = _restore_plan(repo)
    crashed = False

    def crash_once(point: str) -> None:
        nonlocal crashed
        if point == crash_point and not crashed:
            crashed = True
            raise KeyboardInterrupt(f"crash at {point}")

    monkeypatch.setattr(git_first_restore_module, "_restore_fault", crash_once)
    with pytest.raises(KeyboardInterrupt, match=crash_point):
        _apply(repo, plan)

    monkeypatch.setattr(git_first_restore_module, "_restore_fault", lambda _point: None)
    receipt = _apply(repo, plan)
    replayed = _apply(repo, plan, expected_receipt=asdict(receipt))

    assert replayed == receipt
    assert receipt.restore_protocol == "git_first_v1"
    assert receipt.target_commit == plan.target_commit
    assert len(repo.checkpoint_rows()) == 1
    _assert_target_state(repo, plan)
    journal_dir = repo.run_root / "git-first-restores"
    assert not journal_dir.exists() or list(journal_dir.iterdir()) == []


def test_git_first_restore_replays_when_one_owned_entry_is_unchanged(
    repo: RestoreRepo,
) -> None:
    selected = list(repo.selected_entries(spec_mode="100755"))
    unchanged = b"# current gates\n"
    selected[1] = CandidateCheckpointEntry(
        path="quality-gates.md",
        mode="100644",
        blob_oid=repo.blob_oid(unchanged),
        sha256=hashlib.sha256(unchanged).hexdigest(),
        content=unchanged,
    )
    plan = _build(
        repo,
        completion_id="2" * 32,
        selected_entries=tuple(selected),
    )

    receipt = _apply(repo, plan)
    replayed = _apply(repo, plan, expected_receipt=asdict(receipt))

    assert replayed == receipt
    assert len(repo.checkpoint_rows()) == 1
    _assert_target_state(repo, plan)


def test_git_first_restore_preserves_unrelated_repository_paths(
    repo: RestoreRepo,
) -> None:
    plan = _restore_plan(repo)
    readme_before = (repo.root / "README.md").read_bytes()
    readme_entry = repo.tree_entry(repo.base_commit, "README.md")

    _apply(repo, plan)

    assert (repo.root / "README.md").read_bytes() == readme_before
    assert repo.tree_entry(plan.target_commit, "README.md") == readme_entry
    _assert_target_state(repo, plan)


def test_git_first_restore_symlink_drift_is_rejected_without_following(
    repo: RestoreRepo,
) -> None:
    plan = _restore_plan(repo)
    target = repo.root / "specs/001-example/spec.md"
    victim = repo.root / "victim"
    victim.write_bytes(b"do not mutate\n")
    target.unlink()
    target.symlink_to("../../victim")

    with pytest.raises(GitFirstRestoreError, match="regular file"):
        _apply(repo, plan)

    assert target.is_symlink()
    assert victim.read_bytes() == b"do not mutate\n"
    assert repo.head() == plan.base_commit
    assert repo.index_tree() == plan.base_tree
    assert repo.checkpoint_rows() == []


def test_git_first_restore_mode_only_owned_drift_is_rejected_before_mutation(
    repo: RestoreRepo,
) -> None:
    plan = _restore_plan(repo)
    spec = repo.root / "specs/001-example/spec.md"
    gates = repo.root / "specs/001-example/quality-gates.md"
    gates_before = gates.read_bytes()
    spec.chmod(0o755)

    with pytest.raises(GitFirstRestoreError, match="worktree authority changed"):
        _apply(repo, plan)

    assert spec.read_bytes() == repo.current_bytes
    assert stat.S_IMODE(spec.stat().st_mode) == 0o755
    assert gates.read_bytes() == gates_before
    assert repo.head() == plan.base_commit
    assert repo.index_tree() == plan.base_tree
    assert repo.checkpoint_rows() == []


def test_git_first_restore_rejects_unrelated_owned_drift_before_mutation(
    repo: RestoreRepo,
) -> None:
    plan = _restore_plan(repo)
    spec = repo.root / "specs/001-example/spec.md"
    issues = repo.root / "specs/001-example/issues.md"
    issues.write_bytes(b"unrelated owned drift\n")

    with pytest.raises(GitFirstRestoreError, match="worktree authority changed"):
        _apply(repo, plan)

    assert spec.read_bytes() == repo.current_bytes
    assert issues.read_bytes() == b"unrelated owned drift\n"
    assert repo.head() == plan.base_commit
    assert repo.index_tree() == plan.base_tree
    assert repo.checkpoint_rows() == []


def test_git_first_restore_rejects_same_digest_inode_swap(
    repo: RestoreRepo,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _restore_plan(repo)
    spec = repo.root / "specs/001-example/spec.md"
    real_snapshot = git_first_restore_module._restore_entry_snapshot
    swapped = False

    def swap_after_snapshot(directory_fd: int, name: str, **kwargs: object):
        nonlocal swapped
        snapshot = real_snapshot(directory_fd, name, **kwargs)
        if name == "spec.md" and snapshot is not None and not swapped:
            swapped = True
            replacement = spec.with_name("same-digest-replacement")
            replacement.write_bytes(spec.read_bytes())
            replacement.chmod(stat.S_IMODE(spec.stat().st_mode))
            os.replace(replacement, spec)
        return snapshot

    monkeypatch.setattr(
        git_first_restore_module,
        "_restore_entry_snapshot",
        swap_after_snapshot,
    )

    with pytest.raises(GitFirstRestoreError, match="identity changed"):
        _apply(repo, plan)

    assert swapped is True
    assert repo.head() == plan.base_commit
    assert repo.index_tree() == plan.base_tree
    assert repo.checkpoint_rows() == []


def test_git_first_restore_rejects_unexplained_deterministic_temp(
    repo: RestoreRepo,
) -> None:
    plan = _restore_plan(repo)
    journal_dir = repo.run_root / "git-first-restores"
    journal_dir.mkdir()
    temp_name = git_first_restore_module._restore_temporary_name(
        plan.completion_id,
        plan.entries[0].path,
    )
    (journal_dir / temp_name).write_bytes(b"unexplained residue")

    with pytest.raises(GitFirstRestoreError, match="journal is missing"):
        _apply(repo, plan)

    assert repo.head() == plan.base_commit
    assert repo.index_tree() == plan.base_tree
    assert repo.checkpoint_rows() == []


def test_git_first_restore_preflights_all_existing_temps_before_exchange(
    repo: RestoreRepo,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _restore_plan(repo)

    def crash_after_journal(point: str) -> None:
        if point == "after_journal":
            raise KeyboardInterrupt("crash after journal")

    monkeypatch.setattr(
        git_first_restore_module,
        "_restore_fault",
        crash_after_journal,
    )
    with pytest.raises(KeyboardInterrupt, match="after journal"):
        _apply(repo, plan)

    journal_dir = repo.run_root / "git-first-restores"
    later = plan.entries[1]
    temporary = journal_dir / git_first_restore_module._restore_temporary_name(
        plan.completion_id,
        later.path,
    )
    temporary.write_bytes(b"corrupt deterministic temporary\n")
    temporary.chmod(int(later.target_mode[-3:], 8))
    before = {
        entry.path: (
            (repo.root / entry.path).read_bytes(),
            stat.S_IMODE((repo.root / entry.path).stat().st_mode),
        )
        for entry in plan.entries
    }
    monkeypatch.setattr(
        git_first_restore_module,
        "_restore_fault",
        lambda _point: None,
    )

    with pytest.raises(GitFirstRestoreError, match="temporary changed"):
        _apply(repo, plan)

    assert {
        entry.path: (
            (repo.root / entry.path).read_bytes(),
            stat.S_IMODE((repo.root / entry.path).stat().st_mode),
        )
        for entry in plan.entries
    } == before
    assert repo.head() == plan.base_commit
    assert repo.index_tree() == plan.base_tree
    assert repo.checkpoint_rows() == []


def test_git_first_restore_rejects_ref_conflict_without_mutation(
    repo: RestoreRepo,
) -> None:
    plan = _restore_plan(repo)
    repo.git("commit", "--allow-empty", "-m", "conflicting ref advance")
    conflicting = repo.head()

    with pytest.raises(GitFirstRestoreError, match="ref authority changed"):
        _apply(repo, plan)

    assert repo.head() == conflicting
    assert repo.spec_bytes() == repo.current_bytes
    assert repo.checkpoint_rows() == []


def test_git_first_restore_rejects_index_conflict_without_mutation(
    repo: RestoreRepo,
) -> None:
    plan = _restore_plan(repo)
    readme = repo.root / "README.md"
    readme.write_bytes(b"staged unrelated drift\n")
    repo.git("add", "README.md")

    with pytest.raises(GitFirstRestoreError, match="index authority changed"):
        _apply(repo, plan)

    assert repo.head() == plan.base_commit
    assert repo.spec_bytes() == repo.current_bytes
    assert repo.checkpoint_rows() == []
