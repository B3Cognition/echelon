"""LLM-backed build and feedback execution for the harness loop."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Mapping, Protocol

from harness.build_result import (
    BUILD_STATUS_FILENAME,
    ECHELON_RESULT_FILENAME,
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
        prompt_metadata: Mapping[str, object] | None = None,
    ) -> BuildResult:
        status_file = Path(worktree_path) / BUILD_STATUS_FILENAME
        start = time.monotonic()
        extra_env = {
            "HARNESS_BUILD_STATUS_FILE": str(status_file),
            "HARNESS_WORKTREE": worktree_path,
            "PROJECT_ROOT": worktree_path,
        }
        if containment_policy_file:
            extra_env["ECHELON_CONTAINMENT_POLICY_FILE"] = containment_policy_file
            policy_env, policy_error = _containment_policy_env(
                containment_policy_file,
                worktree_path=worktree_path,
            )
            if policy_error:
                return _containment_policy_error_result(
                    policy_file=containment_policy_file,
                    reason=policy_error,
                    duration_ms=int((time.monotonic() - start) * 1000),
                )
            extra_env.update(policy_env)
        run_prompt_result = getattr(self._prompt_executor, "run_prompt_result", None)
        if prompt_metadata and callable(run_prompt_result):
            provider_result = run_prompt_result(
                worktree_path,
                prompt,
                extra_env=extra_env,
                request_metadata={"prompt_metadata": dict(prompt_metadata)},
            )
            exit_code = int(provider_result.exit_code)
        else:
            exit_code = self._prompt_executor.exec_prompt(
                worktree_path,
                prompt,
                extra_env=extra_env,
            )
        duration_ms = int((time.monotonic() - start) * 1000)
        stdout = str(getattr(self._prompt_executor, "last_stdout", "") or "")
        stderr = str(getattr(self._prompt_executor, "last_stderr", "") or "")
        token_usage = _reported_token_usage(
            getattr(self._prompt_executor, "last_token_usage", None)
        )

        if exit_code == -1:
            result = BuildResult(
                exit_code=-1,
                status="timeout",
                impasse_file=None,
                reason=None,
                stdout=stdout,
                stderr=stderr,
                duration_ms=duration_ms,
                token_usage=token_usage,
            )
            result.provider_invocation = _provider_invocation(
                self._prompt_executor,
                duration_ms=duration_ms,
                status=result.status,
                exit_code=exit_code,
                token_usage=token_usage,
            )
            return result

        result = BuildResult.from_status_file(
            status_file,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_ms=duration_ms,
        )
        if result.status == "unknown" and not status_file.exists():
            legacy_result_file = Path(worktree_path) / ECHELON_RESULT_FILENAME
            if legacy_result_file.exists():
                result = BuildResult.from_echelon_result_file(
                    legacy_result_file,
                    exit_code=exit_code,
                    stdout=stdout,
                    stderr=stderr,
                    duration_ms=duration_ms,
                )
            if result.status == "unknown":
                recovered = recover_done_result_from_output(
                    stdout=stdout,
                    stderr=stderr,
                    exit_code=exit_code,
                    duration_ms=duration_ms,
                )
                if recovered is not None:
                    result = recovered
        result.token_usage = token_usage
        result.provider_invocation = _provider_invocation(
            self._prompt_executor,
            duration_ms=duration_ms,
            status=result.status,
            exit_code=exit_code,
            token_usage=token_usage,
        )
        return result

    def exec_feedback(
        self,
        worktree_path: str,
        prompt: str,
        *,
        containment_policy_file: str | None = None,
        prompt_metadata: Mapping[str, object] | None = None,
    ) -> BuildResult:
        return self.exec_build(
            worktree_path,
            prompt,
            containment_policy_file=containment_policy_file,
            prompt_metadata=prompt_metadata,
        )


def _containment_policy_env(
    policy_file: str,
    *,
    worktree_path: str,
) -> tuple[dict[str, str], str | None]:
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
    if not allowed_roots and not forbidden_roots:
        return {}, "empty containment policy"
    boundary_error = _worktree_boundary_error(
        worktree_path,
        allowed_roots=allowed_roots,
        forbidden_roots=forbidden_roots,
    )
    if boundary_error:
        return {}, boundary_error

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
        token_usage=None,
    )


def _reported_token_usage(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value > 0 else None


def _provider_invocation(
    prompt_executor: PromptExecutor,
    *,
    duration_ms: int,
    status: str,
    exit_code: int,
    token_usage: int | None,
) -> dict[str, object] | None:
    raw = getattr(prompt_executor, "last_invocation_metadata", None)
    if type(raw) is not dict or not isinstance(raw.get("provider"), str):
        return None
    provider = str(raw["provider"]).strip()
    if not provider:
        return None
    return {
        "provider": provider,
        "model": _optional_invocation_text(raw.get("model")),
        "profile": _optional_invocation_text(raw.get("profile")),
        "effort": _optional_invocation_text(raw.get("effort")),
        "duration_ms": max(0, duration_ms),
        "status": status,
        "exit_code": exit_code,
        "token_usage": token_usage,
    }


def _optional_invocation_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _worktree_boundary_error(
    worktree_path: str,
    *,
    allowed_roots: list[str],
    forbidden_roots: list[str],
) -> str | None:
    worktree = _resolved_path(worktree_path)
    for forbidden in (_resolved_path(path) for path in forbidden_roots):
        if _path_is_relative_to(worktree, forbidden):
            return f"worktree under containment policy forbidden root {forbidden}"
    if allowed_roots and not any(
        _path_is_relative_to(worktree, _resolved_path(root)) for root in allowed_roots
    ):
        return "worktree outside containment policy allowed roots"
    return None


def _resolved_path(path: object) -> Path:
    return Path(str(path)).expanduser().resolve(strict=False)


def _path_is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
