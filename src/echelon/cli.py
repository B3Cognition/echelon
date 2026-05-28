#!/usr/bin/env python3
"""echelon CLI — deterministic entry points for echelon skills.

LLM commands read the corresponding skill markdown, inject arguments,
and invoke the configured LLM CLI so the LLM only executes the skill.

`init` is pure Python — no LLM involved.

Skill file locations by AI tool:
  Claude   : .claude/skills/speckit-echelon-<cmd>/[Ss]kill.md
  Copilot  : .github/agents/speckit.echelon.<cmd>.agent.md
  Opencode : .opencode/command/speckit.echelon.<cmd>.md
Auto-detected from ECHELON_LLM (default: claude).
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

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
    "cicd":    "echelon.cicd",
}

CLI_VERSION = "2.2.0"

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
  continue [--mode semi|banzai|guided]      Advance the last run to its next required phase.
                                            Reads the task and mode from prior state — no
                                            prompt needed. Handles: resume if running,
                                            escalation guidance if blocked, or determines
                                            the correct next phase if done.
  resume  "<answers>"                       Answer escalation questions from a blocked run
                                            and continue it. Use when the run printed
                                            "blocked — human input required".
  bugfix  <spec_id> <description>           Diagnose and plan a bugfix
  build   <spec_id>                         Build implementation for a spec
  review  <spec_id> [pr_url=<url>]          Triage PR review comments
  change  <spec_id> <description>           Plan a scope change
  codegen <spec_id>                         Run SOAR codegen pipeline
  cicd    <spec_id>                         Detect project type and configure verify_command
  land    <spec_id>                         Land a spec: merge PR, clean up
  harness init   [<target_repo>]            Initialize harness (no LLM)
  harness run    <spec_id> [strategy=<s>]   Run build→verify→PR loop
  harness resume <spec_id> [strategy=<s>]   Resume harness blocked on verify_command_needed
  spec target    <spec_id> <repo> [repo...] Set target repos in spec frontmatter

Skill file locations (auto-detected from ECHELON_LLM env var):
  Claude   : .claude/skills/speckit-echelon-<cmd>/[Ss]kill.md
  Copilot  : .github/agents/speckit.echelon.<cmd>.agent.md
  Opencode : .opencode/command/speckit.echelon.<cmd>.md
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
            "Usage: echelon land <spec_id>\n\n"
            "  Merge PR, delete branch, clean worktrees, mark spec as landed.\n",
        )
        sys.exit(0)

    from harness.config import load_config, ValidationError as HarnessValidationError
    from harness.gitops import GitOpsManager
    from harness.land import land

    spec_id = args[0]
    project_dir = Path.cwd()

    try:
        config = load_config()
    except HarnessValidationError as e:
        print(f"✗ Harness config error: {e}\n  Fix: re-run 'echelon harness init'.", file=sys.stderr)
        sys.exit(1)
    gitops = GitOpsManager(config)

    success = land(spec_id, project_dir=project_dir, gitops=gitops)
    if success:
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
    fields.append(("Next step", "echelon run \"<feature>\"\n  echelon harness run <spec_id>"))
    _banner("HARNESS INIT — COMPLETE", fields)


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

    # Orchestrator mode: spec targets take priority over local echelon-config.yml.
    # Check targets first so a polyrepo root with its own echelon-config.yml (e.g. for
    # deploy) doesn't silently bypass target validation and run against the wrong repo.
    from harness.spec_frontmatter import find_spec_dir, read_frontmatter
    from echelon.orchestrator import validate_targets, run_multi_target

    spec_dir = find_spec_dir(spec_id, Path.cwd())
    if spec_dir is not None:
        frontmatter = read_frontmatter(spec_dir)
        targets_rel: list[str] = frontmatter.get("targets") or []
        if targets_rel:
            polyrepo_root = spec_dir.parent.parent
            targets = validate_targets(targets_rel, polyrepo_root)
            sys.exit(run_multi_target(spec_id, targets, args[1:]))

    # Single-repo mode: require local echelon-config.yml (harness config).
    echelon_yml = Path.cwd() / ".specify" / "extensions" / "echelon" / "echelon-config.yml"
    if not echelon_yml.exists():
        print(
            "✗ Harness not initialised for this project.\n"
            f"  Expected: {echelon_yml}\n"
            "  Fix: run 'echelon harness init' first, or add 'targets:' to your spec.",
            file=sys.stderr,
        )
        sys.exit(1)

    from harness.paths import mirror_path as _mirror_path_fn
    mirror_path = _mirror_path_fn(Path.cwd())
    if not mirror_path.exists():
        print(
            "✗ Harness mirror not initialised for this project.\n"
            f"  Expected: {mirror_path}\n"
            "  Fix: run 'echelon harness init' to create the mirror.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        config = load_config()
    except HarnessValidationError as e:
        print(f"✗ Harness config error: {e}\n  Fix: re-run 'echelon harness init'.", file=sys.stderr)
        sys.exit(1)
    gitops = GitOpsManager(config)
    provider = DockerWorktreeProvider(buffer_limit_bytes=config.buffer_limit_bytes)

    task_count = _count_tasks(spec_id, str(Path.cwd()))
    target_display = str(getattr(config, "target_repo", None) or "local")
    _banner("HARNESS RUN", [
        ("Spec", f"{spec_id}" + (f"  ({task_count} tasks)" if task_count else "")),
        ("Mode", mode),
        ("Strategy", strategy),
        ("Target", target_display),
    ])

    run(user_message, provider, gitops)


def _cmd_harness_resume(args: list[str]) -> None:
    import logging
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if not args or args[0] in ("-h", "--help"):
        print(
            "Usage: echelon harness resume <spec_id> [strategy=<s>]\n\n"
            "Resume a harness run that is blocked waiting for verify_command configuration.\n\n"
            "Steps:\n"
            "  1. Add verify_command to echelon-config.yml (or run 'echelon cicd').\n"
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

    if current_status != "blocked":
        print(
            f"✗ Spec {spec_id!r} is not blocked (status={current_status!r}).\n"
            "  Use 'echelon harness run <spec_id>' to start or continue.",
            file=sys.stderr,
        )
        sys.exit(1)

    if termination_reason != "verify_command_needed":
        print(
            f"✗ Spec {spec_id!r} is blocked for a different reason: {termination_reason!r}.\n"
            "  Use 'echelon harness run <spec_id>' to resume.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not config.verify_command:
        print(
            "✗ verify_command is still not set in echelon-config.yml.\n\n"
            "  Option 1 — auto-configure:  echelon cicd\n"
            "  Option 2 — manual:          add to echelon-config.yml:\n"
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
    gitops = GitOpsManager(config)
    provider = DockerWorktreeProvider(buffer_limit_bytes=config.buffer_limit_bytes)
    user_message = f"spec {spec_id} {strategy} mode resume"
    run(user_message, provider, gitops)


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

    (runs_root / ".current").write_text(run_id)
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


def _find_converged_harness_build(project_root: Path) -> Optional[tuple[str, Optional[str]]]:
    """Return (spec_id, pr_url) for the most recent converged harness build, or None.

    Returns None when a newer squad run exists than the harness build — that
    means new spec work has been done since the last harness run.
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
                if data.get("status") == "converged":
                    return data.get("spec_id", ""), data.get("pr_url")
            except Exception:
                pass
    return None


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

    # ── Phase B already done? Skip Phase A checks entirely ─────────────────
    harness = _find_converged_harness_build(project_root)
    if harness:
        spec_id, pr_url = harness
        fields: list[tuple[str, str]] = [("spec", spec_id)] if spec_id else []
        if pr_url:
            fields.append(("PR", pr_url))
            fields.append(("next", f"echelon land {spec_id}"))
        else:
            fields.append(("next", f"echelon land {spec_id}"))
        _banner("NEXT STEP", fields, subtitle="Harness build converged — ready to land")
        return

    # ── Gather signals ──────────────────────────────────────────────────────
    blockers: list[str] = []
    warnings: list[str] = []
    ready_items: list[str] = []

    # 1. Constitution — must exist and not be the blank template
    const_path = project_root / ".specify" / "memory" / "constitution.md"
    if not const_path.exists():
        blockers.append(
            "constitution.md absent\n"
            "     → echelon continue\n"
            "       (CHIEF will invoke speckit.constitution and fill it)"
        )
    else:
        text = const_path.read_text(errors="replace")
        if "[PROJECT_NAME]" in text or "[PRINCIPLE_1_NAME]" in text:
            blockers.append(
                "constitution.md is still the blank template\n"
                "     → echelon continue\n"
                "       (CHIEF will invoke speckit.constitution and fill it)"
            )
        else:
            ready_items.append("constitution.md ✓")

    # 2. Quality gates — check specs/ first, then staging/ for mid-run blocked states
    specs_root = project_root / "specs"

    # Pre-check: if tasks.md already exists, the run completed all phases past quality gates
    tasks_exist_in_spec = False
    if specs_root.exists():
        for d in sorted(specs_root.iterdir(), key=lambda p: p.name, reverse=True):
            if (d / "tasks.md").exists():
                tasks_exist_in_spec = True
            break

    quality_gates_file: Optional[Path] = None
    if specs_root.exists():
        for d in sorted(specs_root.iterdir(), key=lambda p: p.name, reverse=True):
            qg = d / "quality-gates.md"
            if qg.exists():
                quality_gates_file = qg
                break

    # Blocked runs may not have finalized to specs/ yet — load state once for reuse
    run_dir = _find_current_run_dir(project_root)
    run_state: dict = {}
    if run_dir:
        try:
            run_state = _json.loads((run_dir / "state.json").read_text())
        except Exception:
            pass

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
    # (if gates are failing, HOW/tasks missing is expected and not actionable yet)
    # Skip HOW check entirely when tasks.md already exists — the run completed,
    # so HOW was done (possibly with different artifact names for this workflow).
    why2_passed = tasks_exist_in_spec or (
        quality_gates_file is not None
        and not hard_fails
        and not borderline
        and qg_verdict not in ("FAIL", "BLOCKED")
    )
    how_present = 0
    how_missing = []
    if why2_passed and not tasks_exist_in_spec and specs_root.exists():
        for d in sorted(specs_root.iterdir(), key=lambda p: p.name, reverse=True):
            for fname in ("plan.md", "research.md", "data-model.md"):
                if (d / fname).exists():
                    how_present += 1
                else:
                    how_missing.append(fname)
            break  # only check most recent spec dir

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
    newest_spec_id = ""
    if why2_passed and specs_root.exists():
        for d in sorted(specs_root.iterdir(), key=lambda p: p.name, reverse=True):
            newest_spec_id = d.name
            if (d / "tasks.md").exists():
                tasks_present = True
                ready_items.append("tasks.md ✓")
            break

    if why2_passed and not tasks_present:
        blockers.append(
            "tasks.md absent — ORCHESTRATOR (phase3-plan) has not run\n"
            "     → echelon continue"
        )

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
    fields: list[tuple[str, str]] = []
    if not blockers:
        for item in ready_items:
            fields.append(("✓", item))
        harness_cmd = f"echelon harness run {newest_spec_id}" if newest_spec_id else "echelon harness run <spec-id>"
        fields.append(("build", harness_cmd))
        if warnings:
            fields.append(("warnings", "\n".join(f"⚠ {w}" for w in warnings)))
    else:
        if blockers:
            fields.append(("blockers", "\n".join(f"{i}. {b}" for i, b in enumerate(blockers, 1))))
        if warnings:
            fields.append(("warnings", "\n".join(f"⚠ {w}" for w in warnings)))
        if ready_items:
            fields.append(("already done", ", ".join(ready_items)))

    subtitle = "BUILD BLOCKED — fix blockers before running" if blockers else ""
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


