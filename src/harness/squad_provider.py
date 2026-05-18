"""SquadAgentResult + SquadCliProvider for pre-code squad phase dispatch."""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

from harness.llm_provider import AICodingCliProvider
from harness.skill_loader import StreamEventPrinter


@dataclass
class SquadAgentResult:
    exit_code: int
    echelon_result: Optional[dict]
    raw_output: str
    duration_ms: int
    timed_out: bool

    @property
    def verdict(self) -> Optional[str]:
        return (self.echelon_result or {}).get("verdict")

    @property
    def state_updates(self) -> dict:
        return (self.echelon_result or {}).get("state_updates", {})

    @property
    def blocked(self) -> bool:
        return self.verdict == "BLOCKED" or self.timed_out or self.exit_code != 0


def _extract_echelon_result(raw: str) -> Optional[dict]:
    """Find the last echelon_result: block in raw output and parse it."""
    idx = raw.rfind("echelon_result:")
    if idx == -1:
        return None
    snippet = raw[idx:]
    # Trim at closing code fence if present
    fence_end = snippet.find("\n```")
    if fence_end != -1:
        snippet = snippet[:fence_end]
    try:
        parsed = yaml.safe_load(snippet)
        if isinstance(parsed, dict) and "echelon_result" in parsed:
            return parsed["echelon_result"]
        return None
    except yaml.YAMLError:
        return None


class SquadCliProvider(AICodingCliProvider):
    """Extends AICodingCliProvider with exec_agent() for squad phase dispatch.

    Inherits CLI selection (claude/copilot/opencode via ECHELON_LLM env var).
    Adds output capture + echelon_result: extraction on top of streaming.
    """

    def exec_agent(
        self,
        project_root: str,
        prompt: str,
        timeout_ms: Optional[int] = None,
    ) -> SquadAgentResult:
        cmd = self._build_cmd(prompt)
        env = {**os.environ}
        if self._config_dir and self._cli == "claude":
            env["CLAUDE_CONFIG_DIR"] = os.path.expanduser(self._config_dir)

        start = time.monotonic()
        if self._cli == "claude":
            exit_code, raw = self._run_streaming_captured(cmd, project_root, env, timeout_ms)
        else:
            exit_code, raw = self._run_plain_captured(cmd, project_root, env, timeout_ms)

        duration_ms = int((time.monotonic() - start) * 1000)
        timed_out = exit_code is None
        return SquadAgentResult(
            exit_code=exit_code if exit_code is not None else -1,
            echelon_result=_extract_echelon_result(raw),
            raw_output=raw,
            duration_ms=duration_ms,
            timed_out=timed_out,
        )

    def _run_streaming_captured(
        self, cmd: list, cwd: str, env: dict, timeout_ms: Optional[int]
    ) -> tuple[Optional[int], str]:
        timeout_s = (timeout_ms / 1000.0) if timeout_ms else self._timeout_s
        proc = subprocess.Popen(
            cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=None
        )
        text_chunks: list[str] = []
        timed_out = False
        printer = StreamEventPrinter()

        def _kill() -> None:
            nonlocal timed_out
            timed_out = True
            proc.kill()

        timer = threading.Timer(timeout_s, _kill)
        try:
            timer.start()
            for raw_line in proc.stdout:  # type: ignore[union-attr]
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    printer(event)
                    if (
                        event.get("type") == "content_block_delta"
                        and event.get("delta", {}).get("type") == "text_delta"
                    ):
                        text_chunks.append(event["delta"].get("text", ""))
                except json.JSONDecodeError:
                    print(line, flush=True)
                    text_chunks.append(line)
            proc.stdout.close()  # type: ignore[union-attr]
            proc.wait()
        finally:
            timer.cancel()

        exit_code = None if timed_out else proc.returncode
        return exit_code, "".join(text_chunks)

    def _run_plain_captured(
        self, cmd: list, cwd: str, env: dict, timeout_ms: Optional[int]
    ) -> tuple[Optional[int], str]:
        timeout_s = (timeout_ms / 1000.0) if timeout_ms else self._timeout_s
        try:
            result = subprocess.run(
                cmd, cwd=cwd, env=env, timeout=timeout_s, capture_output=True
            )
            text = result.stdout.decode("utf-8", errors="replace")
            print(text, flush=True)
            return result.returncode, text
        except subprocess.TimeoutExpired:
            return None, ""
