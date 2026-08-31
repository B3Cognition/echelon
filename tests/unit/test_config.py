"""Tests for config loading and validation.

Coverage:
  Validation (via _parse_config — no filesystem):
    - Valid minimal dict loads with all defaults
    - Valid full dict preserves all fields
    - target_repo raises migration ValidationError
    - Invalid provider raises ValidationError
    - Invalid semver range raises ValidationError

  Defaults:
    - Resource limits match spec
    - Network allowlist contains all 9 FQDNs

  4-level config cascade (via load_config with temp project_root):
    - Layer 2 project config is applied
    - Layer 3 local config overrides project config
    - Layer 4 env vars (ECHELON_HARNESS_*) override local config
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
    ReV2BaselineConfig,
    StacksConfig,
    ValidationError,
    _parse_config,
    get_full_resolved_config,
    load_config,
)

ROOT = Path(__file__).resolve().parents[2]
CONFIG_TEMPLATE = ROOT / "runtime" / "config-template.yml"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MINIMAL = {
    "provider": "docker",
}

FULL = {
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


def _echelon_dir(project_root: Path) -> Path:
    d = project_root / ".echelon"
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
        assert config.target_repo == ""
        assert config.target_default_branch == "main"
        assert config.provider == "docker"
        assert config.container_cli == "docker"
        assert config.resource_limits.memory == "4g"
        assert config.resource_limits.cpu == 2.0
        assert config.resource_limits.pids == 256
        assert config.resource_limits.storage == "10g"
        assert config.buffer_limit_bytes == 10_485_760
        assert config.ci_skip_enabled is True
        assert config.bind_mount_ack is False
        assert config.pr_host == "none"
        assert config.fulfillment.refresh_policy == "milestone"
        assert isinstance(config.stacks, StacksConfig)
        assert config.stacks.selected == []
        assert config.verification.execution == "sandbox"

    def test_host_verification_requires_explicit_opt_in(self) -> None:
        config = _parse_config({
            **MINIMAL,
            "verification": {"execution": "host"},
        })

        assert config.verification.execution == "host"

    def test_fulfillment_refresh_policy_can_be_configured(self) -> None:
        config = _parse_config({
            **MINIMAL,
            "fulfillment": {"refresh_policy": "convergence_only"},
        })

        assert config.fulfillment.refresh_policy == "convergence_only"

    def test_container_cli_accepts_podman(self) -> None:
        config = _parse_config({**MINIMAL, "container_cli": "podman"})

        assert config.container_cli == "podman"

    def test_scoped_fulfillment_refresh_policy_can_be_configured(self) -> None:
        config = _parse_config({
            **MINIMAL,
            "fulfillment": {"refresh_policy": "scoped"},
        })

        assert config.fulfillment.refresh_policy == "scoped"

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
        assert config.stacks.selected == []

    def test_stacks_default_to_empty_selection(self) -> None:
        config = _parse_config(MINIMAL)

        assert isinstance(config.stacks, StacksConfig)
        assert config.stacks.selected == []

    def test_stacks_selection_can_be_configured(self) -> None:
        config = _parse_config({
            **MINIMAL,
            "stacks": {
                "selected": [
                    "statsperform-playbook",
                    "statsperform-msa-service",
                ],
            },
        })

        assert config.stacks.selected == [
            "statsperform-playbook",
            "statsperform-msa-service",
        ]

    def test_stack_target_archetypes_can_be_configured(self) -> None:
        config = _parse_config({
            **MINIMAL,
            "stacks": {
                "selected": ["statsperform-stark-webapp"],
                "target_archetypes": ["web_app"],
            },
        })

        assert config.stacks.target_archetypes == ["web_app"]


@pytest.mark.unit
class TestParseConfigInvalid:
    def test_target_repo_is_rejected_with_spec_run_target_hint(self) -> None:
        with pytest.raises(ValidationError, match="echelon spec run"):
            _parse_config({**MINIMAL, "target_repo": "git@example.com:app/repo.git"})

    def test_invalid_provider_raises(self) -> None:
        with pytest.raises(ValidationError, match="provider"):
            _parse_config({**MINIMAL, "provider": "kubernetes"})

    def test_invalid_container_cli_raises(self) -> None:
        with pytest.raises(ValidationError, match="container_cli"):
            _parse_config({**MINIMAL, "container_cli": "nerdctl"})

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

    def test_stacks_selected_must_be_list(self) -> None:
        with pytest.raises(ValidationError, match="stacks.selected"):
            _parse_config({**MINIMAL, "stacks": {"selected": "statsperform-playbook"}})

    def test_stacks_selected_rejects_empty_ids(self) -> None:
        with pytest.raises(ValidationError, match="stacks.selected"):
            _parse_config({**MINIMAL, "stacks": {"selected": ["statsperform-playbook", " "]}})

    def test_stack_target_archetypes_must_be_list(self) -> None:
        with pytest.raises(ValidationError, match="stacks.target_archetypes"):
            _parse_config({**MINIMAL, "stacks": {"target_archetypes": "web_app"}})


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
    def test_project_config_applied(self, tmp_path: Path) -> None:
        config_dir = _echelon_dir(tmp_path)
        _write_yaml(config_dir / "config.yml", {"harness": {
            **MINIMAL,
            "resource_limits": {"memory": "8g"},
        }})
        config = load_config(tmp_path)
        assert config.resource_limits.memory == "8g"
        # Defaults still fill unspecified sub-fields
        assert config.resource_limits.cpu == 2.0

    def test_top_level_stacks_in_unified_config_inherited_by_harness(self, tmp_path: Path) -> None:
        config_dir = _echelon_dir(tmp_path)
        _write_yaml(config_dir / "config.yml", {
            "stacks": {
                "selected": ["statsperform-playbook"],
            },
            "harness": {
                **MINIMAL,
            },
        })

        config = load_config(tmp_path)

        assert config.stacks.selected == ["statsperform-playbook"]

    def test_harness_stacks_override_top_level_stacks(self, tmp_path: Path) -> None:
        config_dir = _echelon_dir(tmp_path)
        _write_yaml(config_dir / "config.yml", {
            "stacks": {
                "selected": ["top-level-stack"],
            },
            "harness": {
                **MINIMAL,
                "stacks": {
                    "selected": ["harness-stack"],
                },
            },
        })

        config = load_config(tmp_path)

        assert config.stacks.selected == ["harness-stack"]

    def test_local_config_overrides_project(self, tmp_path: Path) -> None:
        config_dir = _echelon_dir(tmp_path)
        _write_yaml(config_dir / "config.yml", {"harness": {**MINIMAL, "buffer_limit_bytes": 5_000_000}})
        _write_yaml(config_dir / "local.yml", {"harness": {"buffer_limit_bytes": 1_000_000}})
        config = load_config(tmp_path)
        assert config.buffer_limit_bytes == 1_000_000

    def test_env_vars_override_local(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Env var parsing splits on '_' as nesting separators (same as ConfigManager),
        # so only single-word top-level keys round-trip cleanly via env vars.
        # ECHELON_HARNESS_PROVIDER → {"provider": "e2b"}
        config_dir = _echelon_dir(tmp_path)
        _write_yaml(config_dir / "config.yml", {"harness": MINIMAL})
        _write_yaml(config_dir / "local.yml", {"harness": {"provider": "docker"}})
        monkeypatch.setenv("ECHELON_HARNESS_PROVIDER", "e2b")
        config = load_config(tmp_path)
        assert config.provider == "e2b"

    def test_legacy_env_var_reports_exact_echelon_replacement(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SPECKIT_HARNESS_PROVIDER", "e2b")

        with pytest.raises(
            ValidationError,
            match="SPECKIT_HARNESS_PROVIDER.*ECHELON_HARNESS_PROVIDER",
        ):
            load_config(tmp_path)

    def test_missing_optional_files_are_skipped(self, tmp_path: Path) -> None:
        config_dir = _echelon_dir(tmp_path)
        # Only project config — no local, no env vars
        _write_yaml(config_dir / "config.yml", {"harness": MINIMAL})
        config = load_config(tmp_path)
        assert config.provider == "docker"

    def test_defaults_cwd_used_when_no_project_root(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        config_dir = _echelon_dir(tmp_path)
        _write_yaml(config_dir / "config.yml", {"harness": MINIMAL})
        monkeypatch.chdir(tmp_path)
        config = load_config()  # no project_root — falls back to cwd
        assert config.target_repo == ""

    def test_canonical_project_config_applied(self, tmp_path: Path) -> None:
        cfg_dir = _echelon_dir(tmp_path)
        _write_yaml(cfg_dir / "config.yml", {"harness": {
            **MINIMAL,
            "resource_limits": {"memory": "6g"},
        }})

        config = load_config(tmp_path)

        assert config.target_repo == ""
        assert config.resource_limits.memory == "6g"

    def test_canonical_project_config_wins_over_legacy(self, tmp_path: Path) -> None:
        ext = _ext_dir(tmp_path)
        cfg_dir = _echelon_dir(tmp_path)
        _write_yaml(ext / "echelon-config.yml", {"harness": {
            **MINIMAL,
            "provider": "e2b",
        }})
        _write_yaml(cfg_dir / "config.yml", {"harness": {
            **MINIMAL,
            "provider": "docker",
        }})

        config = load_config(tmp_path)

        assert config.provider == "docker"

    def test_canonical_local_config_overrides_canonical_project(self, tmp_path: Path) -> None:
        cfg_dir = _echelon_dir(tmp_path)
        _write_yaml(cfg_dir / "config.yml", {"harness": {
            **MINIMAL,
            "buffer_limit_bytes": 5_000_000,
        }})
        _write_yaml(cfg_dir / "local.yml", {"harness": {
            "buffer_limit_bytes": 1_000_000,
        }})

        config = load_config(tmp_path)

        assert config.buffer_limit_bytes == 1_000_000

    def test_full_resolved_config_uses_canonical_config(self, tmp_path: Path) -> None:
        cfg_dir = _echelon_dir(tmp_path)
        _write_yaml(cfg_dir / "config.yml", {
            "analysis": {"enabled": True},
            "harness": MINIMAL,
        })

        config = get_full_resolved_config(tmp_path)

        assert config["analysis"]["enabled"] is True
        assert config["harness"]["provider"] == "docker"


@pytest.mark.unit
class TestVisualTestsConfig:
    def test_visual_tests_defaults(self) -> None:
        """visual_tests block absent → all defaults applied."""
        cfg = _parse_config(MINIMAL)
        assert cfg.visual_tests.enabled is False
        assert cfg.visual_tests.serve_command == "npm run preview"
        assert cfg.visual_tests.test_command == "npx playwright test --reporter=json"
        assert cfg.visual_tests.timeout_ms == 300_000
        assert cfg.visual_tests.screenshot_dir == "playwright-report"
        assert cfg.visual_tests.max_iterations == 3

    def test_visual_tests_enabled_flag(self) -> None:
        """visual_tests.enabled and serve_command can be overridden."""
        cfg = _parse_config({
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
    config = _parse_config(MINIMAL)
    assert config.llm.timeout_ms == 43_200_000
    assert config.llm.config_dir is None
    assert config.llm.codex_inherit_user_config is False
    assert isinstance(config.llm.re_v2_baseline, ReV2BaselineConfig)
    assert config.llm.re_v2_baseline.model_revision is None


def test_llm_re_v2_baseline_capability_config_is_typed() -> None:
    config = _parse_config({
        "provider": "docker",
        "llm": {
            "cli": "openai-compatible",
            "base_url": "https://api.example.test/v1",
            "model": "gpt-example",
            "re_v2_baseline": {
                "model_revision": "gpt-example-2026-08-01",
                "revision_authority": "provider_resolved_revision",
                "provider_context_tokens": 200000,
                "reasoning_effort": "high",
                "top_p": "1.0",
                "seed": 42,
                "request_path": "/chat/completions",
                "api_protocol_version": "1",
                "non_secret_headers": [
                    {"name": "openai-organization", "value": "org-example"},
                ],
                "fixed_framing_byte_upper_bound": 4096,
            },
        },
    })

    capability = config.llm.re_v2_baseline
    assert capability.model_revision == "gpt-example-2026-08-01"
    assert capability.provider_context_tokens == 200000
    assert capability.top_p == "1.0"
    assert capability.seed == 42
    assert [(header.name, header.value) for header in capability.non_secret_headers] == [
        ("openai-organization", "org-example"),
    ]


def test_llm_re_v2_baseline_rejects_non_mapping_headers() -> None:
    with pytest.raises(ValidationError, match="non_secret_headers"):
        _parse_config({
            "provider": "docker",
            "llm": {"re_v2_baseline": {"non_secret_headers": ["x-route: one"]}},
        })


def test_llm_config_dir_set():
    """LlmConfig.config_dir is read from config."""
    config = _parse_config({
        "provider": "docker",
        "llm": {"config_dir": "/home/user/.config/claude-work"},
    })
    assert config.llm.config_dir == "/home/user/.config/claude-work"


def test_llm_codex_user_config_can_be_inherited_explicitly():
    config = _parse_config({
        "provider": "docker",
        "llm": {"cli": "codex", "codex_inherit_user_config": True},
    })

    assert config.llm.codex_inherit_user_config is True


def test_llm_timeout_ms_set():
    """LlmConfig.timeout_ms is read from config."""
    config = _parse_config({
        "provider": "docker",
        "llm": {"timeout_ms": 600_000},
    })
    assert config.llm.timeout_ms == 600_000


def test_llm_openai_compatible_config_parsed() -> None:
    config = _parse_config({
        "provider": "docker",
        "llm": {
            "cli": "openai-compatible",
            "base_url": "http://127.0.0.1:8000/v1",
            "model": "local-model",
            "api_key_env": "LOCAL_LLM_API_KEY",
            "api_key_file": "~/.omlx_token",
            "temperature": 0.2,
            "max_tokens": 8192,
            "features": {
                "streaming": False,
                "json_mode": True,
                "structured_outputs": False,
                "tool_calls": False,
                "reasoning_content": "auto",
                "reasoning_effort": False,
            },
        },
    })

    assert config.llm.cli == "openai-compatible"
    assert config.llm.base_url == "http://127.0.0.1:8000/v1"
    assert config.llm.model == "local-model"
    assert config.llm.api_key_env == "LOCAL_LLM_API_KEY"
    assert config.llm.api_key_file == "~/.omlx_token"
    assert config.llm.temperature == 0.2
    assert config.llm.max_tokens == 8192
    assert config.llm.features == {
        "streaming": False,
        "json_mode": True,
        "structured_outputs": False,
        "tool_calls": False,
        "reasoning_content": "auto",
        "reasoning_effort": False,
    }


def test_llm_openai_compatible_requires_base_url() -> None:
    with pytest.raises(ValidationError, match="base_url"):
        _parse_config({
            "provider": "docker",
            "llm": {
                "cli": "openai-compatible",
                "model": "local-model",
            },
        })


def test_llm_openai_compatible_requires_model() -> None:
    with pytest.raises(ValidationError, match="model"):
        _parse_config({
            "provider": "docker",
            "llm": {
                "cli": "openai-compatible",
                "base_url": "http://127.0.0.1:8000/v1",
            },
        })


def test_llm_tool_policy_defaults_deny_unsafe_host_execution() -> None:
    config = _parse_config(MINIMAL)

    assert config.llm.tool_policy.file_boundary == "workspace"
    assert config.llm.tool_policy.network_boundary == "harness_allowlist"
    assert config.llm.tool_policy.allow_unsafe_host_execution is False


def test_llm_tool_policy_config_override_requires_approval_metadata() -> None:
    with pytest.raises(ValidationError, match="approval_reason"):
        _parse_config({
            "provider": "docker",
            "llm": {
                "tool_policy": {
                    "allow_unsafe_host_execution": True,
                },
            },
        })


def test_llm_tool_policy_config_override_accepts_approved_unsafe_mode() -> None:
    config = _parse_config({
        "provider": "docker",
        "llm": {
            "tool_policy": {
                "file_boundary": "workspace",
                "network_boundary": "harness_allowlist",
                "allow_unsafe_host_execution": True,
                "approval_reason": "Operator approved disposable worktree after sandbox review.",
            },
        },
    })

    assert config.llm.tool_policy.allow_unsafe_host_execution is True
    assert "disposable worktree" in config.llm.tool_policy.approval_reason


def test_load_config_inherits_top_level_llm_defaults_into_harness_section(
    tmp_path: Path,
) -> None:
    config_file = tmp_path / ".echelon" / "config.yml"
    config_file.parent.mkdir(parents=True)
    config_file.write_text(
        "llm:\n"
        "  tool_policy:\n"
        "    allow_unsafe_host_execution: true\n"
        "    approval_reason: Operator approved disposable harness worktree.\n"
        "harness:\n"
        "  provider: docker\n"
        "  llm:\n"
        "    cli: claude\n",
        encoding="utf-8",
    )

    config = load_config(tmp_path)

    assert config.llm.cli == "claude"
    assert config.llm.tool_policy.allow_unsafe_host_execution is True
    assert "disposable harness worktree" in config.llm.tool_policy.approval_reason


def test_load_config_harness_llm_overrides_top_level_llm_defaults(tmp_path: Path) -> None:
    config_file = tmp_path / ".echelon" / "config.yml"
    config_file.parent.mkdir(parents=True)
    config_file.write_text(
        "llm:\n"
        "  cli: claude\n"
        "  timeout_ms: 600000\n"
        "harness:\n"
        "  provider: docker\n"
        "  llm:\n"
        "    cli: codex\n",
        encoding="utf-8",
    )

    config = load_config(tmp_path)

    assert config.llm.cli == "codex"
    assert config.llm.timeout_ms == 600_000
