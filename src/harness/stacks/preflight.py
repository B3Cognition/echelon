from __future__ import annotations

from dataclasses import asdict, dataclass, field
import os
from pathlib import Path
import subprocess
from typing import Callable, Iterable, Mapping

from harness.canonical_requirements import extract_canonical_requirements
from harness.coverage_evidence import parse_coverage_map_obligations
from harness.deferred_scope import active_entries
from harness.stacks.provisioning import provisioning_statuses
from harness.stacks.resolver import ResolvedCoverageObserver, ResolvedStacks


CommandLocator = Callable[[str], str | None]
CommandRunner = Callable[[list[str], int], subprocess.CompletedProcess[str]]


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
    coverage_test_types: Iterable[str] = (),
    command_locator: CommandLocator | None = None,
    probe_tools: bool = False,
    command_runner: CommandRunner | None = None,
    timeout_seconds: int = 30,
    target_root: Path | None = None,
    environment: Mapping[str, str] | None = None,
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

    findings.extend(
        coverage_observer_preflight_findings(
            resolved,
            coverage_test_types=coverage_test_types,
        )
    )

    if target_root is not None:
        findings.extend(
            _provisioning_findings(
                resolved,
                target_root=target_root,
                environment=environment if environment is not None else os.environ,
            )
        )

    return StackPreflightResult(
        findings=findings,
        checked_commands=checked_commands,
    )


def coverage_observer_preflight_findings(
    resolved: ResolvedStacks,
    *,
    coverage_test_types: Iterable[str],
) -> list[StackPreflightFinding]:
    """Return fail-closed capability findings for planned coverage types.

    Coverage maps are planning artifacts, so the caller supplies their already
    parsed type values.  This deliberately verifies only *required* observers:
    an optional stack tool is not evidence that delivery can meet a mandatory
    coverage obligation.
    """
    test_types = tuple(
        sorted(
            {
                str(value).strip()
                for value in coverage_test_types
                if str(value).strip()
            }
        )
    )
    if not test_types:
        return []

    stack_names = ", ".join(resolved.resolved_ids) or "selected stack"
    if resolved.runnability.runner == "macos_simulator":
        return [
            StackPreflightFinding(
                severity="error",
                code="coverage_observer_unavailable",
                message=(
                    "Coverage observation for selected stack(s) "
                    f"`{stack_names}` requires a macOS simulator runner "
                    "(macos_simulator_required); the current Linux sandbox "
                    "cannot execute it."
                ),
            )
        ]

    supported: dict[str, ResolvedCoverageObserver] = {}
    for item in resolved.coverage_observers:
        if not item.observer.required:
            continue
        for test_type in item.observer.test_types:
            supported.setdefault(test_type, item)

    return [
        StackPreflightFinding(
            severity="error",
            code="coverage_observer_unavailable",
            message=(
                f"Coverage test type `{test_type}` has no required structured "
                f"observer in selected stack(s) `{stack_names}`."
            ),
        )
        for test_type in test_types
        if test_type not in supported
    ]


def required_coverage_observers_for_types(
    resolved: ResolvedStacks,
    *,
    coverage_test_types: Iterable[str],
) -> tuple[ResolvedCoverageObserver, ...]:
    """Select only required observers that own a planned test type."""
    requested = {
        str(value).strip()
        for value in coverage_test_types
        if str(value).strip()
    }
    return tuple(
        item
        for item in resolved.coverage_observers
        if item.observer.required and requested.intersection(item.observer.test_types)
    )


def coverage_test_types_from_spec(spec_dir: Path | None) -> tuple[str, ...]:
    """Read planned test types using the canonical coverage-map parser.

    An incomplete Phase A directory has no capability requirement yet.  The
    caller can therefore keep rendering general stack context while this helper
    turns a completed map into a deterministic preflight input.
    """
    if spec_dir is None:
        return ()
    coverage_map = Path(spec_dir) / "coverage-map.md"
    if not coverage_map.is_file():
        return ()
    try:
        canonical_ids = {
            item.id for item in extract_canonical_requirements(Path(spec_dir))
        }
        obligations = parse_coverage_map_obligations(coverage_map, canonical_ids)
        owner_deferred_ids = {
            item_id
            for entry in active_entries(Path(spec_dir))
            for item_id in entry.selected_ids
            if not item_id.startswith("T-")
        }
    except (OSError, ValueError):
        return ()
    return tuple(
        sorted(
            {
                item.test_type
                for row in obligations
                for item in row
                if item.requirement_id not in owner_deferred_ids
            }
        )
    )


def _provisioning_findings(
    resolved: ResolvedStacks,
    *,
    target_root: Path,
    environment: Mapping[str, str],
) -> list[StackPreflightFinding]:
    findings: list[StackPreflightFinding] = []
    for status in provisioning_statuses(resolved, target_root, environment):
        if status.state == "ready":
            continue
        if status.state == "missing":
            findings.append(
                StackPreflightFinding(
                    severity="error",
                    code="STACK_PROVISIONING_MISSING",
                    message=(
                        f"Verification provisioner `{status.provisioner_id}` for stack "
                        f"`{status.owner_stack_id}` is missing. Configure its required "
                        "environment or render its verification artifacts with "
                        "`echelon stack provision`."
                    ),
                    stack_id=status.owner_stack_id,
                )
            )
            continue
        if status.state == "prepared":
            path = f" at `{status.path}`" if status.path is not None else ""
            findings.append(
                StackPreflightFinding(
                    severity="warning",
                    code="STACK_PROVISIONING_PREPARED",
                    message=(
                        f"Verification provisioner `{status.provisioner_id}` for stack "
                        f"`{status.owner_stack_id}` is prepared{path}, but Echelon did "
                        "not start Docker. Start the Compose service manually or configure "
                        "the required environment."
                    ),
                    stack_id=status.owner_stack_id,
                )
            )
    return findings


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
