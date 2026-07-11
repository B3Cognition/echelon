"""LLM-backed build and feedback execution for the harness loop."""

from __future__ import annotations

import json
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

    def exec_build(
        self,
        worktree_path: str,
        prompt: str,
        *,
        containment_policy_file: str | None = None,
    ) -> BuildResult:
        status_file = Path(worktree_path) / BUILD_STATUS_FILENAME
        start = time.monotonic()
        extra_env = {
            "HARNESS_BUILD_STATUS_FILE": str(status_file),
            "HARNESS_WORKTREE": worktree_path,
            "PROJECT_ROOT": worktree_path,
            "SPEC_KIT_ROOT": worktree_path,
        }
        if containment_policy_file:
            extra_env["ECHELON_CONTAINMENT_POLICY_FILE"] = containment_policy_file
            policy_env, policy_error = _containment_policy_env(containment_policy_file)
            if policy_error:
                return _containment_policy_error_result(
                    policy_file=containment_policy_file,
                    reason=policy_error,
                    duration_ms=int((time.monotonic() - start) * 1000),
                )
            extra_env.update(policy_env)
        exit_code = self._prompt_executor.exec_prompt(
            worktree_path,
            prompt,
            extra_env=extra_env,
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

    def exec_feedback(
        self,
        worktree_path: str,
        prompt: str,
        *,
        containment_policy_file: str | None = None,
    ) -> BuildResult:
        return self.exec_build(
            worktree_path,
            prompt,
            containment_policy_file=containment_policy_file,
        )


def _containment_policy_env(policy_file: str) -> tuple[dict[str, str], str | None]:
    """Return provider-facing root boundary env vars derived from policy JSON."""
    path = Path(policy_file)
    if not path.exists():
        return {}, "missing containment policy"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {}, f"malformed containment policy: {exc}"
    if not isinstance(data, dict):
        return {}, "malformed containment policy: expected JSON object"

    allowed_roots: list[str] = []
    allowed = data.get("allowed_roots")
    if isinstance(allowed, dict):
        for roots in allowed.values():
            allowed_roots.extend(_string_list(roots))

    forbidden_roots = _string_list(data.get("forbidden_source_roots"))
    forbidden_aliases = _string_list(data.get("forbidden_source_root_aliases"))

    return (
        {
            "ECHELON_ALLOWED_ROOTS_JSON": json.dumps(allowed_roots),
            "ECHELON_FORBIDDEN_ROOTS_JSON": json.dumps(forbidden_roots),
            "ECHELON_FORBIDDEN_ROOT_ALIASES_JSON": json.dumps(forbidden_aliases),
        },
        None,
    )


def _containment_policy_error_result(
    *,
    policy_file: str,
    reason: str,
    duration_ms: int,
) -> BuildResult:
    message = f"{reason}: {policy_file}"
    return BuildResult(
        exit_code=125,
        status="error",
        impasse_file=None,
        reason=message,
        stdout="",
        stderr=message,
        duration_ms=duration_ms,
        token_usage=0,
    )


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]