def _next_continue_phase(project_root: Path) -> Optional[str]:
    """Return the phase ID to continue from, or None when build is ready.

    Runs the same blockers analysis as _print_next_steps and maps each blocker
    to the entry phase that resolves it. Returns the first (highest-priority)
    actionable phase, or None if everything is clear.
    """
    import json as _json
    import re as _re

    run_dir = _find_current_run_dir(project_root)
    if run_dir and (run_dir / "state.json").exists():
        try:
            state = _json.loads((run_dir / "state.json").read_text())
            recommended = state.get("phase_recommendation")
            if (
                recommended
                and (state.get("convergence_forced") or state.get("convergence_detected"))
            ):
                return recommended
        except Exception:
            pass

    # 0. Constitution missing or template — harness now handles it via phase1-constitution
    const_path = project_root / ".specify" / "memory" / "constitution.md"
    if not const_path.exists():
        return "phase1-constitution"
    if "[PROJECT_NAME]" in const_path.read_text(errors="replace"):
        return "phase1-constitution"

    # 1. WHY2 failures — fix spec first, so CARTOGRAPHER runs before HOW
    specs_root = project_root / "specs"
    quality_gates_file: Optional[Path] = None
    if specs_root.exists():
        for d in sorted(specs_root.iterdir(), key=lambda p: p.name, reverse=True):
            qg = d / "quality-gates.md"
            if qg.exists():
                quality_gates_file = qg
            break

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
    if specs_root.exists():
        for d in sorted(specs_root.iterdir(), key=lambda p: p.name, reverse=True):
            if not all((d / f).exists() for f in ("plan.md", "research.md", "data-model.md")):
                return "phase3-how"
            break

    # 3. tasks.md missing
    if specs_root.exists():
        for d in sorted(specs_root.iterdir(), key=lambda p: p.name, reverse=True):
            if not (d / "tasks.md").exists():
                return "phase3-plan"
            break

    return None  # build is ready


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
    mode = mode_override or state.get("mode", "semi")
    status = state.get("status", "")

    if status in ("running", "in_progress"):
        # Live run — let echelon run pick it up (same message → same dir → resume)
        print(f"[squad] Resuming active run in {squad_dir.name}…", flush=True)
        _cmd_run([user_message, "--mode", mode], project_root=project_root, ext_dir=ext_dir)
        return

    if status == "blocked":
        q = (state.get("escalation_question") or "").strip()
        _banner(
            "CHECKPOINT",
            [
                ("decision needed", q or "(no escalation question recorded)"),
                ("resume with",     'echelon resume "<your answer>"'),
            ],
            subtitle="Run paused. Human decision required.",
        )
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

    phase_labels = {
        "phase1-constitution": "CHIEF → speckit.constitution (creates constitution.md)",
        "phase1-what":         "CARTOGRAPHER (spec amendment + WHY2 re-validation)",
        "phase3-how":          "ARCHITECT (architecture, data-model, contracts)",
        "phase3-plan":         "ORCHESTRATOR (task breakdown)",
        "phase3-consensus":    "Consensus gate (WHY3 + ASSESS2 + PLAN2)",
    }
    label = phase_labels.get(next_phase, next_phase)
    print(
        f"[squad] Continuing from {next_phase} — {label}\n"
        f"[squad] Task:  {(user_message[:80] + '…') if len(user_message) > 80 else user_message}\n"
        f"[squad] Mode:  {mode}",
        flush=True,
    )
    _cmd_run(
        ["--next-phase", next_phase, "--mode", mode, user_message],
        project_root=project_root,
        ext_dir=ext_dir,
    )


