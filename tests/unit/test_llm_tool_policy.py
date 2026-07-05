"""Tests for deterministic host-side LLM tool policy."""

from __future__ import annotations

import pytest

from harness.llm_tool_policy import (
    LlmToolPolicy,
    ToolPolicyViolation,
    build_llm_cli_command,
    build_opencode_skill_command,
    inject_llm_tool_policy_preamble,
    render_llm_tool_policy_preamble,
)


def test_default_policy_denies_unsafe_host_execution() -> None:
    policy = LlmToolPolicy()

    assert policy.file_boundary == "workspace"
    assert policy.network_boundary == "harness_allowlist"
    assert policy.allow_unsafe_host_execution is False
    assert policy.approval_reason is None


def test_policy_preamble_states_effective_boundaries() -> None:
    preamble = render_llm_tool_policy_preamble(LlmToolPolicy())

    assert "Effective Host Tool Policy" in preamble
    assert "File boundary: workspace" in preamble
    assert "Network boundary: harness_allowlist" in preamble
    assert "Unsafe host execution bypass: disabled" in preamble


def test_policy_preamble_injection_is_idempotent() -> None:
    prompt = "Do the work."

    injected = inject_llm_tool_policy_preamble(prompt, LlmToolPolicy())

    assert injected.startswith("## Effective Host Tool Policy")
    assert inject_llm_tool_policy_preamble(injected, LlmToolPolicy()) == injected


def test_dangerous_codex_bypass_requires_explicit_approval_reason() -> None:
    policy = LlmToolPolicy(allow_unsafe_host_execution=True)

    with pytest.raises(ToolPolicyViolation, match="approval_reason"):
        build_llm_cli_command("codex", "codex", "Do the work.", policy)


def test_unapproved_codex_command_uses_default_exec_boundary() -> None:
    cmd = build_llm_cli_command("codex", "codex", "Do the work.", LlmToolPolicy())

    assert cmd == [
        "codex",
        "exec",
        inject_llm_tool_policy_preamble("Do the work.", LlmToolPolicy()),
    ]


def test_approved_codex_command_uses_dangerous_bypass_flag() -> None:
    policy = LlmToolPolicy(
        allow_unsafe_host_execution=True,
        approval_reason="Operator approved local disposable worktree on 2026-06-23.",
    )

    cmd = build_llm_cli_command("codex", "codex", "Do the work.", policy)

    assert cmd[:3] == ["codex", "exec", "--dangerously-bypass-approvals-and-sandbox"]
    assert "Effective Host Tool Policy" in cmd[-1]


def test_codex_command_can_request_json_and_output_last_message() -> None:
    cmd = build_llm_cli_command(
        "codex",
        "codex",
        "Do the work.",
        LlmToolPolicy(),
        codex_json=True,
        output_last_message="/tmp/codex-last.txt",
    )

    assert cmd[:2] == ["codex", "exec"]
    assert "--json" in cmd
    assert "--output-last-message" in cmd
    assert cmd[cmd.index("--output-last-message") + 1] == "/tmp/codex-last.txt"
    assert cmd[-1].startswith("## Effective Host Tool Policy")


def test_opencode_skill_command_preserves_native_command_dispatch() -> None:
    cmd = build_opencode_skill_command(
        "opencode",
        "echelon.build",
        "005",
        LlmToolPolicy(),
    )

    assert cmd == [
        "opencode",
        "run",
        "--command",
        "speckit.echelon.build",
        "005",
    ]
    assert "--dangerously-skip-permissions" not in cmd


def test_opencode_skill_command_uses_dangerous_bypass_when_approved() -> None:
    policy = LlmToolPolicy(
        allow_unsafe_host_execution=True,
        approval_reason="Operator approved local disposable worktree.",
    )

    cmd = build_opencode_skill_command("opencode", "echelon.build", "005", policy)

    assert cmd[:3] == ["opencode", "run", "--dangerously-skip-permissions"]
