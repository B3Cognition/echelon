from pathlib import Path

from harness.provider_scaffolding import provider_runtime_scaffolder


def _runtime_extension(root: Path) -> Path:
    extension = root / ".specify" / "extensions" / "echelon"
    (extension / "agents" / "control").mkdir(parents=True)
    (extension / "agents" / "build").mkdir(parents=True)
    (extension / "commands").mkdir()
    (extension / "workflow").mkdir()
    (extension / "agents" / "control" / "commander.md").write_text(
        "# COMMANDER\n\ncontrol\n",
        encoding="utf-8",
    )
    (extension / "agents" / "build" / "spec-guard.md").write_text(
        "# SPEC GUARD\n\nbuild\n",
        encoding="utf-8",
    )
    (extension / "commands" / "echelon.verify-spec.md").write_text(
        "---\n"
        "name: speckit.echelon.verify-spec\n"
        "description: Verify spec\n"
        "---\n\n"
        "Read `agents/control/commander.md`.\n",
        encoding="utf-8",
    )
    (extension / "commands" / "echelon.build.md").write_text(
        "---\n"
        "name: speckit.echelon.build\n"
        "description: Build spec\n"
        "---\n\n"
        "Build from `workflow/definition.yaml`.\n",
        encoding="utf-8",
    )
    (extension / "commands" / "echelon.run.md").write_text(
        "---\n"
        "name: speckit.echelon.run\n"
        "description: Run Phase A\n"
        "---\n\n"
        "Run Phase A.\n",
        encoding="utf-8",
    )
    (extension / "commands" / "echelon.re-extract.md").write_text(
        "---\n"
        "name: speckit.echelon.re-extract\n"
        "description: Reverse engineer\n"
        "---\n\n"
        "Run reverse engineering.\n",
        encoding="utf-8",
    )
    (extension / "workflow" / "definition.yaml").write_text("workflow\n", encoding="utf-8")
    return extension


def test_claude_provider_scaffolder_materializes_claude_runtime_wrappers(tmp_path):
    extension = _runtime_extension(tmp_path)
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    excluded: list[str] = []

    provider_runtime_scaffolder("claude").sync(
        extension_root=extension,
        worktree=worktree,
        exclude_line=excluded.append,
    )

    assert (worktree / ".claude" / "skills" / "speckit-echelon-verify-spec" / "SKILL.md").exists()
    assert (worktree / ".claude" / "skills" / "speckit-echelon-build" / "SKILL.md").exists()
    assert not (worktree / ".claude" / "skills" / "speckit-echelon-run").exists()
    assert not (worktree / ".claude" / "skills" / "speckit-echelon-re-extract").exists()
    assert (worktree / ".claude" / "agents" / "speckit-echelon-commander.md").exists()
    assert (worktree / ".claude" / "agents" / "speckit-echelon-spec-guard.md").exists()
    assert ".claude/skills/speckit-echelon-verify-spec/" in excluded
    assert ".claude/skills/speckit-echelon-build/" in excluded
    assert ".claude/skills/speckit-echelon-run/" not in excluded
    assert ".claude/skills/speckit-echelon-re-extract/" not in excluded
    assert ".claude/agents/" in excluded


def test_non_claude_provider_scaffolder_is_an_explicit_noop(tmp_path):
    extension = _runtime_extension(tmp_path)
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    excluded: list[str] = []

    provider_runtime_scaffolder("codex").sync(
        extension_root=extension,
        worktree=worktree,
        exclude_line=excluded.append,
    )

    assert not (worktree / ".claude").exists()
    assert excluded == []
