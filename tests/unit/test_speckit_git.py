from __future__ import annotations

import json
from pathlib import Path
import subprocess

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
    def unexpected_run(*_args, **_kwargs):
        raise AssertionError("specify must not run when the Git extension is absent")

    state = disable_speckit_git(tmp_path, run=unexpected_run)

    assert state.safe is True
    assert state.installed is False


def test_disable_invokes_specify_and_verifies_postcondition(tmp_path: Path) -> None:
    _write_registry(tmp_path, enabled=True)
    _write_hooks(tmp_path, enabled=True)
    calls: list[tuple[list[str], Path]] = []

    def fake_run(command, *, cwd, capture_output, text, check):
        calls.append((command, cwd))
        assert capture_output is True
        assert text is True
        assert check is False
        _write_registry(tmp_path, enabled=False)
        _write_hooks(tmp_path, enabled=False)
        return subprocess.CompletedProcess(command, 0, stdout="disabled", stderr="")

    state = disable_speckit_git(tmp_path, run=fake_run)

    assert calls == [(["specify", "extension", "disable", "git"], tmp_path)]
    assert state.safe is True
    assert state.registry_enabled is False


def test_disable_reports_specify_failure(tmp_path: Path) -> None:
    _write_registry(tmp_path, enabled=True)

    def fake_run(command, **_kwargs):
        return subprocess.CompletedProcess(command, 2, stdout="", stderr="registry locked")

    with pytest.raises(SpecKitGitOwnershipError, match="registry locked"):
        disable_speckit_git(tmp_path, run=fake_run)


def test_disable_rejects_false_success_that_leaves_git_enabled(tmp_path: Path) -> None:
    _write_registry(tmp_path, enabled=True)

    def fake_run(command, **_kwargs):
        return subprocess.CompletedProcess(command, 0, stdout="disabled", stderr="")

    with pytest.raises(SpecKitGitOwnershipError, match="remains enabled"):
        disable_speckit_git(tmp_path, run=fake_run)
