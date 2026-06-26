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
import shutil
import subprocess
import sys
from pathlib import Path

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
# echelon.run.md → "echelon run" → skill → ... (155 nested processes).
SKILL_MAP = {
    "bugfix":  "echelon.bugfix",
    "build":   "echelon.build",
    "review":  "echelon.review",
    "change":  "echelon.change",
    "codegen": "echelon.codegen",
    "verify-spec": "echelon.verify-spec",
    "reopen":  "echelon.reopen",
}

CLI_VERSION = "3.0.0"

from echelon.ui import banner as _banner  # noqa: E402  (after stdlib imports)


USAGE = f"""\
echelon {CLI_VERSION}

Usage: echelon <command> [args...]

Commands:
  init                                      One-time project setup (no LLM)
  run     <description> [--mode semi|banzai|guided] [--reset]
                        [--next-phase <phase-id>]
                                            Run echelon squad. Resumes if a run is in
                                            progress with the same task; starts fresh if
                                            task differs or run is complete.
                                            --reset            force fresh start
                                            --next-phase <id>  recover from invalid-phase block
  status                                    Show current run state, staging artifacts, open
                                            issues, cost, and next action — orient after a
                                            break without reading files manually.
  continue [--mode semi|banzai|guided]      Run the next no-input recovery action for the
                                            last run. Retries running/interrupted runs,
                                            retries recoverable failed dispatches, or
                                            advances completed-but-incomplete Phase A work.
                                            If human input is needed, prints `resume`.
  rewind  <phase-id>                        Rewind the active squad run to a safe checkpoint
                                            phase and prepare it for `echelon continue`.
  resume  "<answers>"                       Answer escalation questions from a blocked run.
                                            Use only when the run asked for human input;
                                            after recording the answer, Echelon continues.
  bugfix  <spec_id> <description>           Diagnose and plan a bugfix
  verify-spec <spec_id> [strict=true] [--reconcile] [--dry-run]
                                            Audit implementation against spec
  reopen  <spec_id> [from=<report>]          Reopen spec from fulfillment gaps
  build   <spec_id>                         Build implementation for a spec
  review  <spec_id> [pr_url=<url>]          Triage PR review comments
  change  <spec_id> <description>           Plan a scope change
  codegen <spec_id>                         Run SOAR codegen pipeline
  cicd                                      Retired; use 'echelon harness init'
  artifacts <spec_id>                       Generate specs/<id>/ARTIFACTS.md
  land    <spec_id> [--continue] [--prepare-only] [--no-autoresolve]
                    [--allow-fulfillment-gaps] [--strategy merge|rebase]
                                            Land a spec: merge PR, clean up
  harness init   [<target_repo>]            Initialize harness (no LLM)
  harness run    <spec_id> [strategy=<s>]   Run build→verify→PR loop
  harness resume <spec_id> [strategy=<s>]   Resume harness blocked on verify_command_needed
  spec target    <spec_id> <repo> [repo...] Set target repos in spec frontmatter

Skill file locations (auto-detected from ECHELON_LLM env var):
  Claude   : .claude/skills/speckit-echelon-<cmd>/[Ss]kill.md
  Copilot  : .github/agents/speckit.echelon.<cmd>.agent.md
  Opencode : .opencode/command/speckit.echelon.<cmd>.md
  Codex    : .claude/skills/speckit-echelon-<cmd>/[Ss]kill.md
"""


# ── init (pure Python, no LLM) ────────────────────────────────────────────

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


