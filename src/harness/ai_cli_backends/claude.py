from __future__ import annotations

from harness.ai_cli_backend import CliRunRequest, CliRunResult
from harness.config import HarnessConfig


class ClaudeCliBackend:
    name = "claude"

    def __init__(self, config: HarnessConfig) -> None:
        self._config = config

    def run_prompt(self, request: CliRunRequest) -> CliRunResult:
        raise NotImplementedError

    def run_agent(self, request: CliRunRequest) -> CliRunResult:
        return self.run_prompt(request)
