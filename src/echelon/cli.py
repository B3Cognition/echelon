#!/usr/bin/env python3
"""echelon CLI — deterministic entry points for echelon skills.

LLM commands read the corresponding skill markdown, inject arguments,
and invoke the configured LLM CLI so the LLM only executes the skill.

`init` is pure Python — no LLM involved.

Skill file locations by AI tool:
  Claude   : .claude/skills/speckit-echelon-<cmd>/[Ss]kill.md
  Copilot  : .github/agents/speckit.echelon.<cmd>.agent.md
  Opencode : .opencode/command/speckit.echelon.<cmd>.md
  Codex    : .claude/skills/speckit-echelon-<cmd>/[Ss]kill.md
Auto-detected from ECHELON_LLM (default: claude).
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from harness.gitops import runtime_extension_copy_ignore
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

# Maps CLI command → spec-kit skill base name (used to derive file paths).
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

CLI_VERSION = "3.1.0"
LEXICON_TASK_SPEC_REF_PATH = "lexicon_gate.artifacts.tasks.spec_ref"

from echelon.workspace_model import discover_workspace  # noqa: E402  (after stdlib imports)
from echelon.ui import banner as _banner  # noqa: E402  (after stdlib imports)


USAGE = f"""\
echelon {CLI_VERSION}

Usage: echelon <command> [args...]

