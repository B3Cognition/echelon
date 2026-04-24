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
  init                                One-time project setup (no LLM)
  run     <description>               Run echelon for a new feature
  bugfix  <spec_id> <description>     Diagnose and plan a bugfix
  build   <spec_id>                   Build implementation for a spec
  review  <spec_id> [pr_url=<url>]    Triage PR review comments
  change  <spec_id> <description>     Plan a scope change
  codegen <spec_id>                   Run SOAR codegen pipeline

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


def _build_prompt(skill_path: Path, arguments: str) -> str:
    template = skill_path.read_text(encoding="utf-8")
    if "$ARGUMENTS" in template:
        return template.replace("$ARGUMENTS", arguments)
    return f"{template}\n\n## Arguments\n{arguments}"


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
    else:
        prompt = _build_prompt(skill_path, arguments)
        cmd = [bin_, "-p", prompt, "--dangerously-skip-permissions"]
        if cli == "copilot":
            cmd += ["--allow-all-tools"]

    result = subprocess.run(cmd, cwd=str(project_dir))
    sys.exit(result.returncode)
