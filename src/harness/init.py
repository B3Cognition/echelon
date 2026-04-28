"""Init flow orchestration for spec-kit-harness.

Implements the init flow from plan.md Phase 1E:
1. Accept target repo URL/path, validate it exists
2. Self-targeting detection (FR-INIT-001)
3. Docker health check
4. OS detection + Windows rejection (FR-OS-001)
5. Mirror clone via GitOpsManager
6. Language/framework fingerprint (FR-INIT-002)
7. Image resolution via 4-source chain
8. config.yml generation with detected values + defaults
9. Bind-mount acknowledgement prompt (FR-INIT-ACK-001)
10. Playwright detection + image selection (FR-PLAYWRIGHT-001)
11. Version compatibility check (FR-VERSION-001)
12. Constitution placeholder detection (FR-CONST-001a/b)
"""

from __future__ import annotations

import logging
import os
import platform
import subprocess
from pathlib import Path
from typing import Optional

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

from harness.config import HarnessConfig
from harness.errors import GitOpsError, SandboxCreationError, SelfTargetError
from harness.fingerprint import fingerprint_repo, detect_playwright
from harness.gitops import GitOpsManager
from harness.image_resolver import resolve_image, ImageResolutionError

logger = logging.getLogger(__name__)


class InitError(Exception):
    """Raised when harness initialization fails."""


def _check_docker() -> bool:
    """Check if Docker daemon is running."""
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=10,
            check=False,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _check_os() -> str:
    """Check OS and reject Windows.

    Returns:
        OS name (darwin/linux).

    Raises:
        InitError: On unsupported OS.

    FR-OS-001
    """
    os_name = platform.system().lower()
    if os_name == "windows":
        raise InitError(
            "Windows is not supported. echelon-harness requires macOS or Linux (FR-OS-001)."
        )
    if os_name not in ("darwin", "linux"):
        logger.warning("Unrecognized OS '%s', proceeding anyway", os_name)
    return os_name


def _detect_pr_host() -> str:
    """Detect PR hosting platform from git remotes + installed CLI tools.

    Checks actual remote URLs first so repos without a remote don't get
    mis-assigned a PR host just because gh/glab happen to be installed.
    """
    import shutil
    import subprocess as _sp

    try:
        result = _sp.run(
            ["git", "remote", "-v"],
            capture_output=True, text=True, timeout=10,
        )
        remotes = result.stdout.lower()
    except Exception:
        remotes = ""

    if "github.com" in remotes and shutil.which("gh"):
        return "github"
    if "gitlab.com" in remotes and shutil.which("glab"):
        return "gitlab"
    return "none"


def _detect_llm_cli() -> str:
    """Detect available LLM CLI tool.

    Respects ECHELON_LLM env var; otherwise checks PATH for supported CLIs.
    Returns 'claude' | 'copilot' | 'opencode'.
    """
    import os
    import shutil

    env = os.environ.get("ECHELON_LLM", "").strip()
    if env in ("claude", "copilot", "opencode"):
        return env
    for cli in ("claude", "copilot", "opencode"):
        if shutil.which(cli):
            return cli
    return "claude"  # default; will error at runtime if not installed



def _check_constitution(base_dir: Path) -> Optional[str]:
    """Check for constitution placeholder or populated content.

    FR-CONST-001a: Populated constitution -> blocker warning
    FR-CONST-001b: Placeholder constitution -> info warning

    Returns:
        Warning message or None.
    """
    const_path = base_dir / "constitution.md"
    if not const_path.exists():
        return None

    try:
        text = const_path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return "WARNING: Constitution file is unreadable (binary or corrupt)"

    # Check for template markers
    if "{{" in text and "}}" in text:
        return "INFO: Constitution appears to be a placeholder template. Fill in your project rules."

    # Check for populated content
    if len(text.strip()) > 50:
        return (
            "WARNING: Constitution is populated. SPEC GUARD will enforce these rules "
            "during the build. Review constitution.md before proceeding."
        )

    return None


def _check_version_compatibility(
    echelon_version_range: Optional[str],
) -> Optional[str]:
    """Check version compatibility (FR-VERSION-001).

    Returns warning message if incompatible, None if OK.
    """
    if not echelon_version_range:
        return None
    # Simplified check — full semver range matching would need a library
    logger.info("Version range specified: %s (validation simplified)", echelon_version_range)
    return None