Commands:
  workspace init [--llm <claude|codex|opencode|copilot>]
                    [--allow-unsafe-host-execution|--no-unsafe-host-execution]
                                            One-time project setup (no LLM)
  workspace doctor                          Check workspace/source/runtime contract
  workspace sources sync [--write]          Sync discovered sources/* roots into config
  workspace migrate [--write] [--commit] [--message <msg>]
                                            Migrate legacy workspace layout

  spec run <description> [--mode semi|banzai|guided] [--reset]
                    [--message <text>] [--next-phase <id>]
                    [--target <source-id-or-path>] [--init]
                    [--re-policy none|cached-only|changed|target-changed|target-only|refresh-all]
                                            Run Phase A squad spec authoring.
  spec status                               Show current run state, artifacts, cost, and next action.
  spec continue [--mode semi|banzai|guided] Run the next no-input Phase A recovery action.
  spec resume "<answers>"                   Answer escalation questions from a blocked run.
  spec rewind <phase-id>                    Rewind the active squad run to a safe checkpoint.
  spec checkpoint list|accept|commit [--spec <id>] [--phase <phase-id>]
                                            Manage Phase A/spec checkpoints.
  spec target <spec_id> <repo> [repo...] [--init]
                                            Set target repos in spec frontmatter.
                                            With --init, create/prepare target Git repo(s).
  spec artifacts <spec_id>                  Generate specs/<id>/ARTIFACTS.md.
  spec verify <spec_id> [--reconcile] [--dry-run]
                                            Audit implementation against spec.
  spec reopen <spec_id> [from=<report>]      Reopen spec from fulfillment gaps.
  spec bugfix <spec_id> <description>        Diagnose and plan a bugfix.
  spec change <spec_id> <description>        Plan a scope change.

  phase list                                List workflow phases available for manual replay.
  phase run <phase-id> [--spec <id>] [--mode semi|banzai|guided]
                    [--message <text>]
                                            Run one explicit phase through COMMANDER contracts.

  re publish <run-id> [--allow-partial] [--commit]
                                            Publish validated workspace RE output.

  benchmark list                            List experimental benchmark fixtures and variants.
  benchmark show [latest|<summary-path-or-run-dir>]
                                            Print saved benchmark scores.
  benchmark run <fixture> --variant <id> [--baseline-ref <ref>] [--dry-run]
                                            Run or print an artifact-quality benchmark variant.

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

Skill file locations (auto-detected from ECHELON_LLM env var):
  Claude   : .claude/skills/speckit-echelon-<cmd>/[Ss]kill.md
  Copilot  : .github/agents/speckit.echelon.<cmd>.agent.md
  Opencode : .opencode/command/speckit.echelon.<cmd>.md
  Codex    : .claude/skills/speckit-echelon-<cmd>/[Ss]kill.md
"""


# ── init (pure Python, no LLM) ────────────────────────────────────────────

def _workspace_git_preflight(project_root: Path, *, command_name: str) -> None:
    manifest = discover_workspace(project_root)
    if manifest.workspace.git_present:
        return

    source_paths = [source.path for source in manifest.sources if source.path != "."]
    ignore_entries = [f"/{path}/" for path in source_paths] or ["/source-repo/"]
    ignore_entries.extend(["/.specify/", "/runs/"])
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
    if not ((project_root / ".specify").exists() or (project_root / "specs").exists()):
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


def _apply_workspace_llm_selection(config: dict, llm_cli: str | None = None) -> str:
    from harness.config import VALID_LLM_CLIS
    from harness.init import _detect_llm_cli

    harness = config.setdefault("harness", {})
    if not isinstance(harness, dict):
        raise ValueError("config harness section must be a mapping")
    llm = harness.setdefault("llm", {})
    if not isinstance(llm, dict):
        raise ValueError("config harness.llm section must be a mapping")

    existing = llm.get("cli")
    if llm_cli:
        if llm_cli not in VALID_LLM_CLIS:
            raise ValueError(
                f"invalid --llm {llm_cli!r}; expected one of: "
                f"{', '.join(sorted(VALID_LLM_CLIS))}"
            )
        llm["cli"] = llm_cli
        return llm_cli

    selected = _detect_llm_cli()
    if os.environ.get("ECHELON_LLM", "").strip() or not existing:
        llm["cli"] = selected
        return selected
    return str(existing)


def _cmd_init(
    project_dir: Path,
    *,
    allow_unsafe_host_execution: bool = False,
    llm_cli: str | None = None,
) -> None:
    ext_dir = project_dir / ".specify" / "extensions" / "echelon"
    legacy_cfg = ext_dir / "echelon-config.yml"
    echelon_cfg = project_dir / ".echelon" / "config.yml"

    # Step 1: Confirm project config exists. New workspaces commit .echelon/config.yml;
    # legacy extension-local config remains a migration/template source.
    if not echelon_cfg.exists():
        if legacy_cfg.exists():
            echelon_cfg.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(legacy_cfg, echelon_cfg)
            print(f"✓ Project config created: {echelon_cfg}")
        else:
            print(
                f"✗ Project config not found: {echelon_cfg}\n"
                f"  Legacy template also missing: {legacy_cfg}\n"
                "  Run: specify extension add echelon",
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
        print(f"✗ Cannot parse echelon-config.yml: {e}", file=sys.stderr)
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
                f"✗ deploy config incomplete in echelon-config.yml.\n"
                f"  HTTP type requires: {missing}\n"
                f"  See config-template.yml for reference.",
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

    try:
        selected_llm_cli = _apply_workspace_llm_selection(config, llm_cli=llm_cli)
    except Exception as e:
        print(f"✗ Cannot write workspace LLM provider: {e}", file=sys.stderr)
        sys.exit(1)
    echelon_cfg.write_text(
        yaml.dump(config, default_flow_style=False, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    print(f"✓ LLM provider configured: {selected_llm_cli}")

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
    init_script = ext_dir / "scripts" / "bash" / "deploy-init.sh"
    deploy_state_label = str(project_dir / ".specify" / "squad" / "deploy-state.json")
    if not deploy_enabled:
        deploy_state_label = "skipped (deploy.enabled=false)"
    elif not deploy_runtime_ready:
        deploy_state_label = "skipped (Docker unavailable)"
    elif not init_script.exists():
        print(
            f"✗ deploy-init.sh not found at {init_script}\n"
            "  Ensure the echelon extension is deployed via spec-kit.",
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

    success = land(spec_id, project_dir=project_dir, gitops=gitops, options=options)
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
        "  Set the target in spec frontmatter:\n"
        f"    echelon spec target {spec_id} <source-path>\n"
        f"    echelon spec target {spec_id} sources/<new-repo> --init\n\n"
        f"  Then rerun: {command_prefix} {spec_id}",
        file=sys.stderr,
    )


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
            "  Implementation targets are declared per spec:\n"
            "    echelon spec target <spec_id> <source-path>\n"
            "    echelon spec target <spec_id> sources/<new-repo> --init\n\n"
            f"  Then rerun: {command_prefix}",
            file=sys.stderr,
        )
        sys.exit(1)

    target_repo = "."
    base_dir = str(Path.cwd())
    _workspace_git_preflight(
        Path(base_dir),
        command_name=_command_display(command_prefix, args),
    )
    bind_mount_ack = os.environ.get("HARNESS_BIND_MOUNT_ACK", "").lower() in ("true", "1", "yes")

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
            "`echelon spec target`.",
        )
        return

    spec_id = args[0]
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
            f"  Fix: echelon spec target {spec_dir.name} <source-path>",
            file=sys.stderr,
        )
        sys.exit(1)

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
                f"  Fix: echelon spec target {spec_dir.name} {target_rel} --init",
                file=sys.stderr,
            )
            sys.exit(1)
        if not (target_path / ".git").exists():
            print(
                f"✗ Target is not a Git repo: {target_rel}\n"
                f"  Fix: echelon spec target {spec_dir.name} {target_rel} --init",
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
    """Copy wrapper-owned runtime extension into a target-specific harness base."""
    source = polyrepo_root / ".specify" / "extensions" / "echelon"
    dest = harness_base_dir / ".specify" / "extensions" / "echelon"
    required = (
        source / "agents" / "control" / "commander.md",
        source / "workflow" / "definition.yaml",
    )
    if not all(path.exists() for path in required):
        print(
            "✗ Echelon extension not installed in polyrepo root.\n"
            f"  Expected: {source}\n"
            "  Fix: run 'specify extension add --dev <echelon>/extension' from the polyrepo root.",
            file=sys.stderr,
        )
        sys.exit(1)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        source,
        dest,
        dirs_exist_ok=True,
        ignore=runtime_extension_copy_ignore(source),
    )
    prune_delivery_workflow_definition(dest / "workflow" / "definition.yaml")


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
        f"    echelon spec target {spec_id or '<spec-id>'} sources/<new-repo> --init"
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
        spec_ref = spec_id or "<spec-id>"
        print(
            f"✗ Multiple source roots found; choose one before running {command_label}.\n\n"
            "  Source roots:\n"
            f"{_candidate_lines()}\n\n"
            f"  Fix: run 'echelon spec target {spec_ref} <source-path>'."
            + new_repo_hint
            + (f"\n  Then rerun:  {rerun_command}" if rerun_command else ""),
            file=sys.stderr,
        )
        raise SystemExit(2)

    if result.decision == "invalid_target":
        spec_ref = spec_id or "<spec-id>"
        configured = f"\n  Configured target: {explicit_target}" if explicit_target else ""
        print(
            "✗ Configured implementation target does not match a workspace source root.\n"
            f"{configured}\n\n"
            "  Source roots:\n"
            f"{_candidate_lines()}\n\n"
            f"  Fix: run 'echelon spec target {spec_ref} <source-path>'.\n"
            f"       For a new repo: echelon spec target {spec_ref} "
            "sources/<new-repo> --init"
            + (f"\n  Then rerun:  {rerun_command}" if rerun_command else ""),
            file=sys.stderr,
        )
        raise SystemExit(1)

    if not result.recommended_target:
        print(
            "✗ No implementation target configured and target detection was ambiguous.\n"
            f"  Fix: run 'echelon spec target {spec_id or '<spec-id>'} <repo>'.",
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

    parts = [f"spec {spec_id}", f"{mode} mode", f"strategies={strategy}"]
    if explicit_target:
        parts.append(f"target={explicit_target}")
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
        write_targets,
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
        if explicit_target and not target_env:
            workspace_target = _resolve_harness_workspace_target(
                polyrepo_root,
                explicit_target,
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
                _block_if_harness_phase_a_not_ready(spec_dir, resolved_spec_id)
                sys.exit(run_multi_target(
                    spec_id,
                    [target],
                    args[1:],
                    **_workspace_target_dispatch_metadata(workspace_target),
                ))
        targets_rel: list[str] = read_targets(spec_dir)
        if targets_rel and not target_env:
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
                    write_targets(spec_dir, [target_rel])
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
                # A spec may declare multiple targets. Multiple targets dispatch
                # to each sub-repo in parallel via run_multi_target (the polyrepo
                # design documented in CLAUDE.md).
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
            workspace_target = _resolve_harness_workspace_target(
                polyrepo_root,
                None,
                spec_dir=spec_dir,
                spec_id=resolved_spec_id,
                rerun_command=rerun_command,
            )
            if workspace_target.source_root != workspace_target.workspace_root:
                target_rel = workspace_target.source_root.relative_to(
                    workspace_target.workspace_root
                ).as_posix()
                if mode == "banzai":
                    write_targets(spec_dir, [target_rel])
                    print(f"✓ Wrote inferred implementation target: {target_rel}")
                target = validate_single_target([target_rel], polyrepo_root)
                _block_if_harness_phase_a_not_ready(spec_dir, resolved_spec_id)
                sys.exit(run_multi_target(
                    spec_id,
                    [target],
                    args[1:],
                    **_workspace_target_dispatch_metadata(workspace_target),
                ))

            if direct_target_path is None:
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
            f"  Legacy fallback: {config_root / '.specify' / 'extensions' / 'echelon' / 'echelon-config.yml'}\n"
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

    target_display = str(getattr(config, "target_repo", None) or "local")
    _banner("HARNESS RUN", [
        ("Spec", f"{spec_id}" + (f"  ({task_count} tasks)" if task_count else "")),
        ("Mode", mode),
        ("Strategy", strategy),
        ("Target", target_display),
    ])

    if spec_dir is not None:
        _write_spec_status(spec_dir, "In Progress")

    try:
        run(user_message, provider, gitops, base_dir=str(harness_base_dir), config=config)
    except Exception as exc:
        if _is_docker_unavailable_error(exc):
            _mark_current_harness_state_blocked(
                Path.cwd(),
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
            project_root=Path.cwd(),
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
        import json as _json
        from harness.paths import build_dir, current_build_marker, runs_dir

        marker = current_build_marker(project_root, spec_id)
        if marker.exists():
            state_dir = build_dir(project_root, marker.read_text().strip()) / "state"
        else:
            state_dir = runs_dir(project_root) / "state"
        state_file = state_dir / f"{strategy}.json"
        if not state_file.exists():
            return
        data = _json.loads(state_file.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return
        data["status"] = "blocked"
        data["termination_reason"] = reason
        if error:
            data["harness_error"] = error
        state_file.write_text(_json.dumps(data, indent=4) + "\n", encoding="utf-8")
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
    changed = any(str(state.get(key) or "") != value for key, value in updates.items())
    if not changed:
        return state, spec_dir, False

    refreshed = dict(state)
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
    spec_id, kv, resume_answer = _parse_harness_resume_args(args)
    strategy = kv.get("strategy", "default")
    mode = kv.get("mode", "semi")

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
                            command="resume",
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
                            command="resume",
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
            f"  Legacy fallback: {config_root / '.specify' / 'extensions' / 'echelon' / 'echelon-config.yml'}\n"
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
    }
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


def _setup_run_dir(project_root: Path, run_id: str) -> Path:
    """Create runs/<run_id>/ + staging/, write runs/.gitignore, update runs/.current."""
    from harness.paths import runs_dir
    runs_root = runs_dir(project_root)
    runs_root.mkdir(exist_ok=True)

    gitignore = runs_root / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("*/state.json\n*/*.tmp\n.current*\n")

    run_dir = runs_root / run_id
    run_dir.mkdir(exist_ok=True)
    (run_dir / "staging").mkdir(exist_ok=True)

    (runs_root / ".current").write_text(f"{run_id}\n")
    return run_dir


def _find_current_run_dir(project_root: Path) -> Optional[Path]:
    """Return the active run dir from a .current pointer, or the newest run dir.

    Checks runs/.current first (CLI-created layout), then squad/.current
    (legacy layout).  Falls back to the newest run-* directory with a
    state.json when no .current pointer exists — handles spec-kit-created
    runs which don't write the pointer file.
    """
    for base_dir in [project_root / "runs", project_root / "squad"]:
        current_file = base_dir / ".current"
        if not current_file.exists():
            continue
        run_id = current_file.read_text().strip()
        if not run_id:
            continue
        run_dir = base_dir / run_id
        if run_dir.exists():
            return run_dir
    # No .current pointer — fall back to newest run dir that has state.json
    all_runs = _iter_run_dirs(project_root)
    return all_runs[0] if all_runs else None


_SAFE_REWIND_PHASES: tuple[str, ...] = (
    "phase3-how",
    "phase3-sentinel",
    "phase3-plan",
)

_REWIND_PHASE_ORDER: tuple[str, ...] = (
    "phase3-how",
    "phase3-sentinel",
    "phase3-plan",
    "phase3-consensus",
    "checkpoint-plan",
    "phase4-document",
)

_REWIND_REQUIRED_INPUTS: dict[str, tuple[str, ...]] = {
    "phase3-how": ("spec.md",),
    "phase3-sentinel": ("spec.md", "plan.md", "research.md", "data-model.md", "contracts/"),
    "phase3-plan": (
        "spec.md",
        "plan.md",
        "research.md",
        "data-model.md",
        "contracts/",
        "test-strategy.md",
    ),
}

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


def _blocked_non_escalation_recovery_command(run_state: dict) -> str | None:
    blocked_reason = str(run_state.get("blocked_reason") or "").strip()
    phase_id = _last_incomplete_dispatch_phase(run_state)
    if _is_retryable_dispatch_block_reason(blocked_reason) and phase_id in _SAFE_REWIND_PHASES:
        return f"echelon spec rewind {phase_id}"
    return None


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


def _interrupted_retry_phase(run_state: dict) -> str | None:
    phase_id = str(run_state.get("interrupted_phase") or run_state.get("phase") or "").strip()
    if phase_id and phase_id not in {"DONE", "terminal-blocked"}:
        return phase_id
    return _last_incomplete_dispatch_phase(run_state)


def _classify_run_recovery(run_state: dict) -> _RunRecoveryAction:
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

    if run_state.get("escalation_question"):
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

    if "invalid next_phase" in reason:
        return _RunRecoveryAction(
            "manual_recovery",
            reason=reason,
            command="echelon spec run --next-phase <phase-id>",
            note="choose a valid phase from echelon spec status output",
        )

    rewind = _blocked_non_escalation_recovery_command(run_state)
    if rewind:
        phase = str((run_state.get("last_dispatch") or {}).get("phase_id") or "").strip()
        return _RunRecoveryAction(
            "safe_rewind",
            reason=reason,
            phase=phase,
            command=rewind,
            note="safe checkpoint cleanup is required before retry",
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


def _print_squad_summary(
    project_root: Path,
    squad_dir: Path,
    result: object,
    *,
    mode: str,
    message: str,
    target_source: str = "",
    re_policy: str = "",
) -> None:
    """Render a delivery-style Phase A/spec authoring summary."""
    import json as _json

    state: dict = {}
    state_file = squad_dir / "state.json"
    if state_file.exists():
        try:
            state = _json.loads(state_file.read_text(encoding="utf-8"))
        except Exception:
            state = {}

    status = str(getattr(result, "status", "") or state.get("status") or "unknown")
    result_phase = str(getattr(result, "phase", "") or "")
    action = _classify_run_recovery(state) if state else _RunRecoveryAction("advance")
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
    if target_source:
        fields.append(("target", target_source))
    if re_policy:
        fields.append(("RE policy", re_policy))
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

    if status in {"blocked", "interrupted", "budget_exhausted"}:
        command = action.command or "echelon spec continue"
        if command:
            label = "answer" if action.kind == "human_resume" else "continue"
            fields.append((label, command))
        if action.note:
            fields.append(("note", action.note))
    fields.append(("result", _phase_a_result_line(status, state)))
    _banner("SQUAD SUMMARY", fields, subtitle=f"{icon} {status_text}")


def _rewind_constitution_is_real(project_root: Path) -> bool:
    path = project_root / ".specify" / "memory" / "constitution.md"
    if not path.exists():
        return False
    text = path.read_text(errors="replace")
    template_markers = (
        "[PROJECT_NAME]",
        "[CONSTITUTION_VERSION]",
        "[RATIFICATION_DATE]",
        "[LAST_AMENDED_DATE]",
    )
    return not any(marker in text for marker in template_markers)


def _normalize_rewind_spec_dir(project_root: Path, state: dict) -> tuple[Path | None, str | None]:
    ref = str(state.get("spec_dir") or "").strip()
    if ref:
        candidate = Path(ref)
        if not candidate.is_absolute():
            candidate = project_root / candidate
        try:
            rel_candidate = candidate.relative_to(project_root)
            if rel_candidate.parts and rel_candidate.parts[0] in {"runs", "squad"}:
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


def _collect_rewind_missing_inputs(spec_dir: Path, phase: str) -> list[str]:
    missing: list[str] = []
    for rel in _REWIND_REQUIRED_INPUTS.get(phase, ()):
        path = spec_dir / rel.rstrip("/")
        if rel.endswith("/"):
            if not path.is_dir():
                missing.append(rel)
        elif not path.exists():
            missing.append(rel)
    return missing


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


def _reset_rewind_state(state: dict, phase: str, spec_dir_ref: str) -> dict:
    rewound = dict(state)
    rewound["phase"] = phase
    rewound["status"] = "running"
    rewound["spec_dir"] = spec_dir_ref
    rewound["blocked_reason"] = None
    rewound["escalation_question"] = None
    rewound["escalation_resolved"] = False
    rewound["escalation_resolver"] = None
    if phase in _REWIND_PHASE_ORDER:
        cutoff = _REWIND_PHASE_ORDER.index(phase)
        downstream = set(_REWIND_PHASE_ORDER[cutoff:])
        completed = rewound.get("completed_phases")
        if isinstance(completed, list):
            rewound["completed_phases"] = [p for p in completed if p not in downstream]
        counts = rewound.get("phase_dispatch_counts")
        if isinstance(counts, dict):
            rewound["phase_dispatch_counts"] = {
                key: value for key, value in counts.items() if key not in downstream
            }
    return rewound


def _iter_run_dirs(project_root: Path) -> list[Path]:
    """Return all spec run dirs under runs/ (and legacy squad/), sorted newest-first."""
    dirs: list[Path] = []
    for base_name in ("runs", "squad"):
        base = project_root / base_name
        if not base.exists():
            continue
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
        action = _classify_run_recovery(current_state)
        if action.kind == "human_resume":
            fields = [
                ("reason", action.reason),
                ("question", action.note),
                ("next", action.command),
            ]
            _banner("NEXT STEP", fields, subtitle="RUN BLOCKED — answer required")
            return
        if action.kind == "safe_rewind":
            fields = [
                ("reason", action.reason),
                ("phase", action.phase or "?"),
                ("next", action.command),
                ("then", "echelon spec continue"),
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
        if action.kind == "manual_recovery":
            fields = [
                ("reason", action.reason),
                ("next", action.command),
                ("note", action.note),
            ]
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
    const_path = project_root / ".specify" / "memory" / "constitution.md"
    if current_state and "phase1-constitution" not in completed_phases:
        blockers.append(
            "phase1-constitution has not completed in this run\n"
            "     → echelon spec continue\n"
            "       (CHIEF will invoke speckit.constitution and record provenance)"
        )
    elif not const_path.exists():
        blockers.append(
            "constitution.md absent\n"
            "     → echelon spec continue\n"
            "       (CHIEF will invoke speckit.constitution and fill it)"
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


def _print_staging_artifacts(
    project_root: Path,
    exclude_dir: Optional[Path] = None,
    run_status: str = "",
) -> None:
    """Print a compact manifest of staging artifacts from the most recent prior run.

    Skips squad-internal files (issues.md, assumption-review.md, *-endorsement.md)
    so the list reflects substantive domain artifacts the squad can build on.
    Silent when no prior run has staging content, or when the run is done (the
    NEXT STEP section already surfaces readiness in that case).
    """
    if run_status == "done":
        return

    candidates = [
        d for d in _iter_run_dirs(project_root)
        if d != exclude_dir and (d / "staging").exists()
    ]
    if not candidates:
        return

    staging = candidates[0] / "staging"

    _SKIP_NAMES = {"issues.md", "assumption-review.md", "escalation-request.md",
                   "user-clarifications.md"}
    _SKIP_SUFFIXES = ("-halt-endorsement.md", "-endorsement.md")

    names = sorted(
        f.stem for f in staging.glob("*.md")
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
        "STAGING ARTIFACTS",
        [("artifacts", files_list)],
        subtitle=f"{len(names)} files · {candidates[0].name}",
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

    Reads staging/issues.md from the latest run dir (excluding the current one).
    Shows CRITICAL issue titles and user-gated HIGH issues. Silent when nothing
    to show — no output if no issues.md exists or all issues are LOW/MEDIUM.
    """
    import re as _re

    # Find most recent run dir with a staging/issues.md, skipping the current run
    candidates = [
        d for d in _iter_run_dirs(project_root)
        if d != exclude_dir and (d / "staging" / "issues.md").exists()
    ]
    if not candidates:
        return

    issues_md = (candidates[0] / "staging" / "issues.md").read_text(errors="replace")

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
    run_label = candidates[0].name
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

    fields.append(("details", str(candidates[0] / "staging" / "issues.md")))
    if user_gated:
        fields.append(("answer", "echelon spec resume \"<your answers>\""))

    _banner("OPEN ISSUES", fields, subtitle=f"from {run_label}")


def _select_squad_dir(
    project_root: Path,
    user_message: str,
    reset: bool = False,
) -> tuple[Path, bool]:
    """Return (squad_dir, is_fresh_start).

    is_fresh_start=True  → caller should initialize state (new run).
    is_fresh_start=False → caller should resume (existing run dir, same task).
    """
    import json as _json
    from harness.paths import make_spec_run_id

    if reset:
        return _setup_run_dir(project_root, make_spec_run_id()), True

    existing_dir = _find_current_run_dir(project_root)
    if not existing_dir:
        return _setup_run_dir(project_root, make_spec_run_id()), True

    try:
        state = _json.loads((existing_dir / "state.json").read_text())
    except Exception:
        return _setup_run_dir(project_root, make_spec_run_id()), True

    status = state.get("status")
    if status not in ("running", "in_progress"):
        return _setup_run_dir(project_root, make_spec_run_id()), True

    # Different task → new run dir (preserves old one, doesn't overwrite)
    if user_message and user_message != state.get("user_message", ""):
        return _setup_run_dir(project_root, make_spec_run_id()), True

    # Same task, resumable status → resume in existing dir
    return existing_dir, False


def _inferred_source_extension_dir() -> Path:
    """Possible dev-checkout extension path for source-aware drift checks."""
    return Path(__file__).resolve().parents[2] / "extension"


def _print_extension_drift_warning(project_root: Path, ext_dir: Path) -> None:
    """Warn when installed extension differs from a trusted source extension."""
    try:
        from harness.extension_drift import (
            assess_extension_drift,
            resolve_extension_source_dir,
        )

        source_dir = resolve_extension_source_dir(
            ext_dir,
            inferred_source_dir=_inferred_source_extension_dir(),
        )
        if source_dir is None:
            return
        report = assess_extension_drift(source_dir, ext_dir)
    except Exception:
        return

    if not report.drifted:
        return

    examples: list[str] = []
    for label, paths in (
        ("changed", report.changed_files),
        ("missing", report.missing_files),
        ("extra", report.extra_files),
    ):
        for rel_path in paths[:3]:
            examples.append(f"{label}: {rel_path}")
    examples = examples[:6]

    _banner(
        "EXTENSION DRIFT",
        [
            ("installed", _repo_relative_or_absolute(ext_dir, project_root)),
            ("source", str(source_dir)),
            (
                "diff",
                f"{len(report.changed_files)} changed, "
                f"{len(report.missing_files)} missing, "
                f"{len(report.extra_files)} extra",
            ),
            ("examples", "\n".join(examples) if examples else "(none)"),
            ("update", f"specify extension update --dev {source_dir}"),
        ],
        subtitle="Installed Echelon extension differs from this checkout",
    )


@dataclass(frozen=True)
class ProjectConfigCompatibilityIssue:
    title: str
    path: str
    current: str
    expected: str
    config_file: Path


def _project_echelon_config(project_root: Path) -> Path:
    canonical = project_root / ".echelon" / "config.yml"
    if canonical.exists():
        return canonical
    return project_root / ".specify" / "extensions" / "echelon" / "echelon-config.yml"


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
    return phase_id in {"phase3-plan", "phase3-consensus"}


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


def _cmd_run(
    args: list[str],
    project_root: Path,
    ext_dir: Path,
) -> None:
    """Drive the pre-code squad run via deterministic Python harness."""
    from harness.config import load_config
    from harness.phase_graph import PhaseGraph
    from harness.squad import SquadController
    from harness.squad_provider import SquadCliProvider
    from harness.squad_state import SquadStateStore

    _print_extension_drift_warning(project_root, ext_dir)
    _enforce_project_config_compatibility(project_root)
    _workspace_git_preflight(project_root, command_name="echelon spec run")

    # Parse optional flags
    mode = "semi"
    reset = False
    next_phase = ""
    target_source = os.environ.get("ECHELON_TARGET_SOURCE", "").strip()
    init_target = False
    re_policy = os.environ.get("ECHELON_RE_POLICY", "").strip()
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
        elif args[i] == "--init":
            init_target = True
            i += 1
        elif args[i] == "--next-phase" and i + 1 < len(args):
            next_phase = args[i + 1]
            i += 2
        elif args[i] in {"--target", "--target-source"}:
            if i + 1 >= len(args):
                print(
                    "✗ echelon spec run: --target requires a source id or path",
                    file=sys.stderr,
                )
                sys.exit(1)
            target_source = args[i + 1].strip()
            i += 2
        elif args[i].startswith("--target="):
            target_source = args[i].split("=", 1)[1].strip()
            i += 1
        elif args[i].startswith("--target-source="):
            target_source = args[i].split("=", 1)[1].strip()
            i += 1
        elif args[i] == "--re-policy":
            if i + 1 >= len(args):
                print(
                    "✗ echelon spec run: --re-policy requires a policy name",
                    file=sys.stderr,
                )
                sys.exit(1)
            re_policy = args[i + 1].strip()
            i += 2
        elif args[i].startswith("--re-policy="):
            re_policy = args[i].split("=", 1)[1].strip()
            i += 1
        else:
            message_parts.append(args[i])
            i += 1
    message = " ".join(message_parts)
    _workspace_git_preflight_for_squad_run(
        project_root,
        command_name=_command_display("echelon spec run", args),
        user_message=message,
        reset=reset,
    )

    prev_dir = _find_current_run_dir(project_root)
    squad_dir, is_fresh = _select_squad_dir(project_root, message, reset=reset)
    if reset:
        print("[squad] state reset — starting fresh", flush=True)
    elif is_fresh and prev_dir is not None and prev_dir != squad_dir:
        print(
            f"[squad] new task — starting fresh in {squad_dir.name} "
            f"(previous run preserved at {prev_dir.name})",
            flush=True,
        )

    if init_target:
        if not target_source:
            print(
                "✗ echelon spec run: --init requires --target <source id or path>",
                file=sys.stderr,
            )
            sys.exit(1)
        init_messages = _prepare_spec_target_repo(project_root, squad_dir, target_source)
        from echelon.workspace_sources import ensure_source_config_entry

        source_added = ensure_source_config_entry(project_root, target_source)
        for init_message in init_messages:
            print(init_message)
        if source_added:
            print(f"Added workspace source: {target_source}")

    config = load_config(project_root, squad_only=True)
    provider = SquadCliProvider(config)
    state_store = SquadStateStore(squad_dir)
    graph = PhaseGraph(
        ext_dir / "workflow/definition.yaml",
        ext_dir / "extension.yml",
    )
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
        re_policy=re_policy,
        target_source=target_source,
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
        ("Task", (message[:80] + "…") if len(message) > 80 else message),
        ("Dir", str(squad_dir.name)),
        ("RE target", target_source or "(all sources)"),
        ("RE policy", re_policy or "(default)"),
    ])

    result = controller.run(user_message=message, mode=mode, next_phase_override=next_phase)

    _print_squad_summary(
        project_root,
        squad_dir,
        result,
        mode=mode,
        message=message,
        target_source=target_source,
        re_policy=re_policy,
    )
    _print_next_steps(project_root, result.status)
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
    spec_id = str(state.get("spec_id") or "").strip()
    spec_ref = str(state.get("spec_dir") or "").strip()
    published_ref = str(state.get("published_spec_dir") or "").strip()

    spec_id = spec_id or _spec_id_from_ref(spec_ref) or _spec_id_from_ref(published_ref)
    if not spec_id:
        only_spec = _single_project_spec_dir(project_root)
        if only_spec is None:
            return state, None
        spec_id = only_spec.name

    active_spec_dir = run_dir / "specs" / spec_id
    published_spec_dir = project_root / "specs" / spec_id

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
    spec_arg: str = "",
) -> Path | None:
    """Resolve the project-visible spec dir for a manual phase run."""
    from harness.spec_frontmatter import find_spec_dir

    value = spec_arg.strip()
    if value:
        candidate = Path(value)
        if candidate.exists() and candidate.is_dir():
            return candidate if candidate.is_absolute() else project_root / candidate
        return find_spec_dir(value, project_root)

    target = _build_target_continue_spec_dir(project_root, current_state)
    if target is not None:
        return target
    return _single_project_spec_dir(project_root)


def _phase_state_updates_for_target(
    project_root: Path,
    current_state: dict,
    target_spec_dir: Path | None,
) -> dict:
    """Build state fields that make phase context/output target the spec dir."""
    if target_spec_dir is None:
        return {}

    target_spec_dir.mkdir(parents=True, exist_ok=True)

    source_ref = str(current_state.get("spec_dir") or "").strip()
    if source_ref:
        source = Path(source_ref)
        if not source.is_absolute():
            source = project_root / source
        if source.exists() and source.is_dir() and source.resolve() != target_spec_dir.resolve():
            _copy_missing_tree(source, target_spec_dir)

    updates: dict[str, str] = {
        "spec_id": target_spec_dir.name,
        "spec_dir": _repo_relative_or_absolute(target_spec_dir, project_root),
        "published_spec_dir": _repo_relative_or_absolute(target_spec_dir, project_root),
    }
    if source_ref:
        updates["phase_run_source_spec_dir"] = source_ref
    return updates


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
            resolved_ref = resolved_ref.replace(".specify/squad/staging/", f"{staging}/")
            resolved_ref = resolved_ref.replace(".specify/squad/staging", str(staging))
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

    spec_id = str(current_state.get("spec_id") or "").strip()
    if spec_id:
        add(project_root / "specs" / spec_id)
        if run_dir is not None:
            add(run_dir / "specs" / spec_id)

    for key in ("published_spec_dir", "spec_dir"):
        ref = str(current_state.get(key) or "").strip()
        if not ref:
            continue
        add(Path(ref))

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
                if _phase_a_ready_to_build(project_root, current_state):
                    return None
                if current_state.get("status") == "done":
                    return "phase4-document"
                return recommended
        except Exception:
            current_state = {}
    active_spec_dir = _active_continue_spec_dir(project_root, current_state, run_dir)
    if current_state.get("status") == "done" and _phase_a_ready_to_build(project_root, current_state):
        return None

    action = _classify_run_recovery(current_state)
    if action.kind == "retry_phase":
        return action.phase
    if action.kind in {"human_resume", "safe_rewind"}:
        return None
    if action.kind == "manual_recovery" and current_state.get("status") == "interrupted":
        return None

    # 0. Constitution phase provenance first, artifact integrity second.
    completed = current_state.get("completed_phases")
    completed_phases = completed if isinstance(completed, list) else []
    if "phase1-constitution" not in completed_phases:
        return "phase1-constitution"
    const_path = project_root / ".specify" / "memory" / "constitution.md"
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


def _phase_a_ready_to_build(project_root: Path, current_state: dict) -> bool:
    """Return True when Phase A already produced enough artifacts for harness run."""
    completed = current_state.get("completed_phases")
    completed_phases = completed if isinstance(completed, list) else []
    if current_state and "phase1-constitution" not in completed_phases:
        return False

    const_path = project_root / ".specify" / "memory" / "constitution.md"
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
    "phase1-why2", "checkpoint-assess", "phase2-decide",
    "phase2-strategic-overview", "phase2-tracker-alignment",
    "phase3-specialists", "phase3-how", "phase3-sentinel", "phase3-plan",
    "phase3-consensus", "checkpoint-plan", "phase4-document", "done",
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

    path: list[str] = []
    current = "init"
    seen: set[str] = set()
    while current and current in phases and current not in seen:
        path.append(current)
        seen.add(current)
        if current == "done":
            break

        next_phase = ""
        transitions = phases[current].get("transitions") or []
        if isinstance(transitions, list):
            for transition in transitions:
                if not isinstance(transition, dict):
                    continue
                candidate = str(transition.get("to") or "")
                if candidate and candidate != current and candidate != "escalate":
                    next_phase = candidate
                    break
        current = next_phase

    if not path or path[-1] != "done":
        return list(_FALLBACK_ROADMAP_PHASES)
    return path


_ROADMAP_PHASES = _derive_roadmap_phases(
    Path(__file__).resolve().parents[2] / "extension/workflow/definition.yaml"
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
    current = state.get("current_phase")
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
    _print_extension_drift_warning(
        project_root,
        project_root / ".specify" / "extensions" / "echelon",
    )
    _print_project_config_compatibility_warning(project_root)

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
        _ld = state.get("current_phase") or state.get("last_dispatch")
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
        if run_status in ("running", "in_progress"):
            fields.append(("Next", "echelon spec continue"))
        elif run_status == "blocked":
            fields.append(("Next", 'echelon spec resume "<your answer>"'))

        _banner("RUN STATE", fields)

        # ── Pipeline roadmap ────────────────────────────────────────────────
        _print_roadmap(
            state,
            project_root / ".specify" / "extensions" / "echelon" / "workflow" / "definition.yaml",
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


def _cmd_continue(
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

    _print_extension_drift_warning(project_root, ext_dir)

    # Optionally accept --mode override
    mode_override = ""
    i = 0
    while i < len(args):
        parsed_mode, next_i = _consume_mode_arg(args, i, command_name="echelon spec continue")
        if parsed_mode is not None:
            mode_override = parsed_mode
            i = next_i
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
    user_message = state.get("user_message", "")
    mode = mode_override or state.get("autonomy_mode") or state.get("mode", "semi")
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
        "phase1-constitution": "CHIEF → speckit.constitution (creates constitution.md)",
        "phase1-what":         "CARTOGRAPHER (spec amendment + WHY2 re-validation)",
        "phase3-how":          "ARCHITECT (architecture, data-model, contracts)",
        "phase3-plan":         "ORCHESTRATOR (task breakdown)",
        "phase3-consensus":    "Consensus gate (WHY3 + ASSESS2 + PLAN2)",
    }

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
        (squad_dir / "state.json").write_text(_json.dumps(state, indent=2, ensure_ascii=False))
        label = phase_labels.get(next_phase, next_phase)
        print(
            f"[squad] {verb} {next_phase} — {label}\n"
            f"[squad] Task:  {(user_message[:80] + '…') if len(user_message) > 80 else user_message}\n"
            f"[squad] Mode:  {mode}",
            flush=True,
        )
        _cmd_run([user_message, "--mode", mode], project_root=project_root, ext_dir=ext_dir)

    action = _classify_run_recovery(state)
    if action.kind == "safe_rewind":
        _banner(
            "CHECKPOINT",
            [
                ("blocked by", action.reason),
                ("recover with", action.command),
                ("then", "echelon spec continue"),
            ],
            subtitle="Run paused. Deterministic recovery required.",
        )
        return
    if action.kind == "retry_phase":
        start_phase(action.phase, verb="Retrying incomplete phase", clear_recovery=True)
        return
    if action.kind == "human_resume":
        _banner(
            "CHECKPOINT",
            [
                ("decision needed", action.note or "(no escalation question recorded)"),
                ("resume with", action.command),
            ],
            subtitle="Run paused. Human decision required.",
        )
        return
    if action.kind == "manual_recovery":
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

    # terminal-blocked: the consecutive-fail guard fired. echelon spec resume recorded the
    # user's answer but left phase=terminal-blocked (a TERMINAL_PHASE). The controller
    # would exit immediately from that phase, so we repair state here — advance the
    # phase to the next runnable one — before resuming in the SAME squad dir.
    if cur_phase == "terminal-blocked":
        next_phase = _next_continue_phase(project_root)
        if next_phase is None:
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
        _cmd_run([user_message, "--mode", mode], project_root=project_root, ext_dir=ext_dir)
        return

    # Determine the next phase automatically
    next_phase = _next_continue_phase(project_root)
    if next_phase is None:
        print(
            "Build is ready — nothing left to do in Phase A.\n\n"
            "  echelon delivery run <spec-id>",
            flush=True,
        )
        return

    start_phase(next_phase, verb="Continuing from")


def _cmd_rewind(
    args: list[str],
    project_root: Path,
) -> None:
    confirm = "--confirm" in args
    positional = [arg for arg in args if arg != "--confirm"]
    if len(positional) != 1:
        print(
            "Usage: echelon spec rewind <phase-id> [--confirm]\n"
            f"Supported phases: {', '.join(_SAFE_REWIND_PHASES)}",
            file=sys.stderr,
        )
        sys.exit(1)

    target = positional[0].strip()
    if target not in _SAFE_REWIND_PHASES:
        print(
            "✗ Unsupported rewind target.\n"
            f"  Phase: {target}\n"
            f"  Supported phases: {', '.join(_SAFE_REWIND_PHASES)}",
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

    checkpoint_ledger = spec_dir / ".echelon" / "checkpoints.json"
    if checkpoint_ledger.exists():
        from echelon.rewind import RewindError, prepare_rewind

        try:
            result = prepare_rewind(
                project_root=project_root,
                spec=spec_dir.name,
                target=target,
                confirm=confirm,
            )
        except RewindError as exc:
            print(f"✗ Cannot rewind to {target}.\n  {exc}", file=sys.stderr)
            sys.exit(1)

        if not result.applied:
            print(result.message)
            return

        _banner(
            "REWIND COMPLETE",
            [
                ("spec", result.spec_id),
                ("checkpoint", result.checkpoint_id),
                ("from", result.from_commit[:7]),
                ("to", result.to_commit[:7]),
                ("backup", result.backup_ref or "(none)"),
            ],
        )
        return

    if not _rewind_constitution_is_real(project_root):
        print(
            f"✗ Cannot rewind to {target}.\n"
            "  constitution.md is missing or still contains template placeholders.",
            file=sys.stderr,
        )
        sys.exit(1)

    missing = _collect_rewind_missing_inputs(spec_dir, target)
    if missing:
        print(
            f"✗ Cannot rewind to {target}.\n"
            "  Missing required inputs:",
            file=sys.stderr,
        )
        for item in missing:
            print(f"  - {spec_dir / item.rstrip('/')}", file=sys.stderr)
        print(
            "  Next step: regenerate the missing upstream artifacts or rewind to an earlier safe phase.",
            file=sys.stderr,
        )
        sys.exit(1)

    removed = _cleanup_rewind_outputs(spec_dir, target, squad_dir)
    rewound = _reset_rewind_state(state, target, spec_dir_ref)
    store.save(rewound)

    details = [
        ("run dir", str(squad_dir)),
        ("phase", target),
        ("spec dir", spec_dir_ref),
        ("cleaned", ", ".join(removed) if removed else "(none)"),
        ("next step", "echelon spec continue"),
    ]
    _banner("REWIND PREPARED", details)


def _cmd_benchmark(args: list[str], project_root: Path) -> None:
    from echelon.benchmark import (
        baseline_snapshot_commands,
        latest_summary_path,
        load_saved_scorecard,
        load_summary,
        list_fixtures,
        list_variants,
        plan_variant_commands,
        run_benchmark_variant,
        variant_execution_commands,
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
        "[--baseline-ref <ref>] [--dry-run]\n"
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
            "| Variant | Status | Spec | Delivery | Gaps | Verify Failures | Blocks | Retries | Dispatches | Seconds |"
        )
        print("|---|---|---|---|---:|---:|---:|---:|---:|---:|")
        variants = summary.get("variants")
        if isinstance(variants, dict):
            for variant_id, record in variants.items():
                if not isinstance(record, dict):
                    continue
                print(
                    f"| {variant_id} | {record.get('status', '')} | {record.get('spec_id') or '-'} | "
                    f"{record.get('delivery_run_id') or '-'} | {record.get('fulfillment_gaps', 0)} | "
                    f"{record.get('verification_failures', 0)} | {record.get('blocked_states', 0)} | "
                    f"{record.get('retries', 0)} | {record.get('build_dispatches', 0)} | "
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
    dry_run = False
    i = 2
    while i < len(args):
        if args[i] == "--variant" and i + 1 < len(args):
            variant_id = args[i + 1]
            i += 2
        elif args[i] == "--baseline-ref" and i + 1 < len(args):
            baseline_ref = args[i + 1]
            i += 2
        elif args[i] == "--dry-run":
            dry_run = True
            i += 1
        else:
            print(f"✗ Unknown benchmark argument: {args[i]}", file=sys.stderr)
            sys.exit(1)

    try:
        plan = plan_variant_commands(fixture_id, variant_id)
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
        commands = (
            variant_execution_commands(plan, baseline_ref)
            if baseline_ref
            else baseline_snapshot_commands()
            + variant_execution_commands(plan, "BENCHMARK_BASELINE_SNAPSHOT")
        )
        _banner(
            "BENCHMARK DRY RUN",
            [("fixture", plan.fixture_id), ("variant", plan.variant_id)],
            subtitle="Commands that would run",
        )
        for command in commands:
            print(" ".join(command))
        return

    output_dir = run_benchmark_variant(project_root, fixture_id, variant_id, baseline_ref=baseline_ref or None)
    _banner(
        "BENCHMARK COMPLETE",
        [("fixture", fixture_id), ("variant", variant_id), ("output", str(output_dir))],
    )


def _cmd_phase(
    args: list[str],
    project_root: Path,
    ext_dir: Path,
) -> None:
    from harness.config import get_full_resolved_config, load_config
    from harness.paths import make_spec_run_id
    from harness.phase_graph import PhaseGraph
    from harness.squad import SquadController
    from harness.squad_provider import SquadCliProvider
    from harness.squad_state import SquadStateStore

    _print_extension_drift_warning(project_root, ext_dir)

    graph = PhaseGraph(
        ext_dir / "workflow/definition.yaml",
        ext_dir / "extension.yml",
    )

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
        run_dir = _setup_run_dir(project_root, make_spec_run_id())

    state_store = SquadStateStore(run_dir)
    current_state = state_store.load()
    target_spec_dir = _resolve_phase_target_spec_dir(project_root, current_state, spec_arg)
    if spec_arg and target_spec_dir is None:
        print(f"✗ Spec not found for --spec {spec_arg!r}", file=sys.stderr)
        sys.exit(1)

    initial_updates = _phase_state_updates_for_target(
        project_root,
        current_state,
        target_spec_dir,
    )
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

    user_message = " ".join(message_parts) or current_state.get("user_message", "")
    result = controller.run_single_phase(
        phase_id,
        user_message=user_message,
        mode=mode,
        initial_state_updates=initial_updates,
    )

    status_icon = "✓" if result.status in {"running", "done"} else "✗"
    _banner(
        f"{status_icon}  PHASE RUN {result.status.upper()}",
        [
            ("phase", result.phase),
            ("artifacts", str(target_spec_dir or run_dir)),
            ("next", "echelon spec continue"),
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
    from harness.phase_graph import PhaseGraph
    from harness.squad import SquadController
    from harness.squad_provider import SquadCliProvider
    from harness.squad_state import SquadStateStore

    _print_extension_drift_warning(project_root, ext_dir)

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
    state = store.load()

    if state.get("status") != "blocked":
        print(
            f"✗ Run is not blocked (status: {state.get('status', 'unknown')}).",
            file=sys.stderr,
        )
        print("  Nothing to resume.", file=sys.stderr)
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

    # Capture blocked phase before clearing — needed to decide resume path.
    blocked_phase = state.get("phase", "")

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

    graph = PhaseGraph(
        ext_dir / "workflow/definition.yaml",
        ext_dir / "extension.yml",
    )
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
        re_policy=str(state.get("requested_re_policy") or ""),
        target_source=str(state.get("target_source") or ""),
    )
    result = controller.run(
        user_message=state.get("user_message", ""),
        mode=state.get("autonomy_mode") or state.get("mode", "semi"),
    )

    _banner("SQUAD RESUMED", [
        ("Phase resumed", state.get("phase", "?")),
        ("Answer given", (answer[:60] + "…") if len(answer) > 60 else answer),
        ("Status", result.status),
        ("Current phase", result.phase),
        ("Artifacts", str(squad_dir)),
    ])
    _print_next_steps(project_root, result.status)


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

    CARTOGRAPHER may be re-dispatched after a human escalation. If the first
    pass already created the spec-kit branch and spec directory, resume must
    continue enhancing that spec, not call speckit.specify again and allocate a
    new branch number.
    """
    if state.get("phase") != "phase1-what":
        return

    spec_dir = state.get("spec_dir")
    if spec_dir:
        candidate = Path(spec_dir)
        if not candidate.is_absolute():
            candidate = project_root / candidate
        if candidate.exists():
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
    if not candidate.exists():
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
    StreamEventPrinter as _StreamEventPrinter,
)
from harness.config import load_config
from harness.llm_provider import AICodingCliProvider
from harness.llm_tool_policy import (
    LlmToolPolicy,
    build_llm_cli_command,
    build_opencode_skill_command,
)


def _find_skill(skill_base: str, project_dir: Path, cli: str) -> Path | None:
    return _find_skill_impl(skill_base, project_dir, cli)


def _build_prompt(skill_path: Path, arguments: str) -> str:
    return _build_skill_prompt_impl(skill_path, arguments)


def _load_cli_config(project_dir: Path):
    return load_config(project_dir, squad_only=True)


def _load_cli_tool_policy(project_dir: Path) -> LlmToolPolicy:
    return _load_cli_config(project_dir).llm.tool_policy


def _print_event(event: dict, _printer: list = []) -> None:
    # Lazy-init one printer per process; list used as mutable default container.
    if not _printer:
        _printer.append(_StreamEventPrinter())
    _printer[0](event)


def _run_claude_streaming(
    bin_: str,
    prompt: str,
    project_dir: Path,
    extra_args: list[str] | None = None,
    tool_policy: LlmToolPolicy | None = None,
) -> None:
    """Invoke claude -p with stream-json output and print live progress to stdout."""
    import json as _json

    cmd = build_llm_cli_command(
        "claude",
        bin_,
        prompt,
        tool_policy or LlmToolPolicy(),
        stream_json=True,
    ) + (extra_args or [])

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=None,  # inherit so errors are visible
        cwd=str(project_dir),
    )
    assert proc.stdin and proc.stdout
    proc.stdin.write(prompt.encode("utf-8"))
    proc.stdin.close()

    for raw in proc.stdout:
        line = raw.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        try:
            _print_event(_json.loads(line))
        except _json.JSONDecodeError:
            print(line, flush=True)

    proc.stdout.close()
    proc.wait()
    sys.exit(proc.returncode)


def _skill_not_found_msg(skill_base: str, project_dir: Path, cli: str) -> str:
    if cli == "copilot":
        return (
            f"echelon: skill 'speckit.{skill_base}' not found.\n"
            f"Expected at:\n"
            f"  {project_dir / '.github' / 'agents' / f'speckit.{skill_base}.agent.md'}\n"
            f"Run: specify extension add echelon"
        )
    if cli == "opencode":
        return (
            f"echelon: skill 'speckit.{skill_base}' not found.\n"
            f"Expected at:\n"
            f"  {project_dir / '.opencode' / 'command' / f'speckit.{skill_base}.md'}\n"
            f"Run: specify extension add echelon"
        )
    dash_name = "speckit-" + skill_base.replace(".", "-")
    return (
        f"echelon: skill '{dash_name}' not found.\n"
        f"Expected at:\n"
        f"  {project_dir / '.claude' / 'skills' / dash_name / 'skill.md'}\n"
        f"  {Path.home() / '.claude' / 'skills' / dash_name / 'skill.md'}\n"
        f"Run: specify extension add echelon"
    )


def _dispatch_skill_command(command: str, args: list[str]) -> None:
    skill_base = SKILL_MAP[command]
    arguments = " ".join(args)

    if not arguments:
        print(f"echelon {command}: missing arguments\n", file=sys.stderr)
        print(USAGE)
        sys.exit(1)

    project_dir = Path.cwd()
    cli = os.environ.get("ECHELON_LLM", "claude")
    try:
        config = _load_cli_config(project_dir)
        tool_policy = config.llm.tool_policy
    except Exception as exc:
        print(f"echelon {command}: invalid LLM tool policy: {exc}", file=sys.stderr)
        sys.exit(1)

    skill_path = _find_skill(skill_base, project_dir, cli)
    if skill_path is None:
        print(_skill_not_found_msg(skill_base, project_dir, cli), file=sys.stderr)
        sys.exit(1)

    bin_ = shutil.which(cli) or cli
    if cli == "opencode":
        cmd = build_opencode_skill_command(bin_, skill_base, arguments, tool_policy)
        result = subprocess.run(cmd, cwd=str(project_dir))
    elif cli in {"copilot", "codex"}:
        prompt = _build_prompt(skill_path, arguments)
        result_code = AICodingCliProvider(config).exec_prompt(str(project_dir), prompt)
        sys.exit(result_code)
    else:
        # claude: use stream-json for live tool-call progress in the terminal
        prompt = _build_prompt(skill_path, arguments)
        _run_claude_streaming(bin_, prompt, project_dir, tool_policy=tool_policy)
        return  # _run_claude_streaming calls sys.exit
    sys.exit(result.returncode)


# ── RE publication subcommand ────────────────────────────────────────────────

def _cmd_re_publish(args: list[str]) -> None:
    """Publish one validated run into the canonical workspace RE registry."""
    import re

    from echelon.git_helpers import GitHelperError, run_git
    from harness.re_lock import (
        RePublicationActiveRun,
        RePublishLocked,
        RePublishRecoveryRequired,
    )
    from harness.re_migration import import_legacy_re_cache
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
    candidates = [project_root / "runs" / run_id, project_root / "squad" / run_id]
    run_dir = next((path for path in candidates if path.is_dir()), None)
    if run_dir is None:
        print(
            f"echelon re publish: run not found under runs/ or squad/: {run_id}",
            file=sys.stderr,
        )
        raise SystemExit(1)

    try:
        imported = import_legacy_re_cache(project_root)
        result = publish_re_run(
            project_root,
            run_dir,
            allow_partial=allow_partial,
        )
        if commit:
            _commit_re_publication(project_root, result.generation, run_git)
    except (
        RePublicationError,
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
            "  run <description> [--mode semi|banzai|guided] [--reset]\n"
            "                    [--message <text>] [--next-phase <id>]\n"
            "                    [--target <source-id-or-path>] [--init]\n"
            "                    [--re-policy none|cached-only|changed|target-changed|target-only|refresh-all]\n"
            "                                      Run Phase A squad spec authoring\n"
            "  status                              Show current run state and next action\n"
            "  continue [--mode semi|banzai|guided]\n"
            "                                      Run the next no-input Phase A recovery action\n"
            "  resume <answers>                    Answer escalation questions from a blocked run\n"
            "  rewind <phase-id>                   Rewind the active squad run to a checkpoint\n"
            "  checkpoint list|accept|commit [--spec <id>] [--phase <phase-id>]\n"
            "                                      Manage Phase A/spec checkpoints\n"
            "  target <spec_id> <repo> [repo...] [--init]\n"
            "                                      Set targets: in spec frontmatter\n"
            "                                      With --init, create/prepare target Git repo(s).\n"
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
    elif subcmd == "rewind":
        _cmd_rewind(args[1:], project_root=Path.cwd())
    elif subcmd == "checkpoint":
        from echelon.checkpoint_cli import run_checkpoint_command

        run_checkpoint_command(args[1:], project_root=Path.cwd())
    elif subcmd == "artifacts":
        _cmd_artifacts(args[1:])
    elif subcmd == "verify":
        _dispatch_skill_command("verify-spec", args[1:])
    elif subcmd in {"bugfix", "change", "reopen"}:
        _dispatch_skill_command(subcmd, args[1:])
    else:
        print(f"echelon spec: unknown subcommand '{subcmd}'\n", file=sys.stderr)
        sys.exit(1)


def _installed_extension_or_exit(project_root: Path) -> Path:
    ext_dir = project_root / ".specify" / "extensions" / "echelon"
    if not ext_dir.exists():
        print(
            f"✗ Echelon extension not installed: {ext_dir}\n"
            "  Run: specify extension add echelon",
            file=sys.stderr,
        )
        sys.exit(1)
    return ext_dir


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
    ext_dir = _installed_extension_or_exit(project_root)
    cfg_file = _project_echelon_config(project_root)
    if not cfg_file.exists():
        print(
            f"✗ Project not initialized — config not found: {cfg_file}\n"
            "  Run: echelon workspace init",
            file=sys.stderr,
        )
        sys.exit(1)
    _cmd_run(args, project_root=project_root, ext_dir=ext_dir)


def _cmd_spec_continue(args: list[str]) -> None:
    project_root = Path.cwd()
    ext_dir = _installed_extension_or_exit(project_root)
    _cmd_continue(args, project_root=project_root, ext_dir=ext_dir)


def _cmd_spec_resume(args: list[str]) -> None:
    if os.environ.get("ECHELON_SQUAD_ACTIVE"):
        print(
            "✗ echelon spec resume: refusing nested invocation (ECHELON_SQUAD_ACTIVE is set).",
            file=sys.stderr,
        )
        sys.exit(1)
    project_root = Path.cwd()
    ext_dir = _installed_extension_or_exit(project_root)
    _cmd_resume(args, project_root=project_root, ext_dir=ext_dir)


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


def _cmd_spec_target(args: list[str]) -> None:
    if len(args) < 2:
        print(
            "echelon spec target: usage: echelon spec target <spec_id> <repo> "
            "[repo...] [--init]\n",
            file=sys.stderr,
        )
        sys.exit(1)

    spec_id = args[0]
    init_targets = False
    repos: list[str] = []
    for arg in args[1:]:
        if arg == "--init":
            init_targets = True
        elif arg.startswith("--"):
            print(f"echelon spec target: unknown option '{arg}'", file=sys.stderr)
            sys.exit(1)
        else:
            repos.append(arg)

    if not repos:
        print(
            "echelon spec target: usage: echelon spec target <spec_id> <repo> "
            "[repo...] [--init]\n",
            file=sys.stderr,
        )
        sys.exit(1)

    from harness.spec_frontmatter import find_spec_dir, write_targets

    # Check for ambiguity: multiple specs/ dirs matching spec_id at the found level
    start = Path.cwd()
    current = start
    while True:
        matches = sorted(current.glob(f"specs/{spec_id}-*"))
        if len(matches) > 1:
            print(f"✗ Ambiguous spec id '{spec_id}': multiple matches:", file=sys.stderr)
            for m in matches:
                print(f"  {m}", file=sys.stderr)
            sys.exit(1)
        if matches:
            break
        parent = current.parent
        if parent == current or (parent / ".git").exists():
            break
        current = parent

    spec_dir = find_spec_dir(spec_id, start)
    if spec_dir is None:
        print(f"✗ Spec '{spec_id}' not found (searched from {start})", file=sys.stderr)
        sys.exit(1)

    init_messages: list[str] = []
    if init_targets:
        for repo in repos:
            init_messages.extend(_prepare_spec_target_repo(start, spec_dir, repo))

    md = write_targets(spec_dir, repos)
    try:
        display = md.relative_to(start)
    except ValueError:
        display = md
    for message in init_messages:
        print(message)
    print(f"Updated {display}")
    print("  targets:")
    for r in repos:
        print(f"    - {r}")
    if init_targets:
        print()
        print(f"Next: echelon delivery target {spec_dir.name}")


def _cmd_workspace(args: list[str]) -> None:
    if not args or args[0] in ("-h", "--help"):
        print(
            "Usage: echelon workspace <subcommand> [args...]\n\n"
            "  init [--llm <provider>]\n"
            "       [--allow-unsafe-host-execution|--no-unsafe-host-execution]\n"
            "                            One-time project setup (no LLM)\n"
            "                            Prompts on an interactive TTY; use the flag to opt in non-interactively\n"
            "  doctor                    Validate workspace/source/runtime contract\n"
            "  sources sync [--write]    Sync discovered sources/* roots into config\n"
            "  migrate [--write]         Copy legacy config, ignore runtime state, stage fixes\n"
            "          [--commit] [--message <msg>]\n"
            "                            Apply and commit migration changes\n",
            file=sys.stderr,
        )
        sys.exit(0)

    subcmd = args[0]
    if subcmd == "init":
        init_args = args[1:]
        if any(arg in {"-h", "--help"} for arg in init_args):
            print(
                "Usage: echelon workspace init "
                "[--llm <claude|codex|opencode|copilot>] "
                "[--allow-unsafe-host-execution|--no-unsafe-host-execution]\n\n"
                "  --llm <provider>              Persist the workspace AI CLI provider\n"
                "  --allow-unsafe-host-execution  Write local approval for AI CLI "
                "permission-bypass flags\n"
                "  --no-unsafe-host-execution     Do not prompt or write local approval",
                file=sys.stderr,
            )
            sys.exit(0)
        parsed_init_args: list[str] = []
        llm_cli: str | None = None
        valid_llm_clis = {"claude", "codex", "opencode", "copilot"}
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
            elif arg in {"--allow-unsafe-host-execution", "--no-unsafe-host-execution"}:
                parsed_init_args.append(arg)
                i += 1
            else:
                print(f"echelon workspace init: unknown option '{arg}'\n", file=sys.stderr)
                print(
                    "Usage: echelon workspace init "
                    "[--llm <claude|codex|opencode|copilot>] "
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
        _cmd_init(project_root, allow_unsafe_host_execution=allow_unsafe, llm_cli=llm_cli)
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


def _cmd_stack(args: list[str], project_root: Path | None = None) -> None:
    project_root = project_root or Path.cwd()
    if not args or args[0] in {"-h", "--help", "help"}:
        print(
            "Usage:\n"
            "  echelon stack list [--json]\n"
            "  echelon stack detect [--target <path>] [--artifacts <path>] "
            "[--write] [--format text|yaml] [--json]\n"
            "  echelon stack preflight [--stack <id>] "
            "[--target-archetype <id>] [--from-detect <path>] [--probe-tools] [--json]"
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

    print(f"echelon stack: unknown subcommand '{subcmd}'", file=sys.stderr)
    sys.exit(1)


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
        run_typer_cli(args)
    except click_exceptions as exc:
        exc.show()
        sys.exit(exc.exit_code)
