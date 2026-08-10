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

from harness.app_runtime_detection import AppRuntimeDetectionResult, detect_app_runtime
from harness.config import (
    CANONICAL_CONFIG_PATH,
    HarnessConfig,
    VALID_CONTAINER_CLIS,
)
from harness.errors import GitOpsError, SandboxCreationError, SelfTargetError
from harness.fingerprint import fingerprint_repo, detect_playwright
from harness.gitops import GitOpsManager
from harness.image_resolver import resolve_image, ImageResolutionError
from harness.paths import runs_dir, strategies_dir as _strategies_dir_fn, mirror_path as _mirror_path_fn
from harness.sandbox_suggestion import (
    SandboxSuggestionReport,
    detect_sandbox_suggestion,
    render_sandbox_suggestion_markdown,
)
from harness.verify_detection import VerifyDetectionResult, detect_verify_command

logger = logging.getLogger(__name__)


class InitError(Exception):
    """Raised when harness initialization fails."""


def _harness_config_file(base: Path) -> Path:
    """Return the canonical project config file harness init should write."""
    return base / CANONICAL_CONFIG_PATH


def _write_app_runtime_detection(
    config_file: Path,
    result: AppRuntimeDetectionResult,
) -> AppRuntimeDetectionResult:
    """Merge harness.app detection metadata into .echelon/config.yml."""
    if yaml is None:
        return result

    existing = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
    harness = existing.setdefault("harness", {})

    existing_app = harness.get("app")
    if existing_app:
        harness["app_detection"] = "existing"
        config_file.write_text(
            yaml.dump(existing, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )
        return AppRuntimeDetectionResult(
            profile=existing_app,
            confidence="existing",
            evidence=["existing harness.app profile"],
        )

    harness["app_detection"] = result.confidence
    if result.profile and result.confidence == "high":
        harness["app"] = result.profile
        harness["app_evidence"] = result.evidence
    elif result.reason:
        harness["app_reason"] = result.reason
        if result.evidence:
            harness["app_evidence"] = result.evidence

    config_file.write_text(
        yaml.dump(existing, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
    return result


def _apply_app_runtime_detection(
    config_file: Path,
    repo_path: Path,
) -> AppRuntimeDetectionResult:
    """Detect and write harness.app when confidence is high."""
    return _write_app_runtime_detection(
        config_file=config_file,
        result=detect_app_runtime(repo_path),
    )


def _write_verify_command_detection(
    config_file: Path,
    result: VerifyDetectionResult,
) -> VerifyDetectionResult:
    """Merge verify_command detection metadata into .echelon/config.yml."""
    if yaml is None:
        return result

    existing = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
    harness = existing.setdefault("harness", {})

    existing_command = existing.get("verify_command")
    if existing_command:
        command = str(existing_command)
        harness["detected_verify_command"] = command
        harness["verify_command_detection"] = "existing"
        config_file.write_text(
            yaml.dump(existing, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )
        return VerifyDetectionResult(
            command=command,
            confidence="existing",
            evidence=["existing top-level verify_command"],
        )

    harness["verify_command_detection"] = result.confidence
    if result.command and result.confidence == "high":
        existing["verify_command"] = result.command
        harness["detected_verify_command"] = result.command
        harness["verify_command_evidence"] = result.evidence
    elif result.reason:
        harness["verify_command_reason"] = result.reason
        if result.evidence:
            harness["verify_command_evidence"] = result.evidence

    config_file.write_text(
        yaml.dump(existing, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
    return result


def _apply_verify_command_detection(
    config_file: Path,
    repo_path: Path,
) -> VerifyDetectionResult:
    """Detect and write verify_command when confidence is high."""
    return _write_verify_command_detection(
        config_file=config_file,
        result=detect_verify_command(repo_path),
    )


def _write_sandbox_suggestion_report(
    config_file: Path,
    report: SandboxSuggestionReport,
) -> SandboxSuggestionReport:
    """Merge the sandbox suggestion report into .echelon/config.yml."""
    if yaml is None:
        return report

    existing = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
    harness = existing.setdefault("harness", {})
    harness["sandbox_suggestion"] = report.to_dict()
    config_file.write_text(
        yaml.dump(existing, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
    config_file.with_name("sandbox-suggestion.md").write_text(
        render_sandbox_suggestion_markdown(report) + "\n",
        encoding="utf-8",
    )
    return report


def _resolve_container_cli(base: Optional[Path] = None) -> str:
    """Resolve the Docker-compatible container CLI for harness sandboxes."""
    env_cli = os.environ.get("ECHELON_CONTAINER_CLI", "").strip()
    cli = env_cli or _read_existing_container_cli(base) or "docker"
    if cli not in VALID_CONTAINER_CLIS:
        raise InitError(
            f"Invalid container_cli={cli!r}. "
            f"Expected one of: {sorted(VALID_CONTAINER_CLIS)}."
        )
    return cli


def _read_existing_container_cli(base: Optional[Path]) -> Optional[str]:
    if base is None or yaml is None:
        return None
    config_file = _harness_config_file(base)
    if not config_file.exists():
        return None
    try:
        existing = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
    except Exception:
        return None
    harness = existing.get("harness", existing)
    if not isinstance(harness, dict):
        return None
    value = harness.get("container_cli")
    return str(value).strip() if value else None


def _check_container_runtime(container_cli: str) -> bool:
    """Check if the selected Docker-compatible runtime is reachable."""
    try:
        result = subprocess.run(
            [container_cli, "info"],
            capture_output=True,
            timeout=10,
            check=False,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _check_docker() -> bool:
    """Backward-compatible wrapper for older tests and callers."""
    return _check_container_runtime("docker")


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
    Returns 'claude' | 'copilot' | 'opencode' | 'codex'.
    """
    import os
    import shutil

    env = os.environ.get("ECHELON_LLM", "").strip()
    if env in ("claude", "copilot", "opencode", "codex"):
        return env
    for cli in ("claude", "copilot", "opencode", "codex"):
        if shutil.which(cli):
            return cli
    return "claude"  # default; will error at runtime if not installed


def _resolve_harness_llm_config(
    existing: dict,
    *,
    detected_cli: str,
) -> dict:
    """Preserve workspace LLM provider unless ECHELON_LLM explicitly overrides it."""
    harness = existing.get("harness")
    existing_llm = harness.get("llm") if isinstance(harness, dict) else {}
    llm = dict(existing_llm) if isinstance(existing_llm, dict) else {}

    env = os.environ.get("ECHELON_LLM", "").strip()
    if env in ("claude", "copilot", "opencode", "codex"):
        llm["cli"] = env
    elif not llm.get("cli"):
        llm["cli"] = detected_cli
    return llm



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
    """Initialize delivery runtime settings.

    Args:
        target_repo: URL or local path used only for init-time fingerprinting.
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

    container_cli = _resolve_container_cli(base)

    # Step 2: Container runtime health check
    if not _check_container_runtime(container_cli):
        hint = (
            " If using Podman on macOS, run 'podman machine start' and retry."
            if container_cli == "podman"
            else ""
        )
        raise InitError(
            f"{container_cli} is not running or is unreachable. "
            "echelon-harness requires a Docker-compatible runtime to create sandboxes. "
            f"Please start {container_cli} and try again.{hint}"
        )
    logger.info("%s runtime is running", container_cli)

    # Step 3: Self-targeting detection
    # Create a temporary config to initialize GitOpsManager
    temp_config = HarnessConfig(
        target_repo=target_repo,
        target_default_branch="main",
        provider="docker",
        container_cli=container_cli,
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
        worktree_path = mgr.create_worktree(
            "init",
            "fingerprint",
            0,
            build_id="init",
            prepare_codegraph=False,
        )
    except GitOpsError as e:
        raise InitError(f"Failed to create worktree for fingerprinting: {e}")

    verify_detection = VerifyDetectionResult(
        command=None,
        confidence="none",
        reason="fingerprint worktree unavailable",
    )
    app_detection = AppRuntimeDetectionResult(
        profile=None,
        confidence="none",
        reason="fingerprint worktree unavailable",
    )
    sandbox_suggestion = SandboxSuggestionReport(
        confidence="low",
        confidence_score=0.0,
        suggested_strategy="Fingerprint worktree unavailable.",
        human_approval_point="Review sandbox settings manually before execution.",
        fallback_path="Add explicit harness settings to .echelon/config.yml.",
    )

    try:
        # Step 8: Language/framework fingerprint
        fp = fingerprint_repo(Path(worktree_path))
        logger.info("Detected language: %s, playwright: %s", fp.language, fp.has_playwright)
        verify_detection = detect_verify_command(Path(worktree_path))
        if verify_detection.command:
            logger.info("Detected verify_command: %s", verify_detection.command)
        else:
            logger.info("No verify_command detected: %s", verify_detection.reason)
        app_detection = detect_app_runtime(Path(worktree_path))
        if app_detection.profile:
            logger.info("Detected harness.app runtime: %s", app_detection.profile)
        else:
            logger.info("No harness.app runtime detected: %s", app_detection.reason)
        sandbox_suggestion = detect_sandbox_suggestion(
            Path(worktree_path),
            verify_detection=verify_detection,
            app_detection=app_detection,
        )
        logger.info(
            "Sandbox suggestion: %s (confidence %.2f)",
            sandbox_suggestion.confidence,
            sandbox_suggestion.confidence_score,
        )

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
                "Set base_image in .echelon/config.yml "
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
        container_cli=container_cli,
        base_image=resolved.image if resolved.source == "config_override" else None,
        pr_host=pr_host,
        bind_mount_ack=bind_mount_ack,
    )

    # Enable visual tests when Playwright is detected
    config.visual_tests.enabled = has_playwright

    # Step 13: Write harness section into the Echelon project config.
    config_file = _harness_config_file(base)
    config_file.parent.mkdir(parents=True, exist_ok=True)
    existing: dict = {}
    if yaml is not None and config_file.exists():
        existing = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}

    harness_data = {
        "provider": config.provider,
        "container_cli": config.container_cli,
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
        "llm": _resolve_harness_llm_config(existing, detected_cli=_detect_llm_cli()),
    }

    if yaml is not None:
        # Merge into the canonical config while preserving squad settings.
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

    verify_detection = _write_verify_command_detection(config_file, verify_detection)
    app_detection = _write_app_runtime_detection(config_file, app_detection)
    _write_sandbox_suggestion_report(config_file, sandbox_suggestion)
    logger.info("Harness config written to %s (harness: section)", config_file)

    # Create runs/ and strategies dir so codegen preflight finds them without noise
    rd = runs_dir(base)
    rd.mkdir(parents=True, exist_ok=True)
    gitignore = rd / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("# echelon harness runtime artifacts — do not commit\n*\n!.gitignore\n", encoding="utf-8")
    strats = _strategies_dir_fn(base)
    strats.mkdir(parents=True, exist_ok=True)
    gitkeep = strats / ".gitkeep"
    if not gitkeep.exists():
        gitkeep.touch()

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
