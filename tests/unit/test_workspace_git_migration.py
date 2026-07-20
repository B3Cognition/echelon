from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from echelon.workspace_git_migration import (
    MigrationError,
    build_migration_plan,
    doctor_workspace,
    migrate_workspace,
)


def _write_workspace(path: Path) -> None:
    (path / ".specify").mkdir()
    spec_dir = path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Demo\n", encoding="utf-8")


@pytest.mark.unit
def test_migration_plan_ignores_child_source_roots(tmp_path: Path) -> None:
    _write_workspace(tmp_path)
    source = tmp_path / "og-platform"
    (source / ".git").mkdir(parents=True)
    (source / "package.json").write_text("{}\n", encoding="utf-8")

    plan = build_migration_plan(tmp_path)

    assert plan.workspace_root == tmp_path.resolve()
    assert plan.canonical_config == tmp_path / ".echelon" / "config.yml"
    assert plan.source_ignore_entries == ("/og-platform/",)
    assert plan.runtime_ignore_entries == (
        "/.specify/",
        "/runs/",
        "/.claude/",
        "/.claude-work/",
        "!/.echelon/",
        "!/.echelon/config.yml",
        "/.echelon/local.yml",
        "/.echelon/runtime/",
        "/.echelon/cache/",
        "/.echelon/recovery-backups/",
        "/sources/*",
        "!/sources/README.md",
    )
    assert plan.stage_paths == (".gitignore", "specs")
    assert plan.already_git_backed is False


@pytest.mark.unit
def test_migration_write_initializes_git_and_stages_only_workspace_files(
    tmp_path: Path,
) -> None:
    _write_workspace(tmp_path)
    source = tmp_path / "og-platform"
    (source / ".git").mkdir(parents=True)
    (source / "package.json").write_text("{}\n", encoding="utf-8")

    result = migrate_workspace(tmp_path, write=True, commit=False)

    assert result.git_initialized is True
    assert result.committed is False
    assert (tmp_path / ".git").exists()
    gitignore = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert "/og-platform/" in gitignore
    assert "/.specify/" in gitignore
    assert "/runs/" in gitignore
    assert "/.claude/" in gitignore
    assert "/.claude-work/" in gitignore
    assert "/.echelon/runtime/" in gitignore
    assert "/.echelon/cache/" in gitignore
    assert "/.echelon/recovery-backups/" in gitignore
    assert "/sources/*" in gitignore
    assert "!/sources/README.md" in gitignore
    assert result.source_roots_scaffolded is True
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert ".gitignore" in staged
    assert "re/.gitignore" in staged
    assert "sources/README.md" in staged
    assert ".specify" not in staged
    assert "specs/001-demo/spec.md" in staged
    assert not any(path.startswith("og-platform/") for path in staged)


@pytest.mark.unit
def test_existing_git_workspace_migration_only_stages_gitignore(tmp_path: Path) -> None:
    _write_workspace(tmp_path)
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    source = tmp_path / "og-platform"
    (source / ".git").mkdir(parents=True)
    (source / "package.json").write_text("{}\n", encoding="utf-8")

    result = migrate_workspace(tmp_path, write=True, commit=False)

    assert result.git_initialized is False
    assert result.staged_paths == (".gitignore", "sources/README.md", "re/.gitignore")
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert staged == [".gitignore", "re/.gitignore", "sources/README.md"]


