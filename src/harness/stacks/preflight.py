from __future__ import annotations

from dataclasses import asdict, dataclass, field
import subprocess
from typing import Callable

from harness.stacks.resolver import ResolvedStacks


CommandLocator = Callable[[str], str | None]
CommandRunner = Callable[[list[str], int], subprocess.CompletedProcess[str]]

REGISTRY_PROBE_COMMANDS: dict[str, list[str]] = {
    "statsperform-nexus": [
        "npm",
        "view",
        "@statsperform/playbook-cli",
        "version",
        "--registry=https://nexus.statsperform.tools/repository/public-npm/",
    ],
}


@dataclass(frozen=True)
class StackPreflightFinding:
    severity: str
    code: str
    message: str
    stack_id: str | None = None
    tool_id: str | None = None
    command: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class StackPreflightResult:
    findings: list[StackPreflightFinding]
    checked_commands: dict[str, str | None] = field(default_factory=dict)

    @property
    def has_errors(self) -> bool:
        return any(finding.severity == "error" for finding in self.findings)

    @property
    def status(self) -> str:
        if self.has_errors:
            return "fail"
        if any(finding.severity == "warning" for finding in self.findings):
            return "warn"
        return "pass"


def run_stack_preflight(
    resolved: ResolvedStacks,
    *,
    command_locator: CommandLocator | None = None,
    probe_tools: bool = False,
    command_runner: CommandRunner | None = None,
    timeout_seconds: int = 30,
) -> StackPreflightResult:
    """Check host availability for requirements declared by resolved stacks."""
    import shutil

    locator = command_locator or shutil.which
    runner = command_runner or _run_command
    findings: list[StackPreflightFinding] = []
    checked_commands: dict[str, str | None] = {}

    for command in resolved.required_commands:
        location = locator(command)
        checked_commands[command] = location
        if location is None:
            findings.append(
                StackPreflightFinding(
                    severity="error",
                    code="STACK_COMMAND_MISSING",
                    message=f"Required command `{command}` is not available on PATH.",
                    command=[command],
                )
            )

    for tool_id, tool in sorted(resolved.tools.items()):
        location = checked_commands.get(tool.command)
        if tool.command not in checked_commands:
            location = locator(tool.command)
            checked_commands[tool.command] = location
        if location is None and tool.command not in resolved.required_commands:
            findings.append(
                StackPreflightFinding(
                    severity="error",
                    code="STACK_TOOL_COMMAND_MISSING",
                    message=(
                        f"Tool `{tool_id}` command `{tool.command}` is not available on PATH."
                    ),
                    tool_id=tool_id,
                    command=[tool.command],
                )
            )
            continue

        if not probe_tools:
            continue
        for command_id, command_def in sorted(tool.commands.items()):
            if not command_def.gate:
                continue
            command = [tool.command, *tool.args, *command_def.args]
            findings.extend(
                _run_tool_probe(
                    tool_id=tool_id,
                    command_id=command_id,
                    command=command,
                    runner=runner,
                    timeout_seconds=timeout_seconds,
                )
            )

    for registry in resolved.required_registries:
        command = REGISTRY_PROBE_COMMANDS.get(registry)
        if command is not None:
            executable = command[0]
            location = checked_commands.get(executable)
            if executable not in checked_commands:
                location = locator(executable)
                checked_commands[executable] = location
            if location is None:
                findings.append(
                    StackPreflightFinding(
                        severity="warning",
                        code="STACK_REGISTRY_UNVERIFIED",
                        message=(
                            f"Registry `{registry}` could not be probed because "
                            f"`{executable}` is not available on PATH."
                        ),
                        command=command,
                    )
                )
            else:
                findings.extend(
                    _run_registry_probe(
                        registry=registry,
                        command=command,
                        runner=runner,
                        timeout_seconds=timeout_seconds,
                    )
                )
            continue

        findings.append(
            StackPreflightFinding(
                severity="warning",
                code="STACK_REGISTRY_UNVERIFIED",
                message=(
                    f"Registry `{registry}` requires credentials/configuration; "
                    "verify access before using stack tools."
                ),
            )
        )

    return StackPreflightResult(
        findings=findings,
        checked_commands=checked_commands,
    )


