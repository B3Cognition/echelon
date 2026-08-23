from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from harness.stacks.preflight import (
    render_preflight_markdown,
    run_stack_preflight,
)
from harness.stacks.resolver import resolve_stacks
from harness.stacks.schema import StackDefinition, StackTool, StackToolCommand


def _stack(
    stack_id: str,
    *,
    requires_commands: list[str] | None = None,
    requires_registries: list[str] | None = None,
    tools: dict[str, StackTool] | None = None,
) -> StackDefinition:
    return StackDefinition(
        id=stack_id,
        name=stack_id,
        version="1.0.0",
        kind="capability",
        owner="test",
        description="",
        source_path=Path(f"{stack_id}/stack.yml"),
        applies_to_archetypes=["web_app"],
        provides={"ui.components": stack_id},
        implies=[],
        requires_commands=requires_commands or [],
        requires_registries=requires_registries or [],
        tools=tools or {},
        context_files=["context.md"],
    )


@pytest.mark.unit
def test_missing_required_command_fails_preflight() -> None:
    resolved = resolve_stacks(
        ["playbook"],
        {"playbook": _stack("playbook", requires_commands=["npx"])},
    )

    result = run_stack_preflight(resolved, command_locator=lambda _command: None)

    assert result.status == "fail"
    assert result.has_errors
    assert result.findings[0].code == "STACK_COMMAND_MISSING"
    assert "npx" in result.findings[0].message


@pytest.mark.unit
def test_available_required_command_passes_preflight() -> None:
    resolved = resolve_stacks(
        ["playbook"],
        {"playbook": _stack("playbook", requires_commands=["npx"])},
    )

    result = run_stack_preflight(resolved, command_locator=lambda command: f"/bin/{command}")

    assert result.status == "pass"
    assert not result.has_errors


@pytest.mark.unit
def test_registry_without_a_probe_is_a_warning_not_blocker() -> None:
    resolved = resolve_stacks(
        ["playbook"],
        {
            "playbook": _stack(
                "playbook",
                requires_commands=["npx"],
                requires_registries=["custom-registry"],
            )
        },
    )

    result = run_stack_preflight(resolved, command_locator=lambda command: f"/bin/{command}")

    assert result.status == "warn"
    assert not result.has_errors
    assert [finding.code for finding in result.findings] == ["STACK_REGISTRY_UNVERIFIED"]


@pytest.mark.unit
def test_statsperform_nexus_registry_probe_suppresses_unverified_warning() -> None:
    """A reachable authenticated registry must not be reported as unverified."""
    resolved = resolve_stacks(
        ["playbook"],
        {
            "playbook": _stack(
                "playbook",
                requires_registries=["statsperform-nexus"],
            )
        },
    )
    calls: list[list[str]] = []

    result = run_stack_preflight(
        resolved,
        command_locator=lambda command: f"/bin/{command}",
        command_runner=lambda command, _timeout_seconds: calls.append(command)
        or subprocess.CompletedProcess(command, 0, stdout="1.2.3", stderr=""),
    )

    assert result.status == "pass"
    assert result.findings == []
    assert calls == [
        [
            "npm",
            "view",
            "@statsperform/playbook-cli",
            "version",
            "--registry=https://nexus.statsperform.tools/repository/public-npm/",
        ]
    ]


@pytest.mark.unit
def test_statsperform_nexus_registry_probe_reports_access_failure() -> None:
    """An unavailable registry must not be reported as successfully verified."""
    resolved = resolve_stacks(
        ["playbook"],
        {
            "playbook": _stack(
                "playbook",
                requires_registries=["statsperform-nexus"],
            )
        },
    )

    result = run_stack_preflight(
        resolved,
        command_locator=lambda command: f"/bin/{command}",
        command_runner=lambda command, _timeout_seconds: subprocess.CompletedProcess(
            command, 1, stdout="", stderr="authentication required"
        ),
    )

    assert result.status == "warn"
    assert [finding.code for finding in result.findings] == [
        "STACK_REGISTRY_PROBE_FAILED"
    ]
    assert "authentication required" in result.findings[0].message
    assert result.findings[0].command == [
        "npm",
        "view",
        "@statsperform/playbook-cli",
        "version",
        "--registry=https://nexus.statsperform.tools/repository/public-npm/",
    ]


@pytest.mark.unit
def test_declared_tool_command_is_checked_even_when_requirements_omit_it() -> None:
    resolved = resolve_stacks(
        ["playbook"],
        {
            "playbook": _stack(
                "playbook",
                tools={
                    "playbook_cli": StackTool(
                        id="playbook_cli",
                        type="cli",
                        command="playbook",
                    )
                },
            )
        },
    )

    result = run_stack_preflight(resolved, command_locator=lambda _command: None)

    assert result.status == "fail"
    assert result.findings[0].code == "STACK_TOOL_COMMAND_MISSING"
    assert result.findings[0].tool_id == "playbook_cli"


@pytest.mark.unit
def test_gated_tool_probes_run_only_when_requested() -> None:
    calls: list[list[str]] = []
    resolved = resolve_stacks(
        ["playbook"],
        {
            "playbook": _stack(
                "playbook",
                requires_commands=["npx"],
                tools={
                    "playbook_cli": StackTool(
                        id="playbook_cli",
                        type="cli",
                        command="npx",
                        args=["-y", "@statsperform/playbook-cli"],
                        commands={
                            "compliance_scan": StackToolCommand(
                                args=["compliance", "scan"],
                                gate=True,
                            ),
                            "component_list": StackToolCommand(
                                args=["components", "list"],
                                gate=False,
                            ),
                        },
                    )
                },
            )
        },
    )

    result = run_stack_preflight(
        resolved,
        command_locator=lambda command: f"/bin/{command}",
        probe_tools=True,
        command_runner=lambda command, _timeout_seconds: calls.append(command)
        or subprocess.CompletedProcess(command, 0, stdout="ok", stderr=""),
    )

    assert result.status == "pass"
    assert calls == [["npx", "-y", "@statsperform/playbook-cli", "compliance", "scan"]]


@pytest.mark.unit
def test_failed_gated_tool_probe_fails_preflight() -> None:
    resolved = resolve_stacks(
        ["playbook"],
        {
            "playbook": _stack(
                "playbook",
                requires_commands=["npx"],
                tools={
                    "playbook_cli": StackTool(
                        id="playbook_cli",
                        type="cli",
                        command="npx",
                        commands={
                            "compliance_scan": StackToolCommand(
                                args=["compliance", "scan"],
                                gate=True,
                            ),
                        },
                    )
                },
            )
        },
    )

    result = run_stack_preflight(
        resolved,
        command_locator=lambda command: f"/bin/{command}",
        probe_tools=True,
        command_runner=lambda command, _timeout_seconds: subprocess.CompletedProcess(
            command,
            2,
            stdout="",
            stderr="missing token",
        ),
    )

    assert result.status == "fail"
    assert result.findings[0].code == "STACK_TOOL_PROBE_FAILED"
    assert "missing token" in result.findings[0].message


@pytest.mark.unit
def test_render_preflight_markdown_names_status_and_findings() -> None:
    resolved = resolve_stacks(
        ["playbook"],
        {"playbook": _stack("playbook", requires_commands=["npx"])},
    )
    result = run_stack_preflight(resolved, command_locator=lambda _command: None)

    markdown = render_preflight_markdown(result)

    assert "## Stack Preflight" in markdown
    assert "Status: fail" in markdown
    assert "STACK_COMMAND_MISSING" in markdown
