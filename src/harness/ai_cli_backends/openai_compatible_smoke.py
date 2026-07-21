"""Smoke checks for OpenAI-compatible provider endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from harness.ai_cli_backend import CliRunRequest
from harness.ai_cli_backends.openai_compatible import OpenAICompatibleBackend
from harness.config import HarnessConfig, LlmConfig


@dataclass(frozen=True)
class OpenAICompatibleSmokeResult:
    ok: bool
    exit_code: int
    stdout: str
    stderr: str
    token_usage: int
    tool_call_count: int
    transcript_path: str
    work_dir: Path


def run_openai_compatible_smoke(
    *,
    project_root: Path,
    base_url: str,
    model: str,
    api_key_env: str | None,
    api_key_file: str | None,
    timeout_s: float,
    streaming: bool,
) -> OpenAICompatibleSmokeResult:
    work_dir = _smoke_work_dir(project_root)
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "smoke-input.txt").write_text(
        "OpenAI-compatible smoke fixture. Read this file, then return "
        "echelon_result with verdict PASS.\n",
        encoding="utf-8",
    )
    config = HarnessConfig(
        target_repo=".",
        target_default_branch="main",
        provider="docker",
        llm=LlmConfig(
            cli="openai-compatible",
            base_url=base_url,
            model=model,
            api_key_env=api_key_env,
            api_key_file=api_key_file,
            timeout_ms=int(timeout_s * 1000),
            temperature=0.0,
            max_tokens=1024,
            features={
                "streaming": streaming,
                "stream_options": streaming,
                "tool_calls": True,
                "max_tool_rounds": 4,
                "transcript": True,
                "provider_transcript_dir": str(work_dir),
            },
        ),
    )
    result = OpenAICompatibleBackend(config).run_prompt(
        CliRunRequest(
            cwd=str(work_dir),
            prompt=(
                "Run an OpenAI-compatible provider smoke check. Use the read_file "
                "tool to read smoke-input.txt. Then respond exactly with:\n"
                "echelon_result:\n  verdict: PASS\n"
            ),
            env={},
            timeout_s=timeout_s,
            metadata={
                "run_dir": str(work_dir),
                "provider_transcript_label": "smoke",
            },
        )
    )
    tool_call_count = int(result.metadata.get("tool_call_count", 0) or 0)
    ok = (
        result.exit_code == 0
        and tool_call_count >= 1
        and "verdict: PASS" in result.stdout
    )
    transcript_path = result.metadata.get("provider_transcript_path")
    return OpenAICompatibleSmokeResult(
        ok=ok,
        exit_code=result.exit_code,
        stdout=result.stdout,
        stderr=result.stderr,
        token_usage=result.token_usage,
        tool_call_count=tool_call_count,
        transcript_path=str(transcript_path) if isinstance(transcript_path, str) else "",
        work_dir=work_dir,
    )


def _smoke_work_dir(project_root: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return (
        project_root.resolve(strict=False)
        / ".echelon"
        / "smoke"
        / f"openai-compatible-{timestamp}"
    )
