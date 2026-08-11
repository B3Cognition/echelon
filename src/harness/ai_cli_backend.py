"""Shared interfaces for host-side AI coding CLI backends."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Protocol

from harness.config import HarnessConfig


@dataclass(frozen=True)
class CliRunRequest:
    cwd: str
    prompt: str
    env: Mapping[str, str]
    timeout_s: float
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass
class CliRunResult:
    exit_code: int
    stdout: str
    stderr: str
    token_usage: int | None = None
    cost_usd: float = 0.0
    timed_out: bool = False
    metadata: dict[str, object] = field(default_factory=dict)


class AICodingCliBackend(Protocol):
    name: str

    def run_prompt(self, request: CliRunRequest) -> CliRunResult:
        ...

    def run_agent(self, request: CliRunRequest) -> CliRunResult:
        ...


def create_ai_cli_backend(config: HarnessConfig) -> AICodingCliBackend:
    from harness.ai_cli_backends.claude import ClaudeCliBackend
    from harness.ai_cli_backends.codex import CodexCliBackend
    from harness.ai_cli_backends.copilot import CopilotCliBackend
    from harness.ai_cli_backends.openai_compatible import OpenAICompatibleBackend
    from harness.ai_cli_backends.opencode import OpenCodeCliBackend
    from harness.ai_cli_backends.plain import PlainCliBackend

    cli = config.llm.cli
    if cli == "openai-compatible":
        return OpenAICompatibleBackend(config)
    if cli == "claude":
        return ClaudeCliBackend(config)
    if cli == "codex":
        return CodexCliBackend(config)
    if cli == "copilot":
        return CopilotCliBackend(config)
    if cli == "opencode":
        return OpenCodeCliBackend(config)
    return PlainCliBackend(config)