def _cmd_resume(
    args: list[str],
    project_root: Path,
    ext_dir: Path,
) -> None:
    """Provide user answers to an escalation-blocked squad run and continue it."""
    from harness.config import get_full_resolved_config, load_config
    from harness.phase_graph import PhaseGraph
    from harness.squad import SquadController
    from harness.squad_provider import SquadCliProvider
    from harness.squad_state import SquadStateStore

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
            ("next", "echelon continue"),
            ("note", "CARTOGRAPHER will apply your fix, then WHY2 re-validates"),
            ("artifacts", str(squad_dir)),
        ])
        _print_next_steps(project_root, "done")
        return

    # Re-run from the current phase (same mode, same task).
    config = load_config(project_root, squad_only=True)
    provider = SquadCliProvider(config)
    graph = PhaseGraph(
        ext_dir / "workflow/definition.yaml",
        ext_dir / "extension.yml",
    )
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
        mode=state.get("mode", "semi"),
    )

    _banner("SQUAD RESUMED", [
        ("Phase resumed", state.get("phase", "?")),
        ("Answer given", (answer[:60] + "…") if len(answer) > 60 else answer),
        ("Status", result.status),
        ("Current phase", result.phase),
        ("Artifacts", str(squad_dir)),
    ])
    _print_next_steps(project_root, result.status)


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


