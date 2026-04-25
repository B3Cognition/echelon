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

import os
import shutil
import subprocess
import sys
from pathlib import Path

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
  harness init [<target_repo>]              Initialize harness (no LLM)
  harness run  <spec_id> [strategy=<s>]     Run build→verify→PR loop

Skill file locations (auto-detected from ECHELON_LLM env var):
  Claude   : .claude/skills/speckit-echelon-<cmd>/[Ss]kill.md
  Copilot  : .github/agents/speckit.echelon.<cmd>.agent.md
  Opencode : .opencode/command/speckit.echelon.<cmd>.md
"""


# ── init (pure Python, no LLM) ────────────────────────────────────────────

def _cmd_init(project_dir: Path) -> None:
    ext_dir = project_dir / ".specify" / "extensions" / "echelon"
    echelon_yml = project_dir / "echelon.yml"

    # Step 1: Bootstrap echelon.yml
    if echelon_yml.exists():
        print(f"✓ echelon.yml already exists")
    else:
        template = None
        for name in ("echelon-config.yml", "config-template.yml"):
            candidate = ext_dir / name
            if candidate.exists():
                template = candidate
                break
        if template is None:
            print(
                "✗ echelon.yml not found and no template available.\n"
                f"  Expected template at: {ext_dir / 'echelon-config.yml'}\n"
                "  Have you run 'specify extension add echelon' first?",
                file=sys.stderr,
            )
            sys.exit(1)
        shutil.copy(template, echelon_yml)
        print(f"✓ Bootstrapped echelon.yml from {template.name}")
        print(
            "\n  Review echelon.yml and configure the deploy: block before continuing.\n"
            "  Set type: http or cli, ports (http) or install_path (cli).\n"
        )
        sys.exit(0)

    # Step 2: Validate deploy config
    try:
        import yaml
    except ImportError:
        print("✗ PyYAML not installed. Run: pip install pyyaml", file=sys.stderr)
        sys.exit(1)

    try:
        config = yaml.safe_load(echelon_yml.read_text())
    except Exception as e:
        print(f"✗ Cannot parse echelon.yml: {e}", file=sys.stderr)
        sys.exit(1)

    deploy = config.get("deploy", {})
    deploy_type = deploy.get("type", "http")
    if deploy_type not in ("http", "cli"):
        print(f"✗ deploy.type must be 'http' or 'cli', got: {deploy_type!r}", file=sys.stderr)
        sys.exit(1)
    if deploy_type == "http":
        missing = [k for k in ("blue_port", "green_port", "active_port") if k not in deploy]
        if missing:
            print(
                f"✗ deploy config incomplete in echelon.yml.\n"
                f"  HTTP type requires: {missing}\n"
                f"  See config-template.yml for reference.",
                file=sys.stderr,
            )
            sys.exit(1)
    print(f"✓ deploy config valid (type={deploy_type})")

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
        ["bash", str(init_script), str(project_dir), str(echelon_yml)],
        cwd=str(project_dir),
    )
    if result.returncode != 0:
        sys.exit(result.returncode)

    # Step 4: Confirm
    state_file = project_dir / ".specify" / "squad" / "deploy-state.json"
    hook_file = project_dir / ".git" / "hooks" / "post-merge"
    print(
        f"\n"
        f"╔══════════════════════════════════════════╗\n"
        f"║         echelon init — complete          ║\n"
        f"╚══════════════════════════════════════════╝\n"
        f"\n"
        f"  echelon.yml      → {echelon_yml}\n"
        f"  deploy-state     → {state_file}\n"
        f"  post-merge hook  → {hook_file}\n"
        f"\n"
        f"Next step:\n"
        f"  echelon run <description>\n"
    )


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

    config_file = Path(base_dir) / ".specify" / "extensions" / "echelon" / "echelon.yml"
    mirror_dir = Path(base_dir) / ".specify" / "harness" / "mirror.git"

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
    for arg in args[1:]:
        if "=" in arg:
            k, _, v = arg.partition("=")
            kv[k.strip()] = v.strip()
    strategy = kv.get("strategy", "default")
    mode = kv.get("mode", "semi")

    user_message = " ".join([f"spec {spec_id}", f"{mode} mode", f"strategies={strategy}"])

    from harness.config import load_config
    from harness.docker_provider import DockerWorktreeProvider
    from harness.gitops import GitOpsManager
    from harness.skills.run_skill import run

    config = load_config()
    gitops = GitOpsManager(config)
    provider = DockerWorktreeProvider(buffer_limit_bytes=config.buffer_limit_bytes)

    run(user_message, provider, gitops)


# ── Skill resolution ──────────────────────────────────────────────────────

def _find_skill(skill_base: str, project_dir: Path, cli: str) -> Path | None:
    """Locate the skill file for the given LLM CLI tool.

    Claude   : .claude/skills/speckit-echelon-<cmd>/[Ss]kill.md
    Copilot  : .github/agents/speckit.<skill_base>.agent.md
    Opencode : .opencode/command/speckit.<skill_base>.md
    """
    if cli == "copilot":
        candidates = [
            project_dir / ".github" / "agents" / f"speckit.{skill_base}.agent.md",
        ]
    elif cli == "opencode":
        candidates = [
            project_dir / ".opencode" / "command" / f"speckit.{skill_base}.md",
        ]
    else:
        # claude (default) — dash-separated directory name
        dash_name = "speckit-" + skill_base.replace(".", "-")
        candidates = [
            project_dir / ".claude" / "skills" / dash_name / "skill.md",
            project_dir / ".claude" / "skills" / dash_name / "SKILL.md",
            Path.home() / ".claude" / "skills" / dash_name / "skill.md",
            Path.home() / ".claude" / "skills" / dash_name / "SKILL.md",
        ]

    for p in candidates:
        if p.exists():
            return p
    return None


def _strip_frontmatter(text: str) -> str:
    """Remove YAML frontmatter from a skill file.

    Skill files have frontmatter for the spec-kit skill invocation system
    (disable-model-invocation, user-invocable, etc.). When the content is
    passed directly to an LLM via -p, the frontmatter is meaningless and
    causes the model to treat the file as a document to narrate rather than
    instructions to execute.
    """
    if not text.startswith("---\n"):
        return text
    end = text.find("\n---\n", 4)
    if end == -1:
        return text
    return text[end + 5:].lstrip()


def _build_prompt(skill_path: Path, arguments: str) -> str:
    raw = skill_path.read_text(encoding="utf-8")
    content = _strip_frontmatter(raw)
    if "$ARGUMENTS" in content:
        content = content.replace("$ARGUMENTS", arguments)
    else:
        content = f"{content}\n\n## Arguments\n{arguments}"

    preamble = (
        "You are COMMANDER running non-interactively via `claude -p`. "
        "The text below is your complete operating instruction set for this session. "
        "Execute every step immediately using your tools. "
        "Do not narrate or repeat the instructions back — just execute them.\n\n"
    )
    return preamble + content


def _print_event(event: dict) -> None:
    """Print a human-readable line for each meaningful stream-json event."""
    import json as _json
    etype = event.get("type")

    if etype == "assistant":
        for block in event.get("message", {}).get("content", []):
            btype = block.get("type")
            if btype == "text":
                text = block.get("text", "").strip()
                if text:
                    print(text, flush=True)
            elif btype == "tool_use":
                name = block.get("name", "")
                inp = block.get("input", {})
                hint = (
                    inp.get("description")
                    or inp.get("command", "")[:80]
                    or inp.get("prompt", "")[:80]
                    or inp.get("file_path", "")
                    or inp.get("path", "")
                    or inp.get("subagent_type", "")
                    or ""
                )
                print(f"  ▷ {name}: {hint}" if hint else f"  ▷ {name}", flush=True)

    elif etype == "result":
        cost = event.get("total_cost_usd", 0)
        ms = event.get("duration_ms", 0)
        turns = event.get("num_turns", 0)
        if event.get("is_error"):
            print(f"\n✗ failed after {turns} turns · {ms/1000:.0f}s: {event.get('result', '')}", flush=True)
        else:
            print(f"\n── done  {turns} turns · {ms/1000:.0f}s · ${cost:.4f} ──", flush=True)


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
