"""Tests for _cmd_harness_run argument parsing in cli.py.

Covers the free-text task description capture introduced to fix the bug
where 'echelon harness run 013 strategy=codegen "do X"' silently dropped "do X".
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness.run_intent import parse_intent


@pytest.mark.unit
class TestHarnessRunArgParsing:
    """Verify the user_message built by _cmd_harness_run reaches parse_intent correctly."""

    def _build_user_message(self, args: list[str]) -> str:
        """Replicate the user_message construction logic from _cmd_harness_run."""
        spec_id = args[0]
        kv: dict[str, str] = {}
        free_text: list[str] = []
        for arg in args[1:]:
            if "=" in arg:
                k, _, v = arg.partition("=")
                kv[k.strip()] = v.strip()
            else:
                free_text.append(arg)
        strategy = kv.get("strategy", "default")
        mode = kv.get("mode", "semi")
        parts = [f"spec {spec_id}", f"{mode} mode", f"strategies={strategy}"]
        if free_text:
            parts.append(f"task: {' '.join(free_text)}")
        return " ".join(parts)

    def test_free_text_becomes_task_description(self) -> None:
        """Free-text arg is forwarded as task_description through parse_intent."""
        msg = self._build_user_message(
            ["013", "strategy=codegen", "fix the bug as described in 'bugfix-1.md'"]
        )
        intent = parse_intent(msg)
        assert intent.task_description == "fix the bug as described in 'bugfix-1.md'"
        assert intent.spec_id == "013"
        assert intent.strategies == ["codegen"]

    def test_no_free_text_gives_empty_task_description(self) -> None:
        """When only kv args are given, task_description is empty."""
        msg = self._build_user_message(["013", "strategy=codegen"])
        intent = parse_intent(msg)
        assert intent.task_description == ""

    def test_multiple_free_text_words_joined(self) -> None:
        """Multiple free-text tokens are joined into a single task_description."""
        msg = self._build_user_message(["013", "implement", "feature", "X"])
        intent = parse_intent(msg)
        assert intent.task_description == "implement feature X"

    def test_kv_args_not_leaked_into_task(self) -> None:
        """key=value pairs are not included in task_description."""
        msg = self._build_user_message(["013", "mode=banzai", "strategy=default", "do the thing"])
        intent = parse_intent(msg)
        assert intent.task_description == "do the thing"
        assert intent.mode == "banzai"
        assert "mode=banzai" not in intent.task_description


@pytest.mark.unit
class TestHarnessRunTaskFormatErrors:
    def test_old_task_format_exits_with_migration_guidance(
        self,
        tmp_path: Path,
        monkeypatch,
        capsys,
    ) -> None:
        echelon_yml = tmp_path / ".specify" / "extensions" / "echelon" / "echelon-config.yml"
        echelon_yml.parent.mkdir(parents=True)
        echelon_yml.write_text("harness:\n  target_repo: .\n", encoding="utf-8")

        mirror = tmp_path / "runs" / "mirror.git"
        mirror.mkdir(parents=True)

        spec_dir = tmp_path / "specs" / "003-test"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")
        (spec_dir / "tasks.md").write_text("### T-001: Legacy task\n", encoding="utf-8")

        monkeypatch.chdir(tmp_path)

        with patch("harness.config.load_config") as mock_cfg, \
             patch("harness.paths.mirror_path", return_value=mirror), \
             patch("harness.gitops.GitOpsManager"), \
             patch("harness.docker_provider.DockerWorktreeProvider"), \
             patch("harness.skills.run_skill.run") as mock_run:
            mock_cfg.return_value = MagicMock(buffer_limit_bytes=1024 * 1024, target_repo=".")
            from echelon.cli import _cmd_harness_run

            with pytest.raises(SystemExit) as exc:
                _cmd_harness_run(["003"])

        assert exc.value.code == 1
        mock_run.assert_not_called()
        err = capsys.readouterr().err
        assert "tasks.md is not in canonical format" in err
        assert "no canonical task rows found" in err
        assert "python -m harness migrate-tasks" in err
        assert "--write" in err

    def test_invalid_plan_format_exits_with_migration_guidance(
        self,
        tmp_path: Path,
        monkeypatch,
        capsys,
    ) -> None:
        echelon_yml = tmp_path / ".specify" / "extensions" / "echelon" / "echelon-config.yml"
        echelon_yml.parent.mkdir(parents=True)
        echelon_yml.write_text("harness:\n  target_repo: .\n", encoding="utf-8")

        mirror = tmp_path / "runs" / "mirror.git"
        mirror.mkdir(parents=True)

        spec_dir = tmp_path / "specs" / "003-test"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")
        (spec_dir / "tasks.md").write_text(
            "- [ ] T-001 complexity=standard phase=foundation req=INFRA depends=none\n",
            encoding="utf-8",
        )
        (spec_dir / "plan.md").write_text("# Plan\n\n## Summary\n", encoding="utf-8")

        monkeypatch.chdir(tmp_path)

        with patch("harness.config.load_config") as mock_cfg, \
             patch("harness.paths.mirror_path", return_value=mirror), \
             patch("harness.gitops.GitOpsManager"), \
             patch("harness.docker_provider.DockerWorktreeProvider"), \
             patch("harness.skills.run_skill.run") as mock_run:
            mock_cfg.return_value = MagicMock(buffer_limit_bytes=1024 * 1024, target_repo=".")
            from echelon.cli import _cmd_harness_run

            with pytest.raises(SystemExit) as exc:
                _cmd_harness_run(["003"])

        assert exc.value.code == 1
        mock_run.assert_not_called()
        err = capsys.readouterr().err
        assert "plan.md is not in canonical format" in err
        assert "python -m harness migrate-plan" in err
        assert "--write" in err