def _find_skill(skill_base: str, project_dir: Path, cli: str) -> Path | None:
    return _find_skill_impl(skill_base, project_dir, cli)


def _build_prompt(skill_path: Path, arguments: str) -> str:
    return _build_skill_prompt_impl(skill_path, arguments)


def _print_event(event: dict, _printer: list = []) -> None:
    # Lazy-init one printer per process; list used as mutable default container.
    if not _printer:
        _printer.append(_StreamEventPrinter())
    _printer[0](event)


def _run_claude_streaming(bin_: str, prompt: str, project_dir: Path, extra_args: list[str] | None = None) -> None:
    """Invoke claude -p with stream-json output and print live progress to stdout."""
    import json as _json

    cmd = [
        bin_, "-p",
        "--dangerously-skip-permissions",
        "--output-format", "stream-json",
        "--verbose",
    ] + (extra_args or [])

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

    if command == "spec":
        _cmd_spec(args[1:])
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

    skill_path = _find_skill(skill_base, project_dir, cli)
    if skill_path is None:
        print(_skill_not_found_msg(skill_base, project_dir, cli), file=sys.stderr)
        sys.exit(1)

    bin_ = shutil.which(cli) or cli
    if cli == "opencode":
        # Use native --command mode; opencode resolves the skill file itself.
        cmd = [bin_, "run", "--dangerously-skip-permissions",
               "--command", f"speckit.{skill_base}", arguments]
        result = subprocess.run(cmd, cwd=str(project_dir))
    elif cli == "copilot":
        prompt = _build_prompt(skill_path, arguments)
        cmd = [bin_, "-p", prompt, "--dangerously-skip-permissions", "--allow-all-tools"]
        result = subprocess.run(cmd, cwd=str(project_dir))
    else:
        # claude: use stream-json for live tool-call progress in the terminal
        prompt = _build_prompt(skill_path, arguments)
        _run_claude_streaming(bin_, prompt, project_dir)
        return  # _run_claude_streaming calls sys.exit
    sys.exit(result.returncode)
