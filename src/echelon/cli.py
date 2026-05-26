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

_HR = "=" * 44


def _banner(title: str, fields: list[tuple[str, str]], flush: bool = True) -> None:
    """Print a formatted banner block."""
    print(f"\n{_HR}", flush=flush)
    print(f"  {title}", flush=flush)
    print(_HR, flush=flush)
    if fields:
        label_w = max(len(k) for k, _ in fields) + 1
        for key, val in fields:
            label = f"{key}:".ljust(label_w + 1)
            if "\n" in val:
                print(f"\n  {label}", flush=flush)
                for line in val.strip().splitlines():
                    print(f"    {line}", flush=flush)
            else:
                print(f"\n  {label}  {val}", flush=flush)
    print(f"\n{_HR}\n", flush=flush)


# Maps CLI command → spec-kit skill base name (used to derive file paths)
SKILL_MAP = {
    "run":     "echelon.run",
    "bugfix":  "echelon.bugfix",
    "build":   "echelon.build",
    "review":  "echelon.review",
    "change":  "echelon.change",
    "codegen": "echelon.codegen",
}

USAGE = """\
Usage: echelon <command> [args...]

Commands:
  init                                      One-time project setup (no LLM)
  run     <description>                     Run echelon for a new feature
  bugfix  <spec_id> <description>           Diagnose and plan a bugfix
  build   <spec_id>                         Build implementation for a spec
  review  <spec_id> [pr_url=<url>]          Triage PR review comments
  change  <spec_id> <description>           Plan a scope change
  codegen <spec_id>                         Run SOAR codegen pipeline
  land    <spec_id>                         Land a spec: merge PR, clean up
  harness init [<target_repo>]              Initialize harness (no LLM)
  harness run  <spec_id> [strategy=<s>]     Run build→verify→PR loop
  spec target  <spec_id> <repo> [repo...]   Set target repos in spec frontmatter

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
    print(
        f"\n"
        f"╔══════════════════════════════════════════╗\n"
        f"║         echelon init — complete          ║\n"
        f"╚══════════════════════════════════════════╝\n"
        f"\n"
        f"  config       → {echelon_cfg}\n"
        f"  deploy-state → {state_file}\n"
        f"\n"
        f"Next step:\n"
        f"  echelon run <description>\n"
    )


# ── land (pure Python, no LLM) ────────────────────────────────────────────

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
        print(f"echelon land: {spec_id} landed successfully")
        sys.exit(0)
    else:
        print(f"echelon land: {spec_id} could not be landed (PR merge blocked?)", file=sys.stderr)
        sys.exit(1)


# ── harness subcommands (pure Python, no LLM) ────────────────────────────

def _cmd_harness(args: list[str]) -> None:
    if not args or args[0] in ("-h", "--help"):
        print(
            "Usage: echelon harness <subcommand> [args...]\n\n"
            "Subcommands:\n"
            "  init [<target_repo>]              Initialize harness — config, mirror clone, image fingerprint\n"
            "  run  <spec_id> [strategy=<s>]     Run build→verify→PR loop\n"
            "                                    strategy: default (echelon squad) or codegen (SOAR)\n"
            "                                    mode:     semi (default) | banzai | guided\n\n"
            "Examples:\n"
            "  echelon harness init\n"
            "  echelon harness init https://github.com/org/repo\n"
            "  echelon harness run 001\n"
            "  echelon harness run 001 strategy=codegen\n"
            "  echelon harness run 001 strategy=default mode=banzai\n"
        )
        return

    subcmd = args[0]
    if subcmd == "init":
        _cmd_harness_init(args[1:])
    elif subcmd == "run":
        _cmd_harness_run(args[1:])
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
    from harness.paths import harness_dir
    mirror_dir = harness_dir(Path(base_dir)) / "mirror.git"

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

    print(
        f"\n"
        f"╔══════════════════════════════════════════╗\n"
        f"║      echelon harness init — complete     ║\n"
        f"╚══════════════════════════════════════════╝\n"
        f"\n"
        f"  target_repo  → {config.target_repo}\n"
        f"  config       → {config_file}\n"
        f"  mirror       → {mirror_dir}\n"
        f"  provider     → {config.provider}\n"
        f"  pr_host      → {config.pr_host}\n"
        f"{image_note}"
        f"\n"
        f"Next step:\n"
        f"  echelon run \"<feature description>\"\n"
        f"  echelon harness run <spec_id>\n"
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

    from harness.paths import harness_dir as _harness_dir
    mirror_path = _harness_dir(Path.cwd()) / "mirror.git"
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
