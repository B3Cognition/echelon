import json
from pathlib import Path
import subprocess

import pytest

from harness.errors import GitOpsError
from harness.gitops import deploy_provider_prose


def test_claude_provider_prose_is_deployed_by_prosaic(tmp_path: Path) -> None:
    calls: list[tuple[list[str], Path]] = []

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((command, Path(str(kwargs["cwd"]))))
        return subprocess.CompletedProcess(command, 0, stdout="apply: 2 created\n", stderr="")

    excludes = deploy_provider_prose("claude", tmp_path, run=run)

    assert calls == [
        (
            [
                "prosaic",
                "apply",
                "--source",
                ".echelon/prosaic",
                "--targets",
                "claude-code",
                "--types",
                "command",
                "subagent",
                "--no-color",
            ],
            tmp_path,
        )
    ]
    assert excludes == (
        ".claude/commands/",
        ".claude/agents/",
        ".claude/skills/",
        ".prosaic-manifest.json",
        ".prosaic-backups/",
        ".echelon/prosaic-provider-owner.json",
    )
    assert json.loads(
        (tmp_path / ".echelon/prosaic-provider-owner.json").read_text(encoding="utf-8")
    ) == {"owner": "echelon", "target": "claude-code"}


def test_provider_without_worktree_target_does_not_run_prosaic(tmp_path: Path) -> None:
    def run(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("Prosaic should not run for Codex delivery")

    assert deploy_provider_prose("codex", tmp_path, run=run) == ()


def test_prosaic_provider_deployment_failure_is_actionable(tmp_path: Path) -> None:
    def run(*_args: object, **_kwargs: object) -> object:
        raise subprocess.CalledProcessError(1, ["prosaic", "apply"], stderr="bad prose")

    with pytest.raises(GitOpsError, match="Prosaic provider deployment failed"):
        deploy_provider_prose("claude", tmp_path, run=run)


def test_existing_unclaimed_prosaic_manifest_blocks_delivery_deployment(
    tmp_path: Path,
) -> None:
    (tmp_path / ".prosaic-manifest.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(GitOpsError, match="already has a Prosaic manifest"):
        deploy_provider_prose(
            "claude",
            tmp_path,
            run=lambda *_args, **_kwargs: pytest.fail("Prosaic must not run"),
        )
