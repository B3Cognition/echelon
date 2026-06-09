"""Tests for config loading and validation.

Coverage:
  Validation (via _parse_config — no filesystem):
    - Valid minimal dict loads with all defaults
    - Valid full dict preserves all fields
    - Missing target_repo raises ValidationError
    - Invalid provider raises ValidationError
    - Invalid semver range raises ValidationError

  Defaults:
    - Resource limits match spec
    - Network allowlist contains all 9 FQDNs

  4-level config cascade (via load_config with temp project_root):
    - Layer 2 project config is applied
    - Layer 3 local config overrides project config
    - Layer 4 env vars (SPECKIT_HARNESS_*) override local config
    - Missing config files are silently skipped (only required fields needed)
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from harness.config import (
    DEFAULT_NETWORK_ALLOWLIST,
    HarnessConfig,
    ValidationError,
    _parse_config,
    load_config,
)

ROOT = Path(__file__).resolve().parents[2]
CONFIG_TEMPLATE = ROOT / "extension" / "config-template.yml"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MINIMAL = {
    "target_repo": "git@github.com:example/payments.git",
    "target_default_branch": "main",
    "provider": "docker",
}

FULL = {
    "target_repo": "git@github.com:example/payments.git",
    "target_default_branch": "main",
    "provider": "docker",
    "base_image": "node:20-slim",
    "resource_limits": {
        "memory": "8g",
        "cpu": 4.0,
        "pids": 512,
        "storage": "20g",
    },
    "buffer_limit_bytes": 20_971_520,
    "gc": {
        "worktree_max_age_hours": 48,
        "container_max_age_hours": 2,
        "backup_max_age_days": 14,
    },
    "echelon_version_range": ">=0.4.0 <1.0.0",
    "bind_mount_ack": True,
    "pr_host": "github",
    "network": {
        "allowlist": ["custom.registry.io"],
    },
}


def test_config_template_schema_comment_uses_workspace_specs_path() -> None:
    text = CONFIG_TEMPLATE.read_text(encoding="utf-8")

    assert ".specify/specs/003-internalization-metrics/data-model.md" not in text
    assert "specs/003-internalization-metrics/data-model.md" in text


def _ext_dir(project_root: Path) -> Path:
    d = project_root / ".specify" / "extensions" / "echelon"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_yaml(path: Path, data: dict) -> None:
    path.write_text(yaml.dump(data), encoding="utf-8")


# ---------------------------------------------------------------------------
# Validation tests (no filesystem)
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestParseConfigValid:
    def test_minimal_loads_with_defaults(self) -> None:
        config = _parse_config(MINIMAL)
        assert isinstance(config, HarnessConfig)
        assert config.target_repo == "git@github.com:example/payments.git"
        assert config.target_default_branch == "main"
        assert config.provider == "docker"
        assert config.resource_limits.memory == "4g"
        assert config.resource_limits.cpu == 2.0
        assert config.resource_limits.pids == 256
        assert config.resource_limits.storage == "10g"
        assert config.buffer_limit_bytes == 10_485_760
        assert config.ci_skip_enabled is True
        assert config.bind_mount_ack is False
        assert config.pr_host == "none"

    def test_full_dict_preserves_all_fields(self) -> None:
        config = _parse_config(FULL)
        assert config.base_image == "node:20-slim"
        assert config.resource_limits.memory == "8g"
        assert config.resource_limits.cpu == 4.0
        assert config.resource_limits.pids == 512
        assert config.resource_limits.storage == "20g"
        assert config.buffer_limit_bytes == 20_971_520
        assert config.gc.worktree_max_age_hours == 48
        assert config.gc.container_max_age_hours == 2
        assert config.gc.backup_max_age_days == 14
        assert config.echelon_version_range == ">=0.4.0 <1.0.0"
        assert config.bind_mount_ack is True
        assert config.pr_host == "github"
        assert "custom.registry.io" in config.network.allowlist


@pytest.mark.unit
class TestParseConfigInvalid:
    def test_missing_target_repo_raises(self) -> None:
        data = {**MINIMAL}
        del data["target_repo"]
        with pytest.raises(ValidationError, match="target_repo"):
            _parse_config(data)

    def test_empty_target_repo_raises(self) -> None:
        with pytest.raises(ValidationError, match="target_repo"):
            _parse_config({**MINIMAL, "target_repo": "  "})

    def test_invalid_provider_raises(self) -> None:
        with pytest.raises(ValidationError, match="provider"):
            _parse_config({**MINIMAL, "provider": "kubernetes"})

    def test_codex_is_not_a_sandbox_provider(self) -> None:
        with pytest.raises(ValidationError, match="provider"):
            _parse_config({**MINIMAL, "provider": "codex"})

    def test_invalid_llm_cli_raises(self) -> None:
        with pytest.raises(ValidationError, match="llm.cli"):
            _parse_config({**MINIMAL, "llm": {"cli": "kubernetes"}})

    def test_invalid_semver_range_raises(self) -> None:
        with pytest.raises(ValidationError, match="semver"):
            _parse_config({**MINIMAL, "echelon_version_range": "not-a-range!!"})

    def test_codex_is_valid_llm_cli_backend(self) -> None:
        config = _parse_config({**MINIMAL, "llm": {"cli": "codex"}})

        assert config.provider == "docker"
        assert config.llm.cli == "codex"


@pytest.mark.unit
class TestConfigDefaults:
    def test_default_resource_limits(self) -> None:
        config = _parse_config(MINIMAL)
        assert config.resource_limits.memory == "4g"
        assert config.resource_limits.cpu == 2.0
        assert config.resource_limits.pids == 256
        assert config.resource_limits.storage == "10g"

    def test_default_network_allowlist_has_all_9_fqdns(self) -> None:
        config = _parse_config(MINIMAL)
        for fqdn in DEFAULT_NETWORK_ALLOWLIST:
            assert fqdn in config.network.allowlist, f"Missing FQDN: {fqdn}"
        assert len(config.network.allowlist) == 9


# ---------------------------------------------------------------------------
# 4-level cascade tests (load_config with temp project_root)
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestLoadConfigCascade:
    @pytest.fixture(autouse=True)
    def _force_fallback_config_loader(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # ConfigManager.get_config() reads the globally registered extension config,
        # not the project-level file under tmp_path — force the inline fallback so
        # these unit tests exercise the real merge logic against the temp fixtures.
        monkeypatch.setattr("harness.config._SpecKitConfigManager", None)
    def test_project_config_applied(self, tmp_path: Path) -> None:
        ext = _ext_dir(tmp_path)
        _write_yaml(ext / "echelon-config.yml", {"harness": {
            **MINIMAL,
            "resource_limits": {"memory": "8g"},
        }})
        config = load_config(tmp_path)
        assert config.resource_limits.memory == "8g"
        # Defaults still fill unspecified sub-fields
        assert config.resource_limits.cpu == 2.0

    def test_local_config_overrides_project(self, tmp_path: Path) -> None:
        ext = _ext_dir(tmp_path)
        _write_yaml(ext / "echelon-config.yml", {"harness": {**MINIMAL, "buffer_limit_bytes": 5_000_000}})
        _write_yaml(ext / "local-config.yml", {"harness": {"buffer_limit_bytes": 1_000_000}})
        config = load_config(tmp_path)
        assert config.buffer_limit_bytes == 1_000_000

    def test_env_vars_override_local(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Env var parsing splits on '_' as nesting separators (same as ConfigManager),
        # so only single-word top-level keys round-trip cleanly via env vars.
        # SPECKIT_HARNESS_PROVIDER → {"provider": "e2b"}
        ext = _ext_dir(tmp_path)
        _write_yaml(ext / "echelon-config.yml", {"harness": MINIMAL})
        _write_yaml(ext / "local-config.yml", {"harness": {"provider": "docker"}})
        monkeypatch.setenv("SPECKIT_HARNESS_PROVIDER", "e2b")
        config = load_config(tmp_path)
        assert config.provider == "e2b"

    def test_missing_optional_files_are_skipped(self, tmp_path: Path) -> None:
        ext = _ext_dir(tmp_path)
        # Only project config — no local, no env vars
        _write_yaml(ext / "echelon-config.yml", {"harness": MINIMAL})
        config = load_config(tmp_path)
        assert config.provider == "docker"

    def test_defaults_cwd_used_when_no_project_root(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        ext = _ext_dir(tmp_path)
        _write_yaml(ext / "echelon-config.yml", {"harness": MINIMAL})
        monkeypatch.chdir(tmp_path)
        config = load_config()  # no project_root — falls back to cwd
        assert config.target_repo == MINIMAL["target_repo"]


@pytest.mark.unit
class TestVisualTestsConfig:
    def test_visual_tests_defaults(self) -> None:
        """visual_tests block absent → all defaults applied."""
        cfg = _parse_config({
            "target_repo": "https://github.com/x/y",
            "target_default_branch": "main",
            "provider": "docker",
        })
        assert cfg.visual_tests.enabled is False
        assert cfg.visual_tests.serve_command == "npm run preview"
        assert cfg.visual_tests.test_command == "npx playwright test --reporter=json"
        assert cfg.visual_tests.timeout_ms == 300_000
        assert cfg.visual_tests.screenshot_dir == "playwright-report"
        assert cfg.visual_tests.max_iterations == 3

    def test_visual_tests_enabled_flag(self) -> None:
        """visual_tests.enabled and serve_command can be overridden."""
        cfg = _parse_config({
            "target_repo": "https://github.com/x/y",
            "target_default_branch": "main",
            "provider": "docker",
            "visual_tests": {"enabled": True, "serve_command": "npm run dev"},
        })
        assert cfg.visual_tests.enabled is True
        assert cfg.visual_tests.serve_command == "npm run dev"
        # Unset fields still default
        assert cfg.visual_tests.test_command == "npx playwright test --reporter=json"


@pytest.mark.unit
def test_app_runtime_config_parsed() -> None:
    """harness.app block is parsed for brownfield Docker-backed app runtime."""
    cfg = _parse_config({
        "target_repo": "https://github.com/x/y",
        "target_default_branch": "main",
        "provider": "docker",
        "app": {
            "enabled": True,
            "mode": "docker_compose",
            "compose_file": "docker-compose.yml",
            "service": "web",
            "url": "http://localhost:3000",
        },
    })

    assert cfg.app.enabled is True
    assert cfg.app.mode == "docker_compose"
    assert cfg.app.compose_file == "docker-compose.yml"
    assert cfg.app.service == "web"
    assert cfg.app.url == "http://localhost:3000"


@pytest.mark.unit
def test_app_runtime_command_profile_parsed() -> None:
    """harness.app supports explicit command profiles for brownfield apps."""
    cfg = _parse_config({
        "target_repo": "https://github.com/x/y",
        "target_default_branch": "main",
        "provider": "docker",
        "app": {
            "enabled": True,
            "mode": "command",
            "app": "frontend",
            "setup_commands": ["docker compose -f compose.db.yml up -d postgres"],
            "start_commands": ["npx nx dev frontend"],
            "stop_commands": ["pkill -f 'nx dev frontend'"],
            "url": "http://localhost:3000",
            "readiness_timeout_ms": 120000,
        },
    })

    assert cfg.app.enabled is True
    assert cfg.app.mode == "command"
    assert cfg.app.app == "frontend"
    assert cfg.app.setup_commands == ["docker compose -f compose.db.yml up -d postgres"]
    assert cfg.app.start_commands == ["npx nx dev frontend"]
    assert cfg.app.stop_commands == ["pkill -f 'nx dev frontend'"]
    assert cfg.app.url == "http://localhost:3000"
    assert cfg.app.readiness_timeout_ms == 120000


@pytest.mark.unit
def test_app_runtime_command_profile_accepts_single_command_strings() -> None:
    """Single command values are normalized to one-item lists."""
    cfg = _parse_config({
        "target_repo": "https://github.com/x/y",
        "target_default_branch": "main",
        "provider": "docker",
        "app": {
            "enabled": True,
            "mode": "command",
            "setup_commands": "docker compose -f compose.db.yml up -d postgres",
            "start_commands": "npx nx dev frontend",
            "stop_commands": "npx nx reset",
        },
    })

    assert cfg.app.setup_commands == ["docker compose -f compose.db.yml up -d postgres"]
    assert cfg.app.start_commands == ["npx nx dev frontend"]
    assert cfg.app.stop_commands == ["npx nx reset"]


# ---------------------------------------------------------------------------
# LlmConfig tests
# ---------------------------------------------------------------------------


def test_llm_defaults():
    """LlmConfig has correct defaults when section absent."""
    config = _parse_config({
        "target_repo": ".",
        "target_default_branch": "main",
        "provider": "docker",
    })
    assert config.llm.timeout_ms == 1_200_000
    assert config.llm.config_dir is None


def test_llm_config_dir_set():
    """LlmConfig.config_dir is read from config."""
    config = _parse_config({
        "target_repo": ".",
        "target_default_branch": "main",
        "provider": "docker",
        "llm": {"config_dir": "/home/user/.config/claude-work"},
    })
    assert config.llm.config_dir == "/home/user/.config/claude-work"


def test_llm_timeout_ms_set():
    """LlmConfig.timeout_ms is read from config."""
    config = _parse_config({
        "target_repo": ".",
        "target_default_branch": "main",
        "provider": "docker",
        "llm": {"timeout_ms": 600_000},
    })
    assert config.llm.timeout_ms == 600_000