def preflight_to_dict(result: StackPreflightResult) -> dict:
    return {
        "status": result.status,
        "checked_commands": result.checked_commands,
        "findings": [asdict(finding) for finding in result.findings],
    }


def render_preflight_markdown(result: StackPreflightResult) -> str:
    lines = ["## Stack Preflight", "", f"Status: {result.status}", ""]
    if not result.findings:
        lines.append("- No stack preflight issues found.")
        return "\n".join(lines).rstrip() + "\n"

    for finding in result.findings:
        command = f" Command: `{' '.join(finding.command)}`." if finding.command else ""
        tool = f" Tool: `{finding.tool_id}`." if finding.tool_id else ""
        lines.append(
            f"- {finding.severity.upper()} {finding.code}: "
            f"{finding.message}{tool}{command}"
        )
    return "\n".join(lines).rstrip() + "\n"


def _run_tool_probe(
    *,
    tool_id: str,
    command_id: str,
    command: list[str],
    runner: CommandRunner,
    timeout_seconds: int,
) -> list[StackPreflightFinding]:
    try:
        completed = runner(command, timeout_seconds)
    except subprocess.TimeoutExpired:
        return [
            StackPreflightFinding(
                severity="error",
                code="STACK_TOOL_PROBE_TIMEOUT",
                message=(
                    f"Tool `{tool_id}` probe `{command_id}` timed out after "
                    f"{timeout_seconds}s."
                ),
                tool_id=tool_id,
                command=command,
            )
        ]
    except OSError as exc:
        return [
            StackPreflightFinding(
                severity="error",
                code="STACK_TOOL_PROBE_ERROR",
                message=f"Tool `{tool_id}` probe `{command_id}` could not run: {exc}.",
                tool_id=tool_id,
                command=command,
            )
        ]

    if completed.returncode == 0:
        return []

    detail = _probe_detail(completed)
    return [
        StackPreflightFinding(
            severity="error",
            code="STACK_TOOL_PROBE_FAILED",
            message=(
                f"Tool `{tool_id}` probe `{command_id}` exited "
                f"{completed.returncode}.{detail}"
            ),
            tool_id=tool_id,
            command=command,
        )
    ]


def _run_registry_probe(
    *,
    registry: str,
    command: list[str],
    runner: CommandRunner,
    timeout_seconds: int,
) -> list[StackPreflightFinding]:
    """Run a read-only package lookup using the registry's configured npm auth."""
    try:
        completed = runner(command, timeout_seconds)
    except subprocess.TimeoutExpired:
        return [
            StackPreflightFinding(
                severity="warning",
                code="STACK_REGISTRY_PROBE_TIMEOUT",
                message=(
                    f"Registry `{registry}` probe timed out after {timeout_seconds}s."
                ),
                command=command,
            )
        ]
    except OSError as exc:
        return [
            StackPreflightFinding(
                severity="warning",
                code="STACK_REGISTRY_PROBE_ERROR",
                message=f"Registry `{registry}` probe could not run: {exc}.",
                command=command,
            )
        ]

    if completed.returncode == 0:
        return []

    detail = _probe_detail(completed)
    return [
        StackPreflightFinding(
            severity="warning",
            code="STACK_REGISTRY_PROBE_FAILED",
            message=(
                f"Registry `{registry}` probe exited {completed.returncode}.{detail}"
            ),
            command=command,
        )
    ]


def _run_command(
    command: list[str],
    timeout_seconds: int,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )


def _probe_detail(completed: subprocess.CompletedProcess[str]) -> str:
    output = (completed.stderr or completed.stdout or "").strip()
    if not output:
        return ""
    return f" {_truncate(output)}"


def _truncate(value: str, limit: int = 240) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3].rstrip() + "..."
