from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from echelon.speckit_git import (
    SpecKitGitOwnershipError,
    disable_speckit_git,
    inspect_speckit_git,
    require_speckit_git_disabled,
)


def _write_registry(project_root: Path, *, enabled: bool) -> None:
    path = project_root / ".specify" / "extensions" / ".registry"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "extensions": {"git": {"version": "1.0.0", "enabled": enabled}},
            }
        ),
        encoding="utf-8",
    )


def _write_hooks(project_root: Path, *, enabled: bool) -> None:
    path = project_root / ".specify" / "extensions.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "installed": ["git"],
                "hooks": {
                    "before_specify": [
                        {
                            "extension": "git",
                            "command": "speckit.git.feature",
                            "enabled": enabled,
                        }
                    ]
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def test_absent_git_extension_is_safe(tmp_path: Path) -> None:
    state = inspect_speckit_git(tmp_path)

    assert state.safe is True
    assert state.installed is False
    assert state.registry_enabled is None
    assert state.enabled_hooks == ()


def test_enabled_registry_is_unsafe(tmp_path: Path) -> None:
    _write_registry(tmp_path, enabled=True)
    _write_hooks(tmp_path, enabled=True)

    state = inspect_speckit_git(tmp_path)

    assert state.safe is False
    assert state.installed is True
    assert state.registry_enabled is True
    assert state.enabled_hooks == ("before_specify:speckit.git.feature",)
    assert "enabled" in state.reason


def test_disabled_registry_and_hooks_are_safe(tmp_path: Path) -> None:
    _write_registry(tmp_path, enabled=False)
    _write_hooks(tmp_path, enabled=False)

    state = require_speckit_git_disabled(tmp_path)

    assert state.safe is True
    assert state.installed is True
    assert state.registry_enabled is False
    assert state.enabled_hooks == ()


def test_enabled_hook_is_unsafe_even_when_registry_is_disabled(tmp_path: Path) -> None:
    _write_registry(tmp_path, enabled=False)
    _write_hooks(tmp_path, enabled=True)

    with pytest.raises(SpecKitGitOwnershipError, match="enabled Git hook"):
        require_speckit_git_disabled(tmp_path)


@pytest.mark.parametrize(
    ("relative_path", "content", "message"),
    [
        (Path(".specify/extensions/.registry"), "{not-json", "malformed"),
        (Path(".specify/extensions.yml"), "hooks: [", "malformed"),
    ],
)
def test_malformed_speckit_extension_state_fails_closed(
    tmp_path: Path,
    relative_path: Path,
    content: str,
    message: str,
) -> None:
    path = tmp_path / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")

    with pytest.raises(SpecKitGitOwnershipError, match=message):
        require_speckit_git_disabled(tmp_path)


def test_disable_is_idempotent_when_git_extension_is_absent(tmp_path: Path) -> None:
    state = disable_speckit_git(tmp_path)

    assert state.safe is True
    assert state.installed is False


def test_disable_updates_legacy_files_without_external_specify(tmp_path: Path) -> None:
    _write_registry(tmp_path, enabled=True)
    _write_hooks(tmp_path, enabled=True)
    hooks_path = tmp_path / ".specify" / "extensions.yml"
    hooks = yaml.safe_load(hooks_path.read_text(encoding="utf-8"))
    hooks["hooks"]["before_specify"].append(
        {
            "extension": "unrelated",
            "command": "unrelated.command",
            "enabled": True,
        }
    )
    hooks_path.write_text(yaml.safe_dump(hooks, sort_keys=False), encoding="utf-8")

    state = disable_speckit_git(tmp_path)

    assert state.safe is True
    assert state.registry_enabled is False
    registry = json.loads(
        (tmp_path / ".specify/extensions/.registry").read_text(encoding="utf-8")
    )
    assert registry["extensions"]["git"]["enabled"] is False
    rewritten_hooks = yaml.safe_load(hooks_path.read_text(encoding="utf-8"))
    git_hook, unrelated_hook = rewritten_hooks["hooks"]["before_specify"]
    assert git_hook["enabled"] is False
    assert unrelated_hook["enabled"] is True


def test_legacy_git_migration_has_no_external_specify_command() -> None:
    source = (
        Path(__file__).resolve().parents[2] / "src/echelon/speckit_git.py"
    ).read_text(encoding="utf-8")

    assert "SPEC_KIT_GIT_DISABLE_COMMAND" not in source
    assert "subprocess" not in source
