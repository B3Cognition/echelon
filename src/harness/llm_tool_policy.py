"""Deterministic host-side LLM tool policy helpers."""

from __future__ import annotations

from dataclasses import dataclass


class ToolPolicyViolation(ValueError):
    """Raised when a host-side LLM command would violate configured policy."""


@dataclass(frozen=True)
class LlmToolPolicy:
    """Effective host-side tool boundary for AI coding CLI subprocesses."""

    file_boundary: str = "workspace"
    network_boundary: str = "harness_allowlist"
    allow_unsafe_host_execution: bool = False
    approval_reason: str | None = None


_PREAMBLE_HEADING = "## Effective Host Tool Policy"


def validate_llm_tool_policy(policy: LlmToolPolicy) -> None:
    """Fail closed for unsafe host execution unless approval metadata exists."""
    if policy.allow_unsafe_host_execution and not (policy.approval_reason or "").strip():
        raise ToolPolicyViolation(
            "llm.tool_policy.approval_reason is required when "
            "allow_unsafe_host_execution is true"
        )


def render_llm_tool_policy_preamble(policy: LlmToolPolicy) -> str:
    """Render the deterministic policy statement injected into host LLM prompts."""
    validate_llm_tool_policy(policy)
    bypass = (
        f"enabled; approval: {policy.approval_reason}"
        if policy.allow_unsafe_host_execution
        else "disabled"
    )
    return "\n".join(
        [
            _PREAMBLE_HEADING,
            "",
            f"- File boundary: {policy.file_boundary}",
            f"- Network boundary: {policy.network_boundary}",
            f"- Unsafe host execution bypass: {bypass}",
            "- Deterministic enforcement: unsafe CLI permission-bypass flags are "
            "only added when explicitly approved in harness config.",
            "- Remaining scope: file/network/tool limits beyond CLI permission "
            "flags depend on the selected AI CLI runtime.",
            "",
        ]
    )


def inject_llm_tool_policy_preamble(prompt: str, policy: LlmToolPolicy) -> str:
    """Prepend the effective policy unless the prompt already contains it."""
    if prompt.startswith(_PREAMBLE_HEADING) or f"\n{_PREAMBLE_HEADING}\n" in prompt:
        return prompt
    return f"{render_llm_tool_policy_preamble(policy)}{prompt}"


def build_llm_cli_command(
    cli: str,
    bin_: str,
    prompt: str,
    policy: LlmToolPolicy,
    *,
    stream_json: bool = False,
    disallow_claude_task_tools: bool = False,
) -> list[str]:
    """Build a host-side AI coding CLI command under the effective policy."""
    validate_llm_tool_policy(policy)
    effective_prompt = inject_llm_tool_policy_preamble(prompt, policy)
    unsafe = policy.allow_unsafe_host_execution

    if cli == "opencode":
        cmd = [bin_, "run"]
        if unsafe:
            cmd.append("--dangerously-skip-permissions")
        cmd.append(effective_prompt)
        return cmd

    if cli == "codex":
        cmd = [bin_, "exec"]
        if unsafe:
            cmd.append("--dangerously-bypass-approvals-and-sandbox")
        cmd.append(effective_prompt)
        return cmd

    if cli == "claude":
        cmd = [bin_, "-p", effective_prompt]
        if unsafe:
            cmd.append("--dangerously-skip-permissions")
        if disallow_claude_task_tools:
            cmd += ["--disallowedTools", "TaskCreate,TaskUpdate"]
        if stream_json:
            cmd += ["--output-format", "stream-json", "--verbose"]
        return cmd

    cmd = [bin_, "-p", effective_prompt]
    if unsafe:
        cmd.append("--dangerously-skip-permissions")
        if cli == "copilot":
            cmd.append("--allow-all-tools")
    return cmd


def build_opencode_skill_command(
    bin_: str,
    skill_base: str,
    arguments: str,
    policy: LlmToolPolicy,
) -> list[str]:
    """Build native opencode command dispatch under the effective policy."""
    validate_llm_tool_policy(policy)
    cmd = [bin_, "run"]
    if policy.allow_unsafe_host_execution:
        cmd.append("--dangerously-skip-permissions")
    cmd += ["--command", f"speckit.{skill_base}", arguments]
    return cmd