@pytest.mark.unit
def test_migration_copies_legacy_config_to_canonical(tmp_path: Path) -> None:
    _write_workspace(tmp_path)
    legacy = tmp_path / ".specify" / "extensions" / "echelon" / "echelon-config.yml"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text("verify_command: pytest\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)

    result = migrate_workspace(tmp_path, write=True, commit=False)

    assert result.canonical_config_copied is True
    canonical = tmp_path / ".echelon" / "config.yml"
    assert canonical.read_text(encoding="utf-8") == "verify_command: pytest\n"
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert ".echelon/config.yml" in staged


@pytest.mark.unit
def test_migration_repairs_broad_echelon_ignore_before_staging_config(
    tmp_path: Path,
) -> None:
    _write_workspace(tmp_path)
    (tmp_path / ".gitignore").write_text(
        "/.specify/\n/runs/\n/.echelon/\n/.claude/\n",
        encoding="utf-8",
    )
    legacy = tmp_path / ".specify" / "extensions" / "echelon" / "echelon-config.yml"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text("verify_command: pytest\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)

    result = migrate_workspace(tmp_path, write=True, commit=False)

    assert result.canonical_config_copied is True
    gitignore = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert "!/.echelon/" in gitignore
    assert "!/.echelon/config.yml" in gitignore
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert ".echelon/config.yml" in staged


@pytest.mark.unit
def test_migration_stages_existing_canonical_config_after_ignore_repair(
    tmp_path: Path,
) -> None:
    _write_workspace(tmp_path)
    (tmp_path / ".gitignore").write_text(
        "/.specify/\n/runs/\n/.echelon/\n/.claude/\n",
        encoding="utf-8",
    )
    canonical = tmp_path / ".echelon" / "config.yml"
    canonical.parent.mkdir(parents=True, exist_ok=True)
    canonical.write_text("verify_command: pytest\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)

    result = migrate_workspace(tmp_path, write=True, commit=False)

    assert result.gitignore_updated is True
    assert ".echelon/config.yml" in result.staged_paths
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert ".echelon/config.yml" in staged


@pytest.mark.unit
def test_migration_untracks_legacy_runtime_state(tmp_path: Path) -> None:
    _write_workspace(tmp_path)
    legacy = tmp_path / ".specify" / "extensions" / "echelon" / "echelon-config.yml"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text("verify_command: pytest\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", ".specify"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "track runtime"], cwd=tmp_path, check=True, capture_output=True)

    result = migrate_workspace(tmp_path, write=True, commit=False)

    assert any(path.startswith(".specify/") for path in result.untracked_runtime_paths)
    still_tracked = subprocess.run(
        ["git", "ls-files", ".specify"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert still_tracked == []


@pytest.mark.unit
def test_existing_gitignore_runtime_entries_satisfy_runtime_ignore(tmp_path: Path) -> None:
    _write_workspace(tmp_path)
    (tmp_path / ".gitignore").write_text(
        ".specify\nruns\n.claude\n.claude-work\n!/.echelon/\n!/.echelon/config.yml\n.echelon/local.yml\n.echelon/runtime\n.echelon/cache\n.echelon/recovery-backups\n/sources/*\n!/sources/README.md\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)

    result = migrate_workspace(tmp_path, write=True, commit=False)

    assert result.gitignore_updated is False
    assert result.staged_paths == ("sources/README.md", "re/.gitignore")
    assert (tmp_path / ".gitignore").read_text(encoding="utf-8") == (
        ".specify\nruns\n.claude\n.claude-work\n!/.echelon/\n!/.echelon/config.yml\n.echelon/local.yml\n.echelon/runtime\n.echelon/cache\n.echelon/recovery-backups\n/sources/*\n!/sources/README.md\n"
    )


@pytest.mark.unit
def test_migration_refuses_non_echelon_workspace(tmp_path: Path) -> None:
    (tmp_path / "source").mkdir()

    with pytest.raises(MigrationError, match="not an Echelon workspace"):
        build_migration_plan(tmp_path)


@pytest.mark.unit
def test_migration_dry_run_does_not_write(tmp_path: Path) -> None:
    _write_workspace(tmp_path)
    (tmp_path / "repo" / ".git").mkdir(parents=True)

    result = migrate_workspace(tmp_path, write=False, commit=False)

    assert result.git_initialized is False
    assert result.committed is False
    assert not (tmp_path / ".git").exists()
    assert not (tmp_path / ".gitignore").exists()


@pytest.mark.unit
def test_workspace_doctor_reports_runtime_tracking_and_legacy_config(
    tmp_path: Path,
) -> None:
    _write_workspace(tmp_path)
    legacy = tmp_path / ".specify" / "extensions" / "echelon" / "echelon-config.yml"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text("verify_command: pytest\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", ".specify"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "track runtime"], cwd=tmp_path, check=True, capture_output=True)

    result = doctor_workspace(tmp_path)

    codes = {finding.code for finding in result.findings}
    assert result.has_errors is True
    assert "canonical_config_missing" in codes
    assert "runtime_not_ignored" in codes
    assert "runtime_tracked" in codes


@pytest.mark.unit
def test_workspace_doctor_accepts_configured_source_root(tmp_path: Path) -> None:
    _write_workspace(tmp_path)
    (tmp_path / ".gitignore").write_text("/.specify/\n/runs/\n/app/\n", encoding="utf-8")
    (tmp_path / ".echelon").mkdir()
    (tmp_path / ".echelon" / "config.yml").write_text(
        "workspace:\n"
        "  git_role: orchestration\n"
        "sources:\n"
        "  - id: app\n"
        "    path: app\n",
        encoding="utf-8",
    )
    source = tmp_path / "app"
    source.mkdir()
    (source / "package.json").write_text("{}\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)

    result = doctor_workspace(tmp_path)

    assert result.has_errors is False
    assert result.buildable is True
    assert {finding.code for finding in result.findings} == set()


@pytest.mark.unit
def test_workspace_doctor_reports_ignored_canonical_config(tmp_path: Path) -> None:
    _write_workspace(tmp_path)
    (tmp_path / ".gitignore").write_text("/.specify/\n/runs/\n/.echelon/\n", encoding="utf-8")
    (tmp_path / ".echelon").mkdir()
    (tmp_path / ".echelon" / "config.yml").write_text(
        "workspace:\n  git_role: orchestration\nsources: []\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)

    result = doctor_workspace(tmp_path)

    assert result.has_errors is True
    assert "canonical_config_ignored" in {finding.code for finding in result.findings}


@pytest.mark.unit
def test_workspace_doctor_reports_unignored_recovery_backups(tmp_path: Path) -> None:
    _write_workspace(tmp_path)
    (tmp_path / ".gitignore").write_text(
        "/.specify/\n/runs/\n!/.echelon/\n!/.echelon/config.yml\n",
        encoding="utf-8",
    )
    (tmp_path / ".echelon" / "recovery-backups" / "abc123").mkdir(parents=True)
    (tmp_path / ".echelon" / "config.yml").write_text(
        "workspace:\n  git_role: orchestration\nsources: []\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)

    result = doctor_workspace(tmp_path)

    assert result.has_errors is True
    assert "runtime_not_ignored" in {finding.code for finding in result.findings}


@pytest.mark.unit
def test_workspace_doctor_marks_empty_sources_planning_only(tmp_path: Path) -> None:
    _write_workspace(tmp_path)
    (tmp_path / ".gitignore").write_text("/.specify/\n/runs/\n", encoding="utf-8")
    (tmp_path / ".echelon").mkdir()
    (tmp_path / ".echelon" / "config.yml").write_text(
        "workspace:\n  git_role: orchestration\nsources: []\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)

    result = doctor_workspace(tmp_path)

    assert result.has_errors is False
    assert result.buildable is False
    assert {finding.code for finding in result.findings} == {"planning_only_workspace"}


@pytest.mark.unit
def test_workspace_doctor_rejects_ignored_re_artifact_surface(tmp_path: Path) -> None:
    _write_workspace(tmp_path)
    (tmp_path / ".gitignore").write_text(
        "/.specify/\n/runs/\n/re/\n",
        encoding="utf-8",
    )
    (tmp_path / ".echelon").mkdir()
    (tmp_path / ".echelon" / "config.yml").write_text(
        "workspace:\n  git_role: orchestration\nsources: []\n",
        encoding="utf-8",
    )
    (tmp_path / "re").mkdir()
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)

    result = doctor_workspace(tmp_path)

    findings = {finding.code: finding for finding in result.findings}
    assert findings["re_ignored"].path == "re"


@pytest.mark.unit
def test_workspace_doctor_rejects_unignored_re_runtime_dirs(tmp_path: Path) -> None:
    _write_workspace(tmp_path)
    (tmp_path / ".gitignore").write_text("/.specify/\n/runs/\n", encoding="utf-8")
    (tmp_path / ".echelon").mkdir()
    (tmp_path / ".echelon" / "config.yml").write_text(
        "workspace:\n  git_role: orchestration\nsources: []\n",
        encoding="utf-8",
    )
    (tmp_path / "re" / ".cache").mkdir(parents=True)
    (tmp_path / "re" / ".cache" / "entry.json").write_text("{}\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)

    result = doctor_workspace(tmp_path)

    runtime_paths = {
        finding.path
        for finding in result.findings
        if finding.code == "re_runtime_not_ignored"
    }
    assert "re/.cache" in runtime_paths
