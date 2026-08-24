#!/usr/bin/env python3
"""echelon CLI — deterministic entry points for echelon skills.

LLM commands read the corresponding skill markdown, inject arguments,
and invoke the configured LLM CLI so the LLM only executes the skill.

`init` is pure Python — no LLM involved.

Command prose for every AI tool:
  .echelon/prosaic/commands/echelon.<cmd>.md
Auto-detected from ECHELON_LLM (default: claude).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
import fcntl
import re
import shlex
import shutil
import stat
import subprocess
import sys
from pathlib import Path, PurePosixPath

from harness.gitops import copy_prosaic_runtime_tree, copy_runtime_tree
from harness.recovery_instruction import (
    RecoveryInstruction,
    RecoveryInstructionError,
    RecoveryKind,
    retry_phase_recovery,
    validate_recovery_instruction,
)
from harness.runtime_surface import prune_delivery_workflow_definition
from harness.phase_a_readiness import validate_phase_a_readiness

try:
    from codegen.memory.collision import check_wing_collision
except ImportError:
    try:
        from src.codegen.memory.collision import check_wing_collision  # type: ignore
    except ImportError:
        def check_wing_collision(*a, **k):  # type: ignore[assignment]
            return []

# Maps CLI commands to deployed Prosaic command names used to derive file paths.
# NOTE: "run" is intentionally absent — it is handled by the Python harness
# (_cmd_run) and must never fall through to the skill-based LLM path.
# Keeping "run" here would cause infinite recursion: skill → claude -p →
# echelon.run.md → "echelon spec run" → skill → ... (155 nested processes).
SKILL_MAP = {
    "bugfix":  "echelon.bugfix",
    "build":   "echelon.build",
    "review":  "echelon.review",
    "change":  "echelon.change",
    "codegen": "echelon.codegen",
    "verify-spec": "echelon.verify-spec",
    "reopen":  "echelon.reopen",
}

CLI_VERSION = "4.0.11"
LEXICON_TASK_SPEC_REF_PATH = "lexicon_gate.artifacts.tasks.spec_ref"
_SPEC_SUMMARY_COMMAND: ContextVar[str] = ContextVar(
    "echelon_spec_summary_command",
    default="echelon spec run",
)


@dataclass
class _SpecSummaryScope:
    project_root: Path
    command: str
    run_dir: Path | None = None
    mode: str = "semi"
    message: str = ""
    implementation_targets: tuple[str, ...] = ()
    emitted: bool = False
    next_already_printed: bool = False


_SPEC_SUMMARY_SCOPE: ContextVar[_SpecSummaryScope | None] = ContextVar(
    "echelon_spec_summary_scope",
    default=None,
)

from echelon.workspace_model import discover_workspace  # noqa: E402  (after stdlib imports)
from echelon.ui import banner as _banner  # noqa: E402  (after stdlib imports)


USAGE = f"""\
echelon {CLI_VERSION}

Usage: echelon <command> [args...]

Commands:
  workspace init [--llm <provider>] [--openai-base-url <url>] [--openai-model <model>]
                    [--openai-api-key-file <path>|--openai-api-key-env <env>]
                    [--allow-unsafe-host-execution|--no-unsafe-host-execution]
                    One-time project setup (no LLM)
  workspace doctor                          Check workspace/source/runtime contract
  workspace sources sync [--write]          Sync discovered sources/* roots into config
  workspace migrate [--write] [--commit] [--message <msg>]
                                            Migrate legacy workspace layout

  spec run <description> [--mode semi|banzai|guided] [--reset] [--perfectionist]
                    [--message <text>] [--next-phase <id>]
                    [--target <source-id-or-path>]... [--re-source <source-id-or-re-path>]... [--init]
                    [--ignore-re]
                                            Run Phase A squad spec authoring;
                                            --perfectionist requests exhaustive Cartographer authoring.
  spec status                               Show current run state, artifacts, cost, and next action.
  spec continue [--mode semi|banzai|guided] Run the next no-input Phase A recovery action.
  spec resume "<answers>"                   Answer escalation questions from a blocked run.
  spec rewind <phase-id> [--commit <sha>] [--next-phase <phase-id>]
                                            Rewind the active squad run to a safe checkpoint.
  spec switch <spec-or-run-id> [--stash | --discard --confirm] [--restore-stash]
                                            Select a checkpointed Phase A spec run.
  spec drop-target <spec_id> <target> --confirm
                                            Remove an unused target from an unfinished run.
  spec retarget <spec_id> --target <source-id-or-path>... [--confirm]
                                            Destructively replace all implementation targets.
  spec checkpoint list|accept|commit [--spec <id>] [--phase <phase-id>]
                                            Manage Phase A/spec checkpoints.
  spec targets <spec_id>                    Display every task grouped by delivery target.
  spec artifacts <spec_id>                  Generate specs/<id>/ARTIFACTS.md.
  spec verify <spec_id> [--reconcile] [--dry-run]
                                            Audit implementation against spec.
  spec reopen <spec_id> [from=<report>]      Reopen spec from fulfillment gaps.
  spec bugfix <spec_id> <description>        Diagnose and plan a bugfix.
  spec change <spec_id> <description>        Plan a scope change.
  spec amend <spec_id> <description> [--input <role:path>]... [--dry-run]
                                            Prepare an isolated amendment for an unbuilt spec.

  phase list                                List workflow phases available for manual replay.
  phase run <phase-id> [--spec <id>] [--mode semi|banzai|guided]
                    [--message <text>]
                                            Run one explicit phase through COMMANDER contracts.

  re run [--engine v1|v2] [--goal baseline|inventory] [--shadow]
                    [--re-policy none|cached-only|changed|refresh-all]
                    [--re-max-inner <n>] [--reset]
                                            Run or reuse workspace reverse engineering.
  re refresh --source <source-id>           Refresh and publish one declared source.
  re status [--json]                        Show live RE state, source quality, debt, and next action.
  re continue [--re-max-inner <n>] [--re-token-limit <n>] [--re-time-limit-minutes <n>]
                                            Continue the active RE run.
  re resume <answer> [--re-max-inner <n>] [--re-token-limit <n>] [--re-time-limit-minutes <n>]
                                            Resume blocked RE with a human answer.
  re finalize [<run-id>] --allow-partial    Accept recorded debt and stop a blocked RE run.
  re synthesize [<run-id>] --allow-partial [--re-token-limit <n>]
                                            Build workspace synthesis from partial source results.
  re publish <run-id> [--allow-partial] [--commit]
                                            Publish validated workspace RE output.

  benchmark list                            List experimental benchmark fixtures and variants.
  benchmark show [latest|<summary-path-or-run-dir>]
                                            Print saved benchmark scores.
  benchmark run <fixture> --variant <id> [--baseline-ref <ref>] [--artifact-only] [--dry-run]
                                            Run or print an artifact-quality benchmark variant.

  llm smoke-openai-compatible [--base-url <url>] [--model <model>]
                    [--api-key-file <path>|--api-key-env <env>] [--no-streaming]
                                            Exercise an OpenAI-compatible endpoint with a tiny tool-call loop.

  stack list [--json]                       List available Echelon stacks.
  stack detect [--target <path>] [--artifacts <path>] [--write] [--format text|yaml] [--json]
                                            Detect source/artifact stack evidence.
  stack preflight [--stack <id>] [--target-archetype <id>] [--from-detect <path>] [--probe-tools] [--json]
                                            Check selected stack commands, registries, and tool probes.

  delivery init                              Initialize delivery environment: sandbox, mirror, verify.
  delivery target <spec_id>                  Prepare target-scoped delivery metadata from spec targets.
  delivery status [spec_id] [--strategy <s>] Show current Phase B delivery/Ralph state.
  delivery run <spec_id> [--mode <m>] [--strategy <s>] [--max-outer <n>] [--max-inner <n>]
                    [--token-budget <n>] [--auto-merge|--no-auto-merge] [--kill-losers] [--reset]
                                            Run build→verify→PR loop.
                    Legacy key=value options remain accepted for compatibility.
  delivery continue <spec_id> [--strategy <s>] [--mode <guided|semi|banzai>]
                                            Continue a blocked delivery run without a new answer.
  delivery resume <spec_id> "<answer>" [--strategy <s>] [--mode <guided|semi|banzai>]
                                            Resume a blocked delivery run with a human answer.
  delivery checkpoint list <spec_id> [--strategy <s>]
                                            List delivery checkpoint/recovery commits.
  delivery land <spec_id> [--continue] [--prepare-only] [--no-autoresolve]
                    [--allow-fulfillment-gaps] [--strategy merge|rebase]
                                            Land a spec: merge PR/branch, clean up.

Command prose for every provider:
  .echelon/prosaic/commands/echelon.<cmd>.md
"""


# ── init (pure Python, no LLM) ────────────────────────────────────────────

def _workspace_git_preflight(project_root: Path, *, command_name: str) -> None:
    manifest = discover_workspace(project_root)
    if manifest.workspace.git_present:
        return

    source_paths = [source.path for source in manifest.sources if source.path != "."]
    ignore_entries = [f"/{path}/" for path in source_paths] or ["/source-repo/"]
    ignore_entries.append("/runs/")
    ignore_lines = "\n".join(ignore_entries)
    print(
        "✗ Echelon workspace root is not a Git repo.\n\n"
        "Echelon requires workspace Git so specs, run state, and recovery metadata "
        "have durable version history.\n\n"
        "Fix:\n"
        "  git init\n"
        f"  printf \"{ignore_lines}\\n\" >> .gitignore\n"
        "  git add .gitignore specs\n"
        "  git commit -m \"chore: initialize echelon workspace\"\n\n"
        "Then rerun:\n"
        f"  {command_name}",
        file=sys.stderr,
    )
    raise SystemExit(2)


def _workspace_git_present(project_root: Path) -> bool:
    return discover_workspace(project_root).workspace.git_present


def _workspace_git_has_head(project_root: Path) -> bool:
    if not _workspace_git_present(project_root):
        return False
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _workspace_git_has_only_init_owned_drift(project_root: Path) -> bool:
    if not _workspace_git_present(project_root):
        return False
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return False
    allowed = {".echelon/config.yml", ".gitignore"}
    for line in result.stdout.splitlines():
        path = line[3:] if len(line) > 3 else ""
        if path not in allowed:
            return False
    return True


def _workspace_source_scaffold_needs_repair(project_root: Path) -> bool:
    readme = project_root / "sources" / "README.md"
    if not readme.exists():
        return True
    gitignore = project_root / ".gitignore"
    text = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    if "/sources/*" not in text or "!/sources/README.md" not in text:
        return True
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "sources/README.md"],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
    )
    return tracked.returncode != 0


def _maybe_bootstrap_workspace_git(project_root: Path) -> None:
    """Initialize lightweight workspace Git after workspace init when possible."""
    has_head = _workspace_git_has_head(project_root)
    if has_head:
        if not _workspace_source_scaffold_needs_repair(project_root):
            return
        from echelon.workspace_git_migration import migrate_workspace

        commit_repair = _workspace_git_has_only_init_owned_drift(project_root)
        result = migrate_workspace(project_root, write=True, commit=commit_repair)
        if result.source_roots_scaffolded:
            print("✓ source roots scaffolded: sources/ (clone/copy implementation repos there)")
        if result.gitignore_updated or result.staged_paths:
            staged = ", ".join(result.staged_paths) or "(none)"
            print(f"✓ workspace contract repaired; staged: {staged}")
        if result.committed:
            print("✓ committed initial workspace contract")
        elif result.staged_paths:
            print("  workspace repair left staged because the worktree was not clean")
        return
    if not (
        (project_root / ".specify").exists()
        or (project_root / "specs").exists()
        or (project_root / ".echelon" / "config.yml").exists()
    ):
        return

    from echelon.workspace_git_migration import migrate_workspace

    result = migrate_workspace(project_root, write=True, commit=True)
    if result.source_roots_scaffolded:
        print("✓ source roots scaffolded: sources/ (clone/copy implementation repos there)")
    if result.git_initialized:
        staged = ", ".join(result.staged_paths) or "(none)"
        print(f"✓ workspace Git initialized; staged: {staged}")
    if result.committed:
        print("✓ committed initial workspace contract")


def _print_legacy_branchless_recovery_notice(command_name: str) -> None:
    print(
        "legacy branchless run detected; continuing for recovery only\n"
        "Initialize workspace Git before starting new Echelon runs.",
        file=sys.stderr,
    )


def _command_display(prefix: str, args: list[str]) -> str:
    return shlex.join([*prefix.split(), *args])


def _workspace_git_preflight_for_squad_run(
    project_root: Path,
    *,
    command_name: str,
    user_message: str,
    reset: bool,
    manual_recovery: bool = False,
) -> None:
    if _workspace_git_present(project_root):
        return
    if reset:
        _workspace_git_preflight(project_root, command_name=command_name)

    existing_dir = _find_current_run_dir(project_root)
    if not existing_dir or not (existing_dir / "state.json").exists():
        _workspace_git_preflight(project_root, command_name=command_name)

    try:
        import json as _json

        state = _json.loads((existing_dir / "state.json").read_text(encoding="utf-8"))
    except Exception:
        _workspace_git_preflight(project_root, command_name=command_name)

    # A controller-owned issue recovery, like an explicit phase, must reuse the
    # existing run before new-spec branch/slug machinery sees its empty description.
    recovery = state.get("issue_resolution_recovery")
    manual_recovery = manual_recovery or (
        isinstance(recovery, dict) and recovery.get("status") != "consumed"
    )
    # An explicit phase is an intentional recovery command.  It must reuse the
    # existing run before any new-spec branch/slug machinery sees its empty
    # description, including when the run is waiting on a human escalation.
    if manual_recovery:
        _print_legacy_branchless_recovery_notice(command_name)
        return

    if state.get("status") in ("running", "in_progress") and (
        not user_message or user_message == state.get("user_message", "")
    ):
        _print_legacy_branchless_recovery_notice(command_name)
        return

    _workspace_git_preflight(project_root, command_name=command_name)


def _derive_wing_suggestion(project_dir: Path) -> str:
    """Suggest a wing name: git remote slug if available, else dirname-hash6."""
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            cwd=str(project_dir),
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            url = result.stdout.strip()
            slug = url.rstrip("/").removesuffix(".git").rsplit("/", 1)[-1]
            if slug:
                return slug
    except Exception:
        pass
    abs_hash = hashlib.sha256(str(project_dir.resolve()).encode()).hexdigest()[:6]
    return f"{project_dir.name}-{abs_hash}"


def _provision_wing(project_dir: Path, echelon_yml: Path) -> str:
    """
    Interactively provision wing name into echelon-config.yml.
    Idempotent: if wing already set, returns existing value immediately.
    Returns the confirmed wing name.
    """
    try:
        import yaml as _yaml
    except ImportError:
        print("✗ PyYAML not installed. Run: pip install pyyaml", file=sys.stderr)
        sys.exit(1)

    config = _yaml.safe_load(echelon_yml.read_text()) or {}
    existing_wing = config.get("mempalace", {}).get("wing", "")
    if existing_wing:
        print(f"✓ wing: {existing_wing!r} already configured")
        return existing_wing

    try:
        from mempalace.config import MempalaceConfig  # type: ignore[import]
        palace_path = MempalaceConfig().palace_path
    except ImportError:
        palace_path = os.path.expanduser("~/.mempalace/palace")

    suggestion = _derive_wing_suggestion(project_dir)
    last_entered: str = ""

    if not sys.stdin.isatty():
        chosen = suggestion
        foreign = check_wing_collision(chosen, project_dir, palace_path)
        if foreign:
            print(
                f"✗ Suggested MemPalace wing {chosen!r} belongs to another project. "
                "Re-run interactively and choose a different wing.",
                file=sys.stderr,
            )
            sys.exit(1)
        print(f"✓ wing: {chosen!r} selected for non-interactive initialization")
    else:
        while True:
            raw = input(f"Wing name for MemPalace memory [{suggestion}]: ").strip()
            chosen = raw or suggestion

            foreign = check_wing_collision(chosen, project_dir, palace_path)
            if foreign:
                if chosen == last_entered:
                    print(f"  ⚠  Sharing memory with other project intentionally — wing: {chosen!r}")
                    break
                print(f"\n  ⚠  Wing {chosen!r} already has drawers from a different project:")
                for path in foreign[:5]:
                    print(f"       {path}")
                print("  Enter a different name, or re-enter the same name to share memory intentionally.\n")
                last_entered = chosen
                suggestion = chosen
                continue

            break

    if "mempalace" not in config:
        config["mempalace"] = {}
    config["mempalace"]["wing"] = chosen
    echelon_yml.write_text(_yaml.dump(config, default_flow_style=False, allow_unicode=True))
    print(f"✓ wing: {chosen!r} written to echelon-config.yml")
    return chosen


def _print_http_deploy_runtime_warning(
    *,
    reason: str,
    detail: str | None = None,
) -> None:
    print(
        "⚠ HTTP deploy initialization skipped because Docker is not ready.\n"
        f"  reason   {reason}",
        file=sys.stderr,
    )
    if detail:
        print(f"  detail   {detail}", file=sys.stderr)
    print(
        "\n"
        "  workspace init will continue without provisioning local HTTP deploy infra.\n"
        "  Echelon will set deploy.enabled: false in .echelon/config.yml for this workspace.\n"
        "\n"
        "  next\n"
        "  ────\n"
        "  To enable HTTP deploy later, install/start Docker and rerun:\n"
        "    echelon workspace init\n"
        "\n"
        "  To disable local deploy for this project, set in .echelon/config.yml:\n"
        "    deploy.enabled: false\n"
        "\n"
        "  To initialize delivery sandboxing with Podman after workspace init:\n"
        "    ECHELON_CONTAINER_CLI=podman echelon delivery init\n"
        "\n"
        "  note\n"
        "  ────\n"
        "  Podman is supported for Echelon delivery sandboxing. The HTTP deploy\n"
        "  Traefik setup currently expects Docker and the Docker socket.",
        file=sys.stderr,
    )


def _preflight_deploy_runtime(
    deploy: dict,
    *,
    which=shutil.which,
    run=subprocess.run,
) -> bool:
    if deploy.get("type", "http") != "http":
        return True

    docker_bin = which("docker")
    if not docker_bin:
        _print_http_deploy_runtime_warning(reason="docker command not found on PATH")
        return False

    try:
        result = run(
            [docker_bin, "info"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        _print_http_deploy_runtime_warning(reason="docker info timed out")
        return False
    except OSError as exc:
        _print_http_deploy_runtime_warning(
            reason="docker info could not run",
            detail=str(exc),
        )
        return False

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        _print_http_deploy_runtime_warning(
            reason="Docker CLI found, but the Docker daemon is not reachable",
            detail=detail or None,
        )
        return False

    return True


UNSAFE_HOST_EXECUTION_APPROVAL_REASON = (
    "Operator approved echelon workspace init to allow local AI CLI host tool execution."
)


def _wants_unsafe_host_execution_interactively() -> bool:
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return False
    answer = input(
        "Allow local AI CLI subprocesses to bypass host tool approvals for this workspace? [y/N] "
    ).strip().lower()
    return answer in {"y", "yes"}


def _ensure_local_config_ignored(project_dir: Path) -> None:
    gitignore = project_dir / ".gitignore"
    entry = "/.echelon/local.yml"
    existing = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    normalized = {line.strip().strip("/") for line in existing.splitlines()}
    if ".echelon/local.yml" in normalized:
        return
    suffix = "" if not existing or existing.endswith("\n") else "\n"
    gitignore.write_text(f"{existing}{suffix}{entry}\n", encoding="utf-8")


def _assert_local_config_untracked(project_dir: Path) -> None:
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", ".echelon/local.yml"],
        cwd=project_dir,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        raise ValueError(
            ".echelon/local.yml is tracked; remove it from Git before storing "
            "developer-local LLM settings"
        )


def _write_unsafe_host_execution_local_override(project_dir: Path, yaml_module) -> Path:
    local_cfg = project_dir / ".echelon" / "local.yml"
    local_cfg.parent.mkdir(parents=True, exist_ok=True)
    if local_cfg.exists():
        loaded = yaml_module.safe_load(local_cfg.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise ValueError(f"local config must be a mapping: {local_cfg}")
    else:
        loaded = {}

    harness = loaded.setdefault("harness", {})
    if not isinstance(harness, dict):
        raise ValueError("local config harness section must be a mapping")
    llm = harness.setdefault("llm", {})
    if not isinstance(llm, dict):
        raise ValueError("local config harness.llm section must be a mapping")
    tool_policy = llm.setdefault("tool_policy", {})
    if not isinstance(tool_policy, dict):
        raise ValueError("local config harness.llm.tool_policy section must be a mapping")

    tool_policy["allow_unsafe_host_execution"] = True
    tool_policy["approval_reason"] = UNSAFE_HOST_EXECUTION_APPROVAL_REASON
    local_cfg.write_text(
        yaml_module.dump(loaded, default_flow_style=False, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    _ensure_local_config_ignored(project_dir)
    return local_cfg


def _apply_workspace_llm_selection(
    config: dict,
    llm_cli: str | None = None,
    *,
    openai_base_url: str | None = None,
    openai_model: str | None = None,
    openai_api_key_file: str | None = None,
    openai_api_key_env: str | None = None,
) -> str:
    from harness.config import VALID_LLM_CLIS
    from harness.init import _detect_llm_cli

    harness = config.setdefault("harness", {})
    if not isinstance(harness, dict):
        raise ValueError("config harness section must be a mapping")
    llm = harness.setdefault("llm", {})
    if not isinstance(llm, dict):
        raise ValueError("config harness.llm section must be a mapping")

    existing = llm.get("cli")
    openai_options = {
        "base_url": openai_base_url,
        "model": openai_model,
        "api_key_file": openai_api_key_file,
        "api_key_env": openai_api_key_env,
    }

    if llm_cli:
        if llm_cli not in VALID_LLM_CLIS:
            raise ValueError(
                f"invalid --llm {llm_cli!r}; expected one of: "
                f"{', '.join(sorted(VALID_LLM_CLIS))}"
            )
        llm["cli"] = llm_cli
        for key, value in openai_options.items():
            if value:
                llm[key] = value
        return llm_cli

    selected = _detect_llm_cli()
    if os.environ.get("ECHELON_LLM", "").strip() or not existing:
        llm["cli"] = selected
        for key, value in openai_options.items():
            if value:
                llm[key] = value
        return selected
    for key, value in openai_options.items():
        if value:
            llm[key] = value
    return str(existing)


def _cmd_init(
    project_dir: Path,
    *,
    allow_unsafe_host_execution: bool = False,
    llm_cli: str | None = None,
    openai_base_url: str | None = None,
    openai_model: str | None = None,
    openai_api_key_file: str | None = None,
    openai_api_key_env: str | None = None,
) -> None:
    echelon_cfg = project_dir / ".echelon" / "config.yml"
    runtime_dir = project_dir / ".echelon" / "runtime"

    from echelon.prosaic_packages import ProsaicBundleInstallError, install_prosaic_bundle

    try:
        install_prosaic_bundle(project_dir)
    except ProsaicBundleInstallError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(f"✓ Prosaic prose deployed: {project_dir / '.echelon/prosaic'}")
    print(f"✓ Prosaic runtime deployed: {runtime_dir}")
    _ensure_prosaic_workspace_ignores(project_dir)

    # Step 1: Confirm project config exists, seeded from the Echelon runtime.
    runtime_config = runtime_dir / "echelon-config.yml"
    config_template = runtime_dir / "config-template.yml"
    config_source = runtime_config if runtime_config.exists() else config_template
    if not echelon_cfg.exists():
        if config_source.exists():
            echelon_cfg.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(config_source, echelon_cfg)
            print(f"✓ Project config created: {echelon_cfg}")
        else:
            print(
                f"✗ Project config not found: {echelon_cfg}\n"
                f"  Runtime config also missing: {runtime_config}\n"
                f"  Config template also missing: {config_template}\n"
                "  Run: echelon workspace init",
                file=sys.stderr,
            )
            sys.exit(1)
    print(f"✓ Project config found: {echelon_cfg}")

    # Step 2: Validate deploy config
    try:
        import yaml
    except ImportError:
        print("✗ PyYAML not installed. Run: pip install pyyaml", file=sys.stderr)
        sys.exit(1)

    try:
        config = yaml.safe_load(echelon_cfg.read_text())
    except Exception as e:
        print(f"✗ Cannot parse .echelon/config.yml: {e}", file=sys.stderr)
        sys.exit(1)

    deploy = config.get("deploy", {})
    deploy_type = deploy.get("type", "http")
    if deploy_type not in ("http", "cli"):
        print(f"✗ deploy.type must be 'http' or 'cli', got: {deploy_type!r}", file=sys.stderr)
        sys.exit(1)
    if deploy_type == "http":
        missing = [k for k in ("blue_port", "green_port") if k not in deploy]
        if missing:
            print(
                f"✗ deploy config incomplete in .echelon/config.yml.\n"
                f"  HTTP type requires: {missing}\n"
                f"  See .echelon/runtime/config-template.yml for reference.",
                file=sys.stderr,
            )
            sys.exit(1)
    print(f"✓ deploy config valid (type={deploy_type})")
    deploy_enabled = deploy.get("enabled", True) is not False
    deploy_runtime_ready = _preflight_deploy_runtime(deploy) if deploy_enabled else False
    if deploy_enabled and not deploy_runtime_ready:
        deploy["enabled"] = False
        config["deploy"] = deploy
        echelon_cfg.write_text(yaml.dump(config, default_flow_style=False, allow_unicode=True))
        deploy_enabled = False
        print("✓ deploy.enabled=false written to .echelon/config.yml")

    local_cfg = project_dir / ".echelon" / "local.yml"
    try:
        _assert_local_config_untracked(project_dir)
        local_config = (
            yaml.safe_load(local_cfg.read_text(encoding="utf-8")) or {}
            if local_cfg.exists()
            else {}
        )
        if not isinstance(local_config, dict):
            raise ValueError(f"local config must be a mapping: {local_cfg}")
        selected_llm_cli = _apply_workspace_llm_selection(
            local_config,
            llm_cli=llm_cli,
            openai_base_url=openai_base_url,
            openai_model=openai_model,
            openai_api_key_file=openai_api_key_file,
            openai_api_key_env=openai_api_key_env,
        )
        local_cfg.parent.mkdir(parents=True, exist_ok=True)
        local_cfg.write_text(
            yaml.dump(local_config, default_flow_style=False, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        _ensure_local_config_ignored(project_dir)
    except Exception as e:
        print(f"✗ Cannot write local LLM provider: {e}", file=sys.stderr)
        sys.exit(1)
    echelon_cfg.write_text(
        yaml.dump(config, default_flow_style=False, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    print(f"✓ local LLM provider configured: {selected_llm_cli}")

    if allow_unsafe_host_execution:
        try:
            local_cfg = _write_unsafe_host_execution_local_override(project_dir, yaml)
        except Exception as e:
            print(f"✗ Cannot write local host tool policy approval: {e}", file=sys.stderr)
            sys.exit(1)
        print(f"✓ host tool execution approval written to {local_cfg}")

    # Step 2b: Provision MemPalace wing
    print("\n▶ Configuring MemPalace wing...")
    _provision_wing(project_dir, echelon_cfg)

    # Step 3: Run deploy-init.sh
    init_script = runtime_dir / "scripts" / "bash" / "deploy-init.sh"
    deploy_state_label = str(project_dir / "runs" / "deploy-state.json")
    if not deploy_enabled:
        deploy_state_label = "skipped (deploy.enabled=false)"
    elif not deploy_runtime_ready:
        deploy_state_label = "skipped (Docker unavailable)"
    elif not init_script.exists():
        print(
            f"✗ deploy-init.sh not found at {init_script}\n"
            "  Ensure the selected Echelon runtime is installed.",
            file=sys.stderr,
        )
        sys.exit(1)

    else:
        result = subprocess.run(
            ["bash", str(init_script), str(project_dir), str(echelon_cfg)],
            cwd=str(project_dir),
        )
        if result.returncode != 0:
            sys.exit(result.returncode)

    # Step 4: Confirm
    _banner("ECHELON INIT — COMPLETE", [
        ("Config",       str(echelon_cfg)),
        ("Deploy state", deploy_state_label),
        ("Next step",    "echelon spec run <description>"),
    ])


# ── land (pure Python, no LLM) ────────────────────────────────────────────

def _archive_squad_run(project_dir: Path, spec_id: str) -> None:
    """Offer to archive the active spec run into specs/<spec_id>-*/run/."""
    import shutil
    from harness.spec_frontmatter import find_spec_dir

    run_dir = _find_current_run_dir(project_dir)
    if run_dir is None:
        return

    spec_dir = find_spec_dir(spec_id, project_dir)
    if spec_dir is None:
        print(f"  (spec run archive skipped — spec {spec_id!r} dir not found)", flush=True)
        return

    run_id = run_dir.name
    archive_dest = spec_dir / "run"
    current_marker = run_dir.parent / ".current"
    try:
        spec_rel = spec_dir.resolve().relative_to(project_dir.resolve())
    except ValueError:
        spec_rel = spec_dir
    print(
        f"\nArchive spec run {run_id!r} into "
        f"{spec_rel}/run/ ?"
    )
    if not sys.stdin.isatty():
        print("  Spec run archive skipped — non-interactive stdin.", flush=True)
        return
    try:
        choice = input("  [Y]es archive / [n]o keep in runs/ / [s]kip: ").strip().lower()
    except EOFError:
        print("  Spec run archive skipped — no input available.", flush=True)
        return

    if choice in ("", "y", "yes"):
        shutil.move(str(run_dir), str(archive_dest))
        if current_marker.exists():
            current_marker.unlink()
        import subprocess
        subprocess.run(["git", "add", str(archive_dest)], cwd=str(project_dir), check=False)
        subprocess.run(
            ["git", "rm", "-r", "--cached", str(run_dir)],
            cwd=str(project_dir), check=False, capture_output=True,
        )
        try:
            archive_rel = archive_dest.resolve().relative_to(project_dir.resolve())
        except ValueError:
            archive_rel = archive_dest
        print(f"  ✓ Archived to {archive_rel}", flush=True)
    elif choice in ("s", "skip"):
        print("  Skipped.", flush=True)
    else:
        run_rel = run_dir.relative_to(project_dir) if run_dir.is_relative_to(project_dir) else run_dir
        print(f"  Spec run left at {run_rel}/", flush=True)


def _cmd_land(args: list[str]) -> None:
    """Land a spec: merge PR, delete branch, clean worktrees, mark done."""
    import logging
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if not args or args[0] in ("-h", "--help"):
        print(
            "Usage: echelon delivery land <spec_id> [--continue] [--prepare-only] "
            "[--no-autoresolve] [--allow-fulfillment-gaps] "
            "[--strategy merge|rebase]\n\n"
            "  Compatibility alias: echelon land <spec_id> [options...]\n"
            "  Merge PR, delete branch, clean worktrees, mark spec as landed.\n",
        )
        sys.exit(0)

    if args[0].startswith("-"):
        print(f"✗ missing spec_id before option {args[0]!r}", file=sys.stderr)
        sys.exit(1)

    spec_id = args[0]
    continue_existing = False
    prepare_only = False
    autoresolve = True
    allow_fulfillment_gaps = False
    strategy = "merge"

    remaining = args[1:]
    idx = 0
    while idx < len(remaining):
        arg = remaining[idx]
        if arg == "--continue":
            continue_existing = True
        elif arg == "--prepare-only":
            prepare_only = True
        elif arg == "--no-autoresolve":
            autoresolve = False
        elif arg == "--allow-fulfillment-gaps":
            allow_fulfillment_gaps = True
        elif arg == "--strategy":
            if idx + 1 >= len(remaining):
                print("✗ --strategy requires 'merge' or 'rebase'", file=sys.stderr)
                sys.exit(1)
            strategy = remaining[idx + 1]
            idx += 1
        elif arg.startswith("-"):
            print(f"✗ unknown option for echelon delivery land: {arg}", file=sys.stderr)
            sys.exit(1)
        else:
            print(f"✗ unexpected argument for echelon delivery land: {arg}", file=sys.stderr)
            sys.exit(1)
        idx += 1

    if strategy not in {"merge", "rebase"}:
        print("✗ --strategy must be 'merge' or 'rebase'", file=sys.stderr)
        sys.exit(1)

    project_dir = Path.cwd()
    target_env = os.environ.get("ECHELON_TARGET_REPO_PATH")
    polyrepo_env = os.environ.get("ECHELON_POLYREPO_ROOT")
    target_name_env = os.environ.get("ECHELON_TARGET_REPO_NAME")
    config_root = Path(polyrepo_env).resolve() if target_env and polyrepo_env else project_dir
    _require_provider_capability(
        "echelon delivery land",
        ProviderCapability.BUILD,
        project_dir=config_root,
    )
    harness_base_dir = project_dir
    if target_env and polyrepo_env:
        harness_base_dir = (
            config_root
            / "runs"
            / "targets"
            / (target_name_env or Path(target_env).resolve().name)
        )
        _sync_polyrepo_runtime_extension(config_root, harness_base_dir)
        project_dir = config_root
    elif _dispatch_land_to_spec_targets(
        spec_id,
        args[1:],
        project_root=project_dir,
        rerun_command=_command_display("echelon delivery land", args),
    ):
        return

    from harness.config import load_config, ValidationError as HarnessValidationError
    from harness.gitops import GitOpsManager
    from harness.land import LandOptions, land
    from harness.paths import mirror_path as _mirror_path_fn
    options = LandOptions(
        autoresolve=autoresolve,
        prepare_only=prepare_only,
        continue_existing=continue_existing,
        strategy=strategy,
        allow_fulfillment_gaps=allow_fulfillment_gaps,
    )

    try:
        config = (
            load_config(project_root=config_root, squad_only=True)
            if target_env
            else load_config()
        )
    except HarnessValidationError as e:
        _print_harness_config_error(e)
        sys.exit(1)
    if target_env:
        target_repo_path = Path(target_env).resolve()
        config.target_repo = str(target_repo_path)
        if not getattr(config, "target_default_branch", None):
            config.target_default_branch = "main"
        if getattr(config, "provider", None) not in {"docker", "e2b", "modal", "daytona"}:
            config.provider = "docker"
    gitops = (
        GitOpsManager(config, base_dir=str(harness_base_dir))
        if target_env
        else GitOpsManager(config)
    )
    if target_env and not _mirror_path_fn(harness_base_dir).exists():
        gitops.clone_mirror(config.target_repo)

    land_kwargs = (
        {"harness_root": harness_base_dir}
        if target_env and polyrepo_env
        else {}
    )
    success = land(
        spec_id,
        project_dir=project_dir,
        gitops=gitops,
        options=options,
        **land_kwargs,
    )
    if success:
        if options.prepare_only:
            _banner("LAND", [("spec", spec_id), ("status", "prepared")])
            sys.exit(0)
        _banner("LAND", [("spec", spec_id), ("status", "landed successfully")])
        _archive_squad_run(project_dir, spec_id)
        sys.exit(0)
    else:
        _banner("LAND", [("spec", spec_id), ("status", "could not be landed (PR merge blocked?)")], file=sys.stderr)
        sys.exit(1)


def _dispatch_land_to_spec_targets(
    spec_id: str,
    extra_args: list[str],
    *,
    project_root: Path,
    rerun_command: str,
) -> bool:
    """Dispatch workspace-level land to target repos declared by the spec."""
    from harness.spec_frontmatter import find_spec_dir, read_targets, write_targets
    from echelon.orchestrator import run_multi_target, validate_single_target, validate_targets

    spec_dir = find_spec_dir(spec_id, project_root)
    if spec_dir is None:
        return False
    targets_rel = read_targets(spec_dir)
    if not targets_rel:
        return False

    resolved_spec_id = spec_dir.name
    polyrepo_root = spec_dir.parent.parent
    if len(targets_rel) == 1:
        workspace_target = _resolve_harness_workspace_target(
            polyrepo_root,
            targets_rel[0],
            spec_dir=spec_dir,
            spec_id=resolved_spec_id,
            rerun_command=rerun_command,
        )
        if workspace_target.source_root == workspace_target.workspace_root:
            return False
        target_rel = workspace_target.source_root.relative_to(
            workspace_target.workspace_root
        ).as_posix()
        if target_rel != targets_rel[0]:
            write_targets(spec_dir, [target_rel])
        target = validate_single_target([target_rel], polyrepo_root)
        sys.exit(
            run_multi_target(
                resolved_spec_id,
                [target],
                extra_args,
                command="land",
                **_workspace_target_dispatch_metadata(workspace_target),
            )
        )

    targets = validate_targets(targets_rel, polyrepo_root)
    source_ids: dict[str, str] = {}
    source_git_roles: dict[str, str] = {}
    for target in targets:
        target_metadata = _source_dispatch_metadata(
            target=target,
            polyrepo_root=polyrepo_root,
            source_id=None,
        )
        source_ids.update(target_metadata["source_ids"])
        source_git_roles.update(target_metadata["source_git_roles"])
    sys.exit(
        run_multi_target(
            resolved_spec_id,
            targets,
            extra_args,
            command="land",
            workspace_root=polyrepo_root.resolve(),
            workspace_git_role="orchestration",
            source_ids=source_ids,
            source_git_roles=source_git_roles,
        )
    )


# ── harness subcommands (pure Python, no LLM) ────────────────────────────

def _cmd_harness(args: list[str]) -> None:
    if not args or args[0] in ("-h", "--help"):
        print(
            "Usage: echelon harness <subcommand> [args...]\n"
            "Compatibility alias for: echelon delivery <subcommand> [args...]\n\n"
            "Subcommands:\n"
            "  init                              Initialize delivery environment — config, mirror, verify\n"
            "  run    <spec_id> [mode=<m>] [strategy=<s>] [max_outer=<n>] [max_inner=<n>]\n"
            "                     [token_budget=<n>] [auto_merge=<bool>] [kill_losers=<bool>] [--reset]\n"
            "                                     Run build→verify→PR loop\n"
            "                                     mode: semi (default) | banzai | guided\n"
            "                                     strategy: default (echelon squad) or codegen (SOAR)\n"
            "  resume <spec_id> [strategy=<s>] [mode=<guided|semi|banzai>]\n"
            "                                     Resume a blocked run with a human answer\n"
            "  continue <spec_id> [strategy=<s>] [mode=<guided|semi|banzai>]\n"
            "                                     Continue a blocked/checkpointed run without a new answer\n"
            "  land   <spec_id> [options...]      Merge PR/branch, clean up, mark spec landed\n\n"
            "Examples:\n"
            "  echelon delivery init\n"
            "  echelon delivery init https://github.com/org/repo\n"
            "  echelon delivery run 001\n"
            "  echelon delivery run 001 strategy=codegen\n"
            "  echelon delivery run 001 strategy=default mode=banzai max_outer=3\n"
            "  echelon delivery continue 001\n"
            "  echelon delivery resume 001 \"Use the simpler option\"\n"
        )
        return

    subcmd = args[0]
    if subcmd == "init":
        _cmd_harness_init(args[1:])
    elif subcmd == "run":
        _cmd_harness_run(args[1:])
    elif subcmd == "resume":
        _cmd_harness_resume(args[1:])
    elif subcmd == "continue":
        _cmd_harness_continue(args[1:])
    elif subcmd == "land":
        _cmd_land(args[1:])
    else:
        print(f"echelon harness: unknown subcommand '{subcmd}'\n", file=sys.stderr)
        sys.exit(1)


def _cmd_delivery(args: list[str]) -> None:
    if not args or args[0] in ("-h", "--help"):
        print(
            "Usage: echelon delivery <subcommand> [args...]\n\n"
            "Delivery is Echelon Phase B: build, verify, recover, review, and land a completed spec.\n\n"
            "Subcommands:\n"
            "  init                              Initialize delivery environment — sandbox, mirror, verify\n"
            "  target <spec_id>                  Prepare target-scoped delivery metadata\n"
            "  status [spec_id] [--strategy <s>] Show current Phase B delivery/Ralph state\n"
            "  run    <spec_id> [mode=<m>] [strategy=<s>] [max_outer=<n>] [max_inner=<n>]\n"
            "                     [token_budget=<n>] [auto_merge=<bool>] [kill_losers=<bool>] [--reset]\n"
            "                                     Run build→verify→PR loop\n"
            "                                     mode: semi (default) | banzai | guided\n"
            "                                     strategy: default (echelon squad) or codegen (SOAR)\n"
            "  resume <spec_id> [strategy=<s>] [mode=<guided|semi|banzai>]\n"
            "                                     Resume a blocked delivery run with a human answer\n"
            "  continue <spec_id> [strategy=<s>] [mode=<guided|semi|banzai>]\n"
            "                                     Continue a blocked/checkpointed delivery run without a new answer\n"
            "  checkpoint list <spec_id> [strategy=<s>]\n"
            "                                     List delivery checkpoint/recovery commits\n"
            "  land   <spec_id> [options...]      Merge PR/branch, clean up, mark spec landed\n\n"
            "Examples:\n"
            "  echelon delivery init\n"
            "  echelon delivery target 001\n"
            "  echelon delivery status 001\n"
            "  echelon delivery run 001\n"
            "  echelon delivery run 001 strategy=codegen\n"
            "  echelon delivery run 001 mode=banzai max_outer=3\n"
            "  echelon delivery continue 001\n"
            "  echelon delivery resume 001 \"Use the simpler option\"\n"
            "  echelon delivery land 001\n"
        )
        return

    subcmd = args[0]
    if subcmd == "init":
        _cmd_harness_init(args[1:], command_prefix="echelon delivery init")
    elif subcmd == "target":
        _cmd_delivery_target(args[1:])
    elif subcmd == "status":
        _cmd_delivery_status(args[1:])
    elif subcmd == "run":
        _cmd_harness_run(args[1:], command_prefix="echelon delivery run")
    elif subcmd == "resume":
        _cmd_harness_resume(args[1:])
    elif subcmd == "continue":
        _cmd_harness_continue(args[1:])
    elif subcmd == "checkpoint":
        _cmd_delivery_checkpoint(args[1:])
    elif subcmd == "land":
        _cmd_land(args[1:])
    else:
        print(f"echelon delivery: unknown subcommand '{subcmd}'\n", file=sys.stderr)
        sys.exit(1)


def _print_harness_config_error(error: Exception) -> None:
    field_path = getattr(error, "field_path", None)
    if field_path == "target_repo":
        print(f"✗ Harness config error: {error}", file=sys.stderr)
        return
    print(f"✗ Harness config error: {error}\n  Fix: re-run 'echelon delivery init'.", file=sys.stderr)


def _print_missing_spec_target_error(spec_id: str, *, command_prefix: str = "echelon delivery run") -> None:
    print(
        f"✗ Spec '{spec_id}' has no implementation target.\n\n"
        "  Implementation targets are fixed when Phase A begins. Start a new spec run with:\n"
        "    echelon spec run <description> --target <source-path> "
        "[--target <source-path> ...]\n\n"
        f"  Delivery will not infer or mutate targets for spec '{spec_id}'.",
        file=sys.stderr,
    )


def _block_if_spec_task_targets_mismatch(
    spec_dir: Path,
    declared_targets: list[str],
    spec_id: str,
) -> None:
    """Fail before delivery spends tokens on tasks owned by other source repos."""
    tasks_path = spec_dir / "tasks.md"
    if not tasks_path.is_file() or not declared_targets:
        return

    from harness.task_targets import validate_task_targets

    result = validate_task_targets(
        tasks_path.read_text(encoding="utf-8", errors="replace"),
        declared_targets=declared_targets,
    )
    if result.valid:
        return

    lines = [
        "✗ Task ownership does not match the spec delivery targets.",
        "",
        "  Delivery is stopping before launching a build agent.",
        "  declared: " + ", ".join(declared_targets),
    ]
    if result.missing_targets:
        lines.append("  missing targets: " + ", ".join(result.missing_targets))
    if result.unreferenced_targets:
        lines.append(
            "  unreferenced targets: " + ", ".join(result.unreferenced_targets)
        )
    if result.unowned_tasks:
        lines.append(
            "  tasks without explicit target= ownership: "
            + ", ".join(result.unowned_tasks)
        )
    if result.cross_target_tasks:
        rendered = ", ".join(
            f"{task_id} ({' + '.join(targets)})"
            for task_id, targets in result.cross_target_tasks.items()
        )
        lines.append("  tasks spanning multiple targets: " + rendered)
    if result.path_target_mismatches:
        rendered = ", ".join(
            f"{task_id} (target={declared}; paths={' + '.join(paths)})"
            for task_id, (declared, paths) in result.path_target_mismatches.items()
        )
        lines.append("  task target/path mismatches: " + rendered)

    lines.extend(
        [
            "",
            "  Every task must declare exactly one target=<source-path> from targets.yml.",
            "  File paths validate ownership but never infer or replace it.",
        ]
    )
    lines.append("  Regenerate target-dependent plan/tasks artifacts from a correctly targeted spec run.")
    print("\n".join(lines), file=sys.stderr)
    raise SystemExit(2)


def _cmd_harness_init(
    args: list[str],
    *,
    command_prefix: str = "echelon delivery init",
) -> None:
    import logging
    import os
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args:
        print(
            f"✗ {command_prefix} no longer accepts a target repository.\n\n"
            "  Implementation targets are declared when Phase A begins:\n"
            "    echelon spec run <description> --target <source-path> "
            "[--target <source-path> ...]\n\n"
            f"  Then rerun: {command_prefix}",
            file=sys.stderr,
        )
        sys.exit(1)

    _require_provider_capability(command_prefix, ProviderCapability.BUILD)

    target_repo = "."
    base_dir = str(Path.cwd())
    _workspace_git_preflight(
        Path(base_dir),
        command_name=_command_display(command_prefix, args),
    )
    bind_mount_ack = os.environ.get("HARNESS_BIND_MOUNT_ACK", "").lower() in ("true", "1", "yes")
    try:
        _assert_local_config_untracked(Path(base_dir))
    except ValueError as exc:
        print(f"✗ {command_prefix} failed: {exc}", file=sys.stderr)
        sys.exit(1)

    from harness.init import init_harness, InitError
    try:
        config = init_harness(
            target_repo=target_repo,
            base_dir=base_dir,
            bind_mount_ack=bind_mount_ack,
        )
    except InitError as e:
        print(f"✗ {command_prefix} failed: {e}", file=sys.stderr)
        sys.exit(1)

    _ensure_local_config_ignored(Path(base_dir))

    config_file = _project_echelon_config(Path(base_dir))
    from harness.paths import mirror_path as _mirror_path_fn
    mirror_dir = _mirror_path_fn(Path(base_dir))

    image_note = ""
    if config.base_image is None:
        try:
            import yaml as _yaml
            raw = _yaml.safe_load(config_file.read_text())
            harness_raw = raw.get("harness", raw)
            detected = harness_raw.get("detected_image", "ubuntu:22.04")
            source = harness_raw.get("detected_image_source", "fallback")
            if source == "fallback":
                image_note = (
                    f"\n  ⚠  base_image not detected — using ubuntu:22.04 as fallback.\n"
                    f"     Set base_image in {config_file}\n"
                    f"     once you know your stack (e.g. node:20, python:3.12-slim).\n"
                )
            else:
                image_note = f"\n  base_image    → {detected} (auto-detected: {source})\n"
        except Exception:
            pass

    fields = [
        ("Config",      str(config_file)),
        ("Mirror",      str(mirror_dir)),
        ("Provider",    config.provider),
        ("PR host",     config.pr_host),
    ]
    if image_note.strip():
        fields.append(("Base image", image_note.strip()))
    fields.extend(_harness_init_detection_fields(config_file))
    fields.append(("Next step", _harness_init_next_step(config_file)))
    _banner("HARNESS INIT — COMPLETE", fields)


def _cmd_delivery_target(args: list[str]) -> None:
    if not args or args[0] in {"-h", "--help"}:
        print(
            "Usage: echelon delivery target <spec_id>\n\n"
            "Prepare target-scoped delivery metadata for the repo(s) declared by "
            "the originating `echelon spec run --target` invocation.",
        )
        return

    spec_id = args[0]
    _require_provider_capability("echelon delivery target", ProviderCapability.BUILD)
    from harness.spec_frontmatter import (
        find_spec_dir,
        read_target_entries,
        write_target_delivery,
    )

    workspace_root = Path.cwd()
    spec_dir = find_spec_dir(spec_id, workspace_root)
    if spec_dir is None:
        print(f"✗ Spec {spec_id!r} not found (searched from {workspace_root})", file=sys.stderr)
        sys.exit(1)

    targets = read_target_entries(spec_dir)
    if not targets:
        print(
            f"✗ Spec {spec_dir.name} has no delivery target.\n"
            "  Delivery will not infer or mutate targets. Regenerate the spec with "
            "echelon spec run <description> --target <source-path>.",
            file=sys.stderr,
        )
        sys.exit(1)

    _block_if_spec_task_targets_mismatch(
        spec_dir,
        [str(entry.get("path") or "").strip() for entry in targets],
        spec_dir.name,
    )

    spec_root = spec_dir.parent.parent
    fields: list[tuple[str, str]] = [("Spec", spec_dir.name)]
    for entry in targets:
        target_rel = str(entry.get("path") or "").strip()
        if not target_rel:
            continue
        target_path = Path(target_rel).expanduser()
        if not target_path.is_absolute():
            target_path = (spec_root / target_path).resolve()
        if not target_path.exists():
            print(
                f"✗ Target repo not found: {target_rel}\n"
                "  Restore the declared repo, or regenerate the spec with "
                f"--target {target_rel} --init.",
                file=sys.stderr,
            )
            sys.exit(1)
        if not (target_path / ".git").exists():
            print(
                f"✗ Target is not a Git repo: {target_rel}\n"
                "  Initialize the declared repo, or regenerate the spec with "
                f"--target {target_rel} --init.",
                file=sys.stderr,
            )
            sys.exit(1)

        delivery = _detect_target_verify_delivery(target_path, spec_dir.name)
        write_target_delivery(spec_dir, target_rel, delivery)
        fields.append(("Target", target_rel))
        fields.append(("Branch", str(entry.get("branch") or spec_dir.name)))
        verify = delivery.get("verify_command")
        if verify:
            fields.append(("Verify", str(verify)))
        else:
            reason = delivery.get("verify_reason") or "no high-confidence verify command detected"
            fields.append(("Verify", f"not configured - {reason}"))

    fields.append(("Metadata", str(spec_dir / "targets.yml")))
    fields.append(("Next", f"echelon delivery run {spec_dir.name} --mode=banzai"))
    _banner("DELIVERY TARGET", fields)


def _harness_verify_status(config_file: Path) -> tuple[str, str, str]:
    """Return (verify_command, detection_status, detection_reason)."""
    try:
        import yaml as _yaml

        raw = _yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
    except Exception:
        return "", "", ""

    if not isinstance(raw, dict):
        return "", "", ""
    harness_raw = raw.get("harness", {})
    if not isinstance(harness_raw, dict):
        harness_raw = {}

    return (
        str(raw.get("verify_command") or ""),
        str(harness_raw.get("verify_command_detection") or ""),
        str(harness_raw.get("verify_command_reason") or ""),
    )


def _harness_init_next_step(config_file: Path) -> str:
    """Return the init banner next step without suggesting an invalid delivery run."""
    verify_command, verify_detection, verify_reason = _harness_verify_status(config_file)
    if verify_command:
        return "echelon spec run \"<feature>\"\n  echelon delivery run <spec_id>"

    if verify_detection or verify_reason:
        detail = verify_detection or "none"
        if verify_reason:
            detail += f": {verify_reason}"
        return (
            "set top-level verify_command before delivery build\n"
            f"  detection: {detail}\n"
            "  examples:\n"
            "    verify_command: pytest\n"
            "    verify_command: npm test\n"
            "    verify_command: go test ./...\n"
            "  then: echelon delivery continue <spec_id>  # if recovering a blocked run\n"
            "        echelon delivery run <spec_id>     # for a new build"
        )

    return (
        "echelon spec run \"<feature>\"\n"
        "  echelon delivery run <spec_id>\n"
        "  if verification blocks: echelon delivery init or set verify_command manually"
    )


def _harness_init_detection_fields(config_file: Path) -> list[tuple[str, str]]:
    """Summarize auto-detected harness commands for the init banner."""
    try:
        import yaml as _yaml

        raw = _yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
    except Exception:
        return []

    harness_raw = raw.get("harness", {})
    if not isinstance(harness_raw, dict):
        harness_raw = {}

    fields: list[tuple[str, str]] = []

    verify_command = raw.get("verify_command")
    verify_detection = harness_raw.get("verify_command_detection")
    verify_reason = harness_raw.get("verify_command_reason")
    if verify_command:
        source = "auto-detected" if verify_detection == "high" else "configured"
        fields.append(("Verify", f"{verify_command} ({source})"))
    elif verify_detection or verify_reason:
        status = str(verify_detection or "none")
        detail = f"{status}: {verify_reason}" if verify_reason else status
        fields.append(("Verify", f"not configured - {detail}"))

    app_raw = harness_raw.get("app")
    app_detection = harness_raw.get("app_detection")
    app_reason = harness_raw.get("app_reason")
    if isinstance(app_raw, dict) and app_raw:
        mode = app_raw.get("mode", "manual")
        app_name = app_raw.get("app") or app_raw.get("service") or app_raw.get("compose_file") or "app"
        url = app_raw.get("url")
        source = "auto-detected" if app_detection == "high" else "configured"
        detail = f"{app_name} via {mode}"
        if url:
            detail += f" at {url}"
        fields.append(("App runtime", f"{detail} ({source})"))
    elif app_detection or app_reason:
        status = str(app_detection or "none")
        detail = f"{status}: {app_reason}" if app_reason else status
        fields.append(("App runtime", f"not configured - {detail}"))

    sandbox_raw = harness_raw.get("sandbox_suggestion")
    if isinstance(sandbox_raw, dict) and sandbox_raw:
        confidence = sandbox_raw.get("confidence", "unknown")
        score = sandbox_raw.get("confidence_score", 0.0)
        strategy = sandbox_raw.get("suggested_strategy", "review sandbox suggestion")
        approval = sandbox_raw.get("human_approval_point", "review before execution")
        fields.append(
            (
                "Sandbox",
                f"{confidence} ({float(score):.2f}) - {strategy} Approval: {approval}",
            )
        )
        fields.append(("Sandbox report", str(config_file.with_name("sandbox-suggestion.md"))))

    return fields


def _format_missing_verify_command_resume_message(config_file: Path, spec_id: str) -> str:
    """Format actionable resume guidance when verify_command is still missing."""
    _verify_command, verify_detection, verify_reason = _harness_verify_status(config_file)
    examples = (
        "    verify_command: swift test --package-path Packages/MyLib\n"
        "    verify_command: pytest\n"
        "    verify_command: npm test\n"
        "    verify_command: go test ./..."
    )

    if verify_detection or verify_reason:
        detail = verify_detection or "none"
        if verify_reason:
            detail += f": {verify_reason}"
        return (
            "✗ verify_command is still not set in echelon-config.yml.\n\n"
            "  Auto-detection already ran and did not configure a command.\n"
            f"  detection: {detail}\n\n"
            f"  Add a top-level verify_command to {config_file}, for example:\n"
            f"{examples}\n\n"
            f"  Then re-run:  echelon delivery continue {spec_id}"
        )

    return (
        "✗ verify_command is still not set in echelon-config.yml.\n\n"
        "  Option 1 — auto-detect once:  echelon delivery init\n"
        "  Option 2 — manual:            add a top-level verify_command to echelon-config.yml:\n"
        f"{examples}\n\n"
        f"  Then re-run:  echelon delivery continue {spec_id}"
    )


def _run_git_quiet(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )


def _clean_git_branch_name(line: str) -> str:
    return line.strip().removeprefix("*").strip()


def _target_feature_branch_candidates(target_repo: Path, spec_id: str) -> list[str]:
    if not (target_repo / ".git").exists():
        return []
    result = _run_git_quiet(["branch", "--list", spec_id, f"{spec_id}-*"], cwd=target_repo)
    if result.returncode != 0:
        return []
    branches: list[str] = []
    for line in result.stdout.splitlines():
        branch = _clean_git_branch_name(line)
        if branch and branch not in branches:
            branches.append(branch)
    return branches


def _detect_verify_result_from_git_ref(target_repo: Path, git_ref: str) -> object | None:
    import tempfile

    from harness.verify_detection import detect_verify_command

    rev = _run_git_quiet(["rev-parse", "--verify", f"{git_ref}^{{commit}}"], cwd=target_repo)
    if rev.returncode != 0:
        return None

    with tempfile.TemporaryDirectory(prefix="echelon-verify-detect-") as tmp:
        worktree = Path(tmp) / "worktree"
        added = _run_git_quiet(
            ["worktree", "add", "--detach", str(worktree), rev.stdout.strip()],
            cwd=target_repo,
        )
        if added.returncode != 0:
            return None
        try:
            detected = detect_verify_command(worktree)
            if detected.confidence == "high" and detected.command:
                return detected
            return None
        finally:
            _run_git_quiet(["worktree", "remove", "--force", str(worktree)], cwd=target_repo)
            _run_git_quiet(["worktree", "prune"], cwd=target_repo)


def _detect_verify_command_from_git_ref(target_repo: Path, git_ref: str) -> str | None:
    detected = _detect_verify_result_from_git_ref(target_repo, git_ref)
    command = getattr(detected, "command", None)
    return str(command) if command else None


def _detect_target_verify_delivery(target_repo: Path, spec_id: str) -> dict[str, object]:
    from harness.verify_detection import detect_verify_command

    detected = detect_verify_command(target_repo)
    source = "target_checkout"
    if detected.confidence != "high" or not detected.command:
        for branch in _target_feature_branch_candidates(target_repo, spec_id):
            branch_detected = _detect_verify_result_from_git_ref(target_repo, branch)
            if branch_detected is not None:
                detected = branch_detected  # type: ignore[assignment]
                source = f"branch:{branch}"
                break

    result: dict[str, object] = {
        "verify_detection": str(getattr(detected, "confidence", "none")),
        "verify_source": source,
    }
    command = getattr(detected, "command", None)
    if command:
        result["verify_command"] = str(command)
    evidence = getattr(detected, "evidence", None)
    if isinstance(evidence, list) and evidence:
        result["verify_evidence"] = [str(item) for item in evidence]
    reason = getattr(detected, "reason", None)
    if reason:
        result["verify_reason"] = str(reason)
    return result


def _apply_target_verify_command_detection(
    config: object,
    *,
    target_repo: Path | None,
    spec_id: str,
) -> None:
    """Populate runtime verify_command from the actual delivery target."""
    if getattr(config, "verify_command", None) or target_repo is None:
        return
    if not target_repo.exists():
        return

    from harness.verify_detection import detect_verify_command

    detected = detect_verify_command(target_repo)
    if detected.confidence == "high" and detected.command:
        config.verify_command = detected.command
        print(
            f"Detected verify_command from delivery target: {detected.command}",
            file=sys.stderr,
        )
        return

    for branch in _target_feature_branch_candidates(target_repo, spec_id):
        command = _detect_verify_command_from_git_ref(target_repo, branch)
        if command:
            config.verify_command = command
            print(
                f"Detected verify_command from delivery target branch {branch}: {command}",
                file=sys.stderr,
            )
            return


def _cmd_cicd(args: list[str]) -> None:
    """Retired CI/CD auto-generation command."""
    print(
        "✗ echelon cicd is retired.\n\n"
        "  The old command launched a full LLM squad and could create new specs or\n"
        "  mutate Docker/deploy/CI files when the harness only needed verification.\n\n"
        "  For delivery verification, run:\n"
        "    echelon delivery init\n\n"
        "  If auto-detection cannot make a high-confidence choice, add a top-level\n"
        "  verify_command to .echelon/config.yml, for example:\n"
        "    verify_command: pytest\n"
        "    verify_command: npm test\n"
        "    verify_command: go test ./...",
        file=sys.stderr,
    )
    sys.exit(1)


def _sync_polyrepo_runtime_extension(polyrepo_root: Path, harness_base_dir: Path) -> None:
    """Copy deployed Prosaic and runtime bundles into a target harness base."""
    prose_source = polyrepo_root / ".echelon" / "prosaic"
    runtime_source = polyrepo_root / ".echelon" / "runtime"
    prose_dest = harness_base_dir / ".echelon" / "prosaic"
    runtime_dest = harness_base_dir / ".echelon" / "runtime"
    required = (
        prose_source / "commands",
        prose_source / "subagents",
        runtime_source / "workflow" / "definition.yaml",
    )
    if not all(path.exists() for path in required):
        print(
            "✗ Echelon Prosaic/runtime bundle is not installed in polyrepo root.\n"
            f"  Expected: {prose_source} and {runtime_source}\n"
            "  Fix: run 'echelon workspace migrate-to-prosaic' from the polyrepo root.",
            file=sys.stderr,
        )
        sys.exit(1)
    copy_prosaic_runtime_tree(prose_source, prose_dest)
    copy_runtime_tree(runtime_source, runtime_dest)
    prune_delivery_workflow_definition(runtime_dest / "workflow" / "definition.yaml")


def _target_candidate_lines(candidates: list[object]) -> str:
    lines: list[str] = []
    for candidate in candidates:
        repo = str(getattr(candidate, "repo", ""))
        evidence = [str(item) for item in getattr(candidate, "evidence", [])]
        source_path = None
        for item in evidence:
            prefix = "workspace source path `"
            if item.startswith(prefix) and item.endswith("`"):
                source_path = item[len(prefix):-1]
                break
        if source_path and source_path != repo:
            lines.append(f"  - {repo} (path: {source_path})")
        elif repo:
            lines.append(f"  - {repo}")
    return "\n".join(lines)


def _source_dispatch_metadata(
    *,
    target: Path,
    polyrepo_root: Path,
    source_id: str | None,
) -> dict[str, object]:
    resolved_target = target.resolve()
    resolved_workspace = polyrepo_root.resolve()
    resolved_source_id = source_id or ("." if resolved_target == resolved_workspace else target.name)
    workspace_git_role = (
        "source"
        if resolved_target == resolved_workspace and resolved_source_id == "."
        else "orchestration"
    )
    return {
        "workspace_root": resolved_workspace,
        "workspace_git_role": workspace_git_role,
        "source_ids": {str(resolved_target): resolved_source_id},
        "source_git_roles": {str(resolved_target): "source"},
    }


@dataclass(frozen=True)
class HarnessWorkspaceTarget:
    workspace_root: Path
    workspace_git_role: str
    source_root: Path
    source_id: str
    source_git_role: str


def _resolve_harness_workspace_target(
    project_root: Path,
    explicit_target: str | None,
    *,
    spec_dir: Path | None = None,
    spec_id: str | None = None,
    rerun_command: str | None = None,
) -> HarnessWorkspaceTarget:
    from echelon.target_detection import detect_target
    from echelon.workspace_model import SourceRoot, discover_workspace

    manifest = discover_workspace(project_root)
    if explicit_target == ".":
        return HarnessWorkspaceTarget(
            workspace_root=manifest.workspace.root,
            workspace_git_role="source",
            source_root=manifest.workspace.root,
            source_id=".",
            source_git_role="source",
        )

    result = detect_target(
        spec_dir=spec_dir or project_root,
        polyrepo_root=project_root,
        workspace_manifest=manifest,
        explicit_target=explicit_target,
    )

    def _candidate_lines() -> str:
        return _target_candidate_lines(result.candidates)

    command_label = "delivery" if (rerun_command or "").startswith("echelon delivery ") else "harness"
    new_repo_hint = (
        "\n\n"
        "  For a new implementation repo:\n"
        "    echelon spec run <description> --target sources/<new-repo> --init"
    )

    if result.decision == "no_source_roots":
        print(
            "✗ No source roots found; harness build needs at least one implementation source root.\n\n"
            "  Add or checkout the source repo(s), or add source project markers to this workspace."
            + (f"\n  Then rerun:  {rerun_command}" if rerun_command else ""),
            file=sys.stderr,
        )
        raise SystemExit(2)

    if result.decision == "multiple_source_roots_need_target":
        print(
            f"✗ Multiple source roots found; choose one before running {command_label}.\n\n"
            "  Source roots:\n"
            f"{_candidate_lines()}\n\n"
            "  Fix: start Phase A with repeatable "
            "'echelon spec run <description> --target <source-path>' options."
            + new_repo_hint
            + (f"\n  Then rerun:  {rerun_command}" if rerun_command else ""),
            file=sys.stderr,
        )
        raise SystemExit(2)

    if result.decision == "invalid_target":
        configured = f"\n  Configured target: {explicit_target}" if explicit_target else ""
        print(
            "✗ Configured implementation target does not match a workspace source root.\n"
            f"{configured}\n\n"
            "  Source roots:\n"
            f"{_candidate_lines()}\n\n"
            "  Fix: regenerate with 'echelon spec run <description> "
            "--target <source-path>'.\n"
            "       For a new repo, add --init."
            + (f"\n  Then rerun:  {rerun_command}" if rerun_command else ""),
            file=sys.stderr,
        )
        raise SystemExit(1)

    if not result.recommended_target:
        print(
            "✗ No implementation target configured and target detection was ambiguous.\n"
            "  Fix: start Phase A with 'echelon spec run <description> "
            "--target <source-path>'.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    source_root = (
        manifest.workspace.root
        if result.recommended_target == "."
        else (manifest.workspace.root / result.recommended_target).resolve()
    )
    source: SourceRoot | None = None
    for candidate in manifest.sources:
        candidate_root = (
            manifest.workspace.root
            if candidate.path == "."
            else (manifest.workspace.root / candidate.path).resolve()
        )
        if candidate_root == source_root:
            source = candidate
            break
    if source is None:
        print(
            "✗ Recommended implementation target does not match a workspace source root.\n"
            f"  Target: {result.recommended_target}",
            file=sys.stderr,
        )
        raise SystemExit(1)

    return HarnessWorkspaceTarget(
        workspace_root=manifest.workspace.root,
        workspace_git_role=manifest.workspace.git_role,
        source_root=source_root,
        source_id=source.id,
        source_git_role=source.git_role,
    )


def _workspace_target_dispatch_metadata(target: HarnessWorkspaceTarget) -> dict[str, object]:
    return {
        "workspace_root": target.workspace_root,
        "workspace_git_role": target.workspace_git_role,
        "source_ids": {str(target.source_root.resolve()): target.source_id},
        "source_git_roles": {str(target.source_root.resolve()): target.source_git_role},
    }


def _fsync_directory(path: Path) -> None:
    """Persist directory-entry changes needed by the delivery safety boundary."""
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_delivery_preparation_state(
    state_path: Path,
    payload: Mapping[str, object],
) -> None:
    """Atomically write Phase B evidence and persist every new directory entry."""
    from harness.lexicon_gate_io import write_json_atomic

    write_json_atomic(state_path, payload)
    _fsync_directory(state_path.parent)
    _fsync_directory(state_path.parent.parent)
    _fsync_directory(state_path.parent.parent.parent)


def _validate_locked_target_child_contract(
    *,
    project_root: Path,
    spec_dir: Path,
) -> None:
    """Fail closed when an orchestrated child's inherited target is stale."""
    target_env = os.environ.get("ECHELON_TARGET_REPO_PATH")
    if not target_env:
        return

    from harness.spec_frontmatter import read_canonical_target_entries

    expected_target_text = os.environ.get("ECHELON_TARGET_CONTRACT_JSON", "")
    expected_targets_text = os.environ.get("ECHELON_TARGETS_CONTRACT_JSON", "")
    try:
        expected_target = json.loads(expected_target_text)
        expected_targets = json.loads(expected_targets_text)
    except json.JSONDecodeError:
        expected_target = None
        expected_targets = None
    if not isinstance(expected_target, dict) or not isinstance(expected_targets, list):
        print(
            "✗ Target-child delivery is missing its inherited canonical target contract.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    canonical_targets = [
        dict(entry)
        for entry in read_canonical_target_entries(spec_dir)
    ]
    if canonical_targets != expected_targets or expected_target not in canonical_targets:
        print(
            "✗ Target-child delivery contract is stale; the canonical spec targets "
            "changed after dispatch. Restart delivery from the workspace root.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    implementation_target = os.environ.get("ECHELON_IMPLEMENTATION_TARGET", "")
    if implementation_target != str(expected_target.get("path") or ""):
        print(
            "✗ Target-child delivery metadata no longer matches the canonical target set.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    expected_path = (
        project_root
        if implementation_target == "."
        else project_root / implementation_target
    ).resolve()
    inherited_path = Path(target_env).resolve()
    source_root = Path(os.environ.get("ECHELON_SOURCE_ROOT") or target_env).resolve()
    if inherited_path != expected_path or source_root != expected_path:
        print(
            "✗ Target-child repository path no longer matches the canonical target contract.",
            file=sys.stderr,
        )
        raise SystemExit(1)


def _prepare_delivery_build_state(
    *,
    project_root: Path,
    harness_base_dir: Path,
    spec_id: str,
    spec_dir: Path,
) -> str:
    """Create durable Phase B evidence under the per-spec mutation lease."""
    from harness.paths import build_dir, make_build_id
    from echelon.spec_lifecycle import (
        PhaseAExecutionLock,
        SpecLifecycleLocked,
        SpecMutationLock,
    )

    operation_id = f"delivery-{os.getpid()}"
    try:
        with SpecMutationLock.acquire(project_root, spec_id, operation_id):
            with PhaseAExecutionLock.acquire(project_root, operation_id):
                _validate_locked_target_child_contract(
                    project_root=project_root,
                    spec_dir=spec_dir,
                )
                _block_if_harness_phase_a_not_ready(spec_dir, spec_id)
                build_id = make_build_id()
                _write_delivery_preparation_state(
                    build_dir(harness_base_dir, build_id) / "state.json",
                    {
                        "schema_version": 1,
                        "spec_id": spec_id,
                        "build_id": build_id,
                        "status": "preparing",
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    },
                )
                return build_id
    except SpecLifecycleLocked as exc:
        print(
            "✗ Cannot prepare delivery while the spec mutation lease is owned by "
            f"{exc.operation_id}.",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc


def _cmd_harness_run(
    args: list[str],
    *,
    command_prefix: str = "echelon delivery run",
    display_args: list[str] | None = None,
) -> None:
    import logging
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if not args:
        print(f"{command_prefix}: missing spec_id\n", file=sys.stderr)
        sys.exit(1)

    rerun_command = _command_display(command_prefix, display_args or args)
    _require_provider_capability(command_prefix, ProviderCapability.BUILD)
    _workspace_git_preflight(Path.cwd(), command_name=rerun_command)

    spec_id = args[0]
    kv: dict[str, str] = {}
    free_text: list[str] = []
    reset = "--reset" in args[1:]
    for arg in args[1:]:
        if arg == "--reset":
            continue
        if "=" in arg:
            k, _, v = arg.partition("=")
            kv[k.strip()] = v.strip()
        else:
            free_text.append(arg)
    strategy = kv.get("strategy", "default")
    mode = kv.get("mode", "semi")
    explicit_target = kv.get("target") or kv.get("target_source")
    if explicit_target:
        print(
            f"✗ {command_prefix} no longer accepts a target override.\n"
            "  Delivery consumes the implementation targets declared when Phase A began.\n"
            "  Start a new spec with: echelon spec run <description> "
            "--target <source-path> [--target <source-path> ...]",
            file=sys.stderr,
        )
        raise SystemExit(2)

    parts = [f"spec {spec_id}", f"{mode} mode", f"strategies={strategy}"]
    if kv.get("max_outer"):
        parts.append(f"max {kv['max_outer']} outer iterations")
    if kv.get("max_inner"):
        parts.append(f"max {kv['max_inner']} inner iterations")
    if kv.get("token_budget"):
        parts.append(f"token_budget={kv['token_budget']}")
    auto_merge = kv.get("auto_merge")
    if auto_merge is not None:
        if auto_merge.lower() in {"0", "false", "no", "off"}:
            parts.append("no_auto_merge")
        else:
            parts.append("auto_merge")
    kill_losers = kv.get("kill_losers")
    if kill_losers is not None and kill_losers.lower() not in {"0", "false", "no", "off"}:
        parts.append("kill_losers")
    if free_text:
        parts.append(f"task: {' '.join(free_text)}")
    if reset:
        parts.append("--reset")
    user_message = " ".join(parts)

    # Orchestrator mode: spec targets take priority over local echelon-config.yml.
    # Check targets first so a polyrepo root with its own echelon-config.yml (e.g. for
    # deploy) doesn't silently bypass target validation and run against the wrong repo.
    from harness.spec_frontmatter import (
        find_spec_dir,
        read_targets,
        write_status as _write_spec_status,
    )
    from harness.spec_snapshot import snapshot_spec_dir
    from echelon.orchestrator import (
        run_multi_target,
        validate_single_target,
        validate_targets,
    )

    target_env = os.environ.get("ECHELON_TARGET_REPO_PATH")
    polyrepo_env = os.environ.get("ECHELON_POLYREPO_ROOT")
    target_name_env = os.environ.get("ECHELON_TARGET_REPO_NAME")
    direct_target_path: Path | None = None
    spec_search_root = Path(polyrepo_env).resolve() if polyrepo_env else Path.cwd()
    harness_base_dir = Path.cwd()
    config_root = Path.cwd()
    if target_env and polyrepo_env:
        config_root = Path(polyrepo_env).resolve()
        harness_base_dir = (
            config_root
            / "runs"
            / "targets"
            / (target_name_env or Path(target_env).resolve().name)
        )
        _sync_polyrepo_runtime_extension(config_root, harness_base_dir)
    spec_dir = find_spec_dir(spec_id, spec_search_root)
    if spec_dir is not None:
        resolved_spec_id = spec_dir.name
        polyrepo_root = spec_dir.parent.parent
        try:
            snapshot_spec_dir(spec_dir, polyrepo_root)
        except OSError as e:
            print(
                "✗ Could not preserve spec artifacts before harness run.\n"
                f"  Error: {e}\n"
                "  Refusing to continue because untracked spec work could be lost.",
                file=sys.stderr,
            )
            sys.exit(1)
        targets_rel: list[str] = read_targets(spec_dir)
        if targets_rel and not target_env:
            _block_if_spec_task_targets_mismatch(
                spec_dir,
                targets_rel,
                resolved_spec_id,
            )
            if len(targets_rel) == 1:
                workspace_target = _resolve_harness_workspace_target(
                    polyrepo_root,
                    targets_rel[0],
                    spec_dir=spec_dir,
                    spec_id=resolved_spec_id,
                    rerun_command=rerun_command,
                )
                target_rel = (
                    "."
                    if workspace_target.source_root == workspace_target.workspace_root
                    else workspace_target.source_root.relative_to(workspace_target.workspace_root).as_posix()
                )
                if target_rel != targets_rel[0]:
                    print(
                        "✗ Declared implementation target is not a canonical workspace source path.\n"
                        f"  declared: {targets_rel[0]}\n"
                        f"  resolved: {target_rel}\n"
                        "  Delivery will not rewrite Phase A target metadata; regenerate the spec "
                        "with the resolved --target path.",
                        file=sys.stderr,
                    )
                    raise SystemExit(2)
                if workspace_target.source_root == workspace_target.workspace_root:
                    direct_target_path = workspace_target.source_root
                else:
                    target = validate_single_target([target_rel], polyrepo_root)
                    sys.exit(run_multi_target(
                        spec_id,
                        [target],
                        args[1:],
                        **_workspace_target_dispatch_metadata(workspace_target),
                    ))

            else:
                # A spec may declare multiple targets. run_multi_target assigns
                # canonical task ownership and serializes cross-target dependency
                # order so shared progress writes cannot race.
                targets = validate_targets(targets_rel, polyrepo_root)
                _block_if_harness_phase_a_not_ready(spec_dir, resolved_spec_id)
                source_ids: dict[str, str] = {}
                source_git_roles: dict[str, str] = {}
                for target in targets:
                    target_metadata = _source_dispatch_metadata(
                        target=target,
                        polyrepo_root=polyrepo_root,
                        source_id=None,
                    )
                    source_ids.update(target_metadata["source_ids"])
                    source_git_roles.update(target_metadata["source_git_roles"])
                dispatch_metadata: dict[str, object] = {
                    "workspace_root": polyrepo_root.resolve(),
                    "workspace_git_role": "orchestration",
                    "source_ids": source_ids,
                    "source_git_roles": source_git_roles,
                }
                sys.exit(run_multi_target(spec_id, targets, args[1:], **dispatch_metadata))

        if not target_env and direct_target_path is None:
            _print_missing_spec_target_error(spec_id, command_prefix=command_prefix)
            sys.exit(1)

    if not target_env and direct_target_path is None:
        _print_missing_spec_target_error(spec_id, command_prefix=command_prefix)
        sys.exit(1)

    from harness.config import load_config, ValidationError as HarnessValidationError
    from harness.docker_provider import DockerWorktreeProvider
    from harness.gitops import GitOpsManager
    from harness.skills.run_skill import run, _count_tasks
    from harness.plan_validation import PlanValidationError, validate_plan_file
    from harness.task_validation import TaskValidationError

    # Single-repo mode: require local Echelon harness config.
    echelon_yml = _project_echelon_config(config_root)
    if not echelon_yml.exists():
        print(
            "✗ Harness not initialised for this project.\n"
            f"  Expected: {echelon_yml}\n"
            "  Fix: run 'echelon delivery init' first, or add 'targets:' to your spec.",
            file=sys.stderr,
        )
        sys.exit(1)

    from harness.paths import mirror_path as _mirror_path_fn
    mirror_path = _mirror_path_fn(harness_base_dir)
    if not mirror_path.exists() and not target_env:
        print(
            "✗ Harness mirror not initialised for this project.\n"
            f"  Expected: {mirror_path}\n"
            "  Fix: run 'echelon delivery init' to create the mirror.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        config = load_config(project_root=config_root, squad_only=bool(target_env))
    except HarnessValidationError as e:
        _print_harness_config_error(e)
        sys.exit(1)
    if direct_target_path is not None:
        config.target_repo = str(direct_target_path.resolve())
        if not getattr(config, "target_default_branch", None):
            config.target_default_branch = "main"
        if getattr(config, "provider", None) not in {"docker", "e2b", "modal", "daytona"}:
            config.provider = "docker"
        _apply_target_verify_command_detection(
            config,
            target_repo=direct_target_path.resolve(),
            spec_id=spec_id,
        )
    elif target_env:
        target_repo_path = Path(target_env).resolve()
        config.target_repo = str(target_repo_path)
        if not getattr(config, "target_default_branch", None):
            config.target_default_branch = "main"
        if getattr(config, "provider", None) not in {"docker", "e2b", "modal", "daytona"}:
            config.provider = "docker"
        _apply_target_verify_command_detection(
            config,
            target_repo=target_repo_path,
            spec_id=spec_id,
        )
    gitops = GitOpsManager(config, base_dir=str(harness_base_dir))
    if target_env and not mirror_path.exists():
        gitops.clone_mirror(config.target_repo)
    provider = DockerWorktreeProvider(
        buffer_limit_bytes=config.buffer_limit_bytes,
        container_cli=_container_runtime_cli(config),
    )

    try:
        task_count = _count_tasks(spec_id, str(spec_search_root))
    except TaskValidationError as e:
        tasks_path = (
            spec_dir / "tasks.md"
            if spec_dir is not None
            else Path("specs") / spec_id / "tasks.md"
        )
        print(
            "✗ tasks.md is not in canonical format.\n"
            f"  Error: {e}\n"
            f"  Preview migration: python -m harness migrate-tasks {tasks_path}\n"
            f"  Apply migration:   python -m harness migrate-tasks {tasks_path} --write\n"
            f"  Then rerun:        {rerun_command}",
            file=sys.stderr,
        )
        sys.exit(1)
    if spec_dir is not None and (spec_dir / "plan.md").exists():
        try:
            validate_plan_file(spec_dir / "plan.md")
        except PlanValidationError as e:
            plan_path = spec_dir / "plan.md"
            print(
                "✗ plan.md is not in canonical format.\n"
                f"  Error: {e}\n"
                f"  Preview migration: python -m harness migrate-plan {plan_path}\n"
                f"  Apply migration:   python -m harness migrate-plan {plan_path} --write\n"
                f"  Then rerun:        {rerun_command}",
                file=sys.stderr,
            )
            sys.exit(1)

    if spec_dir is not None:
        _block_if_harness_phase_a_not_ready(spec_dir, spec_dir.name)

    assert spec_dir is not None
    delivery_build_id = _prepare_delivery_build_state(
        project_root=spec_dir.parent.parent,
        harness_base_dir=harness_base_dir,
        spec_id=spec_dir.name,
        spec_dir=spec_dir,
    )

    target_display = str(getattr(config, "target_repo", None) or "local")
    _banner("HARNESS RUN", [
        ("Spec", f"{spec_id}" + (f"  ({task_count} tasks)" if task_count else "")),
        ("Mode", mode),
        ("Strategy", strategy),
        ("Target", target_display),
    ])

    if spec_dir is not None:
        _write_spec_status(spec_dir, "in_progress")

    try:
        run(
            user_message,
            provider,
            gitops,
            base_dir=str(harness_base_dir),
            config=config,
            resume_build_id=delivery_build_id,
            orchestration_root=spec_search_root,
            summary_command=command_prefix,
        )
    except Exception as exc:
        if _is_docker_unavailable_error(exc):
            _mark_current_harness_state_blocked(
                harness_base_dir,
                spec_id,
                strategy,
                "docker_unavailable",
            )
            print(
                f"✗ {_container_runtime_display(config)} is not running or is unreachable.\n"
                f"  Error: {exc}\n"
                f"  Fix: {_container_runtime_fix(_container_runtime_cli(config))}, then rerun:\n"
                f"       {rerun_command}",
                file=sys.stderr,
            )
            sys.exit(1)
        _print_harness_error_and_exit(
            project_root=harness_base_dir,
            spec_id=spec_id,
            strategy=strategy,
            command=rerun_command,
            exc=exc,
        )


def _block_if_harness_phase_a_not_ready(spec_dir: Path, spec_id: str) -> None:
    """Fail before build LLM dispatch when published Phase A inputs are invalid."""
    readiness = validate_phase_a_readiness({"status": "done"}, [spec_dir])
    if readiness.ready:
        return

    blockers = "\n".join(f"  - {blocker}" for blocker in readiness.blockers)
    print(
        "✗ Phase A build inputs are not ready.\n"
        f"  Spec dir: {spec_dir}\n"
        "  Blockers:\n"
        f"{blockers}\n"
        "  Fix: run 'echelon spec continue' to republish Phase A artifacts, then rerun:\n"
        f"       echelon delivery run {spec_id}",
        file=sys.stderr,
    )
    sys.exit(1)


def _is_docker_unavailable_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return (
        ("docker" in message or "podman" in message)
        and (
            "daemon is running" in message
            or "docker api" in message
            or "docker.sock" in message
            or "podman.sock" in message
            or "cannot connect to the docker daemon" in message
            or "failed to connect" in message
            or "connection refused" in message
        )
    )


def _container_runtime_fix(container_cli: str) -> str:
    if container_cli == "podman":
        return "start the Podman machine (`podman machine start`) and wait until it reports running"
    return "start Docker Desktop and wait until it reports running"


def _container_runtime_cli(config: object) -> str:
    cli = getattr(config, "container_cli", "docker")
    if cli not in {"docker", "podman"}:
        return "docker"
    return cli


def _container_runtime_display(config: object) -> str:
    cli = _container_runtime_cli(config)
    return "Docker" if cli == "docker" else "Podman"


def _mark_current_harness_state_blocked(
    project_root: Path,
    spec_id: str,
    strategy: str,
    reason: str,
    error: str = "",
) -> None:
    try:
        from harness.paths import build_dir, current_build_marker, runs_dir
        from harness.state import DELIVERY_STATE_VERSION, StateStore

        marker = current_build_marker(project_root, spec_id)
        if marker.exists():
            state_dir = build_dir(project_root, marker.read_text().strip()) / "state"
        else:
            state_dir = runs_dir(project_root) / "state"
        state_store = StateStore(state_dir, spec_id, strategy)
        data = state_store.read()
        if not data:
            return
        status = data.get("status")
        if status in {"converged", "failed", "cancelled_by_coordinator"}:
            return
        if data.get("delivery_state_version") == DELIVERY_STATE_VERSION:
            if status == "blocked":
                phase = data.get("blocked_phase")
            elif status == "running":
                phase = "implementation"
            elif status == "validating":
                phase = "visual"
            elif status == "reviewing":
                phase = "review"
            elif status == "finalizing":
                phase = "finalization"
            elif status == "verified":
                phases = data.get("enabled_phases")
                completed = data.get("last_completed_phase")
                phase = "finalization"
                if isinstance(phases, list) and completed in phases:
                    index = phases.index(completed)
                    if index + 1 < len(phases):
                        phase = phases[index + 1]
            else:
                phase = "implementation"
            if phase not in {"implementation", "visual", "review", "finalization"}:
                phase = "implementation"
            updates = {"blocked_phase": phase, "termination_reason": reason}
            if error:
                updates["harness_error"] = error
            state_store.transition("blocked", updates=updates)
            return

        # Legacy state remains V1. The coordinator is the only component that
        # can select and snapshot its V2 phase plan from the active config.
        data["status"] = "blocked"
        data["termination_reason"] = reason
        if error:
            data["harness_error"] = error
        state_store.write(data)
    except Exception:
        pass


def _print_harness_error_and_exit(
    *,
    project_root: Path,
    spec_id: str,
    strategy: str,
    command: str,
    exc: Exception,
) -> None:
    _mark_current_harness_state_blocked(
        project_root,
        spec_id,
        strategy,
        "harness_error",
        str(exc),
    )
    print(
        "✗ Harness run failed before completion.\n"
        f"  Error: {exc}\n"
        "  State was marked blocked instead of left running.\n"
        f"  Next:  {command if spec_id in command else f'{command} {spec_id}'}",
        file=sys.stderr,
    )
    sys.exit(1)


def _refresh_harness_state_spec_paths(
    *,
    project_root: Path,
    spec_id: str,
    state: dict,
    state_store: object,
) -> tuple[dict, Path | None, bool]:
    """Refresh persisted harness artifact paths from the current project.

    Older or failed runs can retain stale paths in state. Resume must not trust
    those paths when the project has a resolvable current spec directory.
    """
    from harness.spec_frontmatter import find_spec_dir

    spec_dir = find_spec_dir(spec_id, project_root)
    if spec_dir is None:
        return state, None, False

    updates = {
        "spec_dir": str(spec_dir),
        "spec_file": str(spec_dir / "spec.md"),
        "tasks_file": str(spec_dir / "tasks.md"),
    }
    refreshed = dict(state)
    changed = any(str(refreshed.get(key) or "") != value for key, value in updates.items())
    if not changed:
        return state, spec_dir, False

    refreshed.update(updates)
    state_store.write(refreshed)  # type: ignore[attr-defined]
    return refreshed, spec_dir, True


def _harness_error_resume_blockers(*, project_root: Path, spec_id: str, spec_dir: Path | None) -> list[str]:
    """Return blockers that make a previous harness_error unsafe to retry."""
    if spec_dir is None:
        return [f"no spec directory found for {spec_id!r}"]

    blockers: list[str] = []
    from harness.task_validation import TaskValidationError, count_tasks_for_spec

    try:
        task_count = count_tasks_for_spec(spec_id, project_root)
    except TaskValidationError as exc:
        task_count = 0
        blockers.append(f"tasks.md is not canonical: {exc}")
    if task_count <= 0 and not any("tasks.md" in blocker for blocker in blockers):
        blockers.append("tasks.md has no canonical task rows")

    readiness = validate_phase_a_readiness({"status": "done"}, [spec_dir])
    if not readiness.ready:
        blockers.extend(readiness.blockers or ["Phase A build inputs are not ready"])
    return blockers


def _is_docs_report_only_containment_violation(state: dict) -> bool:
    """Return True for legacy containment blocks caused only by docs reports."""
    if state.get("termination_reason") != "containment_violation":
        return False

    violation = state.get("containment_violation")
    if not isinstance(violation, dict):
        return False

    changed_status = violation.get("changed_status")
    if not isinstance(changed_status, list) or not changed_status:
        return False

    return all(
        _is_allowed_external_documentation_status(str(line))
        for line in changed_status
    )


def _is_allowed_external_documentation_status(status_line: str) -> bool:
    path = _status_path(status_line)
    if not path.startswith("specs/"):
        return False
    return PurePosixPath(path).name in {
        "documentation-impact-report.md",
        "docs-verification-report.md",
    }


def _status_path(status_line: str) -> str:
    line = status_line.strip()
    if not line:
        return ""
    path = line[3:].strip() if len(status_line) >= 4 else line
    if " -> " in path:
        path = path.split(" -> ", 1)[1]
    return path.strip('"').replace("\\", "/")


def _is_phase_a_build_incomplete_retry(state: dict) -> bool:
    """Return True when build_incomplete should retry without git recovery."""
    if state.get("termination_reason") != "build_incomplete":
        return False
    if state.get("salvage_commit") or state.get("target_commit"):
        return False
    checkpoint_commits = state.get("checkpoint_commits")
    if isinstance(checkpoint_commits, list) and checkpoint_commits:
        return False

    build_status = str(state.get("build_status") or "").strip()
    build_reason = str(state.get("build_reason") or "")
    return (
        build_status == "phase_a_not_ready"
        or "Phase A artifacts are not build-ready" in build_reason
        or "constitution.md contains unresolved template markers" in build_reason
    )


def _parse_harness_resume_args(args: list[str]) -> tuple[str, dict[str, str], str]:
    spec_id = args[0]
    kv: dict[str, str] = {}
    answer_parts: list[str] = []
    i = 1
    while i < len(args):
        arg = args[i]
        if arg in {"--mode", "--strategy"} and i + 1 < len(args):
            kv[arg.removeprefix("--")] = args[i + 1].strip()
            i += 2
            continue
        if arg.startswith("--mode="):
            kv["mode"] = arg.partition("=")[2].strip()
        elif arg.startswith("--strategy="):
            kv["strategy"] = arg.partition("=")[2].strip()
        elif "=" in arg:
            key, _, value = arg.partition("=")
            key = key.strip()
            if key in {"mode", "strategy"}:
                kv[key] = value.strip()
            elif key == "answer":
                answer_parts.append(value.strip())
            else:
                answer_parts.append(arg)
        else:
            answer_parts.append(arg)
        i += 1
    return spec_id, kv, " ".join(part for part in answer_parts if part).strip()


def _cmd_harness_resume(
    args: list[str],
    *,
    command_prefix: str = "echelon delivery resume",
    display_args: list[str] | None = None,
    require_answer: bool = True,
) -> None:
    import logging
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if not args or args[0] in ("-h", "--help"):
        print(
            f"Usage: {command_prefix} <spec_id> [strategy=<s>] [mode=<guided|semi|banzai>] [answer]\n\n"
            "Resume or continue a blocked delivery run.\n"
            "Supports blocker_escalation, verify_command_needed,\n"
            "checkpoint continuation, repaired harness_error, docker_unavailable,\n"
            "and recovery from build_incomplete/publish_failed committed work.\n\n"
            "Steps:\n"
            "  1. Fix the blocker shown by the previous delivery output.\n"
            "     For blocker_escalation: pass the answer to 'echelon delivery resume'.\n"
            "     For verify_command_needed: add verify_command to echelon-config.yml\n"
            "     (or re-run 'echelon delivery init' to auto-detect high-confidence commands).\n"
            "  2. Run: echelon delivery continue <spec_id> when no answer is needed.\n",
        )
        return

    rerun_command = _command_display(command_prefix, display_args or args)
    _require_provider_capability(command_prefix, ProviderCapability.BUILD)
    spec_id, kv, resume_answer = _parse_harness_resume_args(args)
    strategy = kv.get("strategy", "default")
    mode = kv.get("mode", "semi")
    target_resume_command = "resume" if require_answer else "continue"

    from harness.config import load_config, ValidationError as HarnessValidationError
    from harness.docker_provider import DockerWorktreeProvider
    from harness.gitops import GitOpsManager
    from harness.paths import build_dir, current_build_marker, runs_dir
    from harness.spec_frontmatter import find_spec_dir, read_targets
    from harness.state import StateStore

    target_env = os.environ.get("ECHELON_TARGET_REPO_PATH")
    polyrepo_env = os.environ.get("ECHELON_POLYREPO_ROOT")
    target_name_env = os.environ.get("ECHELON_TARGET_REPO_NAME")
    direct_target_path: Path | None = None
    cwd = Path.cwd()
    spec_search_root = Path(polyrepo_env).resolve() if polyrepo_env else cwd
    harness_base_dir = cwd
    config_root = cwd
    if target_env and polyrepo_env:
        config_root = Path(polyrepo_env).resolve()
        harness_base_dir = (
            config_root
            / "runs"
            / "targets"
            / (target_name_env or Path(target_env).resolve().name)
        )
        _sync_polyrepo_runtime_extension(config_root, harness_base_dir)

    spec_dir = find_spec_dir(spec_id, spec_search_root)
    if spec_dir is not None and not target_env:
        from echelon.orchestrator import (
            run_multi_target,
            validate_single_target,
            validate_targets,
        )

        resolved_spec_id = spec_dir.name
        polyrepo_root = spec_dir.parent.parent
        targets_rel: list[str] = read_targets(spec_dir)
        if targets_rel:
            _block_if_spec_task_targets_mismatch(
                spec_dir,
                targets_rel,
                resolved_spec_id,
            )
            if len(targets_rel) == 1:
                workspace_target = _resolve_harness_workspace_target(
                    polyrepo_root,
                    targets_rel[0],
                    spec_dir=spec_dir,
                    spec_id=resolved_spec_id,
                    rerun_command=rerun_command,
                )
                target_rel = (
                    "."
                    if workspace_target.source_root == workspace_target.workspace_root
                    else workspace_target.source_root.relative_to(
                        workspace_target.workspace_root
                    ).as_posix()
                )
                if workspace_target.source_root == workspace_target.workspace_root:
                    direct_target_path = workspace_target.source_root
                else:
                    target = validate_single_target([target_rel], polyrepo_root)
                    sys.exit(
                        run_multi_target(
                            spec_id,
                            [target],
                            args[1:],
                            command=target_resume_command,
                            **_workspace_target_dispatch_metadata(workspace_target),
                        )
                    )

            else:
                targets = validate_targets(targets_rel, polyrepo_root)
                source_ids: dict[str, str] = {}
                source_git_roles: dict[str, str] = {}
                for target in targets:
                    target_metadata = _source_dispatch_metadata(
                        target=target,
                        polyrepo_root=polyrepo_root,
                        source_id=None,
                    )
                    source_ids.update(target_metadata["source_ids"])
                    source_git_roles.update(target_metadata["source_git_roles"])
                    sys.exit(
                        run_multi_target(
                            spec_id,
                            targets,
                            args[1:],
                            workspace_root=polyrepo_root.resolve(),
                            workspace_git_role="orchestration",
                            source_ids=source_ids,
                            source_git_roles=source_git_roles,
                            command=target_resume_command,
                        )
                    )

            if direct_target_path is None:
                _print_missing_spec_target_error(spec_id, command_prefix=command_prefix)
                sys.exit(1)

    if not target_env and direct_target_path is None:
        _print_missing_spec_target_error(spec_id, command_prefix=command_prefix)
        sys.exit(1)

    echelon_yml = _project_echelon_config(config_root)
    if not echelon_yml.exists():
        print(
            "✗ Harness not initialised for this project.\n"
            f"  Expected: {echelon_yml}\n"
            "  Fix: run 'echelon delivery init' first.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        config = load_config(project_root=config_root, squad_only=bool(target_env))
    except HarnessValidationError as e:
        _print_harness_config_error(e)
        sys.exit(1)
    if direct_target_path is not None:
        config.target_repo = str(direct_target_path.resolve())
        if not getattr(config, "target_default_branch", None):
            config.target_default_branch = "main"
        if getattr(config, "provider", None) not in {"docker", "e2b", "modal", "daytona"}:
            config.provider = "docker"
        _apply_target_verify_command_detection(
            config,
            target_repo=direct_target_path.resolve(),
            spec_id=spec_id,
        )
    elif target_env:
        target_repo_path = Path(target_env).resolve()
        config.target_repo = str(target_repo_path)
        if not getattr(config, "target_default_branch", None):
            config.target_default_branch = "main"
        if getattr(config, "provider", None) not in {"docker", "e2b", "modal", "daytona"}:
            config.provider = "docker"
        _apply_target_verify_command_detection(
            config,
            target_repo=target_repo_path,
            spec_id=spec_id,
        )

    # Resolve state_dir from the current-build marker; fall back to runs/state/
    # for runs that pre-date build_id or were started without one.
    marker = current_build_marker(harness_base_dir, spec_id)
    build_id = marker.read_text().strip() if marker.exists() else ""
    if marker.exists():
        state_dir = build_dir(harness_base_dir, build_id) / "state"
    else:
        state_dir = runs_dir(harness_base_dir) / "state"
    state_store = StateStore(state_dir, spec_id, strategy)
    state = state_store.read()
    if not _workspace_git_present(cwd):
        if state:
            _print_legacy_branchless_recovery_notice(
                rerun_command
            )
        else:
            _workspace_git_preflight(
                cwd,
                command_name=rerun_command,
            )

    if not state:
        print(
            f"✗ No harness state found for spec {spec_id!r} (strategy={strategy!r}).\n"
            "  Run 'echelon delivery run <spec_id>' to start a new run.",
            file=sys.stderr,
        )
        sys.exit(1)

    state, resolved_spec_dir, spec_paths_refreshed = _refresh_harness_state_spec_paths(
        project_root=spec_search_root,
        spec_id=spec_id,
        state=state,
        state_store=state_store,
    )

    current_status = state.get("status", "unknown")
    termination_reason = state.get("termination_reason", "")
    if (
        state.get("build_status") == "provider_session_limit"
        and termination_reason in {"build_incomplete", "publish_failed"}
    ):
        state["termination_reason"] = "provider_session_limit"
        state_store.write(state)
        termination_reason = "provider_session_limit"
    recoverable_reasons = {"build_incomplete", "publish_failed"}
    continuation_reasons = {
        "blocker_escalation",
        "checkpoint_outer_cap",
        "docker_unavailable",
        "no_progress",
        "provider_session_limit",
        "target_merge_failed",
    }
    if _is_docs_report_only_containment_violation(state):
        continuation_reasons.add("containment_violation")
    retryable_error_reasons = {"harness_error"}

    if current_status != "blocked" and termination_reason not in recoverable_reasons:
        print(
            f"✗ Spec {spec_id!r} is not blocked (status={current_status!r}).\n"
            "  Use 'echelon delivery run <spec_id>' to start or continue.",
            file=sys.stderr,
        )
        sys.exit(1)

    if termination_reason not in {
        "verify_command_needed",
        *recoverable_reasons,
        *continuation_reasons,
        *retryable_error_reasons,
    }:
        if termination_reason == "build_blocked":
            build_reason = str(state.get("build_reason") or "the build agent reported a blocker")
            print(
                f"✗ Spec {spec_id!r} is blocked by the build agent.\n"
                f"  Blocker: {build_reason}\n"
                "  Resolve the blocker; do not retry delivery until it is resolved.\n"
                f"  For a spec decision: echelon spec reopen {spec_id}\n"
                f"  Then start a new delivery run: echelon delivery run {spec_id}",
                file=sys.stderr,
            )
            sys.exit(1)
        print(
            f"✗ Spec {spec_id!r} is blocked for unsupported resume reason: {termination_reason!r}.\n"
            f"  This is delivery state, not spec-planning state.\n"
            f"  State file: {state_store.state_file}\n"
            f"  After fixing the blocker, retry: echelon delivery resume {spec_id}\n"
            f"  To discard this blocked delivery state and start fresh: echelon delivery run {spec_id} --reset",
            file=sys.stderr,
        )
        sys.exit(1)

    gitops = GitOpsManager(config, base_dir=str(harness_base_dir))
    escalation_file = state.get("escalation_file")
    if resume_answer and escalation_file:
        from harness.escalation import EscalationHandler

        EscalationHandler(str(build_dir(harness_base_dir, build_id))).resume(
            str(escalation_file),
            resume_answer,
        )
    elif require_answer and escalation_file:
        print(
            f"✗ Spec {spec_id!r} is waiting for a delivery answer.\n"
            f"  Escalation file: {escalation_file}\n"
            f"  Answer with: echelon delivery resume {spec_id} \"<answer>\"\n"
            f"  If no answer is needed, continue with: echelon delivery continue {spec_id}",
            file=sys.stderr,
        )
        sys.exit(1)
    elif require_answer and not resume_answer:
        print(
            "delivery resume without an answer is deprecated; "
            f"use echelon delivery continue {spec_id} when no answer is needed.",
            file=sys.stderr,
        )

    if _is_phase_a_build_incomplete_retry(state):
        blockers = _harness_error_resume_blockers(
            project_root=spec_search_root,
            spec_id=spec_id,
            spec_dir=resolved_spec_dir,
        )
        if blockers:
            print(
                f"✗ Spec {spec_id!r} is still blocked after Phase A repair.\n"
                "  Resume preflight failed:\n"
                + "".join(f"  - {blocker}\n" for blocker in blockers)
                + f"  Fix the blockers, then re-run: echelon delivery resume {spec_id}",
                file=sys.stderr,
            )
            sys.exit(1)

        fields = [
            ("Spec", spec_id),
            ("Strategy", strategy),
            ("Reason", "phase_a_repaired"),
        ]
        if resolved_spec_dir is not None:
            fields.append(("Spec dir", str(resolved_spec_dir)))
        if spec_paths_refreshed:
            fields.append(("State", "refreshed stale spec artifact paths"))
        _banner("HARNESS RESUME — RETRYING", fields)

        from harness.skills.run_skill import run
        provider = DockerWorktreeProvider(
            buffer_limit_bytes=config.buffer_limit_bytes,
            container_cli=_container_runtime_cli(config),
        )
        user_message = f"spec {spec_id} strategy={strategy} mode={mode} resume"
        try:
            run(
                user_message,
                provider,
                gitops,
                base_dir=str(harness_base_dir),
                config=config,
                resume_build_id=build_id or None,
                orchestration_root=spec_search_root,
                summary_command=command_prefix,
            )
        except Exception as exc:
            if _is_docker_unavailable_error(exc):
                _mark_current_harness_state_blocked(
                    harness_base_dir,
                    spec_id,
                    strategy,
                    "docker_unavailable",
                )
                print(
                    f"✗ {_container_runtime_display(config)} is not running or is unreachable.\n"
                    f"  Error: {exc}\n"
                    f"  Fix: {_container_runtime_fix(_container_runtime_cli(config))}, then rerun:\n"
                    f"       echelon delivery continue {spec_id}",
                    file=sys.stderr,
                )
                sys.exit(1)
            _print_harness_error_and_exit(
                project_root=harness_base_dir,
                spec_id=spec_id,
                strategy=strategy,
                command=rerun_command,
                exc=exc,
            )
        _exit_if_provider_session_limited(state_store)
        return

    if termination_reason in retryable_error_reasons:
        blockers = _harness_error_resume_blockers(
            project_root=spec_search_root,
            spec_id=spec_id,
            spec_dir=resolved_spec_dir,
        )
        if blockers:
            print(
                f"✗ Spec {spec_id!r} is still blocked after the previous harness error.\n"
                "  Resume preflight failed:\n"
                + "".join(f"  - {blocker}\n" for blocker in blockers)
                + f"  Fix the blockers, then re-run: echelon delivery resume {spec_id}",
                file=sys.stderr,
            )
            sys.exit(1)

        fields = [
            ("Spec", spec_id),
            ("Strategy", strategy),
            ("Reason", termination_reason),
        ]
        if resolved_spec_dir is not None:
            fields.append(("Spec dir", str(resolved_spec_dir)))
        if spec_paths_refreshed:
            fields.append(("State", "refreshed stale spec artifact paths"))
        _banner("HARNESS RESUME — RETRYING", fields)

        from harness.skills.run_skill import run
        provider = DockerWorktreeProvider(
            buffer_limit_bytes=config.buffer_limit_bytes,
            container_cli=_container_runtime_cli(config),
        )
        user_message = f"spec {spec_id} strategy={strategy} mode={mode} resume"
        try:
            run(
                user_message,
                provider,
                gitops,
                base_dir=str(harness_base_dir),
                config=config,
                resume_build_id=build_id or None,
                orchestration_root=spec_search_root,
                summary_command=command_prefix,
            )
        except Exception as exc:
            if _is_docker_unavailable_error(exc):
                _mark_current_harness_state_blocked(
                    harness_base_dir,
                    spec_id,
                    strategy,
                    "docker_unavailable",
                )
                print(
                    f"✗ {_container_runtime_display(config)} is not running or is unreachable.\n"
                    f"  Error: {exc}\n"
                    f"  Fix: {_container_runtime_fix(_container_runtime_cli(config))}, then rerun:\n"
                    f"       echelon delivery continue {spec_id}",
                    file=sys.stderr,
                )
                sys.exit(1)
            _print_harness_error_and_exit(
                project_root=harness_base_dir,
                spec_id=spec_id,
                strategy=strategy,
                command=rerun_command,
                exc=exc,
            )
        _exit_if_provider_session_limited(state_store)
        return

    if termination_reason in recoverable_reasons:
        from harness.recovery import HarnessRecoveryError, recover_blocked_run

        recovery_project_dir = Path(
            str(
                state.get("target_repo_path")
                or state.get("target_path")
                or state.get("source_root")
                or config.target_repo
                or harness_base_dir
            )
        )
        if not recovery_project_dir.is_absolute():
            recovery_project_dir = (config_root / recovery_project_dir).resolve()

        try:
            recovered = recover_blocked_run(
                project_dir=recovery_project_dir,
                spec_id=spec_id,
                strategy_id=strategy,
                state=state,
                gitops=gitops,
                build_id=build_id,
            )
        except HarnessRecoveryError as e:
            print(
                f"✗ Harness recovery failed for spec {spec_id!r}: {e}",
                file=sys.stderr,
            )
            sys.exit(1)

        action = "applied" if recovered.applied else "already present"
        fields = [
            ("Spec", spec_id),
            ("Strategy", strategy),
            ("Reason", termination_reason),
            ("Source", recovered.source),
            ("Commit", recovered.commit[:12]),
            ("Branch", recovered.target_branch),
            ("Status", action),
        ]
        if recovered.backed_up_untracked:
            fields.append(("Untracked backups", str(len(recovered.backed_up_untracked))))
            fields.append(("Backup dir", recovered.backup_dir))
        _banner("HARNESS RESUME — RECOVERED", fields)

        from harness.skills.run_skill import run
        provider = DockerWorktreeProvider(
            buffer_limit_bytes=config.buffer_limit_bytes,
            container_cli=_container_runtime_cli(config),
        )
        user_message = f"spec {spec_id} strategy={strategy} mode={mode} resume"
        try:
            run(
                user_message,
                provider,
                gitops,
                base_dir=str(harness_base_dir),
                config=config,
                resume_build_id=build_id or None,
                orchestration_root=spec_search_root,
                summary_command=command_prefix,
            )
        except Exception as exc:
            if _is_docker_unavailable_error(exc):
                _mark_current_harness_state_blocked(
                    harness_base_dir,
                    spec_id,
                    strategy,
                    "docker_unavailable",
                )
                print(
                    f"✗ {_container_runtime_display(config)} is not running or is unreachable.\n"
                    f"  Error: {exc}\n"
                    f"  Fix: {_container_runtime_fix(_container_runtime_cli(config))}, then rerun:\n"
                    f"       echelon delivery continue {spec_id}",
                    file=sys.stderr,
                )
                sys.exit(1)
            _print_harness_error_and_exit(
                project_root=harness_base_dir,
                spec_id=spec_id,
                strategy=strategy,
                command=rerun_command,
                exc=exc,
            )
        _exit_if_provider_session_limited(state_store)
        return

    if not config.verify_command:
        print(
            _format_missing_verify_command_resume_message(echelon_yml, spec_id),
            file=sys.stderr,
        )
        sys.exit(1)

    _banner("HARNESS RESUME", [
        ("Spec", spec_id),
        ("Strategy", strategy),
        ("Verify", config.verify_command),
    ])

    from harness.skills.run_skill import run
    provider = DockerWorktreeProvider(
        buffer_limit_bytes=config.buffer_limit_bytes,
        container_cli=_container_runtime_cli(config),
    )
    user_message = f"spec {spec_id} strategy={strategy} mode={mode} resume"
    try:
        run(
            user_message,
            provider,
            gitops,
            base_dir=str(harness_base_dir),
            config=config,
            resume_build_id=build_id or None,
            orchestration_root=spec_search_root,
            summary_command=command_prefix,
        )
    except Exception as exc:
        if _is_docker_unavailable_error(exc):
            _mark_current_harness_state_blocked(
                harness_base_dir,
                spec_id,
                strategy,
                "docker_unavailable",
            )
            print(
                f"✗ {_container_runtime_display(config)} is not running or is unreachable.\n"
                f"  Error: {exc}\n"
                f"  Fix: {_container_runtime_fix(_container_runtime_cli(config))}, then rerun:\n"
                f"       echelon delivery continue {spec_id}",
                file=sys.stderr,
            )
            sys.exit(1)
        _print_harness_error_and_exit(
            project_root=harness_base_dir,
            spec_id=spec_id,
            strategy=strategy,
            command=rerun_command,
            exc=exc,
        )
    _exit_if_provider_session_limited(state_store)


def _cmd_harness_continue(
    args: list[str],
    *,
    command_prefix: str = "echelon delivery continue",
    display_args: list[str] | None = None,
) -> None:
    _cmd_harness_resume(
        args,
        command_prefix=command_prefix,
        display_args=display_args,
        require_answer=False,
    )


def _exit_if_provider_session_limited(state_store: object) -> None:
    """Return a nonzero target status for a resumable provider-exhaustion block."""
    read = getattr(state_store, "read", None)
    state = read() if callable(read) else {}
    if (
        isinstance(state, dict)
        and state.get("status") == "blocked"
        and state.get("termination_reason") == "provider_session_limit"
        and state.get("build_status") == "provider_session_limit"
    ):
        raise SystemExit(2)


_RUNS_GITIGNORE_PATTERNS = (
    "**/.echelon/checkpoints.json",
    "**/.echelon/checkpoints.lock",
    "**/.echelon/.checkpoints.json.*.tmp",
    "*/state.json",
    "*/*.tmp",
    ".current*",
)


def _ensure_runs_gitignore(gitignore: Path) -> None:
    lines = gitignore.read_text(encoding="utf-8").splitlines() if gitignore.exists() else []
    missing = [pattern for pattern in _RUNS_GITIGNORE_PATTERNS if pattern not in lines]
    if not missing:
        return
    gitignore.write_text("\n".join([*lines, *missing]) + "\n", encoding="utf-8")


def _setup_run_dir(project_root: Path, run_id: str) -> Path:
    """Create runs/<run_id>/ + staging/, write runs/.gitignore, update runs/.current."""
    from harness.paths import runs_dir
    runs_root = runs_dir(project_root)
    runs_root.mkdir(exist_ok=True)

    _ensure_runs_gitignore(runs_root / ".gitignore")

    run_dir = runs_root / run_id
    run_dir.mkdir(exist_ok=True)
    (run_dir / "staging").mkdir(exist_ok=True)

    (runs_root / ".current").write_text(f"{run_id}\n")
    return run_dir


def _find_current_run_dir(project_root: Path) -> Optional[Path]:
    """Return the active run dir from a .current pointer, or the newest run dir.

    Checks runs/.current first, then falls back to the newest run directory
    with state.json when no pointer exists.
    """
    base_dir = project_root / "runs"
    current_file = base_dir / ".current"
    if current_file.exists():
        run_id = current_file.read_text().strip()
        if run_id:
            run_dir = base_dir / run_id
            if run_dir.exists():
                return run_dir
    # No .current pointer — fall back to newest run dir that has state.json
    all_runs = _iter_run_dirs(project_root)
    return all_runs[0] if all_runs else None


_REWIND_CLEANUP_OUTPUTS: dict[str, tuple[str, ...]] = {
    "phase3-sentinel": (
        "test-strategy.md",
        "test-architecture.md",
        "coverage-map.md",
    ),
    "phase3-plan": (
        "tasks.md",
        "critical-path.md",
        "risk-matrix.md",
        "dependencies.md",
    ),
}


@dataclass(frozen=True)
class _RunRecoveryAction:
    kind: str
    reason: str = ""
    phase: str = ""
    command: str = ""
    note: str = ""


@dataclass(frozen=True)
class _RuntimeBundleCompatibility:
    compatible: bool
    command: str = ""
    note: str = ""


def _runtime_bundle_compatibility(
    project_root: Path,
) -> _RuntimeBundleCompatibility:
    """Validate the deployed Echelon runtime needed for safe retry."""
    missing = _runtime_bundle_missing_paths(project_root)
    if missing:
        return _RuntimeBundleCompatibility(
            compatible=False,
            command="echelon workspace migrate-to-prosaic",
            note=(
                "the deployed Echelon runtime is incomplete: "
                + ", ".join(missing)
            ),
        )
    return _RuntimeBundleCompatibility(
        compatible=True,
        note="deployed Prosaic and runtime bundles are available",
    )


def _recovery_action_from_instruction(
    instruction: RecoveryInstruction,
    *,
    run_state: dict,
    project_root: Path | None,
) -> _RunRecoveryAction:
    kind = instruction.kind
    reason = instruction.reason_code
    phase = instruction.phase

    if kind == RecoveryKind.SYNC_RUNTIME_THEN_RETRY:
        compatibility = (
            _runtime_bundle_compatibility(project_root)
            if project_root is not None
            else _RuntimeBundleCompatibility(compatible=True)
        )
        if not compatibility.compatible:
            return _RunRecoveryAction(
                "manual_recovery",
                reason=reason,
                phase=phase,
                command=compatibility.command,
                note=compatibility.note,
            )
        return _RunRecoveryAction(
            "retry_phase",
            reason=reason,
            phase=phase,
            command="echelon spec continue",
            note="runtime contracts are compatible; the blocked phase will retry without rewind",
        )
    if kind in {RecoveryKind.RETRY_PHASE, RecoveryKind.WAIT_FOR_PROVIDER}:
        return _RunRecoveryAction(
            "retry_phase",
            reason=reason,
            phase=phase,
            command="echelon spec continue",
            note=(
                "wait for the provider reset, then retry the blocked phase"
                if kind == RecoveryKind.WAIT_FOR_PROVIDER
                else "will retry the blocked phase without rewind"
            ),
        )
    if kind == RecoveryKind.RESOLVE_DECISION:
        return _RunRecoveryAction(
            "resolve_decision",
            reason=reason,
            phase=phase,
            command="echelon spec continue",
            note="the controller will resolve the persisted decision using its sealed autonomy mode",
        )
    if kind == RecoveryKind.AWAIT_HUMAN_ANSWER:
        return _RunRecoveryAction(
            "human_resume",
            reason=reason,
            phase=phase,
            command='echelon spec resume "<your answer>"',
            note=str(run_state.get("escalation_question") or "").strip(),
        )
    if kind == RecoveryKind.RESOLVE_ISSUE:
        return _RunRecoveryAction(
            "manual_recovery",
            reason=reason,
            phase=phase,
            command='echelon spec resolve ISS-<n> "<project decision>"',
            note="resolve the first unresolved issue before continuing",
        )
    if kind == RecoveryKind.SAFE_REWIND:
        return _RunRecoveryAction(
            "safe_rewind",
            reason=reason,
            phase=phase,
            command=_command_display("echelon spec rewind", [phase]),
            note="safe checkpoint cleanup is required before retry",
        )
    if kind == RecoveryKind.INCREASE_BUDGET:
        return _RunRecoveryAction(
            "manual_recovery",
            reason=reason,
            command="increase analysis.token_budget_k, then echelon spec continue",
            note="the run cannot continue until the configured budget is higher",
        )
    if kind == RecoveryKind.MANUAL_REPAIR:
        return _RunRecoveryAction(
            "manual_recovery",
            reason=reason,
            phase=phase,
            command=_command_display("echelon phase run", [phase]),
            note="run the recorded deterministic repair before continuing",
        )
    if kind == RecoveryKind.MANUAL_DIAGNOSIS:
        return _RunRecoveryAction(
            "manual_recovery",
            reason=reason,
            command="inspect echelon spec status, then diagnose the failed decision",
            note="the controller exhausted automatic decision resolution",
        )
    return _RunRecoveryAction(
        "manual_recovery",
        reason=reason,
        command="inspect echelon spec status, then choose a recovery action",
        note="the controller recorded that automatic recovery is unsafe",
    )


def _active_versioned_decision(
    state: Mapping[str, object],
) -> dict[str, object] | None:
    """Return one exact unresolved v2/v3 decision authority."""
    decision = _validated_versioned_decision(state)
    if decision is None:
        return None
    return (
        decision
        if decision["status"]
        in {"pending", "resolving", "awaiting_human", "failed"}
        else None
    )


def _active_v2_decision(state: dict) -> dict[str, object] | None:
    """Compatibility view retained for callers auditing legacy v2 state."""
    raw_decision = state.get("blocked_decision")
    if not isinstance(raw_decision, dict) or raw_decision.get("schema_version") != 2:
        return None
    return _active_versioned_decision(state)


def _validated_versioned_decision(
    state: Mapping[str, object],
) -> dict[str, object] | None:
    """Validate a persisted v2/v3 decision and its exact recovery pair."""
    from harness.blocked_decision import validate_blocked_decision
    from harness.recovery_instruction import validate_decision_recovery_pair

    raw_decision = state.get("blocked_decision")
    if (
        not isinstance(raw_decision, Mapping)
        or raw_decision.get("schema_version") not in {2, 3}
    ):
        return None
    decision = validate_blocked_decision(raw_decision)
    validate_decision_recovery_pair(
        decision,
        state.get("recovery_instruction"),
    )
    return decision


def _v2_automatic_decision_is_registered(
    decision: Mapping[str, object],
    *,
    project_root: Path | None,
    graph: object | None = None,
) -> bool:
    """Reconstruct intrinsic v2 automatic eligibility from registered policy."""
    if decision.get("schema_version") != 2 or project_root is None:
        return False
    try:
        from harness.human_input import v2_automatic_decision_is_registered

        if graph is None:
            from harness.phase_graph import load_workspace_phase_graph

            graph, _ = load_workspace_phase_graph(project_root)
        registry = graph.human_input_policy_registry()
        policy = registry.lookup(
            str(decision.get("source_kind") or ""),
            str(decision.get("producer_id") or ""),
            str(decision.get("reason_code") or ""),
        )
        return v2_automatic_decision_is_registered(decision, policy)
    except (AttributeError, KeyError, OSError, TypeError, ValueError):
        return False


def _automatic_decision_is_eligible(
    decision: Mapping[str, object],
    *,
    project_root: Path | None,
    graph: object | None = None,
) -> bool:
    if decision.get("schema_version") == 3:
        return decision.get("automatic_eligible") is True
    return _v2_automatic_decision_is_registered(
        decision,
        project_root=project_root,
        graph=graph,
    )


def _decision_gate_rewind_action(
    run_state: Mapping[str, object],
    decision: Mapping[str, object],
    *,
    project_root: Path | None,
) -> _RunRecoveryAction | None:
    if project_root is None:
        return None
    source_phase = str(decision.get("source_phase") or "").strip()
    spec_dir, _ = _normalize_rewind_spec_dir(project_root, dict(run_state))
    if spec_dir is None or not source_phase:
        return None
    from harness.phase_checkpoints import load_checkpoint_ledger

    try:
        ledger = load_checkpoint_ledger(spec_dir)
    except (KeyError, OSError, TypeError, ValueError):
        return None
    candidates = [
        checkpoint
        for checkpoint in ledger.checkpoints
        if checkpoint.rewind == "supported"
        and checkpoint.next_phase == source_phase
    ]
    if not candidates:
        return None
    checkpoint = candidates[-1]
    duplicate_phase = sum(
        item.phase == checkpoint.phase for item in ledger.checkpoints
    ) > 1
    command_args = [checkpoint.phase]
    if duplicate_phase:
        command_args.extend(("--commit", checkpoint.commit))
    command_args.extend(("--next-phase", source_phase, "--confirm"))
    return _RunRecoveryAction(
        "safe_rewind",
        reason=str(run_state.get("blocked_reason") or "gate_rejected"),
        phase=checkpoint.phase,
        command=_command_display("echelon spec rewind", command_args),
        note=(
            "rewind the exact checkpoint ledger predecessor before replaying "
            "the human gate"
        ),
    )


def _versioned_decision_recovery_action(
    run_state: Mapping[str, object],
    *,
    project_root: Path | None,
) -> _RunRecoveryAction | None:
    decision = _validated_versioned_decision(run_state)
    if decision is None:
        return None
    status = decision["status"]
    source_kind = decision["source_kind"]
    if (
        status == "resolved"
        and source_kind == "human_gate"
        and str(run_state.get("blocked_reason") or "").strip()
        == "gate_rejected"
    ):
        return _decision_gate_rewind_action(
            run_state,
            decision,
            project_root=project_root,
        )
    if (
        status != "failed"
        or decision.get("autonomy_mode") != "banzai"
        or run_state.get("autonomy_mode") != "banzai"
        or not _automatic_decision_is_eligible(
            decision,
            project_root=project_root,
        )
    ):
        return None
    if source_kind == "human_gate":
        return _decision_gate_rewind_action(
            run_state,
            decision,
            project_root=project_root,
        )
    if source_kind not in {"provider_escalation", "controller_safeguard"}:
        return None
    source_phase = str(decision.get("source_phase") or "").strip()
    if not source_phase or project_root is None:
        return None
    try:
        from harness.phase_graph import load_workspace_phase_graph

        graph, _ = load_workspace_phase_graph(project_root)
        if source_phase not in graph.all_phase_ids():
            return None
    except (KeyError, OSError, TypeError, ValueError):
        return None
    reason = str(decision.get("failure_code") or "").strip() or str(
        run_state.get("blocked_reason") or decision.get("reason_code") or ""
    ).strip()
    return _RunRecoveryAction(
        "manual_recovery",
        reason=reason,
        phase=source_phase,
        command=_command_display("echelon phase run", [source_phase]),
        note="replay the exact failed automatic decision source phase",
    )


def _retryable_failed_agent_block_phase(run_state: dict) -> str | None:
    """Return the retry phase for a legacy bare-agent-block decision.

    Older controllers treated a bare agent ``BLOCKED`` envelope as material and
    could make a run unrecoverable after COMMANDER's provider retries failed.
    Because this decision records neither an agent reason nor a real question,
    retrying its source phase is safer than asking the operator to invent one.
    The identity check is deliberately narrow so genuine failed decisions remain
    manual-recovery cases.
    """
    raw_decision = run_state.get("blocked_decision")
    if not isinstance(raw_decision, dict):
        return None
    try:
        from harness.blocked_decision import validate_blocked_decision_v2

        decision = validate_blocked_decision_v2(raw_decision)
    except ValueError:
        return None
    if (
        decision["status"] != "failed"
        or decision["source_kind"] != "controller_safeguard"
        or decision["producer_id"] != "agent_blocked"
        or decision["reason_code"] != "agent_blocked"
        or str(run_state.get("blocked_reason") or "").strip() != "agent_blocked"
    ):
        return None
    phase = str(decision["source_phase"] or "").strip()
    return phase if phase and phase != "terminal-blocked" else None


def _discard_retryable_failed_agent_block_decision(state: dict) -> bool:
    """Discard only an obsolete generic-agent-block decision before retrying."""
    if _retryable_failed_agent_block_phase(state) is None:
        return False
    state.pop("blocked_decision", None)
    state.pop("recovery_instruction", None)
    state.pop("escalation_question", None)
    state.pop("escalation_options", None)
    state.pop("escalation_resolved", None)
    return True


def _supersede_quality_guard_decision(state: dict) -> bool:
    """Close the obsolete WHY safeguard when quality remediation supersedes it.

    A certified quality remediation cycle is controller-owned evidence that a
    previous no-progress WHY guard no longer describes the next safe action.
    Preserve that guard as a resolved decision rather than leaving an active
    decision without its recovery instruction.  The narrow identity check
    prevents this path from bypassing ordinary human or provider decisions.
    """
    from harness.blocked_decision import validate_blocked_decision_v2

    remediation = state.get("quality_gate_remediation")
    raw_decision = state.get("blocked_decision")
    ledger = state.get("issue_resolution_ledger")
    if not isinstance(remediation, dict) or not isinstance(raw_decision, dict):
        return False
    if not isinstance(ledger, dict) or not ledger:
        return False
    if not all(
        isinstance(entry, dict) and entry.get("status") == "validated"
        for entry in ledger.values()
    ):
        return False
    try:
        decision = validate_blocked_decision_v2(raw_decision)
    except ValueError:
        return False
    if (
        decision["status"] != "awaiting_human"
        or decision["source_kind"] != "controller_safeguard"
        or decision["producer_id"] not in {
            "consecutive_why_fails",
            "why2_metric_stagnation",
        }
        or decision["reason_code"] != decision["producer_id"]
    ):
        return False

    superseded = {
        **decision,
        "status": "resolved",
        "answer_text": (
            "Superseded by controller quality-gate remediation after all "
            "recorded issue resolutions were validated."
        ),
        "resolved_by": "COMMANDER",
        "resolved_at": datetime.now(timezone.utc).isoformat(),
    }
    state["blocked_decision"] = validate_blocked_decision_v2(superseded)
    state.pop("recovery_instruction", None)
    return True


def _reset_quality_remediation_dispatch_counts(state: dict) -> None:
    """Start a spec-changing quality remediation with a fresh verification budget."""
    dispatch_counts = state.get("phase_dispatch_counts")
    if not isinstance(dispatch_counts, dict):
        return
    updated_counts = dict(dispatch_counts)
    for phase_id in (
        "phase1-what",
        "phase1-lexicon",
        "phase1-understanding",
        "phase1-why2",
    ):
        updated_counts.pop(phase_id, None)
    state["phase_dispatch_counts"] = updated_counts


def _current_qualitative_findings(state: Mapping[str, object]) -> list[dict[str, object]]:
    """Return current SAGE findings that must survive remediation recovery."""
    finding_routes = state.get("finding_routes")
    findings = (
        finding_routes.get("findings")
        if isinstance(finding_routes, Mapping)
        else None
    )
    return [
        dict(finding)
        for finding in findings
        if isinstance(finding, Mapping)
    ] if isinstance(findings, list) else []


def _render_v2_decision_options(decision: dict[str, object]) -> str:
    options = decision.get("options")
    if not isinstance(options, list) or not options:
        return "Free text"
    return "\n".join(
        f"{option['id']}: {option['label']}"
        for option in options
        if isinstance(option, dict)
    )


def _v2_decision_recommendation(decision: dict[str, object]) -> str:
    options = decision.get("options")
    if isinstance(options, list):
        for option in options:
            if isinstance(option, dict) and option.get("recommended") is True:
                return f"{option['id']}: {option['label']}"
    return str(decision.get("recommended_answer") or "(none)")


def _decision_option_display(
    decision: Mapping[str, object],
    option_id: object,
) -> str:
    identifier = str(option_id or "").strip()
    if not identifier:
        return "(none)"
    options = decision.get("options")
    if isinstance(options, list):
        for option in options:
            if isinstance(option, Mapping) and option.get("id") == identifier:
                label = str(option.get("label") or "").strip()
                return f"{identifier}: {label}" if label else identifier
    return identifier


def _decision_audit_fields(
    decision: Mapping[str, object],
) -> list[tuple[str, str]]:
    """Render recommendation and resolution audit from a validated decision."""
    fields: list[tuple[str, str]] = [
        ("Decision ID", str(decision["id"])),
        ("Decision status", str(decision["status"])),
        ("Decision mode", str(decision["autonomy_mode"])),
        ("Classification", str(decision["classification"])),
        ("Question", str(decision["question"])),
        ("Options", _render_v2_decision_options(dict(decision))),
    ]
    if decision.get("schema_version") == 3:
        recommended_option = decision.get("recommended_option_id")
        recommended_answer = str(
            decision.get("recommended_answer") or ""
        ).strip()
        recommendation_target = (
            _decision_option_display(decision, recommended_option)
            if recommended_option is not None
            else recommended_answer or "(human action only)"
        )
        fields.extend(
            [
                ("Recommendation", f"Recommended: {recommendation_target}"),
                (
                    "Recommendation rationale",
                    str(decision["recommendation_rationale"]),
                ),
                (
                    "Recommendation confidence",
                    str(decision["recommendation_confidence"]),
                ),
            ]
        )
        recommended_action = str(
            decision.get("recommended_action") or ""
        ).strip()
        if recommended_action:
            fields.append(("Recommended action", recommended_action))
    else:
        fields.append(
            (
                "Recommendation",
                f"Recommended: {_v2_decision_recommendation(dict(decision))}",
            )
        )
    fields.append(("Risk", str(decision.get("risk_level") or "(none)")))

    selected_option = decision.get("selected_option_id")
    answer_text = str(decision.get("answer_text") or "").strip()
    if selected_option is not None or answer_text:
        fields.append(
            (
                "Answer",
                _decision_option_display(decision, selected_option)
                if selected_option is not None
                else answer_text,
            )
        )
    resolved_by = str(decision.get("resolved_by") or "").strip()
    if resolved_by:
        fields.append(("Resolved by", resolved_by))
    if decision.get("schema_version") == 3 and decision.get("status") == "resolved":
        followed = decision.get("recommendation_followed")
        resolution = (
            "Followed recommendation"
            if followed is True
            else "Overrode recommendation"
            if followed is False
            else "Recommendation action required human judgment"
        )
        fields.append(("Resolution", resolution))
        resolution_rationale = str(
            decision.get("resolution_rationale") or ""
        ).strip()
        resolution_confidence = str(
            decision.get("resolution_confidence") or ""
        ).strip()
        override_reason = str(decision.get("override_reason") or "").strip()
        if resolution_rationale:
            fields.append(("Resolution rationale", resolution_rationale))
        if resolution_confidence:
            fields.append(("Resolution confidence", resolution_confidence))
        if override_reason:
            fields.append(("Override reason", override_reason))
    return fields


def _proportional_quality_decision_fields(
    state: Mapping[str, object],
    decision: Mapping[str, object],
) -> list[tuple[str, str]]:
    """Render sealed proportional budget evidence without inferring choices."""
    if decision.get("resolution_handler") != "proportional_quality_debt":
        return []
    fields: list[tuple[str, str]] = []
    repair = state.get("phase1_quality_repair")
    if isinstance(repair, Mapping):
        automatic = repair.get("automatic_consumed")
        automatic_limit = repair.get("automatic_limit")
        extension = repair.get("extension_consumed")
        extension_limit = repair.get("extension_limit")
        extension_authorized = repair.get("extension_authorized")
        if type(automatic) is int and type(automatic_limit) is int:
            fields.append(
                (
                    "Automatic repairs",
                    f"{automatic} of {automatic_limit} consumed "
                    f"({max(0, automatic_limit - automatic)} remaining)",
                )
            )
        if type(extension) is int and type(extension_limit) is int:
            authorization = (
                f"; {extension_authorized} authorized"
                if type(extension_authorized) is int
                else ""
            )
            fields.append(
                (
                    "Extension repairs",
                    f"{extension} of {extension_limit} consumed "
                    f"({max(0, extension_limit - extension)} remaining"
                    f"{authorization})",
                )
            )
    evidence = state.get("proportional_quality_candidate_evidence")
    if isinstance(evidence, Mapping):
        candidate = str(evidence.get("selected_candidate_id") or "").strip()
        if candidate:
            fields.append(("Selected candidate", candidate))
        failed_gates: list[str] = []
        raw_gates = evidence.get("failed_gates")
        if isinstance(raw_gates, list):
            for gate in raw_gates[:8]:
                if not isinstance(gate, Mapping):
                    continue
                name = str(gate.get("name") or "").strip()
                score = gate.get("score")
                threshold = gate.get("threshold")
                if (
                    name
                    and type(score) in {int, float}
                    and type(threshold) in {int, float}
                ):
                    failed_gates.append(
                        f"{name} {float(score):.2f} < {float(threshold):.2f}"
                    )
        if failed_gates:
            fields.append(("Residual gate evidence", ", ".join(failed_gates)))
        sage_findings: list[str] = []
        raw_findings = evidence.get("sage_finding_routes")
        if isinstance(raw_findings, list):
            for finding in raw_findings[:5]:
                if not isinstance(finding, Mapping):
                    continue
                issue_id = str(finding.get("issue_id") or "").strip()
                severity = str(finding.get("severity") or "").strip()
                issue_type = str(finding.get("type") or "").strip()
                rationale = str(finding.get("rationale") or "").strip()
                identity = issue_id or "SAGE finding"
                classification = "/".join(
                    value for value in (severity, issue_type) if value
                )
                rendered = (
                    f"{identity} [{classification}]" if classification else identity
                )
                if rationale:
                    rendered += f": {rationale[:240]}"
                sage_findings.append(rendered)
        if sage_findings:
            fields.append(("Material SAGE findings", "\n".join(sage_findings)))
        recommendation_evidence = evidence.get("recommendation_evidence")
        if isinstance(recommendation_evidence, Mapping):
            baseline_candidate = str(
                recommendation_evidence.get("baseline_candidate_id") or ""
            ).strip()
            current_candidate = str(
                recommendation_evidence.get("current_candidate_id") or ""
            ).strip()
            if baseline_candidate and current_candidate:
                fields.append(
                    (
                        "Growth comparison",
                        f"{baseline_candidate} → {current_candidate}",
                    )
                )
            comparison_previous = str(
                recommendation_evidence.get(
                    "comparison_previous_candidate_id"
                ) or ""
            ).strip()[:128]
            comparison_current = str(
                recommendation_evidence.get(
                    "comparison_current_candidate_id"
                ) or ""
            ).strip()[:128]
            if comparison_previous and comparison_current:
                fields.append(
                    (
                        "Repair comparison",
                        f"{comparison_previous} → {comparison_current}",
                    )
                )
            baseline_statements = recommendation_evidence.get(
                "baseline_formal_statement_count"
            )
            statements = recommendation_evidence.get("formal_statement_count")
            statement_growth = recommendation_evidence.get(
                "formal_statement_growth"
            )
            if all(
                type(value) is int
                for value in (baseline_statements, statements, statement_growth)
            ):
                fields.append(
                    (
                        "Formal statements",
                        f"{baseline_statements:,} → {statements:,} "
                        f"({statement_growth:+,})",
                    )
                )
            baseline_bytes = recommendation_evidence.get("baseline_byte_count")
            byte_count = recommendation_evidence.get("byte_count")
            byte_growth = recommendation_evidence.get("byte_growth")
            if all(
                type(value) is int
                for value in (baseline_bytes, byte_count, byte_growth)
            ):
                fields.append(
                    (
                        "Specification bytes",
                        f"{baseline_bytes:,} → {byte_count:,} "
                        f"({byte_growth:+,} bytes)",
                    )
                )
            score_history_lines: list[str] = []
            raw_score_history = recommendation_evidence.get("score_history")
            if isinstance(raw_score_history, list):
                for entry in raw_score_history[:5]:
                    if not isinstance(entry, Mapping):
                        continue
                    repair_number = entry.get("repair_number")
                    candidate_id = str(
                        entry.get("candidate_id") or ""
                    ).strip()[:128]
                    scores = entry.get("scores")
                    if (
                        type(repair_number) is not int
                        or repair_number < 0
                        or not candidate_id
                        or not isinstance(scores, list)
                    ):
                        continue
                    rendered_scores: list[str] = []
                    for score_entry in scores[:8]:
                        if not isinstance(score_entry, Mapping):
                            continue
                        name = str(
                            score_entry.get("name") or ""
                        ).strip()[:80]
                        score = score_entry.get("score")
                        threshold = score_entry.get("threshold")
                        if (
                            name
                            and type(score) in {int, float}
                            and type(threshold) in {int, float}
                        ):
                            rendered_scores.append(
                                f"{name} {float(score):.2f}/{float(threshold):.2f}"
                            )
                    if rendered_scores:
                        score_history_lines.append(
                            f"repair {repair_number} {candidate_id}: "
                            + ", ".join(rendered_scores)
                        )
            if score_history_lines:
                fields.append(("Score history", "\n".join(score_history_lines)))
            delta_lines: list[str] = []
            raw_deltas = recommendation_evidence.get("per_repair_deltas")
            if isinstance(raw_deltas, list):
                for entry in raw_deltas[:4]:
                    if not isinstance(entry, Mapping):
                        continue
                    repair_number = entry.get("repair_number")
                    statement_delta = entry.get("formal_statement_delta")
                    byte_delta = entry.get("byte_delta")
                    score_deltas = entry.get("score_deltas")
                    if (
                        type(repair_number) is not int
                        or repair_number < 0
                        or type(statement_delta) is not int
                        or type(byte_delta) is not int
                        or not isinstance(score_deltas, list)
                    ):
                        continue
                    rendered_deltas: list[str] = []
                    for score_delta in score_deltas[:8]:
                        if not isinstance(score_delta, Mapping):
                            continue
                        name = str(
                            score_delta.get("name") or ""
                        ).strip()[:80]
                        delta = score_delta.get("delta")
                        if name and type(delta) in {int, float}:
                            rendered_deltas.append(
                                f"{name} {float(delta):+.2f}"
                            )
                    if rendered_deltas:
                        delta_lines.append(
                            f"repair {repair_number}: "
                            + ", ".join(rendered_deltas)
                            + f"; statements {statement_delta:+d}"
                            + f"; bytes {byte_delta:+d}"
                        )
            if delta_lines:
                fields.append(("Per-repair deltas", "\n".join(delta_lines)))
            rationale = str(
                recommendation_evidence.get("rationale") or ""
            ).strip()
            if rationale:
                fields.append(("Recommendation rationale", rationale[:500]))
    options = decision.get("options")
    if isinstance(options, list):
        recommended = next(
            (
                option
                for option in options
                if isinstance(option, Mapping)
                and option.get("recommended") is True
            ),
            None,
        )
        if isinstance(recommended, Mapping):
            fields.append(
                (
                    "Quality recommendation",
                    f"{recommended.get('id')} ({recommended.get('label')})",
                )
            )
        choice_commands = [
            f'echelon spec resume "{option.get("id")}"'
            for option in options
            if isinstance(option, Mapping)
            and isinstance(option.get("id"), str)
            and option.get("id")
        ]
        if choice_commands:
            fields.append(("Choice syntax", "\n".join(choice_commands)))
    return fields


def _current_quality_debt_cli_facts(
    state: Mapping[str, object],
    project_root: Path,
) -> dict[str, object] | None:
    """Return bounded display facts only for Task 6-verified live authority."""
    authorization = state.get("spec_quality_debt_authorization")
    if not isinstance(authorization, Mapping):
        return None
    from harness.phase1_quality_debt import (
        has_current_quality_debt_authorization,
    )

    if not has_current_quality_debt_authorization(
        state,
        project_root=project_root,
    ):
        return None
    if authorization.get("status") != "accepted_with_debt":
        return None
    failed_gates: list[str] = []
    raw_gates = authorization.get("failed_gates")
    if isinstance(raw_gates, list):
        for gate in raw_gates[:8]:
            if not isinstance(gate, Mapping):
                continue
            name = str(gate.get("name") or "").strip()
            score = gate.get("score")
            threshold = gate.get("threshold")
            if name and type(score) in {int, float} and type(threshold) in {int, float}:
                failed_gates.append(
                    f"{name} {float(score):.2f} < {float(threshold):.2f}"
                )
    qualitative_issues: list[str] = []
    raw_qualitative = authorization.get("qualitative_debt")
    if isinstance(raw_qualitative, list):
        for finding in raw_qualitative[:8]:
            if not isinstance(finding, Mapping):
                continue
            issue_id = str(finding.get("issue_id") or "").strip()
            title = str(finding.get("title") or "").strip()
            if issue_id and title:
                qualitative_issues.append(
                    f"{issue_id[:80]}: {title[:120]}"
                )
            elif issue_id:
                qualitative_issues.append(issue_id[:80])
    return {
        "status": "accepted_with_debt",
        "artifact": str(authorization.get("debt_artifact") or "").strip(),
        "resolved_by": str(authorization.get("resolved_by") or "").strip(),
        "failed_gates": tuple(failed_gates),
        "qualitative_issues": tuple(qualitative_issues),
    }


def _persisted_or_legacy_recovery_instruction(
    run_state: dict,
) -> RecoveryInstruction | None:
    reason = str(run_state.get("blocked_reason") or "").strip()
    phase_output_recovery = run_state.get("phase_output_recovery")
    phase_output_instruction: RecoveryInstruction | None = None
    if (
        reason in {"missing_phase_outputs", "invalid_evidence_inventory"}
        and isinstance(phase_output_recovery, dict)
    ):
        recovery_phase = str(
            phase_output_recovery.get("phase") or ""
        ).strip()
        missing_outputs = phase_output_recovery.get("missing_outputs")
        invalid_outputs = phase_output_recovery.get("invalid_outputs")
        has_recovery_evidence = (
            isinstance(missing_outputs, list) and bool(missing_outputs)
        ) or (
            isinstance(invalid_outputs, list) and bool(invalid_outputs)
        )
        if recovery_phase and has_recovery_evidence:
            phase_output_instruction = retry_phase_recovery(
                recovery_phase,
                reason,
            )

    raw_instruction = run_state.get("recovery_instruction")
    if raw_instruction is not None:
        instruction = validate_recovery_instruction(raw_instruction)
        if reason and instruction.reason_code != reason:
            if phase_output_instruction is not None:
                return phase_output_instruction
            raise RecoveryInstructionError(
                "recovery instruction does not match blocked reason"
            )
        return instruction

    if phase_output_instruction is not None:
        return phase_output_instruction
    return None


def _render_escalation_options(options: object) -> str:
    """Render the same selectable choices that ``spec resume`` accepts.

    Choice escalations are persisted separately from the prose question so the
    resume command can route deterministically.  They must be displayed with
    that question; otherwise users cannot know which positional answer maps to
    which route.
    """
    if not isinstance(options, list):
        return ""

    rendered: list[str] = []
    letters: list[str] = []
    for index, raw in enumerate(options):
        if not isinstance(raw, dict):
            continue
        label = str(raw.get("label") or raw.get("id") or "").strip()
        if not label:
            continue
        letter = chr(ord("A") + index)
        letters.append(letter)
        rendered.append(f"{letter}: {label}")

    if not rendered:
        return ""
    choices = "/".join(letters)
    rendered.append(f"Answer with {choices}, the option id, or the option label.")
    return "\n".join(rendered)


def _phase_dispatch_limit_phase(run_state: dict) -> str | None:
    """Find the phase whose retry window was exhausted.

    New runs persist the phase explicitly.  The question fallback keeps runs
    created by older Echelon versions recoverable without state-file surgery.
    """
    phase = str(run_state.get("phase_dispatch_limit_phase") or "").strip()
    if phase:
        return phase

    question = str(run_state.get("escalation_question") or "")
    match = re.search(r"Phase ['\"]([^'\"]+)['\"] has been dispatched", question)
    return match.group(1) if match else None


def _is_retryable_dispatch_block_reason(reason: str) -> bool:
    reason = reason.strip()
    return (
        reason in {
            "missing_phase_outputs",
            "missing_echelon_result",
            "agent_timeout",
            "agent_blocked",
        }
        or reason.startswith("agent_exit_code_")
    )


def _last_incomplete_dispatch_phase(run_state: dict) -> str | None:
    last_dispatch = run_state.get("last_dispatch") or {}
    phase_id = str(last_dispatch.get("phase_id") or "").strip()
    if not phase_id or phase_id == "terminal-blocked":
        return None

    return phase_id


def _blocked_non_escalation_recovery_command(
    run_state: dict,
    *,
    project_root: Path | None = None,
) -> str | None:
    blocked_reason = str(run_state.get("blocked_reason") or "").strip()
    phase_id = _last_incomplete_dispatch_phase(run_state)
    if not _is_retryable_dispatch_block_reason(blocked_reason) or not phase_id:
        return None
    if project_root is None:
        return None
    spec_dir, _ = _normalize_rewind_spec_dir(project_root, run_state)
    if spec_dir is None:
        return None
    from harness.phase_checkpoints import load_checkpoint_ledger, resolve_checkpoint

    try:
        resolve_checkpoint(load_checkpoint_ledger(spec_dir), phase_id)
    except (KeyError, OSError, ValueError, TypeError):
        return None
    return _command_display("echelon spec rewind", [phase_id])


def _blocked_failed_dispatch_phase(run_state: dict) -> str | None:
    """Return the incomplete phase that caused a deterministic dispatch block."""

    blocked_reason = str(run_state.get("blocked_reason") or "").strip()
    if run_state.get("escalation_question"):
        return None

    phase_id = _last_incomplete_dispatch_phase(run_state)
    if not phase_id:
        return None
    completed = run_state.get("completed_phases")
    completed_phases = {str(phase) for phase in completed} if isinstance(completed, list) else set()
    if phase_id in completed_phases and not _is_retryable_dispatch_block_reason(blocked_reason):
        return None
    if blocked_reason in {"token_budget_exhausted"} or "invalid next_phase" in blocked_reason:
        return None

    return phase_id


def _phase_a_readiness_traceability_blockers(run_state: dict) -> list[str]:
    """Return product-input mapping blockers preserved by Phase A finalization."""
    blockers = run_state.get("phase_a_readiness_blockers")
    if not isinstance(blockers, list):
        return []
    markers = (
        "product input traceability",
        "included requirement has no specification IDs",
        "included requirement has no task IDs",
        "does not reference the mapped specification IDs",
        "is not target-owned by a declared implementation target",
    )
    return [
        str(blocker)
        for blocker in blockers
        if isinstance(blocker, str) and any(marker in blocker for marker in markers)
    ]


def _interrupted_retry_phase(run_state: dict) -> str | None:
    phase_id = str(run_state.get("interrupted_phase") or run_state.get("phase") or "").strip()
    if phase_id and phase_id not in {"DONE", "terminal-blocked"}:
        return phase_id
    return _last_incomplete_dispatch_phase(run_state)


def _spec_markdown_sha256_for_state(run_state: dict, project_root: Path) -> str | None:
    """Return the active run's canonical spec digest, if it is available."""
    spec_dir_ref = str(run_state.get("spec_dir") or "").strip()
    if not spec_dir_ref:
        return None
    spec_dir = Path(spec_dir_ref)
    if not spec_dir.is_absolute():
        spec_dir = project_root / spec_dir
    try:
        return hashlib.sha256((spec_dir / "spec.md").read_bytes()).hexdigest()
    except OSError:
        return None


def _active_dispatch_cap_evidence_exists(
    run_state: dict,
    project_root: Path | None,
) -> bool:
    """Whether the active run has recoverable dispatch-cap evidence."""
    if project_root is None:
        return False
    spec_ref = str(run_state.get("spec_dir") or "").strip()
    spec_dir: Path | None = None
    try:
        if spec_ref:
            spec_dir = Path(spec_ref)
            if not spec_dir.is_absolute():
                spec_dir = project_root / spec_dir
            if (spec_dir / "issues.md").is_file():
                return True
            if (spec_dir / "spec.md").is_file():
                return False

        staging_ref = str(run_state.get("staging_dir") or "").strip()
        if not staging_ref:
            return False
        staging_dir = Path(staging_ref)
        if not staging_dir.is_absolute():
            staging_dir = project_root / staging_dir
        return (staging_dir / "issues.md").is_file()
    except OSError:
        return False


def _classify_run_recovery(
    run_state: dict,
    *,
    project_root: Path | None = None,
) -> _RunRecoveryAction:
    status = str(run_state.get("status") or "").strip()
    reason = str(run_state.get("blocked_reason") or "").strip()

    if status in {"running", "in_progress"}:
        return _RunRecoveryAction("continue_running")

    if status == "interrupted":
        retry_phase = _interrupted_retry_phase(run_state)
        if retry_phase:
            return _RunRecoveryAction(
                "retry_phase",
                reason="interrupted",
                phase=retry_phase,
                command="echelon spec continue",
                note="will retry the interrupted phase",
            )
        return _RunRecoveryAction(
            "manual_recovery",
            reason="interrupted",
            command="echelon spec run --next-phase <phase-id>",
            note="interrupted run does not record a retryable phase",
        )

    if status != "blocked":
        return _RunRecoveryAction("advance")

    try:
        decision_recovery = _versioned_decision_recovery_action(
            run_state,
            project_root=project_root,
        )
    except (RecoveryInstructionError, ValueError) as exc:
        return _RunRecoveryAction(
            "manual_recovery",
            reason="invalid_decision_authority",
            note=(
                f"invalid persisted decision authority: {exc}; restore or repair "
                "the exact decision and recovery pair before retrying"
            ),
        )
    if decision_recovery is not None:
        return decision_recovery

    if reason == "proportional_quality_debt_declined":
        return _RunRecoveryAction(
            "manual_recovery",
            reason=reason,
            command=(
                "inspect the retained quality evidence, then start a new or "
                "amended specification run"
            ),
            note=(
                "The exhausted proportional repair loop was explicitly stopped. "
                "Ordinary continue cannot reopen it; deliberately amend the request "
                "or quality policy and start a new run."
            ),
        )

    retryable_agent_block_phase = _retryable_failed_agent_block_phase(run_state)
    if retryable_agent_block_phase:
        return _RunRecoveryAction(
            "retry_phase",
            reason="agent_blocked",
            phase=retryable_agent_block_phase,
            command="echelon spec continue",
            note=(
                "will retry a generic agent block; no material ambiguity was "
                "recorded"
            ),
        )

    ledger = run_state.get("issue_resolution_ledger")
    ledger_entries = (
        [entry for entry in ledger.values() if isinstance(entry, dict)]
        if isinstance(ledger, dict)
        else []
    )
    all_ledger_entries_validated = bool(ledger_entries) and all(
        entry.get("status") == "validated" for entry in ledger_entries
    )

    if reason == "issue_resolution_next":
        if all_ledger_entries_validated:
            return _RunRecoveryAction(
                "retry_phase",
                reason="quality_gate_remediation",
                phase="phase1-what",
                command="echelon spec continue",
                note=(
                    "All recorded issue resolutions are complete, but the certified "
                    "quality gates still fail. Starting a fresh specification quality "
                    "remediation cycle; no further `spec resolve` command applies."
                ),
            )
        return _RunRecoveryAction(
            "manual_recovery",
            reason=reason,
            command='echelon spec resolve ISS-<n> "<project decision>"',
            note=(
                "The previous issue repair was validated. Resolve the next "
                "unresolved SAGE issue; Echelon will retain the issue ledger "
                "and run only that issue's targeted repair."
            ),
        )

    # Once every controller-recorded issue decision is validated, a stale WHY
    # guard must not send the operator back to `spec resolve`. Resume the
    # normal quality remediation path instead. With an outstanding selected
    # repair, leave recovery handling below in charge of its declared edge.
    if reason == "consecutive_why_fails" and all_ledger_entries_validated:
        return _RunRecoveryAction(
            "retry_phase",
            reason="quality_gate_remediation",
            phase="phase1-what",
            command="echelon spec continue",
            note=(
                "All recorded issue resolutions are complete, but the certified "
                "quality gates still fail. Starting a fresh specification quality "
                "remediation cycle; no further `spec resolve` command applies."
            ),
        )

    if reason == "quality_gates_failed_after_resolutions":
        return _RunRecoveryAction(
            "human_resume",
            reason=reason,
            command='echelon spec resume "<quality-gate decision>"',
            note=(
                "All recorded issue resolutions are complete, but the certified "
                "quality gates still fail. No further `spec resolve` command applies."
            ),
        )

    if reason == "quality_gate_remediation_no_artifact_progress":
        return _RunRecoveryAction(
            "retry_phase",
            reason="quality_gate_remediation",
            phase="phase1-what",
            command="echelon spec continue",
            note=(
                "The prior quality remediation did not modify spec.md. Retrying "
                "CARTOGRAPHER with the controller's mandatory atomic-requirement "
                "repair contract; no `spec resolve` command applies."
            ),
        )

    if (
        reason == "phase_dispatch_limit_evidence_missing"
        and _active_dispatch_cap_evidence_exists(run_state, project_root)
    ):
        phase = str(run_state.get("phase") or "").strip()
        if phase and phase != "terminal-blocked":
            return _RunRecoveryAction(
                "retry_phase",
                reason="phase_dispatch_limit_evidence_retry",
                phase=phase,
                command="echelon spec continue",
                note=(
                    "The active run contains issues.md; retrying the capped phase "
                    "after bypassing a stale published-spec lookup."
                ),
            )

    phase = str(run_state.get("phase") or "").strip()
    if (
        reason.startswith("phase_dispatch_limit_evidence_")
        and phase
        in {
            "phase3-tasks-lexicon",
            "phase3-consensus-tasks-lexicon",
        }
    ):
        return _RunRecoveryAction(
            "manual_recovery",
            reason=reason,
            phase=phase,
            command=_command_display("echelon phase run", [phase]),
            note=(
                "Re-run the capped deterministic task gate after repairing "
                "tasks.md from tasks-lexicon-report.json or updating the "
                "validator. The gate will route any remaining findings back "
                "to planning without another automatic dispatch-cap decision."
            ),
        )

    try:
        instruction = _persisted_or_legacy_recovery_instruction(run_state)
    except RecoveryInstructionError as exc:
        return _RunRecoveryAction(
            "manual_recovery",
            reason=reason or "invalid_recovery_instruction",
            command="inspect echelon spec status, then repair the run state",
            note=f"persisted recovery instruction is invalid: {exc}",
        )
    if instruction is not None:
        return _recovery_action_from_instruction(
            instruction,
            run_state=run_state,
            project_root=project_root,
        )

    recovery = run_state.get("issue_resolution_recovery")
    if (
        isinstance(recovery, dict)
        and recovery.get("status") != "consumed"
        and str(recovery.get("issue_id") or "").strip()
    ):
        return _RunRecoveryAction(
            "retry_phase",
            reason="issue_resolution",
            phase=str(recovery.get("to_phase") or "").strip(),
            command="echelon spec continue",
            note="will validate and consume the declared issue-repair workflow edge",
        )

    # A prior version could finish the selected WHAT repair, then let SAGE
    # re-list that same issue from stale generic reasoning.  Give the repaired
    # issue one focused WHY2 validation pass before asking the operator to
    # re-enter a decision they have already supplied.
    selected_issue = str(run_state.get("selected_issue_resolution") or "").strip()
    ledger = run_state.get("issue_resolution_ledger")
    retried_issue = str(
        run_state.get("issue_resolution_revalidation_attempted") or ""
    ).strip()
    if (
        selected_issue
        and selected_issue != retried_issue
        and isinstance(ledger, dict)
        and isinstance(ledger.get(selected_issue), dict)
        and ledger[selected_issue].get("status") == "repaired"
        and reason in {"consecutive_why_fails", "why2_metric_stagnation"}
    ):
        return _RunRecoveryAction(
            "retry_phase",
            reason="issue_resolution_revalidation",
            phase="phase1-understanding",
            command="echelon spec continue",
            note=(
                f"will revalidate the already-repaired {selected_issue} against "
                "its recorded decision before requesting another resolution"
            ),
        )

    if reason == "selected_issue_repair_no_artifact_progress":
        baseline = run_state.get("issue_resolution_repair_baseline")
        repair_phase = (
            str(baseline.get("repair_phase") or "").strip()
            if isinstance(baseline, dict)
            else ""
        )
        return _RunRecoveryAction(
            "retry_phase",
            reason=reason,
            phase=repair_phase or "phase1-what",
            command="echelon spec continue",
            note="will retry the selected repair; it may not advance without spec.md progress",
        )

    if run_state.get("escalation_question"):
        if reason == "phase_dispatch_limit":
            phase = _phase_dispatch_limit_phase(run_state)
            if phase:
                return _RunRecoveryAction(
                    "manual_recovery",
                    reason=reason,
                    phase=phase,
                    command='echelon spec resolve ISS-<n> "<project decision>"',
                    note=(
                        f"{run_state.get('escalation_question', '').strip()}\n\n"
                        "No retry has been authorized. Resolve the first unresolved issue "
                        "with a project decision; Echelon will run only that issue's "
                        "targeted repair and retain the remaining issue ledger."
                    ),
                )
        return _RunRecoveryAction(
            "human_resume",
            reason=reason or "human answer required",
            command='echelon spec resume "<your answer>"',
            note=str(run_state.get("escalation_question") or "").strip(),
        )

    if reason == "token_budget_exhausted":
        return _RunRecoveryAction(
            "manual_recovery",
            reason=reason,
            command="increase analysis.token_budget_k, then echelon spec continue",
            note="the run cannot continue until the configured budget is higher",
        )

    last_dispatch = run_state.get("last_dispatch")
    last_dispatch_phase = (
        str(last_dispatch.get("phase_id") or "").strip()
        if isinstance(last_dispatch, dict)
        else ""
    )
    tasks_lexicon_block = reason == "tasks_lexicon_gate_exhausted" or (
        reason == "lexicon_gate_exhausted"
        and last_dispatch_phase
        in {"phase3-tasks-lexicon", "phase3-consensus-tasks-lexicon"}
    )
    if tasks_lexicon_block:
        return _RunRecoveryAction(
            "manual_recovery",
            reason="tasks_lexicon_gate_exhausted",
            phase="phase3-plan",
            command="echelon phase run phase3-plan",
            note=(
                "The hard Tasks Lexicon gate failed. Re-run the Phase 3 planning "
                "node to repair tasks.md from tasks-lexicon-report.json; the "
                "controller will revalidate the repaired plan through the "
                "deterministic Tasks Lexicon gate."
            ),
        )

    if reason == "lexicon_gate_exhausted":
        return _RunRecoveryAction(
            "manual_recovery",
            reason=reason,
            phase="phase1-lexicon-derive",
            command=(
                "echelon phase run phase1-lexicon-derive"
            ),
            note=(
                "The hard spec Lexicon gate failed. Dispatch the dedicated "
                "derivation node to repair requirements.lexicon.md "
                "from spec-lexicon-report.json. Certify with the deterministic "
                "Lexicon gate only after the repair pass changes the artifact."
            ),
        )

    if reason == "lexicon_repair_no_artifact_progress":
        return _RunRecoveryAction(
            "manual_recovery",
            reason=reason,
            phase="phase1-lexicon-derive",
            command=(
                "echelon phase run phase1-lexicon-derive"
            ),
            note=(
                "The derivation repair pass did not change the derived Lexicon "
                "artifact. Re-run the repair node to repair requirements.lexicon.md "
                "with the controller-injected "
                "spec-lexicon-report.json context; re-running certification "
                "will only repeat the same findings until requirements.lexicon.md changes."
            ),
        )

    if reason == "provider_session_limit":
        provider_message = str(run_state.get("provider_limit_message") or "").strip()
        note = "wait for the provider reset, then retry the blocked phase"
        if provider_message:
            note += f": {provider_message}"
        return _RunRecoveryAction(
            "retry_phase",
            reason=reason,
            phase=_last_incomplete_dispatch_phase(run_state) or "",
            command="echelon spec continue",
            note=note,
        )

    if reason == "phase_a_readiness_failed":
        traceability_blockers = _phase_a_readiness_traceability_blockers(run_state)
        if traceability_blockers:
            return _RunRecoveryAction(
                "manual_recovery",
                reason=reason,
                command="echelon spec repair-traceability",
                note=(
                    "Preview a deterministic repair that removes contextual task references "
                    "while preserving direct requirement mappings; it resumes finalization without "
                    "re-running PLAN when safe. "
                    f"{len(traceability_blockers)} traceability blocker(s) were recorded; "
                    "each listed task must have a req= value that intersects its mapped spec_ids."
                ),
            )

    if "invalid next_phase" in reason:
        return _RunRecoveryAction(
            "manual_recovery",
            reason=reason,
            command="echelon spec run --next-phase <phase-id>",
            note="choose a valid phase from echelon spec status output",
        )

    # Schema rejection happens after an agent dispatch but before its result is
    # committed.  The last dispatch is therefore incomplete even when an older
    # successful pass appears in completed_phases; retrying it is safe and does
    # not require deleting its planning artifacts.
    if reason.startswith("echelon_result validation failed:"):
        phase = _last_incomplete_dispatch_phase(run_state)
        if phase:
            return _RunRecoveryAction(
                "retry_phase",
                reason=reason,
                phase=phase,
                command="echelon spec continue",
                note="will retry the phase with the rejected result; no rewind is required",
            )

    rewind = _blocked_non_escalation_recovery_command(
        run_state,
        project_root=project_root,
    )
    if rewind:
        phase = str((run_state.get("last_dispatch") or {}).get("phase_id") or "").strip()
        return _RunRecoveryAction(
            "safe_rewind",
            reason=reason,
            phase=phase,
            command=rewind,
            note="safe checkpoint cleanup is required before retry",
        )

    if reason == "controller_state_contract_validation_failed":
        return _RunRecoveryAction(
            "manual_recovery",
            reason=reason,
            phase=str(run_state.get("phase") or "").strip(),
            command="inspect echelon spec status, then choose a recovery action",
            note="no runtime-sync recovery instruction was recorded",
        )

    retry_phase = _blocked_failed_dispatch_phase(run_state)
    if retry_phase:
        return _RunRecoveryAction(
            "retry_phase",
            reason=reason,
            phase=retry_phase,
            command="echelon spec continue",
            note="will retry the blocked phase; it was not marked complete",
        )

    if not reason:
        return _RunRecoveryAction("advance")

    return _RunRecoveryAction(
        "manual_recovery",
        reason=reason,
        command="inspect echelon spec status, then choose a recovery action",
        note="no human question, safe rewind target, or incomplete phase was recorded",
    )


def _format_phase_a_elapsed(state: dict) -> str:
    created = str(state.get("created_at") or "").strip()
    updated = str(state.get("updated_at") or "").strip()
    if not created or not updated:
        return ""
    try:
        from datetime import datetime

        start = datetime.fromisoformat(created.replace("Z", "+00:00"))
        end = datetime.fromisoformat(updated.replace("Z", "+00:00"))
    except ValueError:
        return ""
    seconds = max(0, int((end - start).total_seconds()))
    if seconds < 60:
        return f"{seconds}s"
    minutes, rem = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {rem}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m"


def _format_completed_phases(state: dict) -> str:
    completed = state.get("completed_phases")
    phases = [str(phase) for phase in completed] if isinstance(completed, list) else []
    if not phases:
        return "(none recorded)"
    shown = phases[-8:]
    prefix = f"{len(phases)} phase{'s' if len(phases) != 1 else ''} completed"
    if len(phases) > len(shown):
        return f"{prefix}: ... -> " + " -> ".join(shown)
    return f"{prefix}: " + " -> ".join(shown)


def _phase_a_current_phase(state: dict, result_phase: str) -> str:
    phase = str(state.get("phase") or result_phase or "unknown").strip()
    retry_phase = _last_incomplete_dispatch_phase(state)
    if phase == "terminal-blocked" and retry_phase:
        return f"{retry_phase} (terminal-blocked)"
    return phase or "unknown"


def _phase_a_result_line(status: str, state: dict) -> str:
    status_label = {
        "done": "done",
        "blocked": "blocked",
        "interrupted": "interrupted",
        "budget_exhausted": "budget exhausted",
    }.get(status, status or "unknown")
    parts = [status_label]
    elapsed = _format_phase_a_elapsed(state)
    if elapsed:
        parts.append(elapsed)
    try:
        cost = float(state.get("cost_usd") or 0)
    except (TypeError, ValueError):
        cost = 0.0
    if cost:
        parts.append(f"${cost:.4f}")
    try:
        token_usage = int(state.get("token_usage") or 0)
    except (TypeError, ValueError):
        token_usage = 0
    if token_usage:
        parts.append(f"{token_usage:,} tokens")
    return "  ·  ".join(parts)


def _current_issues_recap(
    project_root: Path,
    squad_dir: Path,
    state: dict,
) -> tuple[str, str] | None:
    """Return a compact recap and absolute path for the current run's issues."""
    candidates: list[Path] = []
    for key in ("published_spec_dir", "spec_dir"):
        spec_ref = str(state.get(key) or "").strip()
        if not spec_ref:
            continue
        spec_dir = Path(spec_ref)
        if not spec_dir.is_absolute():
            spec_dir = project_root / spec_dir
        candidates.append(spec_dir / "issues.md")
    candidates.append(_run_artifact_dir(project_root, squad_dir) / "issues.md")

    seen: set[Path] = set()
    ledger = state.get("issue_resolution_ledger")
    ledger = ledger if isinstance(ledger, dict) else {}
    for candidate in candidates:
        issues_path = candidate.resolve()
        if issues_path in seen:
            continue
        seen.add(issues_path)
        if not issues_path.is_file():
            continue
        try:
            issues_md = issues_path.read_text(errors="replace")
        except OSError:
            continue

        issue_blocks = re.findall(
            r"^### (ISS-\d+:\s*[^\n]+)\n(.*?)(?=^### ISS-\d+:|\Z)",
            issues_md,
            re.MULTILINE | re.DOTALL,
        )
        issues: list[str] = []
        severity_counts: dict[str, int] = {}
        for title, body in issue_blocks:
            issue_id_match = re.match(r"^(ISS-\d+):", title.strip())
            issue_id = issue_id_match.group(1) if issue_id_match else ""
            if (
                (issue_id and isinstance(ledger.get(issue_id), dict)
                 and ledger[issue_id].get("status") == "validated")
                or
                "RESOLVED" in title.upper()
                or re.search(r"\*\*Status:\*\*\s*[^\n]*\bRESOLVED\b", body, re.IGNORECASE)
                or re.search(r"\bNo action required\b", body, re.IGNORECASE)
            ):
                continue
            severity = re.search(r"\*\*Severity(?::)?\*\*\s*:?\s*(\w+)", body)
            label = severity.group(1).upper() if severity else "ISSUE"
            short_title = re.sub(r"^ISS-\d+:\s*", "", title).strip()
            issues.append(f"[{label}] {short_title}")
            severity_counts[label] = severity_counts.get(label, 0) + 1
        counts = [
            f"{severity} {severity_counts[severity]}"
            for severity in ("CRITICAL", "HIGH", "MEDIUM", "LOW")
            if severity_counts.get(severity)
        ]
        recap = " · ".join(counts) if counts else "Issues recorded"
        if issues:
            recap += "\n" + "\n".join(f"- {issue}" for issue in issues)
        return recap, str(issues_path)
    return None


def _issue_resolution_requests(project_root: Path, squad_dir: Path, state: dict) -> list[dict[str, str]]:
    """Extract user-decidable issue guidance from the canonical SAGE report."""
    recap = _current_issues_recap(project_root, squad_dir, state)
    if recap is None:
        return []
    _summary, issues_path_text = recap
    try:
        issues_md = Path(issues_path_text).read_text(errors="replace")
    except OSError:
        return []
    requests: list[dict[str, str]] = []
    for title, body in re.findall(
        r"^### (ISS-\d+:\s*[^\n]+)\n(.*?)(?=^### ISS-\d+:|\Z)",
        issues_md,
        re.MULTILINE | re.DOTALL,
    ):
        issue_id_match = re.match(r"^(ISS-\d+):\s*(.+)$", title.strip())
        if not issue_id_match:
            continue
        if (
            "RESOLVED" in title.upper()
            or re.search(r"\*\*Status:\*\*\s*[^\n]*\bRESOLVED\b", body, re.IGNORECASE)
            or re.search(r"\bNo action required\b", body, re.IGNORECASE)
        ):
            continue
        action = re.search(r"\*\*Action Required:\*\*\s*(.+)", body)
        amendment = re.search(r"\*\*Required Amendment\*\*:\s*(.+)", body)
        recommendation = re.search(r"\*\*Recommendation:\*\s*(.+)", body)
        severity = re.search(r"\*\*Severity(?::)?\*\*\s*:?\s*(\w+)", body)
        resolution_guidance = re.search(
            r"### Resolution Guidance\n(.*?)(?=^### |\Z)", body, re.DOTALL
        )
        guidance_text = resolution_guidance.group(1) if resolution_guidance else ""
        def guidance_field(name: str) -> str:
            match = re.search(
                rf"- \*\*{re.escape(name)}:\*\*\s*(.+)", guidance_text
            )
            return match.group(1).strip() if match else ""
        guidance = (
            action.group(1).strip()
            if action
            else amendment.group(1).strip()
            if amendment
            else recommendation.group(1).strip()
            if recommendation
            else "Provide a project-specific decision for this issue."
        )
        if guidance.lower().startswith("none"):
            continue
        request = {
            "issue_id": issue_id_match.group(1),
            "title": issue_id_match.group(2),
            "severity": severity.group(1).upper() if severity else "ISSUE",
            "guidance": guidance,
        }
        for key, label in (
            ("suggested_option", "Suggested option"),
            ("evidence_basis", "Evidence basis"),
            ("values_not_inferable", "Values not inferable"),
            ("banzai_eligible", "Banzai eligible"),
        ):
            value = guidance_field(label)
            if value:
                request[key] = value.lower() if key == "banzai_eligible" else value
        requests.append(request)
    return requests


def _issue_resolution_guidance_recap(
    project_root: Path, squad_dir: Path, state: dict
) -> str:
    """Render every unresolved issue's next decision without truncation."""
    ledger = state.get("issue_resolution_ledger")
    ledger = ledger if isinstance(ledger, dict) else {}
    lines: list[str] = []
    for request in _issue_resolution_requests(project_root, squad_dir, state):
        entry = ledger.get(request["issue_id"])
        if isinstance(entry, dict) and entry.get("status") == "validated":
            continue
        lines.append(
            f"- {request['issue_id']} [{request['severity']}]: {request['guidance']}"
        )
    return "\n".join(lines)


def _issue_resolution_screen_guidance(
    project_root: Path, squad_dir: Path, state: dict
) -> list[tuple[str, str]]:
    """Return all actionable issue details for CLI banners without hidden files."""
    recap = _current_issues_recap(project_root, squad_dir, state)
    if recap is None:
        return []
    _summary, issues_path_text = recap
    issues_path = Path(issues_path_text)
    ledger = state.get("issue_resolution_ledger")
    ledger = ledger if isinstance(ledger, dict) else {}
    fields: list[tuple[str, str]] = [
        ("issues file", str(issues_path)),
        ("open issues", issues_path.as_uri()),
    ]
    unresolved_requests = [
        request
        for request in _issue_resolution_requests(project_root, squad_dir, state)
        if not (
            isinstance(ledger.get(request["issue_id"]), dict)
            and ledger[request["issue_id"]].get("status") == "validated"
        )
    ]
    for index, request in enumerate(unresolved_requests):
        lines = [
            f"{request['title']} [{request['severity']}]",
            f"action: {request['guidance']}",
        ]
        suggested = request.get("suggested_option", "")
        if suggested and suggested.lower() != "none":
            lines.append(f"suggested: {suggested}")
            lines.append(
                f"accept: echelon spec resolve {request['issue_id']} {shlex.quote(suggested)}"
            )
        else:
            lines.append(
                f"resolve: echelon spec resolve {request['issue_id']} '<decision>'"
            )
        evidence = request.get("evidence_basis", "")
        if evidence and evidence.lower() != "none":
            lines.append(f"evidence: {evidence}")
        unknown = request.get("values_not_inferable", "")
        if unknown and unknown.lower() != "none":
            lines.append(f"user decides: {unknown}")
        rendered = "\n".join(lines)
        if index == 0:
            fields.append(("next issue", rendered))
        fields.append((request["issue_id"], rendered))
    return fields


def _is_issue_resolution_recovery(action: _RunRecoveryAction) -> bool:
    """Return whether one classified action authorizes issue-resolution CLI."""
    return action.command.startswith("echelon spec resolve ")


def _cmd_spec_resolve(args: list[str], *, project_root: Path, ext_dir: Path) -> None:
    """Record one issue decision, then run its targeted Phase 1 repair."""
    if len(args) < 2:
        print(
            'Usage: echelon spec resolve ISS-<n> "<project decision>"\n'
            "Resolve issues one at a time; use `echelon spec status` to see guidance.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    issue_id = args[0].strip().upper()
    decision = " ".join(args[1:]).strip()
    if not re.fullmatch(r"ISS-\d+", issue_id) or not decision:
        print("✗ resolve requires an ISS-<n> id and a non-empty decision", file=sys.stderr)
        raise SystemExit(2)
    squad_dir = _find_current_run_dir(project_root)
    if squad_dir is None:
        print("✗ No active squad run found.", file=sys.stderr)
        raise SystemExit(1)
    from harness.squad_state import SquadStateStore

    store = SquadStateStore(squad_dir)
    state = store.load()
    requests = _issue_resolution_requests(project_root, squad_dir, state)
    matching = next((item for item in requests if item["issue_id"] == issue_id), None)
    if matching is None:
        print(f"✗ {issue_id} is not an unresolved issue in the active run.", file=sys.stderr)
        raise SystemExit(1)
    ledger = state.get("issue_resolution_ledger")
    if not isinstance(ledger, dict):
        ledger = {}
    existing = ledger.get(issue_id)
    if isinstance(existing, dict):
        existing_status = str(existing.get("status") or "").strip()
        existing_decision = " ".join(
            str(existing.get("decision") or "").split()
        )
        normalized_decision = " ".join(decision.split())
        if existing_status == "validated":
            print(
                f"[squad] {issue_id} is already validated; no resolution was changed.",
                flush=True,
            )
            return
        if (
            existing_status in {"selected", "repaired"}
            and existing_decision == normalized_decision
        ):
            print(
                f"[squad] {issue_id} is already recorded with this decision; "
                "no resolution was changed.\n"
                "[squad] next: echelon spec continue",
                flush=True,
            )
            return
    unresolved_before = [
        item["issue_id"]
        for item in requests
        if ledger.get(item["issue_id"], {}).get("status") != "validated"
    ]
    if unresolved_before and unresolved_before[0] != issue_id:
        print(
            f"✗ Resolve {unresolved_before[0]} before {issue_id}; issues are handled in SAGE order.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    ledger[issue_id] = {
        **matching,
        "status": "selected",
        "decision": decision,
        "repair_phase": "phase1-what",
    }
    state["issue_resolution_ledger"] = ledger
    state["selected_issue_resolution"] = issue_id
    # A new decision starts a new targeted-validation allowance, even when it
    # revisits an issue whose previous validation had to be retried.
    state.pop("issue_resolution_revalidation_attempted", None)
    state["issue_resolution_repair_baseline"] = {
        "issue_id": issue_id,
        "repair_phase": "phase1-what",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    # This is a controller-owned recovery edge, not an agent instruction and
    # not a free-form phase override. It is consumed only after the controller
    # verifies that WHY2 declares the repair transition in definition.yaml.
    state["issue_resolution_recovery"] = {
        "issue_id": issue_id,
        "from_phase": "phase1-why2",
        "to_phase": "phase1-what",
        "reason": "issue_resolution",
    }
    dispatch_counts = state.get("phase_dispatch_counts")
    if isinstance(dispatch_counts, dict):
        state["phase_dispatch_counts"] = {
            phase: count
            for phase, count in dispatch_counts.items()
            if phase not in {"phase1-what", "phase1-understanding", "phase1-why2"}
        }
    state["phase"] = "phase1-what"
    state["status"] = "running"
    for key in (
        "blocked_reason",
        "escalation_question",
        "escalation_options",
        "blocked_decision",
        "phase_dispatch_limit",
        "phase_dispatch_limit_phase",
    ):
        state.pop(key, None)
    state["phase_dispatch_limit_recovery"] = {
        "phase": "phase1-what",
        "resolver": "issue_resolution",
    }
    store.save(state)
    print(
        f"[squad] recorded resolution for {issue_id}; the controller will validate "
        "and consume the declared WHY2 → WHAT recovery edge.\n"
        "[squad] next: echelon spec continue",
        flush=True,
    )


def _register_spec_summary_run(
    project_root: Path,
    squad_dir: Path,
    *,
    mode: object,
    message: object,
    implementation_targets: object = (),
) -> None:
    scope = _SPEC_SUMMARY_SCOPE.get()
    if scope is None:
        return
    scope.run_dir = Path(squad_dir)
    scope.mode = str(mode or "semi")
    scope.message = str(message or "")
    if isinstance(implementation_targets, (list, tuple)):
        scope.implementation_targets = tuple(
            str(value) for value in implementation_targets if str(value).strip()
        )


def _note_spec_summary_next_printed() -> None:
    scope = _SPEC_SUMMARY_SCOPE.get()
    if scope is not None:
        scope.next_already_printed = True


@contextmanager
def _spec_summary_session(project_root: Path, command: str):
    active = _SPEC_SUMMARY_SCOPE.get()
    if active is not None:
        yield active
        return
    scope = _SpecSummaryScope(
        project_root=Path(project_root).resolve(),
        command=command,
    )
    token = _SPEC_SUMMARY_SCOPE.set(scope)
    try:
        yield scope
    finally:
        try:
            if scope.run_dir is not None and not scope.emitted:
                state_file = scope.run_dir / "state.json"
                state = json.loads(state_file.read_text(encoding="utf-8"))
                if isinstance(state, dict) and state:
                    persisted_targets = state.get("implementation_targets")
                    fallback_targets = (
                        tuple(
                            str(value)
                            for value in persisted_targets
                            if str(value).strip()
                        )
                        if isinstance(persisted_targets, list)
                        else ()
                    )
                    _print_squad_summary(
                        scope.project_root,
                        scope.run_dir,
                        object(),
                        mode=scope.mode,
                        message=scope.message
                        or str(state.get("user_message") or ""),
                        implementation_targets=list(
                            scope.implementation_targets
                            or fallback_targets
                        ),
                        command=scope.command,
                        include_next=not scope.next_already_printed,
                    )
        except BaseException:
            pass
        finally:
            _SPEC_SUMMARY_SCOPE.reset(token)


def _phase_a_summary_facts(
    state: Mapping[str, object],
    *,
    spec_dir: str,
    stopped: str,
):
    from harness.run_summary import (
        SummaryFact,
        SummaryFactCategory,
        SummaryFactImportance,
    )

    facts: list[SummaryFact] = []
    if spec_dir:
        facts.append(
            SummaryFact(
                SummaryFactCategory.WORK,
                SummaryFactImportance.HIGH,
                f"Published the specification at {spec_dir}.",
                len(facts),
            )
        )
    completed = tuple(
        str(value).strip()
        for value in state.get("completed_phases", ())
        if str(value).strip()
    )
    repair_state = state.get("phase1_quality_repair")
    certificate = state.get("spec_quality_certificate")
    if isinstance(repair_state, Mapping) and isinstance(certificate, Mapping):
        consumed = int(repair_state.get("automatic_consumed", 0) or 0)
        if (
            repair_state.get("authoring_mode") == "proportional"
            and certificate.get("status") == "passed"
        ):
            if consumed == 1:
                quality_text = (
                    "One proportional quality repair produced a passing "
                    "specification quality certificate."
                )
            elif consumed > 1:
                quality_text = (
                    f"{consumed} proportional quality repairs produced a passing "
                    "specification quality certificate."
                )
            else:
                quality_text = (
                    "The proportional quality review produced a passing "
                    "specification quality certificate."
                )
            facts.append(
                SummaryFact(
                    SummaryFactCategory.VERIFICATION,
                    SummaryFactImportance.HIGH,
                    quality_text,
                    len(facts),
                )
            )
    if completed:
        facts.append(
            SummaryFact(
                SummaryFactCategory.HANDOFF,
                SummaryFactImportance.NORMAL,
                f"Completed {len(completed)} specification phases and preserved "
                "durable state.",
                len(facts),
            )
        )
    if stopped and stopped != "completed":
        facts.append(
            SummaryFact(
                SummaryFactCategory.BLOCKER,
                SummaryFactImportance.CRITICAL,
                f"Specification work stopped because {stopped}.",
                len(facts),
            )
        )
    return tuple(facts)


def _print_squad_summary(
    project_root: Path,
    squad_dir: Path,
    result: object,
    *,
    mode: str,
    message: str,
    implementation_targets: list[str] | None = None,
    command: str = "echelon spec run",
    include_next: bool = True,
) -> None:
    """Render a delivery-style Phase A/spec authoring summary."""
    import json as _json

    scope = _SPEC_SUMMARY_SCOPE.get()
    if scope is not None:
        if scope.emitted:
            return

    state: dict = {}
    state_file = squad_dir / "state.json"
    if state_file.exists():
        try:
            state = _json.loads(state_file.read_text(encoding="utf-8"))
        except Exception:
            state = {}

    status = str(getattr(result, "status", "") or state.get("status") or "unknown")
    result_phase = str(getattr(result, "phase", "") or "")
    action = (
        _classify_run_recovery(state, project_root=project_root)
        if state
        else _RunRecoveryAction("advance")
    )
    spec_id = str(state.get("spec_id") or "").strip()
    spec_dir = str(state.get("published_spec_dir") or state.get("spec_dir") or "").strip()
    if not spec_id and spec_dir:
        spec_id = Path(spec_dir).name

    icon = {
        "done": "✓",
        "blocked": "✗",
        "interrupted": "◐",
        "budget_exhausted": "✗",
    }.get(status, "•")
    status_text = {
        "done": "DONE",
        "blocked": "BLOCKED",
        "interrupted": "INTERRUPTED",
        "budget_exhausted": "BUDGET EXHAUSTED",
    }.get(status, status.upper() if status else "UNKNOWN")

    fields: list[tuple[str, str]] = []
    if spec_id:
        fields.append(("spec", spec_id))
    fields.append(("mode", mode))
    if implementation_targets:
        fields.append(("targets", ", ".join(implementation_targets)))
    if message:
        fields.append(("task", message))

    current_phase = _phase_a_current_phase(state, result_phase)
    fields.append(("current", current_phase))
    if spec_dir:
        fields.append(("spec dir", spec_dir))
    fields.append(("artifacts", str(squad_dir)))
    fields.append(("done", _format_completed_phases(state)))

    stopped = ""
    if status == "blocked":
        stopped = action.reason or str(state.get("blocked_reason") or "").strip() or "blocked"
    elif status == "interrupted":
        stopped = action.reason or "interrupted"
    elif status == "budget_exhausted":
        stopped = "token budget exhausted"
    elif status == "done":
        stopped = "completed"
    if stopped:
        fields.append(("stopped", stopped))
    provider_message = str(state.get("provider_limit_message") or "").strip()
    if provider_message:
        fields.append(("provider limit", provider_message))

    debt_facts = _current_quality_debt_cli_facts(state, project_root)
    if debt_facts is not None:
        fields.append(("specification quality", "accepted with quality debt"))
        debt_gates = debt_facts["failed_gates"]
        if debt_gates:
            fields.append(("residual gates", ", ".join(debt_gates)))
        debt_issues = debt_facts["qualitative_issues"]
        if debt_issues:
            fields.append(("residual SAGE", ", ".join(debt_issues)))
        if debt_facts["resolved_by"]:
            fields.append(("debt resolver", str(debt_facts["resolved_by"])))
        if debt_facts["artifact"]:
            fields.append(("debt evidence", str(debt_facts["artifact"])))

    if status in {"blocked", "interrupted", "budget_exhausted"}:
        if action.note:
            fields.append(("note", action.note))
        if status == "blocked" and _is_issue_resolution_recovery(action):
            issues_recap = _current_issues_recap(project_root, squad_dir, state)
            if issues_recap:
                recap, issues_path = issues_recap
                fields.append(("issues", recap))
                guidance = _issue_resolution_guidance_recap(project_root, squad_dir, state)
                if guidance:
                    fields.append(("decisions", guidance))
                fields.extend(
                    _issue_resolution_screen_guidance(project_root, squad_dir, state)
                )
    try:
        summary_decision = _validated_versioned_decision(state)
    except (RecoveryInstructionError, ValueError):
        summary_decision = None
    if summary_decision is not None:
        fields.extend(_decision_audit_fields(summary_decision))
        fields.extend(
            _proportional_quality_decision_fields(state, summary_decision)
        )
    result_line = _phase_a_result_line(status, state)
    fields.append(("result", result_line))
    next_step = ""
    if status == "done" and spec_id:
        next_step = f"echelon delivery run {spec_id}"
    elif status in {"blocked", "interrupted", "budget_exhausted"}:
        next_step = action.command

    from harness.run_summary import RunSummaryContext, summarize_run_for_cli

    facts = _phase_a_summary_facts(state, spec_dir=spec_dir, stopped=stopped)
    worked_on = summarize_run_for_cli(
        RunSummaryContext(
            project_root=project_root,
            command=command,
            task=message,
            status=status,
            facts=facts,
            next_step=next_step,
            quality_debt_status=(
                str(debt_facts["status"]) if debt_facts is not None else ""
            ),
            quality_debt_artifact=(
                str(debt_facts["artifact"]) if debt_facts is not None else ""
            ),
            quality_debt_failed_gates=(
                tuple(debt_facts["failed_gates"])
                if debt_facts is not None
                else ()
            ),
            quality_debt_qualitative_issues=(
                tuple(debt_facts["qualitative_issues"])
                if debt_facts is not None
                else ()
            ),
            quality_debt_resolved_by=(
                str(debt_facts["resolved_by"])
                if debt_facts is not None
                else ""
            ),
            provider_limit_message=provider_message,
        )
    )
    fields.append(("worked on", worked_on))
    if next_step and include_next:
        fields.append(("next", next_step))
    _banner("SQUAD SUMMARY", fields, subtitle=f"{icon} {status_text}")
    if scope is not None:
        scope.emitted = True


def _normalize_rewind_spec_dir(project_root: Path, state: dict) -> tuple[Path | None, str | None]:
    retarget = state.get("retarget")
    published_ref = str(state.get("published_spec_dir") or "").strip()
    if isinstance(retarget, dict) and published_ref:
        published = Path(published_ref)
        if published.is_absolute():
            try:
                relative_published = published.relative_to(project_root)
            except ValueError:
                relative_published = None
        else:
            relative_published = published
            published = project_root / published
        if (
            relative_published is not None
            and relative_published.parts[:1] == ("specs",)
            and published.is_dir()
            and not published.is_symlink()
            and published.name == state.get("spec_id")
        ):
            return published, str(relative_published)
    ref = str(state.get("spec_dir") or "").strip()
    if ref:
        candidate = Path(ref)
        if not candidate.is_absolute():
            candidate = project_root / candidate
        try:
            rel_candidate = candidate.relative_to(project_root)
            if rel_candidate.parts and rel_candidate.parts[0] == "runs":
                if candidate.exists():
                    return candidate, str(rel_candidate)
        except ValueError:
            pass
        parts = candidate.parts
        if "specs" in parts:
            idx = parts.index("specs")
            suffix = Path(*parts[idx:])
            project_candidate = project_root / suffix
            if project_candidate.exists():
                return project_candidate, str(suffix)
        if candidate.exists():
            try:
                return candidate, str(candidate.relative_to(project_root))
            except ValueError:
                return candidate, str(candidate)
    return None, None


def _cleanup_rewind_outputs(spec_dir: Path, phase: str, run_dir: Path | None = None) -> list[str]:
    removed: list[str] = []
    roots = [spec_dir]
    if run_dir is not None:
        run_shadow = run_dir / spec_dir.parent.name / spec_dir.name
        if run_shadow not in roots:
            roots.append(run_shadow)
    for rel in _REWIND_CLEANUP_OUTPUTS.get(phase, ()):
        removed_here = False
        for root in roots:
            path = root / rel
            if path.exists():
                path.unlink()
                removed_here = True
        if removed_here:
            removed.append(rel)
    return removed


def _reset_rewind_state(
    state: dict,
    phase: str,
    spec_dir_ref: str,
    *,
    checkpoint_phases_before_target: set[str] | None = None,
    boundary_completion_id: str = "",
    preserve_resolved_gate_rejection: bool = False,
    preserve_failed_human_gate_for_cas: bool = False,
) -> dict:
    rewound = dict(state)
    rewound["phase"] = phase
    rewound["status"] = "running"
    rewound["iteration"] = 0
    rewound["spec_dir"] = spec_dir_ref
    rewound["blocked_reason"] = None
    decision: Mapping[str, object] | None = None
    try:
        decision = _validated_versioned_decision(state)
    except (RecoveryInstructionError, ValueError) as exc:
        from echelon.rewind import RewindError

        raise RewindError(f"versioned decision authority is invalid: {exc}") from exc
    if decision is not None:
        resolved_gate_rejection = (
            preserve_resolved_gate_rejection
            and decision["status"] == "resolved"
            and decision["source_kind"] == "human_gate"
            and state.get("status") == "blocked"
            and state.get("blocked_reason") == "gate_rejected"
        )
        failed_human_gate = (
            preserve_failed_human_gate_for_cas
            and decision["status"] == "failed"
            and decision["source_kind"] == "human_gate"
            and state.get("status") == "blocked"
            and state.get("phase") == decision.get("source_phase")
        )
        if not (resolved_gate_rejection or failed_human_gate):
            from echelon.rewind import RewindError

            raise RewindError(
                "versioned decision authority requires its source-specific recovery"
            )
    else:
        rewound["escalation_question"] = None
        rewound["escalation_resolved"] = False
        rewound["escalation_resolver"] = None
    rewound.pop("phase_a_readiness_blockers", None)
    # A rewind reopens the target phase's owned repair loop.  Retaining an
    # exhausted Lexicon certificate makes CARTOGRAPHER/ORCHESTRATOR conclude
    # that they have no repair budget before they inspect the restored files.
    # Reset only the gates whose owning phase is being revisited.
    try:
        phase_index = _ROADMAP_PHASES.index(phase)
    except ValueError:
        phase_index = len(_ROADMAP_PHASES)
    # Issues, selected resolutions, and WHY failure counters are valid only
    # for the artifact epoch that produced them. Rewinding before WHY2 must not
    # let a stale spec review steer discovery or assumption validation.
    if phase_index <= _ROADMAP_PHASES.index("phase1-why2"):
        rewound.pop("spec_quality_certificate", None)
        for key in (
            "issue_resolution_ledger",
            "selected_issue_resolution",
            "issue_resolution_recovery",
            "issue_resolution_repair_baseline",
            "phase_dispatch_limit_recovery",
            "issues_log",
            "why_failure_baseline",
        ):
            rewound.pop(key, None)
        rewound["why_fail_count"] = 0
        rewound["why2_metric_stagnation_count"] = 0
    if phase_index <= _ROADMAP_PHASES.index("phase1-lexicon"):
        rewound.pop("lexicon_pass", None)
        rewound["lexicon_attempts"] = 0
        rewound.pop("lexicon_findings", None)
        rewound.pop("lexicon_report", None)
        rewound.pop("lexicon_warning_waiver", None)
        rewound["lexicon_evaluation"] = "pending"
        rewound.pop("lexicon_gate_exhausted", None)
    if phase_index <= _ROADMAP_PHASES.index("phase3-plan"):
        rewound["tasks_lexicon_pass"] = None
        rewound["tasks_lexicon_attempts"] = 0
        rewound.pop("tasks_lexicon_gate_exhausted", None)
    if rewound.get("checkpoint_policy_version") == 2:
        from echelon.rewind import RewindError

        outcomes = rewound.get("phase_completion_outcomes")
        if type(outcomes) is not list or not boundary_completion_id:
            raise RewindError("versioned checkpoint boundary is missing")
        matches = [
            index
            for index, outcome in enumerate(outcomes)
            if type(outcome) is dict
            and outcome.get("completion_id") == boundary_completion_id
            and outcome.get("phase") == phase
            and outcome.get("outcome") == "executed"
        ]
        if len(matches) != 1:
            raise RewindError("versioned checkpoint boundary is invalid")
        retained_outcomes = outcomes[: matches[0]]
        rewound["phase_completion_outcomes"] = retained_outcomes
        completed: list[str] = []
        for outcome in retained_outcomes:
            if type(outcome) is not dict or outcome.get("outcome") != "executed":
                continue
            completed_phase = outcome.get("phase")
            if isinstance(completed_phase, str) and completed_phase not in completed:
                completed.append(completed_phase)
        rewound["completed_phases"] = completed
        counts = rewound.get("phase_dispatch_counts")
        if isinstance(counts, dict):
            rewound["phase_dispatch_counts"] = {
                key: value for key, value in counts.items() if key in completed
            }
    elif checkpoint_phases_before_target is not None:
        completed = rewound.get("completed_phases")
        primary_predecessors: list[str] = []
        if phase in _ROADMAP_PHASES:
            primary_predecessors = _ROADMAP_PHASES[:_ROADMAP_PHASES.index(phase)]
        if isinstance(completed, list):
            # Checkpoints are deliberately sparse: the roadmap's primary
            # predecessors are known complete when rewinding to a later phase,
            # even if no individual checkpoint was emitted for them.  Preserve
            # any additional checkpointed branch phases after that backbone.
            retained = [
                item
                for item in completed
                if item in checkpoint_phases_before_target and item not in _ROADMAP_PHASES
            ]
            rewound["completed_phases"] = primary_predecessors + [
                item for item in retained if item not in primary_predecessors
            ]
        counts = rewound.get("phase_dispatch_counts")
        if isinstance(counts, dict):
            rewound["phase_dispatch_counts"] = {
                key: value
                for key, value in counts.items()
                if key in rewound.get("completed_phases", [])
            }
    return rewound


def _iter_run_dirs(project_root: Path) -> list[Path]:
    """Return all spec run dirs under runs/, sorted newest-first."""
    dirs: list[Path] = []
    base = project_root / "runs"
    if base.exists():
        for d in base.iterdir():
            if d.is_dir() and not d.name.startswith(".") and (d / "state.json").exists():
                dirs.append(d)
    dirs.sort(key=lambda d: d.name, reverse=True)
    return dirs


def _find_latest_harness_build_state(project_root: Path) -> Optional[dict]:
    """Return the newest readable harness build state, unless newer spec work exists.

    Returns None when a newer squad run exists than the newest harness build;
    that means new spec work has been done since the last harness run.
    """
    import json as _json
    runs = project_root / "runs"
    if not runs.exists():
        return None

    # Latest squad-run timestamp (spec-* current format, run-* legacy)
    latest_squad_ts = ""
    for d in runs.iterdir():
        if (
            d.is_dir()
            and (d.name.startswith("spec-") or d.name.startswith("run-"))
            and (d / "state.json").exists()
        ):
            ts = d.name.partition("-")[2]  # "YYYYMMDD-HHMMSS-ffffff"
            if ts > latest_squad_ts:
                latest_squad_ts = ts

    for build in sorted(runs.glob("build-*/"), reverse=True):
        build_ts = build.name.partition("-")[2]
        if latest_squad_ts > build_ts:
            # A squad run is newer than this harness build — new spec work exists
            return None
        state_dir = build / "state"
        if not state_dir.exists():
            continue
        for state_file in sorted(state_dir.glob("*.json")):
            try:
                data = _json.loads(state_file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    data.setdefault("build_id", build.name)
                    return data
            except Exception:
                pass
    return None


def _iter_harness_build_states(project_root: Path) -> list[dict]:
    import json as _json

    states: list[dict] = []
    runs = project_root / "runs"
    if not runs.exists():
        return states
    for build in sorted(runs.glob("build-*/"), reverse=True):
        state_dir = build / "state"
        if not state_dir.exists():
            continue
        for state_file in sorted(state_dir.glob("*.json")):
            try:
                data = _json.loads(state_file.read_text(encoding="utf-8"))
            except Exception:
                continue
            if isinstance(data, dict):
                data.setdefault("build_id", build.name)
                data.setdefault("strategy_id", state_file.stem)
                data.setdefault("state_file", str(state_file))
                states.append(data)
    return states


def _parse_delivery_status_args(args: list[str]) -> tuple[str, str, bool]:
    spec_id = ""
    strategy = ""
    json_output = False
    index = 0
    while index < len(args):
        arg = args[index]
        if arg in {"-h", "--help"}:
            print(
                "Usage: echelon delivery status [spec_id] [--strategy <id>] [--json]\n\n"
                "Show Phase B delivery/Ralph status. Without spec_id, shows the latest "
                "delivery state across specs."
            )
            raise SystemExit(0)
        if arg == "--json":
            json_output = True
        elif arg == "--strategy":
            index += 1
            if index >= len(args):
                print("echelon delivery status: --strategy requires a value", file=sys.stderr)
                raise SystemExit(1)
            strategy = args[index].strip()
        elif arg.startswith("--strategy="):
            strategy = arg.split("=", 1)[1].strip()
        elif arg.startswith("strategy="):
            strategy = arg.split("=", 1)[1].strip()
        elif arg.startswith("-"):
            print(f"echelon delivery status: unknown option '{arg}'", file=sys.stderr)
            raise SystemExit(1)
        elif not spec_id:
            spec_id = arg.strip()
        else:
            print(
                "echelon delivery status: expected at most one spec_id",
                file=sys.stderr,
            )
            raise SystemExit(1)
        index += 1
    return spec_id, strategy, json_output


def _delivery_status_next_step(state: dict, spec_id: str) -> str:
    status = str(state.get("status") or "unknown")
    termination_reason = str(state.get("termination_reason") or "")
    effective_spec = spec_id or str(state.get("spec_id") or "<spec_id>")
    if status == "converged":
        return f"echelon delivery land {effective_spec}"
    if status == "blocked":
        if str(state.get("escalation_file") or ""):
            return f'echelon delivery resume {effective_spec} "<answer>"'
        if termination_reason == "verify_command_needed":
            return "set delivery.verify_command, then echelon delivery continue " + effective_spec
        return f"echelon delivery continue {effective_spec}"
    if status in {"initialized", "running", "interrupted"}:
        return f"echelon delivery continue {effective_spec}"
    if status in {"failed", "cancelled_by_coordinator"}:
        return f"inspect state, then echelon delivery run {effective_spec} --reset if needed"
    return f"echelon delivery run {effective_spec}"


def _delivery_status_summary(
    state: dict,
    *,
    project_root: Path,
) -> dict:
    spec_id = str(state.get("spec_id") or "")
    strategy = str(state.get("strategy_id") or "default")
    status = str(state.get("status") or "unknown")
    checkpoints = state.get("checkpoint_commits")
    checkpoint_count = len(checkpoints) if isinstance(checkpoints, list) else 0
    summary = {
        "spec_id": spec_id,
        "strategy": strategy,
        "build_id": str(state.get("build_id") or ""),
        "status": status,
        "mode": str(state.get("mode") or ""),
        "outer_iter": int(state.get("outer_iter") or 0),
        "inner_iter": int(state.get("inner_iter") or 0),
        "tokens_used": int(state.get("tokens_used") or 0),
        "token_budget": state.get("token_budget"),
        "termination_reason": str(state.get("termination_reason") or ""),
        "build_status": str(state.get("build_status") or ""),
        "build_reason": str(state.get("build_reason") or ""),
        "pr_url": str(state.get("pr_url") or ""),
        "target_branch": str(state.get("target_branch") or ""),
        "target_commit": str(state.get("target_commit") or ""),
        "salvage_branch": str(state.get("salvage_branch") or ""),
        "salvage_commit": str(state.get("salvage_commit") or ""),
        "checkpoint_count": checkpoint_count,
        "state_file": str(state.get("state_file") or ""),
        "next": _delivery_status_next_step(state, spec_id),
    }
    try:
        from harness.spec_frontmatter import find_spec_dir, read_frontmatter

        spec_dir = find_spec_dir(spec_id, project_root) if spec_id else None
        if spec_dir is not None:
            summary["spec_dir"] = str(spec_dir)
            frontmatter = read_frontmatter(spec_dir)
            if frontmatter.get("status"):
                summary["spec_status"] = str(frontmatter.get("status"))
            try:
                from harness.harness_run_history import summarize_history

                history = summarize_history(spec_dir, limit=1)
                summary["history_count"] = int(history.get("count") or 0)
                recent = history.get("recent")
                if isinstance(recent, list) and recent:
                    latest = recent[-1]
                    if isinstance(latest, dict):
                        summary["last_finished_at"] = str(latest.get("finished_at") or "")
            except Exception:
                pass
    except Exception:
        pass
    return summary


def _delivery_status_fields(summary: dict) -> list[tuple[str, str]]:
    status_icon = {
        "converged": "ok",
        "blocked": "blocked",
        "running": "running",
        "initialized": "initialized",
        "failed": "failed",
        "interrupted": "interrupted",
    }.get(str(summary.get("status") or ""), "status")
    fields: list[tuple[str, str]] = [
        ("spec", str(summary.get("spec_id") or "-")),
        ("strategy", str(summary.get("strategy") or "default")),
        ("build", str(summary.get("build_id") or "-")),
        ("status", f"{status_icon}: {summary.get('status') or 'unknown'}"),
    ]
    if summary.get("spec_status"):
        fields.append(("spec status", str(summary["spec_status"])))
    if summary.get("mode"):
        fields.append(("mode", str(summary["mode"])))
    fields.append(("iteration", f"{summary.get('outer_iter', 0)}.{summary.get('inner_iter', 0)}"))
    tokens = int(summary.get("tokens_used") or 0)
    budget = summary.get("token_budget")
    if budget:
        try:
            budget_int = int(budget)
            pct = (tokens / budget_int) * 100 if budget_int else 0
            fields.append(("tokens", f"{tokens:,} / {budget_int:,} ({pct:.0f}%)"))
        except (TypeError, ValueError):
            fields.append(("tokens", f"{tokens:,}"))
    else:
        fields.append(("tokens", f"{tokens:,}"))
    for key, label in (
        ("termination_reason", "reason"),
        ("build_status", "build status"),
        ("build_reason", "build reason"),
        ("pr_url", "PR"),
        ("target_branch", "target branch"),
        ("target_commit", "target commit"),
        ("salvage_branch", "salvage branch"),
        ("salvage_commit", "salvage commit"),
    ):
        value = str(summary.get(key) or "").strip()
        if value:
            fields.append((label, value[:12] if key.endswith("_commit") else value))
    checkpoint_count = int(summary.get("checkpoint_count") or 0)
    if checkpoint_count:
        fields.append(("checkpoints", str(checkpoint_count)))
    history_count = summary.get("history_count")
    if history_count is not None:
        fields.append(("history", f"{history_count} delivery run(s) recorded"))
    if summary.get("state_file"):
        fields.append(("state", str(summary["state_file"])))
    fields.append(("next", str(summary.get("next") or "")))
    return fields


def _cmd_delivery_status(args: list[str], *, project_root: Path | None = None) -> None:
    import json as _json

    root = project_root or Path.cwd()
    spec_id, strategy, json_output = _parse_delivery_status_args(args)
    _require_provider_capability(
        "echelon delivery status",
        ProviderCapability.BUILD,
        project_dir=root,
    )
    states = _iter_harness_build_states(root)
    if spec_id:
        states = [state for state in states if str(state.get("spec_id") or "") == spec_id]
    if strategy:
        states = [state for state in states if str(state.get("strategy_id") or "") == strategy]

    summaries = [_delivery_status_summary(state, project_root=root) for state in states]
    if json_output:
        payload = {
            "status": summaries[0]["status"] if summaries else "none",
            "spec_id": spec_id or (summaries[0].get("spec_id") if summaries else ""),
            "strategy": strategy,
            "latest": summaries[0] if summaries else None,
            "states": summaries[:10],
        }
        print(_json.dumps(payload, indent=2, ensure_ascii=False))
        return

    if not summaries:
        next_step = f"echelon delivery run {spec_id}" if spec_id else "echelon delivery run <spec_id>"
        _banner(
            "DELIVERY STATUS",
            [
                ("status", "No delivery runs found"),
                ("next", next_step),
            ],
            subtitle="Phase B delivery",
        )
        return

    latest = summaries[0]
    subtitle = "Phase B delivery"
    if len(summaries) > 1:
        subtitle += f" - {len(summaries)} matching state files"
    _banner("DELIVERY STATUS", _delivery_status_fields(latest), subtitle=subtitle)


def _find_harness_checkpoint_state(
    project_root: Path,
    spec_id: str,
    strategy_id: str = "",
) -> Optional[dict]:
    for state in _iter_harness_build_states(project_root):
        if str(state.get("spec_id") or "") != spec_id:
            continue
        if strategy_id and str(state.get("strategy_id") or "") != strategy_id:
            continue
        return state
    return None


def _cmd_delivery_checkpoint(args: list[str], *, project_root: Path | None = None) -> None:
    if not args or args[0] in {"-h", "--help", "help"}:
        print(
            "Usage:\n"
            "  echelon delivery checkpoint list <spec_id> [--strategy <id>]\n\n"
            "Lists delivery checkpoint/recovery commits recorded by Ralph/harness.\n"
        )
        return
    subcmd = args[0]
    if subcmd != "list":
        print(f"echelon delivery checkpoint: unknown subcommand '{subcmd}'\n", file=sys.stderr)
        sys.exit(1)
    if len(args) < 2:
        print("Usage: echelon delivery checkpoint list <spec_id> [--strategy <id>]", file=sys.stderr)
        sys.exit(1)

    spec_id = args[1]
    strategy = ""
    if "--strategy" in args:
        idx = args.index("--strategy")
        if idx + 1 >= len(args):
            print("--strategy requires a value", file=sys.stderr)
            sys.exit(1)
        strategy = args[idx + 1]
    for raw in args[2:]:
        if raw.startswith("strategy="):
            strategy = raw.split("=", 1)[1]

    root = project_root or Path.cwd()
    _require_provider_capability(
        "echelon delivery checkpoint",
        ProviderCapability.BUILD,
        project_dir=root,
    )
    state = _find_harness_checkpoint_state(root, spec_id, strategy)
    if state is None:
        strategy_suffix = f" strategy {strategy!r}" if strategy else ""
        print(f"No delivery checkpoint state found for {spec_id!r}{strategy_suffix}.", file=sys.stderr)
        sys.exit(1)

    strategy_label = str(state.get("strategy_id") or strategy or "default")
    print(f"CHECKPOINTS - delivery {spec_id} (strategy {strategy_label})\n")
    rows: list[tuple[str, str, str, str, str]] = []
    checkpoints = state.get("checkpoint_commits")
    if isinstance(checkpoints, list):
        for checkpoint in checkpoints:
            if not isinstance(checkpoint, dict):
                continue
            commit = str(checkpoint.get("commit") or "").strip()
            if not commit:
                continue
            phase = str(checkpoint.get("phase") or "").strip() or "-"
            phase_group = str(checkpoint.get("phase_group") or "").strip()
            task_ids = checkpoint.get("task_ids")
            tasks = ",".join(str(item) for item in task_ids) if isinstance(task_ids, list) else "-"
            label = phase_group or phase
            rows.append((commit[:7], "checkpoint", phase, tasks or "-", label or "-"))

    for key, kind in (("salvage_commit", "salvage"), ("target_commit", "target")):
        commit = str(state.get(key) or "").strip()
        if commit:
            rows.append((commit[:7], kind, "-", "-", str(state.get("target_branch") or state.get("salvage_branch") or "-")))

    if not rows:
        print("(none)")
        return

    print("COMMIT   KIND        PHASE      TASKS                 CONTEXT")
    for commit, kind, phase, tasks, context in rows:
        print(f"{commit:<8} {kind:<11} {phase:<10} {tasks:<21} {context}")


def _find_converged_harness_build(project_root: Path) -> Optional[tuple[str, Optional[str]]]:
    """Return (spec_id, pr_url) when the most recent harness build converged."""
    data = _find_latest_harness_build_state(project_root)
    if data and data.get("status") == "converged":
        return data.get("spec_id", ""), data.get("pr_url")
    return None


def _has_tracked_checkout_changes(project_root: Path) -> bool:
    import subprocess as _subprocess

    try:
        result = _subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception:
        return False
    return bool(result.stdout.strip())


def _constitution_template_markers(text: str) -> list[str]:
    import re as _re

    explicit_markers = (
        "[PROJECT_NAME]",
        "[CONSTITUTION_VERSION]",
        "[RATIFICATION_DATE]",
        "[LAST_AMENDED_DATE]",
    )
    markers = [marker for marker in explicit_markers if marker in text]
    markers.extend(sorted(set(_re.findall(r"\[PRINCIPLE_[0-9]+_NAME\]", text))))
    return markers


_HARNESS_CHECKPOINT_REASONS = {"build_incomplete", "publish_failed", "checkpoint_outer_cap"}


def _phase_a_buildable(result_status: str, blockers: list) -> bool:
    """Single readiness predicate for Phase-A surfaces.

    A run is buildable only when there are no outstanding blockers AND the run
    is not in a blocked/interrupted lifecycle state. A blocked run with an empty
    blocker list (e.g. it halted before the spec/HOW/tasks checks could flag
    anything) must NOT be reported as ready — that was the false "READY TO BUILD"
    bug (docs/findings/2026-06-20-blocked-run-reports-ready-to-build.md).
    """
    return not blockers and result_status not in ("blocked", "interrupted")


def _print_next_steps(project_root: Path, result_status: str) -> None:
    """Print actionable next-step guidance after a run completes or blocks.

    Checks build readiness (constitution, quality gates, HOW phase, tasks) and
    surfaces either 'ready to build' or a prioritised list of blockers. Silent
    when the run is still in progress (status not in done/blocked/interrupted).
    """
    import json as _json
    import re as _re

    if result_status not in ("done", "blocked", "interrupted"):
        return

    # ── Latest harness build owns next-step guidance when present ───────────
    harness_state = _find_latest_harness_build_state(project_root)
    if harness_state:
        spec_id = str(harness_state.get("spec_id") or "")
        pr_url = harness_state.get("pr_url")
        harness_status = str(harness_state.get("status") or "unknown")
        termination_reason = str(harness_state.get("termination_reason") or "")
        fields: list[tuple[str, str]] = [("spec", spec_id)] if spec_id else []
        if harness_status == "converged":
            if pr_url:
                fields.append(("PR", pr_url))
                fields.append(("next", f"echelon delivery land {spec_id}"))
            else:
                fields.append(("next", f"echelon delivery land {spec_id}"))
            _banner("NEXT STEP", fields, subtitle="Harness build converged — ready to land")
            return
        fields.append(("harness status", harness_status))
        if termination_reason:
            fields.append(("reason", termination_reason))
        build_status = str(harness_state.get("build_status") or "")
        build_reason = str(harness_state.get("build_reason") or "")
        if build_status:
            fields.append(("build status", build_status))
        if build_reason and build_reason != "None":
            fields.append(("build reason", build_reason))
        provider_reset_hint = str(harness_state.get("provider_reset_hint") or "")
        provider_limit_message = str(harness_state.get("provider_limit_message") or "")
        if provider_limit_message:
            fields.append(("provider", provider_limit_message))
        if provider_reset_hint:
            fields.append(("reset", provider_reset_hint))
        tokens_used = harness_state.get("tokens_used")
        if build_status == "provider_session_limit":
            fields.append(("token accounting", f"{int(tokens_used or 0):,} tokens recorded before provider stop"))
        salvage_commit = str(harness_state.get("salvage_commit") or "")
        salvage_branch = str(harness_state.get("salvage_branch") or "")
        salvage_verified = str(harness_state.get("salvage_verified") or "")
        if salvage_commit:
            fields.append(("salvage commit", salvage_commit[:12]))
        if salvage_branch:
            fields.append(("salvage branch", salvage_branch))
        if salvage_verified:
            fields.append(("salvage verified", salvage_verified))
        is_checkpoint = termination_reason in _HARNESS_CHECKPOINT_REASONS
        if build_status == "provider_session_limit":
            fields.append(("next", f"wait for provider reset, then echelon delivery continue {spec_id}"))
            subtitle = "HARNESS PROVIDER SESSION LIMIT"
        elif termination_reason == "build_blocked":
            fields.append(("next", f"resolve the reported blocker, then echelon spec reopen {spec_id}"))
            subtitle = "HARNESS BUILD BLOCKED"
        elif is_checkpoint:
            if _has_tracked_checkout_changes(project_root):
                fields.append(
                    (
                        "blocked by",
                        "tracked checkout changes block harness recovery",
                    )
                )
                fields.append(
                    (
                        "next",
                        f"commit or stash tracked changes, then echelon delivery continue {spec_id}",
                    )
                )
            else:
                fields.append(("next", f"echelon delivery continue {spec_id}"))
        elif termination_reason == "docker_unavailable":
            fields.append(("fix", "start the configured container runtime and wait until it reports running"))
            fields.append(("next", f"echelon delivery continue {spec_id}"))
            subtitle = "HARNESS BUILD BLOCKED"
        elif harness_status in {"running", "in_progress"}:
            fields.append(("next", "echelon spec status"))
            subtitle = "HARNESS BUILD IN PROGRESS"
        else:
            fields.append(("next", f"echelon delivery run {spec_id} --reset"))
            subtitle = "HARNESS BUILD BLOCKED"
        if is_checkpoint and build_status != "provider_session_limit":
            subtitle = "HARNESS BUILD CHECKPOINTED"
        _banner("NEXT STEP", fields, subtitle=subtitle)
        return

    # ── Gather signals ──────────────────────────────────────────────────────
    blockers: list[str] = []
    warnings: list[str] = []
    ready_items: list[str] = []
    current_state: dict = {}
    run_dir = _find_current_run_dir(project_root)
    if run_dir and (run_dir / "state.json").exists():
        try:
            current_state = _json.loads((run_dir / "state.json").read_text())
        except Exception:
            current_state = {}

    if result_status in {"blocked", "interrupted"}:
        action = _classify_run_recovery(current_state, project_root=project_root)
        if action.kind == "human_resume":
            question = action.note
            if run_dir is not None:
                from harness.squad import _checkpoint_context

                phase = str(current_state.get("phase") or "")
                label = {
                    "checkpoint-assess": "Phase 1 Checkpoint",
                    "checkpoint-plan": "Plan Checkpoint",
                }.get(phase, phase)
                question += _checkpoint_context(
                    current_state,
                    node_id=phase,
                    node_label=label,
                    journal_path=run_dir / "reasoning-journal.jsonl",
                )
            fields = [
                ("reason", action.reason),
                ("question", question),
            ]
            rendered_options = _render_escalation_options(
                current_state.get("escalation_options")
            )
            if rendered_options:
                fields.append(("options", rendered_options))
            fields.append(("next", action.command))
            _banner("NEXT STEP", fields, subtitle="RUN BLOCKED — answer required")
            return
        if action.kind == "safe_rewind":
            fields = [
                ("reason", action.reason),
                ("phase", action.phase or "?"),
                ("next", action.command),
            ]
            _banner("NEXT STEP", fields, subtitle="RUN BLOCKED")
            return
        if action.kind == "retry_phase":
            fields = [
                ("reason", action.reason),
                ("phase", action.phase),
                ("next", action.command),
                ("note", action.note),
            ]
            _banner(
                "NEXT STEP",
                fields,
                subtitle="RUN INTERRUPTED" if result_status == "interrupted" else "RUN BLOCKED",
            )
            return
        if action.kind == "resolve_decision":
            fields = [
                ("reason", action.reason),
                ("phase", action.phase),
                ("next", action.command),
                ("note", action.note),
            ]
            _banner(
                "NEXT STEP",
                fields,
                subtitle="RUN BLOCKED — controller-owned decision resolution pending",
            )
            return
        if action.kind == "manual_recovery":
            fields = [
                ("reason", action.reason),
                ("note", action.note),
            ]
            if action.command:
                fields.insert(1, ("next", action.command))
            if run_dir is not None and _is_issue_resolution_recovery(action):
                fields.extend(
                    _issue_resolution_screen_guidance(project_root, run_dir, current_state)
                )
            _banner(
                "NEXT STEP",
                fields,
                subtitle="RUN INTERRUPTED — manual recovery required"
                if result_status == "interrupted"
                else "RUN BLOCKED — manual recovery required",
            )
            return

    # 1. Constitution — phase provenance first, artifact integrity second
    completed = current_state.get("completed_phases")
    completed_phases = completed if isinstance(completed, list) else []
    from echelon.constitution import canonical_constitution_path

    const_path = canonical_constitution_path(project_root)
    if current_state and "phase1-constitution" not in completed_phases:
        blockers.append(
            "phase1-constitution has not completed in this run\n"
            "     → echelon spec continue\n"
            "       (CHIEF will author the constitution and record provenance)"
        )
    elif not const_path.exists():
        blockers.append(
            "constitution.md absent\n"
            "     → echelon spec continue\n"
            "       (CHIEF will author the constitution)"
        )
    else:
        markers = _constitution_template_markers(const_path.read_text(errors="replace"))
        if markers:
            blockers.append(
                "unresolved constitution template markers remain: "
                + ", ".join(markers)
                + "\n"
                "     → echelon spec continue\n"
                "       (CHIEF will repair constitution.md before continuing)"
            )
        else:
            ready_items.append("constitution.md ✓")

    # 2. Quality gates — prefer the active run spec root. Published specs/ is
    # the build-harness target, not the source of truth for an in-progress squad.
    specs_root = project_root / "specs"
    active_spec_dir = _active_continue_spec_dir(project_root, current_state, run_dir)
    published_spec_dir: Path | None = None
    if result_status == "done":
        published_spec_dir = _published_continue_spec_dir(project_root, current_state)
        if published_spec_dir and (published_spec_dir / "tasks.md").exists():
            active_spec_dir = published_spec_dir

    # Pre-check: if tasks.md already exists, the run completed all phases past quality gates.
    # Also capture newest_spec_id here so the build command always has the actual spec name.
    tasks_exist_in_spec = False
    newest_spec_id = str(current_state.get("spec_id") or "").strip()
    if active_spec_dir is not None:
        newest_spec_id = newest_spec_id or active_spec_dir.name
        tasks_exist_in_spec = (active_spec_dir / "tasks.md").exists()

    quality_gates_file: Optional[Path] = None
    if active_spec_dir is not None:
        qg = active_spec_dir / "quality-gates.md"
        if qg.exists():
            quality_gates_file = qg

    # Blocked runs may not have finalized to specs/ yet — load state once for reuse
    run_dir = _find_current_run_dir(project_root)
    run_state: dict = {}
    if run_dir:
        try:
            run_state = _json.loads((run_dir / "state.json").read_text())
        except Exception:
            pass
    if not newest_spec_id:
        newest_spec_id = str(run_state.get("spec_id") or "").strip()

    if quality_gates_file is None and run_state:
        staging_dir = Path(run_state.get("staging_dir") or str(run_dir / "staging"))
        staging_qg = staging_dir / "quality-gates.md"
        if staging_qg.exists():
            quality_gates_file = staging_qg

    hard_fails: list[str] = []
    borderline: list[str] = []
    fail_scores: dict[str, tuple[str, str]] = {}  # gate -> (score, threshold)
    qg_verdict = ""

    if quality_gates_file:
        qg_text = quality_gates_file.read_text(errors="replace")

        verdict_m = _re.search(r"^##\s+Verdict:\s+(PASS|FAIL|BLOCKED)", qg_text, _re.MULTILINE)
        qg_verdict = verdict_m.group(1) if verdict_m else ""

        # Parse gate rows: | Gate | score | threshold | PASS/FAIL | note |
        # Matches plain FAIL and bold **FAIL** (NEVER rule in sage.md enforces plain text)
        gate_pattern = _re.compile(
            r"\|\s*(Overall|Structure|Testability|Semantic|Cognitive|Readability|Behavioral|Depth)"
            r"\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|\s*\*{0,2}FAIL\*{0,2}\s*\|([^|]*)\|",
        )
        for m in gate_pattern.finditer(qg_text):
            gate, score, threshold, note = (
                m.group(1), m.group(2).strip(), m.group(3).strip(), m.group(4)
            )
            fail_scores[gate] = (score, threshold)
            note_lower = note.lower()
            if "borderline" in note_lower and "not borderline" not in note_lower:
                borderline.append(gate)
            else:
                hard_fails.append(gate)

        if hard_fails:
            fail_detail = ", ".join(
                f"{g} {fail_scores[g][0]} (need {fail_scores[g][1]})"
                if g in fail_scores else g
                for g in hard_fails
            )
            if tasks_exist_in_spec:
                # Run already completed all phases past quality gates — quality debt, not a blocker
                warnings.append(
                    f"Quality debt: WHY gates FAIL: {fail_detail}\n"
                    f"  (run converged past gates — amendment improves future estimates)"
                )
            else:
                blockers.append(
                    f"WHY2 quality gates FAIL: {fail_detail}\n"
                    f"     → echelon spec continue\n"
                    f"       (CARTOGRAPHER amendment pass, then WHY2 re-validates)"
                )
        if borderline:
            warnings.append(
                f"WHY2 borderline: {', '.join(borderline)} — monitor after CARTOGRAPHER amendment"
            )
        # Verdict FAIL/BLOCKED with no numeric rows = SAGE ran in BLOCKED mode (spec.md absent)
        if qg_verdict in ("FAIL", "BLOCKED") and not hard_fails and not borderline:
            if not tasks_exist_in_spec:
                blockers.append(
                    "WHY2 BLOCKED — spec.md absent: CARTOGRAPHER has not written it yet\n"
                    "     → echelon spec continue\n"
                    "       (CARTOGRAPHER will write spec.md, then WHY2 re-validates)"
                )
        if not hard_fails and not borderline and qg_verdict not in ("FAIL", "BLOCKED"):
            ready_items.append("WHY2 quality gates ✓")
    else:
        warnings.append("WHY2 not yet run — spec validation pending")

    # 3. HOW phase artifacts — only surface when quality gates have passed
    # (if gates are hard-failing, HOW/tasks missing is expected and not actionable yet)
    # Borderline-only quality gates still allow Phase 3 to proceed.
    # Skip HOW check entirely when tasks.md already exists — the run completed,
    # so HOW was done (possibly with different artifact names for this workflow).
    why2_passed = tasks_exist_in_spec or (
        quality_gates_file is not None
        and not hard_fails  # borderline-only is fine — only hard fails block Phase 3
    )
    how_present = 0
    how_missing = []
    if why2_passed and not tasks_exist_in_spec and active_spec_dir is not None:
        for fname in ("plan.md", "research.md", "data-model.md"):
            if (active_spec_dir / fname).exists():
                how_present += 1
            else:
                how_missing.append(fname)

    if how_missing:
        missing_str = ", ".join(dict.fromkeys(how_missing))  # dedup, preserve order
        blockers.append(
            f"HOW phase not run — {missing_str} absent\n"
            f"     → echelon spec continue\n"
            f"       (ARCHITECT commits stack, data-model, contracts)"
        )
    elif why2_passed:
        ready_items.append("HOW artifacts ✓")

    # 4. tasks.md — only surface when quality gates have passed
    tasks_present = False
    if why2_passed and active_spec_dir is not None and (active_spec_dir / "tasks.md").exists():
        tasks_present = True
        ready_items.append("tasks.md ✓")

    if why2_passed and not tasks_present:
        blockers.append(
            "tasks.md absent — ORCHESTRATOR (phase3-plan) has not run\n"
            "     → echelon spec continue"
        )

    readiness_state = dict(run_state or current_state)
    readiness_state["status"] = result_status
    if run_state.get("blocked_reason"):
        readiness_state["blocked_reason"] = run_state.get("blocked_reason")
    readiness = validate_phase_a_readiness(
        readiness_state,
        _phase_a_readiness_candidate_dirs(
            project_root,
            readiness_state,
            run_dir,
            active_spec_dir=active_spec_dir,
            published_spec_dir=published_spec_dir,
        ),
    )
    for blocker in readiness.blockers:
        if blocker not in blockers:
            blockers.append(blocker)

    # 5. Blocked run — surface escalation context and improvement recommendations
    if result_status == "blocked":
        blocked_reason = run_state.get("blocked_reason") or ""
        escalation_q = run_state.get("escalation_question") or ""

        # Extract improvement recommendations from quality-gates.md
        improvement_lines: list[str] = []
        if quality_gates_file:
            try:
                qg_for_tips = quality_gates_file.read_text(errors="replace")
                in_section = False
                for line in qg_for_tips.splitlines():
                    if _re.match(r"^##\s+(Metric Improvement|Action Required)", line):
                        in_section = True
                        continue
                    if in_section:
                        if line.startswith("## ") or line.startswith("# "):
                            break
                        stripped = line.strip()
                        if stripped and not stripped.startswith("<!--"):
                            improvement_lines.append(stripped)
                            if len(improvement_lines) >= 8:
                                break
            except Exception:
                pass

        if blocked_reason == "consecutive_why_fails":
            msg_lines = ["Run blocked: 2+ consecutive WHY FAILs — spec is not improving"]
            if improvement_lines:
                msg_lines.append("  Recommended fixes (from quality-gates.md):")
                for il in improvement_lines[:6]:
                    msg_lines.append(f"    {il}")
            msg_lines.append(
                "  → echelon spec resume \"<tell CARTOGRAPHER what to fix>\"\n"
                "    e.g. \"Fix structure: split compound FRs, add numeric thresholds\""
            )
            warnings.append("\n".join(msg_lines))
        elif escalation_q:
            warnings.append(
                f"Run blocked: {escalation_q}\n"
                "     → echelon spec resume \"<your answer>\""
            )
        else:
            warnings.append(
                "Run blocked\n"
                "     → echelon spec resume \"<your answer>\""
            )

    # ── Print ──────────────────────────────────────────────────────────────
    # Single readiness predicate: a blocked/interrupted run is never "READY TO
    # BUILD", even when no explicit blocker was collected.
    fields: list[tuple[str, str]] = []
    if _phase_a_buildable(result_status, blockers):
        if ready_items:
            fields.append(("ready", "\n".join(f"✓ {item}" for item in ready_items)))
        harness_cmd = f"echelon delivery run {newest_spec_id}" if newest_spec_id else "echelon delivery run <spec-id>"
        fields.append(("next", harness_cmd))
        if warnings:
            fields.append(("warnings", "\n".join(f"⚠ {w}" for w in warnings)))
        subtitle = "READY TO BUILD"
    else:
        if blockers:
            fields.append(("blockers", "\n".join(f"{i}. {b}" for i, b in enumerate(blockers, 1))))
        if warnings:
            fields.append(("warnings", "\n".join(f"⚠ {w}" for w in warnings)))
        if ready_items:
            fields.append(("already done", ", ".join(ready_items)))
        if result_status == "blocked":
            subtitle = "RUN BLOCKED — resolve before building"
        elif blockers:
            subtitle = "PHASE A INCOMPLETE — continue authoring before build"
        else:
            subtitle = "RUN BLOCKED — resolve the block before building"

    _banner("NEXT STEP", fields, subtitle=subtitle)


def _run_artifact_dir(project_root: Path, run_dir: Path) -> Path:
    """Return the canonical artifact root for a run, with pre-WHAT fallback."""
    state_path = run_dir / "state.json"
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            spec_ref = str(state.get("spec_dir") or "").strip()
            if spec_ref:
                spec_dir = Path(spec_ref)
                if not spec_dir.is_absolute():
                    spec_dir = project_root / spec_dir
                if spec_dir.is_dir():
                    return spec_dir
        except (OSError, ValueError, TypeError):
            pass
    return run_dir / "staging"


def _print_staging_artifacts(
    project_root: Path,
    exclude_dir: Optional[Path] = None,
    run_status: str = "",
) -> None:
    """Print a compact manifest of artifacts from the most recent prior run.

    Skips squad-internal files (issues.md, assumption-review.md, *-endorsement.md)
    so the list reflects substantive domain artifacts the squad can build on.
    Once WHAT establishes ``state.spec_dir``, that directory is authoritative;
    staging is only the pre-WHAT fallback. Silent when no prior run has content, or when the run is done (the
    NEXT STEP section already surfaces readiness in that case).
    """
    if run_status == "done":
        return

    candidates = [
        (d, _run_artifact_dir(project_root, d))
        for d in _iter_run_dirs(project_root)
        if d != exclude_dir
    ]
    candidates = [(run_dir, artifact_dir) for run_dir, artifact_dir in candidates if artifact_dir.exists()]
    if not candidates:
        return

    run_dir, artifact_dir = candidates[0]

    _SKIP_NAMES = {"issues.md", "assumption-review.md", "escalation-request.md",
                   "user-clarifications.md"}
    _SKIP_SUFFIXES = ("-halt-endorsement.md", "-endorsement.md")

    names = sorted(
        f.stem for f in artifact_dir.glob("*.md")
        if f.name not in _SKIP_NAMES
        and not any(f.name.endswith(s) for s in _SKIP_SUFFIXES)
    )
    if not names:
        return

    # Two-column layout; strip .md already done via .stem
    col_w = 28
    pairs = [names[i:i + 2] for i in range(0, len(names), 2)]
    files_list = "\n".join("  ".join(n.ljust(col_w) for n in pair).rstrip() for pair in pairs)
    _banner(
        "PRIOR RUN ARTIFACTS",
        [("artifacts", files_list)],
        subtitle=f"{len(names)} files · {run_dir.name}",
    )


def _print_cost_summary(project_root: Path) -> None:
    """Print cumulative cost across all runs if cost data has been recorded.

    Reads cost_usd from each run's state.json. Silent when no run has cost data
    (i.e. all values are 0 — means tracking hasn't started yet or non-claude CLI).
    """
    import json as _json

    runs: list[tuple[str, float]] = []
    for run_dir in _iter_run_dirs(project_root):
        sf = run_dir / "state.json"
        if not sf.exists():
            continue
        try:
            state = _json.loads(sf.read_text())
            cost = float(state.get("cost_usd") or 0)
            if cost > 0:
                runs.append((run_dir.name, cost))
        except Exception:
            pass

    if not runs:
        return

    total = sum(c for _, c in runs)
    fields: list[tuple[str, str]] = [(name, f"${cost:.4f}") for name, cost in runs[-5:]]
    if len(runs) > 5:
        omitted = len(runs) - 5
        earlier = sum(c for _, c in runs[:-5])
        fields.append((f"… {omitted} earlier", f"${earlier:.4f}"))
    fields.append(("total", f"${total:.4f}"))
    _banner("COST", fields, subtitle=f"{len(runs)} runs tracked")


def _print_prior_knowledge(project_root: Path) -> None:
    """Print a brief summary of accumulated knowledge-base content at run start.

    Covers sage-decisions.yaml (calibration history + last resolution) and any
    other KB files present (patterns, pitfalls, calibration-profile, agent-scores).
    Silent when knowledge-base/ is absent or empty.
    """
    kb_dir = project_root / "knowledge-base"
    if not kb_dir.exists():
        return

    lines: list[str] = []

    # ── sage-decisions.yaml ─────────────────────────────────────────────────
    sage_path = kb_dir / "sage-decisions.yaml"
    if sage_path.exists():
        try:
            import yaml as _yaml
            data = _yaml.safe_load(sage_path.read_text(errors="replace")) or {}
            entries = data.get("entries", [])
            if entries:
                total = len(entries)
                overturned = sum(1 for e in entries if e.get("was_correct") is False)
                calibration = "well-calibrated" if overturned == 0 else f"{overturned} overturned"
                blocked_streak = sum(
                    1 for e in reversed(entries) if e.get("outcome") == "blocked"
                )
                # First substantive sentence of last resolution, capped at 110 chars
                last_res = (entries[-1].get("resolution") or "").replace("\n", " ").strip()
                dot = last_res.find(". ")
                # Skip trivial lead-ins like "Pending." or "Same as prior."
                if 0 < dot < 20:
                    tail = last_res[dot + 2:]
                    dot2 = tail.find(". ")
                    last_res = tail
                    dot = dot2
                snippet = last_res[:dot + 1] if 0 < dot < 110 else last_res[:110]
                if len(last_res) > len(snippet):
                    snippet = snippet.rstrip(".") + "…"

                lines.append(
                    f"SAGE decisions: {total} · {overturned} overturned ({calibration})"
                )
                if blocked_streak >= 2:
                    lines.append(
                        f"Blocker pattern: {blocked_streak} consecutive FAILs"
                        f" on same root cause — human input required"
                    )
                if snippet:
                    lines.append(f"Last resolution: {snippet}")
        except Exception:
            import re as _re
            size_kb = sage_path.stat().st_size // 1024
            try:
                raw = sage_path.read_text(errors="replace")
                # Entries are indented list items: "  - run_id: ..."
                entry_est = len(_re.findall(r"^\s+- run_id:", raw, _re.MULTILINE))
            except Exception:
                entry_est = 0
            note = f"~{entry_est} entries · {size_kb}KB" if entry_est else f"{size_kb}KB"
            lines.append(f"SAGE decisions: {note} (could not parse YAML)")

    # ── other KB files ──────────────────────────────────────────────────────
    _KB_FILES = [
        ("calibration-profile.yaml", "Calibration profile"),
        ("agent-scores.yaml",        "Agent scores"),
        ("patterns.yaml",            "Patterns"),
        ("pitfalls.yaml",            "Pitfalls"),
        ("estimates-log.yaml",       "Estimates log"),
    ]
    for fname, label in _KB_FILES:
        fpath = kb_dir / fname
        if not fpath.exists():
            continue
        try:
            import yaml as _yaml
            data = _yaml.safe_load(fpath.read_text(errors="replace")) or {}
            entries = data.get("entries", data if isinstance(data, list) else [])
            count = len(entries) if isinstance(entries, (list, dict)) else "?"
            lines.append(f"{label}: {count} entries")
        except Exception:
            lines.append(f"{label}: present")

    if not lines:
        return

    _banner(
        "PRIOR KNOWLEDGE",
        [("summary", "\n".join(lines))],
        subtitle=str(kb_dir.relative_to(project_root)),
    )


def _print_open_issues(project_root: Path, exclude_dir: Optional[Path] = None) -> None:
    """Print a formatted summary of open issues from the most recent prior run.

    Reads issues.md from the latest run's canonical artifact root (excluding the
    current run). Before WHAT establishes ``state.spec_dir``, staging is used.
    Shows CRITICAL issue titles and user-gated HIGH issues. Silent when nothing
    to show — no output if no issues.md exists or all issues are LOW/MEDIUM.
    """
    import re as _re

    # Find most recent run dir with issues.md, skipping the current run.
    candidates = [
        (d, _run_artifact_dir(project_root, d) / "issues.md")
        for d in _iter_run_dirs(project_root)
        if d != exclude_dir
    ]
    candidates = [(run_dir, issues_path) for run_dir, issues_path in candidates if issues_path.exists()]
    if not candidates:
        return

    run_dir, issues_path = candidates[0]
    issues_md = issues_path.read_text(errors="replace")

    # Extract severity counts from the Summary block
    counts: dict[str, int] = {}
    for sev in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
        m = _re.search(rf"\*\*{sev}:\*\*\s*(\d+)", issues_md)
        if m:
            counts[sev] = int(m.group(1))

    if not counts.get("CRITICAL", 0) and not counts.get("HIGH", 0):
        return

    # Extract issue entries: title, severity, responsible agent
    issue_blocks = _re.findall(
        r"### (ISS-\d+:[^\n]+)\n(.*?)(?=\n### |\Z)",
        issues_md,
        _re.DOTALL,
    )

    criticals: list[str] = []
    user_gated: list[str] = []

    for title, body in issue_blocks:
        sev_match = _re.search(r"\*\*Severity:\*\*\s*(\w+)", body)
        sev = sev_match.group(1).upper() if sev_match else ""
        is_user = bool(_re.search(r"(?i)responsible agent[^:]*:.*\buser\b", body))

        if sev == "CRITICAL":
            # Strip "ISS-NNN: " prefix for display, keep it compact
            short = _re.sub(r"^ISS-\d+:\s*", "", title).strip()
            criticals.append(short)
        elif sev == "HIGH" and is_user:
            short = _re.sub(r"^ISS-\d+:\s*", "", title).strip()
            user_gated.append(short)

    # Build banner fields
    run_label = run_dir.name
    fields: list[tuple[str, str]] = []

    if criticals:
        tree = "\n".join(
            f"{'└' if i == len(criticals) - 1 else '├'} {t}"
            for i, t in enumerate(criticals)
        )
        fields.append((f"CRITICAL ({counts.get('CRITICAL', len(criticals))})", tree))

    if user_gated:
        tree = "\n".join(
            f"{'└' if i == len(user_gated) - 1 else '├'} {t}"
            for i, t in enumerate(user_gated)
        )
        fields.append((f"HIGH — needs your input ({len(user_gated)})", tree))

    other_high = counts.get("HIGH", 0) - len(user_gated)
    if other_high > 0:
        fields.append(("HIGH — squad-solvable", str(other_high)))

    fields.append(("details", str(issues_path)))
    if user_gated:
        fields.append(("answer", "echelon spec resume \"<your answers>\""))

    _banner("OPEN ISSUES", fields, subtitle=f"from {run_label}")


def _select_squad_dir(
    project_root: Path,
    user_message: str,
    reset: bool = False,
    *,
    manual_recovery: bool = False,
    configured_default_branch: str = "",
    dirty_action: str = "refuse",
    confirm_discard: bool = False,
) -> tuple[Path, bool]:
    """Return (squad_dir, is_fresh_start).

    is_fresh_start=True  → caller should initialize state (new run).
    is_fresh_start=False → caller should resume (existing run dir, same task).
    """
    import json as _json
    from harness.paths import make_spec_run_id

    def start_fresh() -> tuple[Path, bool]:
        from echelon.phase_a_start import PhaseAStartError, start_phase_a_spec

        run_id = make_spec_run_id()
        runs_gitignore = project_root / "runs" / ".gitignore"
        runs_gitignore.parent.mkdir(exist_ok=True)
        _ensure_runs_gitignore(runs_gitignore)
        try:
            outcome = start_phase_a_spec(
                project_root,
                run_id,
                user_message,
                configured_default_branch=configured_default_branch,
                dirty_action=dirty_action,
                confirm_discard=confirm_discard,
            )
        except PhaseAStartError as exc:
            print(f"✗ echelon spec run: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        return outcome.run_dir, True

    def choose_active_run() -> bool:
        """Return whether an interactive user chose to continue the active run."""
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            return False

        active_message = str(state.get("user_message") or "").strip()
        branch = str(state.get("feature_branch") or "current branch").strip()
        answer = input(
            f"Active spec {existing_dir.name} on {branch}.\n"
            f"  Current task: {active_message or '(not recorded)'}\n"
            "Continue current spec/branch or start a new spec? [c/N] "
        ).strip().lower()
        return answer in {"c", "continue"}

    if reset:
        return start_fresh()

    existing_dir = _find_current_run_dir(project_root)
    if not existing_dir:
        return start_fresh()

    try:
        state = _json.loads((existing_dir / "state.json").read_text())
    except Exception:
        return start_fresh()

    if state.get("status") == "preparing" and user_message == state.get("user_message"):
        return existing_dir, True

    status = state.get("status")
    recovery = state.get("issue_resolution_recovery")
    manual_recovery = manual_recovery or (
        isinstance(recovery, dict) and recovery.get("status") != "consumed"
    )
    if manual_recovery and status == "blocked":
        return existing_dir, False
    if status not in ("running", "in_progress"):
        return start_fresh()

    # Different task → new run dir (preserves old one, doesn't overwrite)
    if user_message and user_message != state.get("user_message", ""):
        if choose_active_run():
            print(
                f"[squad] continuing {existing_dir.name}; keeping its current task",
                flush=True,
            )
            return existing_dir, False
        return start_fresh()

    # Same task, resumable status → resume in existing dir
    return existing_dir, False


def _runtime_bundle_missing_paths(project_root: Path) -> list[str]:
    """Return the deployed runtime contracts absent from a workspace."""
    required = (
        (
            project_root / ".echelon" / "runtime" / "workflow" / "definition.yaml",
            ".echelon/runtime/workflow/definition.yaml",
        ),
        (project_root / ".echelon" / "prosaic" / "commands", ".echelon/prosaic/commands"),
        (project_root / ".echelon" / "prosaic" / "subagents", ".echelon/prosaic/subagents"),
    )
    return [display_path for path, display_path in required if not path.exists()]


def _print_runtime_bundle_status(project_root: Path) -> None:
    """Show whether the workspace has the deployed Echelon runtime contracts."""
    missing = _runtime_bundle_missing_paths(project_root)
    fields = [
        ("prose", ".echelon/prosaic"),
        ("runtime", ".echelon/runtime"),
        (
            "status",
            "ready"
            if not missing
            else "incomplete; run echelon workspace migrate-to-prosaic",
        ),
    ]
    if missing:
        fields.append(("missing", ", ".join(missing)))
    _banner(
        "ECHELON RUNTIME",
        fields,
    )


@dataclass(frozen=True)
class ProjectConfigCompatibilityIssue:
    title: str
    path: str
    current: str
    expected: str
    config_file: Path


def _project_echelon_config(project_root: Path) -> Path:
    return project_root / ".echelon" / "config.yml"


def _project_config_compatibility_issues(
    project_root: Path,
) -> list[ProjectConfigCompatibilityIssue]:
    """Detect project config values incompatible with current deterministic flows."""
    cfg_file = _project_echelon_config(project_root)
    if not cfg_file.exists():
        return []

    try:
        import yaml
        raw = yaml.safe_load(cfg_file.read_text(encoding="utf-8")) or {}
    except Exception:
        return []
    if not isinstance(raw, dict):
        return []

    lexicon_gate = raw.get("lexicon_gate") or {}
    if not isinstance(lexicon_gate, dict) or not lexicon_gate.get("enabled", False):
        return []
    artifacts = lexicon_gate.get("artifacts") or {}
    if not isinstance(artifacts, dict):
        return []
    spec_artifact = artifacts.get("spec") or {}
    tasks_artifact = artifacts.get("tasks") or {}
    if not isinstance(spec_artifact, dict) or not isinstance(tasks_artifact, dict):
        return []
    if not tasks_artifact.get("enabled", False):
        return []

    expected = str(spec_artifact.get("path") or "requirements.lexicon.md").strip()
    current = str(tasks_artifact.get("spec_ref") or expected).strip()
    if current == expected:
        return []
    return [
        ProjectConfigCompatibilityIssue(
            title="Stale Lexicon tasks spec_ref",
            path=LEXICON_TASK_SPEC_REF_PATH,
            current=current,
            expected=expected,
            config_file=cfg_file,
        )
    ]


def _print_project_config_compatibility_warning(project_root: Path) -> None:
    issues = _project_config_compatibility_issues(project_root)
    if not issues:
        return

    fields: list[tuple[str, str]] = []
    for issue in issues:
        fields.extend(
            [
                ("problem", issue.title),
                ("config", _repo_relative_or_absolute(issue.config_file, project_root)),
                ("key", issue.path),
                ("current", issue.current or "(empty)"),
                ("expected", issue.expected),
                ("fix", f"set {issue.path}: {issue.expected}"),
            ]
        )
    _banner(
        "CONFIG COMPATIBILITY",
        fields,
        subtitle="Project config is stale for the current Echelon workflow",
    )


def _enforce_project_config_compatibility(project_root: Path) -> None:
    issues = _project_config_compatibility_issues(project_root)
    if not issues:
        return

    issue = issues[0]
    _banner(
        "CONFIG BLOCKED",
        [
            ("problem", issue.title),
            ("config", _repo_relative_or_absolute(issue.config_file, project_root)),
            ("key", issue.path),
            ("current", issue.current or "(empty)"),
            ("expected", issue.expected),
            ("why", "Tasks Lexicon validation must read the derived requirements artifact."),
            ("fix", f"edit config and set {issue.path}: {issue.expected}"),
            ("then", "echelon spec run \"<task>\" or echelon spec continue"),
        ],
        subtitle="Refusing to dispatch agents with stale Lexicon task config",
        file=sys.stderr,
    )
    sys.exit(1)


def _phase_run_requires_task_lexicon_config(phase_id: str) -> bool:
    """Return True when a manual phase run can use task Lexicon config.

    The stale spec_ref guard protects ORCHESTRATOR task generation and PLAN2
    repair. It must not block unrelated targeted repairs such as CHIEF
    constitution replay.
    """
    return phase_id in {
        "phase3-plan",
        "phase3-tasks-lexicon",
        "phase3-consensus",
        "phase3-consensus-tasks-lexicon",
    }


_AUTONOMY_MODES = {"semi", "banzai", "guided"}


def _consume_mode_arg(
    args: list[str],
    index: int,
    *,
    command_name: str,
) -> tuple[str | None, int]:
    token = args[index]
    if token == "--mode":
        if index + 1 >= len(args):
            print(
                f"✗ {command_name}: --mode requires one of: semi, banzai, guided",
                file=sys.stderr,
            )
            sys.exit(1)
        mode = args[index + 1]
        next_index = index + 2
    elif token.startswith("--mode="):
        mode = token.split("=", 1)[1]
        next_index = index + 1
    else:
        return None, index

    if mode not in _AUTONOMY_MODES:
        print(
            f"✗ {command_name}: invalid mode {mode!r}; expected semi, banzai, or guided",
            file=sys.stderr,
        )
        sys.exit(1)
    return mode, next_index


def _resolve_spec_run_implementation_targets(
    project_root: Path,
    requested_targets: list[str],
    *,
    allow_missing: bool,
) -> list[str]:
    """Resolve Phase A implementation targets before any agent dispatch."""
    from echelon.workspace_model import discover_workspace

    root = project_root.resolve()
    manifest = discover_workspace(root)
    if not requested_targets:
        if len(manifest.sources) > 1:
            print(
                "✗ echelon spec run: multiple source repositories were discovered.\n"
                "  Declare every implementation destination with repeatable "
                "--target <source-id-or-path> options.",
                file=sys.stderr,
            )
            raise SystemExit(1)
        if len(manifest.sources) == 1:
            return [manifest.sources[0].path]
        print(
            "✗ echelon spec run: no implementation target was resolved.\n"
            "  Declare a source root or pass --target <source-id-or-path>.\n"
            "  The orchestration workspace is not an implementation target.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    resolved: list[str] = []
    by_id = {source.id: source.path for source in manifest.sources}
    by_path = {source.path: source.path for source in manifest.sources}
    for raw_target in requested_targets:
        raw = raw_target.strip()
        if not raw:
            continue
        path = Path(raw).expanduser()
        if path.is_absolute():
            try:
                normalized = path.resolve().relative_to(root).as_posix()
            except ValueError:
                normalized = path.resolve().as_posix()
        else:
            normalized = path.as_posix().rstrip("/") or "."
        target = by_id.get(raw) or by_path.get(normalized) or normalized
        target_path = Path(target).expanduser()
        if not target_path.is_absolute():
            target_path = root if target == "." else root / target
        if not allow_missing and not target_path.is_dir():
            print(
                f"✗ echelon spec run: implementation target not found: {raw}\n"
                f"  Use --init to create it, or choose a configured workspace source.",
                file=sys.stderr,
            )
            raise SystemExit(1)
        if target not in resolved:
            resolved.append(target)
    if not resolved:
        print("✗ echelon spec run: --target requires a source id or path", file=sys.stderr)
        raise SystemExit(1)
    return resolved


def _fresh_stack_contract_or_exit(project_root: Path) -> dict[str, object]:
    """Freeze selected-stack guidance before a fresh controller run starts."""
    from harness.stack_contract import StackContractError, build_stack_contract

    try:
        definitions = _load_stack_definitions_for_project(project_root)
        selection = get_stack_selection(project_root, definitions)
        return build_stack_contract(selection, definitions)
    except (StackError, StackContractError, StackSelectionError) as exc:
        print(f"✗ echelon spec run: selected stack contract is invalid: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


def _cmd_run(
    args: list[str],
    project_root: Path,
    ext_dir: Path,
) -> None:
    """Drive the pre-code squad run via deterministic Python harness."""
    from harness.config import load_config
    from harness.squad import SquadController
    from harness.squad_provider import SquadCliProvider
    from harness.squad_state import SquadStateStore
    from echelon.spec_authoring import (
        SpecAuthoringModeError,
        resolve_spec_authoring_mode,
    )

    _enforce_project_config_compatibility(project_root)
    _workspace_git_preflight(project_root, command_name="echelon spec run")

    # Parse optional flags
    mode = "semi"
    reset = False
    perfectionist_requested = False
    next_phase = ""
    implementation_targets = [
        value.strip()
        for value in os.environ.get("ECHELON_IMPLEMENTATION_TARGETS", "").split(",")
        if value.strip()
    ]
    product_input_values: list[str] = []
    re_sources: list[str] = []
    init_target = False
    ignore_re = False
    dirty_action = "refuse"
    confirm_discard = False
    message_parts: list[str] = []
    i = 0
    while i < len(args):
        parsed_mode, next_i = _consume_mode_arg(args, i, command_name="echelon spec run")
        if parsed_mode is not None:
            mode = parsed_mode
            i = next_i
        elif args[i] == "--message" and i + 1 < len(args):
            message_parts.append(args[i + 1])
            i += 2
        elif args[i] == "--reset":
            reset = True
            i += 1
        elif args[i] == "--perfectionist":
            perfectionist_requested = True
            i += 1
        elif args[i] == "--init":
            init_target = True
            i += 1
        elif args[i] == "--next-phase" and i + 1 < len(args):
            next_phase = args[i + 1]
            i += 2
        elif args[i] == "--target":
            if i + 1 >= len(args):
                print(
                    "✗ echelon spec run: --target requires a source id or path",
                    file=sys.stderr,
                )
                sys.exit(1)
            implementation_targets.append(args[i + 1].strip())
            i += 2
        elif args[i].startswith("--target="):
            implementation_targets.append(args[i].split("=", 1)[1].strip())
            i += 1
        elif args[i] == "--re-source":
            if i + 1 >= len(args):
                print(
                    "✗ echelon spec run: --re-source requires a published source id or re/sources path",
                    file=sys.stderr,
                )
                sys.exit(1)
            re_sources.append(args[i + 1].strip())
            i += 2
        elif args[i].startswith("--re-source="):
            re_sources.append(args[i].split("=", 1)[1].strip())
            i += 1
        elif args[i] == "--input":
            if i + 1 >= len(args):
                print("✗ echelon spec run: --input requires role:path", file=sys.stderr)
                sys.exit(1)
            product_input_values.append(args[i + 1].strip())
            i += 2
        elif args[i].startswith("--input="):
            product_input_values.append(args[i].split("=", 1)[1].strip())
            i += 1
        elif args[i] == "--ignore-re":
            ignore_re = True
            i += 1
        elif args[i] == "--stash":
            if dirty_action != "refuse":
                print("✗ echelon spec run: choose only --stash or --discard", file=sys.stderr)
                raise SystemExit(2)
            dirty_action = "stash"
            i += 1
        elif args[i] == "--discard":
            if dirty_action != "refuse":
                print("✗ echelon spec run: choose only --stash or --discard", file=sys.stderr)
                raise SystemExit(2)
            dirty_action = "discard"
            i += 1
        elif args[i] == "--confirm":
            confirm_discard = True
            i += 1
        elif args[i] in {"--re-policy", "--re-max-inner"}:
            moved = args[i]
            print(
                f"✗ echelon spec run: {moved} moved to 'echelon re run'.\n"
                "  Run reverse engineering explicitly, then start the spec run.",
                file=sys.stderr,
            )
            raise SystemExit(2)
        elif args[i].startswith("--re-policy=") or args[i].startswith("--re-max-inner="):
            moved = args[i].split("=", 1)[0]
            print(
                f"✗ echelon spec run: {moved} moved to 'echelon re run'.\n"
                "  Run reverse engineering explicitly, then start the spec run.",
                file=sys.stderr,
            )
            raise SystemExit(2)
        elif args[i].startswith("--"):
            option = args[i].split("=", 1)[0]
            replacement = " use --target <source-id-or-path>." if option == "--source" else ""
            print(
                f"✗ echelon spec run: unknown option {option!r}.{replacement}",
                file=sys.stderr,
            )
            raise SystemExit(2)
        else:
            message_parts.append(args[i])
            i += 1
    message = " ".join(message_parts)
    if init_target and not implementation_targets:
        print(
            "✗ echelon spec run: --init requires --target <source id or path>",
            file=sys.stderr,
        )
        sys.exit(1)
    implementation_targets = _resolve_spec_run_implementation_targets(
        project_root,
        implementation_targets,
        allow_missing=init_target,
    )
    prev_dir = _find_current_run_dir(project_root)
    active_versioned_decision = False
    if prev_dir is not None:
        try:
            previous_state = json.loads(
                (prev_dir / "state.json").read_text(encoding="utf-8")
            )
            previous_decision = (
                previous_state.get("blocked_decision")
                if isinstance(previous_state, dict)
                else None
            )
            same_task = (
                isinstance(previous_state, dict)
                and message == previous_state.get("user_message", "")
            )
            candidate_is_active = (
                not reset
                and isinstance(previous_decision, dict)
                and previous_decision.get("schema_version") in {2, 3}
                and previous_decision.get("status") != "resolved"
                and same_task
            )
            if candidate_is_active:
                active_versioned_decision = (
                    _active_versioned_decision(previous_state) is not None
                )
        except (RecoveryInstructionError, ValueError, TypeError) as exc:
            print(f"✗ Invalid persisted decision: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        except OSError:
            pass
    _workspace_git_preflight_for_squad_run(
        project_root,
        command_name=_command_display("echelon spec run", args),
        user_message=message,
        reset=reset,
        manual_recovery=bool(next_phase) or active_versioned_decision,
    )

    config = load_config(project_root, squad_only=True)
    squad_dir, is_fresh = _select_squad_dir(
        project_root,
        message,
        reset=reset,
        manual_recovery=bool(next_phase) or active_versioned_decision,
        configured_default_branch=str(getattr(config, "target_default_branch", "") or ""),
        dirty_action=dirty_action,
        confirm_discard=confirm_discard,
    )
    if reset:
        print("[squad] state reset — starting fresh", flush=True)
    elif is_fresh and prev_dir is not None and prev_dir != squad_dir:
        print(
            f"[squad] new task — starting fresh in {squad_dir.name} "
            f"(previous run preserved at {prev_dir.name})",
            flush=True,
        )

    if init_target:
        from echelon.workspace_sources import ensure_source_config_entry
        added_sources: list[str] = []
        for implementation_target in implementation_targets:
            init_messages = _prepare_spec_target_repo(
                project_root,
                squad_dir,
                implementation_target,
            )
            source_added = ensure_source_config_entry(project_root, implementation_target)
            for init_message in init_messages:
                print(init_message)
            if source_added:
                added_sources.append(implementation_target)
        if added_sources:
            _commit_initialized_workspace_sources(
                project_root,
                run_id=squad_dir.name,
                retry_command=_command_display("echelon spec run", args),
            )
            for implementation_target in added_sources:
                print(f"Added workspace source: {implementation_target}")

    state_store = SquadStateStore(squad_dir)
    product_inputs = None
    existing_state = state_store.load()
    try:
        spec_authoring_mode = resolve_spec_authoring_mode(
            existing_state,
            is_fresh=is_fresh,
            perfectionist_requested=perfectionist_requested,
        )
    except SpecAuthoringModeError as exc:
        print(f"✗ echelon spec run: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    if existing_state.get("spec_authoring_mode") != spec_authoring_mode:
        existing_state["spec_authoring_mode"] = spec_authoring_mode
        state_store.save(existing_state)
    run_message = message
    if not is_fresh:
        existing_message = str(existing_state.get("user_message") or "").strip()
        if existing_message:
            run_message = existing_message
    _register_spec_summary_run(
        project_root,
        squad_dir,
        mode=mode,
        message=run_message,
        implementation_targets=implementation_targets,
    )
    existing_inputs = existing_state.get("product_inputs") if existing_state else None
    if existing_inputs and not reset:
        declared_before = existing_inputs.get("declarations") if isinstance(existing_inputs, dict) else None
        declared_now: list[dict[str, str]] = []
        if product_input_values:
            from echelon.product_inputs import ProductInputError, parse_input_declaration
            try:
                declared_now = [
                    {"role": value.role, "location": value.location}
                    for value in (parse_input_declaration(raw) for raw in product_input_values)
                ]
            except ProductInputError as exc:
                print(f"✗ echelon spec run: {exc}", file=sys.stderr)
                raise SystemExit(1) from exc
        if declared_now and declared_now != declared_before:
            print(
                "✗ echelon spec run: product inputs are immutable for an active run. "
                "Start a new run with --reset to change --input declarations.",
                file=sys.stderr,
            )
            raise SystemExit(1)
    elif product_input_values:
        from echelon.product_inputs import ProductInputError, parse_input_declaration, resolve_product_inputs
        try:
            product_inputs = resolve_product_inputs(
                project_root,
                squad_dir,
                [parse_input_declaration(raw) for raw in product_input_values],
            )
        except ProductInputError as exc:
            print(f"✗ echelon spec run: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc

    stack_contract: dict[str, object] | None = None
    if is_fresh:
        stack_contract = _fresh_stack_contract_or_exit(project_root)
    elif not isinstance(existing_state.get("stack_contract"), dict):
        # Runs created before stack contracts existed have no immutable stack
        # authority to preserve. Freeze the current valid selection once and
        # make the migration visible; all later resumes use state.json only.
        stack_contract = _fresh_stack_contract_or_exit(project_root)
        existing_state["stack_contract"] = stack_contract
        state_store.save(existing_state)
        print("[squad] captured selected stack contract for legacy run", flush=True)
    provider = SquadCliProvider(config)
    from harness.phase_graph import load_workspace_phase_graph
    graph, ext_dir = load_workspace_phase_graph(project_root)
    # token_budget_k lives under analysis: in echelon-config.yml.
    # Use get_full_resolved_config so the 4-level cascade (ConfigManager →
    # echelon-config.yml → local-config.yml → env vars) is respected.
    from harness.config import get_full_resolved_config
    token_budget = 0
    max_iterations = 5  # matches analysis.max_iterations default in config-template.yml
    try:
        _full = get_full_resolved_config(project_root)
        _analysis = _full.get("analysis") or {}
        _k = int(_analysis.get("token_budget_k") or 0)
        token_budget = _k * 1000 if _k else 0
        max_iterations = int(_analysis.get("max_iterations") or 5)
    except Exception:
        pass

    controller = SquadController(
        provider=provider,
        state_store=state_store,
        phase_graph=graph,
        ext_dir=ext_dir,
        project_root=project_root,
        token_budget=token_budget,
        max_iterations=max_iterations,
        squad_dir=squad_dir,
        ignore_re=ignore_re,
        implementation_targets=implementation_targets,
        re_sources=re_sources,
        product_inputs=product_inputs,
        stack_contract=stack_contract,
    )

    _print_cost_summary(project_root)
    _print_prior_knowledge(project_root)
    _print_staging_artifacts(project_root, exclude_dir=squad_dir)
    _print_open_issues(project_root, exclude_dir=squad_dir)

    _state = state_store.load()
    run_id = (_state.get("run_id") if _state else None) or squad_dir.name
    _banner("SQUAD RUN", [
        ("Run ID", run_id),
        ("Mode", mode),
        ("Spec authoring", spec_authoring_mode),
        ("Task", (run_message[:80] + "…") if len(run_message) > 80 else run_message),
        ("Dir", str(squad_dir.name)),
        ("Implementation targets", ", ".join(implementation_targets)),
        ("Published RE sources", ", ".join(re_sources) if re_sources else "auto"),
        ("Published RE", "ignored" if ignore_re else "latest"),
    ])

    result = controller.run(user_message=run_message, mode=mode, next_phase_override=next_phase)

    _print_squad_summary(
        project_root,
        squad_dir,
        result,
        mode=mode,
        message=run_message,
        implementation_targets=implementation_targets,
        command=_SPEC_SUMMARY_COMMAND.get(),
    )
    if result.status != "done":
        sys.exit(1)


def _repo_relative_or_absolute(path: Path, project_root: Path) -> str:
    try:
        return str(path.relative_to(project_root))
    except ValueError:
        return str(path)


def _spec_id_from_ref(ref: str) -> str:
    value = (ref or "").strip()
    if not value:
        return ""
    parts = Path(value).parts
    if "specs" in parts:
        idx = parts.index("specs")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    name = Path(value).name
    return name if name and name != "specs" else ""


def _single_project_spec_dir(project_root: Path) -> Path | None:
    specs_root = project_root / "specs"
    if not specs_root.exists():
        return None
    specs = sorted(d for d in specs_root.iterdir() if d.is_dir())
    return specs[0] if len(specs) == 1 else None


def _copy_missing_tree(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    dst.mkdir(parents=True, exist_ok=True)
    for child in src.iterdir():
        target = dst / child.name
        if target.exists():
            continue
        if child.is_dir():
            shutil.copytree(child, target)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(child, target)


def _ensure_active_continue_spec_context(
    project_root: Path,
    run_dir: Path,
    state: dict,
    *,
    sync_missing: bool,
) -> tuple[dict, Path | None]:
    """Resolve the active run-local spec dir for squad continue.

    Squad phases operate from the active run directory. The published
    project-root specs/<id> directory remains the build-harness target and is
    mirrored into the run-local copy only for missing files.
    """
    # ``specify_feature_directory`` is the original spec-kit allocation.  It
    # carries the full ``NNN-slug`` name and is therefore more specific than a
    # legacy ``spec_id: NNN`` / ``specs/NNN`` alias created by an interrupted
    # run.  Prefer it whenever it still resolves to a directory; otherwise a
    # resume can fork a shadow ``specs/NNN`` artifact tree and validate the
    # wrong copy.
    specified_ref = str(state.get("specify_feature_directory") or "").strip()
    specified_dir: Path | None = None
    if specified_ref:
        candidate = Path(specified_ref)
        if not candidate.is_absolute():
            candidate = project_root / candidate
        if candidate.is_dir():
            specified_dir = candidate

    spec_id = specified_dir.name if specified_dir is not None else str(state.get("spec_id") or "").strip()
    spec_ref = str(state.get("spec_dir") or "").strip()
    published_ref = str(state.get("published_spec_dir") or "").strip()

    spec_id = spec_id or _spec_id_from_ref(spec_ref) or _spec_id_from_ref(published_ref)
    if not spec_id:
        only_spec = _single_project_spec_dir(project_root)
        if only_spec is None:
            return state, None
        spec_id = only_spec.name

    active_spec_dir = run_dir / "specs" / spec_id
    is_project_published_spec = False
    if specified_dir is not None:
        try:
            specified_dir.relative_to(project_root / "specs")
            is_project_published_spec = True
        except ValueError:
            pass
    published_spec_dir = (
        specified_dir
        if is_project_published_spec and specified_dir is not None
        else project_root / "specs" / spec_id
    )

    source_dirs: list[Path] = []
    if published_spec_dir.exists():
        source_dirs.append(published_spec_dir)
    if spec_ref:
        candidate = Path(spec_ref)
        if not candidate.is_absolute():
            candidate = project_root / candidate
        if candidate.exists() and candidate != active_spec_dir and candidate not in source_dirs:
            source_dirs.append(candidate)

    if sync_missing:
        active_spec_dir.mkdir(parents=True, exist_ok=True)
        for source in source_dirs:
            _copy_missing_tree(source, active_spec_dir)

    updated = dict(state)
    updated["spec_id"] = spec_id
    updated["spec_dir"] = _repo_relative_or_absolute(active_spec_dir, project_root)
    if published_spec_dir.exists() or published_ref:
        updated["published_spec_dir"] = _repo_relative_or_absolute(published_spec_dir, project_root)
    return updated, active_spec_dir


def _active_continue_spec_dir(project_root: Path, current_state: dict, run_dir: Path | None) -> Path | None:
    if run_dir is None:
        only_spec = _single_project_spec_dir(project_root)
        return only_spec
    _, active_spec_dir = _ensure_active_continue_spec_context(
        project_root,
        run_dir,
        current_state,
        sync_missing=False,
    )
    return active_spec_dir


def _published_continue_spec_dir(project_root: Path, current_state: dict) -> Path | None:
    """Return the project-root spec dir for completed/build-ready squad output."""
    spec_id = str(current_state.get("spec_id") or "").strip()
    spec_ref = str(current_state.get("spec_dir") or "").strip()
    published_ref = str(current_state.get("published_spec_dir") or "").strip()
    spec_id = spec_id or _spec_id_from_ref(spec_ref) or _spec_id_from_ref(published_ref)

    candidates: list[Path] = []
    if spec_id:
        candidates.append(project_root / "specs" / spec_id)
    for ref in (published_ref, spec_ref):
        if not ref:
            continue
        candidate = Path(ref)
        if not candidate.is_absolute():
            candidate = project_root / candidate
        candidates.append(candidate)

    for candidate in candidates:
        if candidate.exists() and candidate.is_dir():
            return candidate
    return None


def _build_target_continue_spec_dir(project_root: Path, current_state: dict) -> Path | None:
    """Return the project-visible spec dir that harness/build commands resolve."""
    from harness.spec_frontmatter import find_spec_dir

    published_ref = str(current_state.get("published_spec_dir") or "").strip()
    if published_ref:
        candidate = Path(published_ref)
        return candidate if candidate.is_absolute() else project_root / candidate

    spec_id = str(current_state.get("spec_id") or "").strip()
    if not spec_id:
        spec_ref = str(current_state.get("spec_dir") or "").strip()
        spec_id = _spec_id_from_ref(spec_ref) or ""
    if not spec_id:
        return _single_project_spec_dir(project_root)

    existing = find_spec_dir(spec_id, project_root)
    if existing is not None:
        return existing
    exact = project_root / "specs" / spec_id
    if exact.exists():
        return exact
    return None


def _resolve_phase_target_spec_dir(
    project_root: Path,
    current_state: dict,
    run_dir: Path,
    spec_arg: str = "",
) -> Path | None:
    """Resolve the run-local spec dir for a manual phase replay.

    Manual replays are repairs to the active Phase A worktree.  They must never
    dispatch an agent against the project-visible published spec directory.
    """
    from harness.spec_frontmatter import find_spec_dir

    selected: Path | None = None
    value = spec_arg.strip()
    if value:
        candidate = Path(value)
        if candidate.exists() and candidate.is_dir():
            selected = candidate if candidate.is_absolute() else project_root / candidate
        else:
            selected = find_spec_dir(value, project_root)
    else:
        selected = _build_target_continue_spec_dir(project_root, current_state)
        if selected is None:
            selected = _single_project_spec_dir(project_root)

    spec_id = str(current_state.get("spec_id") or "").strip()
    if selected is not None:
        spec_id = selected.name
    if not spec_id:
        return None
    return run_dir / "specs" / spec_id


def _phase_state_updates_for_target(
    project_root: Path,
    current_state: dict,
    target_spec_dir: Path | None,
    *,
    materialize: bool = True,
) -> dict:
    """Build state fields that make phase context/output target the spec dir."""
    if target_spec_dir is None:
        return {}

    if materialize:
        target_spec_dir.mkdir(parents=True, exist_ok=True)

    source_refs = [
        str(current_state.get("phase_run_source_spec_dir") or "").strip(),
        str(current_state.get("spec_dir") or "").strip(),
        str(current_state.get("published_spec_dir") or "").strip(),
        f"specs/{target_spec_dir.name}",
    ]
    for source_ref in source_refs:
        if not source_ref:
            continue
        source = Path(source_ref)
        if not source.is_absolute():
            source = project_root / source
        if (
            materialize
            and source.exists()
            and source.is_dir()
            and source.resolve() != target_spec_dir.resolve()
        ):
            _copy_missing_tree(source, target_spec_dir)
            break

    published_ref = str(current_state.get("published_spec_dir") or "").strip()
    if not published_ref:
        published_ref = f"specs/{target_spec_dir.name}"
    target_ref = _repo_relative_or_absolute(target_spec_dir, project_root)

    updates: dict[str, str] = {
        "spec_id": target_spec_dir.name,
        "spec_dir": target_ref,
        "published_spec_dir": published_ref,
        "phase_run_source_spec_dir": target_ref,
    }
    return updates


@dataclass(frozen=True)
class _FailedAutomaticPhaseReplay:
    decision: Mapping[str, object]
    state_revision: int
    v2_automatic_eligible: bool
    spec_id: str
    spec_dir_ref: str
    spec_dir: Path


def _failed_automatic_phase_replay(
    state: Mapping[str, object],
    *,
    phase_id: str,
    spec_arg: str,
    project_root: Path,
    run_dir: Path,
    graph: object,
) -> _FailedAutomaticPhaseReplay | None:
    """Validate failed replay authority before resolving or materializing a target."""
    raw_decision = state.get("blocked_decision")
    if (
        not isinstance(raw_decision, Mapping)
        or raw_decision.get("schema_version") not in {2, 3}
    ):
        return None
    decision = _validated_versioned_decision(state)
    if decision is None or decision["status"] != "failed":
        return None
    source_phase = str(decision.get("source_phase") or "").strip()
    revision = state.get("state_revision")
    v2_eligible = _v2_automatic_decision_is_registered(
        decision,
        project_root=project_root,
        graph=graph,
    )
    eligible = (
        decision.get("automatic_eligible") is True
        if decision["schema_version"] == 3
        else v2_eligible
    )
    if decision["source_kind"] not in {
        "provider_escalation",
        "controller_safeguard",
    }:
        raise ValueError(
            "failed human-gate authority requires its ledger-derived confirmed rewind command"
        )
    if (
        decision["autonomy_mode"] != "banzai"
        or state.get("autonomy_mode") != "banzai"
        or state.get("status") != "blocked"
        or state.get("phase") != source_phase
        or phase_id != source_phase
        or not eligible
        or type(revision) is not int
        or revision < 0
    ):
        replay_command = _command_display(
            "echelon phase run",
            [source_phase],
        )
        raise ValueError(
            "failed automatic decision can only be retired by its exact "
            f"source replay: {replay_command}"
        )
    spec_id = str(state.get("spec_id") or "").strip()
    spec_dir_ref = str(state.get("spec_dir") or "").strip()
    if not spec_id or not spec_dir_ref:
        raise ValueError("failed decision replay has no exact active spec identity")
    spec_dir = Path(spec_dir_ref)
    if not spec_dir.is_absolute():
        spec_dir = project_root / spec_dir
    expected_run_spec_dir = run_dir / "specs" / spec_id
    if (
        not spec_dir.is_dir()
        or spec_dir.resolve() != expected_run_spec_dir.resolve()
        or spec_dir.name != spec_id
    ):
        raise ValueError(
            "failed decision replay is not bound to the active run-local spec"
        )
    selector = spec_arg.strip()
    if selector:
        candidate = Path(selector)
        path_selector = candidate.is_absolute() or len(candidate.parts) > 1
        if path_selector:
            if not candidate.is_absolute():
                candidate = project_root / candidate
            selector_matches = (
                candidate.is_dir()
                and candidate.resolve() == spec_dir.resolve()
            )
        else:
            selector_matches = selector == spec_id
        if not selector_matches:
            raise ValueError(
                f"failed decision replay is bound to active spec {spec_id!r}; "
                f"--spec {selector!r} selects a different target"
            )
    return _FailedAutomaticPhaseReplay(
        decision=decision,
        state_revision=revision,
        v2_automatic_eligible=v2_eligible,
        spec_id=spec_id,
        spec_dir_ref=spec_dir_ref,
        spec_dir=spec_dir,
    )


def _phase_context_resolution_rows(
    node: object,
    project_root: Path,
    state: dict,
    target_spec_dir: Path | None,
) -> list[tuple[str, str]]:
    """Return compact context-pack resolution rows for phase-run UX."""
    staging_ref = str(state.get("staging_dir") or "").strip()
    staging = Path(staging_ref) if staging_ref else None
    if staging is not None and not staging.is_absolute():
        staging = project_root / staging

    bases: list[Path] = []
    if target_spec_dir is not None:
        bases.append(target_spec_dir)
    source_ref = str(state.get("spec_dir") or "").strip()
    if source_ref:
        source = Path(source_ref)
        if not source.is_absolute():
            source = project_root / source
        if source not in bases:
            bases.append(source)
    if staging is not None:
        bases.append(staging)
    bases.append(project_root)

    rows: list[tuple[str, str]] = []
    for raw_item in getattr(node, "context_pack", []) or []:
        file_ref = str(raw_item).split(" ")[0].split("(")[0].rstrip()
        if not file_ref or file_ref.startswith("#"):
            continue
        resolved_ref = file_ref
        if staging is not None:
            resolved_ref = resolved_ref.replace("{staging_dir}", str(staging))
        if target_spec_dir is not None:
            resolved_ref = resolved_ref.replace("{spec_dir}", str(target_spec_dir))
        if resolved_ref.startswith("/"):
            candidates = [Path(resolved_ref)]
        else:
            candidates = [base / resolved_ref for base in bases]
        found = next((candidate for candidate in candidates if candidate.exists()), None)
        rows.append((file_ref, str(found) if found is not None else "missing"))
    return rows


def _phase_a_readiness_candidate_dirs(
    project_root: Path,
    current_state: dict,
    run_dir: Path | None,
    active_spec_dir: Path | None = None,
    published_spec_dir: Path | None = None,
) -> list[Path]:
    """Return deterministic spec-dir candidates for Phase A build inputs."""
    candidates: list[Path] = []

    def add(candidate: Path | None) -> None:
        if candidate is None:
            return
        path = candidate if candidate.is_absolute() else project_root / candidate
        if path not in candidates:
            candidates.append(path)

    add(active_spec_dir)
    add(published_spec_dir)

    # A complete spec-kit name is authoritative.  A legacy ``spec_id: 004``
    # must not cause a second ``specs/004`` artifact tree to be inspected once
    # state already identifies ``004-feature-name``.
    canonical_spec_id = ""
    for key in ("specify_feature_directory", "spec_dir", "published_spec_dir"):
        candidate_id = _spec_id_from_ref(str(current_state.get(key) or ""))
        if re.fullmatch(r"\d{3,4}-[A-Za-z0-9][A-Za-z0-9._-]*", candidate_id):
            canonical_spec_id = candidate_id
            break

    spec_id = canonical_spec_id or str(current_state.get("spec_id") or "").strip()
    if spec_id:
        add(project_root / "specs" / spec_id)
        if run_dir is not None:
            add(run_dir / "specs" / spec_id)

    for key in ("published_spec_dir", "spec_dir"):
        ref = str(current_state.get(key) or "").strip()
        if not ref:
            continue
        add(Path(ref))

    specified_ref = str(current_state.get("specify_feature_directory") or "").strip()
    if specified_ref:
        add(Path(specified_ref))

    staging_ref = str(current_state.get("staging_dir") or "").strip()
    if staging_ref:
        add(Path(staging_ref))
    elif run_dir is not None:
        add(run_dir / "staging")

    return candidates


def _next_continue_phase(project_root: Path) -> Optional[str]:
    """Return the phase ID to continue from, or None when build is ready.

    Runs the same blockers analysis as _print_next_steps and maps each blocker
    to the entry phase that resolves it. Returns the first (highest-priority)
    actionable phase, or None if everything is clear.
    """
    import json as _json
    import re as _re

    run_dir = _find_current_run_dir(project_root)
    current_state: dict = {}
    if run_dir and (run_dir / "state.json").exists():
        try:
            current_state = _json.loads((run_dir / "state.json").read_text())
            recommended = current_state.get("phase_recommendation")
            if (
                recommended
                and (
                    current_state.get("convergence_forced")
                    or current_state.get("convergence_detected")
                )
            ):
                completed = current_state.get("completed_phases")
                next_solution_phase = _next_incomplete_solution_phase(
                    completed if isinstance(completed, list) else []
                )
                if next_solution_phase is not None:
                    return next_solution_phase
                if _phase_a_ready_to_build(project_root, current_state):
                    return None
                if current_state.get("status") == "done":
                    return "phase4-document"
                return recommended
        except Exception:
            current_state = {}
    active_spec_dir = _active_continue_spec_dir(project_root, current_state, run_dir)
    completed = current_state.get("completed_phases")
    completed_phases = completed if isinstance(completed, list) else []
    next_solution_phase = _next_incomplete_solution_phase(completed_phases)
    if next_solution_phase is not None:
        return next_solution_phase

    if current_state.get("status") == "done" and _phase_a_ready_to_build(project_root, current_state):
        if _explicit_run_local_spec_needs_publication(
            project_root,
            current_state,
            active_spec_dir,
            _published_continue_spec_dir(project_root, current_state),
        ):
            return "phase4-document"
        return None

    action = _classify_run_recovery(current_state, project_root=project_root)
    if action.kind == "retry_phase":
        return action.phase
    if action.kind in {"human_resume", "safe_rewind"}:
        return None
    if action.kind == "manual_recovery" and current_state.get("status") == "interrupted":
        return None

    # 0. Constitution phase provenance first, artifact integrity second.
    if "phase1-constitution" not in completed_phases:
        return "phase1-constitution"
    from echelon.constitution import canonical_constitution_path

    const_path = canonical_constitution_path(project_root)
    if not const_path.exists():
        return "phase1-constitution"
    const_text = const_path.read_text(errors="replace")
    if _constitution_template_markers(const_text):
        return "phase1-constitution"

    # 1. WHY2 failures — fix spec first, so CARTOGRAPHER runs before HOW
    quality_gates_file: Optional[Path] = None
    if active_spec_dir is not None:
        qg = active_spec_dir / "quality-gates.md"
        if qg.exists():
            quality_gates_file = qg

    # Also check staging/ for mid-run blocked states (same as _print_next_steps)
    if quality_gates_file is None:
        if run_dir:
            try:
                state = _json.loads((run_dir / "state.json").read_text())
                staging_dir = Path(state.get("staging_dir") or str(run_dir / "staging"))
                staging_qg = staging_dir / "quality-gates.md"
                if staging_qg.exists():
                    quality_gates_file = staging_qg
            except Exception:
                pass

    if quality_gates_file:
        qg_text = quality_gates_file.read_text(errors="replace")
        verdict_m = _re.search(r"^##\s+Verdict:\s+(FAIL|BLOCKED)", qg_text, _re.MULTILINE)
        if verdict_m:
            return "phase1-what"  # top-level FAIL or BLOCKED → CARTOGRAPHER amendment
        gate_pattern = _re.compile(
            r"\|\s*(Overall|Structure|Testability|Semantic|Cognitive|"
            r"Readability|Behavioral|Depth)\s*\|[^|]+\|[^|]+\|\s*\*{0,2}FAIL\*{0,2}\s*\|([^|]*)\|"
        )
        for m in gate_pattern.finditer(qg_text):
            note = m.group(2).lower()
            if "borderline" not in note or "not borderline" in note:
                return "phase1-what"  # hard gate fail → CARTOGRAPHER amendment

    if _needs_phase3_specialists_recovery(active_spec_dir, completed_phases):
        return "phase3-specialists"

    # 2. HOW artifacts missing
    if active_spec_dir is not None:
        if not all((active_spec_dir / f).exists() for f in ("plan.md", "research.md", "data-model.md")):
            return "phase3-how"

    # 3. tasks.md missing
    if active_spec_dir is not None and not (active_spec_dir / "tasks.md").exists():
        return "phase3-plan"

    # WS1 invariant: a run with no resolvable spec directory has not produced the
    # build inputs (spec.md/tasks.md), so it is not ready. Route back to authoring
    # instead of falling through to a false "Build is ready — nothing left to do".
    if active_spec_dir is None:
        return "phase1-what"

    if current_state.get("status") == "done" and not _phase_a_ready_to_build(project_root, current_state):
        return "phase4-document"

    readiness = validate_phase_a_readiness(
        current_state,
        _phase_a_readiness_candidate_dirs(
            project_root,
            current_state,
            run_dir,
            active_spec_dir=active_spec_dir,
            published_spec_dir=_published_continue_spec_dir(project_root, current_state),
        ),
    )
    if not readiness.ready:
        if "spec.md" in readiness.missing:
            return "phase1-what"
        if any(name in readiness.missing for name in ("plan.md", "research.md", "data-model.md")):
            return "phase3-how"
        if "tasks.md" in readiness.missing:
            return "phase3-plan"
        return "phase1-what"

    return None  # build is ready


def _explicit_run_local_spec_needs_publication(
    project_root: Path,
    current_state: dict,
    active_spec_dir: Path | None,
    published_spec_dir: Path | None,
) -> bool:
    spec_ref = str(current_state.get("spec_dir") or "").strip()
    if not spec_ref or active_spec_dir is None or published_spec_dir is None:
        return False
    explicit_spec_dir = Path(spec_ref)
    if not explicit_spec_dir.is_absolute():
        explicit_spec_dir = project_root / explicit_spec_dir
    if not explicit_spec_dir.exists() or not published_spec_dir.exists():
        return False
    try:
        if explicit_spec_dir.resolve() == published_spec_dir.resolve():
            return False
    except OSError:
        return False
    try:
        explicit_spec_dir.relative_to(project_root / "runs")
    except ValueError:
        return False
    if not validate_phase_a_readiness(current_state, [explicit_spec_dir]).ready:
        return False
    return _spec_tree_differs(explicit_spec_dir, published_spec_dir)


def _spec_tree_differs(source: Path, destination: Path) -> bool:
    for path in source.rglob("*"):
        if not path.is_file():
            continue
        try:
            rel = path.relative_to(source)
        except ValueError:
            continue
        target = destination / rel
        if not target.exists() or not target.is_file():
            return True
        try:
            if path.read_bytes() != target.read_bytes():
                return True
        except OSError:
            return True
    return False


def _needs_phase3_specialists_recovery(
    active_spec_dir: Path | None,
    completed_phases: list,
) -> bool:
    """Detect old bad state that skipped specialists after tracker alignment."""

    if active_spec_dir is None:
        return False
    if "phase2-tracker-alignment" not in completed_phases:
        return False
    if "phase3-specialists" in completed_phases:
        return False
    if not (active_spec_dir / "intent-alignment-check.md").exists():
        return False
    return (active_spec_dir / "spec.md").exists()


def _next_incomplete_solution_phase(completed_phases: list) -> str | None:
    """Return the next required solution phase after tracker alignment.

    Older interrupted runs can have stale plan/task artifacts from a previous
    attempt. Once tracker alignment has completed, phase history is a stronger
    signal than file existence: missing recorded solution phases mean those
    artifacts have not been freshly regenerated for this run.
    """

    if "phase2-tracker-alignment" not in completed_phases:
        return None
    for phase_id in (
        "phase3-specialists",
        "phase3-how",
        "phase3-sentinel",
        "phase3-plan",
        "phase3-consensus",
    ):
        if phase_id not in completed_phases:
            return phase_id
    return None


def _phase_a_ready_to_build(project_root: Path, current_state: dict) -> bool:
    """Return True when Phase A already produced enough artifacts for harness run."""
    completed = current_state.get("completed_phases")
    completed_phases = completed if isinstance(completed, list) else []
    if current_state and "phase1-constitution" not in completed_phases:
        return False

    from echelon.constitution import canonical_constitution_path

    const_path = canonical_constitution_path(project_root)
    if not const_path.exists():
        return False
    if _constitution_template_markers(const_path.read_text(errors="replace")):
        return False

    published_spec_dir = _build_target_continue_spec_dir(project_root, current_state)
    if published_spec_dir is None:
        return False
    return validate_phase_a_readiness(
        current_state,
        [published_spec_dir],
    ).ready


# Fallback only. Normal status rendering derives the roadmap from
# workflow/definition.yaml so the UI cannot drift from the externalized graph.
_FALLBACK_ROADMAP_PHASES = [
    "init", "phase1-discover", "phase1-synthesizer", "phase1-modeler",
    "phase1-tracker", "phase1-why1", "phase1-constitution", "phase1-what",
    "phase1-understanding", "phase1-why2", "phase1-lexicon-derive",
    "phase1-lexicon",
    "checkpoint-assess", "phase2-decide",
    "phase2-strategic-overview", "phase2-tracker-alignment",
    "phase3-specialists", "phase3-how", "phase3-sentinel", "phase3-plan",
    "phase3-tasks-lexicon", "phase3-understanding", "phase3-consensus",
    "phase3-consensus-tasks-lexicon", "checkpoint-plan", "phase4-document", "done",
]


def _derive_roadmap_phases(workflow_path: Path) -> list[str]:
    """Return the primary forward squad path from workflow/definition.yaml."""
    try:
        import yaml as _yaml

        raw = _yaml.safe_load(workflow_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return list(_FALLBACK_ROADMAP_PHASES)

    phases_raw = raw.get("phases")
    if not isinstance(phases_raw, list):
        return list(_FALLBACK_ROADMAP_PHASES)
    phases = {
        str(phase.get("id")): phase
        for phase in phases_raw
        if isinstance(phase, dict) and phase.get("id")
    }

    def longest_path_to_done(current: str, seen: frozenset[str]) -> list[str]:
        if current == "done":
            return ["done"]
        if current not in phases or current in seen:
            return []

        next_seen = seen | {current}
        candidates: list[list[str]] = []
        transitions = phases[current].get("transitions") or []
        if isinstance(transitions, list):
            for transition in transitions:
                if not isinstance(transition, dict):
                    continue
                candidate = str(transition.get("to") or "")
                if (
                    not candidate
                    or candidate == current
                    or candidate in {"escalate", "terminal-blocked"}
                    or candidate in next_seen
                ):
                    continue
                suffix = longest_path_to_done(candidate, next_seen)
                if suffix:
                    candidates.append([current, *suffix])
        return max(candidates, key=len, default=[])

    path = longest_path_to_done("init", frozenset())
    if not path or path[-1] != "done":
        return list(_FALLBACK_ROADMAP_PHASES)
    return path


_ROADMAP_PHASES = _derive_roadmap_phases(
    Path(__file__).resolve().parents[2] / "runtime/workflow/definition.yaml"
)


def _print_roadmap(state: dict, workflow_path: Path | None = None) -> None:
    """Render the pipeline as a checkbox roadmap from the run's state.json:
    [✓] completed · [▶] in progress · [ ] pending. A (×N) marks a re-dispatched
    phase — the early signal of a non-converging loop."""
    roadmap_phases = (
        _derive_roadmap_phases(workflow_path)
        if workflow_path is not None
        else list(_ROADMAP_PHASES)
    )
    completed = state.get("completed_phases")
    completed = completed if isinstance(completed, list) else []
    completed_set = {str(phase) for phase in completed}
    counts = state.get("phase_dispatch_counts")
    counts = counts if isinstance(counts, dict) else {}
    current = state.get("current_phase") or state.get("phase")
    ld = state.get("last_dispatch")
    if not current and isinstance(ld, dict):
        current = ld.get("phase_id") or ld.get("phase")

    # A finished run marks every phase complete, even if `completed_phases`
    # never recorded the terminal nodes (phase4-document / done).
    run_done = state.get("status") == "done"

    fields: list[tuple[str, str]] = []
    done_n = 0
    for ph in roadmap_phases:
        if run_done:
            box = "[✓]"
            done_n += 1
            suffix = ""
        elif ph == current:
            box = "[▶]"
            done_n += 1 if ph in completed_set else 0
            suffix = "  ← in progress"
        elif ph in completed_set:
            box = "[✓]"
            done_n += 1
            suffix = ""
        else:
            box = "[ ]"
            suffix = ""
        n = counts.get(ph, 0)
        rerun = f"  (×{n} — re-dispatched)" if isinstance(n, int) and n > 1 else ""
        fields.append((box, f"{ph}{rerun}{suffix}"))

    pct = int(100 * done_n / len(roadmap_phases)) if roadmap_phases else 0
    _banner("ROADMAP", fields, subtitle=f"{done_n}/{len(roadmap_phases)} phases complete ({pct}%)")


def _print_active_spec_status(project_root: Path) -> None:
    """Render the deterministic Phase A authoring selection, when one exists."""
    from echelon.spec_lifecycle import (
        SpecLifecycleError,
        SpecRunNotFound,
        discover_spec_runs,
        resolve_active_spec_run,
    )
    from echelon.spec_switch import SpecSwitchError, validate_spec_checkpoint

    try:
        active = resolve_active_spec_run(project_root)
    except SpecRunNotFound:
        return

    fields: list[tuple[str, str]] = [
        ("Run", active.run_dir_name),
        ("Spec", active.spec_id),
        ("Branch", active.feature_branch),
    ]
    try:
        checkpoint = validate_spec_checkpoint(project_root, active)
        fields.append(("Checkpoint", f"{checkpoint.checkpoint_id} ({checkpoint.phase})"))
    except SpecSwitchError as exc:
        if str(exc).startswith("no checkpoint for run "):
            fields.append(("Checkpoint", "not yet created"))
        else:
            fields.append(("Checkpoint", f"unavailable: {exc}"))
    except Exception as exc:
        # Status is diagnostic: invalid Git/checkpoint state must not suppress
        # the rest of the operator's orientation report.
        fields.append(("Checkpoint", f"unavailable: {exc}"))

    try:
        state = json.loads((active.run_dir / "state.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        state = {}
    managed_stash = state.get("phase_a_stash") if isinstance(state, dict) else None
    if isinstance(managed_stash, dict):
        stash_commit = managed_stash.get("commit")
        if isinstance(stash_commit, str) and stash_commit.strip():
            fields.append(("Managed stash", stash_commit.strip()))
        else:
            fields.append(("Managed stash", "recorded but malformed"))

    try:
        others = [
            f"{run.spec_id} ({run.run_dir_name})"
            for run in discover_spec_runs(project_root)
            if run.run_dir != active.run_dir
        ]
    except SpecLifecycleError as exc:
        fields.append(("Switchable", f"unavailable: {exc}"))
    else:
        if others:
            fields.append(("Switchable", ", ".join(others)))

    _banner("ACTIVE SPEC", fields)


def _cmd_status(project_root: Path) -> None:
    """Print a concise orientation summary for the current project state.

    Shows: active run state (phase, status, task), staging artifacts,
    open issues, cost summary, prior knowledge, and what to do next.
    Designed to re-orient after a break without reading files manually.
    """
    import json as _json
    from datetime import datetime, timezone

    print(flush=True)
    _banner("ECHELON STATUS", [("Project", str(project_root))])
    _print_runtime_bundle_status(project_root)
    _print_project_config_compatibility_warning(project_root)
    _print_active_spec_status(project_root)

    # ── Run state ───────────────────────────────────────────────────────────
    run_dir = _find_current_run_dir(project_root)
    state: dict = {}
    if run_dir and (run_dir / "state.json").exists():
        try:
            state = _json.loads((run_dir / "state.json").read_text())
        except Exception:
            pass

    if not run_dir or not state:
        _banner("RUN STATE", [
            ("Status", "No active run found"),
            ("Next",   'echelon spec run "<task description>"'),
        ])
    else:
        run_status = state.get("status", "unknown")
        _ld = state.get("current_phase") or state.get("phase") or state.get("last_dispatch")
        if isinstance(_ld, dict):
            _ld = _ld.get("phase_id") or _ld.get("phase") or str(_ld)
        current_phase = _ld or "—"
        task_msg = state.get("user_message", "")
        run_id = run_dir.name

        started_at = state.get("started_at", "")
        elapsed = ""
        if started_at:
            try:
                t = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
                delta = datetime.now(timezone.utc) - t
                h, rem = divmod(int(delta.total_seconds()), 3600)
                m = rem // 60
                elapsed = f"{h}h {m}m ago" if h else f"{m}m ago"
            except Exception:
                pass

        status_icon = {"done": "✓", "blocked": "⚠", "running": "▶",
                       "in_progress": "▶", "interrupted": "✗"}.get(run_status, "·")

        fields: list[tuple[str, str]] = [
            ("Run",    run_id),
            ("Status", f"{status_icon}  {run_status}"),
            ("Phase",  current_phase),
        ]
        spec_ref = str(state.get("spec_dir") or state.get("spec_id") or "").strip()
        if spec_ref:
            fields.insert(1, ("Spec", spec_ref))
        if task_msg:
            snippet = task_msg[:72] + ("…" if len(task_msg) > 72 else "")
            fields.append(("Task", snippet))
        if elapsed:
            fields.append(("Started", elapsed))
        debt_facts = _current_quality_debt_cli_facts(state, project_root)
        if debt_facts is not None:
            fields.append(("Specification quality", "accepted with quality debt"))
            failed_gates = debt_facts["failed_gates"]
            if failed_gates:
                fields.append(("Residual gates", ", ".join(failed_gates)))
            qualitative_issues = debt_facts["qualitative_issues"]
            if qualitative_issues:
                fields.append(
                    ("Residual SAGE", ", ".join(qualitative_issues))
                )
            if debt_facts["resolved_by"]:
                fields.append(("Debt resolver", str(debt_facts["resolved_by"])))
            if debt_facts["artifact"]:
                fields.append(("Debt evidence", str(debt_facts["artifact"])))
        provider_limit_message = str(
            state.get("provider_limit_message") or ""
        ).strip()
        if provider_limit_message:
            fields.append(("Provider limit", provider_limit_message))
        action = _RunRecoveryAction("advance")
        if run_status in ("running", "in_progress"):
            fields.append(("Next", "echelon spec continue"))
        elif run_status == "blocked":
            action = _classify_run_recovery(state, project_root=project_root)
            if action.reason == "phase_dispatch_limit":
                guidance = _issue_resolution_guidance_recap(project_root, run_dir, state)
                if guidance:
                    fields.append(("Issue guidance", guidance))

        try:
            decision = _validated_versioned_decision(state)
        except (RecoveryInstructionError, ValueError):
            pass
        else:
            if decision is not None:
                fields.extend(_decision_audit_fields(decision))
                fields.extend(
                    _proportional_quality_decision_fields(state, decision)
                )

        _banner("RUN STATE", fields)

        # ── Pipeline roadmap ────────────────────────────────────────────────
        _print_roadmap(
            state,
            project_root / ".echelon" / "runtime" / "workflow" / "definition.yaml",
        )

    # ── Staging artifacts ───────────────────────────────────────────────────
    _print_staging_artifacts(project_root, run_status=state.get("status", ""))

    # ── Open issues ─────────────────────────────────────────────────────────
    _print_open_issues(project_root)

    # ── Prior knowledge ─────────────────────────────────────────────────────
    _print_prior_knowledge(project_root)

    # ── Cost summary ────────────────────────────────────────────────────────
    _print_cost_summary(project_root)

    # ── Build readiness (only meaningful when run is done/blocked) ──────────
    run_status = state.get("status", "")
    if run_status in ("done", "blocked", "interrupted") or not run_dir:
        _print_next_steps(project_root, run_status or "done")


def _format_squad_timestamp(timestamp: datetime) -> str:
    """Render a concise, local-time boundary timestamp for CLI transcripts."""
    return timestamp.astimezone().isoformat(timespec="seconds")


def _cmd_continue(
    args: list[str],
    project_root: Path,
    ext_dir: Path,
) -> None:
    """Run `spec continue` with explicit transcript timing boundaries."""
    started_at = datetime.now(timezone.utc)
    print(f"[squad] start: {_format_squad_timestamp(started_at)}", flush=True)
    try:
        _cmd_continue_impl(args, project_root=project_root, ext_dir=ext_dir)
    finally:
        ended_at = datetime.now(timezone.utc)
        print(f"[squad] end:   {_format_squad_timestamp(ended_at)}", flush=True)


def _cmd_continue_impl(
    args: list[str],
    project_root: Path,
    ext_dir: Path,
) -> None:
    """Resume or advance a squad run without requiring the user to know phase names.

    Behaviour by current run status:
    - running / in_progress: re-invokes echelon spec run with the same message (resumes)
    - blocked:               prints echelon spec resume guidance and exits
    - done / interrupted:    determines the next actionable phase from the build-
                             readiness analysis and starts a new run there, reusing
                             the original task message and mode from state.json
    - nothing found:         prints guidance to start a fresh echelon spec run
    """
    import json as _json

    # Optionally accept --mode override
    mode_override = ""
    i = 0
    while i < len(args):
        parsed_mode, next_i = _consume_mode_arg(args, i, command_name="echelon spec continue")
        if parsed_mode is not None:
            mode_override = parsed_mode
            i = next_i
        elif args[i] == "--re-max-inner" or args[i].startswith("--re-max-inner="):
            print(
                "✗ echelon spec continue: --re-max-inner moved to "
                "'echelon re continue'.",
                file=sys.stderr,
            )
            raise SystemExit(2)
        else:
            i += 1

    squad_dir = _find_current_run_dir(project_root)
    if not squad_dir or not (squad_dir / "state.json").exists():
        _workspace_git_preflight(
            project_root,
            command_name=_command_display("echelon spec continue", args),
        )
        print(
            "No prior run found in this project.\n"
            "Start a new run:  echelon spec run \"<task description>\"",
            flush=True,
        )
        return

    state = _json.loads((squad_dir / "state.json").read_text())
    if _supersede_quality_guard_decision(state):
        (squad_dir / "state.json").write_text(
            _json.dumps(state, indent=2, ensure_ascii=False)
        )
    user_message = state.get("user_message", "")
    mode = mode_override or state.get("autonomy_mode") or state.get("mode", "semi")
    _register_spec_summary_run(
        project_root,
        squad_dir,
        mode=mode,
        message=user_message,
        implementation_targets=state.get("implementation_targets") or (),
    )
    try:
        decision = _active_versioned_decision(state)
    except (RecoveryInstructionError, ValueError) as exc:
        print(f"✗ Invalid persisted decision: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    if decision is not None:
        # A sealed decision owns its autonomy policy.  A continue-time flag may
        # still apply to legacy runs, but cannot reclassify this decision.
        mode = str(decision["autonomy_mode"])
    status = state.get("status", "")
    cur_phase = state.get("phase", "")
    if not _workspace_git_present(project_root):
        if status in ("running", "in_progress"):
            _print_legacy_branchless_recovery_notice(
                _command_display("echelon spec continue", args)
            )
        else:
            _workspace_git_preflight(
                project_root,
                command_name=_command_display("echelon spec continue", args),
            )

    action = _classify_run_recovery(state, project_root=project_root)
    if (
        decision is not None
        and action.kind == "retry_phase"
        and _discard_retryable_failed_agent_block_decision(state)
    ):
        (squad_dir / "state.json").write_text(
            _json.dumps(state, indent=2, ensure_ascii=False)
        )
        decision = None
        print(
            "[squad] discarding obsolete generic-agent-block decision; retrying the phase.",
            flush=True,
        )
    if decision is not None:
        if action.kind == "resolve_decision":
            run_args = [user_message, "--mode", mode]
            targets = state.get("implementation_targets")
            if isinstance(targets, list):
                for target in targets:
                    target = str(target).strip()
                    if target:
                        run_args.extend(["--target", target])
            print(
                "[squad] continuing through the controller-owned decision resolver.",
                flush=True,
            )
            _cmd_run(run_args, project_root=project_root, ext_dir=ext_dir)
            return
        if action.kind == "human_resume":
            fields = [
                ("decision id", str(decision["id"])),
                ("decision needed", action.note or str(decision["question"])),
            ]
            fields.append(("options", _render_v2_decision_options(decision)))
            fields.append(("resume with", action.command))
            _note_spec_summary_next_printed()
            _banner("CHECKPOINT", fields, subtitle="Run paused. Human decision required.")
            return
        if action.kind == "manual_recovery":
            _note_spec_summary_next_printed()
            _banner(
                "CHECKPOINT",
                [
                    ("blocked by", action.reason),
                    ("next", action.command),
                    ("note", action.note),
                ],
                subtitle="Run paused. Manual recovery required.",
            )
            return

    prepared_state, _ = _ensure_active_continue_spec_context(
        project_root,
        squad_dir,
        state,
        sync_missing=True,
    )
    if prepared_state != state:
        state = prepared_state
        (squad_dir / "state.json").write_text(_json.dumps(state, indent=2, ensure_ascii=False))

    phase_labels = {
        "phase1-discover":     "SCOUT (retry failed discovery dispatch)",
        "phase1-constitution": "CHIEF → constitution protocol (creates constitution.md)",
        "phase1-what":         "CARTOGRAPHER (spec authoring or amendment)",
        "phase1-lexicon-derive": "LEXICON DERIVER (derived artifact repair)",
        "phase1-lexicon":      "Deterministic spec Lexicon gate",
        "phase1-understanding": "Deterministic Understanding gate",
        "phase3-how":          "ARCHITECT (architecture, data-model, contracts)",
        "phase3-plan":         "ORCHESTRATOR (task breakdown)",
        "phase3-consensus":    "Consensus gate (WHY3 + ASSESS2 + PLAN2)",
    }

    def resume_run_args() -> list[str]:
        """Reconstruct the original execution scope from controller-owned state."""
        targets = state.get("implementation_targets")
        stored_targets = (
            [str(value).strip() for value in targets if str(value).strip()]
            if isinstance(targets, list)
            else []
        )
        run_args = [user_message, "--mode", mode]
        for target in stored_targets:
            run_args.extend(["--target", target])
        return run_args

    def start_phase(next_phase: str, *, verb: str, clear_recovery: bool = False) -> None:
        nonlocal state
        state, _ = _ensure_active_continue_spec_context(
            project_root,
            squad_dir,
            state,
            sync_missing=True,
        )
        state["phase"] = next_phase
        state["status"] = "running"
        if clear_recovery:
            state["blocked_reason"] = None
            state["escalation_question"] = None
            state["escalation_options"] = None
            state.pop("recovery_instruction", None)
        (squad_dir / "state.json").write_text(_json.dumps(state, indent=2, ensure_ascii=False))
        label = phase_labels.get(next_phase, next_phase)
        print(
            f"[squad] {verb} {next_phase} — {label}\n"
            f"[squad] Task:  {(user_message[:80] + '…') if len(user_message) > 80 else user_message}\n"
            f"[squad] Mode:  {mode}",
            flush=True,
        )
        _cmd_run(resume_run_args(), project_root=project_root, ext_dir=ext_dir)

    issue_recovery = state.get("issue_resolution_recovery")
    if (
        isinstance(issue_recovery, dict)
        and issue_recovery.get("status") != "consumed"
        and str(issue_recovery.get("issue_id") or "").strip()
        and action.reason == "issue_resolution"
    ):
        print(
            "[squad] continuing via controller-owned issue-repair workflow edge; "
            "the controller will validate it before dispatch.",
            flush=True,
        )
        # ``_cmd_run`` preserves a terminal-blocked state verbatim.  In semi
        # mode that makes the controller immediately return the same
        # escalation rather than dispatching the requested repair.  Promote
        # the controller-owned recovery edge back to its target phase first;
        # keep its issue ledger/recovery payload so WHY2 can validate it.
        repair_phase = str(issue_recovery.get("to_phase") or "phase1-what").strip()
        start_phase(
            repair_phase or "phase1-what",
            verb="Continuing selected issue repair",
            clear_recovery=True,
        )
        return

    if action.reason == "issue_resolution_revalidation":
        selected_issue = str(state.get("selected_issue_resolution") or "").strip()
        state["issue_resolution_revalidation_attempted"] = selected_issue
        state["why_fail_count"] = 0
        state["why2_metric_stagnation_count"] = 0
        state.pop("why_failure_baseline", None)
        start_phase(
            "phase1-understanding",
            verb="Revalidating selected issue repair",
            clear_recovery=True,
        )
        return

    if action.reason == "quality_gate_remediation":
        state["iteration"] = 0
        state["why_fail_count"] = 0
        state["why2_metric_stagnation_count"] = 0
        state.pop("why_failure_baseline", None)
        # A certified remediation is a new, spec-changing lifecycle cycle.
        # Keep unrelated phase counters for observability, but reset every
        # authoring/quality phase that must run to verify this new artifact.
        _reset_quality_remediation_dispatch_counts(state)
        qualitative_findings = _current_qualitative_findings(state)
        state["quality_gate_remediation"] = {
            "evidence": state.get("understanding_evidence"),
            "baseline_spec_sha256": _spec_markdown_sha256_for_state(
                state, project_root
            ),
            "attempt": int(
                (state.get("quality_gate_remediation") or {}).get("attempt", 0)
            ) + 1 if isinstance(state.get("quality_gate_remediation"), dict) else 1,
            "reason": (
                "All named issue resolutions are complete, but certified quality "
                "review still fails. Begin a fresh remediation cycle."
            ),
            **(
                {"qualitative_findings": qualitative_findings}
                if qualitative_findings
                else {}
            ),
        }
        _supersede_quality_guard_decision(state)
        start_phase(
            "phase1-what",
            verb="Starting quality-gate remediation",
            clear_recovery=True,
        )
        return

    # Echelon versions before the banzai-routing fix persisted a COMMANDER
    # ``next_phase`` as inert metadata, then incorrectly entered Phase-A
    # finalization from ``terminal-blocked``.  Recover that exact historic
    # state without treating the readiness failure as a reason to rewind.
    persisted_banzai_phase = str(state.get("next_phase") or "").strip()
    if (
        state.get("status") == "blocked"
        and state.get("phase") == "terminal-blocked"
        and state.get("blocked_reason") == "phase_a_readiness_failed"
        and state.get("escalation_resolver") == "COMMANDER-banzai"
        and state.get("escalation_resolved") is True
        and persisted_banzai_phase in _ROADMAP_PHASES
    ):
        state.pop("next_phase", None)
        print(
            "[squad] Recovering the persisted banzai COMMANDER route before finalization.",
            flush=True,
        )
        start_phase(
            persisted_banzai_phase,
            verb="Continuing from accepted banzai judgment",
            clear_recovery=True,
        )
        return

    if action.kind == "safe_rewind":
        fields = [("blocked by", action.reason)]
        if action.note:
            fields.append(("why", action.note))
        fields.extend([
            ("recover with", action.command),
            ("then", "echelon spec continue"),
        ])
        _note_spec_summary_next_printed()
        _banner(
            "CHECKPOINT",
            fields,
            subtitle="Run paused. Deterministic recovery required.",
        )
        return
    if action.reason == "phase_dispatch_limit_evidence_retry":
        dispatch_counts = state.get("phase_dispatch_counts")
        if isinstance(dispatch_counts, dict):
            dispatch_counts = dict(dispatch_counts)
            dispatch_counts.pop(action.phase, None)
            state["phase_dispatch_counts"] = dispatch_counts
        start_phase(
            action.phase,
            verb="Retrying phase after active-spec evidence recovery",
            clear_recovery=True,
        )
        return
    if action.kind == "retry_phase":
        start_phase(action.phase, verb="Retrying incomplete phase", clear_recovery=True)
        return
    if action.kind == "resolve_decision":
        print(
            "[squad] continuing through the controller-owned decision resolver.",
            flush=True,
        )
        _cmd_run(resume_run_args(), project_root=project_root, ext_dir=ext_dir)
        return
    if action.kind == "human_resume":
        fields = [
            ("decision needed", action.note or "(no escalation question recorded)"),
        ]
        rendered_options = _render_escalation_options(
            state.get("escalation_options")
        )
        if rendered_options:
            fields.append(("options", rendered_options))
        fields.append(("resume with", action.command))
        _note_spec_summary_next_printed()
        _banner(
            "CHECKPOINT",
            fields,
            subtitle="Run paused. Human decision required.",
        )
        return
    if action.kind == "manual_recovery":
        fields = [
            ("blocked by", action.reason),
            ("next", action.command),
            ("note", action.note),
        ]
        fields.extend(_issue_resolution_screen_guidance(project_root, squad_dir, state))
        _note_spec_summary_next_printed()
        _banner(
            "CHECKPOINT",
            fields,
            subtitle="Run paused. Manual recovery required.",
        )
        return

    # terminal-blocked: the consecutive-fail guard fired. echelon spec resume recorded the
    # user's answer but left phase=terminal-blocked (a TERMINAL_PHASE). The controller
    # would exit immediately from that phase, so we repair state here — advance the
    # phase to the next runnable one — before resuming in the SAME squad dir.
    if cur_phase == "terminal-blocked":
        next_phase = _next_continue_phase(project_root)
        if next_phase is None:
            _note_spec_summary_next_printed()
            print(
                "Build is ready — nothing left to do in Phase A.\n\n"
                "  echelon delivery run <spec-id>",
                flush=True,
            )
            return
        start_phase(next_phase, verb="Continuing from")
        return

    if status in ("running", "in_progress"):
        # Live run — let echelon spec run pick it up (same message → same dir → resume)
        print(f"[squad] Resuming active run in {squad_dir.name}…", flush=True)
        _cmd_run(resume_run_args(), project_root=project_root, ext_dir=ext_dir)
        return

    # Determine the next phase automatically
    next_phase = _next_continue_phase(project_root)
    if next_phase is None:
        _note_spec_summary_next_printed()
        print(
            "Build is ready — nothing left to do in Phase A.\n\n"
            "  echelon delivery run <spec-id>",
            flush=True,
        )
        return

    start_phase(next_phase, verb="Continuing from")


@dataclass(frozen=True)
class _FailedGateRewindAuthority:
    decision_id: str
    state_revision: int
    source_phase: str
    v2_automatic_eligible: bool


def _resolve_rewind_checkpoint(
    ledger: object,
    target: str,
    *,
    commit: str,
    next_phase: str,
) -> object:
    """Resolve the same recovery-specific ledger candidate rendered by status."""
    from harness.phase_checkpoints import resolve_rewind_checkpoint

    return resolve_rewind_checkpoint(
        ledger,
        target,
        commit=commit,
        next_phase=next_phase,
    )


def _failed_gate_rewind_authority(
    state: Mapping[str, object],
    checkpoint: object,
    *,
    project_root: Path,
) -> _FailedGateRewindAuthority | None:
    """Authorize a failed gate rewind before any Git or ledger mutation."""
    from echelon.rewind import RewindError

    raw_decision = state.get("blocked_decision")
    if (
        not isinstance(raw_decision, Mapping)
        or raw_decision.get("schema_version") not in {2, 3}
    ):
        return None
    try:
        decision = _validated_versioned_decision(state)
    except (RecoveryInstructionError, ValueError) as exc:
        raise RewindError(f"versioned decision authority is invalid: {exc}") from exc
    assert decision is not None
    if decision["status"] == "resolved":
        source_phase = str(decision.get("source_phase") or "").strip()
        if (
            decision["source_kind"] == "human_gate"
            and state.get("status") == "blocked"
            and state.get("blocked_reason") == "gate_rejected"
            and str(getattr(checkpoint, "next_phase", "") or "").strip()
            == source_phase
        ):
            return None
        raise RewindError(
            "resolved decision authority is not an exact gate-rejected rewind"
        )
    if decision["status"] != "failed":
        raise RewindError("unresolved decision authority does not permit rewind")
    source_phase = str(decision.get("source_phase") or "").strip()
    predecessor = str(getattr(checkpoint, "phase", "") or "").strip()
    checkpoint_next = str(
        getattr(checkpoint, "next_phase", "") or ""
    ).strip()
    revision = state.get("state_revision")
    v2_eligible = _v2_automatic_decision_is_registered(
        decision,
        project_root=project_root,
    )
    eligible = (
        decision.get("automatic_eligible") is True
        if decision["schema_version"] == 3
        else v2_eligible
    )
    if (
        decision["source_kind"] != "human_gate"
        or decision["autonomy_mode"] != "banzai"
        or state.get("autonomy_mode") != "banzai"
        or state.get("status") != "blocked"
        or state.get("phase") != source_phase
        or not eligible
        or checkpoint_next != source_phase
        or not predecessor
        or type(revision) is not int
        or revision < 0
    ):
        raise RewindError(
            "failed decision does not match the exact Banzai human-gate "
            "rewind authority and checkpoint predecessor"
        )
    return _FailedGateRewindAuthority(
        decision_id=str(decision["id"]),
        state_revision=revision,
        source_phase=source_phase,
        v2_automatic_eligible=v2_eligible,
    )


def _cmd_rewind(
    args: list[str],
    project_root: Path,
) -> None:
    confirm = False
    checkpoint_commit = ""
    checkpoint_next_phase = ""
    commit_seen = False
    next_phase_seen = False
    target = ""
    invalid = False
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--confirm":
            if confirm:
                invalid = True
                break
            confirm = True
            index += 1
            continue
        if arg == "--commit":
            if (
                commit_seen
                or index + 1 >= len(args)
                or args[index + 1].startswith("--")
            ):
                invalid = True
                break
            commit_seen = True
            checkpoint_commit = args[index + 1].strip()
            if not checkpoint_commit:
                invalid = True
                break
            index += 2
            continue
        if arg == "--next-phase":
            if (
                next_phase_seen
                or index + 1 >= len(args)
                or args[index + 1].startswith("--")
            ):
                invalid = True
                break
            next_phase_seen = True
            checkpoint_next_phase = args[index + 1].strip()
            if not checkpoint_next_phase:
                invalid = True
                break
            index += 2
            continue
        if arg.startswith("--") or target:
            invalid = True
            break
        target = arg.strip()
        index += 1
    if invalid or not target:
        print(
            "Usage: echelon spec rewind <checkpoint-phase-or-id> "
            "[--commit <sha>] [--next-phase <phase-id>] [--confirm]\n"
            "Run `echelon spec checkpoint list` to see active-ledger targets.",
            file=sys.stderr,
        )
        sys.exit(1)

    squad_dir = _find_current_run_dir(project_root)
    if squad_dir is None or not (squad_dir / "state.json").exists():
        print(
            "✗ No active squad run found.\n"
            "  Start or resume a run before rewinding.",
            file=sys.stderr,
        )
        sys.exit(1)

    from harness.squad_state import SquadStateStore

    store = SquadStateStore(squad_dir)
    state = store.load()
    spec_dir, spec_dir_ref = _normalize_rewind_spec_dir(project_root, state)
    if spec_dir is None or spec_dir_ref is None:
        print(
            f"✗ Cannot rewind to {target}.\n"
            "  Could not resolve the canonical spec directory from state.json.",
            file=sys.stderr,
        )
        sys.exit(1)

    from echelon.rewind import RewindError, prepare_rewind
    from harness.phase_checkpoints import (
        load_checkpoint_ledger,
        rewindable_checkpoint_targets,
        write_checkpoint_ledger,
    )

    ledger = load_checkpoint_ledger(spec_dir)
    try:
        checkpoint = _resolve_rewind_checkpoint(
            ledger,
            target,
            commit=checkpoint_commit,
            next_phase=checkpoint_next_phase,
        )
    except (KeyError, ValueError) as exc:
        available = rewindable_checkpoint_targets(ledger)
        reason = str(exc.args[0]) if exc.args else (
            f"checkpoint not found for spec {ledger.spec_id}: {target}"
        )
        detail = (
            f"{reason}\n"
            + (
                f"Available checkpoints: {', '.join(available)}"
                if available
                else "No checkpoints are recorded for this spec."
            )
        )
        print(f"✗ Cannot rewind to {target}.\n  {detail}", file=sys.stderr)
        sys.exit(1)
    if checkpoint.rewind != "supported":
        print(
            f"✗ Cannot rewind to {target}.\n"
            f"  Checkpoint does not support rewind: {checkpoint.rewind_reason}",
            file=sys.stderr,
        )
        sys.exit(1)
    try:
        _failed_gate_rewind_authority(
            state,
            checkpoint,
            project_root=project_root,
        )
    except RewindError as exc:
        print(f"✗ Cannot rewind to {target}.\n  {exc}", file=sys.stderr)
        sys.exit(1)

    from echelon.spec_lifecycle import (
        PhaseAExecutionLock,
        SpecLifecycleLocked,
        SpecMutationLock,
        SpecRunExecutionLock,
    )

    operation_id = f"rewind-{os.getpid()}"
    expected_spec_id = spec_dir.name
    try:
        with (
            SpecMutationLock.acquire(project_root, spec_dir.name, operation_id)
            if confirm
            else nullcontext()
        ):
            with PhaseAExecutionLock.acquire(project_root, operation_id):
                locked_squad_dir = _find_current_run_dir(project_root)
                if locked_squad_dir != squad_dir:
                    print(
                        "✗ Cannot rewind because the active run changed before "
                        "the mutation lease was acquired. Retry against the new active run.",
                        file=sys.stderr,
                    )
                    raise SystemExit(1)
                with SpecRunExecutionLock.acquire(locked_squad_dir, operation_id):
                    if _find_current_run_dir(project_root) != locked_squad_dir:
                        print(
                            "✗ Cannot rewind because the active run changed while "
                            "the execution lease was being acquired. Retry.",
                            file=sys.stderr,
                        )
                        raise SystemExit(1)

                    store = SquadStateStore(locked_squad_dir)
                    state = store.load()
                    spec_dir, spec_dir_ref = _normalize_rewind_spec_dir(
                        project_root,
                        state,
                    )
                    if spec_dir is None or spec_dir_ref is None:
                        raise RewindError(
                            "could not resolve the canonical spec directory from "
                            "the locked state.json snapshot"
                        )
                    if spec_dir.name != expected_spec_id:
                        print(
                            "✗ Cannot rewind because the active spec identity changed "
                            "before the mutation lease was acquired. Retry.",
                            file=sys.stderr,
                        )
                        raise SystemExit(1)
                    ledger = load_checkpoint_ledger(spec_dir)
                    try:
                        checkpoint = _resolve_rewind_checkpoint(
                            ledger,
                            target,
                            commit=checkpoint_commit,
                            next_phase=checkpoint_next_phase,
                        )
                    except (KeyError, ValueError) as exc:
                        available = rewindable_checkpoint_targets(ledger)
                        reason = str(exc.args[0]) if exc.args else (
                            f"checkpoint not found for spec {ledger.spec_id}: {target}"
                        )
                        suffix = (
                            f"\nAvailable checkpoints: {', '.join(available)}"
                            if available
                            else "\nNo checkpoints are recorded for this spec."
                        )
                        raise RewindError(reason + suffix) from exc
                    if checkpoint.rewind != "supported":
                        raise RewindError(
                            "checkpoint does not support rewind: "
                            f"{checkpoint.rewind_reason}"
                        )
                    failed_gate_authority = _failed_gate_rewind_authority(
                        state,
                        checkpoint,
                        project_root=project_root,
                    )
                    replacement_state = deepcopy(state)

                    recovery_dirty_paths = frozenset()
                    if checkpoint.source == "retarget-preflight":
                        from echelon.spec_retarget_recovery import (
                            RetargetRecoveryError,
                            resume_committed_retarget_recovery,
                            retarget_recovery_dirty_paths,
                            verified_committed_retarget_recovery,
                        )

                        try:
                            recovery_commit = verified_committed_retarget_recovery(
                                project_root,
                                checkpoint,
                                replacement_state,
                            )
                        except RetargetRecoveryError as exc:
                            raise RewindError(str(exc)) from exc
                        if recovery_commit is not None and not confirm:
                            print(
                                "Retarget recovery is already committed. No changes "
                                "were made.\n"
                                f"  echelon spec rewind checkpoint:{checkpoint.id} "
                                "--confirm"
                            )
                            return
                        if recovery_commit is not None:
                            try:
                                resumed = resume_committed_retarget_recovery(
                                    project_root,
                                    checkpoint,
                                    replacement_state,
                                )
                            except RetargetRecoveryError as exc:
                                raise RewindError(str(exc)) from exc
                            if resumed is None:
                                raise RewindError(
                                    "verified retarget recovery commit became unavailable"
                                )
                            print(
                                "Retarget recovery was already committed; "
                                "state and active-run publication are complete."
                            )
                            return
                        try:
                            recovery_dirty_paths = retarget_recovery_dirty_paths(
                                project_root,
                                spec_dir,
                                replacement_state,
                            )
                        except RetargetRecoveryError as exc:
                            raise RewindError(str(exc)) from exc
                    result = prepare_rewind(
                        project_root=project_root,
                        spec=spec_dir.name,
                        spec_dir=spec_dir,
                        target=target,
                        confirm=confirm,
                        checkpoint_commit=checkpoint_commit,
                        checkpoint_next_phase=checkpoint_next_phase,
                        discard_active_spec_dirty_paths=recovery_dirty_paths,
                    )
                    if not result.applied:
                        print(result.message)
                        return

                    target_index = ledger.checkpoints.index(checkpoint)
                    retained_ledger = type(ledger)(
                        spec_id=ledger.spec_id,
                        checkpoints=ledger.checkpoints[: target_index + 1],
                    )
                    write_checkpoint_ledger(spec_dir, retained_ledger)
                    if checkpoint.source == "retarget-preflight":
                        from echelon.spec_retarget_recovery import (
                            RetargetRecoveryError,
                            recover_retarget_checkpoint,
                        )

                        try:
                            recover_retarget_checkpoint(
                                project_root,
                                checkpoint,
                                replacement_state,
                            )
                        except RetargetRecoveryError as exc:
                            raise RewindError(str(exc)) from exc
                        removed = ()
                    else:
                        checkpoint_phases_before_target = {
                            item.phase for item in ledger.checkpoints[:target_index]
                        }
                        removed = _cleanup_rewind_outputs(
                            spec_dir,
                            checkpoint.phase,
                            squad_dir,
                        )
                        rewound = _reset_rewind_state(
                            state,
                            checkpoint.phase,
                            spec_dir_ref,
                            checkpoint_phases_before_target=(
                                checkpoint_phases_before_target
                            ),
                            boundary_completion_id=(
                                checkpoint.boundary_completion_id
                            ),
                            preserve_resolved_gate_rejection=(
                                failed_gate_authority is None
                                and isinstance(state.get("blocked_decision"), Mapping)
                                and state["blocked_decision"].get("status") == "resolved"
                            ),
                            preserve_failed_human_gate_for_cas=(
                                failed_gate_authority is not None
                            ),
                        )
                        if failed_gate_authority is None:
                            store.save(rewound)
                        else:
                            from harness.squad_state import StateAdvanceError

                            try:
                                store.rewind_failed_banzai_human_gate(
                                    failed_gate_authority.decision_id,
                                    expected_state_revision=(
                                        failed_gate_authority.state_revision
                                    ),
                                    source_phase=(
                                        failed_gate_authority.source_phase
                                    ),
                                    predecessor_phase=checkpoint.phase,
                                    rewound_state=rewound,
                                    v2_automatic_eligible=(
                                        failed_gate_authority.v2_automatic_eligible
                                    ),
                                )
                            except StateAdvanceError as exc:
                                raise RewindError(str(exc)) from exc
    except SpecLifecycleLocked as exc:
        print(
            "✗ Cannot rewind while the active spec run is still running.\n"
            f"  Execution or spec mutation lease owner: {exc.operation_id}.\n"
            "  Interrupt it and wait for `echelon spec status` to show INTERRUPTED, then retry.",
            file=sys.stderr,
        )
        sys.exit(1)
    except RewindError as exc:
        print(f"✗ Cannot rewind to {target}.\n  {exc}", file=sys.stderr)
        sys.exit(1)

    _banner(
        "REWIND COMPLETE",
        [
            ("spec", result.spec_id),
            ("checkpoint", result.checkpoint_id),
            ("from", result.from_commit[:7]),
            ("to", result.to_commit[:7]),
            ("backup", result.backup_ref or "(none)"),
            ("cleaned", ", ".join(removed) if removed else "(none)"),
            ("next", "echelon spec continue"),
        ],
    )


def _cmd_repair_traceability(args: list[str], project_root: Path) -> None:
    """Safely remove contextual task references from active product-input evidence."""
    confirm = "--confirm" in args
    if any(arg != "--confirm" for arg in args):
        print("Usage: echelon spec repair-traceability [--confirm]", file=sys.stderr)
        raise SystemExit(1)

    squad_dir = _find_current_run_dir(project_root)
    if squad_dir is None or not (squad_dir / "state.json").is_file():
        print("✗ No active squad run found.", file=sys.stderr)
        raise SystemExit(1)

    if confirm:
        from threading import get_ident
        from uuid import uuid4

        from echelon.spec_lifecycle import (
            PhaseAExecutionLock,
            SpecLifecycleLocked,
            SpecRunExecutionLock,
        )

        operation_id = f"repair-traceability-{os.getpid()}-{get_ident()}-{uuid4().hex}"
        try:
            with PhaseAExecutionLock.acquire(project_root, operation_id):
                with SpecRunExecutionLock.acquire(squad_dir, operation_id):
                    _cmd_repair_traceability_locked(project_root, squad_dir, confirm=True)
                    return
        except SpecLifecycleLocked as exc:
            print(
                "✗ Cannot repair traceability while execution is active.\n"
                f"  Lease owner: {exc.operation_id}",
                file=sys.stderr,
            )
            raise SystemExit(1) from exc
    _cmd_repair_traceability_locked(project_root, squad_dir, confirm=False)


def _cmd_repair_traceability_locked(
    project_root: Path,
    squad_dir: Path,
    *,
    confirm: bool,
) -> None:
    """Preview or transactionally commit an authenticated package repair."""
    from uuid import uuid4

    from echelon.product_input_transaction import (
        ProductInputMutationError,
        add_complete_product_input_publication,
        authenticate_pending_product_input_mutation,
        authenticate_product_input_contract,
        build_product_input_mutation,
        product_input_tree_identity,
        require_product_input_mutation_postimage,
        restore_product_input_directory_modes,
    )
    from echelon.product_inputs import (
        immutable_product_input_tree_digest,
        repair_product_input_traceability,
    )
    from echelon.spec_add_input import SpecAddInputError, _recover_pending_mutation
    from harness.squad_publication import SquadPublicationTransaction
    from harness.squad_state import SquadStateStore

    store = SquadStateStore(squad_dir)
    if confirm:
        try:
            recovered = _recover_pending_mutation(project_root, store)
        except SpecAddInputError as exc:
            print(f"✗ Traceability repair recovery failed: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        if recovered is not None and recovered.get("kind") == "traceability_repair":
            _banner(
                "TRACEABILITY REPAIRED",
                [("next", "echelon spec continue")],
                subtitle="Recovered the authenticated repair publication.",
            )
            return
    state = store.load()
    if str(state.get("blocked_reason") or "") != "phase_a_readiness_failed":
        print("✗ Traceability repair is available only for a Phase A readiness block.", file=sys.stderr)
        raise SystemExit(1)
    spec_dir, spec_dir_ref = _normalize_rewind_spec_dir(project_root, state)
    inputs = state.get("product_inputs")
    traceability_ref = str(inputs.get("traceability") or "").strip() if isinstance(inputs, dict) else ""
    inputs_ref = str(inputs.get("inputs_dir") or "").strip() if isinstance(inputs, dict) else ""
    if spec_dir is None or spec_dir_ref is None or not traceability_ref or not inputs_ref:
        print("✗ Active run lacks the spec or product-input evidence needed for repair.", file=sys.stderr)
        raise SystemExit(1)
    inputs_dir = Path(inputs_ref)
    if not inputs_dir.is_absolute():
        inputs_dir = project_root / inputs_dir
    inputs_dir = inputs_dir.resolve()
    if inputs_dir != (squad_dir / "inputs").resolve():
        print("✗ Active run Product Input Contract is not run-local.", file=sys.stderr)
        raise SystemExit(1)
    traceability_path = Path(traceability_ref)
    if not traceability_path.is_absolute():
        traceability_path = project_root / traceability_path
    if traceability_path.resolve() != inputs_dir / "traceability.json":
        print("✗ Product-input traceability pointer is not canonical.", file=sys.stderr)
        raise SystemExit(1)
    targets = [str(value).strip() for value in state.get("implementation_targets", []) if str(value).strip()]
    try:
        old_tree_hash = authenticate_product_input_contract(
            project_root,
            inputs,
            inputs_dir,
        )
    except ProductInputMutationError as exc:
        print(f"✗ Product-input package authentication failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    if not confirm:
        repair = repair_product_input_traceability(
            traceability_path,
            spec_dir / "tasks.md",
            targets,
            apply=False,
        )
    else:
        snapshot = store.capture_routing_snapshot(
            expected_phase=str(state.get("phase") or "")
        )
        transaction = SquadPublicationTransaction.begin(
            project_root,
            squad_dir,
            uuid4().hex,
        )
        staged_old_inputs = transaction.build_path("work/product-inputs-old")
        staged_inputs = transaction.build_path("work/product-inputs")
        prepared = None
        try:
            source_identity = product_input_tree_identity(inputs_dir)
            shutil.copytree(
                inputs_dir,
                staged_old_inputs,
                symlinks=True,
                copy_function=shutil.copy2,
            )
            if (
                authenticate_product_input_contract(
                    project_root,
                    inputs,
                    inputs_dir,
                )
                != old_tree_hash
                or product_input_tree_identity(inputs_dir) != source_identity
                or immutable_product_input_tree_digest(staged_old_inputs)
                != old_tree_hash
            ):
                raise ProductInputMutationError(
                    "product input package changed during repair staging"
                )
            shutil.copytree(
                staged_old_inputs,
                staged_inputs,
                symlinks=True,
                copy_function=shutil.copy2,
            )
            if immutable_product_input_tree_digest(staged_inputs) != old_tree_hash:
                raise ProductInputMutationError(
                    "staged product input preimage changed during repair staging"
                )
            repair = repair_product_input_traceability(
                staged_inputs / "traceability.json",
                spec_dir / "tasks.md",
                targets,
                apply=True,
            )
            restore_product_input_directory_modes(
                staged_old_inputs,
                staged_inputs,
            )
            if repair.blockers or not repair.removed:
                transaction.seal().discard()
                prepared = False
            else:
                owned_paths = add_complete_product_input_publication(
                    transaction,
                    project_root,
                    inputs_dir,
                    staged_inputs,
                )
                new_tree_hash = immutable_product_input_tree_digest(staged_inputs)
                prepared = transaction.seal()
                marker = prepared.marker.to_dict()
                mutation = build_product_input_mutation(
                    kind="traceability_repair",
                    marker=marker,
                    inputs_dir=inputs_ref,
                    old_tree_hash=old_tree_hash,
                    new_tree_hash=new_tree_hash,
                    owned_paths=owned_paths,
                )
        except Exception as exc:
            if prepared is None:
                try:
                    transaction.seal().discard()
                except Exception:
                    pass
            print(f"✗ Cannot stage traceability repair: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc

    if repair.blockers:
        print("✗ Traceability cannot be repaired safely:", file=sys.stderr)
        for blocker in repair.blockers:
            print(f"  - {blocker}", file=sys.stderr)
        print("  Re-plan with: echelon spec rewind phase3-plan", file=sys.stderr)
        raise SystemExit(1)
    if not repair.removed:
        print("✗ No contextual task references were available to repair.", file=sys.stderr)
        raise SystemExit(1)

    rows = [("remove", f"{unit_id} → {task_id}") for unit_id, task_id in repair.removed]
    if not confirm:
        rows.append(("next", "echelon spec repair-traceability --confirm"))
        _banner("TRACEABILITY REPAIR PREVIEW", rows, subtitle="No evidence or run state changed.")
        return

    repaired = _reset_rewind_state(state, "phase4-document", spec_dir_ref)
    repaired_inputs = dict(inputs)
    repaired_inputs["tree_hash"] = new_tree_hash
    repaired["product_inputs"] = repaired_inputs
    try:
        store.begin_traceability_repair_publication(
            marker,
            mutation,
            snapshot=snapshot,
            desired_state=repaired,
        )
    except Exception as exc:
        try:
            prepared.discard()
        except Exception:
            pass
        print(f"✗ Cannot persist traceability repair intent: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    try:
        durable = store.confirm_durable_state(store.load())
        authenticate_pending_product_input_mutation(
            project_root,
            durable,
            marker,
            prepared._manifest["operations"],
            staged_inputs=staged_inputs,
        )
        prepared.publish()
        verified_hash = require_product_input_mutation_postimage(
            project_root,
            store.load(),
            marker,
        )
        store.complete_external_publication(
            marker,
            verified_product_input_tree_hash=verified_hash,
        )
        store.confirm_durable_state(store.load())
        prepared.discard()
    except Exception as exc:
        print(
            f"✗ Traceability repair remains pending with evidence retained: {exc}",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
    rows.append(("next", "echelon spec continue"))
    _banner("TRACEABILITY REPAIRED", rows, subtitle="Direct mappings preserved; finalization can resume.")


def _cmd_drop_target(
    args: list[str],
    project_root: Path,
    *,
    _mutation_locked: bool = False,
) -> None:
    """Remove one unreferenced delivery target from the active unfinished run.

    This deliberately supports only a declared target with no task ownership.
    Adding or replacing targets requires re-authoring because it changes the
    architecture decision space; an unused target can safely return to PLAN.
    """
    confirm = "--confirm" in args
    positional = [arg for arg in args if arg != "--confirm"]
    if len(positional) != 2:
        print(
            "Usage: echelon spec drop-target <spec_id> <target> --confirm\n"
            "  Removes one unused declared target and re-dispatches phase3-plan.",
            file=sys.stderr,
        )
        sys.exit(1)
    spec_id, target = (value.strip().rstrip("/") for value in positional)
    if not spec_id or not target:
        print("✗ spec id and target must not be empty", file=sys.stderr)
        sys.exit(1)

    if confirm and not _mutation_locked:
        from echelon.spec_lifecycle import (
            PhaseAExecutionLock,
            SpecLifecycleLocked,
            SpecMutationLock,
        )

        operation_id = f"drop-target-{os.getpid()}"
        try:
            with SpecMutationLock.acquire(project_root, spec_id, operation_id):
                with PhaseAExecutionLock.acquire(project_root, operation_id):
                    return _cmd_drop_target(
                        args,
                        project_root,
                        _mutation_locked=True,
                    )
        except SpecLifecycleLocked as exc:
            print(
                "✗ Cannot drop a target while the spec mutation lease is owned by "
                f"{exc.operation_id}.",
                file=sys.stderr,
            )
            raise SystemExit(1) from exc

    squad_dir = _find_current_run_dir(project_root)
    if squad_dir is None or not (squad_dir / "state.json").is_file():
        print("✗ No active squad run found.", file=sys.stderr)
        sys.exit(1)

    from harness.spec_frontmatter import write_targets
    from harness.squad_state import SquadStateStore
    from harness.task_targets import analyze_task_targets

    store = SquadStateStore(squad_dir)
    state = store.load()
    active_spec_id = str(state.get("spec_id") or "").strip()
    if active_spec_id != spec_id:
        print(
            f"✗ Active run owns spec {active_spec_id or '(unknown)'!r}, not {spec_id!r}.",
            file=sys.stderr,
        )
        sys.exit(1)
    if str(state.get("status") or "") == "done":
        print(
            "✗ Cannot drop a target from a completed spec. Start a new spec run instead.",
            file=sys.stderr,
        )
        sys.exit(1)

    declared = [
        str(value).strip().rstrip("/")
        for value in state.get("implementation_targets") or []
        if str(value).strip()
    ]
    if target not in declared:
        print(f"✗ Target {target!r} is not declared by the active run.", file=sys.stderr)
        sys.exit(1)
    replacement_targets = [value for value in declared if value != target]
    if not replacement_targets:
        print("✗ A spec must retain at least one implementation target.", file=sys.stderr)
        sys.exit(1)

    spec_dir, spec_dir_ref = _normalize_rewind_spec_dir(project_root, state)
    if spec_dir is None or spec_dir_ref is None:
        print("✗ Could not resolve the active spec directory from state.json.", file=sys.stderr)
        sys.exit(1)

    tasks_file = spec_dir / "tasks.md"
    if tasks_file.is_file():
        analysis = analyze_task_targets(tasks_file.read_text(encoding="utf-8"))
        owned_tasks = analysis.target_tasks.get(target, ())
        if owned_tasks:
            print(
                f"✗ Cannot drop {target!r}: it owns task(s) {', '.join(owned_tasks)}.\n"
                "  Re-author the target decision before changing delivery scope.",
                file=sys.stderr,
            )
            sys.exit(1)

    planning_outputs = _REWIND_CLEANUP_OUTPUTS["phase3-plan"]
    if not confirm:
        _banner(
            "DROP TARGET PREVIEW",
            [
                ("spec", spec_id),
                ("remove", target),
                ("remain", ", ".join(replacement_targets)),
                ("invalidate", ", ".join(planning_outputs)),
                ("next", f"echelon spec drop-target {spec_id} {target} --confirm"),
            ],
            subtitle="No files or run state changed.",
        )
        return

    from echelon.rewind import RewindError

    try:
        updated = _reset_rewind_state(state, "phase3-plan", spec_dir_ref)
    except RewindError as exc:
        print(f"✗ Cannot drop target: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    spec_dirs = [spec_dir]
    published_ref = str(state.get("published_spec_dir") or "").strip()
    if published_ref:
        published_dir = Path(published_ref)
        if not published_dir.is_absolute():
            published_dir = project_root / published_dir
        if published_dir.is_dir() and published_dir not in spec_dirs:
            spec_dirs.append(published_dir)

    removed: list[str] = []
    for directory in spec_dirs:
        write_targets(directory, replacement_targets)
        for name in planning_outputs:
            output = directory / name
            if output.exists():
                output.unlink()
                if name not in removed:
                    removed.append(name)

    updated["implementation_targets"] = replacement_targets
    updated["tasks_lexicon_pass"] = None
    updated["target_change"] = {
        "action": "drop-unused-target",
        "removed": target,
        "remaining": replacement_targets,
        "invalidated_outputs": removed,
    }
    store.save(updated)

    _banner(
        "TARGET REMOVED",
        [
            ("spec", spec_id),
            ("removed", target),
            ("targets", ", ".join(replacement_targets)),
            ("invalidated", ", ".join(removed) if removed else "(none)"),
            ("next", "echelon spec continue"),
        ],
        subtitle="Task planning will be regenerated for the remaining targets.",
    )


def _cmd_benchmark(args: list[str], project_root: Path) -> None:
    from echelon.benchmark import (
        CONTEXT_RENDER_MODES,
        baseline_snapshot_commands,
        format_variant_execution_commands,
        latest_summary_path,
        load_saved_scorecard,
        load_summary,
        list_fixtures,
        list_variants,
        plan_variant_commands,
        run_benchmark_variant,
    )

    fixtures = list_fixtures()
    variants = list_variants()
    fixture_ids = {fixture.id for fixture in fixtures}
    variant_ids = {variant.id for variant in variants}
    usage = (
        "Usage:\n"
        "  echelon benchmark list\n"
        "  echelon benchmark show [latest|<summary-path-or-run-dir>]\n"
        "  echelon benchmark run <fixture-id> --variant <variant-id> "
        "[--baseline-ref <ref>] [--artifact-only] [--context-render legacy|bounded|both] [--dry-run]\n"
        "\n"
        "Example:\n"
        "  echelon benchmark run tiny-notes --variant baseline\n"
        "\n"
        "If --baseline-ref is omitted, Echelon commits the current workspace as "
        "the benchmark baseline snapshot.\n"
    )

    if not args or args[0] in ("-h", "--help"):
        print(usage, flush=True)
        return

    if args[0] == "list":
        _banner(
            "BENCHMARKS",
            [("Fixtures", "benchmark prompts"), ("Variants", "pass with --variant <id>")],
            subtitle="Experimental artifact-quality benchmark fixtures and variants",
        )
        print("Fixtures:")
        for fixture in fixtures:
            print(f"  {fixture.id:<30} {fixture.name}")
        print("\nVariants (--variant <id>):")
        for variant in variants:
            print(f"  {variant.id:<30} {variant.label}")
        print("\nExample:")
        print("  echelon benchmark run tiny-notes --variant baseline")
        print("\nBaseline snapshot:")
        print("  --baseline-ref is optional; omitted runs commit the current workspace first.")
        print("\nPrint saved scores:")
        print("  echelon benchmark show")
        print("\nFor an existing spec, use: echelon delivery run <spec-id>")
        return

    if args[0] == "show":
        if len(args) > 2:
            print("✗ Usage: echelon benchmark show [latest|<summary-path-or-run-dir>]", file=sys.stderr)
            sys.exit(1)
        target = args[1] if len(args) == 2 else "latest"
        latest_path = latest_summary_path(project_root)
        summary_path = latest_path if target == "latest" else Path(target)
        if summary_path is None:
            print("✗ No benchmark summaries found under runs/benchmarks/.", file=sys.stderr)
            sys.exit(1)
        summary = load_saved_scorecard(project_root) if target == "latest" else load_summary(summary_path)
        if not summary:
            print(f"✗ Could not read benchmark summary: {summary_path}", file=sys.stderr)
            sys.exit(1)
        _banner(
            "BENCHMARK SUMMARY",
            [("summary", str(summary_path)), ("best_variant", str(summary.get("best_variant")))],
            subtitle="Saved benchmark scores",
        )
        print(
            "| Variant | Render | Status | Spec | Delivery | Gaps | Verify Failures | Blocks | Retries | Dispatches | Context Bytes | Context Tokens | Context Reduction | Seconds |"
        )
        print("|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
        variants = summary.get("variants")
        if isinstance(variants, dict):
            for variant_id, record in variants.items():
                if not isinstance(record, dict):
                    continue
                print(
                    f"| {variant_id} | {record.get('context_render') or '-'} | "
                    f"{record.get('status', '')} | {record.get('spec_id') or '-'} | "
                    f"{record.get('delivery_run_id') or '-'} | {record.get('fulfillment_gaps', 0)} | "
                    f"{record.get('verification_failures', 0)} | {record.get('blocked_states', 0)} | "
                    f"{record.get('retries', 0)} | {record.get('build_dispatches', 0)} | "
                    f"{record.get('context_prompt_bytes', 0)} | "
                    f"{record.get('context_prompt_tokens_estimate', 0)} | "
                    f"{record.get('context_reduction_pct', 0)} | "
                    f"{float(record.get('elapsed_seconds') or 0.0):.1f} |"
                )
        return

    if args[0] != "run" or len(args) < 2:
        if args[0] in fixture_ids:
            print(
                "✗ Missing benchmark subcommand: run\n"
                f"  Did you mean: echelon benchmark run {args[0]} "
                "--variant baseline --baseline-ref <ref>",
                file=sys.stderr,
            )
            sys.exit(1)
        if args[0].startswith("variant:"):
            print(
                "✗ Benchmark variants are passed after --variant.\n"
                "  Example: echelon benchmark run tiny-notes --variant baseline "
                "--baseline-ref <ref>",
                file=sys.stderr,
            )
            sys.exit(1)
        print(
            "✗ " + usage.rstrip(),
            file=sys.stderr,
        )
        sys.exit(1)

    fixture_id = args[1]
    if fixture_id.startswith("-"):
        print(
            "✗ Missing benchmark fixture id after 'run'.\n"
            "  Example: echelon benchmark run tiny-notes --variant baseline "
            "--baseline-ref <ref>",
            file=sys.stderr,
        )
        sys.exit(1)

    variant_id = "baseline"
    baseline_ref = ""
    artifact_only = False
    dry_run = False
    context_render = "bounded"
    i = 2
    while i < len(args):
        if args[i] == "--variant" and i + 1 < len(args):
            variant_id = args[i + 1]
            i += 2
        elif args[i] == "--baseline-ref" and i + 1 < len(args):
            baseline_ref = args[i + 1]
            i += 2
        elif args[i] == "--artifact-only":
            artifact_only = True
            i += 1
        elif args[i] == "--context-render" and i + 1 < len(args):
            context_render = args[i + 1]
            i += 2
        elif args[i] == "--dry-run":
            dry_run = True
            i += 1
        else:
            print(f"✗ Unknown benchmark argument: {args[i]}", file=sys.stderr)
            sys.exit(1)

    if context_render not in CONTEXT_RENDER_MODES:
        print(f"✗ Unknown context render mode: {context_render}", file=sys.stderr)
        sys.exit(1)

    try:
        plan = plan_variant_commands(fixture_id, variant_id, artifact_only=artifact_only)
    except ValueError as exc:
        if variant_id in fixture_ids and variant_id not in variant_ids:
            print(
                f"✗ {variant_id} is a fixture id, not a variant id.\n"
                "  Use --variant baseline, constitution, constitution-tasks, "
                "or constitution-tasks-adrs.",
                file=sys.stderr,
            )
            sys.exit(1)
        if variant_id.startswith("variant:"):
            print(
                f"✗ Use --variant {variant_id.removeprefix('variant:')}, "
                f"not --variant {variant_id}.",
                file=sys.stderr,
            )
            sys.exit(1)
        print(f"✗ {exc}", file=sys.stderr)
        sys.exit(1)

    if dry_run:
        baseline_marker = baseline_ref or "BENCHMARK_BASELINE_SNAPSHOT"
        render_modes = ("legacy", "bounded") if context_render == "both" else (context_render,)
        commands = (() if baseline_ref else baseline_snapshot_commands()) + tuple(
            formatted_command
            for render_mode in render_modes
            for formatted_command in format_variant_execution_commands(
                plan,
                baseline_marker,
                context_render=render_mode,
            )
        )
        _banner(
            "BENCHMARK DRY RUN",
            [
                ("fixture", plan.fixture_id),
                ("variant", plan.variant_id),
                ("context_render", context_render),
                ("mode", "artifact-only" if artifact_only else "full"),
            ],
            subtitle="Commands that would run",
        )
        for command in commands:
            print(command if isinstance(command, str) else " ".join(command))
        return

    output_dir = run_benchmark_variant(
        project_root,
        fixture_id,
        variant_id,
        baseline_ref=baseline_ref or None,
        artifact_only=artifact_only,
        context_render=context_render,
    )
    _banner(
        "BENCHMARK COMPLETE",
        [
            ("fixture", fixture_id),
            ("variant", variant_id),
            ("context_render", context_render),
            ("mode", "artifact-only" if artifact_only else "full"),
            ("output", str(output_dir)),
        ],
    )


def _cmd_phase(
    args: list[str],
    project_root: Path,
    ext_dir: Path,
) -> None:
    from harness.config import get_full_resolved_config, load_config
    from harness.paths import make_spec_run_id
    from harness.phase_graph import load_workspace_phase_graph
    from harness.squad import SquadController
    from harness.squad_provider import SquadCliProvider
    from harness.squad_state import SquadStateStore, StateAdvanceError

    graph, ext_dir = load_workspace_phase_graph(project_root)

    if not args or args[0] in ("-h", "--help"):
        print(
            "Usage:\n"
            "  echelon phase list\n"
            "  echelon phase run <phase-id> [--spec <id>] [--mode semi|banzai|guided] "
            "[--message <text>]\n",
            flush=True,
        )
        return

    subcommand = args[0]
    if subcommand == "list":
        _banner(
            "PHASES",
            [
                (phase_id, f"{graph.get(phase_id).label or '-'}  [{graph.get(phase_id).type}]")
                for phase_id in graph.all_phase_ids()
            ],
            subtitle="Workflow phases available for manual replay",
        )
        return

    if subcommand != "run":
        print(f"✗ Unknown phase subcommand: {subcommand}", file=sys.stderr)
        print("  Usage: echelon phase list | echelon phase run <phase-id>", file=sys.stderr)
        sys.exit(1)

    if len(args) < 2:
        print("✗ Missing phase id.", file=sys.stderr)
        print("  Usage: echelon phase run <phase-id> [--spec <id>]", file=sys.stderr)
        sys.exit(1)

    phase_id = args[1]
    if phase_id not in graph.all_phase_ids():
        print(f"✗ Unknown phase id: {phase_id}", file=sys.stderr)
        print("Available phases:", file=sys.stderr)
        for known in graph.all_phase_ids():
            print(f"  - {known}", file=sys.stderr)
        sys.exit(1)

    if _phase_run_requires_task_lexicon_config(phase_id):
        _enforce_project_config_compatibility(project_root)

    _workspace_git_preflight(project_root, command_name="echelon phase run")

    mode = "semi"
    spec_arg = ""
    message_parts: list[str] = []
    i = 2
    while i < len(args):
        parsed_mode, next_i = _consume_mode_arg(args, i, command_name="echelon phase run")
        if parsed_mode is not None:
            mode = parsed_mode
            i = next_i
        elif args[i] == "--spec" and i + 1 < len(args):
            spec_arg = args[i + 1]
            i += 2
        elif args[i] == "--message" and i + 1 < len(args):
            message_parts.append(args[i + 1])
            i += 2
        else:
            print(f"✗ Unknown phase run argument: {args[i]}", file=sys.stderr)
            print(
                "  Usage: echelon phase run <phase-id> [--spec <id>] "
                "[--mode semi|banzai|guided] [--message <text>]",
                file=sys.stderr,
            )
            sys.exit(1)
    run_dir = _find_current_run_dir(project_root)
    if run_dir is None:
        print(
            "✗ echelon phase run requires an active spec run. "
            "Start one with: echelon spec run <description>",
            file=sys.stderr,
        )
        raise SystemExit(1)

    from echelon.strict_json import loads_strict_json

    state_path = run_dir / "state.json"
    if state_path.exists():
        try:
            current_state = loads_strict_json(
                state_path.read_text(encoding="utf-8")
            )
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            print(f"✗ Could not read active run state: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
    else:
        current_state = {}
    if not isinstance(current_state, dict):
        print("✗ Active run state must be a JSON object.", file=sys.stderr)
        raise SystemExit(1)
    try:
        failed_replay = _failed_automatic_phase_replay(
            current_state,
            phase_id=phase_id,
            spec_arg=spec_arg,
            project_root=project_root,
            run_dir=run_dir,
            graph=graph,
        )
    except (RecoveryInstructionError, ValueError, TypeError) as exc:
        print(f"✗ Invalid failed decision replay authority: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    state_store = SquadStateStore(run_dir)
    loaded_state = state_store.load()
    if failed_replay is not None and loaded_state != current_state:
        print(
            "✗ Failed decision replay authority changed before target setup.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    current_state = loaded_state
    target_spec_dir = _resolve_phase_target_spec_dir(
        project_root,
        current_state,
        run_dir,
        spec_arg,
    )
    if spec_arg and target_spec_dir is None:
        print(f"✗ Spec not found for --spec {spec_arg!r}", file=sys.stderr)
        sys.exit(1)
    if (
        failed_replay is not None
        and (
            target_spec_dir is None
            or target_spec_dir.resolve() != failed_replay.spec_dir.resolve()
        )
    ):
        print(
            "✗ Failed decision replay target does not match the active spec identity.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    initial_updates = _phase_state_updates_for_target(
        project_root,
        current_state,
        target_spec_dir,
        materialize=failed_replay is None,
    )
    if failed_replay is not None:
        # Authorize and persist the exact identity representation sealed in the
        # failed state after selector/path equivalence has been proven above.
        initial_updates["spec_id"] = failed_replay.spec_id
        initial_updates["spec_dir"] = failed_replay.spec_dir_ref
        initial_updates["phase_run_source_spec_dir"] = failed_replay.spec_dir_ref
    if initial_updates:
        initial_updates["manual_phase_run"] = True

    node = graph.get(phase_id)
    context_rows = _phase_context_resolution_rows(
        node,
        project_root,
        {**current_state, **initial_updates},
        target_spec_dir,
    )
    resolved_count = sum(1 for _, resolved in context_rows if resolved != "missing")
    _banner(
        "PHASE RUN",
        [
            ("phase", phase_id),
            ("run", run_dir.name),
            ("mode", mode),
            ("target", str(target_spec_dir) if target_spec_dir else "(none resolved)"),
            ("context", f"{resolved_count}/{len(context_rows)} resolved" if context_rows else "(none)"),
        ],
        subtitle="Manual single-phase replay",
    )

    config = load_config(project_root, squad_only=True)
    provider = SquadCliProvider(config)

    token_budget = 0
    max_iterations = 5
    try:
        full_config = get_full_resolved_config(project_root)
        analysis = full_config.get("analysis") or {}
        token_budget_k = int(analysis.get("token_budget_k") or 0)
        token_budget = token_budget_k * 1000 if token_budget_k else 0
        max_iterations = int(analysis.get("max_iterations") or 5)
    except Exception:
        pass

    controller = SquadController(
        provider=provider,
        state_store=state_store,
        phase_graph=graph,
        ext_dir=ext_dir,
        project_root=project_root,
        token_budget=token_budget,
        max_iterations=max_iterations,
        squad_dir=run_dir,
    )

    if failed_replay is not None:
        try:
            authorized = (
                state_store.authorize_failed_automatic_decision_for_manual_phase_replay(
                    phase_id,
                    decision_id=str(failed_replay.decision["id"]),
                    expected_state_revision=failed_replay.state_revision,
                    v2_automatic_eligible=(
                        failed_replay.v2_automatic_eligible
                    ),
                    expected_spec_id=failed_replay.spec_id,
                    expected_spec_dir=failed_replay.spec_dir_ref,
                    initial_state_updates=initial_updates,
                )
            )
        except (StateAdvanceError, ValueError, TypeError) as exc:
            print(
                f"✗ Failed decision replay authority changed: {exc}",
                file=sys.stderr,
            )
            raise SystemExit(1) from exc
        if not authorized:
            source_phase = str(
                failed_replay.decision.get("source_phase") or ""
            ).strip()
            replay_command = _command_display(
                "echelon phase run",
                [source_phase],
            )
            print(
                "✗ Failed automatic decision can only be retired by its exact "
                f"source replay: {replay_command}",
                file=sys.stderr,
            )
            raise SystemExit(1)
        print(
            "[squad] authorized failed automatic Banzai decision replay: "
            f"{phase_id}",
            flush=True,
        )

    user_message = " ".join(message_parts) or current_state.get("user_message", "")
    try:
        result = controller.run_single_phase(
            phase_id,
            user_message=user_message,
            mode=mode,
            initial_state_updates=initial_updates,
        )
    except StateAdvanceError as exc:
        if failed_replay is None:
            raise
        print(
            f"✗ Failed decision replay authority changed before dispatch: {exc}",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
    finally:
        state_store.clear_failed_automatic_decision_for_manual_phase_replay()

    next_action = (
        "echelon phase run phase1-lexicon"
        if phase_id == "phase1-lexicon-derive" and result.status in {"running", "done"}
        else "echelon spec continue"
    )
    recovery_note = ""
    final_state = state_store.load()
    if result.status == "blocked":
        recovery = _classify_run_recovery(final_state, project_root=project_root)
        if recovery.kind in {"manual_recovery", "human_resume", "safe_rewind"} and recovery.command:
            next_action = recovery.command
            recovery_note = recovery.note
    fields = [
        ("phase", result.phase),
        ("artifacts", str(target_spec_dir or run_dir)),
        ("next", next_action),
    ]
    if recovery_note:
        fields.append(("note", recovery_note))

    status_icon = "✓" if result.status in {"running", "done"} else "✗"
    _banner(
        f"{status_icon}  PHASE RUN {result.status.upper()}",
        fields,
    )


def _resume_versioned_human_input(
    *,
    answer: str,
    project_root: Path,
    ext_dir: Path,
    squad_dir: Path,
    store,
    state: dict,
) -> None:
    from harness.config import get_full_resolved_config, load_config
    from harness.human_input import HumanInputPolicyError
    from harness.squad import SquadController
    from harness.squad_provider import SquadCliProvider

    try:
        decision = _active_versioned_decision(state)
    except (RecoveryInstructionError, ValueError) as exc:
        print(f"✗ Invalid persisted decision: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    if decision is None:
        print("✗ Active versioned decision is missing.", file=sys.stderr)
        raise SystemExit(1)

    from harness.phase_graph import load_workspace_phase_graph
    graph, ext_dir = load_workspace_phase_graph(project_root)
    config = load_config(project_root, squad_only=True)
    provider = SquadCliProvider(config)
    token_budget = 0
    max_iterations = 5
    try:
        full_config = get_full_resolved_config(project_root)
        analysis = full_config.get("analysis") or {}
        token_budget_k = int(analysis.get("token_budget_k") or 0)
        token_budget = token_budget_k * 1000 if token_budget_k else 0
        max_iterations = int(analysis.get("max_iterations") or 5)
    except Exception:
        pass
    controller = SquadController(
        provider=provider,
        state_store=store,
        phase_graph=graph,
        ext_dir=ext_dir,
        project_root=project_root,
        token_budget=token_budget,
        max_iterations=max_iterations,
        squad_dir=squad_dir,
        ignore_re=(state.get("published_re_context") or {}).get("status") == "ignored",
        implementation_targets=[
            str(value)
            for value in (state.get("implementation_targets") or [])
            if str(value).strip()
        ],
    )
    try:
        controller.resume_with_human_input(answer)
    except HumanInputPolicyError as exc:
        print(f"✗ Cannot resume decision: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    current = store.load()
    _note_spec_summary_next_printed()
    _banner(
        "HUMAN DECISION SUBMITTED",
        [
            ("Run ID", current.get("run_id", squad_dir.name)),
            ("Decision ID", decision["id"]),
            ("Answer", answer),
            ("Next", "echelon spec continue"),
        ],
    )


def _cmd_resume(
    args: list[str],
    project_root: Path,
    ext_dir: Path,
) -> None:
    """Provide user answers to an escalation-blocked squad run and continue it."""
    from harness.config import get_full_resolved_config, load_config
    from harness.blocked_decision import (
        ensure_blocked_decision,
        mark_blocked_decision_resolved,
    )
    from harness.squad import SquadController
    from harness.squad_provider import SquadCliProvider
    from harness.squad_state import SquadStateStore
    from echelon.spec_lifecycle import (
        PhaseAExecutionLock,
        SpecLifecycleLocked,
        SpecRunExecutionLock,
    )
    from threading import get_ident
    from uuid import uuid4

    answer = " ".join(args).strip()
    if not answer:
        print(
            "Usage: echelon spec resume \"<your answers>\"\n"
            "  Answer the escalation questions shown when the run was blocked.\n"
            "  Example: echelon spec resume \"Q1: yes, I own the IP  Q2: 13+  Q3: short missions\"",
            file=sys.stderr,
        )
        sys.exit(1)

    squad_dir = _find_current_run_dir(project_root)
    if squad_dir is None:
        print("✗ No active squad run found.", file=sys.stderr)
        print("  Start a run with: echelon spec run \"<task>\"", file=sys.stderr)
        sys.exit(1)

    store = SquadStateStore(squad_dir)
    operation_id = f"resume-{os.getpid()}-{get_ident()}-{uuid4().hex}"
    try:
        with PhaseAExecutionLock.acquire(project_root, operation_id):
            with SpecRunExecutionLock.acquire(squad_dir, operation_id):
                state = store.load()
                _register_spec_summary_run(
                    project_root,
                    squad_dir,
                    mode=state.get("autonomy_mode") or state.get("mode", "semi"),
                    message=state.get("user_message", ""),
                    implementation_targets=state.get("implementation_targets") or (),
                )
                raw_decision = state.get("blocked_decision")
                if (
                    isinstance(raw_decision, dict)
                    and raw_decision.get("schema_version") in {2, 3}
                ):
                    if state.get("status") != "blocked":
                        print(
                            "✗ Run is not blocked "
                            f"(status: {state.get('status', 'unknown')}).",
                            file=sys.stderr,
                        )
                        print("  Nothing to resume.", file=sys.stderr)
                        raise SystemExit(1)
                    _resume_versioned_human_input(
                        answer=answer,
                        project_root=project_root,
                        ext_dir=ext_dir,
                        squad_dir=squad_dir,
                        store=store,
                        state=state,
                    )
                    return
    except SpecLifecycleLocked as exc:
        print(
            f"✗ Cannot resume while execution lease is owned by {exc.operation_id}.",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc

    if state.get("status") != "blocked":
        print(
            f"✗ Run is not blocked (status: {state.get('status', 'unknown')}).",
            file=sys.stderr,
        )
        print("  Nothing to resume.", file=sys.stderr)
        sys.exit(1)

    # A cap is not an ordinary clarification gate.  Do not record a free-text
    # answer as though it authorised progress: a concrete issue decision must
    # become controller-owned state first.
    if str(state.get("blocked_reason") or "") == "phase_dispatch_limit" and _phase_dispatch_limit_phase(state):
        print(
            "✗ A phase-dispatch cap cannot be cleared by a free-text resume answer.\n"
            "  Resolve the first unresolved issue instead:\n"
            '  echelon spec resolve ISS-<n> "<project decision>"',
            file=sys.stderr,
        )
        sys.exit(1)

    escalation_q = state.get("escalation_question")
    if not escalation_q:
        print(
            "✗ Run is blocked but no escalation question found.\n"
            "  Use: echelon spec run --next-phase <phase-id>  to recover manually",
            file=sys.stderr,
        )
        sys.exit(1)
    ensure_blocked_decision(state)
    _enforce_project_config_compatibility(project_root)

    _banner("RESUMING SQUAD RUN", [
        ("Run ID", state.get("run_id", "?")),
        ("Phase", state.get("phase", "?")),
        ("Reason", state.get("blocked_reason", "?")),
        ("Question", escalation_q.strip()),
        ("Your answer", answer),
    ])

    _preserve_active_spec_context(project_root, state)

    # Capture blocked state before clearing — needed to decide resume path and
    # to reopen the retry window after an explicitly authorized cap recovery.
    blocked_phase = state.get("phase", "")
    blocked_reason = str(state.get("blocked_reason") or "").strip()
    capped_phase = _phase_dispatch_limit_phase(state)

    # Write user's answer to staging so the re-dispatched phase can read it.
    staging_dir = Path(state.get("staging_dir", str(squad_dir / "staging")))
    clarifications_file = staging_dir / "user-clarifications.md"
    clarifications_file.write_text(
        f"# User Clarifications\n\n"
        f"> Provided via `echelon spec resume` in response to the escalation block.\n\n"
        f"## Questions asked\n\n"
        f"{escalation_q}\n\n"
        f"## User answers\n\n"
        f"{answer}\n"
    )

    # A clarification is authoritative control-plane input, not merely prompt
    # prose. Persist its generated, immutable policy before any resumed agent
    # dispatch and route stale Phase A artifacts through a narrow WHAT repair.
    from echelon.feature_policy import (
        derive_feature_policy,
        persist_feature_policy,
        reconcile_feature_artifacts,
    )

    blocked_decision = state.get("blocked_decision")
    decision_id = (
        str(blocked_decision.get("id") or "").strip()
        if isinstance(blocked_decision, dict)
        else ""
    ) or f"clarification-{state.get('run_id') or squad_dir.name}"
    feature_policy = derive_feature_policy(answer, decision_id=decision_id)
    persist_feature_policy(staging_dir, feature_policy)
    state["feature_policy"] = feature_policy
    policy_spec_ref = str(state.get("spec_dir") or "").strip()
    policy_spec_dir = Path(policy_spec_ref) if policy_spec_ref else None
    if policy_spec_dir is not None and not policy_spec_dir.is_absolute():
        policy_spec_dir = project_root / policy_spec_dir
    if policy_spec_dir is not None:
        try:
            policy_spec_dir = policy_spec_dir.resolve()
            policy_spec_dir.relative_to(project_root.resolve())
        except ValueError:
            policy_spec_dir = None
    if policy_spec_dir is not None and policy_spec_dir.is_dir():
        reconciliation = reconcile_feature_artifacts(policy_spec_dir, feature_policy)
        state["feature_policy_reconciliation"] = reconciliation
        if reconciliation["requires_repair"]:
            state["phase"] = "phase1-what"

    from echelon.context_builder import build_run_context
    context_result = build_run_context(project_root, squad_dir, user_request=str(state.get("user_message") or ""))
    state["context_dir"] = str(context_result.context_dir)

    from harness.phase_graph import load_workspace_phase_graph
    graph, ext_dir = load_workspace_phase_graph(project_root)
    raw_options = state.get("escalation_options")
    has_structured_options = isinstance(raw_options, list) and bool(raw_options)
    selected_option = None
    if has_structured_options:
        selected_option = _resolve_escalation_option(answer, raw_options)
        if selected_option is None:
            print(
                "✗ Your answer does not match any executable escalation option.\n"
                "  Answer with A/B/C, the option id, or the option label shown in the escalation.",
                file=sys.stderr,
            )
            sys.exit(1)
    if selected_option:
        next_phase = str(selected_option.get("next_phase") or "").strip()
        if next_phase:
            valid_phases = set(graph.all_phase_ids())
            if next_phase not in valid_phases:
                print(
                    f"✗ Escalation option {selected_option.get('id') or selected_option.get('label')!r} "
                    f"routes to {next_phase!r}, which is not an executable phase.",
                    file=sys.stderr,
                )
                sys.exit(1)
            state["phase"] = next_phase
        option_id = str(selected_option.get("id") or selected_option.get("label") or "").strip()
        if option_id:
            state["escalation_selected_option"] = option_id

    resumed_phase = str(state.get("phase", "")).strip()
    mark_blocked_decision_resolved(
        state,
        answer=answer,
        selected_option=selected_option,
        resumed_phase=resumed_phase,
    )

    # Clear the blocked state.
    state["escalation_question"] = None
    state["escalation_resolved"] = True
    state["escalation_resolver"] = "user"
    state["blocked_reason"] = None
    state["status"] = "running"
    store.save(state)

    # terminal-blocked is a TERMINAL_PHASE in the squad controller — running the
    # controller from there is always a silent no-op that returns "done" immediately.
    # Instead, record the answer and tell the user to run `echelon spec continue`.
    if blocked_phase == "terminal-blocked":
        _banner("SQUAD RESUMED", [
            ("answer", (answer[:60] + "…") if len(answer) > 60 else answer),
            ("status", "unblocked — answer recorded"),
            ("next", "continuing"),
            ("note", "delegating to echelon spec continue"),
            ("artifacts", str(squad_dir)),
        ])
        _cmd_continue([], project_root=project_root, ext_dir=ext_dir)
        return

    # Re-run from the current phase (same mode, same task).
    config = load_config(project_root, squad_only=True)
    provider = SquadCliProvider(config)
    token_budget = 0
    max_iterations = 5
    try:
        _full = get_full_resolved_config(project_root)
        _analysis = _full.get("analysis") or {}
        _k = int(_analysis.get("token_budget_k") or 0)
        token_budget = _k * 1000 if _k else 0
        max_iterations = int(_analysis.get("max_iterations") or 5)
    except Exception:
        pass

    controller = SquadController(
        provider=provider,
        state_store=store,
        phase_graph=graph,
        ext_dir=ext_dir,
        project_root=project_root,
        token_budget=token_budget,
        max_iterations=max_iterations,
        squad_dir=squad_dir,
        ignore_re=(state.get("published_re_context") or {}).get("status") == "ignored",
        implementation_targets=[
            str(value)
            for value in (state.get("implementation_targets") or [])
            if str(value).strip()
        ],
    )
    result = controller.run(
        user_message=state.get("user_message", ""),
        mode=state.get("autonomy_mode") or state.get("mode", "semi"),
    )

    _print_squad_summary(
        project_root,
        squad_dir,
        result,
        mode=state.get("autonomy_mode") or state.get("mode", "semi"),
        message=state.get("user_message", ""),
        implementation_targets=[
            str(value)
            for value in (state.get("implementation_targets") or [])
            if str(value).strip()
        ],
        command="echelon spec resume",
    )


def _resolve_escalation_option(answer: str, options: object) -> dict | None:
    """Resolve a user resume answer against structured escalation options.

    Supports A/B/C positional answers, exact option ids, and exact labels.
    Missing or text-only escalations are rejected by _cmd_resume before this helper.
    """
    if not isinstance(options, list) or not options:
        return None

    normalized = answer.strip().lower()
    if not normalized:
        return None

    first_token = normalized.split(maxsplit=1)[0].strip(").:-—–")
    positional: dict[str, dict] = {}
    by_id_or_label: dict[str, dict] = {}

    for index, raw in enumerate(options):
        if not isinstance(raw, dict):
            continue
        letter = chr(ord("a") + index)
        positional[letter] = raw
        option_id = str(raw.get("id") or "").strip().lower()
        label = str(raw.get("label") or "").strip().lower()
        if option_id:
            by_id_or_label[option_id] = raw
        if label:
            by_id_or_label[label] = raw

    return positional.get(first_token) or by_id_or_label.get(normalized)


def _preserve_active_spec_context(project_root: Path, state: dict) -> None:
    """Record the current spec branch/dir before resume re-dispatch.

    CARTOGRAPHER may be re-dispatched after a human escalation. Resume must
    continue using the same Echelon-owned branch and full spec directory.
    """
    if state.get("phase") != "phase1-what":
        return

    # Phase A bootstrap reserves a run-local target path before CARTOGRAPHER
    # authors the first spec. A directory alone is therefore not evidence of
    # an existing spec; the resume flag is set only once spec.md exists.
    state.pop("cartographer_resume_existing_spec", None)

    spec_dir = state.get("spec_dir")
    if spec_dir:
        candidate = Path(spec_dir)
        if not candidate.is_absolute():
            candidate = project_root / candidate
        if (candidate / "spec.md").is_file():
            state["cartographer_resume_existing_spec"] = True
            return

    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception:
        return

    branch = result.stdout.strip()
    if not branch or not _is_spec_feature_branch(branch):
        return

    candidate = project_root / "specs" / branch
    if not (candidate / "spec.md").is_file():
        return

    state["spec_id"] = state.get("spec_id") or branch
    state["spec_dir"] = str(candidate.relative_to(project_root))
    state["feature_branch"] = state.get("feature_branch") or branch
    state["cartographer_resume_existing_spec"] = True


def _is_spec_feature_branch(branch: str) -> bool:
    import re
    return re.match(r"^[0-9]{3,4}-[A-Za-z0-9][A-Za-z0-9._-]*$", branch) is not None


# ── Skill resolution ──────────────────────────────────────────────────────

from harness.skill_loader import (
    find_skill as _find_skill_impl,
    build_skill_prompt as _build_skill_prompt_impl,
)
from harness.prosaic_prompt_loader import (
    ProsaicPromptLoadError,
    ProsaicPromptLoader,
    RenderedProsaicCommand,
)
from harness.config import load_config
from harness.llm_provider import AICodingCliProvider
from harness.llm_tool_policy import build_opencode_skill_command
from harness.provider_capability import ProviderCapability


def _find_skill(skill_base: str, project_dir: Path, cli: str) -> Path | None:
    return _find_skill_impl(skill_base, project_dir, cli)


def _build_prompt(skill_path: Path, arguments: str) -> str:
    return _build_skill_prompt_impl(skill_path, arguments)


def _load_prosaic_command(
    skill_base: str, arguments: str, project_dir: Path
) -> RenderedProsaicCommand | None:
    """Load an installer-owned neutral command when the project has one."""
    try:
        artifact = ProsaicPromptLoader(project_dir).load_command(skill_base)
    except ProsaicPromptLoadError as exc:
        print(f"echelon: {exc}", file=sys.stderr)
        sys.exit(1)
    if artifact is None:
        return None
    return ProsaicPromptLoader.render_command(artifact, arguments)


def _load_cli_config(project_dir: Path):
    return load_config(project_dir, squad_only=True)


def _capability_label(capability: ProviderCapability) -> str:
    if capability == ProviderCapability.ARTIFACT:
        return "artifact"
    if capability == ProviderCapability.BUILD:
        return "build"
    return str(capability)


def _capability_article(capability: ProviderCapability) -> str:
    return "an" if capability == ProviderCapability.ARTIFACT else "a"


def _supported_capability_label(capabilities: frozenset[ProviderCapability]) -> str:
    if capabilities == frozenset({ProviderCapability.ARTIFACT}):
        return "artifact work only"
    if capabilities == frozenset({ProviderCapability.BUILD}):
        return "build work only"
    if capabilities == frozenset({ProviderCapability.ARTIFACT, ProviderCapability.BUILD}):
        return "artifact and build work"
    if not capabilities:
        return "no Echelon work"
    values = ", ".join(sorted(_capability_label(item) for item in capabilities))
    return f"{values} work"


def _require_provider_capability(
    command_name: str,
    required: ProviderCapability,
    *,
    project_dir: Path | None = None,
) -> None:
    root = project_dir or Path.cwd()
    try:
        config = _load_cli_config(root)
    except Exception:
        # Capability gates must not mask existing config/preflight diagnostics.
        # If config cannot load, let the command's normal validation report it.
        return
    provider = AICodingCliProvider(config)
    if required in provider.capabilities:
        return
    provider_name = config.llm.cli
    supported = _supported_capability_label(provider.capabilities)
    required_label = _capability_label(required)
    article = _capability_article(required)
    print(
        f'Provider "{provider_name}" supports {supported}.\n'
        f'Command "{command_name}" requires {required_label} capability.\n'
        f"Choose {article} {required_label}-capable provider.",
        file=sys.stderr,
    )
    sys.exit(2)


def _skill_required_capability(command: str) -> ProviderCapability:
    if command in {"build", "review", "codegen"}:
        return ProviderCapability.BUILD
    return ProviderCapability.ARTIFACT


def _skill_not_found_msg(skill_base: str, project_dir: Path, cli: str) -> str:
    del cli
    return (
        f"echelon: command prose '{skill_base}' not found.\n"
        "Expected at:\n"
        f"  {project_dir / '.echelon' / 'prosaic' / 'commands' / f'{skill_base}.md'}\n"
        "Run: echelon workspace migrate-to-prosaic"
    )


def _dispatch_skill_command(command: str, args: list[str]) -> None:
    skill_base = SKILL_MAP[command]
    arguments = " ".join(args)

    if not arguments:
        print(f"echelon {command}: missing arguments\n", file=sys.stderr)
        print(USAGE)
        sys.exit(1)

    if command == "codegen":
        _require_codegen_installation()

    project_dir = Path.cwd()
    _require_provider_capability(
        f"echelon {command}",
        _skill_required_capability(command),
        project_dir=project_dir,
    )
    try:
        config = _load_cli_config(project_dir)
    except Exception as exc:
        print(f"echelon {command}: invalid LLM tool policy: {exc}", file=sys.stderr)
        sys.exit(1)
    cli = config.llm.cli

    prosaic_command = _load_prosaic_command(skill_base, arguments, project_dir)
    prompt = prosaic_command.prompt if prosaic_command is not None else None
    if prompt is None:
        skill_path = _find_skill(skill_base, project_dir, cli)
        if skill_path is None:
            print(_skill_not_found_msg(skill_base, project_dir, cli), file=sys.stderr)
            sys.exit(1)

    if cli == "opencode" and prompt is None:
        bin_ = shutil.which(cli) or cli
        cmd = build_opencode_skill_command(
            bin_, skill_base, arguments, config.llm.tool_policy
        )
        result = subprocess.run(cmd, cwd=str(project_dir))
        sys.exit(result.returncode)

    if prompt is None:
        prompt = _build_prompt(skill_path, arguments)
    metadata = None
    if prosaic_command is not None:
        metadata = {"prompt_metadata": prosaic_command.frontmatter}
    elif command == "build":
        metadata = {"canonical_task_execution": True}
    result = AICodingCliProvider(config).run_prompt_result(
        str(project_dir), prompt, request_metadata=metadata
    )
    sys.exit(result.exit_code)


def _require_codegen_installation() -> None:
    """Require the installer-owned codegen launcher before SOAR dispatch."""
    launcher = Path(sys.executable).with_name("codegen")
    if launcher.is_file() and os.access(launcher, os.X_OK):
        return
    print(
        "echelon codegen: the optional SOAR/codegen pipeline is not installed.\n"
        "Install it with: bash scripts/install.sh --with-codegen",
        file=sys.stderr,
    )
    sys.exit(2)


# ── RE lifecycle and publication subcommands ────────────────────────────────

_RE_PHASE_LABELS = {
    "re-extract-0-preflight": "preflight",
    "re-extract-1-analyze": "source analysis",
    "re-extract-2-specify": "domain specification and workspace synthesis",
    "re-extract-3-verify": "coverage verification",
    "re-extract-4-expand": "coverage expansion",
    "re-extract-5-validate": "semantic validation",
    "re-extract-6-checklist": "extraction checklist",
    "re-extract-7-constitute": "constitution generation",
}


def _read_re_summary_state(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _re_source_progress(state: dict) -> str:
    raw_states = state.get("re_source_states")
    source_states = raw_states if isinstance(raw_states, dict) else {}
    raw_order = state.get("re_source_order")
    ordered = (
        [value for value in raw_order if isinstance(value, str)]
        if isinstance(raw_order, list)
        else []
    )
    source_ids = list(
        dict.fromkeys(
            [*ordered, *(key for key in source_states if isinstance(key, str))]
        )
    )
    if not source_ids:
        return "not initialized"
    statuses = [
        str(source_states.get(source_id, {}).get("status") or "pending")
        if isinstance(source_states.get(source_id), dict)
        else "pending"
        for source_id in source_ids
    ]
    passed = statuses.count("passed")
    summary = f"{passed}/{len(source_ids)} passed"
    partial = statuses.count("partial_quality_debt")
    active = statuses.count("active")
    blocked = statuses.count("blocked")
    pending = statuses.count("pending")
    extras: list[str] = []
    if partial:
        extras.append(f"{partial} partial")
    if active:
        extras.append(f"{active} active")
    if blocked:
        extras.append(f"{blocked} blocked")
    if pending:
        extras.append(f"{pending} pending")
    return summary + (" · " + " · ".join(extras) if extras else "")


def _re_domain_count(run_re_dir: Path) -> str:
    architecture = _read_re_summary_state(
        run_re_dir / "workspace" / "architecture-map.json"
    )
    domains = architecture.get("domains")
    if not isinstance(domains, list):
        return "not available"
    return str(len(domains))


def _re_status_source_rows(run_re_dir: Path, state: dict) -> list[str]:
    """Render source-quality evidence without requiring callers to inspect JSON."""
    raw_states = state.get("re_source_states")
    source_states = raw_states if isinstance(raw_states, dict) else {}
    raw_order = state.get("re_source_order")
    ordered = (
        [source_id for source_id in raw_order if isinstance(source_id, str)]
        if isinstance(raw_order, list)
        else []
    )
    source_ids = list(
        dict.fromkeys([*ordered, *(key for key in source_states if isinstance(key, str))])
    )
    rows: list[str] = []
    for source_id in source_ids:
        raw_source_state = source_states.get(source_id)
        source_state = raw_source_state if isinstance(raw_source_state, dict) else {}
        report = _read_re_summary_state(
            run_re_dir / "quality" / "sources" / f"{source_id}.json"
        )
        status = str(source_state.get("status") or "pending").replace(
            "_", " "
        )
        coverage = report.get("coverage_pct", source_state.get("coverage_pct"))
        coverage_text = f"{coverage:.1f}%" if isinstance(coverage, (int, float)) else "—"
        details = [coverage_text]
        orphan_paths = report.get("orphan_paths")
        if isinstance(orphan_paths, list) and orphan_paths:
            details.append(f"{len(orphan_paths)} uncovered")
        domain_failures = report.get("domain_failures")
        if isinstance(domain_failures, list) and domain_failures:
            count = len(domain_failures)
            details.append(f"{count} incomplete domain" + ("s" if count != 1 else ""))
        rows.append(f"  {source_id:<38} {status:<22} {' · '.join(details)}")
    return rows


def _re_status_display_state(state: dict, controller_status: str) -> dict:
    """Project stale active sources into the controller's terminal state."""
    if controller_status != "blocked":
        return state
    raw_states = state.get("re_source_states")
    if not isinstance(raw_states, dict):
        return state
    source_states: dict[str, object] = {}
    for source_id, raw_source_state in raw_states.items():
        if (
            isinstance(raw_source_state, dict)
            and raw_source_state.get("status") == "active"
        ):
            source_states[source_id] = {**raw_source_state, "status": "blocked"}
        else:
            source_states[source_id] = raw_source_state
    return {**state, "re_source_states": source_states}


def _format_re_token_budget(state: dict, outer: dict) -> str:
    usage = state.get("re_token_usage")
    profile = state.get("re_execution_profile")
    if not isinstance(profile, dict):
        profile = outer.get("re_execution_profile")
    limit = profile.get("hard_token_limit") if isinstance(profile, dict) else None
    if not isinstance(usage, int) or not isinstance(limit, int) or limit <= 0:
        return "not available"
    return f"{usage / 1_000_000:.1f}M / {limit / 1_000_000:.1f}M ({usage / limit:.0%})"


def _detect_re_engine_for_cli(run_dir: Path) -> str:
    """Detect a pinned engine and preserve recorded identity in refusal errors."""
    from harness.re_v2.run_store import ReV2RunStoreError, detect_re_engine

    try:
        return detect_re_engine(run_dir)
    except ReV2RunStoreError as exc:
        manifest_path = run_dir.resolve() / "v2" / "run.json"
        recorded: tuple[str, str] | None = None
        if manifest_path.is_file() and not manifest_path.is_symlink():
            try:
                raw = json.loads(manifest_path.read_bytes())
                if isinstance(raw, dict):
                    engine = raw.get("engine")
                    protocol = raw.get("engine_protocol_version")
                    if (
                        isinstance(engine, str)
                        and engine
                        and isinstance(protocol, str)
                        and protocol
                    ):
                        recorded = (engine, protocol)
            except (OSError, ValueError, TypeError):
                pass
        if recorded is not None:
            raise ValueError(
                "unsupported pinned RE engine/protocol "
                f"{recorded[0]!r}/{recorded[1]!r}; install an Echelon version "
                "compatible with the recorded protocol"
            ) from exc
        raise ValueError(str(exc)) from exc


def _cmd_re_status(args: list[str]) -> None:
    """Show the active RE controller state and every source's quality outcome."""
    from harness.re_lifecycle import resolve_current_re_run
    from harness.re_v2.status import ReV2StatusError, render_v2_status

    as_json = args == ["--json"]
    if args and not as_json:
        print("Usage: echelon re status [--json]", file=sys.stderr)
        raise SystemExit(2)
    run_dir = resolve_current_re_run(Path.cwd())
    if run_dir is None:
        print("echelon re status: no active RE run", file=sys.stderr)
        raise SystemExit(2)
    try:
        engine = _detect_re_engine_for_cli(run_dir)
        if engine == "v2":
            print(render_v2_status(run_dir, as_json=as_json), end="")
            return
    except (ReV2StatusError, ValueError) as exc:
        print(f"echelon re status: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    if as_json:
        print(
            "echelon re status: --json is available only for pinned v2 runs",
            file=sys.stderr,
        )
        raise SystemExit(2)
    run_re_dir = run_dir / "re"
    outer = _read_re_summary_state(run_dir / "state.json")
    inner = _read_re_summary_state(run_re_dir / "state.json")
    if not inner:
        print(f"echelon re status: missing controller state for {run_dir.name}", file=sys.stderr)
        raise SystemExit(2)
    controller_status = str(inner.get("status") or "unknown")
    display_inner = _re_status_display_state(inner, controller_status)
    lifecycle_status = str(outer.get("status") or "unknown")
    phase = str(inner.get("phase") or outer.get("phase") or "unknown")
    phase_label = _RE_PHASE_LABELS.get(phase, "current controller phase")
    source_rows = _re_status_source_rows(run_re_dir, display_inner)
    raw_source_states = display_inner.get("re_source_states")
    source_states = raw_source_states if isinstance(raw_source_states, dict) else {}
    source_statuses = [
        value.get("status")
        for value in source_states.values()
        if isinstance(value, dict)
    ]
    active_source_count = sum(status == "active" for status in source_statuses)
    partial_count = sum(
        status == "partial_quality_debt" for status in source_statuses
    )
    nonpassed_count = sum(status != "passed" for status in source_statuses)
    finalized_partial = (
        outer.get("finalized_partial") is True
        and outer.get("golddigger_status") == "partial"
    )
    publication_complete = outer.get("publication_complete") is True
    synthesis_status = (
        "complete"
        if inner.get("re_workspace_synthesis_complete") is True
        else "incomplete (accepted partial debt)"
        if finalized_partial
        else "pending"
    )
    fields = [
        ("run", run_dir.name),
        ("controller", controller_status),
        ("lifecycle", lifecycle_status),
        ("phase", f"{phase} — {phase_label}"),
        ("policy", str(outer.get("re_policy") or "unknown")),
        ("sources", _re_source_progress(display_inner)),
        ("synthesis", synthesis_status),
        ("token budget", _format_re_token_budget(inner, outer)),
    ]
    if finalized_partial:
        raw_finalization = outer.get("re_partial_finalization")
        finalization = raw_finalization if isinstance(raw_finalization, dict) else {}
        semantic_count = int(finalization.get("semantic_failure_count") or 0)
        raw_semantic_sources = finalization.get("semantic_failure_sources")
        semantic_sources = (
            [value for value in raw_semantic_sources if isinstance(value, str)]
            if isinstance(raw_semantic_sources, list)
            else []
        )
        fields.append(
            (
                "semantic debt",
                f"{semantic_count} finding{'s' if semantic_count != 1 else ''} across "
                + (", ".join(semantic_sources) or "no named source"),
            )
        )
    if publication_complete:
        fields.append(
            (
                "publication",
                f"generation {int(outer.get('generation') or 0)} "
                f"({outer.get('golddigger_status') or 'unknown'})",
            )
        )
    if controller_status == "blocked":
        fields.extend(
            (
                ("blocked reason", str(inner.get("blocked_reason") or "unknown")),
                ("detail", str(inner.get("re_agent_result_detail") or "not available")),
            )
        )
    _banner(
        "RE STATUS",
        fields,
        subtitle="Live controller state and deterministic source-quality outcomes.",
    )
    if lifecycle_status != controller_status:
        print(
            "\nNote: outer lifecycle state is "
            f"{lifecycle_status} while the live controller state is {controller_status}."
        )
    if source_rows:
        print("\nSource quality")
        print("  source                                 status                 coverage / debt")
        print("  ─────────────────────────────────────  ─────────────────────  ─────────────────")
        print("\n".join(source_rows))
    if finalized_partial and publication_complete:
        action = (
            "This run is finalized and published as partial; debt remains explicit. "
            "No continuation is required."
        )
    elif finalized_partial:
        action = (
            f"This run is finalized as partial. Publish it with `echelon re publish "
            f"{run_dir.name} --allow-partial`."
        )
    elif controller_status == "in_progress":
        action = "Do not start another continuation while the controller is active."
    elif controller_status == "blocked":
        action = (
            "The controller is stopped at the blocker shown above. Resolve it if "
            "needed, then run `echelon re continue`."
        )
    elif active_source_count:
        action = "Do not start another continuation while a source is active."
    elif partial_count:
        action = (
            f"{partial_count} source(s) have partial quality debt; this is not a full-quality outcome. "
            "Raise --re-max-inner above the current budget, then continue."
        )
    elif nonpassed_count:
        action = (
            f"{nonpassed_count} source(s) have not passed the source-quality gate. "
            "Continue the current RE run."
        )
    else:
        action = "All sources have passed the controller's source-quality gate."
    print(f"\nNext action: {action}")


def _print_re_continue_summary(
    project_root: Path,
    *,
    re_max_inner: int | None,
) -> None:
    """Print controller-owned RE orientation before any provider dispatch."""
    from harness.re_lifecycle import resolve_current_re_run

    run_dir = resolve_current_re_run(project_root)
    if run_dir is None:
        return
    run_re_dir = run_dir / "re"
    outer = _read_re_summary_state(run_dir / "state.json")
    inner = _read_re_summary_state(run_re_dir / "state.json")
    status = str(outer.get("status") or inner.get("status") or "unknown")
    phase = str(inner.get("phase") or outer.get("phase") or "unknown")
    phase_label = _RE_PHASE_LABELS.get(phase, "current controller phase")
    coverage = inner.get("coverage_threshold")
    resolution = inner.get("resolution_threshold")
    quality = (
        f"coverage {coverage}% · resolution {resolution}%"
        if isinstance(coverage, int) and isinstance(resolution, int)
        else "not initialized"
    )
    raw_budgets = inner.get("re_source_budgets")
    source_budget = (
        raw_budgets.get("max_source_cycles")
        if isinstance(raw_budgets, dict)
        else None
    )
    budget_candidates = (
        re_max_inner,
        outer.get("re_max_inner"),
        inner.get("re_max_inner"),
        source_budget,
    )
    effective_budgets = [
        value
        for value in budget_candidates
        if isinstance(value, int) and not isinstance(value, bool) and value > 0
    ]
    effective_budget = max(effective_budgets, default=None)

    fields = [
        ("run", run_dir.name),
        ("status", f"{status} → continuing"),
        ("phase", f"{phase} — {phase_label}"),
        ("policy", str(outer.get("re_policy") or "unknown")),
        ("sources", _re_source_progress(inner)),
        ("domains", _re_domain_count(run_re_dir)),
        (
            "synthesis",
            "complete"
            if inner.get("re_workspace_synthesis_complete") is True
            else "pending",
        ),
        ("quality", quality),
    ]
    if effective_budget:
        fields.append(("repair budget", f"{effective_budget} source-local attempts"))
    fields.append(("artifacts", str(run_re_dir)))
    _banner(
        "RE CONTINUE",
        fields,
        subtitle="Controller state before provider dispatch.",
    )


def _parse_re_lifecycle_options(
    args: list[str],
    *,
    allow_policy: bool,
    allow_reset: bool,
    allow_budget_overrides: bool = False,
) -> tuple[str, int | None, bool, bool, str | None, int | None, int | None, list[str]]:
    policy = "changed"
    re_max_inner: int | None = None
    reset = False
    no_reuse = False
    profile: str | None = None
    token_limit: int | None = None
    time_limit_minutes: int | None = None
    positional: list[str] = []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--re-policy" and allow_policy:
            if index + 1 >= len(args):
                raise ValueError("--re-policy requires a policy name")
            policy = args[index + 1].strip()
            index += 2
        elif arg.startswith("--re-policy=") and allow_policy:
            policy = arg.split("=", 1)[1].strip()
            index += 1
        elif arg == "--profile" and allow_policy:
            if index + 1 >= len(args):
                raise ValueError("--profile requires fast, balanced, or high")
            profile = args[index + 1].strip()
            index += 2
        elif arg.startswith("--profile=") and allow_policy:
            profile = arg.split("=", 1)[1].strip()
            index += 1
        elif arg in {"--re-token-limit", "--re-time-limit-minutes"} and (
            allow_policy or allow_budget_overrides
        ):
            if index + 1 >= len(args):
                raise ValueError(f"{arg} requires a positive integer")
            try:
                value = int(args[index + 1])
            except ValueError as exc:
                raise ValueError(f"{arg} requires a positive integer") from exc
            if arg == "--re-token-limit":
                token_limit = value
            else:
                time_limit_minutes = value
            index += 2
        elif arg.startswith("--re-token-limit=") and (
            allow_policy or allow_budget_overrides
        ):
            token_limit = int(arg.split("=", 1)[1])
            index += 1
        elif arg.startswith("--re-time-limit-minutes=") and (
            allow_policy or allow_budget_overrides
        ):
            time_limit_minutes = int(arg.split("=", 1)[1])
            index += 1
        elif arg == "--re-max-inner":
            if index + 1 >= len(args):
                raise ValueError("--re-max-inner requires a positive integer")
            try:
                re_max_inner = int(args[index + 1])
            except ValueError as exc:
                raise ValueError("--re-max-inner requires a positive integer") from exc
            index += 2
        elif arg.startswith("--re-max-inner="):
            try:
                re_max_inner = int(arg.split("=", 1)[1])
            except ValueError as exc:
                raise ValueError("--re-max-inner requires a positive integer") from exc
            index += 1
        elif arg == "--reset" and allow_reset:
            reset = True
            index += 1
        elif arg == "--no-reuse" and allow_policy:
            no_reuse = True
            index += 1
        elif arg.startswith("-"):
            raise ValueError(f"unknown option {arg!r}")
        else:
            positional.append(arg)
            index += 1
    if re_max_inner is not None and re_max_inner < 1:
        raise ValueError("--re-max-inner requires a positive integer")
    if token_limit is not None and token_limit < 1:
        raise ValueError("--re-token-limit requires a positive integer")
    if time_limit_minutes is not None and time_limit_minutes < 1:
        raise ValueError("--re-time-limit-minutes requires a positive integer")
    return (
        policy,
        re_max_inner,
        reset,
        no_reuse,
        profile,
        token_limit,
        time_limit_minutes,
        positional,
    )


def _re_lifecycle_controller(project_root: Path):
    from harness.config import load_config
    from harness.re_lifecycle import ReLifecycleController
    from harness.squad_provider import SquadCliProvider

    runtime_root, prosaic_subagents_dir = _installed_re_runtime_or_exit(project_root)
    config = load_config(project_root, squad_only=True)
    return ReLifecycleController(
        project_root=project_root,
        extension_root=runtime_root,
        prosaic_subagents_dir=prosaic_subagents_dir,
        provider_factory=lambda: SquadCliProvider(config),
    )


def _print_re_lifecycle_result(result: object) -> None:
    status = str(getattr(result, "status", "failed"))
    run_id = str(getattr(result, "run_id", ""))
    generation = int(getattr(result, "generation", 0) or 0)
    no_work = bool(getattr(result, "no_work", False))
    if status == "done":
        if no_work:
            print(f"RE publication is current (generation {generation}); no agent work required.")
            _banner(
                "RE FINAL STATE — CURRENT",
                [("run", run_id or "(not created)"), ("generation", str(generation))],
                subtitle="No reverse-engineering work was required.",
            )
        else:
            print(
                f"RE run {run_id} complete; publication is pending. "
                f"Publish explicitly with: echelon re publish {run_id}"
            )
            _banner(
                "RE FINAL STATE — COMPLETE",
                [
                    ("run", run_id),
                    ("generation", str(generation)),
                    ("next step", f"echelon re publish {run_id}"),
                ],
                subtitle="Reverse engineering completed; publication is pending.",
            )
        return
    reason = str(getattr(result, "blocked_reason", "RE lifecycle failed"))
    print(f"RE run {run_id or '(not created)'} blocked: {reason}", file=sys.stderr)
    detail = str(getattr(result, "blocked_detail", "")).strip()
    fields = [
        ("run", run_id or "(not created)"),
        ("status", "blocked"),
        ("reason", reason),
    ]
    phase = str(getattr(result, "phase", "")).strip()
    if phase:
        fields.append(("phase", phase))
    missing_workspace_artifacts = _workspace_synthesis_missing_artifacts(detail)
    if missing_workspace_artifacts:
        fields.extend(
            [
                (
                    "validation",
                    "Agent reported DONE, but deterministic artifact validation failed.",
                ),
                (
                    "missing artifacts",
                    _format_missing_workspace_artifacts(missing_workspace_artifacts),
                ),
                ("retry", "echelon re continue"),
            ]
        )
    else:
        if detail:
            fields.append(("detail", _summarize_re_lifecycle_detail(detail)))
        fields.append(("action", "Resolve the blocker, then continue or resume the run."))
    _banner(
        "RE FINAL STATE — BLOCKED",
        fields,
        subtitle="No further provider work was run after the controller gate failed.",
        file=sys.stderr,
    )
    raise SystemExit(1)


def _summarize_re_lifecycle_detail(detail: str) -> str:
    """Keep the terminal's final RE state legible when a gate reports many paths."""
    compact = " ".join(detail.split())
    return compact if len(compact) <= 300 else compact[:297] + "…"


def _workspace_synthesis_missing_artifacts(detail: str) -> list[str]:
    prefix = "workspace synthesis has missing or empty artifacts: "
    if not detail.startswith(prefix):
        return []
    return [
        path.strip()
        for path in detail.removeprefix(prefix).split(",")
        if path.strip()
    ]


def _format_missing_workspace_artifacts(paths: list[str]) -> str:
    displayed = paths[:10]
    heading = f"{len(paths)} required artifacts are absent."
    remainder = len(paths) - len(displayed)
    suffix = f"… and {remainder} more" if remainder else ""
    return "\n".join([heading, *displayed, suffix]).strip()


def _parse_re_creation_engine_options(
    args: list[str],
) -> tuple[str, bool, str, list[str]]:
    """Remove additive v2 creation switches without changing the v1 parser."""
    engine = "v1"
    engine_seen = False
    shadow = False
    goal = "baseline"
    goal_seen = False
    remaining: list[str] = []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--engine":
            if engine_seen or index + 1 >= len(args):
                raise ValueError("--engine requires exactly one of v1 or v2")
            engine = args[index + 1].strip()
            engine_seen = True
            index += 2
        elif arg.startswith("--engine="):
            if engine_seen:
                raise ValueError("--engine requires exactly one of v1 or v2")
            engine = arg.split("=", 1)[1].strip()
            engine_seen = True
            index += 1
        elif arg == "--shadow":
            if shadow:
                raise ValueError("--shadow may be supplied only once")
            shadow = True
            index += 1
        elif arg == "--goal":
            if goal_seen or index + 1 >= len(args):
                raise ValueError("--goal requires exactly one of baseline or inventory")
            goal = args[index + 1].strip()
            goal_seen = True
            index += 2
        elif arg.startswith("--goal="):
            if goal_seen:
                raise ValueError("--goal requires exactly one of baseline or inventory")
            goal = arg.split("=", 1)[1].strip()
            goal_seen = True
            index += 1
        else:
            remaining.append(arg)
            index += 1
    if engine not in {"v1", "v2"}:
        raise ValueError("--engine requires v1 or v2")
    if shadow and engine != "v2":
        raise ValueError("--shadow is valid only with --engine v2")
    if goal not in {"baseline", "inventory"}:
        raise ValueError("--goal requires baseline or inventory")
    if goal_seen and engine != "v2":
        raise ValueError("--goal is valid only with --engine v2")
    return engine, shadow, goal, remaining


def _re_v2_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _re_v2_snapshot_root(project_root: Path) -> Path:
    configured = os.environ.get("ECHELON_HOME")
    base = Path(configured).expanduser() if configured else Path.home() / ".echelon"
    destination = (base / "re-v2" / "snapshots").resolve(strict=False)
    workspace = project_root.resolve()
    if destination == workspace or destination.is_relative_to(workspace):
        raise ValueError("RE v2 snapshot storage must be outside the source workspace")
    return destination


def _re_v2_partition_manifest_id(
    workspace_manifest: object, snapshot: object
) -> str:
    from harness.re_v2.snapshot import load_snapshot_manifest
    from harness.re_v2.workspace_snapshot import composite_partition_manifest_id

    snapshot_manifest = load_snapshot_manifest(snapshot)
    components = snapshot_manifest.components
    if components is None:
        raise ValueError("RE v2 creation requires a composite source snapshot")
    expected = sorted(
        (
            str(getattr(source, "id")),
            str(getattr(source, "git_role")),
            str(getattr(source, "path")),
        )
        for source in getattr(workspace_manifest, "sources")
    )
    observed = sorted(
        (
            component.source_id,
            component.git_role,
            component.workspace_path,
        )
        for component in components
    )
    if expected != observed:
        raise ValueError(
            "workspace source set does not match the committed RE v2 snapshot"
        )
    return composite_partition_manifest_id(snapshot_manifest)


def _new_re_v2_run_id(project_root: Path) -> str:
    runs = project_root.resolve() / "runs"
    base = datetime.now(timezone.utc).strftime("re-%Y%m%d-%H%M%S-%f")
    for index in range(1_000):
        candidate = base if index == 0 else f"{base}-{index}"
        if not (runs / candidate).exists() and not (runs / candidate).is_symlink():
            return candidate
    raise ValueError("cannot allocate a unique RE v2 run id")


def _activate_re_v2_run(project_root: Path, run_id: str) -> None:
    runs = project_root.resolve() / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    gitignore = runs / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("*/state.json\n*/*.tmp\n.current*\n", encoding="utf-8")
    marker = runs / ".current-re"
    temporary = runs / f".current-re.{os.getpid()}.tmp"
    try:
        temporary.write_text(run_id + "\n", encoding="utf-8")
        os.replace(temporary, marker)
    finally:
        temporary.unlink(missing_ok=True)


def _re_v22_agent_bytes(project_root: Path) -> bytes | None:
    path = (
        project_root.resolve()
        / ".echelon"
        / "prosaic"
        / "subagents"
        / "echelon.re-baseliner.md"
    )
    if not path.exists() and not path.is_symlink():
        return None
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"unsafe echelon.re-baseliner authority: {path}")
    try:
        before = path.stat(follow_symlinks=False)
        payload = path.read_bytes()
        after = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise ValueError(f"cannot read echelon.re-baseliner authority: {exc}") from exc
    if (
        (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        or not payload
    ):
        raise ValueError("echelon.re-baseliner authority changed while reading")
    try:
        payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ValueError("echelon.re-baseliner authority must be UTF-8") from exc
    return payload


def _re_v22_implementation_digest(*modules: object) -> str:
    from harness.re_v2.protocol_22.authorities import implementation_closure_digest

    files: dict[str, bytes] = {}
    for module in modules:
        module_name = str(getattr(module, "__name__", ""))
        module_path_value = getattr(module, "__file__", None)
        if not module_name or not isinstance(module_path_value, str):
            raise ValueError("protocol-2.2 implementation authority has no source file")
        module_path = Path(module_path_value)
        if module_path.suffix == ".pyc" and module_path.with_suffix(".py").is_file():
            module_path = module_path.with_suffix(".py")
        if module_path.is_symlink() or not module_path.is_file():
            raise ValueError(
                f"protocol-2.2 implementation authority is unavailable: {module_name}"
            )
        files[module_name.replace(".", "/") + ".py"] = module_path.read_bytes()
    return implementation_closure_digest(files)


def _re_v22_partition_authorities() -> object:
    import harness.re_domain_manifest as domain_manifest_module
    import harness.re_v2.protocol_22.partition as partition_module
    from harness.re_v2.protocol_22.partition import (
        ImplementationAuthorityV1,
        PartitionAuthoritiesV1,
    )

    return PartitionAuthoritiesV1(
        partitioner=ImplementationAuthorityV1(
            id="existing-domain-partitioner",
            version="5",
            implementation_digest=_re_v22_implementation_digest(
                partition_module,
                domain_manifest_module,
            ),
        ),
        ownership_policy=ImplementationAuthorityV1(
            id="explicit-domain-ownership",
            version="1",
            implementation_digest=_re_v22_implementation_digest(
                partition_module
            ),
        ),
    )


def _re_schema2_installed_registry(
    agent: bytes | None,
    *,
    provider_mode: str = "api",
) -> tuple[object, bytes | None, dict[str, bytes]]:
    import harness.re_domain_manifest as domain_manifest_module
    import harness.re_v2.protocol_22.baseline as baseline_module
    import harness.re_v2.protocol_22.cli_provider as cli_provider_module
    import harness.re_v2.protocol_22.context as context_module
    import harness.re_v2.protocol_22.controller as controller_module
    import harness.re_v2.protocol_22.evidence as evidence_module
    import harness.re_v2.protocol_22.execution as execution_module
    import harness.re_v2.protocol_22.inventory as inventory_module
    import harness.re_v2.protocol_22.partition as partition_module
    import harness.re_v2.protocol_22.provider as provider_module
    import harness.re_v2.protocol_22.response_schemas as response_schema_module
    import harness.re_v2.protocol_22.runtime as runtime_module
    from harness.re_v2.canonical import content_digest
    from harness.re_v2.protocol_22.authorities import InstalledAuthorityRegistry
    from harness.re_v2.protocol_22.executors import (
        BOUNDED_API_ADAPTER_ID,
        COMPACT_RENDERER_ID,
        COMPACT_VERIFIER_ID,
        CONSERVATIVE_TOKENIZER_ID,
        DISPATCH_CALCULATOR_ID,
        IN_PROCESS_ADAPTER_ID,
        IN_PROCESS_CALCULATOR_ID,
        OPENAI_USAGE_NORMALIZER_ID,
        SHARED_AI_CLI_ADAPTER_ID,
        SHARED_PROVIDER_USAGE_NORMALIZER_ID,
        ZERO_USAGE_NORMALIZER_ID,
    )
    from harness.re_v2.protocol_22.response_schemas import (
        canonical_response_schema_bytes,
    )

    schemas = {
        kind: canonical_response_schema_bytes(kind)
        for kind in ("domain-baseline", "source-overview")
    }
    registry = InstalledAuthorityRegistry(
        executor_implementations={
            BOUNDED_API_ADAPTER_ID: _re_v22_implementation_digest(provider_module),
            SHARED_AI_CLI_ADAPTER_ID: _re_v22_implementation_digest(
                cli_provider_module
            ),
            IN_PROCESS_ADAPTER_ID: _re_v22_implementation_digest(
                controller_module,
                execution_module,
                inventory_module,
                evidence_module,
                context_module,
                runtime_module,
            ),
        },
        renderer_implementations={
            COMPACT_RENDERER_ID: _re_v22_implementation_digest(
                provider_module,
                response_schema_module,
            ),
        },
        tokenizer_implementations={
            CONSERVATIVE_TOKENIZER_ID: _re_v22_implementation_digest(
                provider_module
            ),
        },
        calculator_implementations={
            DISPATCH_CALCULATOR_ID: (
                _re_v22_implementation_digest(
                    provider_module,
                    cli_provider_module,
                )
                if provider_mode == "cli"
                else _re_v22_implementation_digest(provider_module)
            ),
            IN_PROCESS_CALCULATOR_ID: _re_v22_implementation_digest(
                execution_module
            ),
        },
        normalizer_implementations={
            ZERO_USAGE_NORMALIZER_ID: _re_v22_implementation_digest(execution_module),
            OPENAI_USAGE_NORMALIZER_ID: _re_v22_implementation_digest(
                provider_module
            ),
            SHARED_PROVIDER_USAGE_NORMALIZER_ID: _re_v22_implementation_digest(
                provider_module
            ),
        },
        verifier_implementations={
            COMPACT_VERIFIER_ID: _re_v22_implementation_digest(baseline_module),
        },
        partitioner_implementations={
            "existing-domain-partitioner": _re_v22_implementation_digest(
                partition_module,
                domain_manifest_module,
            ),
        },
        ownership_implementations={
            "explicit-domain-ownership": _re_v22_implementation_digest(
                partition_module
            ),
        },
        agent_contracts=(
            {"echelon.re-baseliner": content_digest(agent)}
            if agent is not None
            else {}
        ),
        response_schemas={
            kind: content_digest(payload) for kind, payload in schemas.items()
        },
    )
    return registry, agent, schemas


def _re_v22_installed_registry(
    project_root: Path,
) -> tuple[object, bytes | None, dict[str, bytes]]:
    """Build legacy protocol-2.2 authority from its raw Markdown contract."""
    return _re_schema2_installed_registry(_re_v22_agent_bytes(project_root))


@dataclass(frozen=True, slots=True)
class _Protocol22Creation:
    snapshot: object
    manifest: object
    inputs: object


def _prepare_re_v22_creation(
    workspace_root: Path,
    *,
    goal: str,
    token_limit: int | None,
    time_limit_minutes: int | None,
    engine_protocol_version: str | None = None,
) -> _Protocol22Creation:
    from harness.config import load_config
    from harness.re_v2 import RE_V2_PROTOCOL
    from harness.re_v2.canonical import canonical_json_bytes, content_digest
    from harness.re_v2.model import RE_V2_SCHEMA_2_PROTOCOLS
    from harness.re_v2.protocol_22.authorities import validate_installed_authorities
    from harness.re_v2.protocol_22.executors import resolve_executor_catalog
    from harness.re_v2.protocol_22.graph import build_protocol_22_graph
    from harness.re_v2.protocol_22.inputs import Protocol22InputSet
    from harness.re_v2.protocol_22.model import (
        BudgetPolicyV2,
        CatalogReferenceV1,
        RunManifestV2,
    )
    from harness.re_v2.protocol_22.partition import build_workspace_partition_catalog
    from harness.re_v2.protocol_22.policies import build_compact_v1_policy_catalog
    from harness.re_v2.protocol_22.provider import canonical_prosaic_agent_bytes
    from harness.re_v2.workspace_snapshot import capture_workspace_snapshot

    selected_protocol = (
        RE_V2_PROTOCOL
        if engine_protocol_version is None
        else engine_protocol_version
    )
    if selected_protocol not in RE_V2_SCHEMA_2_PROTOCOLS:
        raise ValueError(
            f"unsupported schema-2 RE protocol: {selected_protocol!r}"
        )

    workspace_manifest = discover_workspace(workspace_root)
    snapshot = capture_workspace_snapshot(
        workspace_root,
        workspace_manifest.sources,
        _re_v2_snapshot_root(workspace_root),
    )
    partition_authorities = _re_v22_partition_authorities()
    workspace_partition = build_workspace_partition_catalog(
        snapshot,
        workspace_manifest,
        partition_authorities,
    )
    artifact_policy = build_compact_v1_policy_catalog()
    if selected_protocol == "2.2":
        registry, agent, schemas = _re_v22_installed_registry(workspace_root)
    else:
        agent = None
        if goal == "baseline":
            try:
                artifact = ProsaicPromptLoader(workspace_root).load_subagent(
                    "echelon.re-baseliner"
                )
            except ProsaicPromptLoadError as exc:
                raise ValueError(str(exc)) from exc
            if artifact is None:
                raise ValueError(
                    "installed Prosaic agent echelon.re-baseliner is missing; run "
                    "`echelon workspace migrate-to-prosaic` before starting RE"
                )
            agent = canonical_prosaic_agent_bytes(artifact)
        registry, agent, schemas = _re_schema2_installed_registry(
            agent,
            provider_mode="cli",
        )
    if (
        registry.require("partitioner", partition_authorities.partitioner.id)
        != partition_authorities.partitioner.implementation_digest
        or registry.require(
            "ownership", partition_authorities.ownership_policy.id
        )
        != partition_authorities.ownership_policy.implementation_digest
    ):
        raise ValueError("protocol-2.2 partition authority changed during preflight")
    try:
        config = load_config(workspace_root, squad_only=True)
    except Exception as exc:
        if exc.__class__.__module__ != "harness.config":
            raise
        raise ValueError(str(exc)) from exc
    executor_contract = resolve_executor_catalog(
        config,
        goal,
        registry,
        provider_mode="api" if selected_protocol == "2.2" else "cli",
    )
    mismatches = validate_installed_authorities(executor_contract, registry)
    if mismatches:
        details = ", ".join(
            f"{item.authority_kind}:{item.authority_id}" for item in mismatches
        )
        raise ValueError(f"protocol-2.2 installed authority mismatch: {details}")
    immutable_objects: dict[str, bytes] = {}
    if goal == "baseline":
        if agent is None:
            raise ValueError("missing installed agent authority echelon.re-baseliner")
        immutable_objects[content_digest(agent)] = agent
        for payload in schemas.values():
            immutable_objects[content_digest(payload)] = payload
    inputs = Protocol22InputSet(
        workspace_partition=workspace_partition,
        artifact_policy=artifact_policy,
        executor_contract=executor_contract,
        immutable_objects=immutable_objects,
    )
    run_id = _new_re_v2_run_id(workspace_root)
    partition_manifest_id = _re_v2_partition_manifest_id(
        workspace_manifest,
        snapshot,
    )
    manifest = RunManifestV2(
        schema_version=2,
        engine="re-v2",
        engine_protocol_version=selected_protocol,
        run_id=run_id,
        created_at=_re_v2_now(),
        source_snapshot_id=snapshot.snapshot_id,
        source_snapshot_kind="workspace-git-composite",
        partition_manifest_id=partition_manifest_id,
        workspace_partition_catalog=CatalogReferenceV1(
            object_hash=content_digest(
                canonical_json_bytes(workspace_partition.to_json_dict())
            ),
            relative_path="workspace-partition.json",
        ),
        artifact_policy_catalog=CatalogReferenceV1(
            object_hash=content_digest(
                canonical_json_bytes(artifact_policy.to_json_dict())
            ),
            relative_path="artifact-policy.json",
        ),
        executor_contract_catalog=CatalogReferenceV1(
            object_hash=content_digest(
                canonical_json_bytes(executor_contract.to_json_dict())
            ),
            relative_path="executor-contract.json",
        ),
        requested_goals=(goal,),
        initial_budget_policy=BudgetPolicyV2.for_goal(
            goal,
            token_limit=token_limit if token_limit is not None else 5_000_000,
            active_ms_limit=(
                time_limit_minutes * 60_000
                if time_limit_minutes is not None
                else 180 * 60_000
            ),
        ),
        parent_run_id=None,
    )
    build_protocol_22_graph(manifest, inputs)
    return _Protocol22Creation(snapshot, manifest, inputs)


class _DeterministicInventoryCertifier:
    """Controller-owned verifier for the exact deterministic L0 document."""

    verifier_id = "deterministic-inventory-verifier"
    verifier_version = "v1"

    def __init__(self, object_store: object, snapshot: object) -> None:
        self._object_store = object_store
        self._snapshot = snapshot

    def certify(self, candidate: object, work_item: object) -> object:
        from harness.re_v2.canonical import canonical_json_bytes
        from harness.re_v2.ledger import CertificationDecision
        from harness.re_v2.model import (
            ArtifactReceipt,
            CertificationKey,
            CertificationReceipt,
        )

        payload_root = Path(getattr(candidate, "payload_path"))
        artifact_hash = self._object_store.put_tree(payload_root)
        diagnostics = self._diagnostics(candidate, work_item, payload_root)
        certified_at = _re_v2_now()
        certification = CertificationReceipt(
            certification_key=CertificationKey(
                artifact_hash=artifact_hash,
                verifier_id=self.verifier_id,
                verifier_version=self.verifier_version,
                source_snapshot_id=getattr(work_item, "output_key").source_snapshot_id,
                audit_epoch_id=None,
            ),
            candidate_id=str(getattr(candidate, "candidate_id")),
            work_item_id=str(getattr(work_item, "work_item_id")),
            verdict="rejected" if diagnostics else "accepted",
            normalized_diagnostics=diagnostics,
            evidence_references=("inventory.json",),
            scope_verified=not diagnostics,
            certified_at=certified_at,
        )
        if diagnostics:
            return CertificationDecision(certification, None)
        artifact = ArtifactReceipt(
            artifact_key=getattr(work_item, "output_key"),
            artifact_hash=artifact_hash,
            certification_id=certification.identity,
            candidate_id=str(getattr(candidate, "candidate_id")),
            work_item_id=str(getattr(work_item, "work_item_id")),
            accepted_at=certified_at,
        )
        return CertificationDecision(certification, artifact)

    def _diagnostics(
        self, candidate: object, work_item: object, payload_root: Path
    ) -> tuple[str, ...]:
        from harness.re_v2.canonical import canonical_json_bytes

        observation = getattr(candidate, "observation")
        if (
            observation.provider_name != "deterministic-inventory"
            or observation.exit_code != 0
            or observation.timed_out
            or observation.output_truncated
            or not observation.result_contract_valid
        ):
            return ("deterministic-transport-invalid",)
        try:
            entries = sorted(path.name for path in payload_root.iterdir())
            document_path = payload_root / "inventory.json"
            payload = document_path.read_bytes()
            document = json.loads(payload)
            snapshot_manifest = json.loads(
                Path(getattr(self._snapshot, "manifest_path")).read_bytes()
            )
        except (OSError, ValueError, TypeError):
            return ("inventory-document-unreadable",)
        if entries != ["inventory.json"] or document_path.is_symlink() or not document_path.is_file():
            return ("inventory-output-scope-invalid",)
        try:
            if payload != canonical_json_bytes(document):
                return ("inventory-document-noncanonical",)
        except (TypeError, ValueError):
            return ("inventory-document-noncanonical",)
        expected_fields = {
            "artifact_kind",
            "dependency_hashes",
            "partition_manifest_id",
            "producer_protocol_version",
            "schema_version",
            "snapshot_entries",
            "source_snapshot_id",
            "work_item_id",
        }
        if not isinstance(document, dict) or set(document) != expected_fields:
            return ("inventory-document-schema-invalid",)
        expected_entries = [
            {
                "digest": item["digest"],
                "mode": int(item["mode"]) & ~0o222,
                "path": item["path"],
                "size": item["size"],
            }
            for item in snapshot_manifest.get("entries", [])
            if isinstance(item, dict)
        ]
        output_key = getattr(work_item, "output_key")
        expected = {
            "artifact_kind": output_key.artifact_kind,
            "dependency_hashes": list(getattr(work_item, "required_artifact_hashes")),
            "partition_manifest_id": output_key.partition_manifest_id,
            "producer_protocol_version": getattr(work_item, "producer_protocol_version"),
            "schema_version": 1,
            "snapshot_entries": sorted(expected_entries, key=lambda item: str(item["path"])),
            "source_snapshot_id": output_key.source_snapshot_id,
            "work_item_id": getattr(work_item, "work_item_id"),
        }
        return () if document == expected else ("inventory-evidence-mismatch",)


def _load_re_v2_snapshot(project_root: Path, manifest: object) -> object:
    from harness.re_v2.snapshot import CapturedSnapshot, validate_source_snapshot

    bundle = _re_v2_snapshot_root(project_root) / str(
        getattr(manifest, "source_snapshot_id")
    )
    snapshot = CapturedSnapshot(
        snapshot_id=str(getattr(manifest, "source_snapshot_id")),
        kind=getattr(manifest, "source_snapshot_kind"),
        read_root=bundle / "source",
        manifest_path=bundle / "manifest.json",
    )
    validate_source_snapshot(snapshot)
    return snapshot


def _reject_re_v22_provider_dispatch(*_args: object, **_kwargs: object) -> None:
    raise ValueError(
        "protocol 2.2 has unresolved provider work; direct provider dispatch "
        "is disabled—start a new protocol 2.3 run"
    )


def _re_v22_context(project_root: Path, run_dir: Path, manifest: object) -> object:
    from types import MappingProxyType, SimpleNamespace

    from harness.re_v2.canonical import canonical_json_bytes, content_digest
    from harness.re_v2.events import EventStore
    from harness.re_v2.ledger import ObjectStore
    from harness.re_v2.protocol_22.controller import accepted_dependencies_for
    from harness.re_v2.protocol_22.cli_provider import SquadCliBaselineExecutor
    from harness.re_v2.protocol_22.evidence import PinnedSnapshotReaderV1
    from harness.re_v2.protocol_22.events import PROTOCOL_22_EVENTS
    from harness.re_v2.protocol_22.execution import (
        DeterministicExecutionDependenciesV1,
        Protocol22ExecutionStore,
        ProviderExecutionDependenciesV1,
    )
    from harness.re_v2.protocol_22.graph import build_protocol_22_graph
    from harness.re_v2.protocol_22.inputs import load_protocol_22_inputs
    from harness.re_v2.protocol_22.ledger import Protocol22Ledger
    from harness.re_v2.protocol_22.model import (
        DeterministicInvocationInputV1,
        DeterministicInvocationV1,
        RunManifestV2,
    )
    from harness.re_v2.protocol_22.recovery import Protocol22RunContext
    from harness.re_v2.protocol_22.runtime import (
        ConservativeTokenizerV1,
        DeterministicRuntimeV1,
    )
    from harness.re_v2.run_store import ReV2Paths
    from harness.re_v2.snapshot import validate_source_snapshot

    if not isinstance(manifest, RunManifestV2):
        raise ValueError("protocol-2.2 context requires a schema-2 manifest")
    paths = ReV2Paths.for_run(run_dir)
    inputs = load_protocol_22_inputs(paths, manifest)
    graph = build_protocol_22_graph(manifest, inputs)
    objects = ObjectStore(paths.objects)
    if manifest.engine_protocol_version == "2.3":
        compact = next(
            (
                entry
                for entry in inputs.executor_contract.entries
                if entry.producer_family == "compact-baseline"
            ),
            None,
        )
        renderer = None if compact is None else compact.request_renderer
        pinned_agent = (
            None
            if renderer is None
            else objects.read_blob(renderer.agent_contract_hash)
        )
        registry, _agent, _schemas = _re_schema2_installed_registry(
            pinned_agent,
            provider_mode="cli",
        )
    else:
        registry, _agent, _schemas = _re_v22_installed_registry(project_root)
    snapshot = _load_re_v2_snapshot(project_root, manifest)
    snapshot_reader = PinnedSnapshotReaderV1(snapshot, inputs.workspace_partition)
    ledger = Protocol22Ledger(paths, objects)
    runtime = DeterministicRuntimeV1(inputs, snapshot_reader)
    context_ref: dict[str, object] = {}
    workspace_bytes = canonical_json_bytes(inputs.workspace_partition.to_json_dict())
    workspace_hash = content_digest(workspace_bytes)

    def dependencies_for(item: object, _attempt_kind: str) -> object:
        executor = inputs.executor_contract.entry_for(
            getattr(item, "producer_family")
        )
        context = context_ref["context"]
        accepted = accepted_dependencies_for(context, item)
        if executor.execution_mode in {"api", "cli"}:
            renderer = executor.request_renderer
            if renderer is None:
                raise ValueError("protocol-2.2 provider executor has no renderer")
            schema_hash = next(
                (
                    reference.schema_hash
                    for reference in renderer.response_schemas
                    if reference.artifact_kind
                    == getattr(getattr(item, "output_key"), "artifact_kind")
                ),
                None,
            )
            if schema_hash is None:
                raise ValueError("protocol-2.2 provider item has no response schema")
            return ProviderExecutionDependenciesV1(
                executor=executor,
                registry=registry,
                agent_bytes=objects.read_blob(renderer.agent_contract_hash),
                context_bytes=accepted.payload_for_role("context_bundle"),
                response_schema_bytes=objects.read_blob(schema_hash),
                tokenizer=(
                    ConservativeTokenizerV1.for_executor(executor)
                    if executor.execution_mode == "api"
                    else None
                ),
            )
        invocation_inputs = tuple(
            DeterministicInvocationInputV1(
                role=role,
                object_hash=accepted_artifact.artifact_hash,
            )
            for role, accepted_artifact in accepted.by_role.items()
        )
        uses_workspace_partition = set(accepted.by_role) == {"workspace_partition"}
        return DeterministicExecutionDependenciesV1(
            executor=executor,
            registry=registry,
            invocation=DeterministicInvocationV1(
                schema_version=1,
                producer_family=getattr(item, "producer_family"),
                output_key=getattr(item, "output_key"),
                artifact_policy_hash=getattr(
                    getattr(item, "output_key"), "layer_policy_hash"
                ),
                inputs=invocation_inputs,
            ),
            workspace_partition_hash=(
                workspace_hash if uses_workspace_partition else None
            ),
            referenced_objects=(
                {workspace_hash: workspace_bytes}
                if uses_workspace_partition
                else dict(accepted.payloads_by_hash)
            ),
        )

    producer_registrations = {
        entry.producer_family: runtime
        for entry in inputs.executor_contract.entries
        if entry.execution_mode == "in_process"
    }
    provider_registrations: dict[str, object] = {}
    for entry in inputs.executor_contract.entries:
        if entry.execution_mode == "api":
            provider_registrations[entry.adapter_id] = SimpleNamespace(
                execute=_reject_re_v22_provider_dispatch
            )
        elif entry.execution_mode == "cli":
            from harness.squad_provider import SquadCliProvider

            provider_registrations[entry.adapter_id] = (
                SquadCliBaselineExecutor(
                    entry,
                    provider_factory=lambda: SquadCliProvider(
                        _load_cli_config(project_root)
                    ),
                )
            )
    verifier_registrations = {
        entry.verifier.verifier_id: runtime
        for entry in inputs.executor_contract.entries
    }
    context = Protocol22RunContext(
        paths=paths,
        inputs=inputs,
        graph=graph,
        event_store=EventStore(paths, protocol=PROTOCOL_22_EVENTS),
        object_store=objects,
        ledger=ledger,
        execution_store=Protocol22ExecutionStore(paths, objects),
        installed_authorities=registry,
        dependencies_for=dependencies_for,
        executors=MappingProxyType(provider_registrations),
        producers=MappingProxyType(producer_registrations),
        verifiers=MappingProxyType(verifier_registrations),
        snapshot_validator=lambda: validate_source_snapshot(snapshot),
    )
    context_ref["context"] = context
    return context


def _re_v24_context(project_root: Path, run_dir: Path, manifest: object) -> object:
    from dataclasses import replace
    from types import MappingProxyType

    import harness.re_v2.protocol_24.artifacts as artifacts_module
    import harness.re_v2.protocol_24.controller as controller_module
    import harness.re_v2.protocol_24.runtime as runtime_module
    from harness.re_v2.canonical import canonical_json_bytes
    from harness.re_v2.events import EventStore
    from harness.re_v2.ledger import ObjectStore
    from harness.re_v2.protocol_22.controller import accepted_dependencies_for
    from harness.re_v2.protocol_22.cli_provider import SquadCliBaselineExecutor
    from harness.re_v2.protocol_22.evidence import PinnedSnapshotReaderV1
    from harness.re_v2.protocol_22.execution import (
        DeterministicExecutionDependenciesV1,
        Protocol22ExecutionStore,
        ProviderExecutionDependenciesV1,
    )
    from harness.re_v2.protocol_22.ledger import Protocol22Ledger
    from harness.re_v2.protocol_22.model import (
        DeterministicInvocationInputV1,
        DeterministicInvocationV1,
    )
    from harness.re_v2.protocol_22.recovery import Protocol22RunContext
    from harness.re_v2.protocol_22.runtime import DeterministicRuntimeV1
    from harness.re_v2.protocol_24.artifacts import (
        DEEPENER_AGENT_ID,
        DEEPENING_IN_PROCESS_ADAPTER_ID,
        DEEPENING_VERIFIER_ID,
    )
    from harness.re_v2.protocol_24.events import PROTOCOL_24_EVENTS
    from harness.re_v2.protocol_24.graph import (
        build_protocol_24_graph,
        reconstruct_adopted_parent_closure,
    )
    from harness.re_v2.protocol_24.inputs import load_protocol_24_inputs
    from harness.re_v2.protocol_24.model import RunManifestV3
    from harness.re_v2.protocol_24.runtime import Protocol24DeterministicRuntime
    from harness.re_v2.run_store import ReV2Paths
    from harness.re_v2.snapshot import validate_source_snapshot

    if not isinstance(manifest, RunManifestV3):
        raise ValueError("protocol-2.4 context requires a schema-3 manifest")
    paths = ReV2Paths.for_run(run_dir)
    inputs = load_protocol_24_inputs(paths, manifest)
    objects = ObjectStore(paths.objects)
    ledger = Protocol22Ledger(paths, objects)
    ledger_view = ledger.replay()
    accepted_parent = reconstruct_adopted_parent_closure(
        inputs.parent_authority_bundle,
        ledger_view,
    )
    graph = build_protocol_24_graph(manifest, inputs, accepted_parent)
    snapshot = _load_re_v2_snapshot(project_root, manifest)
    snapshot_reader = PinnedSnapshotReaderV1(
        snapshot,
        inputs.workspace_partition,
    )
    adopted_payloads = {
        (
            template.scope.source_id,
            template.scope.domain_key,
            template.layer,
            template.artifact_kind,
        ): objects.read_blob(artifact.artifact_hash)
        for template, artifact in accepted_parent.values()
    }
    inherited_runtime = DeterministicRuntimeV1(inputs, snapshot_reader)
    deepening_runtime = Protocol24DeterministicRuntime(
        inputs,
        snapshot_reader,
        adopted_payloads,
    )
    baseline_entry = inputs.executor_contract.entry_for("compact-baseline")
    baseline_renderer = baseline_entry.request_renderer
    if baseline_renderer is None:
        raise ValueError("protocol-2.4 parent provider renderer is missing")
    baseline_agent = objects.read_blob(baseline_renderer.agent_contract_hash)
    registry, _agent, _schemas = _re_schema2_installed_registry(
        baseline_agent,
        provider_mode="cli",
    )
    deepening_entry = inputs.executor_contract.entry_for("compact-deepening")
    deepening_renderer = deepening_entry.request_renderer
    if deepening_renderer is None:
        raise ValueError("protocol-2.4 deepening provider renderer is missing")
    deepener_hash = deepening_renderer.agent_contract_hash
    objects.read_blob(deepener_hash)
    implementation_digest = _re_v22_implementation_digest(
        artifacts_module,
        runtime_module,
        controller_module,
    )
    registry = replace(
        registry,
        executor_implementations={
            **dict(registry.executor_implementations),
            DEEPENING_IN_PROCESS_ADAPTER_ID: implementation_digest,
        },
        verifier_implementations={
            **dict(registry.verifier_implementations),
            DEEPENING_VERIFIER_ID: implementation_digest,
        },
        agent_contracts={
            **dict(registry.agent_contracts),
            DEEPENER_AGENT_ID: deepener_hash,
        },
    )
    context_ref: dict[str, object] = {}
    workspace_bytes = canonical_json_bytes(inputs.workspace_partition.to_json_dict())
    workspace_hash = inputs.workspace_partition.identity

    def dependencies_for(item: object, _attempt_kind: str) -> object:
        executor = inputs.executor_contract.entry_for(
            getattr(item, "producer_family")
        )
        accepted = accepted_dependencies_for(context_ref["context"], item)
        if executor.execution_mode in {"api", "cli"}:
            renderer = executor.request_renderer
            if renderer is None:
                raise ValueError("protocol-2.4 provider executor has no renderer")
            schema_hash = next(
                (
                    reference.schema_hash
                    for reference in renderer.response_schemas
                    if reference.artifact_kind
                    == getattr(getattr(item, "output_key"), "artifact_kind")
                ),
                None,
            )
            if schema_hash is None:
                raise ValueError("protocol-2.4 provider item has no response schema")
            return ProviderExecutionDependenciesV1(
                executor=executor,
                registry=registry,
                agent_bytes=objects.read_blob(renderer.agent_contract_hash),
                context_bytes=accepted.payload_for_role("context_bundle"),
                response_schema_bytes=objects.read_blob(schema_hash),
                tokenizer=None,
            )
        invocation_inputs = tuple(
            DeterministicInvocationInputV1(
                role=role,
                object_hash=accepted_artifact.artifact_hash,
            )
            for role, accepted_artifact in accepted.by_role.items()
        )
        uses_workspace_partition = set(accepted.by_role) == {"workspace_partition"}
        return DeterministicExecutionDependenciesV1(
            executor=executor,
            registry=registry,
            invocation=DeterministicInvocationV1(
                schema_version=1,
                producer_family=getattr(item, "producer_family"),
                output_key=getattr(item, "output_key"),
                artifact_policy_hash=getattr(
                    getattr(item, "output_key"), "layer_policy_hash"
                ),
                inputs=invocation_inputs,
            ),
            workspace_partition_hash=(
                workspace_hash if uses_workspace_partition else None
            ),
            referenced_objects=(
                {workspace_hash: workspace_bytes}
                if uses_workspace_partition
                else dict(accepted.payloads_by_hash)
            ),
        )

    l2_families = {
        "targeted-evidence-pack",
        "deepening-context-bundle",
        "deepening-source-root",
    }
    producers = {
        entry.producer_family: (
            deepening_runtime
            if entry.producer_family in l2_families
            else inherited_runtime
        )
        for entry in inputs.executor_contract.entries
        if entry.execution_mode == "in_process"
    }
    from harness.squad_provider import SquadCliProvider

    provider = SquadCliBaselineExecutor(
        deepening_entry,
        provider_factory=lambda: SquadCliProvider(_load_cli_config(project_root)),
    )
    verifiers = {
        entry.verifier.verifier_id: (
            deepening_runtime
            if entry.verifier.verifier_id == DEEPENING_VERIFIER_ID
            else inherited_runtime
        )
        for entry in inputs.executor_contract.entries
    }
    context = Protocol22RunContext(
        paths=paths,
        inputs=inputs,
        graph=graph,
        event_store=EventStore(paths, protocol=PROTOCOL_24_EVENTS),
        object_store=objects,
        ledger=ledger,
        execution_store=Protocol22ExecutionStore(paths, objects),
        installed_authorities=registry,
        dependencies_for=dependencies_for,
        executors=MappingProxyType({deepening_entry.adapter_id: provider}),
        producers=MappingProxyType(producers),
        verifiers=MappingProxyType(verifiers),
        snapshot_validator=lambda: validate_source_snapshot(snapshot),
    )
    context_ref["context"] = context
    return context


def _re_v2_context(project_root: Path, run_dir: Path) -> object:
    from harness.re_v2.candidates import CandidateStore
    from harness.re_v2.events import EventStore
    from harness.re_v2.ledger import Ledger, ObjectStore
    from harness.re_v2.planner import build_initial_inventory_graph
    from harness.re_v2.recovery import ReV2RunContext
    from harness.re_v2.run_store import ReV2Paths, load_run_manifest
    from harness.re_v2.status import validate_supported_v2_manifest

    manifest = load_run_manifest(run_dir)
    from harness.re_v2.protocol_22.model import RunManifestV2
    from harness.re_v2.protocol_24.model import RunManifestV3

    if isinstance(manifest, RunManifestV2):
        return _re_v22_context(project_root, run_dir, manifest)
    if isinstance(manifest, RunManifestV3):
        return _re_v24_context(project_root, run_dir, manifest)
    paths = ReV2Paths.for_run(run_dir)
    graph = build_initial_inventory_graph(
        manifest.source_snapshot_id, manifest.partition_manifest_id
    )
    validate_supported_v2_manifest(manifest, graph)
    snapshot = _load_re_v2_snapshot(project_root, manifest)
    objects = ObjectStore(paths.objects)
    ledger = Ledger(
        paths,
        objects,
        supported_verifiers={
            _DeterministicInventoryCertifier.verifier_id:
            _DeterministicInventoryCertifier.verifier_version
        },
    )
    return ReV2RunContext(
        paths=paths,
        snapshot=snapshot,
        graph=graph,
        event_store=EventStore(paths),
        object_store=objects,
        ledger=ledger,
        candidate_store=CandidateStore(paths),
        certifier=_DeterministicInventoryCertifier(objects, snapshot),
    )


def _run_re_v2_shadow(context: object) -> None:
    from harness.re_v2.protocol_22.recovery import Protocol22RunContext

    if isinstance(context, Protocol22RunContext):
        _run_re_v22_shadow(context)
        return
    from harness.re_v2.budget import evaluate_budget
    from harness.re_v2.planner import plan_next
    from harness.re_v2.recovery import recover_run
    from harness.re_v2.status import render_v2_status

    recovered = recover_run(context)
    budget = evaluate_budget(
        recovered.manifest.initial_budget_policy,
        recovered.events,
        now=_re_v2_now(),
    )
    decision = plan_next(
        context.graph,
        recovered.ledger,
        budget,
        requested_goals=recovered.manifest.requested_goals,
    )
    print("RE V2 — SHADOW PLAN")
    for template_id, explanation in decision.explanations.items():
        print(
            f"{template_id}: {explanation.action} "
            f"({explanation.reason_code}) — {explanation.reason}"
        )
    print(render_v2_status(context.paths.root.parent), end="")


def _run_re_v22_shadow(context: object) -> None:
    from harness.re_v2.canonical import content_digest
    from harness.re_v2.protocol_22.artifacts import AcceptedDependencySetV2
    from harness.re_v2.protocol_22.execution import (
        ProviderExecutionDependenciesV1,
        preview_dispatch_reservation,
    )
    from harness.re_v2.protocol_22.graph import (
        AcceptedArtifactV2,
        instantiate_ready_item,
    )
    from harness.re_v2.protocol_22.policies import policy_for
    from harness.re_v2.protocol_22.runtime import ConservativeTokenizerV1
    from harness.re_v2.protocol_22.status import render_protocol_22_status
    from harness.re_v2.run_store import load_run_manifest

    entries = {
        entry.producer_family: entry
        for entry in context.inputs.executor_contract.entries
    }
    provider_families = {
        entry.producer_family
        for entry in entries.values()
        if entry.execution_mode in {"api", "cli"}
    }
    provider_templates = tuple(
        template
        for template in context.graph.templates
        if template.producer_family in provider_families
    )
    deterministic_count = len(context.graph.templates) - len(provider_templates)
    maximum_shared_retries = sum(
        template.max_shared_retries for template in provider_templates
    )
    templates = {template.template_id: template for template in context.graph.templates}
    produced: dict[str, AcceptedArtifactV2] = {}
    payloads: dict[str, bytes] = {}
    exact_contexts: list[tuple[str, str | None, int]] = []
    bounded_contexts: list[tuple[str, str | None, int, int]] = []
    exact_provider_reservations: dict[str, object] = {}
    remaining = {template.template_id: template for template in context.graph.templates}
    while True:
        progressed = False
        for template_id, template in tuple(remaining.items()):
            if any(
                dependency not in produced
                for dependency in template.required_template_ids
            ):
                continue
            accepted_by_template = {
                dependency: produced[dependency]
                for dependency in template.required_template_ids
            }
            item = instantiate_ready_item(
                template,
                accepted_by_template,
                context.inputs,
            )
            by_role = {
                _re_v22_dependency_role(templates[dependency]): produced[dependency]
                for dependency in template.required_template_ids
            }
            accepted = AcceptedDependencySetV2(by_role, payloads)
            entry = entries[item.producer_family]
            if entry.execution_mode in {"api", "cli"}:
                renderer = entry.request_renderer
                if renderer is None:
                    raise ValueError("shadow provider executor has no renderer")
                schema_hash = next(
                    reference.schema_hash
                    for reference in renderer.response_schemas
                    if reference.artifact_kind == item.output_key.artifact_kind
                )
                dependencies = ProviderExecutionDependenciesV1(
                    executor=entry,
                    registry=context.installed_authorities,
                    agent_bytes=context.object_store.read_blob(
                        renderer.agent_contract_hash
                    ),
                    context_bytes=accepted.payload_for_role("context_bundle"),
                    response_schema_bytes=context.object_store.read_blob(schema_hash),
                    tokenizer=(
                        ConservativeTokenizerV1.for_executor(entry)
                        if entry.execution_mode == "api"
                        else None
                    ),
                )
                exact_provider_reservations[template.template_id] = (
                    preview_dispatch_reservation(
                        item,
                        "initial_generation",
                        dependencies,
                    ).reservation
                )
                del remaining[template_id]
                progressed = True
                continue
            payload = context.producers[item.producer_family].produce(item, accepted)
            artifact_hash = content_digest(payload)
            produced[template.template_id] = AcceptedArtifactV2(
                item.output_key.identity,
                artifact_hash,
            )
            payloads[artifact_hash] = payload
            if template.artifact_kind.endswith("context-bundle"):
                exact_contexts.append(
                    (
                        template.scope.source_id,
                        template.scope.domain_key,
                        len(payload),
                    )
                )
            del remaining[template_id]
            progressed = True
        if not progressed:
            break
    for template in remaining.values():
        if template.artifact_kind != "source-overview-context-bundle":
            continue
        policy = policy_for(
            context.inputs.artifact_policy,
            template.layer,
            template.artifact_kind,
        )
        byte_bound = min(
            value
            for value in (
                policy.max_canonical_json_bytes,
                policy.max_context_bundle_bytes,
            )
            if value is not None
        )
        token_bound = policy.max_conservative_input_tokens or byte_bound
        bounded_contexts.append(
            (
                template.scope.source_id,
                template.scope.domain_key,
                byte_bound,
                token_bound,
            )
        )

    initial_tokens = 0
    initial_active_ms = 0
    retry_tokens = 0
    retry_active_ms = 0
    for template in context.graph.templates:
        entry = entries[template.producer_family]
        initial_active_ms += entry.limits.max_active_ms_per_dispatch
        if entry.execution_mode not in {"api", "cli"}:
            continue
        context_limit = entry.limits.provider_context_tokens
        hard_tokens = entry.limits.max_billable_tokens_per_dispatch
        if context_limit is not None:
            hard_tokens = min(hard_tokens, context_limit)
        exact = exact_provider_reservations.get(template.template_id)
        initial_tokens += (
            exact.billable_tokens if exact is not None else hard_tokens
        )
        retry_tokens += template.max_shared_retries * hard_tokens
        retry_active_ms += (
            template.max_shared_retries
            * entry.limits.max_active_ms_per_dispatch
        )

    manifest = load_run_manifest(context.paths.root.parent)
    print(
        f"RE V2 — PROTOCOL {manifest.engine_protocol_version} SHADOW PLAN"
    )
    print(f"deterministic initial dispatches: {deterministic_count}")
    print(f"provider initial dispatches: {len(provider_templates)}")
    print(f"maximum shared-retry dispatches: {maximum_shared_retries}")
    for source_id, domain_key, byte_count in sorted(
        exact_contexts,
        key=lambda value: (value[0], value[1] or ""),
    ):
        scope = f"{source_id}/{domain_key}" if domain_key else source_id
        print(
            "context exact: "
            f"scope={scope} canonical_bytes={byte_count} "
            f"conservative_input_tokens={byte_count}"
        )
    for source_id, domain_key, byte_bound, token_bound in sorted(
        bounded_contexts,
        key=lambda value: (value[0], value[1] or ""),
    ):
        scope = f"{source_id}/{domain_key}" if domain_key else source_id
        print(
            "context worst-case bound: "
            f"scope={scope} canonical_bytes<={byte_bound} "
            f"conservative_input_tokens<={token_bound}"
        )
    for entry in sorted(
        (
            value
            for value in entries.values()
            if value.execution_mode in {"api", "cli"}
        ),
        key=lambda value: value.producer_family,
    ):
        print(
            "per-dispatch hard limits: "
            f"executor={entry.adapter_id} "
            f"context_tokens={entry.limits.provider_context_tokens} "
            f"completion_tokens={entry.limits.max_completion_tokens_per_call} "
            f"billable_tokens={entry.limits.max_billable_tokens_per_dispatch} "
            f"active_ms={entry.limits.max_active_ms_per_dispatch}"
        )
    print(
        "whole-run initial reservation: "
        f"tokens={initial_tokens} active_ms={initial_active_ms}"
    )
    print(
        "whole-run shared-retry reservation: "
        f"tokens={retry_tokens} active_ms={retry_active_ms}"
    )
    token_limit = manifest.initial_budget_policy.token_limit
    active_limit = manifest.initial_budget_policy.active_ms_limit
    print(
        "authorized ceilings: "
        f"tokens={token_limit if token_limit is not None else 'unlimited'} "
        f"active_ms={active_limit if active_limit is not None else 'unlimited'}"
    )
    insufficient: list[str] = []
    if token_limit is not None and token_limit < initial_tokens + retry_tokens:
        insufficient.append("tokens")
    if active_limit is not None and active_limit < initial_active_ms + retry_active_ms:
        insufficient.append("active_ms")
    if insufficient:
        print(
            "warning: authorized ceilings cannot cover the whole-run worst case "
            f"({', '.join(insufficient)})"
        )
    else:
        print("authorization: ceilings cover the whole-run worst case")
    print("provider requests issued: 0")
    print(render_protocol_22_status(context.paths.root.parent, context=context), end="")


def _re_v22_dependency_role(template: object) -> str:
    kind = str(getattr(template, "artifact_kind"))
    domain_key = getattr(getattr(template, "scope"), "domain_key")
    static = {
        "source-inventory": "source_inventory",
        "source-partition": "source_partition",
        "source-evidence-pack": "source_evidence_pack",
        "domain-inventory": "domain_inventory",
        "domain-evidence-pack": "domain_evidence_pack",
        "domain-context-bundle": "context_bundle",
        "source-overview-context-bundle": "context_bundle",
        "source-overview": "source_overview",
    }
    if kind in static:
        return static[kind]
    if kind == "domain-baseline" and domain_key is not None:
        return f"domain:{domain_key}"
    raise ValueError(f"unsupported protocol-2.2 dependency role: {kind}")


def _run_re_v2_live(context: object) -> None:
    from harness.re_v2.protocol_22.recovery import Protocol22RunContext

    if isinstance(context, Protocol22RunContext):
        from harness.re_v2.protocol_24.model import RunManifestV3
        from harness.re_v2.run_store import load_run_manifest

        manifest = load_run_manifest(context.paths.root.parent)
        if isinstance(manifest, RunManifestV3):
            from harness.re_v2.protocol_24.controller import Protocol24Controller

            result = Protocol24Controller(context).run_until_stopped()
            print("RE V2 — PROTOCOL 2.4")
            print(f"state: {result.status}")
        else:
            from harness.re_v2.protocol_22.controller import Protocol22Controller
            from harness.re_v2.protocol_22.status import render_protocol_22_status

            Protocol22Controller(context).run_until_stopped()
            print(
                render_protocol_22_status(
                    context.paths.root.parent,
                    context=context,
                ),
                end="",
            )
        return
    from harness.re_v2.controller import ReV2Controller
    from harness.re_v2.status import render_v2_status

    ReV2Controller(context).run_until_stopped()
    print(render_v2_status(context.paths.root.parent), end="")


def _run_re_v2_create(
    project_root: Path,
    *,
    token_limit: int | None,
    time_limit_minutes: int | None,
    shadow: bool,
    goal: str,
) -> None:
    from harness.re_v2.protocol_22.inputs import create_protocol_22_run_store

    if goal not in {"baseline", "inventory"}:
        raise ValueError("protocol-2.2 goal must be baseline or inventory")
    workspace_root = project_root.resolve()
    prepared = _prepare_re_v22_creation(
        workspace_root,
        goal=goal,
        token_limit=token_limit,
        time_limit_minutes=time_limit_minutes,
    )
    run_id = str(getattr(prepared.manifest, "run_id"))
    run_dir = workspace_root / "runs" / run_id
    create_protocol_22_run_store(
        run_dir,
        prepared.manifest,
        prepared.inputs,
    )
    _activate_re_v2_run(workspace_root, run_id)
    context = _re_v2_context(workspace_root, run_dir)
    if shadow:
        _run_re_v2_shadow(context)
    else:
        _run_re_v2_live(context)


def _re_v2_is_paused(events: tuple[object, ...]) -> bool:
    paused = False
    for event in events:
        if getattr(event, "type") == "run_paused":
            paused = True
        elif getattr(event, "type") == "run_resumed":
            paused = False
    return paused


def _run_re_v2_continue(
    run_dir: Path,
    *,
    token_limit: int | None,
    time_limit_minutes: int | None,
) -> None:
    from harness.re_v2.protocol_22.recovery import Protocol22RunContext

    project_root = run_dir.resolve().parent.parent
    context = _re_v2_context(project_root, run_dir)
    if isinstance(context, Protocol22RunContext):
        _run_re_v22_continue(
            context,
            token_limit=token_limit,
            time_limit_minutes=time_limit_minutes,
        )
        return
    from harness.re_v2.budget import (
        BudgetDimension,
        authorize_resource_increase,
        evaluate_budget,
    )
    from harness.re_v2.recovery import recover_run

    recovered = recover_run(context)
    terminal_types = {"run_completed", "run_finalized_partial", "run_failed"}
    if recovered.events and recovered.events[-1].type in terminal_types:
        if token_limit is not None or time_limit_minutes is not None:
            raise ValueError("terminal v2 runs cannot receive budget authorization")
        _run_re_v2_live(context)
        return
    paused = _re_v2_is_paused(recovered.events)
    requested = (
        (BudgetDimension.TOKENS, token_limit),
        (
            BudgetDimension.ACTIVE_MS,
            time_limit_minutes * 60_000
            if time_limit_minutes is not None
            else None,
        ),
    )
    authorized = False
    for dimension, new_value in requested:
        if new_value is None:
            continue
        history = context.event_store.replay()
        if not _re_v2_is_paused(history):
            raise ValueError("v2 budget authorization requires a paused run")
        budget = evaluate_budget(
            context.manifest.initial_budget_policy,
            history,
            now=_re_v2_now(),
        )
        old_value = (
            budget.token_limit
            if dimension is BudgetDimension.TOKENS
            else budget.active_ms_limit
        )
        event = authorize_resource_increase(
            context.manifest.initial_budget_policy,
            history,
            dimension=dimension,
            old_value=old_value,
            new_value=new_value,
            actor="echelon-cli",
            reason="CLI resource ceiling increase",
        )
        context.event_store.append(
            str(event["type"]),
            event["payload"],
            occurred_at=_re_v2_now(),
        )
        authorized = True
    if paused:
        if not authorized:
            context.event_store.append(
                "operator_pause_requested",
                {
                    "reason": "CLI continuation requested",
                    "requested_by": "echelon-cli",
                },
                occurred_at=_re_v2_now(),
            )
        context.event_store.append(
            "run_resumed",
            {
                "reason": (
                    "CLI continuation after resource authorization"
                    if authorized
                    else "CLI continuation requested"
                )
            },
            occurred_at=_re_v2_now(),
        )
    _run_re_v2_live(context)


def _run_re_v22_continue(
    context: object,
    *,
    token_limit: int | None,
    time_limit_minutes: int | None,
    active_ms_limit: int | None = None,
) -> None:
    from harness.re_v2.protocol_22.recovery import (
        protocol_22_run_lock,
        recover_protocol_22_run,
        recover_protocol_22_run_locked,
    )

    requested = {
        "tokens": token_limit,
        "active_ms": (
            active_ms_limit
            if active_ms_limit is not None
            else time_limit_minutes * 60_000
            if time_limit_minutes is not None
            else None
        ),
    }

    def validate(recovered: object) -> list[tuple[str, int, int | None]]:
        state = str(getattr(recovered, "operational_state"))
        changes = [
            (dimension, value)
            for dimension, value in requested.items()
            if value is not None
        ]
        if state == "terminal":
            if changes:
                raise ValueError(
                    "terminal protocol-2.2 runs cannot receive budget authorization"
                )
            return []
        if state == "pinned_authority_unavailable":
            if changes:
                raise ValueError(
                    "protocol-2.2 budget authorization requires restored pinned authority"
                )
            return []
        if state == "paused":
            if not changes:
                raise ValueError(
                    "paused protocol-2.2 continuation requires a strictly higher "
                    "token or active-time ceiling"
                )
            budget = getattr(recovered, "budget", None)
            if budget is None:
                raise ValueError("paused protocol-2.2 recovery omitted budget authority")
            validated: list[tuple[str, int, int | None]] = []
            for dimension, new_value in changes:
                old_value = (
                    budget.token_limit
                    if dimension == "tokens"
                    else budget.active_ms_limit
                )
                if old_value is not None and new_value <= old_value:
                    raise ValueError(
                        f"protocol-2.2 {dimension} ceiling must be strictly higher "
                        f"than {old_value}"
                    )
                validated.append((dimension, new_value, old_value))
            return validated
        if changes:
            raise ValueError(
                "protocol-2.2 budget authorization requires a paused run"
            )
        return []

    recovered = recover_protocol_22_run(context)
    changes = validate(recovered)
    if str(recovered.operational_state) in {
        "terminal",
        "pinned_authority_unavailable",
    }:
        _run_re_v2_live(context)
        return
    if not changes:
        _run_re_v2_live(context)
        return

    with protocol_22_run_lock(context.paths):
        recovered = recover_protocol_22_run_locked(context)
        changes = validate(recovered)
        for dimension, new_value, old_value in changes:
            context.event_store.append(
                "budget_authorized",
                {
                    "authorized_by": "echelon-cli",
                    "dimension": dimension,
                    "new_value": new_value,
                    "old_value": old_value,
                    "reason": "CLI resource ceiling increase",
                },
                occurred_at=_re_v2_now(),
            )
        context.event_store.append(
            "run_resumed",
            {"reason": "CLI continuation after resource authorization"},
            occurred_at=_re_v2_now(),
        )
    _run_re_v2_live(context)


def _cmd_re_run(args: list[str]) -> None:
    from harness.re_lifecycle import ReLifecycleError

    try:
        engine, shadow, goal, lifecycle_args = _parse_re_creation_engine_options(args)
        (
            policy,
            re_max_inner,
            reset,
            no_reuse,
            profile,
            token_limit,
            time_limit_minutes,
            positional,
        ) = _parse_re_lifecycle_options(
            lifecycle_args,
            allow_policy=True,
            allow_reset=True,
        )
        if positional:
            raise ValueError("echelon re run does not accept positional arguments")
        if engine == "v2":
            if re_max_inner is not None:
                raise ValueError(
                    "v2 has independent attempt budgets; this option is valid only for v1"
                )
            if policy != "changed" or reset or no_reuse or profile is not None:
                raise ValueError(
                    "v2 creation does not accept v1 policy, reset, reuse, or profile options"
                )
            try:
                _run_re_v2_create(
                    Path.cwd(),
                    token_limit=token_limit,
                    time_limit_minutes=time_limit_minutes,
                    shadow=shadow,
                    goal=goal,
                )
            except RuntimeError as exc:
                raise ValueError(str(exc)) from exc
            return
        result = _re_lifecycle_controller(Path.cwd()).run(
            policy=policy,
            re_max_inner=re_max_inner,
            reset=reset,
            reuse_published=not no_reuse,
            profile_name=profile,
            hard_token_limit=token_limit,
            hard_active_minutes=time_limit_minutes,
        )
    except (ReLifecycleError, ValueError) as exc:
        print(f"echelon re run: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    _print_re_lifecycle_result(result)


def _cmd_re_refresh(args: list[str]) -> None:
    """Refresh and publish one declared source through the normal RE transaction."""
    from harness.re_lifecycle import ReLifecycleError

    source = ""
    index = 0
    try:
        while index < len(args):
            arg = args[index]
            if arg == "--source":
                if index + 1 >= len(args) or source:
                    raise ValueError("--source requires exactly one source ID")
                source = args[index + 1].strip()
                index += 2
            elif arg.startswith("--source="):
                if source:
                    raise ValueError("--source requires exactly one source ID")
                source = arg.split("=", 1)[1].strip()
                index += 1
            else:
                raise ValueError(f"unknown option {arg!r}")
        if not source:
            raise ValueError("--source requires exactly one source ID")
        result = _re_lifecycle_controller(Path.cwd()).run(
            policy="target-only",
            target_source=source,
            force_selected_refresh=True,
        )
    except (ReLifecycleError, ValueError) as exc:
        print(f"echelon re refresh: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    if str(getattr(result, "status", "failed")) != "done":
        _print_re_lifecycle_result(result)
        return
    run_id = str(getattr(result, "run_id", ""))
    if bool(getattr(result, "no_work", False)) or not run_id:
        raise SystemExit("echelon re refresh: targeted refresh produced no publishable run")
    _cmd_re_publish([run_id])


@dataclass(frozen=True, slots=True)
class _ReDeepenOptions:
    target_layer: str
    all_sources: bool
    source_ids: tuple[str, ...]
    domain_ids: tuple[str, ...]
    from_run: str | None
    token_limit: int | None
    active_ms_limit: int | None


def _parse_re_deepen_options(args: list[str]) -> _ReDeepenOptions:
    values: dict[str, object] = {
        "target_layer": None,
        "all_sources": False,
        "source_ids": [],
        "domain_ids": [],
        "from_run": None,
        "token_limit": None,
        "active_ms_limit": None,
    }
    scalar = {
        "--to": "target_layer",
        "--from-run": "from_run",
        "--token-limit": "token_limit",
        "--active-ms-limit": "active_ms_limit",
    }
    repeatable = {"--source": "source_ids", "--domain": "domain_ids"}
    index = 0
    while index < len(args):
        option = args[index]
        if option == "--all":
            if values["all_sources"]:
                raise ValueError("--all may be supplied only once")
            values["all_sources"] = True
            index += 1
            continue
        name = option
        inline: str | None = None
        if "=" in option:
            name, inline = option.split("=", 1)
        if name not in scalar and name not in repeatable:
            raise ValueError(f"unknown option {option!r}")
        if inline is None:
            if index + 1 >= len(args):
                raise ValueError(f"{name} requires a value")
            inline = args[index + 1]
            index += 2
        else:
            index += 1
        value = inline.strip()
        if not value:
            raise ValueError(f"{name} requires a nonempty value")
        if name in repeatable:
            collection = values[repeatable[name]]
            assert isinstance(collection, list)
            if value in collection:
                raise ValueError(f"duplicate {name} selector {value!r}")
            collection.append(value)
            continue
        field = scalar[name]
        if values[field] is not None:
            raise ValueError(f"{name} may be supplied only once")
        if name in {"--token-limit", "--active-ms-limit"}:
            try:
                parsed = int(value)
            except ValueError as exc:
                raise ValueError(f"{name} must be a positive integer") from exc
            if parsed <= 0:
                raise ValueError(f"{name} must be a positive integer")
            values[field] = parsed
        else:
            values[field] = value
    target = values["target_layer"]
    if target != "L2":
        raise ValueError("--to L2 is required; L3/L4 are not registered")
    sources = tuple(values["source_ids"])
    domains = tuple(values["domain_ids"])
    all_sources = bool(values["all_sources"])
    if all_sources and (sources or domains):
        raise ValueError("--all cannot be combined with --source or --domain")
    if not all_sources and not sources:
        raise ValueError("exactly one selector form is required: --all or --source")
    if domains and len(sources) != 1:
        raise ValueError("--domain requires exactly one --source")
    return _ReDeepenOptions(
        target_layer="L2",
        all_sources=all_sources,
        source_ids=tuple(sorted(sources)),
        domain_ids=tuple(sorted(domains)),
        from_run=values["from_run"] if isinstance(values["from_run"], str) else None,
        token_limit=values["token_limit"] if isinstance(values["token_limit"], int) else None,
        active_ms_limit=(
            values["active_ms_limit"]
            if isinstance(values["active_ms_limit"], int)
            else None
        ),
    )


def _resolve_re_v24_selection(
    workspace_partition: object,
    options: _ReDeepenOptions,
) -> object:
    from harness.re_v2.protocol_22.partition import WorkspacePartitionCatalogV1
    from harness.re_v2.protocol_24.model import SelectionScopeV1

    if not isinstance(workspace_partition, WorkspacePartitionCatalogV1):
        raise ValueError("deepening requires an authenticated workspace partition")
    if not isinstance(options, _ReDeepenOptions):
        raise ValueError("deepening selection options are invalid")
    by_source = {
        source.source_id: source for source in workspace_partition.sources
    }
    if options.all_sources:
        if not by_source:
            raise ValueError("workspace partition contains no sources")
        return SelectionScopeV1(1, True, (), ())
    unknown_sources = tuple(
        source_id for source_id in options.source_ids if source_id not in by_source
    )
    if unknown_sources:
        raise ValueError(
            "unknown source selector(s): " + ", ".join(unknown_sources)
        )
    resolved_domains: list[str] = []
    if options.domain_ids:
        source = by_source[options.source_ids[0]]
        for selector in options.domain_ids:
            matches = tuple(
                domain
                for domain in source.domains
                if selector in {domain.domain_key, domain.presentation_domain_id}
            )
            if not matches:
                raise ValueError(
                    f"unknown domain selector {selector!r} for source {source.source_id!r}"
                )
            if len(matches) != 1:
                raise ValueError(
                    f"ambiguous domain selector {selector!r} for source {source.source_id!r}"
                )
            resolved_domains.append(matches[0].domain_key)
    if len(resolved_domains) != len(set(resolved_domains)):
        raise ValueError("domain selectors resolve to duplicate domains")
    return SelectionScopeV1(
        schema_version=1,
        all_sources=False,
        source_ids=tuple(sorted(options.source_ids)),
        domain_keys=tuple(sorted(resolved_domains)),
    )


def semantic_request_id_for(
    lineage_root_run_id: str,
    lineage_root_manifest_hash: str,
    source_snapshot_id: str,
    selection: object,
    target_layer: str,
    artifact_policy_hash: str,
) -> str:
    from harness.re_v2.canonical import content_digest
    from harness.re_v2.protocol_22.schema import digest_value, safe_id
    from harness.re_v2.protocol_24.model import SelectionScopeV1

    if not isinstance(selection, SelectionScopeV1):
        raise ValueError("semantic request requires SelectionScopeV1")
    safe_id(lineage_root_run_id, "lineage_root_run_id")
    digest_value(lineage_root_manifest_hash, "lineage_root_manifest_hash")
    digest_value(source_snapshot_id, "source_snapshot_id")
    digest_value(artifact_policy_hash, "artifact_policy_hash")
    if target_layer != "L2":
        raise ValueError("semantic request target must be L2")
    return content_digest(
        {
            "artifact_policy_hash": artifact_policy_hash,
            "lineage_root_manifest_hash": lineage_root_manifest_hash,
            "lineage_root_run_id": lineage_root_run_id,
            "selection": selection.to_json_dict(),
            "source_snapshot_id": source_snapshot_id,
            "target_layer": target_layer,
        }
    )


@dataclass(frozen=True, slots=True)
class _Protocol24Creation:
    parent: object
    manifest: object
    inputs: object
    graph: object


def _prepare_re_v24_creation(
    workspace_root: Path,
    parent: object,
    options: _ReDeepenOptions,
) -> _Protocol24Creation:
    from dataclasses import replace

    import harness.re_v2.protocol_24.artifacts as artifacts_module
    import harness.re_v2.protocol_24.controller as controller_module
    import harness.re_v2.protocol_24.runtime as runtime_module
    from harness.re_v2.canonical import canonical_json_bytes, content_digest
    from harness.re_v2.protocol_22.authorities import validate_installed_authorities
    from harness.re_v2.protocol_22.model import BudgetPolicyV2, CatalogReferenceV1
    from harness.re_v2.protocol_22.provider import canonical_prosaic_agent_bytes
    from harness.re_v2.protocol_24.adoption import (
        ValidatedParentV1,
        build_parent_authority_bundle,
    )
    from harness.re_v2.protocol_24.artifacts import (
        DEEPENER_AGENT_ID,
        DEEPENING_IN_PROCESS_ADAPTER_ID,
        DEEPENING_VERIFIER_ID,
        build_deepening_executor_catalog,
    )
    from harness.re_v2.protocol_24.graph import build_protocol_24_graph
    from harness.re_v2.protocol_24.inputs import Protocol24InputSet
    from harness.re_v2.protocol_24.model import ParentLineageV1, RunManifestV3
    from harness.re_v2.protocol_24.policies import build_deepening_v1_policy_catalog

    if not isinstance(parent, ValidatedParentV1):
        raise ValueError("deepening parent validation returned no closed authority")
    selection = _resolve_re_v24_selection(
        parent.inputs.workspace_partition,
        options,
    )
    try:
        artifact = ProsaicPromptLoader(workspace_root).load_subagent(
            DEEPENER_AGENT_ID
        )
    except ProsaicPromptLoadError as exc:
        raise ValueError(str(exc)) from exc
    if artifact is None:
        raise ValueError(
            "installed Prosaic agent echelon.re-deepener is missing; run "
            "`echelon workspace migrate-to-prosaic` before deepening RE"
        )
    deepener_bytes = canonical_prosaic_agent_bytes(artifact)
    deepener_hash = content_digest(deepener_bytes)
    implementation_digest = _re_v22_implementation_digest(
        artifacts_module,
        runtime_module,
        controller_module,
    )
    policy = build_deepening_v1_policy_catalog()
    executors = build_deepening_executor_catalog(
        parent.inputs.executor_contract,
        deepener_hash,
        implementation_digest,
    )
    compact = parent.inputs.executor_contract.entry_for("compact-baseline")
    renderer = compact.request_renderer
    if renderer is None:
        raise ValueError("completed parent has no pinned shared provider renderer")
    baseline_agent = parent.inputs.immutable_objects.get(renderer.agent_contract_hash)
    if baseline_agent is None:
        raise ValueError("completed parent has no pinned Prosaic baseliner authority")
    registry, _agent, _schemas = _re_schema2_installed_registry(
        baseline_agent,
        provider_mode="cli",
    )
    registry = replace(
        registry,
        executor_implementations={
            **dict(registry.executor_implementations),
            DEEPENING_IN_PROCESS_ADAPTER_ID: implementation_digest,
        },
        verifier_implementations={
            **dict(registry.verifier_implementations),
            DEEPENING_VERIFIER_ID: implementation_digest,
        },
        agent_contracts={
            **dict(registry.agent_contracts),
            DEEPENER_AGENT_ID: deepener_hash,
        },
    )
    mismatches = validate_installed_authorities(executors, registry)
    if mismatches:
        details = ", ".join(
            f"{item.authority_kind}:{item.authority_id}" for item in mismatches
        )
        raise ValueError(f"protocol-2.4 installed authority mismatch: {details}")

    bundle, authority_objects = build_parent_authority_bundle(parent)
    parent_manifest_hash = content_digest(parent.manifest_bytes)
    lineage = ParentLineageV1(
        schema_version=1,
        direct_parent_run_id=parent.manifest.run_id,
        direct_parent_manifest_hash=parent_manifest_hash,
        direct_parent_terminal_event_hash=parent.events[-1].event_hash,
        lineage_root_run_id=parent.manifest.run_id,
        lineage_root_manifest_hash=parent_manifest_hash,
    )
    semantic_id = semantic_request_id_for(
        lineage.lineage_root_run_id,
        lineage.lineage_root_manifest_hash,
        parent.manifest.source_snapshot_id,
        selection,
        "L2",
        policy.identity,
    )
    manifest = RunManifestV3(
        schema_version=3,
        engine="re-v2",
        engine_protocol_version="2.4",
        # Allocation happens only while holding the workspace creation lock.
        run_id="re-pending-deepening",
        created_at=_re_v2_now(),
        source_snapshot_id=parent.manifest.source_snapshot_id,
        source_snapshot_kind="workspace-git-composite",
        partition_manifest_id=parent.manifest.partition_manifest_id,
        workspace_partition_catalog=CatalogReferenceV1(
            parent.inputs.workspace_partition.identity,
            "workspace-partition.json",
        ),
        artifact_policy_catalog=CatalogReferenceV1(
            policy.identity,
            "artifact-policy.json",
        ),
        executor_contract_catalog=CatalogReferenceV1(
            executors.identity,
            "executor-contract.json",
        ),
        parent_authority_bundle=CatalogReferenceV1(
            bundle.identity,
            "parent-authority.json",
        ),
        parent_lineage=lineage,
        requested_goals=("selective-deepening",),
        target_layer="L2",
        selection=selection,
        semantic_request_id=semantic_id,
        initial_budget_policy=BudgetPolicyV2(
            token_limit=options.token_limit or 5_000_000,
            active_ms_limit=options.active_ms_limit or 180 * 60_000,
            provider_attempt_limit=2,
            artifact_generation_attempt_limit=2,
            semantic_repair_round_limit=0,
            result_contract_retry_limit=1,
            shared_retry_limit=1,
            artifact_contract_retry_limit=1,
        ),
    )
    immutable_objects = {
        **dict(parent.inputs.immutable_objects),
        **dict(authority_objects),
        deepener_hash: deepener_bytes,
    }
    inputs = Protocol24InputSet(
        workspace_partition=parent.inputs.workspace_partition,
        artifact_policy=policy,
        executor_contract=executors,
        immutable_objects=immutable_objects,
        parent_authority_bundle=bundle,
    )
    graph = build_protocol_24_graph(manifest, inputs, parent.accepted_parent)
    # Canonical construction here catches accidental non-JSON metadata before
    # the manifest-last publisher creates any child path.
    canonical_json_bytes(manifest.to_json_dict())
    return _Protocol24Creation(parent, manifest, inputs, graph)


@contextmanager
def _re_v24_creation_lock(workspace_root: Path):
    runs = workspace_root.resolve() / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    root_fd = os.open(runs, flags)
    lock_fd: int | None = None
    try:
        lock_flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
        lock_flags |= getattr(os, "O_NOFOLLOW", 0)
        for attempt in range(3):
            try:
                lock_fd = os.open(
                    ".re-v24-create.lock",
                    lock_flags,
                    0o600,
                    dir_fd=root_fd,
                )
                break
            except FileNotFoundError:
                if attempt == 2:
                    raise
        if lock_fd is None:
            raise ValueError("cannot open RE deepening creation lock")
        metadata = os.fstat(lock_fd)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("RE deepening creation lock is not a regular file")
        os.fchmod(lock_fd, 0o600)
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        yield
    finally:
        if lock_fd is not None:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(lock_fd)
        os.close(root_fd)


def _find_re_v24_semantic_child(
    workspace_root: Path,
    semantic_request_id: str,
) -> Path | None:
    from harness.re_v2.protocol_24.model import RunManifestV3
    from harness.re_v2.run_store import load_run_manifest

    runs = workspace_root.resolve() / "runs"
    for candidate in sorted(runs.iterdir(), key=lambda path: path.name):
        if (
            not candidate.name.startswith("re-")
            or candidate.is_symlink()
            or not candidate.is_dir()
            or not (candidate / "v2" / "run.json").is_file()
        ):
            continue
        manifest = load_run_manifest(candidate)
        if (
            isinstance(manifest, RunManifestV3)
            and manifest.semantic_request_id == semantic_request_id
        ):
            return candidate
    return None


def _resolve_re_v24_parent_path(
    workspace_root: Path,
    from_run: str | None,
) -> Path:
    from harness.re_lifecycle import resolve_current_re_run
    from harness.re_v2.protocol_22.schema import safe_id

    if from_run is not None:
        safe_id(from_run, "from_run")
        return workspace_root.resolve() / "runs" / from_run
    current = resolve_current_re_run(workspace_root)
    if current is None:
        raise ValueError("no active RE parent; use --from-run RUN_ID")
    return current


def _run_re_v24_deepen(
    workspace_root: Path,
    options: _ReDeepenOptions,
) -> Path:
    from harness.re_v2.events import EventStore
    from harness.re_v2.ledger import ObjectStore
    from harness.re_v2.protocol_22.ledger import Protocol22Ledger
    from harness.re_v2.protocol_24.adoption import (
        import_parent_acceptance_closure,
        validate_parent_for_deepening,
    )
    from harness.re_v2.protocol_24.events import PROTOCOL_24_EVENTS
    from harness.re_v2.protocol_24.inputs import create_protocol_24_run_store

    workspace = workspace_root.resolve()
    parent_path = _resolve_re_v24_parent_path(workspace, options.from_run)
    # Clean/exact-source validation deliberately precedes every child mutation.
    parent = validate_parent_for_deepening(parent_path, workspace)
    prepared = _prepare_re_v24_creation(workspace, parent, options)
    created = False
    with _re_v24_creation_lock(workspace):
        existing = _find_re_v24_semantic_child(
            workspace,
            prepared.manifest.semantic_request_id,
        )
        if existing is None:
            from dataclasses import replace

            manifest = replace(
                prepared.manifest,
                run_id=_new_re_v2_run_id(workspace),
                created_at=_re_v2_now(),
            )
            run_dir = workspace / "runs" / manifest.run_id
            paths = create_protocol_24_run_store(
                run_dir,
                manifest,
                prepared.inputs,
            )
            objects = ObjectStore(paths.objects)
            ledger = Protocol22Ledger(paths, objects)
            import_parent_acceptance_closure(parent, objects, ledger)
            events = EventStore(paths, protocol=PROTOCOL_24_EVENTS)
            events.append(
                "run_created",
                {"run_manifest_id": manifest.run_manifest_id},
                occurred_at=manifest.created_at,
            )
            by_certification = {
                value.certification_receipt_id: value
                for value in prepared.inputs.parent_authority_bundle.artifacts
            }
            for certification_id, work_item in sorted(
                ledger.replay().certification_work_items.items()
            ):
                authority = by_certification.get(certification_id)
                if authority is None:
                    raise ValueError(
                        "imported parent work item has no adoption authority"
                    )
                events.append(
                    "artifact_adopted",
                    {
                        "adopted_artifact_authority": authority.to_json_dict(),
                        "parent_authority_bundle_hash": (
                            prepared.inputs.parent_authority_bundle.identity
                        ),
                        "work_item_id": work_item.work_item_id,
                    },
                    occurred_at=_re_v2_now(),
                )
            created = True
        else:
            run_dir = existing
        _activate_re_v2_run(workspace, run_dir.name)
    context = _re_v2_context(workspace, run_dir)
    if created:
        _run_re_v2_live(context)
    else:
        _continue_re_v24_semantic_child(context, options)
    return run_dir


def _continue_re_v24_semantic_child(
    context: object,
    options: _ReDeepenOptions,
) -> None:
    from harness.re_v2.protocol_22.budget import evaluate_budget_v22
    from harness.re_v2.protocol_24.events import PROTOCOL_24_EVENTS
    from harness.re_v2.run_store import load_run_manifest

    if options.token_limit is None and options.active_ms_limit is None:
        _run_re_v2_live(context)
        return
    events = context.event_store.replay()
    if events and events[-1].type in {"run_completed", "run_failed"}:
        _run_re_v2_live(context)
        return
    if not _re_v2_is_paused(events):
        # A concurrent or crash-recovered child keeps its existing authority;
        # the shared controller will either progress it or expose a pause.
        _run_re_v2_live(context)
        return
    manifest = load_run_manifest(context.paths.root.parent)
    budget = evaluate_budget_v22(
        manifest.initial_budget_policy,
        events,
        (),
        _re_v2_now(),
        event_protocol=PROTOCOL_24_EVENTS,
    )
    token_limit = (
        options.token_limit
        if options.token_limit is not None
        and budget.token_limit is not None
        and options.token_limit > budget.token_limit
        else None
    )
    active_ms_limit = (
        options.active_ms_limit
        if options.active_ms_limit is not None
        and budget.active_ms_limit is not None
        and options.active_ms_limit > budget.active_ms_limit
        else None
    )
    if token_limit is None and active_ms_limit is None:
        _run_re_v2_live(context)
        return
    _run_re_v22_continue(
        context,
        token_limit=token_limit,
        time_limit_minutes=None,
        active_ms_limit=active_ms_limit,
    )


def _cmd_re_deepen(args: list[str]) -> None:
    try:
        options = _parse_re_deepen_options(args)
        _run_re_v24_deepen(Path.cwd(), options)
    except (RuntimeError, ValueError) as exc:
        print(f"echelon re deepen: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


def _cmd_re_continue(args: list[str]) -> None:
    from harness.re_lifecycle import ReLifecycleError, resolve_current_re_run

    try:
        _policy, re_max_inner, _reset, _no_reuse, _profile, token_limit, time_limit_minutes, positional = _parse_re_lifecycle_options(
            args,
            allow_policy=False,
            allow_reset=False,
            allow_budget_overrides=True,
        )
        if positional:
            raise ValueError("echelon re continue does not accept positional arguments")
        project_root = Path.cwd()
        run_dir = resolve_current_re_run(project_root)
        if run_dir is not None and _detect_re_engine_for_cli(run_dir) == "v2":
            if re_max_inner is not None:
                raise ValueError(
                    "v2 has independent attempt budgets; this option is valid only for v1"
                )
            try:
                _run_re_v2_continue(
                    run_dir,
                    token_limit=token_limit,
                    time_limit_minutes=time_limit_minutes,
                )
            except RuntimeError as exc:
                raise ValueError(str(exc)) from exc
            return
        _print_re_continue_summary(project_root, re_max_inner=re_max_inner)
        overrides: dict[str, int] = {}
        if token_limit is not None:
            overrides["hard_token_limit"] = token_limit
        if time_limit_minutes is not None:
            overrides["hard_active_minutes"] = time_limit_minutes
        result = _re_lifecycle_controller(project_root).continue_run(
            re_max_inner,
            **overrides,
        )
    except (ReLifecycleError, ValueError) as exc:
        print(f"echelon re continue: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    _print_re_lifecycle_result(result)


def _cmd_re_resume(args: list[str]) -> None:
    from harness.re_lifecycle import ReLifecycleError

    try:
        _policy, re_max_inner, _reset, _no_reuse, _profile, token_limit, time_limit_minutes, positional = _parse_re_lifecycle_options(
            args,
            allow_policy=False,
            allow_reset=False,
            allow_budget_overrides=True,
        )
        if len(positional) != 1:
            raise ValueError('usage: echelon re resume "<answer>"')
        overrides: dict[str, int] = {}
        if token_limit is not None:
            overrides["hard_token_limit"] = token_limit
        if time_limit_minutes is not None:
            overrides["hard_active_minutes"] = time_limit_minutes
        result = _re_lifecycle_controller(Path.cwd()).resume(
            positional[0],
            re_max_inner,
            **overrides,
        )
    except (ReLifecycleError, ValueError) as exc:
        print(f"echelon re resume: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    _print_re_lifecycle_result(result)


def _cmd_re_finalize(args: list[str]) -> None:
    """Explicitly acknowledge debt and terminalize a blocked RE run as partial."""
    from harness.re_finalization import ReFinalizationError, finalize_partial_re_run

    allow_partial = False
    positional: list[str] = []
    for arg in args:
        if arg == "--allow-partial":
            allow_partial = True
        elif arg.startswith("-"):
            print(f"echelon re finalize: unknown argument '{arg}'", file=sys.stderr)
            raise SystemExit(2)
        else:
            positional.append(arg)
    if not allow_partial:
        print(
            "echelon re finalize: --allow-partial is required; "
            "this transition accepts unresolved RE debt",
            file=sys.stderr,
        )
        raise SystemExit(2)
    if len(positional) > 1:
        print(
            "Usage: echelon re finalize [<run-id>] --allow-partial",
            file=sys.stderr,
        )
        raise SystemExit(2)
    try:
        result = finalize_partial_re_run(
            Path.cwd(),
            run_id=positional[0] if positional else None,
        )
    except (ReFinalizationError, OSError, ValueError) as exc:
        print(f"echelon re finalize: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    publish_command = f"echelon re publish {result.run_id} --allow-partial"
    print(
        f"RE run {result.run_id} finalized as partial; unresolved debt remains."
    )
    _banner(
        "RE FINAL STATE — PARTIAL",
        [
            ("run", result.run_id),
            ("status", "partial (debt accepted, not full quality)"),
            ("stopped because", result.blocked_reason),
            ("partial sources", ", ".join(result.partial_sources) or "workspace-level only"),
            ("semantic findings", str(result.semantic_failure_count)),
            (
                "workspace synthesis",
                "incomplete" if result.workspace_synthesis_incomplete else "present",
            ),
            ("debt manifest", str(result.debt_manifest)),
            ("next step", publish_command),
        ],
        subtitle="The run is terminal and publishable only with --allow-partial.",
    )


def _cmd_re_synthesize(args: list[str]) -> None:
    """Regenerate only workspace synthesis from accepted partial source results."""
    from harness.config import load_config
    from harness.re_finalization import (
        ReFinalizationError,
        synthesize_partial_re_run,
    )
    from harness.squad_provider import SquadCliProvider

    allow_partial = False
    token_limit: int | None = None
    time_limit_minutes: int | None = None
    positional: list[str] = []
    index = 0
    try:
        while index < len(args):
            arg = args[index]
            if arg == "--allow-partial":
                allow_partial = True
                index += 1
            elif arg in {"--re-token-limit", "--re-time-limit-minutes"}:
                if index + 1 >= len(args):
                    raise ValueError(f"{arg} requires a positive integer")
                try:
                    value = int(args[index + 1])
                except ValueError as exc:
                    raise ValueError(f"{arg} requires a positive integer") from exc
                if value < 1:
                    raise ValueError(f"{arg} requires a positive integer")
                if arg == "--re-token-limit":
                    token_limit = value
                else:
                    time_limit_minutes = value
                index += 2
            elif arg.startswith("--re-token-limit="):
                token_limit = int(arg.split("=", 1)[1])
                index += 1
            elif arg.startswith("--re-time-limit-minutes="):
                time_limit_minutes = int(arg.split("=", 1)[1])
                index += 1
            elif arg.startswith("-"):
                raise ValueError(f"unknown argument {arg!r}")
            else:
                positional.append(arg)
                index += 1
        if not allow_partial:
            raise ValueError(
                "--allow-partial is required; synthesis will use sources with accepted debt"
            )
        if len(positional) > 1:
            raise ValueError(
                "usage: echelon re synthesize [<run-id>] --allow-partial "
                "[--re-token-limit <n>]"
            )
        project_root = Path.cwd()
        runtime_root, prosaic_subagents_dir = _installed_re_runtime_or_exit(
            project_root
        )
        config = load_config(project_root, squad_only=True)
        result = synthesize_partial_re_run(
            project_root,
            run_id=positional[0] if positional else None,
            provider=SquadCliProvider(config),
            extension_root=runtime_root,
            prosaic_subagents_dir=prosaic_subagents_dir,
            hard_token_limit=token_limit,
            hard_active_minutes=time_limit_minutes,
        )
    except (ReFinalizationError, OSError, ValueError) as exc:
        print(f"echelon re synthesize: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    publish_command = f"echelon re publish {result.run_id} --allow-partial"
    print(f"Workspace synthesis completed for partial RE run {result.run_id}.")
    _banner(
        "RE WORKSPACE SYNTHESIS — COMPLETE",
        [
            ("run", result.run_id),
            ("source quality", "partial debt accepted"),
            ("workspace synthesis", "complete"),
            ("token usage", str(result.token_usage)),
            ("next step", publish_command),
        ],
        subtitle="Only workspace synthesis ran; source repair and semantic revalidation stayed closed.",
    )


def _cmd_re_publish(args: list[str]) -> None:
    """Publish one validated run into the canonical workspace RE registry."""
    import json
    import re

    from echelon.git_helpers import GitHelperError, run_git
    from harness.re_artifacts import ReArtifactCatalogError
    from harness.re_lock import (
        RePublicationActiveRun,
        RePublishLocked,
        RePublishRecoveryRequired,
    )
    from harness.re_migration import import_legacy_re_cache
    from harness.re_finalization import mark_re_run_published
    from harness.re_publication import RePublicationError, publish_re_run

    allow_partial = False
    commit = False
    positional: list[str] = []
    for arg in args:
        if arg == "--allow-partial":
            allow_partial = True
        elif arg == "--commit":
            commit = True
        elif arg.startswith("-"):
            print(f"echelon re publish: unknown argument '{arg}'", file=sys.stderr)
            raise SystemExit(1)
        else:
            positional.append(arg)

    if len(positional) != 1 or not re.fullmatch(r"[A-Za-z0-9._-]+", positional[0]):
        print(
            "Usage: echelon re publish <run-id> [--allow-partial] [--commit]",
            file=sys.stderr,
        )
        raise SystemExit(1)

    run_id = positional[0]
    if run_id in {".", ".."}:
        print(f"echelon re publish: unsafe run id '{run_id}'", file=sys.stderr)
        raise SystemExit(1)
    project_root = Path.cwd().resolve()
    run_dir = project_root / "runs" / run_id
    if not run_dir.is_dir():
        print(
            f"echelon re publish: run not found under runs/: {run_id}",
            file=sys.stderr,
        )
        raise SystemExit(1)

    try:
        imported = import_legacy_re_cache(project_root)
        lifecycle_state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
        result = publish_re_run(
            project_root,
            run_dir,
            allow_partial=allow_partial,
            expected_generation=int(lifecycle_state.get("expected_generation") or 0),
            allow_same_run_republish=True,
        )
        mark_re_run_published(
            run_dir,
            status=result.status,
            generation=result.generation,
        )
        if commit:
            _commit_re_publication(project_root, result.generation, run_git)
    except (
        RePublicationError,
        ReArtifactCatalogError,
        RePublicationActiveRun,
        RePublishLocked,
        RePublishRecoveryRequired,
        GitHelperError,
        OSError,
        ValueError,
    ) as exc:
        print(f"echelon re publish: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    print(f"Published RE generation {result.generation} ({result.status})")
    if result.changed_sources:
        print("Changed sources: " + ", ".join(result.changed_sources))
    if result.removed_sources:
        print("Removed sources: " + ", ".join(result.removed_sources))
    if imported:
        print(f"Imported {len(imported)} legacy RE cache entr{'y' if len(imported) == 1 else 'ies'}")
    if not commit:
        print("Git commit: not requested")


def _cmd_re_execute_run(args: list[str]) -> None:
    """Run active workspace RE phases under the deterministic controller."""
    import json
    import re

    from harness.re_controller import ReExtractionController
    from harness.squad_provider import SquadCliProvider

    if len(args) != 1 or not re.fullmatch(r"[A-Za-z0-9._-]+", args[0]):
        print("Usage: echelon re execute-run <run-id>", file=sys.stderr)
        raise SystemExit(1)
    run_id = args[0]
    project_root = Path.cwd().resolve()
    current_path = project_root / "runs" / ".current"
    run_dir = project_root / "runs" / run_id
    if not run_dir.is_dir() or not current_path.is_file() or current_path.read_text().strip() != run_id:
        print(
            f"echelon re execute-run: {run_id!r} is not the active workspace run",
            file=sys.stderr,
        )
        raise SystemExit(1)
    runtime_root, prosaic_subagents_dir = _installed_re_runtime_or_exit(project_root)
    try:
        provider = SquadCliProvider(_load_cli_config(project_root))
        result = ReExtractionController(
            provider=provider,
            project_root=project_root,
            run_dir=run_dir,
            extension_root=runtime_root,
            prosaic_subagents_dir=prosaic_subagents_dir,
        ).run()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"echelon re execute-run: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    payload = {
        "run_id": run_id,
        "status": "complete" if result.completed else "blocked",
        "blocked_reason": result.blocked_reason,
    }
    print(json.dumps(payload, sort_keys=True))
    if not result.completed:
        raise SystemExit(1)


def _cmd_re_check_domain(args: list[str]) -> None:
    """Check one staged domain against the deterministic deep-spec contract."""
    import json
    import re

    from harness.re_planner import ReExecutionPlan
    from harness.re_quality_gate import validate_staged_re_domain_quality

    if len(args) != 3 or any(
        not re.fullmatch(r"[A-Za-z0-9._-]+", value) for value in args
    ):
        print(
            "Usage: echelon re check-domain <run-id> <source-id> <domain-id>",
            file=sys.stderr,
        )
        raise SystemExit(1)
    run_id, source_id, domain_id = args
    project_root = Path.cwd().resolve()
    run_dir = project_root / "runs" / run_id
    plan_path = run_dir / "re" / "re-execution-plan.json"
    if not plan_path.is_file():
        print(
            f"echelon re check-domain: run not found under runs/: {run_id}",
            file=sys.stderr,
        )
        raise SystemExit(1)
    try:
        plan = ReExecutionPlan.from_json_dict(
            json.loads(plan_path.read_text(encoding="utf-8"))
        )
        report = validate_staged_re_domain_quality(
            run_dir / "re", plan, source_id, domain_id
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"echelon re check-domain: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(json.dumps(report.to_json_dict(), sort_keys=True))
    if not report.passed:
        raise SystemExit(1)


def _commit_re_publication(project_root: Path, generation: int, run_git) -> None:
    """Commit exactly the durable published RE surface."""
    pre_staged = run_git(
        project_root,
        "diff",
        "--cached",
        "--name-only",
    ).stdout.splitlines()
    if pre_staged:
        raise ValueError(
            "cannot commit RE publication while other staged changes exist: "
            + ", ".join(pre_staged)
        )

    run_git(
        project_root,
        "add",
        "--",
        "re/.gitignore",
        "re/index.json",
        "re/sources",
        "re/workspace",
    )
    staged = run_git(
        project_root,
        "diff",
        "--cached",
        "--name-only",
    ).stdout.splitlines()
    forbidden = (
        "re/.cache/",
        "re/.staging/",
        "re/.locks/",
    )
    invalid = [
        path
        for path in staged
        if path.startswith(forbidden)
        or not (
            path in {"re/.gitignore", "re/index.json"}
            or path.startswith("re/sources/")
            or path.startswith("re/workspace/")
        )
    ]
    if invalid:
        raise ValueError(
            "refusing RE commit with non-durable staged paths: " + ", ".join(invalid)
        )
    if not staged:
        return
    run_git(
        project_root,
        "commit",
        "-m",
        f"docs(re): publish workspace reverse engineering generation {generation}",
    )


# ── spec subcommands ──────────────────────────────────────────────────────────

def _cmd_spec(args: list[str]) -> None:
    if not args or args[0] in ("-h", "--help"):
        print(
            "Usage: echelon spec <subcommand> [args...]\n\n"
            "  run <description> [--mode semi|banzai|guided] [--reset] [--perfectionist]\n"
            "                    [--message <text>] [--next-phase <id>]\n"
            "                    [--target <source-id-or-path>]... [--re-source <source-id-or-re-path>]... [--init]\n"
            "                    [--ignore-re] [--stash | --discard --confirm]\n"
            "                                      Run Phase A squad spec authoring\n"
            "                                      --perfectionist: Exhaustive Cartographer authoring\n"
            "  status                              Show current run state and next action\n"
            "  continue [--mode semi|banzai|guided]\n"
            "                                      Run the next no-input Phase A recovery action\n"
            "  resume <answers>                    Answer escalation questions from a blocked run\n"
            "  add-input --input <role:path>...     Add evidence to a parked investigation run\n"
            "  resolve ISS-<n> <decision>          Record one issue decision and run its targeted repair\n"
            "  rewind <phase-id> [--commit <sha>] [--next-phase <phase-id>]\n"
            "                                      Rewind the active squad run to a checkpoint\n"
            "  repair-traceability [--confirm]     Remove safely-prunable contextual task references\n"
            "  switch <spec-or-run-id> [--stash | --discard --confirm]\n"
            "                    [--restore-stash] Select a checkpointed Phase A spec run\n"
            "  drop-target <spec_id> <target> --confirm\n"
            "                                      Remove an unused target and re-plan tasks\n"
            "  retarget <spec_id> --target <source-id-or-path>... [--confirm]\n"
            "                                      Destructively replace all implementation targets\n"
            "  checkpoint list|accept|commit [--spec <id>] [--phase <phase-id>]\n"
            "                                      Manage Phase A/spec checkpoints\n"
            "  artifacts <spec_id>                 Generate specs/<id>/ARTIFACTS.md\n"
            "  verify <spec_id> [--reconcile] [--dry-run]\n"
            "                                      Audit implementation against spec\n"
            "  reopen <spec_id> [from=<report>]    Reopen spec from fulfillment gaps\n"
            "  bugfix <spec_id> <description>      Diagnose and plan a bugfix\n"
            "  change <spec_id> <description>      Plan a scope change\n",
        )
        sys.exit(0)
    subcmd = args[0]
    if subcmd == "target":
        _cmd_spec_target(args[1:])
    elif subcmd == "run":
        _cmd_spec_run(args[1:])
    elif subcmd == "status":
        _cmd_status(Path.cwd())
    elif subcmd == "continue":
        _cmd_spec_continue(args[1:])
    elif subcmd == "resume":
        _cmd_spec_resume(args[1:])
    elif subcmd == "add-input":
        _cmd_spec_add_input(args[1:])
    elif subcmd == "resolve":
        project_root = Path.cwd()
        ext_dir = _installed_extension_or_exit(project_root)
        _require_provider_capability("echelon spec resolve", ProviderCapability.ARTIFACT, project_dir=project_root)
        _cmd_spec_resolve(args[1:], project_root=project_root, ext_dir=ext_dir)
    elif subcmd == "rewind":
        _cmd_rewind(args[1:], project_root=Path.cwd())
    elif subcmd == "repair-traceability":
        _cmd_repair_traceability(args[1:], project_root=Path.cwd())
    elif subcmd == "switch":
        from echelon.spec_switch_cli import run_spec_switch_command

        exit_code = run_spec_switch_command(args[1:], project_root=Path.cwd())
        if exit_code:
            sys.exit(exit_code)
    elif subcmd == "drop-target":
        _cmd_drop_target(args[1:], project_root=Path.cwd())
    elif subcmd == "retarget":
        _cmd_spec_retarget(args[1:])
    elif subcmd == "checkpoint":
        from echelon.checkpoint_cli import run_checkpoint_command

        run_checkpoint_command(args[1:], project_root=Path.cwd())
    elif subcmd == "artifacts":
        _cmd_artifacts(args[1:])
    elif subcmd == "verify":
        _dispatch_skill_command("verify-spec", args[1:])
    elif subcmd == "amend":
        _cmd_spec_amend(args[1:])
    elif subcmd in {"bugfix", "change", "reopen"}:
        _dispatch_skill_command(subcmd, args[1:])
    else:
        print(f"echelon spec: unknown subcommand '{subcmd}'\n", file=sys.stderr)
        sys.exit(1)


def _installed_extension_or_exit(project_root: Path) -> Path:
    runtime = project_root / ".echelon" / "runtime"
    if not (runtime / "workflow" / "definition.yaml").is_file():
        print(
            f"✗ Echelon runtime not installed: {runtime}\n"
            "  Run: echelon workspace migrate-to-prosaic",
            file=sys.stderr,
        )
        sys.exit(1)
    return runtime


def _installed_phase_runtime_or_exit(project_root: Path) -> Path:
    """Return the complete deployed Prosaic runtime for Phase A."""
    runtime = project_root / ".echelon" / "runtime"
    prose = project_root / ".echelon" / "prosaic" / "subagents"
    if (runtime / "workflow" / "definition.yaml").is_file() and prose.is_dir():
        from harness.workflow_validator import validate_deployed_phase_runtime

        report = validate_deployed_phase_runtime(
            definition_path=runtime / "workflow" / "definition.yaml"
        )
        if report.ok:
            return runtime
        print(
            "✗ Echelon Phase A runtime is incompatible with this controller.\n"
            f"{report.format()}\n"
            "  Run: echelon workspace migrate-to-prosaic",
            file=sys.stderr,
        )
        sys.exit(1)
    print(
        "✗ Echelon runtime not installed.\n"
        "  Run: echelon workspace migrate-to-prosaic\n"
            "  Or, for a new workspace: echelon workspace init",
        file=sys.stderr,
    )
    sys.exit(1)


def _installed_re_runtime_or_exit(project_root: Path) -> tuple[Path, Path | None]:
    """Return deployed RE runtime assets and Prosaic agents."""
    runtime = project_root / ".echelon" / "runtime"
    prose = project_root / ".echelon" / "prosaic" / "subagents"
    if (runtime / "workflow" / "definition.yaml").is_file() and prose.is_dir():
        return runtime, prose
    print(
        "✗ Echelon runtime not installed.\n"
        "  Run: echelon workspace migrate-to-prosaic\n"
            "  Or, for a new workspace: echelon workspace init",
        file=sys.stderr,
    )
    sys.exit(1)


def _cmd_workspace_migrate_to_prosaic(project_root: Path) -> None:
    """Deploy and validate Prosaic without deleting legacy workspace state."""
    from echelon.prosaic_packages import ProsaicBundleInstallError, install_prosaic_bundle
    from echelon.constitution import migrate_legacy_constitution
    from echelon.deploy_state_migration import (
        DeployStateMigrationError,
        migrate_legacy_deploy_state,
    )
    from harness.phase_graph import load_workspace_phase_graph

    config_path = project_root / ".echelon" / "config.yml"
    legacy_config = project_root / ".specify" / "extensions" / "echelon" / "echelon-config.yml"
    if not config_path.exists():
        if not legacy_config.is_file():
            print(
                f"✗ Project config not found: {config_path}\n"
                f"  Legacy config also missing: {legacy_config}",
                file=sys.stderr,
            )
            raise SystemExit(1)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(legacy_config, config_path)
        print(f"✓ copied canonical config from {legacy_config}")

    if _normalize_legacy_re_output_directory(config_path):
        print("✓ normalized standalone RE output: .echelon/re")

    try:
        install_prosaic_bundle(project_root)
    except ProsaicBundleInstallError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    try:
        from echelon.speckit_git import disable_speckit_git

        legacy_git = disable_speckit_git(project_root)
    except Exception as exc:
        print(f"✗ Could not disable legacy Spec-Kit Git integration: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    try:
        graph, runtime_root = load_workspace_phase_graph(project_root)
    except Exception as exc:
        print(f"✗ Prosaic bundle validation failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    if not graph.all_phase_ids():
        print("✗ Prosaic bundle validation failed: workflow has no phases", file=sys.stderr)
        raise SystemExit(1)
    _ensure_prosaic_workspace_ignores(project_root)
    migrated_constitution = migrate_legacy_constitution(project_root)
    try:
        migrated_deploy_state = migrate_legacy_deploy_state(project_root)
    except DeployStateMigrationError as exc:
        print(f"✗ Could not migrate deployment state: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    print("✓ Prosaic migration complete")
    print(f"  prose:   {project_root / '.echelon' / 'prosaic'}")
    print(f"  runtime: {runtime_root}")
    print(f"  phases:  {len(graph.all_phase_ids())}")
    if migrated_constitution is not None:
        print(f"  constitution: {migrated_constitution}")
    if migrated_deploy_state.migrated:
        print(f"  deployment state: {migrated_deploy_state.global_state_path}")
    if legacy_git.installed:
        print("  legacy Git integration: disabled")
    print("  legacy .specify/extensions/echelon was left unchanged")


def _normalize_legacy_re_output_directory(config_path: Path) -> bool:
    """Move only the former default RE state path into Echelon ownership."""
    text = config_path.read_text(encoding="utf-8")
    normalized, replacements = re.subn(
        r"(?m)^(\s*directory:\s*)(['\"]?)\.specify/echelon/re\2(\s*(?:#.*)?)$",
        r"\1\2.echelon/re\2\3",
        text,
    )
    if replacements == 0:
        return False
    config_path.write_text(normalized, encoding="utf-8")
    return True


def _ensure_prosaic_workspace_ignores(project_root: Path) -> None:
    """Ignore generated Prosaic deployment state without rewriting user rules."""
    ignore_path = project_root / ".gitignore"
    existing = ignore_path.read_text(encoding="utf-8") if ignore_path.exists() else ""
    lines = existing.splitlines()
    required = (
        "/.echelon/re/",
        "/.echelon/runtime/",
        "/.echelon/packages/",
        "/.echelon/prosaic/",
        "/.prosaic-manifest.json",
        "/.prosaic-backups/",
    )
    missing = [line for line in required if line not in lines]
    if not missing:
        return
    suffix = "" if not existing or existing.endswith("\n") else "\n"
    ignore_path.write_text(
        f"{existing}{suffix}" + "".join(f"{line}\n" for line in missing),
        encoding="utf-8",
    )


def _cmd_spec_amend(args: list[str]) -> None:
    """Prepare a pre-build amendment without switching the caller checkout."""
    if args and args[0] == "status":
        if len(args) != 2:
            print("Usage: echelon spec amend status <amendment-id-or-spec-id>", file=sys.stderr)
            raise SystemExit(2)
        from echelon.spec_amendment import load_amendment_state

        print(json.dumps(load_amendment_state(Path.cwd(), args[1]), indent=2))
        return
    if args and args[0] == "abandon":
        if len(args) != 2:
            print("Usage: echelon spec amend abandon <amendment-id-or-spec-id>", file=sys.stderr)
            raise SystemExit(2)
        from echelon.spec_amendment import abandon_amendment

        state = abandon_amendment(Path.cwd(), args[1])
        print(f"Amendment abandoned: {state['amendment_id']}")
        return
    if len(args) < 2:
        print(
            "Usage: echelon spec amend <spec-id> <description> "
            "[--input requirement:<path>|reference:<path>]... [--dry-run]",
            file=sys.stderr,
        )
        raise SystemExit(2)
    from echelon.spec_amendment import prepare_amendment

    result = prepare_amendment(Path.cwd(), args)
    if result.dry_run:
        print(
            f"Amendment dry run: {result.amendment_id}\n"
            f"  baseline: {result.baseline.branch}@{result.baseline.commit}\n"
            "  no worktree or amendment state was created"
        )
        return
    assert result.worktree is not None and result.state_path is not None
    print(
        f"Amendment prepared: {result.amendment_id}\n"
        f"  baseline: {result.baseline.branch}@{result.baseline.commit}\n"
        f"  worktree: {result.worktree.path}\n"
        f"  state: {result.state_path}\n"
        "  No canonical spec, plan, or task artifact has been changed.\n"
        "  Next: inspect change-request.md and impact.md in the amendment worktree."
    )


def _cmd_spec_run(args: list[str]) -> None:
    if os.environ.get("ECHELON_SQUAD_ACTIVE"):
        print(
            "✗ echelon spec run: refusing nested invocation — already inside a squad "
            "agent dispatch (ECHELON_SQUAD_ACTIVE is set).\n"
            "  Squad agents must not call 'echelon spec run'. "
            "Return echelon_result: from your agent instead.",
            file=sys.stderr,
        )
        sys.exit(1)
    project_root = Path.cwd()
    ext_dir = _installed_phase_runtime_or_exit(project_root)
    cfg_file = _project_echelon_config(project_root)
    if not cfg_file.exists():
        print(
            f"✗ Project not initialized — config not found: {cfg_file}\n"
            "  Run: echelon workspace init",
            file=sys.stderr,
        )
        sys.exit(1)
    _require_provider_capability("echelon spec run", ProviderCapability.ARTIFACT, project_dir=project_root)
    with _spec_summary_session(project_root, "echelon spec run"):
        _cmd_run(args, project_root=project_root, ext_dir=ext_dir)


def _cmd_spec_retarget(args: list[str]) -> None:
    """Preview or prepare a destructive complete target-set replacement."""
    project_root = Path.cwd()
    try:
        from echelon.spec_retarget import RetargetError
        from echelon.spec_retarget_cli import run_spec_retarget_command

        result = run_spec_retarget_command(args, project_root)
    except RetargetError as exc:
        print(f"✗ echelon spec retarget: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    if not result.applied:
        return
    ext_dir = _installed_phase_runtime_or_exit(project_root)
    run_args = [result.original_user_message, "--mode", result.autonomy_mode]
    for target in result.replacement_targets:
        run_args.extend(("--target", target))
    for source in result.explicit_re_sources:
        run_args.extend(("--re-source", source))
    if result.ignore_re:
        run_args.append("--ignore-re")
    _cmd_run(run_args, project_root=project_root, ext_dir=ext_dir)


def _cmd_spec_continue(args: list[str]) -> None:
    project_root = Path.cwd()
    ext_dir = _installed_phase_runtime_or_exit(project_root)
    _require_provider_capability("echelon spec continue", ProviderCapability.ARTIFACT, project_dir=project_root)
    token = _SPEC_SUMMARY_COMMAND.set("echelon spec continue")
    try:
        with _spec_summary_session(project_root, "echelon spec continue"):
            _cmd_continue(args, project_root=project_root, ext_dir=ext_dir)
    finally:
        _SPEC_SUMMARY_COMMAND.reset(token)


def _cmd_spec_resume(args: list[str]) -> None:
    if os.environ.get("ECHELON_SQUAD_ACTIVE"):
        print(
            "✗ echelon spec resume: refusing nested invocation (ECHELON_SQUAD_ACTIVE is set).",
            file=sys.stderr,
        )
        sys.exit(1)
    project_root = Path.cwd()
    ext_dir = _installed_phase_runtime_or_exit(project_root)
    _require_provider_capability("echelon spec resume", ProviderCapability.ARTIFACT, project_dir=project_root)
    token = _SPEC_SUMMARY_COMMAND.set("echelon spec resume")
    try:
        with _spec_summary_session(project_root, "echelon spec resume"):
            _cmd_resume(args, project_root=project_root, ext_dir=ext_dir)
    finally:
        _SPEC_SUMMARY_COMMAND.reset(token)


def _cmd_spec_add_input(args: list[str]) -> None:
    from echelon.product_inputs import ProductInputError
    from echelon.spec_add_input import SpecAddInputError, add_input_to_active_run

    input_values: list[str] = []
    i = 0
    while i < len(args):
        if args[i] == "--input":
            if i + 1 >= len(args):
                print("✗ echelon spec add-input: --input requires role:path", file=sys.stderr)
                raise SystemExit(2)
            input_values.append(args[i + 1].strip())
            i += 2
        elif args[i].startswith("--input="):
            input_values.append(args[i].split("=", 1)[1].strip())
            i += 1
        else:
            print(
                f"✗ echelon spec add-input: unknown argument {args[i]!r}",
                file=sys.stderr,
            )
            raise SystemExit(2)
    if not input_values:
        print(
            "Usage: echelon spec add-input --input reference:<path> [--input reference:<path>...]",
            file=sys.stderr,
        )
        raise SystemExit(2)
    try:
        result = add_input_to_active_run(Path.cwd(), input_values)
    except (ProductInputError, SpecAddInputError) as exc:
        print(f"✗ echelon spec add-input: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    _banner(
        "INPUT ADDED" if result.added_count else "INPUT ALREADY DECLARED",
        [
            ("Run", result.run_dir.name),
            ("Attachment", result.attachment_id),
            ("Added resources", str(result.added_count)),
            ("Duplicate resources", str(result.duplicate_count)),
            (
                "Original inputs",
                _format_product_input_declarations(result.original_declarations),
            ),
            (
                "Attached inputs",
                _format_product_input_declarations(result.attached_declarations),
            ),
            ("Next", result.next_command),
        ],
    )


def _format_product_input_declarations(
    declarations: Sequence[Mapping[str, object]],
) -> str:
    rendered = [
        f"{item.get('role')}:{item.get('location')}"
        for item in declarations
        if isinstance(item, Mapping)
    ]
    return ", ".join(rendered) if rendered else "(none)"


def _run_spec_target_git(
    repo: Path, args: list[str], *, check: bool = True
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=check,
    )


def _is_git_repo(path: Path) -> bool:
    marker = path / ".git"
    return marker.is_dir() or marker.is_file()


def _git_has_head_commit(repo: Path) -> bool:
    result = _run_spec_target_git(repo, ["rev-parse", "--verify", "HEAD"], check=False)
    return result.returncode == 0


def _git_branch_exists(repo: Path, branch: str) -> bool:
    result = _run_spec_target_git(
        repo, ["rev-parse", "--verify", f"refs/heads/{branch}"], check=False
    )
    return result.returncode == 0


def _prepare_spec_target_repo(workspace_root: Path, spec_dir: Path, repo: str) -> list[str]:
    target = Path(repo).expanduser()
    if not target.is_absolute():
        target = workspace_root / target

    messages: list[str] = []
    try:
        if target.exists() and not target.is_dir():
            raise RuntimeError(f"target path exists but is not a directory: {target}")

        if not target.exists():
            target.mkdir(parents=True)
            messages.append(f"Created target directory: {repo}")

        if not _is_git_repo(target):
            init = subprocess.run(
                ["git", "init", "-b", "main", str(target)],
                capture_output=True,
                text=True,
                check=False,
            )
            if init.returncode != 0:
                subprocess.run(
                    ["git", "init", str(target)],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                _run_spec_target_git(target, ["branch", "-M", "main"])
            messages.append(f"Initialized target repo: {repo}")

        if not _git_has_head_commit(target):
            _run_spec_target_git(target, ["symbolic-ref", "HEAD", "refs/heads/main"])
            _run_spec_target_git(
                target,
                [
                    "-c",
                    "user.name=Echelon",
                    "-c",
                    "user.email=echelon@example.invalid",
                    "commit",
                    "--allow-empty",
                    "-m",
                    "chore: initialize target repository",
                ],
            )
            messages.append(
                "Created initial target commit: chore: initialize target repository"
            )

        feature_branch = spec_dir.name
        if _git_branch_exists(target, feature_branch):
            messages.append(f"Feature branch already exists: {feature_branch}")
        else:
            _run_spec_target_git(target, ["branch", feature_branch])
            messages.append(f"Created feature branch: {feature_branch}")
    except (subprocess.CalledProcessError, OSError, RuntimeError) as exc:
        if isinstance(exc, subprocess.CalledProcessError):
            detail = (exc.stderr or exc.stdout or str(exc)).strip()
        else:
            detail = str(exc)
        print(
            f"✗ Could not initialize target repo {repo!r}.\n"
            f"  Error: {detail}",
            file=sys.stderr,
        )
        sys.exit(1)

    return messages


def _commit_initialized_workspace_sources(
    workspace_root: Path,
    *,
    run_id: str,
    retry_command: str,
) -> str:
    """Commit the exact source-registry mutation before squad dispatch."""
    from echelon.commit_messages import EchelonCommitMetadata, build_echelon_commit_message

    config_path = ".echelon/config.yml"
    message = build_echelon_commit_message(
        "chore: register workspace sources",
        EchelonCommitMetadata(
            origin="workspace",
            action="source-register",
            run_id=run_id,
        ),
    )
    try:
        tracked_status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=workspace_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        changed_paths = {
            line[3:].split(" -> ")[-1]
            for line in tracked_status
            if len(line) >= 4
        }
        if changed_paths != {config_path}:
            observed = ", ".join(sorted(changed_paths)) or "none"
            raise RuntimeError(
                "source registration did not own the exact tracked change set; "
                f"observed: {observed}"
            )
        subprocess.run(
            ["git", "add", "--", config_path],
            cwd=workspace_root,
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Echelon",
                "-c",
                "user.email=echelon-workspace@example.invalid",
                "commit",
                "--only",
                "-m",
                message,
                "--",
                config_path,
            ],
            cwd=workspace_root,
            check=True,
            capture_output=True,
            text=True,
        )
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD^{commit}"],
            cwd=workspace_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError, RuntimeError) as exc:
        if isinstance(exc, subprocess.CalledProcessError):
            detail = (exc.stderr or exc.stdout or str(exc)).strip()
        else:
            detail = str(exc)
        print(
            "✗ Could not commit the initialized workspace source registry.\n"
            f"  Error: {detail}\n"
            "  Fix: git add .echelon/config.yml && "
            "git commit -m 'chore: register workspace sources'\n"
            f"  Then: {retry_command}",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc

    print(f"Committed workspace source registry: {commit[:12]}")
    return commit


def _cmd_spec_target(args: list[str]) -> None:
    print(
        "✗ echelon spec target no longer mutates generated specifications.\n"
        "  Implementation targets must be declared when authoring begins:\n"
        "    echelon spec run <description> --target <source-path> "
        "[--target <source-path> ...]\n"
        "  Changing targets afterward invalidates target-dependent artifacts; "
        "start a new spec run instead.",
        file=sys.stderr,
    )
    raise SystemExit(2)


def _cmd_spec_targets(args: list[str]) -> None:
    """Display every canonical task grouped by its explicit source target."""
    if len(args) != 1:
        print(
            "echelon spec targets: usage: echelon spec targets <spec_id>",
            file=sys.stderr,
        )
        sys.exit(1)

    from harness.spec_frontmatter import find_spec_dir, read_targets
    from harness.task_targets import analyze_task_targets

    spec_id = args[0]
    spec_dir = find_spec_dir(spec_id, Path.cwd())
    if spec_dir is None:
        print(f"✗ Spec '{spec_id}' not found (searched from {Path.cwd()})", file=sys.stderr)
        sys.exit(1)

    tasks_file = spec_dir / "tasks.md"
    if not tasks_file.is_file():
        print(
            f"✗ Spec {spec_dir.name}: canonical tasks file not found: {tasks_file}",
            file=sys.stderr,
        )
        sys.exit(1)

    analysis = analyze_task_targets(tasks_file.read_text(encoding="utf-8"))

    def normalize_target(value: str) -> str:
        normalized = str(value).strip().replace("\\", "/")
        while normalized.startswith("./"):
            normalized = normalized[2:]
        return normalized.rstrip("/") or "."

    declared_targets = tuple(
        sorted(
            {
                normalize_target(target)
                for target in read_targets(spec_dir)
                if str(target).strip()
            }
        )
    )
    declared_set = set(declared_targets)
    referenced_targets = set(analysis.target_tasks)
    for targets in analysis.cross_target_tasks.values():
        referenced_targets.update(targets)
    missing_targets = tuple(sorted(referenced_targets - declared_set))
    unreferenced_targets = tuple(sorted(declared_set - referenced_targets))

    def task_line(task_id: str, *, target_suffix: str = "") -> str:
        title = analysis.task_titles.get(task_id, "")
        label = f"{task_id}  {title}" if title else task_id
        return f"  {label}{target_suffix}"

    print(f"Spec: {spec_dir.name}")
    print("Declared targets:")
    if declared_targets:
        for target in declared_targets:
            print(f"  {target}")
    else:
        print("  (none)")

    for target, task_ids in analysis.target_tasks.items():
        status = "declared" if target in declared_set else "missing declaration"
        print()
        print(f"{target} [{status}]")
        for task_id in task_ids:
            print(task_line(task_id))

    if analysis.unowned_tasks:
        print()
        print("UNOWNED")
        for task_id in analysis.unowned_tasks:
            print(task_line(task_id))

    if analysis.cross_target_tasks:
        print()
        print("CROSS-TARGET")
        for task_id, targets in analysis.cross_target_tasks.items():
            print(task_line(task_id, target_suffix=f" [{', '.join(targets)}]"))

    non_cross_path_mismatches = {
        task_id: mismatch
        for task_id, mismatch in analysis.path_target_mismatches.items()
        if task_id not in analysis.cross_target_tasks
    }
    if non_cross_path_mismatches:
        print()
        print("TARGET/PATH MISMATCH")
        for task_id, (target, paths) in non_cross_path_mismatches.items():
            print(
                f"  mismatch {task_id}: target={target}; paths={', '.join(paths)}"
            )

    if missing_targets:
        print()
        print("Missing declared targets:")
        for target in missing_targets:
            print(f"  {target}")

    if unreferenced_targets:
        print()
        print("Declared but unreferenced targets:")
        for target in unreferenced_targets:
            print(f"  {target}")

    assigned_count = sum(len(task_ids) for task_ids in analysis.target_tasks.values())
    print()
    print(
        f"Tasks: {len(analysis.all_task_ids)} total; {assigned_count} assigned; "
        f"{len(analysis.unowned_tasks)} unowned; "
        f"{len(analysis.cross_target_tasks)} cross-target"
    )

    invalid_reasons: list[str] = []
    if missing_targets:
        invalid_reasons.append(f"{len(missing_targets)} missing declaration(s)")
    if unreferenced_targets:
        invalid_reasons.append(f"{len(unreferenced_targets)} unreferenced declaration(s)")
    if analysis.unowned_tasks:
        invalid_reasons.append(f"{len(analysis.unowned_tasks)} unowned task(s)")
    if analysis.cross_target_tasks:
        invalid_reasons.append(
            f"{len(analysis.cross_target_tasks)} cross-target task(s)"
        )
    if analysis.path_target_mismatches:
        invalid_reasons.append(
            f"{len(analysis.path_target_mismatches)} target/path mismatch(es)"
        )

    if invalid_reasons:
        print("Result: invalid — " + ", ".join(invalid_reasons))
        sys.exit(2)
    print("Result: valid")


def _cmd_workspace(args: list[str]) -> None:
    if not args or args[0] in ("-h", "--help"):
        print(
            "Usage: echelon workspace <subcommand> [args...]\n\n"
            "  init [--llm <provider>] [--openai-base-url <url>] [--openai-model <model>]\n"
            "       [--openai-api-key-file <path>|--openai-api-key-env <env>]\n"
            "       [--allow-unsafe-host-execution|--no-unsafe-host-execution]\n"
            "                            One-time project setup (no LLM)\n"
            "                            Installs the Echelon Prosaic/runtime bundle by default\n"
            "  doctor                    Validate workspace/source/runtime contract\n"
            "  migrate-to-prosaic        Deploy and validate Prosaic runtime without deleting legacy files\n"
            "  sources sync [--write]    Sync discovered sources/* roots into config\n"
            "  migrate [--write]         Copy legacy config, ignore runtime state, stage fixes\n"
            "          [--commit] [--message <msg>]\n"
            "                            Apply and commit migration changes\n",
            file=sys.stderr,
        )
        sys.exit(0)

    subcmd = args[0]
    if subcmd == "migrate-to-prosaic":
        if len(args) != 1:
            print("Usage: echelon workspace migrate-to-prosaic", file=sys.stderr)
            sys.exit(1)
        _cmd_workspace_migrate_to_prosaic(Path.cwd())
        return
    if subcmd == "init":
        init_args = args[1:]
        if any(arg in {"-h", "--help"} for arg in init_args):
            print(
                "Usage: echelon workspace init "
                "[--llm <provider>] "
                "[--openai-base-url <url>] [--openai-model <model>] "
                "[--openai-api-key-file <path>|--openai-api-key-env <env>] "
                "[--allow-unsafe-host-execution|--no-unsafe-host-execution]\n\n"
                "  --llm <provider>              Persist the workspace AI CLI provider\n"
                "  --openai-base-url <url>       Persist OpenAI-compatible API base URL\n"
                "  --openai-model <model>        Persist OpenAI-compatible model name\n"
                "  --openai-api-key-file <path>  Persist file path containing API key\n"
                "  --openai-api-key-env <env>    Persist API key environment variable name\n"
                "  --allow-unsafe-host-execution  Write local approval for AI CLI "
                "permission-bypass flags\n"
                "  --no-unsafe-host-execution     Do not prompt or write local approval",
                file=sys.stderr,
            )
            sys.exit(0)
        parsed_init_args: list[str] = []
        llm_cli: str | None = None
        openai_base_url: str | None = None
        openai_model: str | None = None
        openai_api_key_file: str | None = None
        openai_api_key_env: str | None = None
        from harness.config import VALID_LLM_CLIS

        valid_llm_clis = VALID_LLM_CLIS
        i = 0
        while i < len(init_args):
            arg = init_args[i]
            if arg in {"--llm", "--llm-cli"}:
                if i + 1 >= len(init_args):
                    print(f"echelon workspace init: {arg} requires a provider", file=sys.stderr)
                    sys.exit(1)
                llm_cli = init_args[i + 1]
                i += 2
            elif arg.startswith("--llm="):
                llm_cli = arg.split("=", 1)[1]
                i += 1
            elif arg.startswith("--llm-cli="):
                llm_cli = arg.split("=", 1)[1]
                i += 1
            elif arg == "--openai-base-url":
                if i + 1 >= len(init_args):
                    print(f"echelon workspace init: {arg} requires a URL", file=sys.stderr)
                    sys.exit(1)
                openai_base_url = init_args[i + 1]
                i += 2
            elif arg.startswith("--openai-base-url="):
                openai_base_url = arg.split("=", 1)[1]
                i += 1
            elif arg == "--openai-model":
                if i + 1 >= len(init_args):
                    print(f"echelon workspace init: {arg} requires a model", file=sys.stderr)
                    sys.exit(1)
                openai_model = init_args[i + 1]
                i += 2
            elif arg.startswith("--openai-model="):
                openai_model = arg.split("=", 1)[1]
                i += 1
            elif arg == "--openai-api-key-file":
                if i + 1 >= len(init_args):
                    print(f"echelon workspace init: {arg} requires a path", file=sys.stderr)
                    sys.exit(1)
                openai_api_key_file = init_args[i + 1]
                i += 2
            elif arg.startswith("--openai-api-key-file="):
                openai_api_key_file = arg.split("=", 1)[1]
                i += 1
            elif arg == "--openai-api-key-env":
                if i + 1 >= len(init_args):
                    print(f"echelon workspace init: {arg} requires an environment variable", file=sys.stderr)
                    sys.exit(1)
                openai_api_key_env = init_args[i + 1]
                i += 2
            elif arg.startswith("--openai-api-key-env="):
                openai_api_key_env = arg.split("=", 1)[1]
                i += 1
            elif arg in {"--allow-unsafe-host-execution", "--no-unsafe-host-execution"}:
                parsed_init_args.append(arg)
                i += 1
            else:
                print(f"echelon workspace init: unknown option '{arg}'\n", file=sys.stderr)
                print(
                    "Usage: echelon workspace init "
                    "[--llm <provider>] "
                    "[--openai-base-url <url>] [--openai-model <model>] "
                    "[--openai-api-key-file <path>|--openai-api-key-env <env>] "
                    "[--allow-unsafe-host-execution|--no-unsafe-host-execution]",
                    file=sys.stderr,
                )
                sys.exit(1)
        if llm_cli and llm_cli not in valid_llm_clis:
            print(
                f"echelon workspace init: invalid --llm {llm_cli!r}; expected one of: "
                f"{', '.join(sorted(valid_llm_clis))}",
                file=sys.stderr,
            )
            sys.exit(1)
        if (
            "--allow-unsafe-host-execution" in parsed_init_args
            and "--no-unsafe-host-execution" in parsed_init_args
        ):
            print(
                "echelon workspace init: choose only one of "
                "--allow-unsafe-host-execution or --no-unsafe-host-execution",
                file=sys.stderr,
            )
            sys.exit(1)
        allow_unsafe = "--allow-unsafe-host-execution" in parsed_init_args
        if "--no-unsafe-host-execution" not in parsed_init_args and not allow_unsafe:
            allow_unsafe = _wants_unsafe_host_execution_interactively()
        project_root = Path.cwd()
        init_kwargs = {
            "allow_unsafe_host_execution": allow_unsafe,
            "llm_cli": llm_cli,
            "openai_base_url": openai_base_url,
            "openai_model": openai_model,
            "openai_api_key_file": openai_api_key_file,
            "openai_api_key_env": openai_api_key_env,
        }
        _cmd_init(project_root, **init_kwargs)
        _maybe_bootstrap_workspace_git(project_root)
        return

    if subcmd == "doctor":
        from echelon.workspace_git_migration import doctor_workspace

        result = doctor_workspace(Path.cwd())
        print(f"Workspace: {result.workspace_root}")
        print(f"Buildable: {'yes' if result.buildable else 'no'}")
        if not result.findings:
            print("Findings: none")
        else:
            print("Findings:")
            for finding in result.findings:
                path = f" [{finding.path}]" if finding.path else ""
                print(f"  {finding.severity.upper()} {finding.code}{path}: {finding.message}")
        if result.has_errors:
            sys.exit(1)
        return

    if subcmd == "sources":
        sources_args = args[1:]
        if not sources_args or sources_args[0] in {"-h", "--help"}:
            print(
                "Usage: echelon workspace sources sync [--write]\n\n"
                "  Discover implementation roots under sources/ and sync them into "
                ".echelon/config.yml.\n"
                "  Dry-run by default; pass --write to add missing roots and remove stale "
                "sources/* entries.",
                file=sys.stderr,
            )
            sys.exit(0)
        if sources_args[0] != "sync":
            print(
                f"echelon workspace sources: unknown subcommand '{sources_args[0]}'\n",
                file=sys.stderr,
            )
            sys.exit(1)
        write = False
        for arg in sources_args[1:]:
            if arg == "--write":
                write = True
            else:
                print(f"echelon workspace sources sync: unknown option '{arg}'", file=sys.stderr)
                sys.exit(1)
        from echelon.workspace_sources import sync_sources_config

        result = sync_sources_config(Path.cwd(), write=write)

        def label(values: tuple[str, ...]) -> str:
            return ", ".join(values) if values else "none"

        print(f"Config: {result.config_path}")
        print(f"Dry run: {'yes' if result.dry_run else 'no'}")
        print(f"discovered: {label(result.discovered)}")
        print(f"added: {label(result.added)}")
        print(f"removed: {label(result.removed)}")
        print(f"unchanged: {label(result.unchanged)}")
        if result.dry_run:
            print("Next: echelon workspace sources sync --write")
        else:
            print(f"updated: {'yes' if result.changed else 'no changes'}")
        return

    if subcmd == "migrate":
        from echelon.workspace_git_migration import main as migrate_main

        raise SystemExit(migrate_main([".", *args[1:]]))

    print(f"echelon workspace: unknown subcommand '{subcmd}'\n", file=sys.stderr)
    sys.exit(1)


def _cmd_artifacts(args: list[str]) -> None:
    if not args:
        print("echelon spec artifacts: missing spec_id", file=sys.stderr)
        sys.exit(1)

    from echelon.artifact_index import write_artifact_index
    from harness.spec_frontmatter import find_spec_dir

    spec_id = args[0]
    spec_dir = find_spec_dir(spec_id, Path.cwd())
    if spec_dir is None:
        print(f"✗ Spec not found: {spec_id}", file=sys.stderr)
        sys.exit(1)

    path = write_artifact_index(spec_dir)
    print(f"✓ Wrote artifact map: {path}")


from harness.stacks import (  # noqa: E402  (CLI command helpers)
    detect_stacks,
    detection_report_from_file,
    detection_report_to_yaml,
    load_stack_definitions,
    preflight_to_dict,
    render_detection_markdown,
    render_preflight_markdown,
    resolve_stacks,
    resolved_to_dict,
    run_stack_preflight,
    write_detection_report,
)
from harness.stacks.errors import StackError  # noqa: E402
from harness.stacks.paths import find_stack_extension_root  # noqa: E402
from echelon.stack_selection import (  # noqa: E402
    StackSelectionError,
    change_stack_selection,
    get_stack_selection,
)


def _cmd_stack(args: list[str], project_root: Path | None = None) -> None:
    project_root = project_root or Path.cwd()
    if not args or args[0] in {"-h", "--help", "help"}:
        print(
            "Usage:\n"
            "  echelon stack list [--json]\n"
            "  echelon stack detect [--target <path>] [--artifacts <path>] "
            "[--write] [--format text|yaml] [--json]\n"
            "  echelon stack preflight [--stack <id>] "
            "[--target-archetype <id>] [--from-detect <path>] [--probe-tools] [--json]\n"
            "  echelon stack selected [--json]\n"
            "  echelon stack enable <stack-id>... [--dry-run]\n"
            "  echelon stack disable <stack-id>... [--dry-run]\n"
            "  echelon stack select [<stack-id>...] [--dry-run]"
        )
        return

    subcmd = args[0]
    if subcmd == "list":
        _cmd_stack_list(args[1:], project_root=project_root)
        return

    if subcmd == "detect":
        _cmd_stack_detect(args[1:], project_root=project_root)
        return

    if subcmd == "preflight":
        _cmd_stack_preflight(args[1:], project_root=project_root)
        return

    if subcmd == "enable":
        _cmd_stack_selection_change("enable", args[1:], project_root=project_root)
        return

    if subcmd == "disable":
        _cmd_stack_selection_change("disable", args[1:], project_root=project_root)
        return

    if subcmd == "select":
        _cmd_stack_selection_change("select", args[1:], project_root=project_root)
        return

    if subcmd == "selected":
        _cmd_stack_selected(args[1:], project_root=project_root)
        return

    print(f"echelon stack: unknown subcommand '{subcmd}'", file=sys.stderr)
    sys.exit(1)


def _cmd_stack_selection_change(
    operation: str,
    args: list[str],
    *,
    project_root: Path,
) -> None:
    dry_run = "--dry-run" in args
    stack_ids = [arg for arg in args if arg != "--dry-run"]
    if operation != "select" and not stack_ids:
        print(f"echelon stack {operation}: requires at least one stack ID", file=sys.stderr)
        sys.exit(1)
    try:
        selection = change_stack_selection(
            project_root,
            stack_ids,
            _load_stack_definitions_for_project(project_root),
            operation=operation,
            dry_run=dry_run,
        )
    except (StackError, StackSelectionError) as exc:
        print(f"✗ {exc}", file=sys.stderr)
        sys.exit(1)
    prefix = "Dry run: " if dry_run else ""
    label = {"enable": "Enabled", "disable": "Disabled", "select": "Selected"}[operation]
    values = ", ".join(stack_ids if operation == "disable" else selection.explicit) or "none"
    print(f"{prefix}{label} stacks: {values}")
    if dry_run:
        import yaml

        print(yaml.safe_dump({"stacks": {"selected": selection.explicit}}, sort_keys=False).rstrip())
    if selection.local_override:
        print("Warning: .echelon/local.yml overrides stacks.selected.")


def _cmd_stack_selected(args: list[str], *, project_root: Path) -> None:
    if any(arg != "--json" for arg in args):
        print("echelon stack selected: only --json is supported", file=sys.stderr)
        sys.exit(1)
    try:
        selection = get_stack_selection(
            project_root,
            _load_stack_definitions_for_project(project_root),
        )
    except (StackError, StackSelectionError) as exc:
        print(f"✗ {exc}", file=sys.stderr)
        sys.exit(1)
    if "--json" in args:
        import json

        print(json.dumps(selection.__dict__, indent=2))
        return
    print(f"Explicit stacks: {', '.join(selection.explicit) or 'none'}")
    print(f"Effective stacks: {', '.join(selection.effective) or 'none'}")
    print(f"Resolved stacks: {', '.join(selection.resolved) or 'none'}")
    if selection.local_override:
        print("Warning: .echelon/local.yml overrides stacks.selected.")


def _cmd_stack_list(args: list[str], *, project_root: Path) -> None:
    json_output = False
    for arg in args:
        if arg == "--json":
            json_output = True
            continue
        print(f"echelon stack list: unknown argument '{arg}'", file=sys.stderr)
        sys.exit(1)

    definitions = _load_stack_definitions_for_project(project_root)
    if json_output:
        import json

        print(
            json.dumps(
                {
                    "stacks": [
                        _stack_definition_to_dict(definitions[stack_id])
                        for stack_id in sorted(definitions)
                    ]
                },
                indent=2,
            )
        )
        return

    print("Available Echelon stacks:")
    for stack_id in sorted(definitions):
        stack = definitions[stack_id]
        archetypes = ", ".join(stack.applies_to_archetypes)
        print(f"- {stack.id} ({stack.kind}; {archetypes}) {stack.name}")


def _cmd_stack_detect(args: list[str], *, project_root: Path) -> None:
    target = project_root
    artifact_roots: list[Path] = []
    write_report = False
    output_format = "text"

    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--target":
            index += 1
            if index >= len(args):
                print("echelon stack detect: --target requires a value", file=sys.stderr)
                sys.exit(1)
            target = _resolve_cli_path(project_root, args[index])
        elif arg.startswith("--target="):
            target = _resolve_cli_path(project_root, arg.split("=", 1)[1])
        elif arg == "--artifacts":
            index += 1
            if index >= len(args):
                print("echelon stack detect: --artifacts requires a value", file=sys.stderr)
                sys.exit(1)
            artifact_roots.append(_resolve_cli_path(project_root, args[index]))
        elif arg.startswith("--artifacts="):
            artifact_roots.append(_resolve_cli_path(project_root, arg.split("=", 1)[1]))
        elif arg == "--write":
            write_report = True
        elif arg == "--format":
            index += 1
            if index >= len(args):
                print("echelon stack detect: --format requires text or yaml", file=sys.stderr)
                sys.exit(1)
            output_format = args[index]
        elif arg.startswith("--format="):
            output_format = arg.split("=", 1)[1]
        elif arg == "--json":
            output_format = "json"
        else:
            print(f"echelon stack detect: unknown argument '{arg}'", file=sys.stderr)
            sys.exit(1)
        index += 1

    if output_format not in {"text", "yaml", "json"}:
        print("echelon stack detect: --format must be text or yaml", file=sys.stderr)
        sys.exit(1)

    try:
        definitions = _load_stack_definitions_for_project(project_root)
        report = detect_stacks(
            target=target,
            artifact_roots=artifact_roots,
            stack_definitions=definitions,
        )
    except StackError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        sys.exit(1)

    written = None
    if write_report:
        written = write_detection_report(report, project_root=project_root)

    if output_format == "json":
        import json

        print(json.dumps(report.to_dict(), indent=2))
    elif output_format == "yaml":
        print(detection_report_to_yaml(report).rstrip())
    else:
        print(render_detection_markdown(report).rstrip())
        if written is not None:
            rel_yaml = _relative_display_path(written.yaml_path, project_root)
            rel_markdown = _relative_display_path(written.markdown_path, project_root)
            print()
            print(f"Wrote detection report: {rel_yaml}")
            print(f"Wrote detection summary: {rel_markdown}")


def _cmd_stack_preflight(args: list[str], *, project_root: Path) -> None:
    (
        selected,
        target_archetypes,
        from_detect,
        probe_tools,
        json_output,
    ) = _parse_stack_preflight_args(args, project_root=project_root)
    if from_detect is not None:
        report = detection_report_from_file(from_detect)
        detected_selected, detected_archetypes = _stack_selection_from_detection(report)
        selected = _append_cli_unique(detected_selected, selected)
        target_archetypes = _append_cli_unique(detected_archetypes, target_archetypes)

    if not selected and from_detect is None:
        config = _load_cli_config(project_root)
        selected = list(config.stacks.selected)
        target_archetypes = target_archetypes or list(config.stacks.target_archetypes)

    if not selected:
        if from_detect is not None:
            message = "No adoptable stacks in detection report."
        else:
            message = "No Echelon stacks selected. Use --stack <id> or configure stacks.selected."
        if json_output:
            import json

            print(json.dumps({"status": "pass", "message": message, "selected": []}, indent=2))
        else:
            print(message)
        return

    try:
        definitions = _load_stack_definitions_for_project(project_root)
        resolved = resolve_stacks(
            selected,
            definitions,
            target_archetypes=set(target_archetypes) or None,
        )
    except StackError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        sys.exit(1)

    result = run_stack_preflight(resolved, probe_tools=probe_tools)

    if json_output:
        import json

        print(
            json.dumps(
                {
                    "resolved": resolved_to_dict(resolved),
                    "preflight": preflight_to_dict(result),
                },
                indent=2,
            )
        )
    else:
        print("Resolved Echelon stacks:")
        for stack_id in resolved.resolved_ids:
            print(f"- {stack_id}")
        print()
        print(render_preflight_markdown(result).rstrip())

    if result.has_errors:
        sys.exit(1)


def _parse_stack_preflight_args(
    args: list[str],
    *,
    project_root: Path,
) -> tuple[list[str], list[str], Path | None, bool, bool]:
    selected: list[str] = []
    target_archetypes: list[str] = []
    from_detect: Path | None = None
    probe_tools = False
    json_output = False

    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--stack":
            index += 1
            if index >= len(args):
                print("echelon stack preflight: --stack requires a value", file=sys.stderr)
                sys.exit(1)
            selected.append(args[index])
        elif arg.startswith("--stack="):
            selected.append(arg.split("=", 1)[1])
        elif arg == "--target-archetype":
            index += 1
            if index >= len(args):
                print(
                    "echelon stack preflight: --target-archetype requires a value",
                    file=sys.stderr,
                )
                sys.exit(1)
            target_archetypes.append(args[index])
        elif arg.startswith("--target-archetype="):
            target_archetypes.append(arg.split("=", 1)[1])
        elif arg == "--from-detect":
            index += 1
            if index >= len(args):
                print(
                    "echelon stack preflight: --from-detect requires a value",
                    file=sys.stderr,
                )
                sys.exit(1)
            from_detect = _resolve_cli_path(project_root, args[index])
        elif arg.startswith("--from-detect="):
            from_detect = _resolve_cli_path(project_root, arg.split("=", 1)[1])
        elif arg == "--probe-tools":
            probe_tools = True
        elif arg == "--json":
            json_output = True
        else:
            print(f"echelon stack preflight: unknown argument '{arg}'", file=sys.stderr)
            sys.exit(1)
        index += 1

    return selected, target_archetypes, from_detect, probe_tools, json_output


def _stack_selection_from_detection(report) -> tuple[list[str], list[str]]:
    config = report.suggested_config or {}
    stacks = config.get("stacks", {}) if isinstance(config, dict) else {}
    selected = stacks.get("selected", []) if isinstance(stacks, dict) else []
    target_archetypes = (
        stacks.get("target_archetypes", []) if isinstance(stacks, dict) else []
    )
    return _string_values(selected), _string_values(target_archetypes)


def _string_values(values) -> list[str]:
    if not isinstance(values, list):
        return []
    return [str(value).strip() for value in values if str(value).strip()]


def _append_cli_unique(first: list[str], second: list[str]) -> list[str]:
    result = list(first)
    for value in second:
        if value not in result:
            result.append(value)
    return result


def _resolve_cli_path(project_root: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return project_root / path


def _relative_display_path(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _load_stack_definitions_for_project(project_root: Path):
    return load_stack_definitions(
        extension_root=find_stack_extension_root(project_root),
        project_root=project_root,
    )


def _stack_definition_to_dict(stack) -> dict:
    return {
        "id": stack.id,
        "name": stack.name,
        "version": stack.version,
        "kind": stack.kind,
        "owner": stack.owner,
        "description": stack.description,
        "applies_to_archetypes": stack.applies_to_archetypes,
        "provides": stack.provides,
        "implies": stack.implies,
        "requirements": {
            "commands": stack.requires_commands,
            "registries": stack.requires_registries,
        },
        "detection": stack.detection.to_dict(),
        "tools": sorted(stack.tools),
    }


# ── Entry point ───────────────────────────────────────────────────────────

def main() -> None:
    args = sys.argv[1:]
    if args[:1] == ["help"]:
        args = ["--help"]
    if args[:1] in (["-v"], ["--version"]):
        print(f"echelon {CLI_VERSION}")
        return
    if args[:1] == ["version"]:
        print(f"echelon {CLI_VERSION}")
        return

    from click import ClickException
    from echelon.cli_app import run as run_typer_cli

    click_exceptions: tuple[type[BaseException], ...] = (ClickException,)
    try:
        from typer._click.exceptions import ClickException as TyperClickException

        click_exceptions = (ClickException, TyperClickException)
    except Exception:
        pass

    try:
        exit_code = run_typer_cli(args)
    except click_exceptions as exc:
        exc.show()
        sys.exit(exc.exit_code)
    if exit_code:
        sys.exit(exit_code)
