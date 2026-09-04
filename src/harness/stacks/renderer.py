from __future__ import annotations

from pathlib import Path

from harness.stacks.resolver import ResolvedStacks


def resolved_to_dict(resolved: ResolvedStacks) -> dict:
    return {
        "selected": resolved.selected_ids,
        "resolved": resolved.resolved_ids,
        "implied_by": {key: resolved.implied_by[key] for key in sorted(resolved.implied_by)},
        "capabilities": {
            key: {"value": capability.value, "sources": capability.sources}
            for key, capability in sorted(resolved.capabilities.items())
        },
        "tools": {
            tool_id: {
                "type": tool.type,
                "command": tool.command,
                "args": tool.args,
                "phase_scope": tool.phase_scope,
                "purpose": tool.purpose,
                "commands": {
                    command_id: {
                        "args": command.args,
                        "output": command.output,
                        "gate": command.gate,
                    }
                    for command_id, command in sorted(tool.commands.items())
                },
            }
            for tool_id, tool in sorted(resolved.tools.items())
        },
        "requirements": {
            "commands": resolved.required_commands,
            "registries": resolved.required_registries,
        },
        "runnability": {
            "classification": resolved.runnability.classification,
            "policy": resolved.runnability.policy,
            "runner": resolved.runnability.runner,
            "capabilities": list(resolved.runnability.capabilities),
            "required_observations": list(
                resolved.runnability.required_observations
            ),
            "sources": list(resolved.runnability.sources),
        },
        "context_files": resolved.context_files,
    }


def render_resolved_markdown(resolved: ResolvedStacks) -> str:
    lines = ["# Resolved Echelon Stacks", ""]

    if not resolved.resolved_ids:
        lines.extend(
            [
                "No Echelon stacks selected. Use normal Echelon inference.",
                "",
            ]
        )
        return "\n".join(lines)

    lines.extend(["## Selected Stacks", ""])
    for stack_id in resolved.resolved_ids:
        suffix = ""
        if stack_id in resolved.implied_by:
            suffix = f" (implied by {resolved.implied_by[stack_id]})"
        lines.append(f"- {stack_id}{suffix}")

    lines.extend(
        [
            "",
            "## Capabilities",
            "",
            "| Capability | Value | Source |",
            "|---|---|---|",
        ]
    )
    for key, capability in sorted(resolved.capabilities.items()):
        lines.append(f"| {key} | {capability.value} | {', '.join(capability.sources)} |")

    if resolved.runnability.sources:
        lines.extend(
            [
                "",
                "## User Runnability",
                "",
                f"- Classification: `{resolved.runnability.classification}`",
                f"- Policy: `{resolved.runnability.policy}`",
                f"- Runner: `{resolved.runnability.runner or 'none'}`",
                "- Capabilities: "
                + (", ".join(resolved.runnability.capabilities) or "none"),
                "- Required observations: "
                + (
                    ", ".join(resolved.runnability.required_observations)
                    or "none"
                ),
                f"- Sources: {', '.join(resolved.runnability.sources)}",
            ]
        )

    if resolved.tools:
        lines.extend(["", "## Available Stack Tools", ""])
        for tool_id, tool in sorted(resolved.tools.items()):
            command = " ".join([tool.command, *tool.args]).strip()
            lines.extend(
                [
                    f"### {tool_id}",
                    "",
                    f"- Command: `{command}`",
                    f"- Phase scope: {', '.join(tool.phase_scope) if tool.phase_scope else 'unspecified'}",
                ]
            )
            if tool.purpose:
                lines.append(f"- Purpose: {tool.purpose}")
            if tool.commands:
                lines.append("- Commands:")
                for command_id, command_def in sorted(tool.commands.items()):
                    command_args = " ".join([tool.command, *tool.args, *command_def.args]).strip()
                    lines.append(
                        f"  - {command_id}: `{command_args}`"
                        f" ({command_def.output}{', gate' if command_def.gate else ''})"
                    )
            lines.append("")

    if resolved.required_commands or resolved.required_registries:
        lines.extend(["## Requirements", ""])
        for command in resolved.required_commands:
            lines.append(f"- Command: `{command}`")
        for registry in resolved.required_registries:
            lines.append(f"- Registry: `{registry}`")
        lines.append("")

    if resolved.context_files:
        lines.extend(["## Context Files", ""])
        for context_file in resolved.context_files:
            lines.append(f"- `{context_file}`")
        lines.append("")

        guidance = _render_context_file_contents(resolved.context_files)
        if guidance:
            lines.extend(["## Stack Guidance", "", *guidance])

    return "\n".join(lines).rstrip() + "\n"


def _render_context_file_contents(context_files: list[str]) -> list[str]:
    lines: list[str] = []
    for context_file in context_files:
        path = Path(context_file)
        if not path.exists() or not path.is_file():
            continue
        content = path.read_text(encoding="utf-8").strip()
        if not content:
            continue
        if lines:
            lines.append("")
        lines.extend([f"### {path.name}", "", content])
    return lines