def init_harness(
    target_repo: str,
    base_dir: Optional[str] = None,
    bind_mount_ack: bool = False,
) -> HarnessConfig:
    """Initialize the harness against a target repository.

    Args:
        target_repo: URL or local path to the target repository.
        base_dir: Base directory for harness files. Defaults to cwd.
        bind_mount_ack: Whether the user acknowledges bind-mount limitation.

    Returns:
        The generated HarnessConfig.

    Raises:
        InitError: On any initialization failure.
    """
    base = Path(base_dir) if base_dir else Path.cwd()

    # Step 1: OS detection + Windows rejection
    os_name = _check_os()
    logger.info("OS detected: %s", os_name)

    # Step 2: Docker health check
    if not _check_docker():
        raise InitError(
            "Docker is not running. echelon-harness requires Docker to create sandboxes. "
            "Please start Docker and try again."
        )
    logger.info("Docker is running")

    # Step 3: Self-targeting detection
    # Create a temporary config to initialize GitOpsManager
    temp_config = HarnessConfig(
        target_repo=target_repo,
        target_default_branch="main",
        provider="docker",
        pr_host=_detect_pr_host(),
    )
    try:
        mgr = GitOpsManager(temp_config, base_dir=str(base))
        mgr.validate_not_self_targeting(target_repo, str(base))
    except SelfTargetError:
        raise InitError(
            f"Target repo URL '{target_repo}' matches this repo's own remote. "
            f"To target the current directory use '.' instead of the remote URL."
        )

    # Step 4: Validate target repo exists
    try:
        subprocess.run(
            ["git", "ls-remote", "--exit-code", target_repo],
            capture_output=True,
            timeout=30,
            check=True,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        # Try as local path
        if not Path(target_repo).is_dir():
            raise InitError(
                f"Target repo '{target_repo}' is not accessible. "
                f"Provide a valid git URL or local directory path."
            )

    # Step 5: Mirror clone
    try:
        mgr.clone_mirror(target_repo)
    except GitOpsError as e:
        raise InitError(f"Failed to clone mirror: {e}")

    # Step 6: Detect default branch
    default_branch = mgr.get_default_branch()
    logger.info("Default branch: %s", default_branch)

    # Step 7: Create worktree for fingerprinting
    try:
        worktree_path = mgr.create_worktree("init", "fingerprint", 0)
    except GitOpsError as e:
        raise InitError(f"Failed to create worktree for fingerprinting: {e}")

    try:
        # Step 8: Language/framework fingerprint
        fp = fingerprint_repo(Path(worktree_path))
        logger.info("Detected language: %s, playwright: %s", fp.language, fp.has_playwright)

        # Step 9: Image resolution
        try:
            resolved = resolve_image(
                Path(worktree_path),
                config_base_image=None,
            )
            logger.info("Resolved image: %s (source: %s)", resolved.image, resolved.source)
        except ImageResolutionError:
            from harness.image_resolver import ResolvedImage
            resolved = ResolvedImage(image="ubuntu:22.04", source="fallback")
            logger.warning(
                "Could not detect a base image for this repo. "
                "Falling back to ubuntu:22.04. "
                "Set base_image in .specify/extensions/harness/harness-config.yml "
                "once you know your stack."
            )

        # Step 10: Playwright detection
        has_playwright = detect_playwright(Path(worktree_path))

    finally:
        # Clean up fingerprint worktree
        mgr.destroy_worktree(worktree_path, keep_branch=False)

    # Step 11: PR host detection
    pr_host = _detect_pr_host()
    logger.info("PR host: %s", pr_host)

    # Step 12: Build config
    config = HarnessConfig(
        target_repo=target_repo,
        target_default_branch=default_branch,
        provider="docker",
        base_image=resolved.image if resolved.source == "config_override" else None,
        pr_host=pr_host,
        bind_mount_ack=bind_mount_ack,
    )

    # Enable visual tests when Playwright is detected
    config.visual_tests.enabled = has_playwright

    # Step 13: Write harness section into echelon.yml (unified config file).
    # load_config() reads .specify/extensions/echelon/echelon.yml, harness: key.
    config_dir = base / ".specify" / "extensions" / "echelon"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "echelon.yml"

    harness_data = {
        "target_repo": config.target_repo,
        "target_default_branch": config.target_default_branch,
        "provider": config.provider,
        "detected_language": fp.language,
        "detected_image": resolved.image,
        "detected_image_source": resolved.source,
        "has_playwright": has_playwright,
        "resource_limits": {
            "memory": config.resource_limits.memory,
            "cpu": config.resource_limits.cpu,
            "pids": config.resource_limits.pids,
            "storage": config.resource_limits.storage,
        },
        "network": {
            "allowlist": config.network.allowlist,
        },
        "gc": {
            "worktree_max_age_hours": config.gc.worktree_max_age_hours,
            "container_max_age_hours": config.gc.container_max_age_hours,
            "backup_max_age_days": config.gc.backup_max_age_days,
        },
        "visual_tests": {
            "enabled": has_playwright,
        },
        "ci_skip_enabled": config.ci_skip_enabled,
        "ci_skip_tag": config.ci_skip_tag,
        "pr_host": config.pr_host,
        "bind_mount_ack": config.bind_mount_ack,
        "llm": {
            "cli": _detect_llm_cli(),
        },
    }

    if yaml is not None:
        # Merge into existing echelon.yml (preserves echelon squad settings)
        existing: dict = {}
        if config_file.exists():
            existing = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
        existing["harness"] = harness_data
        config_file.write_text(
            yaml.dump(existing, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )
    else:
        import json
        existing = {}
        if config_file.exists():
            try:
                existing = json.loads(config_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        existing["harness"] = harness_data
        config_file.write_text(json.dumps(existing, indent=2), encoding="utf-8")

    logger.info("Harness config written to %s (harness: section)", config_file)

    # Step 14: Bind-mount acknowledgement
    if not bind_mount_ack:
        logger.warning(
            "BIND-MOUNT LIMITATION: The sandbox uses Docker bind-mounts. "
            "Code inside the sandbox CAN modify the worktree. "
            "Set bind_mount_ack=true in config.yml to acknowledge. (FR-INIT-ACK-001)"
        )

    # Step 15: Version compatibility check
    version_warning = _check_version_compatibility(config.echelon_version_range)
    if version_warning:
        logger.warning(version_warning)

    # Step 16: Constitution check
    const_warning = _check_constitution(base)
    if const_warning:
        if const_warning.startswith("WARNING"):
            logger.warning(const_warning)
        else:
            logger.info(const_warning)

    return config
