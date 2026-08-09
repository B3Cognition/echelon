"""Shared skill-file loading and streaming output utilities."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from harness.prompt_framing import COMMANDER_PREAMBLE

# Maps echelon subcommand → skill base name (mirrors SKILL_MAP in echelon/cli.py)
ECHELON_SKILL_MAP = {
    "run":     "echelon.run",
    "bugfix":  "echelon.bugfix",
    "build":   "echelon.build",
    "review":  "echelon.review",
    "change":  "echelon.change",
    "codegen": "echelon.codegen",
}

def find_skill(skill_base: str, project_dir: Path, cli: str) -> Optional[Path]:
    """Locate the skill file for the given LLM CLI and skill base name.

    Claude/Codex: .claude/skills/echelon-<cmd>/[Ss]kill.md
    """
    if cli == "copilot":
        candidates = [project_dir / ".github" / "agents" / f"{skill_base}.agent.md"]
    elif cli == "opencode":
        candidates = [project_dir / ".opencode" / "command" / f"{skill_base}.md"]
    else:
        dash_name = skill_base.replace(".", "-")
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


class StreamEventPrinter:
    """Stateful stream-json event printer.

    Tracks the last tool name so tool results can be printed with context.
    Create one instance per streaming session; call it with each parsed event.

    Output levels:
      ▷ ToolName: hint          — tool invocation
      ⎿  <preview>              — tool result (trimmed; Read results skipped)
      ── done N turns · Xs ··   — session summary
    """

    # Tools whose results are too verbose to preview (file/notebook reads).
    _SKIP_RESULT = frozenset({"Read", "NotebookRead", "ListMcpResourcesTool", "ReadMcpResourceTool"})
    # Tools that modify files — show first result line only.
    _FILE_WRITE = frozenset({"Edit", "Write", "NotebookEdit"})

    def __init__(self) -> None:
        self._pending_tool: Optional[str] = None

    def __call__(self, event: dict) -> None:
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
                    self._pending_tool = name
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

        elif etype == "user":
            tool_name = self._pending_tool
            self._pending_tool = None
            for block in event.get("message", {}).get("content", []):
                if block.get("type") == "tool_result":
                    self._print_result(tool_name, block.get("content", ""))

        elif etype == "result":
            cost = event.get("total_cost_usd", 0)
            ms = event.get("duration_ms", 0)
            turns = event.get("num_turns", 0)
            if event.get("is_error"):
                print(f"\n✗ failed after {turns} turns · {ms/1000:.0f}s: {event.get('result', '')}", flush=True)
            else:
                print(f"\n── done  {turns} turns · {ms/1000:.0f}s · ${cost:.4f} ──", flush=True)

    def _print_result(self, tool_name: Optional[str], content) -> None:
        # Extract text from content (list of blocks or plain string)
        if isinstance(content, list):
            text = next(
                (c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"),
                "",
            )
        else:
            text = str(content) if content else ""

        if not text:
            return

        # Skip noisy read-only tool results
        if tool_name in self._SKIP_RESULT:
            return

        lines = [l for l in text.splitlines() if l.strip()]
        if not lines:
            return

        if tool_name in self._FILE_WRITE:
            # Single-line confirmation is enough for file writes
            self._emit(lines[0])
            return

        # For commands (Bash, etc.): show up to 3 lines.
        # Prefer the last lines — they tend to be summaries (test counts, etc.).
        if len(lines) <= 3:
            for i, line in enumerate(lines):
                self._emit(line, continuation=i > 0)
        else:
            print(f"  ⎿  … ({len(lines)} lines)", flush=True)
            for line in lines[-3:]:
                self._emit(line, continuation=True)

    @staticmethod
    def _emit(line: str, continuation: bool = False) -> None:
        prefix = "     " if continuation else "  ⎿  "
        if len(line) > 120:
            line = line[:120] + "…"
        print(f"{prefix}{line}", flush=True)


def print_stream_event(event: dict, _printer: StreamEventPrinter = StreamEventPrinter()) -> None:
    """Module-level convenience wrapper. Use StreamEventPrinter() for per-session state."""
    _printer(event)
