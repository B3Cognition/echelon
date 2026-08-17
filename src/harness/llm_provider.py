"""AICodingCliProvider facade for host-side AI coding CLI backends."""
from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import replace
from pathlib import Path
from typing import Mapping

from harness.ai_cli_backend import CliRunRequest, CliRunResult, create_ai_cli_backend
from harness.ai_cli_backends.claude import (
    host_workspace_synthesis_boundary_available,
)
from harness.config import HarnessConfig
from harness.llm_tool_policy import build_llm_cli_command
from harness.provider_capability import (
    ARTIFACT_PROVIDER_CAPABILITIES,
    CLI_PROVIDER_CAPABILITIES,
    ProviderCapability,
)
from harness.provider_workspace_scope import apply_product_plane_boundary


SUPPORTED_EXECUTION_PROFILES = {"claude": frozenset({"review_triage_v1"})}


class AICodingCliProvider:
    """Runs prompts through the configured AI coding CLI backend.

    Supports claude (default), copilot, opencode, and codex. Configured via
    config.llm.cli or the ECHELON_LLM env var (env var takes precedence).

    Not a SandboxProvider: it owns CLI backend selection, environment setup,
    timeout handling, and provider result bookkeeping.
    """

    def __init__(self, config: HarnessConfig) -> None:
        self._cli = os.environ.get("ECHELON_LLM", config.llm.cli)
        effective_config = config
        if self._cli != config.llm.cli:
            effective_config = replace(config, llm=replace(config.llm, cli=self._cli))

        self._config = effective_config
        self._timeout_s = effective_config.llm.timeout_ms / 1000.0
        self._config_dir = effective_config.llm.config_dir
        self._bin = shutil.which(self._cli) or self._cli
        self._backend = create_ai_cli_backend(effective_config)
        if _debug_llm_enabled():
            print(
                "[llm] "
                f"provider={self._cli} "
                f"backend={self._backend.__class__.__name__} "
                f"bin={self._bin} "
                f"config_provider={config.llm.cli}",
                file=sys.stderr,
                flush=True,
            )
        self.last_stdout = ""
        self.last_stderr = ""
        self.last_token_usage = 0
        self.last_invocation_metadata: dict[str, object] = {
            "provider": self._cli,
            "model": None,
            "profile": None,
            "effort": None,
        }

    @property
    def cli(self) -> str:
        return self._cli

    @property
    def capabilities(self) -> frozenset[ProviderCapability]:
        if self._cli == "openai-compatible":
            return ARTIFACT_PROVIDER_CAPABILITIES
        return CLI_PROVIDER_CAPABILITIES

    @property
    def enforces_workspace_synthesis_boundary(self) -> bool:
        """Return whether workspace synthesis cannot access live source roots."""
        if self._cli == "openai-compatible":
            return True
        return bool(
            self._cli in {"claude", "codex"}
            and host_workspace_synthesis_boundary_available()
        )

    def _build_cmd(self, prompt: str) -> list[str]:
        """Compatibility helper for tests and call sites that inspect command shape."""
        return build_llm_cli_command(
            self._cli,
            self._bin,
            prompt,
            self._config.llm.tool_policy,
            stream_json=self._cli == "claude",
            disallow_claude_task_tools=self._cli == "claude",
        )

    def exec_prompt(
        self,
        worktree_path: str,
        prompt: str,
        *,
        extra_env: Mapping[str, str] | None = None,
    ) -> int:
        """Run a prompt with the configured AI coding CLI and return its exit code."""
        result = self.run_prompt_result(
            worktree_path,
            prompt,
            extra_env=extra_env,
        )
        return int(result.exit_code)

    def run_prompt_result(
        self,
        worktree_path: str,
        prompt: str,
        *,
        extra_env: Mapping[str, str] | None = None,
        timeout_ms: int | None = None,
        request_metadata: Mapping[str, object] | None = None,
    ) -> CliRunResult:
        self.last_stdout = ""
        self.last_stderr = ""
        self.last_token_usage = 0
        timeout_s = (timeout_ms / 1000.0) if timeout_ms else self._timeout_s
        metadata = _request_metadata(extra_env, request_metadata)
        prompt, metadata = apply_product_plane_boundary(
            worktree_path,
            prompt,
            metadata,
        )
        profile_violation = _execution_profile_violation(self._cli, metadata)
        if profile_violation is not None:
            self._record_result(profile_violation, metadata)
            return profile_violation
        containment_violation = _containment_cwd_violation(worktree_path, metadata)
        if containment_violation is not None:
            self._record_result(containment_violation, metadata)
            return containment_violation
        result = self._backend.run_prompt(
            CliRunRequest(
                cwd=worktree_path,
                prompt=prompt,
                env=self._build_env(extra_env),
                timeout_s=timeout_s,
                metadata=metadata,
            )
        )
        self._record_result(result, metadata)
        return result

    def run_agent_result(
        self,
        project_root: str,
        prompt: str,
        *,
        timeout_ms: int | None = None,
        extra_env: Mapping[str, str] | None = None,
        request_metadata: Mapping[str, object] | None = None,
    ) -> CliRunResult:
        self.last_stdout = ""
        self.last_stderr = ""
        self.last_token_usage = 0
        timeout_s = (timeout_ms / 1000.0) if timeout_ms else self._timeout_s
        metadata = _request_metadata(extra_env, request_metadata)
        prompt, metadata = apply_product_plane_boundary(
            project_root,
            prompt,
            metadata,
        )
        profile_violation = _execution_profile_violation(self._cli, metadata)
        if profile_violation is not None:
            self._record_result(profile_violation, metadata)
            return profile_violation
        containment_violation = _containment_cwd_violation(project_root, metadata)
        if containment_violation is not None:
            self._record_result(containment_violation, metadata)
            return containment_violation
        result = self._backend.run_agent(
            CliRunRequest(
                cwd=project_root,
                prompt=prompt,
                env=self._build_env(extra_env),
                timeout_s=timeout_s,
                metadata=metadata,
            )
        )
        self._record_result(result, metadata)
        return result

    def _record_result(
        self,
        result: CliRunResult,
        request_metadata: Mapping[str, object],
    ) -> None:
        self.last_stdout = result.stdout
        self.last_stderr = result.stderr
        self.last_token_usage = result.token_usage
        self.last_invocation_metadata = _normalized_invocation_metadata(
            provider=self._cli,
            config=self._config,
            request_metadata=request_metadata,
            result_metadata=result.metadata,
        )

    def _build_env(self, extra_env: Mapping[str, str] | None = None) -> dict[str, str]:
        env = {**os.environ}
        if extra_env:
            env.update(extra_env)
        if self._config_dir and self._cli == "claude":
            env["CLAUDE_CONFIG_DIR"] = os.path.expanduser(self._config_dir)
        return env


