"""Shared skill-file loading and streaming output utilities."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

# Maps echelon subcommand → skill base name (mirrors SKILL_MAP in echelon/cli.py)
ECHELON_SKILL_MAP = {
    "run":     "echelon.run",
    "bugfix":  "echelon.bugfix",
    "build":   "echelon.build",
    "review":  "echelon.review",
    "change":  "echelon.change",
    "codegen": "echelon.codegen",
}

COMMANDER_PREAMBLE = (
    "You are COMMANDER running non-interactively via `claude -p`. "
    "The text below is your complete operating instruction set for this session. "
    "Execute every step immediately using your tools. "
    "Do not narrate or repeat the instructions back — just execute them.\n\n"
)


def find_skill(skill_base: str, project_dir: Path, cli: str) -> Optional[Path]:
    """Locate the skill file for the given LLM CLI and skill base name.

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


def strip_frontmatter(text: str) -> str:
    """Remove YAML frontmatter block from skill file content."""
    if not text.startswith("---\n"):
        return text
    end = text.find("\n---\n", 4)
    if end == -1:
        return text
    return text[end + 5:].lstrip()


def build_skill_prompt(skill_path: Path, arguments: str) -> str:
    """Build a full COMMANDER prompt from a skill file, substituting $ARGUMENTS."""
    raw = skill_path.read_text(encoding="utf-8")
    content = strip_frontmatter(raw)
    if "$ARGUMENTS" in content:
        content = content.replace("$ARGUMENTS", arguments)
    else:
        content = f"{content}\n\n## Arguments\n{arguments}"
    return COMMANDER_PREAMBLE + content


def build_command_to_skill_base(build_command: str) -> Optional[str]:
    """Derive skill base name from a strategy build command.

    "echelon codegen" -> "echelon.codegen"
    "echelon build"   -> "echelon.build"
    Returns None if the command doesn't map to a known skill.
    """
    parts = build_command.strip().split()
    if len(parts) >= 2 and parts[0] == "echelon":
        return ECHELON_SKILL_MAP.get(parts[1])
    return None


def resolve_llm_prompt(
    build_command: str,
    arguments: str,
    project_dir: Path,
    cli: Optional[str] = None,
) -> str:
    """Return the full COMMANDER prompt for the LLM provider path.

    Loads the skill file that corresponds to build_command and substitutes
    arguments. Falls back to a bare prompt if no skill file is found.
    """
    if cli is None:
        cli = os.environ.get("ECHELON_LLM", "claude")

    skill_base = build_command_to_skill_base(build_command)
    if skill_base:
        skill_path = find_skill(skill_base, project_dir, cli)
        if skill_path:
            return build_skill_prompt(skill_path, arguments)

    # Fallback: no skill file found — return bare COMMANDER prompt
    return COMMANDER_PREAMBLE + arguments


def print_stream_event(event: dict) -> None:
    """Print a human-readable line for each meaningful claude stream-json event.

    Shared between echelon CLI and harness LLM provider so both show the same
    live ▷ ToolName: hint format during non-interactive invocations.
    """
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
