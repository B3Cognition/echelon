from pathlib import Path

import pytest

from echelon.git_helpers import GitHelperError, run_git
from echelon.owned_output_commit import OwnedOutputCommit


def repo(tmp_path: Path) -> Path:
    run_git(tmp_path, "init", "-b", "main")
    run_git(tmp_path, "config", "user.name", "Test")
    run_git(tmp_path, "config", "user.email", "test@example.test")
    (tmp_path / "README.md").write_text("base")
    run_git(tmp_path, "add", ".")
    run_git(tmp_path, "commit", "-m", "base")
    return tmp_path


def test_output_commit_preserves_unrelated_staged_work(tmp_path):
    root = repo(tmp_path)
    (root / "README.md").write_text("user edit")
    run_git(root, "add", "README.md")
    output = root / "report.json"
    operation = OwnedOutputCommit(root, [output, root / "absent.json"], "report")
    output.write_text("{}")
    operation.commit()
    assert run_git(root, "show", "HEAD:README.md").stdout == "base"
    assert run_git(root, "diff", "--cached", "--name-only").stdout.strip() == "README.md"
    assert run_git(root, "show", "HEAD:report.json").stdout == "{}"
    head = run_git(root, "rev-parse", "HEAD").stdout
    OwnedOutputCommit(root, [output], "noop").commit()
    assert run_git(root, "rev-parse", "HEAD").stdout == head


def test_output_commit_refuses_preexisting_output_edits(tmp_path):
    root = repo(tmp_path)
    output = root / "report.json"
    output.write_text("user draft")
    with pytest.raises(GitHelperError, match="existing output edits"):
        OwnedOutputCommit(root, [output], "report")
    assert output.read_text() == "user draft"


def test_output_commit_refuses_branch_change(tmp_path):
    root = repo(tmp_path)
    output = root / "report.json"
    operation = OwnedOutputCommit(root, [output], "report")
    output.write_text("{}")
    run_git(root, "switch", "-c", "other")
    with pytest.raises(GitHelperError, match="HEAD changed"):
        operation.commit()
    assert output.exists()


def test_runtime_lock_stays_ignored_after_branch_switch(tmp_path):
    from harness.banzai_protocol import banzai_default_protocol_bundle_lock

    root = repo(tmp_path)
    with banzai_default_protocol_bundle_lock(root, exclusive=True):
        pass
    run_git(root, "switch", "-c", "other")
    assert run_git(root, "status", "--porcelain").stdout == ""


def test_workspace_refresh_commits_member_graph_outputs(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from echelon import workspace_graph_refresh as refresh

    root = repo(tmp_path)
    spec_dir = root / "specs/001-test"
    spec_dir.mkdir(parents=True)
    monkeypatch.setattr(refresh, "audit_spec_graph", lambda *args: SimpleNamespace(status="fail"))
    monkeypatch.setattr(refresh, "classify_spec_graph_audit", lambda report: "stale")
    monkeypatch.setattr(refresh, "build_spec_graph", lambda *args: {})
    monkeypatch.setattr(refresh, "write_spec_graph", lambda graph, path: (path / "spec-artifact-graph.json").write_text("{}"))
    monkeypatch.setattr(refresh, "write_spec_graph_audit", lambda report, path: (path / "spec-artifact-graph-audit.json").write_text("{}"))
    outcome = refresh._refresh_spec_graph(root, spec_dir)
    assert outcome.action == "refreshed"
    assert outcome.status == "fail"
    assert run_git(root, "status", "--porcelain").stdout == ""
    assert len(run_git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").stdout.splitlines()) == 2
