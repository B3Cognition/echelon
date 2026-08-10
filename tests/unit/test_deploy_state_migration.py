"""Deployment state migration into Echelon-owned user storage."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_migration_moves_state_and_repoints_existing_cli_wrapper(tmp_path: Path) -> None:
    from echelon.deploy_state_migration import migrate_legacy_deploy_state

    project = tmp_path / "legacy-app"
    home = tmp_path / "home"
    install_path = tmp_path / "bin"
    legacy_global = home / ".speckit-deploy" / "legacy-app.json"
    local_state = project / "runs" / "deploy-state.json"
    state = {
        "app": "legacy-app",
        "type": "cli",
        "active": "green",
        "install_path": str(install_path),
        "global_state_dir": str(legacy_global.parent),
        "traefik_name": "speckit-traefik",
        "deploy_network": "speckit-deploy",
    }
    _write_json(legacy_global, state)
    _write_json(local_state, state)
    install_path.mkdir(parents=True)
    wrapper = install_path / "legacy-app"
    wrapper.write_text(
        f'#!/usr/bin/env bash\n_state_file="{legacy_global}"\n',
        encoding="utf-8",
    )

    report = migrate_legacy_deploy_state(project, home=home)

    migrated_global = home / ".echelon" / "deploy" / "legacy-app.json"
    assert report.migrated is True
    assert report.global_state_path == migrated_global
    assert not legacy_global.exists()
    assert json.loads(migrated_global.read_text(encoding="utf-8")) == {
        **state,
        "global_state_dir": str(migrated_global.parent),
    }
    assert json.loads(local_state.read_text(encoding="utf-8")) == {
        **state,
        "global_state_dir": str(migrated_global.parent),
    }
    assert f'_state_file="{migrated_global}"' in wrapper.read_text(encoding="utf-8")


def test_migration_refuses_conflicting_echelon_global_state(tmp_path: Path) -> None:
    from echelon.deploy_state_migration import (
        DeployStateMigrationError,
        migrate_legacy_deploy_state,
    )

    project = tmp_path / "conflict-app"
    home = tmp_path / "home"
    legacy_global = home / ".speckit-deploy" / "conflict-app.json"
    migrated_global = home / ".echelon" / "deploy" / "conflict-app.json"
    local_state = project / "runs" / "deploy-state.json"
    legacy_state = {
        "app": "conflict-app",
        "type": "http",
        "active": "blue",
        "global_state_dir": str(legacy_global.parent),
    }
    _write_json(legacy_global, legacy_state)
    _write_json(local_state, legacy_state)
    _write_json(migrated_global, {**legacy_state, "active": "green"})

    with pytest.raises(DeployStateMigrationError, match="already exists"):
        migrate_legacy_deploy_state(project, home=home)

    assert json.loads(legacy_global.read_text(encoding="utf-8")) == legacy_state
    assert json.loads(local_state.read_text(encoding="utf-8")) == legacy_state
    assert json.loads(migrated_global.read_text(encoding="utf-8"))["active"] == "green"


def test_migration_uses_the_same_normalized_app_name_as_deploy_init(
    tmp_path: Path,
) -> None:
    from echelon.deploy_state_migration import migrate_legacy_deploy_state

    project = tmp_path / "Legacy App!"
    home = tmp_path / "home"
    legacy_global = home / ".speckit-deploy" / "legacyapp.json"
    _write_json(
        legacy_global,
        {
            "app": "legacyapp",
            "type": "http",
            "active": "blue",
            "global_state_dir": str(legacy_global.parent),
        },
    )

    report = migrate_legacy_deploy_state(project, home=home)

    assert report.migrated is True
    assert report.global_state_path == home / ".echelon" / "deploy" / "legacyapp.json"