def _cmd_init(project_dir: Path) -> None:
    ext_dir = project_dir / ".specify" / "extensions" / "echelon"
    echelon_cfg = ext_dir / "echelon-config.yml"

    # Step 1: Confirm project config exists (created by `specify extension add echelon`)
    if not echelon_cfg.exists():
        print(
            f"✗ Project config not found: {echelon_cfg}\n"
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

    # Step 2b: Provision MemPalace wing
    print("\n▶ Configuring MemPalace wing...")
    _provision_wing(project_dir, echelon_cfg)

    # Step 3: Run deploy-init.sh
    init_script = ext_dir / "scripts" / "bash" / "deploy-init.sh"
    if not init_script.exists():
        print(
            f"✗ deploy-init.sh not found at {init_script}\n"
            "  Ensure the echelon extension is deployed via spec-kit.",
            file=sys.stderr,
        )
        sys.exit(1)

    result = subprocess.run(
        ["bash", str(init_script), str(project_dir), str(echelon_cfg)],
        cwd=str(project_dir),
    )
    if result.returncode != 0:
        sys.exit(result.returncode)

    # Step 4: Confirm
    state_file = project_dir / ".specify" / "squad" / "deploy-state.json"
    _banner("ECHELON INIT — COMPLETE", [
        ("Config",       str(echelon_cfg)),
        ("Deploy state", str(state_file)),
        ("Next step",    "echelon run <description>"),
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
    choice = input("  [Y]es archive / [n]o keep in runs/ / [s]kip: ").strip().lower()

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
            "Usage: echelon land <spec_id> [--continue] [--prepare-only] "
            "[--no-autoresolve] [--allow-fulfillment-gaps] "
            "[--strategy merge|rebase]\n\n"
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
            print(f"✗ unknown option for echelon land: {arg}", file=sys.stderr)
            sys.exit(1)
        else:
            print(f"✗ unexpected argument for echelon land: {arg}", file=sys.stderr)
            sys.exit(1)
        idx += 1

    if strategy not in {"merge", "rebase"}:
        print("✗ --strategy must be 'merge' or 'rebase'", file=sys.stderr)
        sys.exit(1)

    from harness.config import load_config, ValidationError as HarnessValidationError
    from harness.gitops import GitOpsManager
    from harness.land import LandOptions, land
    options = LandOptions(
        autoresolve=autoresolve,
        prepare_only=prepare_only,
        continue_existing=continue_existing,
        strategy=strategy,
        allow_fulfillment_gaps=allow_fulfillment_gaps,
    )
    project_dir = Path.cwd()

    try:
        config = load_config()
    except HarnessValidationError as e:
        print(f"✗ Harness config error: {e}\n  Fix: re-run 'echelon harness init'.", file=sys.stderr)
        sys.exit(1)
    gitops = GitOpsManager(config)

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


# ── harness subcommands (pure Python, no LLM) ────────────────────────────

def _cmd_harness(args: list[str]) -> None:
    if not args or args[0] in ("-h", "--help"):
        print(
            "Usage: echelon harness <subcommand> [args...]\n\n"
            "Subcommands:\n"
            "  init   [<target_repo>]             Initialize harness — config, mirror clone, image fingerprint\n"
            "  run    <spec_id> [strategy=<s>]    Run build→verify→PR loop\n"
            "                                     strategy: default (echelon squad) or codegen (SOAR)\n"
            "                                     mode:     semi (default) | banzai | guided\n"
            "  resume <spec_id>                   Resume a blocked run (e.g. after adding verify_command)\n\n"
            "Examples:\n"
            "  echelon harness init\n"
            "  echelon harness init https://github.com/org/repo\n"
            "  echelon harness run 001\n"
            "  echelon harness run 001 strategy=codegen\n"
            "  echelon harness run 001 strategy=default mode=banzai\n"
            "  echelon harness resume 001\n"
        )
        return

    subcmd = args[0]
    if subcmd == "init":
        _cmd_harness_init(args[1:])
    elif subcmd == "run":
        _cmd_harness_run(args[1:])
    elif subcmd == "resume":
        _cmd_harness_resume(args[1:])
    else:
        print(f"echelon harness: unknown subcommand '{subcmd}'\n", file=sys.stderr)
        sys.exit(1)


def _cmd_harness_init(args: list[str]) -> None:
    import logging
    import os
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    target_repo = args[0] if args else "."
    base_dir = str(Path.cwd())
    bind_mount_ack = os.environ.get("HARNESS_BIND_MOUNT_ACK", "").lower() in ("true", "1", "yes")

    from harness.init import init_harness, InitError
    try:
        config = init_harness(
            target_repo=target_repo,
            base_dir=base_dir,
            bind_mount_ack=bind_mount_ack,
        )
    except InitError as e:
        print(f"✗ echelon harness init failed: {e}", file=sys.stderr)
        sys.exit(1)

    config_file = Path(base_dir) / ".specify" / "extensions" / "echelon" / "echelon-config.yml"
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
        ("Target repo", config.target_repo),
        ("Config",      str(config_file)),
        ("Mirror",      str(mirror_dir)),
        ("Provider",    config.provider),
        ("PR host",     config.pr_host),
    ]
    if image_note.strip():
        fields.append(("Base image", image_note.strip()))
    fields.extend(_harness_init_detection_fields(config_file))
    fields.append(("Next step", "echelon run \"<feature>\"\n  echelon harness run <spec_id>"))
    _banner("HARNESS INIT — COMPLETE", fields)


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


def _cmd_cicd(args: list[str]) -> None:
    """Retired CI/CD auto-generation command."""
    print(
        "✗ echelon cicd is retired.\n\n"
        "  The old command launched a full LLM squad and could create new specs or\n"
        "  mutate Docker/deploy/CI files when the harness only needed verification.\n\n"
        "  For harness verification, run:\n"
        "    echelon harness init\n\n"
        "  If auto-detection cannot make a high-confidence choice, add a top-level\n"
        "  verify_command to .specify/extensions/echelon/echelon-config.yml, for example:\n"
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
        ignore=shutil.ignore_patterns(
            ".git",
            "__pycache__",
            ".pytest_cache",
            "node_modules",
        ),
    )


def _cmd_harness_run(args: list[str]) -> None:
    import logging
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if not args:
        print("echelon harness run: missing spec_id\n", file=sys.stderr)
        sys.exit(1)

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

    parts = [f"spec {spec_id}", f"{mode} mode", f"strategies={strategy}"]
    if free_text:
        parts.append(f"task: {' '.join(free_text)}")
    if reset:
        parts.append("--reset")
    user_message = " ".join(parts)

    from harness.config import load_config, ValidationError as HarnessValidationError
    from harness.docker_provider import DockerWorktreeProvider
    from harness.gitops import GitOpsManager
    from harness.skills.run_skill import run, _count_tasks
    from harness.plan_validation import PlanValidationError, validate_plan_file
    from harness.task_validation import TaskValidationError

    # Orchestrator mode: spec targets take priority over local echelon-config.yml.
    # Check targets first so a polyrepo root with its own echelon-config.yml (e.g. for
    # deploy) doesn't silently bypass target validation and run against the wrong repo.
    from harness.spec_frontmatter import (
        find_spec_dir,
        read_frontmatter,
        write_status as _write_spec_status,
        write_targets,
    )
    from harness.spec_snapshot import snapshot_spec_dir
    from echelon.orchestrator import (
        run_multi_target,
        validate_single_target,
        validate_targets,
    )
    from echelon.target_detection import detect_target

    target_env = os.environ.get("ECHELON_TARGET_REPO_PATH")
    polyrepo_env = os.environ.get("ECHELON_POLYREPO_ROOT")
    target_name_env = os.environ.get("ECHELON_TARGET_REPO_NAME")
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
        frontmatter = read_frontmatter(spec_dir)
        targets_rel: list[str] = frontmatter.get("targets") or []
        if targets_rel and not target_env:
            # A spec may declare one or many targets. Multiple targets dispatch
            # to each sub-repo in parallel via run_multi_target (the polyrepo
            # design documented in CLAUDE.md); a single target is just the
            # one-element case of the same path.
            targets = validate_targets(targets_rel, polyrepo_root)
            sys.exit(run_multi_target(spec_id, targets, args[1:]))

        detection = detect_target(spec_dir=spec_dir, polyrepo_root=polyrepo_root)
        if target_env:
            detection = None
        if detection and detection.decision == "recommend":
            if mode == "banzai" and detection.recommended_target:
                write_targets(spec_dir, [detection.recommended_target])
                target = validate_single_target([detection.recommended_target], polyrepo_root)
                print(
                    f"✓ Wrote inferred implementation target: {detection.recommended_target} "
                    f"(confidence {detection.confidence:.2f})"
                )
                sys.exit(run_multi_target(spec_id, [target], args[1:]))
            print(
                f"✗ No implementation target configured.\n"
                f"  Recommended implementation target: {detection.recommended_target} "
                f"(confidence {detection.confidence:.2f})\n"
                "  Evidence:\n"
                + "".join(
                    f"  - {item}\n"
                    for item in (
                        detection.candidates[0].evidence
                        if detection.candidates else []
                    )
                )
                + f"  Confirm with: echelon spec target {resolved_spec_id} {detection.recommended_target}\n"
                + f"  Then rerun:  echelon harness run {resolved_spec_id}",
                file=sys.stderr,
            )
            sys.exit(1)
        if detection and detection.decision == "ambiguous":
            print(
                "✗ No implementation target configured and target detection was ambiguous.\n"
                f"  Fix: run 'echelon spec target {spec_id} <repo>'.",
                file=sys.stderr,
            )
            sys.exit(1)

    # Single-repo mode: require local echelon-config.yml (harness config).
    echelon_yml = config_root / ".specify" / "extensions" / "echelon" / "echelon-config.yml"
    if not echelon_yml.exists():
        print(
            "✗ Harness not initialised for this project.\n"
            f"  Expected: {echelon_yml}\n"
            "  Fix: run 'echelon harness init' first, or add 'targets:' to your spec.",
            file=sys.stderr,
        )
        sys.exit(1)

    from harness.paths import mirror_path as _mirror_path_fn
    mirror_path = _mirror_path_fn(harness_base_dir)
    if not mirror_path.exists() and not target_env:
        print(
            "✗ Harness mirror not initialised for this project.\n"
            f"  Expected: {mirror_path}\n"
            "  Fix: run 'echelon harness init' to create the mirror.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        config = load_config(project_root=config_root)
    except HarnessValidationError as e:
        print(f"✗ Harness config error: {e}\n  Fix: re-run 'echelon harness init'.", file=sys.stderr)
        sys.exit(1)
    if target_env:
        config.target_repo = str(Path(target_env).resolve())
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
            f"  Then rerun:        echelon harness run {spec_id}",
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
                f"  Then rerun:        echelon harness run {spec_id}",
                file=sys.stderr,
            )
            sys.exit(1)
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
                f"       echelon harness run {spec_id}",
                file=sys.stderr,
            )
            sys.exit(1)
        _print_harness_error_and_exit(
            project_root=Path.cwd(),
            spec_id=spec_id,
            strategy=strategy,
            command="echelon harness run",
            exc=exc,
        )


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
        f"  Next:  {command} {spec_id}",
        file=sys.stderr,
    )
    sys.exit(1)


