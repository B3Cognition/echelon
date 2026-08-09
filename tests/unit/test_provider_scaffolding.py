from pathlib import Path

from harness.provider_scaffolding import provider_runtime_scaffolder


def _prosaic_prose(root: Path) -> Path:
    prose = root / ".echelon" / "prosaic"
    (prose / "commands").mkdir(parents=True)
    (prose / "subagents").mkdir()
    (prose / "subagents" / "echelon.commander.md").write_text(
        "# COMMANDER\n\ncontrol\n", encoding="utf-8"
    )
    (prose / "subagents" / "echelon.spec-guard.md").write_text(
        "# SPEC GUARD\n\nbuild\n", encoding="utf-8"
    )
    (prose / "commands" / "echelon.verify-spec.md").write_text(
        "---\n"
        "name: echelon.verify-spec\n"
        "description: Verify spec\n"
        "---\n\n"
        "Read `agents/control/commander.md`.\n",
        encoding="utf-8",
    )
    (prose / "commands" / "echelon.build.md").write_text(
        "---\n"
        "name: echelon.build\n"
        "description: Build spec\n"
        "---\n\n"
        "Build from `workflow/definition.yaml`.\n",
        encoding="utf-8",
    )
    (prose / "commands" / "echelon.run.md").write_text(
        "---\n"
        "name: echelon.run\n"
        "description: Run Phase A\n"
        "---\n\n"
        "Run Phase A.\n",
        encoding="utf-8",
    )
    (prose / "commands" / "echelon.re-extract.md").write_text(
        "---\n"
        "name: echelon.re-extract\n"
        "description: Reverse engineer\n"
        "---\n\n"
        "Run reverse engineering.\n",
        encoding="utf-8",
    )
    return prose


def test_claude_provider_scaffolder_materializes_claude_runtime_wrappers(tmp_path):
    prose = _prosaic_prose(tmp_path)
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    excluded: list[str] = []

    provider_runtime_scaffolder("claude").sync(
        prose_root=prose,
        worktree=worktree,
        exclude_line=excluded.append,
    )

    assert (worktree / ".claude" / "skills" / "echelon-verify-spec" / "SKILL.md").exists()
    assert (worktree / ".claude" / "skills" / "echelon-build" / "SKILL.md").exists()
    verify_skill = (
        worktree / ".claude" / "skills" / "echelon-verify-spec" / "SKILL.md"
    ).read_text(encoding="utf-8")
    build_skill = (
        worktree / ".claude" / "skills" / "echelon-build" / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert "agents/control/commander.md" not in verify_skill
    assert "workflow/definition.yaml" not in build_skill
    assert "compatibility: Requires an Echelon workspace with .echelon/runtime/" in verify_skill
    assert "author: echelon" in verify_skill
    assert not (worktree / ".claude" / "skills" / "echelon-run").exists()
    assert not (worktree / ".claude" / "skills" / "echelon-re-extract").exists()
    assert not (worktree / ".claude" / "agents" / "echelon-commander.md").exists()
    assert (worktree / ".claude" / "agents" / "echelon-spec-guard.md").exists()
    assert ".claude/skills/echelon-verify-spec/" in excluded
    assert ".claude/skills/echelon-build/" in excluded
    assert ".claude/skills/echelon-run/" not in excluded
    assert ".claude/skills/echelon-re-extract/" not in excluded
    assert ".claude/agents/" in excluded


def test_non_claude_provider_scaffolder_is_an_explicit_noop(tmp_path):
    prose = _prosaic_prose(tmp_path)
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    excluded: list[str] = []

    provider_runtime_scaffolder("codex").sync(
        prose_root=prose,
        worktree=worktree,
        exclude_line=excluded.append,
    )

    assert not (worktree / ".claude").exists()
    assert excluded == []