def _debug_llm_enabled() -> bool:
    value = os.environ.get("ECHELON_DEBUG_LLM", "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _normalized_invocation_metadata(
    *,
    provider: str,
    config: HarnessConfig,
    request_metadata: Mapping[str, object],
    result_metadata: Mapping[str, object],
) -> dict[str, object]:
    raw_prompt_metadata = request_metadata.get("prompt_metadata")
    prompt_metadata = (
        raw_prompt_metadata if isinstance(raw_prompt_metadata, Mapping) else {}
    )
    model = (
        _metadata_text(result_metadata, "response_model")
        or _metadata_text(result_metadata, "request_model")
        or _metadata_text(prompt_metadata, "model")
        or _optional_text(config.llm.model)
    )
    profile = _metadata_text(prompt_metadata, "model_tier")
    effort = (
        _metadata_text(prompt_metadata, "reasoning_effort")
        or _metadata_text(prompt_metadata, "effort")
        or _metadata_text(config.llm.features, "reasoning_effort")
        or _metadata_text(config.llm.features, "effort")
    )
    normalized: dict[str, object] = {
        "provider": provider,
        "model": model,
        "profile": profile,
        "effort": effort,
    }
    isolated_user_config = result_metadata.get("isolated_user_config")
    if isinstance(isolated_user_config, bool):
        normalized["isolated_user_config"] = isolated_user_config
    return normalized


def _metadata_text(metadata: Mapping[str, object], key: str) -> str | None:
    return _optional_text(metadata.get(key))


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _request_metadata(
    extra_env: Mapping[str, str] | None,
    request_metadata: Mapping[str, object] | None = None,
) -> dict[str, object]:
    metadata = dict(request_metadata or {})
    containment = _containment_metadata(extra_env)
    if containment:
        metadata["containment"] = containment
    return metadata