def _cmd_harness_resume(args: list[str]) -> None:
    import logging
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if not args or args[0] in ("-h", "--help"):
        print(
            "Usage: echelon harness resume <spec_id> [strategy=<s>] [mode=<guided|semi|banzai>]\n\n"
            "Resume a blocked harness run. Supports verify_command_needed and\n"
            "recovery from build_incomplete/publish_failed committed work.\n\n"
            "Steps:\n"
            "  1. For verify_command_needed: add verify_command to echelon-config.yml\n"
            "     (or re-run 'echelon harness init' to auto-detect high-confidence commands).\n"
            "  2. Run: echelon harness resume <spec_id>\n",
        )
        return

    spec_id = args[0]
    kv: dict[str, str] = {}
    for arg in args[1:]:
        if "=" in arg:
            k, _, v = arg.partition("=")
            kv[k.strip()] = v.strip()
    strategy = kv.get("strategy", "default")
    mode = kv.get("mode", "semi")

    from harness.config import load_config, ValidationError as HarnessValidationError
    from harness.docker_provider import DockerWorktreeProvider
    from harness.gitops import GitOpsManager
    from harness.paths import build_dir, current_build_marker, runs_dir
    from harness.state import StateStore

    echelon_yml = Path.cwd() / ".specify" / "extensions" / "echelon" / "echelon-config.yml"
    if not echelon_yml.exists():
        print(
            "✗ Harness not initialised for this project.\n"
            f"  Expected: {echelon_yml}\n"
            "  Fix: run 'echelon harness init' first.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        config = load_config()
    except HarnessValidationError as e:
        print(f"✗ Harness config error: {e}\n  Fix: re-run 'echelon harness init'.", file=sys.stderr)
        sys.exit(1)

    # Resolve state_dir from the current-build marker; fall back to runs/state/
    # for runs that pre-date build_id or were started without one.
    cwd = Path.cwd()
    marker = current_build_marker(cwd, spec_id)
    if marker.exists():
        state_dir = build_dir(cwd, marker.read_text().strip()) / "state"
    else:
        state_dir = runs_dir(cwd) / "state"
    state_store = StateStore(state_dir, spec_id, strategy)
    state = state_store.read()

    if not state:
        print(
            f"✗ No harness state found for spec {spec_id!r} (strategy={strategy!r}).\n"
            "  Run 'echelon harness run <spec_id>' to start a new run.",
            file=sys.stderr,
        )
        sys.exit(1)

    current_status = state.get("status", "unknown")
    termination_reason = state.get("termination_reason", "")
    recoverable_reasons = {"build_incomplete", "publish_failed"}
    continuation_reasons = {"checkpoint_outer_cap"}

    if current_status != "blocked" and termination_reason not in recoverable_reasons:
        print(
            f"✗ Spec {spec_id!r} is not blocked (status={current_status!r}).\n"
            "  Use 'echelon harness run <spec_id>' to start or continue.",
            file=sys.stderr,
        )
        sys.exit(1)

    if termination_reason not in {"verify_command_needed", *recoverable_reasons, *continuation_reasons}:
        print(
            f"✗ Spec {spec_id!r} is blocked for a different reason: {termination_reason!r}.\n"
            "  Use 'echelon harness run <spec_id>' to resume.",
            file=sys.stderr,
        )
        sys.exit(1)

    gitops = GitOpsManager(config)

    if termination_reason in recoverable_reasons:
        from harness.recovery import HarnessRecoveryError, recover_blocked_run

        build_id = marker.read_text().strip() if marker.exists() else ""
        try:
            recovered = recover_blocked_run(
                project_dir=cwd,
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
        _banner("HARNESS RESUME — RECOVERED", [
            ("Spec", spec_id),
            ("Strategy", strategy),
            ("Reason", termination_reason),
            ("Source", recovered.source),
            ("Commit", recovered.commit[:12]),
            ("Branch", recovered.target_branch),
            ("Status", action),
        ])

        from harness.skills.run_skill import run
        provider = DockerWorktreeProvider(
            buffer_limit_bytes=config.buffer_limit_bytes,
            container_cli=_container_runtime_cli(config),
        )
        user_message = f"spec {spec_id} strategy={strategy} mode={mode} resume"
        try:
            run(user_message, provider, gitops)
        except Exception as exc:
            if _is_docker_unavailable_error(exc):
                _mark_current_harness_state_blocked(
                    cwd,
                    spec_id,
                    strategy,
                    "docker_unavailable",
                )
                print(
                    f"✗ {_container_runtime_display(config)} is not running or is unreachable.\n"
                    f"  Error: {exc}\n"
                    f"  Fix: {_container_runtime_fix(_container_runtime_cli(config))}, then rerun:\n"
                    f"       echelon harness resume {spec_id}",
                    file=sys.stderr,
                )
                sys.exit(1)
            _print_harness_error_and_exit(
                project_root=cwd,
                spec_id=spec_id,
                strategy=strategy,
                command="echelon harness resume",
                exc=exc,
            )
        return

    if not config.verify_command:
        print(
            "✗ verify_command is still not set in echelon-config.yml.\n\n"
            "  Option 1 — auto-detect:  echelon harness init\n"
            "  Option 2 — manual:       add to echelon-config.yml:\n"
            "    verify_command: swift test --package-path Packages/MyLib\n"
            "    verify_command: pytest\n"
            "    verify_command: go test ./...\n\n"
            f"  Then re-run:  echelon harness resume {spec_id}",
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
        run(user_message, provider, gitops)
    except Exception as exc:
        if _is_docker_unavailable_error(exc):
            _mark_current_harness_state_blocked(
                cwd,
                spec_id,
                strategy,
                "docker_unavailable",
            )
            print(
                f"✗ {_container_runtime_display(config)} is not running or is unreachable.\n"
                f"  Error: {exc}\n"
                f"  Fix: {_container_runtime_fix(_container_runtime_cli(config))}, then rerun:\n"
                f"       echelon harness resume {spec_id}",
                file=sys.stderr,
            )
            sys.exit(1)
        _print_harness_error_and_exit(
            project_root=cwd,
            spec_id=spec_id,
            strategy=strategy,
            command="echelon harness resume",
            exc=exc,
        )


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

    completed = run_state.get("completed_phases")
    completed_phases = completed if isinstance(completed, list) else []
    if phase_id in completed_phases:
        return None

    return phase_id


def _blocked_non_escalation_recovery_command(run_state: dict) -> str | None:
    blocked_reason = str(run_state.get("blocked_reason") or "").strip()
    phase_id = _last_incomplete_dispatch_phase(run_state)
    if _is_retryable_dispatch_block_reason(blocked_reason) and phase_id in _SAFE_REWIND_PHASES:
        return f"echelon rewind {phase_id}"
    return None


def _blocked_failed_dispatch_phase(run_state: dict) -> str | None:
    """Return the incomplete phase that caused a deterministic dispatch block."""

    blocked_reason = str(run_state.get("blocked_reason") or "").strip()
    if not _is_retryable_dispatch_block_reason(blocked_reason):
        return None
    if run_state.get("escalation_question"):
        return None

    phase_id = _last_incomplete_dispatch_phase(run_state)
    if not phase_id:
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
                command="echelon continue",
                note="will retry the interrupted phase",
            )
        return _RunRecoveryAction(
            "manual_recovery",
            reason="interrupted",
            command="echelon run --next-phase <phase-id>",
            note="interrupted run does not record a retryable phase",
        )

    if status != "blocked":
        return _RunRecoveryAction("advance")

    if run_state.get("escalation_question"):
        return _RunRecoveryAction(
            "human_resume",
            reason=reason or "human answer required",
            command='echelon resume "<your answer>"',
            note=str(run_state.get("escalation_question") or "").strip(),
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
            command="echelon continue",
            note="will retry the failed phase; it was not marked complete",
        )

    if reason == "token_budget_exhausted":
        return _RunRecoveryAction(
            "manual_recovery",
            reason=reason,
            command="increase analysis.token_budget_k, then echelon continue",
            note="the run cannot continue until the configured budget is higher",
        )

    if "invalid next_phase" in reason:
        return _RunRecoveryAction(
            "manual_recovery",
            reason=reason,
            command="echelon run --next-phase <phase-id>",
            note="choose a valid phase from echelon status output",
        )

    if not reason:
        return _RunRecoveryAction("advance")

    return _RunRecoveryAction(
        "manual_recovery",
        reason=reason,
        command="fix the blocker, then echelon continue",
        note="no human question, safe rewind target, or retryable dispatch was recorded",
    )


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
                fields.append(("next", f"echelon land {spec_id}"))
            else:
                fields.append(("next", f"echelon land {spec_id}"))
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
        if is_checkpoint:
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
                        f"commit or stash tracked changes, then echelon harness resume {spec_id}",
                    )
                )
            else:
                fields.append(("next", f"echelon harness resume {spec_id}"))
        elif termination_reason == "docker_unavailable":
            fields.append(("fix", "start the configured container runtime and wait until it reports running"))
            fields.append(("next", f"echelon harness run {spec_id}"))
            subtitle = "HARNESS BUILD BLOCKED"
        elif harness_status in {"running", "in_progress"}:
            fields.append(("next", "echelon status"))
            subtitle = "HARNESS BUILD IN PROGRESS"
        else:
            fields.append(("next", f"echelon harness run {spec_id} --reset"))
            subtitle = "HARNESS BUILD BLOCKED"
        if is_checkpoint:
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
                ("then", "echelon continue"),
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
            "     → echelon continue\n"
            "       (CHIEF will invoke speckit.constitution and record provenance)"
        )
    elif not const_path.exists():
        blockers.append(
            "constitution.md absent\n"
            "     → echelon continue\n"
            "       (CHIEF will invoke speckit.constitution and fill it)"
        )
    else:
        markers = _constitution_template_markers(const_path.read_text(errors="replace"))
        if markers:
            blockers.append(
                "unresolved constitution template markers remain: "
                + ", ".join(markers)
                + "\n"
                "     → echelon continue\n"
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
                    f"     → echelon continue\n"
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
                    "     → echelon continue\n"
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
            f"     → echelon continue\n"
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
            "     → echelon continue"
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
                "  → echelon resume \"<tell CARTOGRAPHER what to fix>\"\n"
                "    e.g. \"Fix structure: split compound FRs, add numeric thresholds\""
            )
            warnings.append("\n".join(msg_lines))
        elif escalation_q:
            warnings.append(
                f"Run blocked: {escalation_q}\n"
                "     → echelon resume \"<your answer>\""
            )
        else:
            warnings.append(
                "Run blocked\n"
                "     → echelon resume \"<your answer>\""
            )

    # ── Print ──────────────────────────────────────────────────────────────
    # Single readiness predicate: a blocked/interrupted run is never "READY TO
    # BUILD", even when no explicit blocker was collected.
    fields: list[tuple[str, str]] = []
    if _phase_a_buildable(result_status, blockers):
        if ready_items:
            fields.append(("ready", "\n".join(f"✓ {item}" for item in ready_items)))
        harness_cmd = f"echelon harness run {newest_spec_id}" if newest_spec_id else "echelon harness run <spec-id>"
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
        fields.append(("answer", "echelon resume \"<your answers>\""))

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

    # Parse optional flags
    mode = "semi"
    reset = False
    next_phase = ""
    message_parts: list[str] = []
    i = 0
    while i < len(args):
        if args[i] == "--mode" and i + 1 < len(args):
            mode = args[i + 1]
            i += 2
        elif args[i] == "--message" and i + 1 < len(args):
            message_parts.append(args[i + 1])
            i += 2
        elif args[i] == "--reset":
            reset = True
            i += 1
        elif args[i] == "--next-phase" and i + 1 < len(args):
            next_phase = args[i + 1]
            i += 2
        else:
            message_parts.append(args[i])
            i += 1
    message = " ".join(message_parts)

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
    ])

    result = controller.run(user_message=message, mode=mode, next_phase_override=next_phase)

    status_icon = "✓" if result.status == "done" else "✗"
    _banner(f"{status_icon}  SQUAD RUN {result.status.upper()}", [
        ("Phase", result.phase),
        ("Artifacts", str(squad_dir)),
    ])
    _print_next_steps(project_root, result.status)


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

    run_dir = _find_current_run_dir(project_root)
    spec_dir = _active_continue_spec_dir(project_root, current_state, run_dir)
    published_spec_dir = _published_continue_spec_dir(project_root, current_state)
    return validate_phase_a_readiness(
        current_state,
        _phase_a_readiness_candidate_dirs(
            project_root,
            current_state,
            run_dir,
            active_spec_dir=spec_dir,
            published_spec_dir=published_spec_dir,
        ),
    ).ready


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
            ("Next",   'echelon run "<task description>"'),
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
            fields.append(("Next", "echelon continue"))
        elif run_status == "blocked":
            fields.append(("Next", 'echelon resume "<your answer>"'))

        _banner("RUN STATE", fields)

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
    - running / in_progress: re-invokes echelon run with the same message (resumes)
    - blocked:               prints echelon resume guidance and exits
    - done / interrupted:    determines the next actionable phase from the build-
                             readiness analysis and starts a new run there, reusing
                             the original task message and mode from state.json
    - nothing found:         prints guidance to start a fresh echelon run
    """
    import json as _json

    _print_extension_drift_warning(project_root, ext_dir)

    # Optionally accept --mode override
    mode_override = ""
    i = 0
    while i < len(args):
        if args[i] == "--mode" and i + 1 < len(args):
            mode_override = args[i + 1]
            i += 2
        else:
            i += 1

    squad_dir = _find_current_run_dir(project_root)
    if not squad_dir or not (squad_dir / "state.json").exists():
        print(
            "No prior run found in this project.\n"
            "Start a new run:  echelon run \"<task description>\"",
            flush=True,
        )
        return

    state = _json.loads((squad_dir / "state.json").read_text())
    user_message = state.get("user_message", "")
    mode = mode_override or state.get("autonomy_mode") or state.get("mode", "semi")
    status = state.get("status", "")
    cur_phase = state.get("phase", "")
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
                ("then", "echelon continue"),
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

    # terminal-blocked: the consecutive-fail guard fired. echelon resume recorded the
    # user's answer but left phase=terminal-blocked (a TERMINAL_PHASE). The controller
    # would exit immediately from that phase, so we repair state here — advance the
    # phase to the next runnable one — before resuming in the SAME squad dir.
    if cur_phase == "terminal-blocked":
        next_phase = _next_continue_phase(project_root)
        if next_phase is None:
            print(
                "Build is ready — nothing left to do in Phase A.\n\n"
                "  echelon harness run <spec-id>",
                flush=True,
            )
            return
        start_phase(next_phase, verb="Continuing from")
        return

    if status in ("running", "in_progress"):
        # Live run — let echelon run pick it up (same message → same dir → resume)
        print(f"[squad] Resuming active run in {squad_dir.name}…", flush=True)
        _cmd_run([user_message, "--mode", mode], project_root=project_root, ext_dir=ext_dir)
        return

    # Determine the next phase automatically
    next_phase = _next_continue_phase(project_root)
    if next_phase is None:
        print(
            "Build is ready — nothing left to do in Phase A.\n\n"
            "  echelon harness run <spec-id>",
            flush=True,
        )
        return

    start_phase(next_phase, verb="Continuing from")


def _cmd_rewind(
    args: list[str],
    project_root: Path,
) -> None:
    if len(args) != 1:
        print(
            "Usage: echelon rewind <phase-id>\n"
            f"Supported phases: {', '.join(_SAFE_REWIND_PHASES)}",
            file=sys.stderr,
        )
        sys.exit(1)

    target = args[0].strip()
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
        ("next step", "echelon continue"),
    ]
    _banner("REWIND PREPARED", details)


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
            "Usage: echelon resume \"<your answers>\"\n"
            "  Answer the escalation questions shown when the run was blocked.\n"
            "  Example: echelon resume \"Q1: yes, I own the IP  Q2: 13+  Q3: short missions\"",
            file=sys.stderr,
        )
        sys.exit(1)

    squad_dir = _find_current_run_dir(project_root)
    if squad_dir is None:
        print("✗ No active squad run found.", file=sys.stderr)
        print("  Start a run with: echelon run \"<task>\"", file=sys.stderr)
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
            "  Use: echelon run --next-phase <phase-id>  to recover manually",
            file=sys.stderr,
        )
        sys.exit(1)
    ensure_blocked_decision(state)

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
        f"> Provided via `echelon resume` in response to the escalation block.\n\n"
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
    # Instead, record the answer and tell the user to run `echelon continue`.
    if blocked_phase == "terminal-blocked":
        _banner("SQUAD RESUMED", [
            ("answer", (answer[:60] + "…") if len(answer) > 60 else answer),
            ("status", "unblocked — answer recorded"),
            ("next", "continuing"),
            ("note", "delegating to echelon continue"),
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
from harness.llm_tool_policy import (
    LlmToolPolicy,
    build_llm_cli_command,
    build_opencode_skill_command,
)


def _find_skill(skill_base: str, project_dir: Path, cli: str) -> Path | None:
    return _find_skill_impl(skill_base, project_dir, cli)


def _build_prompt(skill_path: Path, arguments: str) -> str:
    return _build_skill_prompt_impl(skill_path, arguments)


def _load_cli_tool_policy(project_dir: Path) -> LlmToolPolicy:
    from harness.config import load_config

    return load_config(project_dir, squad_only=True).llm.tool_policy


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


# ── spec subcommands ──────────────────────────────────────────────────────────

def _cmd_spec(args: list[str]) -> None:
    if not args or args[0] in ("-h", "--help"):
        print(
            "Usage: echelon spec <subcommand> [args...]\n\n"
            "  target <spec_id> <repo> [repo...]   Set targets: in spec frontmatter\n",
            file=sys.stderr,
        )
        sys.exit(0)
    subcmd = args[0]
    if subcmd == "target":
        _cmd_spec_target(args[1:])
    else:
        print(f"echelon spec: unknown subcommand '{subcmd}'\n", file=sys.stderr)
        sys.exit(1)


def _cmd_spec_target(args: list[str]) -> None:
    if len(args) < 2:
        print(
            "echelon spec target: usage: echelon spec target <spec_id> <repo> [repo...]\n",
            file=sys.stderr,
        )
        sys.exit(1)

    spec_id, repos = args[0], args[1:]

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

    md = write_targets(spec_dir, repos)
    try:
        display = md.relative_to(start)
    except ValueError:
        display = md
    print(f"Updated {display}")
    print("  targets:")
    for r in repos:
        print(f"    - {r}")


def _cmd_artifacts(args: list[str]) -> None:
    if not args:
        print("echelon artifacts: missing spec_id", file=sys.stderr)
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


# ── Entry point ───────────────────────────────────────────────────────────

def main() -> None:
    args = sys.argv[1:]

    if not args or args[0] in ("-h", "--help"):
        print(USAGE)
        sys.exit(0)

    if args[0] in ("-v", "--version", "version"):
        print(f"echelon {CLI_VERSION}")
        sys.exit(0)

    command = args[0]

    if command == "init":
        _cmd_init(Path.cwd())
        return

    if command == "harness":
        _cmd_harness(args[1:])
        return

    if command == "cicd":
        _cmd_cicd(args[1:])
        return

    if command == "spec":
        _cmd_spec(args[1:])
        return

    if command == "artifacts":
        _cmd_artifacts(args[1:])
        return

    if command == "land":
        _cmd_land(args[1:])
        return

    if command == "status":
        _cmd_status(Path.cwd())
        return

    if command == "continue":
        project_root = Path.cwd()
        ext_dir = project_root / ".specify" / "extensions" / "echelon"
        if not ext_dir.exists():
            print(
                f"✗ Echelon extension not installed: {ext_dir}\n"
                "  Run: specify extension add echelon",
                file=sys.stderr,
            )
            sys.exit(1)
        _cmd_continue(args[1:], project_root=project_root, ext_dir=ext_dir)
        return

    if command == "rewind":
        _cmd_rewind(args[1:], project_root=Path.cwd())
        return

    if command == "resume":
        if os.environ.get("ECHELON_SQUAD_ACTIVE"):
            print(
                "✗ echelon resume: refusing nested invocation (ECHELON_SQUAD_ACTIVE is set).",
                file=sys.stderr,
            )
            sys.exit(1)
        project_root = Path.cwd()
        ext_dir = project_root / ".specify" / "extensions" / "echelon"
        if not ext_dir.exists():
            print(
                f"✗ Echelon extension not installed: {ext_dir}\n"
                "  Run: specify extension add echelon",
                file=sys.stderr,
            )
            sys.exit(1)
        _cmd_resume(args[1:], project_root=project_root, ext_dir=ext_dir)
        return

    if command == "run":
        if os.environ.get("ECHELON_SQUAD_ACTIVE"):
            print(
                "✗ echelon run: refusing nested invocation — already inside a squad "
                "agent dispatch (ECHELON_SQUAD_ACTIVE is set).\n"
                "  Squad agents must not call 'echelon run'. "
                "Return echelon_result: from your agent instead.",
                file=sys.stderr,
            )
            sys.exit(1)
        project_root = Path.cwd()
        ext_dir = project_root / ".specify" / "extensions" / "echelon"
        if not ext_dir.exists():
            print(
                f"✗ Echelon extension not installed: {ext_dir}\n"
                "  Run: specify extension add echelon",
                file=sys.stderr,
            )
            sys.exit(1)
        cfg_file = ext_dir / "echelon-config.yml"
        if not cfg_file.exists():
            print(
                f"✗ Project not initialized — config not found: {cfg_file}\n"
                "  Run: echelon init",
                file=sys.stderr,
            )
            sys.exit(1)
        _cmd_run(args[1:], project_root=project_root, ext_dir=ext_dir)
        return

    if command not in SKILL_MAP:
        print(f"echelon: unknown command '{command}'\n", file=sys.stderr)
        print(USAGE)
        sys.exit(1)

    skill_base = SKILL_MAP[command]
    arguments = " ".join(args[1:])

    if not arguments:
        print(f"echelon {command}: missing arguments\n", file=sys.stderr)
        print(USAGE)
        sys.exit(1)

    project_dir = Path.cwd()
    cli = os.environ.get("ECHELON_LLM", "claude")
    try:
        tool_policy = _load_cli_tool_policy(project_dir)
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
        cmd = build_llm_cli_command(cli, bin_, prompt, tool_policy)
        result = subprocess.run(cmd, cwd=str(project_dir))
    else:
        # claude: use stream-json for live tool-call progress in the terminal
        prompt = _build_prompt(skill_path, arguments)
        _run_claude_streaming(bin_, prompt, project_dir, tool_policy=tool_policy)
        return  # _run_claude_streaming calls sys.exit
    sys.exit(result.returncode)
