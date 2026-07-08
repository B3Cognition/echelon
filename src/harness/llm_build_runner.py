"""LLM-backed build and feedback execution for the harness loop."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Mapping, Protocol

from harness.build_result import (
    BUILD_STATUS_FILENAME,
    BuildResult,
    recover_done_result_from_output,
)


class PromptExecutor(Protocol):
    def exec_prompt(
        self,
        worktree_path: str,
        prompt: str,
        *,
        extra_env: Mapping[str, str] | None = None,
    ) -> int:
        ...


class LlmBuildRunner:
    """Runs build/fix prompts and interprets the harness build-status file."""

    def __init__(self, prompt_executor: PromptExecutor) -> None:
        self._prompt_executor = prompt_executor

    def exec_build(self, worktree_path: str, prompt: str) -> BuildResult:
        status_file = Path(worktree_path) / BUILD_STATUS_FILENAME
        start = time.monotonic()
        exit_code = self._prompt_executor.exec_prompt(
            worktree_path,
            prompt,
            extra_env={
                "HARNESS_BUILD_STATUS_FILE": str(status_file),
                "HARNESS_WORKTREE": worktree_path,
                "PROJECT_ROOT": worktree_path,
                "SPEC_KIT_ROOT": worktree_path,
                "HARNESS_SOURCE_DIR": str(Path(__file__).resolve().parent),
            },
        )
        duration_ms = int((time.monotonic() - start) * 1000)
        stdout = str(getattr(self._prompt_executor, "last_stdout", "") or "")
        stderr = str(getattr(self._prompt_executor, "last_stderr", "") or "")
        token_usage = int(getattr(self._prompt_executor, "last_token_usage", 0) or 0)

        if exit_code == -1:
            return BuildResult(
                exit_code=-1,
                status="timeout",
                impasse_file=None,
                reason=None,
                stdout=stdout,
                stderr=stderr,
                duration_ms=duration_ms,
                token_usage=token_usage,
            )

        result = BuildResult.from_status_file(
            status_file,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_ms=duration_ms,
        )
        if result.status == "unknown" and not status_file.exists():
            recovered = recover_done_result_from_output(
                stdout=stdout,
                stderr=stderr,
                exit_code=exit_code,
                duration_ms=duration_ms,
            )
            if recovered is not None:
                result = recovered
        result.token_usage = token_usage
        return result

    def exec_feedback(self, worktree_path: str, prompt: str) -> BuildResult:
        return self.exec_build(worktree_path, prompt)
