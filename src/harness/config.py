"""Config loading and validation for the harness execution substrate.

Reads the ``harness:`` section of the unified echelon config file.
Implements the spec-kit 4-level config cascade by delegating to
``specify_cli.extensions.ConfigManager`` when available:

  1. Defaults   — extension.yml ``config.defaults``                   (bundled)
  2. Project    — ``.specify/extensions/echelon/echelon-config.yml``         (committed)
  3. Local      — ``.specify/extensions/echelon/local-config.yml``    (gitignored)
  4. Env vars   — ``SPECKIT_HARNESS_<SECTION>_<KEY>``                 (CI/secrets)

Layers are deep-merged in precedence order; required fields
(``target_repo``, ``target_default_branch``, ``provider``) must be
present after merging.

Per ADR-001: Python for orchestration. Per ADR-002: JSON/YAML for config.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

try:
    from specify_cli.extensions import ConfigManager as _SpecKitConfigManager
except ImportError:
    _SpecKitConfigManager = None  # type: ignore[assignment, misc]


# ---------------------------------------------------------------------------
# Validation error
# ---------------------------------------------------------------------------

class ValidationError(Exception):
    """Raised when config validation fails."""

    def __init__(self, message: str, *, field_path: Optional[str] = None) -> None:
        self.field_path = field_path
        super().__init__(message)

    def __str__(self) -> str:
        base = super().__str__()
        if self.field_path:
            return f"{base} (field: {self.field_path})"
        return base


# ---------------------------------------------------------------------------
# Default values (must mirror extension.yml config.defaults)
# ---------------------------------------------------------------------------

DEFAULT_RESOURCE_LIMITS = {
    "memory": "4g",
    "cpu": 2.0,
    "pids": 256,
    "storage": "10g",
}

DEFAULT_NETWORK_ALLOWLIST = [
    "registry.npmjs.org",
    "pypi.org",
    "files.pythonhosted.org",
    "proxy.golang.org",
    "crates.io",
    "static.crates.io",
    "repo1.maven.org",
    "playwright.azureedge.net",
    "cdn.playwright.dev",
]

VALID_PROVIDERS = {"docker", "e2b", "modal", "daytona"}
VALID_CONTAINER_CLIS = {"docker", "podman"}
VALID_LLM_CLIS = {"claude", "copilot", "opencode", "codex"}
VALID_PR_HOSTS = {"github", "gitlab", "none"}
VALID_FULFILLMENT_REFRESH_POLICIES = {
    "every_slice",
    "milestone",
    "convergence_only",
    "scoped",
}

# Simple semver range pattern: supports ^, ~, >=, <=, =, -, x ranges
SEMVER_RANGE_PATTERN = re.compile(
    r"^[\^~>=<!\s\d.*xX|,-]+$"
)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ResourceLimits:
    """Resource limits for sandbox containers."""
    memory: str = "4g"
    cpu: float = 2.0
    pids: int = 256
    storage: str = "10g"


@dataclass
class NetworkConfig:
    """Network policy configuration."""
    allowlist: List[str] = field(default_factory=lambda: list(DEFAULT_NETWORK_ALLOWLIST))
    proxy_image: str = "ubuntu/squid:latest"


@dataclass
class GCConfig:
    """Garbage collection configuration."""
    worktree_max_age_hours: int = 24
    container_max_age_hours: int = 1
    backup_max_age_days: int = 7


@dataclass
class VisualTestsConfig:
    """Configuration for Phase 2 visual verification loop."""
    enabled: bool = False
    serve_command: str = "npm run preview"
    test_command: str = "npx playwright test --reporter=json"
    timeout_ms: int = 300_000
    screenshot_dir: str = "playwright-report"
    max_iterations: int = 3


@dataclass
class AppRuntimeConfig:
    """Docker-backed app runtime profile for browser/screenshot checks."""
    enabled: bool = False
    mode: str = ""
    app: Optional[str] = None
    url: Optional[str] = None
    compose_file: Optional[str] = None
    service: Optional[str] = None
    dockerfile: Optional[str] = None
    container_port: Optional[int] = None
    health_check: Optional[str] = None
    start_command: Optional[str] = None
    setup_commands: List[str] = field(default_factory=list)
    start_commands: List[str] = field(default_factory=list)
    stop_commands: List[str] = field(default_factory=list)
    readiness_timeout_ms: int = 120_000


@dataclass
class LlmConfig:
    """Configuration for the LLM CLI provider (claude -p or copilot -p subprocess)."""
    enabled: bool = False              # true when llm section is present in config
    cli: str = "claude"               # "claude", "copilot", or "opencode"
    config_dir: Optional[str] = None   # passed as CLAUDE_CONFIG_DIR env var (claude only)
    timeout_ms: int = 10_800_000       # 3 hours per autonomous build invocation


@dataclass
class ReviewLoopConfig:
    """Configuration for Phase 3 automated PR review cycle."""
    enabled: bool = False
    poll_interval_minutes: int = 10        # short default — sized for bot reviewers
    merge_timeout_hours: float = 1.0       # silence window since last comment → merge
    reviewers: List[str] = field(default_factory=list)
    require_approval: bool = False         # True → only merge on explicit APPROVED
    max_fix_iterations: int = 10
    resolve_threads: bool = True
    adjacent_line_threshold: int = 10      # comments within N lines → same fix group


@dataclass
class FulfillmentConfig:
    """Configuration for expensive verify-spec fulfillment refreshes."""
    refresh_policy: str = "milestone"


@dataclass
class HarnessConfig:
    """Complete harness configuration."""
    target_repo: str
    target_default_branch: str
    provider: str

    # Optional fields with defaults
    container_cli: str = "docker"
    base_image: Optional[str] = None
    image_digest_pin: Optional[str] = None
    resource_limits: ResourceLimits = field(default_factory=ResourceLimits)
    network: NetworkConfig = field(default_factory=NetworkConfig)
    buffer_limit_bytes: int = 10_485_760  # 10 MB
    gc: GCConfig = field(default_factory=GCConfig)
    ci_skip_tag: str = "[skip ci]"
    ci_skip_enabled: bool = True
    echelon_version_range: Optional[str] = None
    secrets_env_file: str = "secrets.env"
    devcontainer_subset: List[str] = field(default_factory=lambda: [
        "image", "build.dockerfile", "features",
        "forwardPorts", "containerEnv", "postCreateCommand",
    ])
    bind_mount_ack: bool = False
    pr_host: str = "none"
    visual_tests: VisualTestsConfig = field(default_factory=VisualTestsConfig)
    app: AppRuntimeConfig = field(default_factory=AppRuntimeConfig)
    llm: LlmConfig = field(default_factory=LlmConfig)
    review_loop: ReviewLoopConfig = field(default_factory=ReviewLoopConfig)
    fulfillment: FulfillmentConfig = field(default_factory=FulfillmentConfig)
    verify_command: Optional[str] = None


# ---------------------------------------------------------------------------
# Internal: YAML helpers and inline ConfigManager fallback
# ---------------------------------------------------------------------------

def _parse_yaml(text: str) -> Dict[str, Any]:
    if yaml is not None:
        return yaml.safe_load(text) or {}
    raise ImportError(
        "PyYAML is required for config loading. Install with: pip install pyyaml"
    )


def _load_yaml_file(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return _parse_yaml(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively deep-merge *override* onto *base* (same logic as ConfigManager)."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def _env_config() -> Dict[str, Any]:
    """Build config dict from ``SPECKIT_HARNESS_*`` environment variables."""
    result: Dict[str, Any] = {}
    prefix = "SPECKIT_HARNESS_"
    for key, value in os.environ.items():
        if not key.startswith(prefix):
            continue
        parts = key[len(prefix):].lower().split("_")
        node = result
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
    return result


def _get_merged_config(project_root: Path) -> Dict[str, Any]:
    """Return the fully merged config dict using ConfigManager if available."""
    if _SpecKitConfigManager is not None:
        mgr = _SpecKitConfigManager(project_root=project_root, extension_id="echelon")
        full = mgr.get_config()
        if isinstance(full.get("harness"), dict):
            harness = dict(full["harness"])
            if "verify_command" in full and "verify_command" not in harness:
                harness["verify_command"] = full["verify_command"]
            return harness
        return full

    # Inline fallback — same 4-layer logic as ConfigManager.
    # Layer 1 (extension.yml defaults) is not read here: extension.yml is not
    # installed alongside the project configs, so dataclass field defaults are
    # the effective layer 1, identical to ConfigManager behaviour in practice.
    ext_dir = project_root / ".specify" / "extensions" / "echelon"
    config: Dict[str, Any] = {}

    # Layer 2: project config — harness: section of echelon-config.yml
    raw = _load_yaml_file(ext_dir / "echelon-config.yml")
    config = _merge(config, raw.get("harness", raw))
    if "verify_command" in raw and "verify_command" not in config:
        config["verify_command"] = raw["verify_command"]

    # Layer 3: local config (gitignored)
    raw_local = _load_yaml_file(ext_dir / "local-config.yml")
    config = _merge(config, raw_local.get("harness", raw_local))

    # Layer 4: environment variables
    config = _merge(config, _env_config())

    return config


# ---------------------------------------------------------------------------
# Internal: field validation and sub-section parsers
# ---------------------------------------------------------------------------

def _validate_required(data: Dict[str, Any], field_name: str) -> str:
    value = data.get(field_name)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValidationError(
            f"Required field '{field_name}' is missing or empty",
            field_path=field_name,
        )
    return str(value)


def _validate_provider(provider: str) -> str:
    if provider not in VALID_PROVIDERS:
        raise ValidationError(
            f"Invalid provider '{provider}'. Must be one of: {sorted(VALID_PROVIDERS)}",
            field_path="provider",
        )
    return provider


def _validate_container_cli(container_cli: str) -> str:
    if container_cli not in VALID_CONTAINER_CLIS:
        raise ValidationError(
            f"Invalid container_cli '{container_cli}'. Must be one of: {sorted(VALID_CONTAINER_CLIS)}",
            field_path="container_cli",
        )
    return container_cli


def _validate_llm_cli(cli: str) -> str:
    if cli not in VALID_LLM_CLIS:
        raise ValidationError(
            f"Invalid LLM CLI '{cli}'. Must be one of: {sorted(VALID_LLM_CLIS)}",
            field_path="llm.cli",
        )
    return cli


def _validate_semver_range(version_range: str) -> str:
    if not SEMVER_RANGE_PATTERN.match(version_range):
        raise ValidationError(
            f"Invalid semver range '{version_range}'",
            field_path="echelon_version_range",
        )
    return version_range


def _parse_resource_limits(data: Dict[str, Any]) -> ResourceLimits:
    raw = data.get("resource_limits", {})
    if not isinstance(raw, dict):
        raw = {}
    return ResourceLimits(
        memory=str(raw.get("memory", DEFAULT_RESOURCE_LIMITS["memory"])),
        cpu=float(raw.get("cpu", DEFAULT_RESOURCE_LIMITS["cpu"])),
        pids=int(raw.get("pids", DEFAULT_RESOURCE_LIMITS["pids"])),
        storage=str(raw.get("storage", DEFAULT_RESOURCE_LIMITS["storage"])),
    )


def _parse_network(data: Dict[str, Any]) -> NetworkConfig:
    raw = data.get("network", {})
    if not isinstance(raw, dict):
        raw = {}
    allowlist = raw.get("allowlist", list(DEFAULT_NETWORK_ALLOWLIST))
    if not isinstance(allowlist, list):
        allowlist = list(DEFAULT_NETWORK_ALLOWLIST)
    return NetworkConfig(
        allowlist=allowlist,
        proxy_image=str(raw.get("proxy_image", "ubuntu/squid:latest")),
    )


def _parse_gc(data: Dict[str, Any]) -> GCConfig:
    raw = data.get("gc", {})
    if not isinstance(raw, dict):
        raw = {}
    return GCConfig(
        worktree_max_age_hours=int(raw.get("worktree_max_age_hours", 24)),
        container_max_age_hours=int(raw.get("container_max_age_hours", 1)),
        backup_max_age_days=int(raw.get("backup_max_age_days", 7)),
    )


def _parse_visual_tests(data: Dict[str, Any]) -> VisualTestsConfig:
    raw = data.get("visual_tests", {})
    if not isinstance(raw, dict):
        raw = {}
    return VisualTestsConfig(
        enabled=bool(raw.get("enabled", False)),
        serve_command=str(raw.get("serve_command", "npm run preview")),
        test_command=str(raw.get("test_command", "npx playwright test --reporter=json")),
        timeout_ms=int(raw.get("timeout_ms", 300_000)),
        screenshot_dir=str(raw.get("screenshot_dir", "playwright-report")),
        max_iterations=int(raw.get("max_iterations", 3)),
    )


def _parse_review_loop(data: Dict[str, Any]) -> ReviewLoopConfig:
    raw = data.get("review_loop", {})
    if not isinstance(raw, dict):
        raw = {}
    reviewers_raw = raw.get("reviewers", [])
    reviewers = [str(r) for r in (reviewers_raw if isinstance(reviewers_raw, list) else [])]
    return ReviewLoopConfig(
        enabled=bool(raw.get("enabled", False)),
        poll_interval_minutes=int(raw.get("poll_interval_minutes", 10)),
        merge_timeout_hours=float(raw.get("merge_timeout_hours", 1.0)),
        reviewers=reviewers,
        require_approval=bool(raw.get("require_approval", False)),
        max_fix_iterations=int(raw.get("max_fix_iterations", 10)),
        resolve_threads=bool(raw.get("resolve_threads", True)),
        adjacent_line_threshold=int(raw.get("adjacent_line_threshold", 10)),
    )


def _parse_command_list(value: Any) -> List[str]:
    if isinstance(value, str):
        command = value.strip()
        return [command] if command else []
    if isinstance(value, list):
        return [str(command) for command in value if str(command).strip()]
    return []


def _parse_app_runtime(data: Dict[str, Any]) -> AppRuntimeConfig:
    raw = data.get("app", {})
    if not isinstance(raw, dict):
        raw = {}

    container_port = raw.get("container_port")
    if container_port is not None:
        container_port = int(container_port)

    return AppRuntimeConfig(
        enabled=bool(raw.get("enabled", False)),
        mode=str(raw.get("mode", "")),
        app=raw.get("app") or None,
        url=raw.get("url") or None,
        compose_file=raw.get("compose_file") or None,
        service=raw.get("service") or None,
        dockerfile=raw.get("dockerfile") or None,
        container_port=container_port,
        health_check=raw.get("health_check") or None,
        start_command=raw.get("start_command") or None,
        setup_commands=_parse_command_list(raw.get("setup_commands", [])),
        start_commands=_parse_command_list(raw.get("start_commands", [])),
        stop_commands=_parse_command_list(raw.get("stop_commands", [])),
        readiness_timeout_ms=int(raw.get("readiness_timeout_ms", 120_000)),
    )


def _parse_llm(data: Dict[str, Any]) -> LlmConfig:
    raw = data.get("llm", {})
    if not isinstance(raw, dict):
        raw = {}
    return LlmConfig(
        enabled="llm" in data,
        cli=_validate_llm_cli(str(raw.get("cli", "claude"))),
        config_dir=str(raw["config_dir"]) if raw.get("config_dir") else None,
        timeout_ms=int(raw.get("timeout_ms", 10_800_000)),
    )


def _parse_fulfillment(data: Dict[str, Any]) -> FulfillmentConfig:
    raw = data.get("fulfillment", {})
    if not isinstance(raw, dict):
        raw = {}
    refresh_policy = str(raw.get("refresh_policy", "milestone"))
    if refresh_policy not in VALID_FULFILLMENT_REFRESH_POLICIES:
        raise ValidationError(
            f"Invalid fulfillment refresh_policy '{refresh_policy}'. "
            f"Must be one of: {sorted(VALID_FULFILLMENT_REFRESH_POLICIES)}",
            field_path="fulfillment.refresh_policy",
        )
    return FulfillmentConfig(refresh_policy=refresh_policy)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _parse_config(data: Dict[str, Any], squad_only: bool = False) -> HarnessConfig:
    """Validate and construct a HarnessConfig from an already-merged dict.

    Args:
        data: Merged config dict.
        squad_only: When True, skip validation of build-harness-only required
            fields (target_repo, target_default_branch, provider). The squad
            run (Phase A) never uses these fields — they are only needed for
            the build harness (Phase B / echelon harness run).

    Raises:
        ValidationError: If required fields are missing or invalid after merging.
    """
    if squad_only:
        target_repo = data.get("target_repo", "")
        target_default_branch = data.get("target_default_branch", "main")
        provider = data.get("provider", "github")
        if provider:
            try:
                provider = _validate_provider(provider)
            except ValidationError:
                provider = "github"
    else:
        target_repo = _validate_required(data, "target_repo")
        target_default_branch = _validate_required(data, "target_default_branch")
        provider = _validate_provider(_validate_required(data, "provider"))

    echelon_version_range = data.get("echelon_version_range")
    if echelon_version_range is not None:
        _validate_semver_range(str(echelon_version_range))
        echelon_version_range = str(echelon_version_range)

    pr_host = data.get("pr_host", "none")
    if pr_host not in VALID_PR_HOSTS:
        pr_host = "none"

    return HarnessConfig(
        target_repo=target_repo,
        target_default_branch=target_default_branch,
        provider=provider,
        container_cli=_validate_container_cli(str(data.get("container_cli", "docker"))),
        base_image=data.get("base_image"),
        image_digest_pin=data.get("image_digest_pin"),
        resource_limits=_parse_resource_limits(data),
        network=_parse_network(data),
        buffer_limit_bytes=int(data.get("buffer_limit_bytes", 10_485_760)),
        gc=_parse_gc(data),
        ci_skip_tag=str(data.get("ci_skip_tag", "[skip ci]")),
        ci_skip_enabled=bool(data.get("ci_skip_enabled", True)),
        echelon_version_range=echelon_version_range,
        secrets_env_file=str(data.get("secrets_env_file", "secrets.env")),
        devcontainer_subset=data.get("devcontainer_subset", [
            "image", "build.dockerfile", "features",
            "forwardPorts", "containerEnv", "postCreateCommand",
        ]),
        bind_mount_ack=bool(data.get("bind_mount_ack", False)),
        pr_host=pr_host,
        visual_tests=_parse_visual_tests(data),
        app=_parse_app_runtime(data),
        llm=_parse_llm(data),
        review_loop=_parse_review_loop(data),
        fulfillment=_parse_fulfillment(data),
        verify_command=data.get("verify_command") or None,
    )


def load_config(
    project_root: Optional[Path] = None,
    squad_only: bool = False,
) -> HarnessConfig:
    """Load and validate harness configuration using the spec-kit 4-level cascade.

    Delegates to ``specify_cli.extensions.ConfigManager`` when available;
    falls back to an inline implementation of the same merge logic.

    Args:
        project_root: Root of the spec-kit project. Defaults to ``Path.cwd()``.
        squad_only: When True, skip validation of build-harness-only required
            fields. Pass True from the squad run (echelon run / Phase A) which
            only needs llm + budget config and never touches target_repo etc.

    Returns:
        Validated ``HarnessConfig`` dataclass.

    Raises:
        ValidationError: If required fields are missing or invalid after merging.
    """
    if project_root is None:
        project_root = Path.cwd()

    data = _get_merged_config(project_root)
    return _parse_config(data, squad_only=squad_only)


def get_full_resolved_config(project_root: Optional[Path] = None) -> Dict[str, Any]:
    """Return the full resolved config dict for all sections (not just harness:).

    Use this when you need access to non-harness sections such as ``analysis:``
    or ``endocrine:``.  Goes through the same 4-level cascade as ``load_config``:
    ConfigManager (spec-kit) when available, otherwise inline file merge.
    """
    if project_root is None:
        project_root = Path.cwd()

    if _SpecKitConfigManager is not None:
        mgr = _SpecKitConfigManager(project_root=project_root, extension_id="echelon")
        return mgr.get_config()

    # Inline fallback: merge echelon-config.yml + local-config.yml (full dicts).
    ext_dir = project_root / ".specify" / "extensions" / "echelon"
    full: Dict[str, Any] = {}
    full = _merge(full, _load_yaml_file(ext_dir / "echelon-config.yml"))
    full = _merge(full, _load_yaml_file(ext_dir / "local-config.yml"))
    return full