def _containment_metadata(extra_env: Mapping[str, str] | None) -> dict[str, object]:
    if not extra_env:
        return {}
    errors: list[str] = []
    containment = {
        "allowed_roots": _json_string_list(
            extra_env.get("ECHELON_ALLOWED_ROOTS_JSON"),
            key="ECHELON_ALLOWED_ROOTS_JSON",
            errors=errors,
        ),
        "forbidden_roots": _json_string_list(
            extra_env.get("ECHELON_FORBIDDEN_ROOTS_JSON"),
            key="ECHELON_FORBIDDEN_ROOTS_JSON",
            errors=errors,
        ),
        "forbidden_root_aliases": _json_string_list(
            extra_env.get("ECHELON_FORBIDDEN_ROOT_ALIASES_JSON"),
            key="ECHELON_FORBIDDEN_ROOT_ALIASES_JSON",
            errors=errors,
        ),
    }
    cleaned: dict[str, object] = {
        key: value for key, value in containment.items() if value
    }
    if errors:
        cleaned["parse_errors"] = errors
    return cleaned


def _execution_profile_violation(
    provider: str,
    metadata: Mapping[str, object],
) -> CliRunResult | None:
    if "execution_profile" not in metadata:
        return None
    raw_profile = metadata["execution_profile"]
    if raw_profile is None:
        return None
    if not isinstance(raw_profile, str):
        return CliRunResult(
            exit_code=125,
            stdout="",
            stderr="execution profile must be a string",
            metadata={"unsupported_execution_profile": "invalid"},
        )
    profile = raw_profile.strip()
    if not profile:
        return None
    if profile in SUPPORTED_EXECUTION_PROFILES.get(provider, frozenset()):
        return None
    if profile == "review_triage_v1":
        message = (
            "execution profile review_triage_v1 requires claude; "
            f"configured provider is {provider}"
        )
    else:
        message = (
            f"execution profile {profile} is unsupported; "
            f"configured provider is {provider}"
        )
    return CliRunResult(
        exit_code=125,
        stdout="",
        stderr=message,
        metadata={"unsupported_execution_profile": profile},
    )


def _json_string_list(
    raw: object,
    *,
    key: str,
    errors: list[str],
) -> list[str]:
    if not isinstance(raw, str) or not raw.strip():
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        errors.append(key)
        return []
    if not isinstance(parsed, list):
        errors.append(key)
        return []
    return [str(item) for item in parsed if str(item).strip()]


def _containment_cwd_violation(
    cwd: str,
    metadata: Mapping[str, object],
) -> CliRunResult | None:
    containment = metadata.get("containment")
    if not isinstance(containment, Mapping):
        return None
    parse_errors = _metadata_string_list(containment.get("parse_errors"))
    if parse_errors:
        return _containment_violation_result(
            cwd=_resolved_path(cwd),
            reason=(
                "malformed containment root metadata: "
                + ", ".join(sorted(parse_errors))
            ),
        )
    cwd_path = _resolved_path(cwd)
    allowed_roots = [
        _resolved_path(path)
        for path in _metadata_string_list(containment.get("allowed_roots"))
    ]
    forbidden_roots = [
        _resolved_path(path)
        for path in _metadata_string_list(containment.get("forbidden_roots"))
    ]
    for forbidden in forbidden_roots:
        if _path_is_relative_to(cwd_path, forbidden):
            return _containment_violation_result(
                cwd=cwd_path,
                reason=f"cwd is under forbidden root {forbidden}",
            )
    if allowed_roots and not any(
        _path_is_relative_to(cwd_path, root) for root in allowed_roots
    ):
        return _containment_violation_result(
            cwd=cwd_path,
            reason="cwd is outside allowed roots",
        )
    return None


def _containment_violation_result(*, cwd: Path, reason: str) -> CliRunResult:
    message = f"LLM provider containment violation: {reason}: {cwd}"
    return CliRunResult(
        exit_code=125,
        stdout="",
        stderr=message,
        metadata={"containment_violation": True, "reason": reason, "cwd": str(cwd)},
    )


def _metadata_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _resolved_path(path: object) -> Path:
    return Path(str(path)).expanduser().resolve(strict=False)


def _path_is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
