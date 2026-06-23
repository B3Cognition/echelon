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

from harness.echelon_result_schema import (
    EchelonResultValidationError,
    validate_echelon_result,
)
from harness.llm_provider import AICodingCliProvider
from harness.skill_loader import StreamEventPrinter


@dataclass
class SquadAgentResult:
    exit_code: int
    echelon_result: Optional[dict]
    raw_output: str
    duration_ms: int
    timed_out: bool
    cost_usd: float = 0.0

    @property
    def verdict(self) -> Optional[str]:
        payload = self.echelon_result if isinstance(self.echelon_result, dict) else {}
        verdict = payload.get("verdict")
        return verdict if isinstance(verdict, str) else None

    @property
    def state_updates(self) -> dict:
        payload = self.echelon_result if isinstance(self.echelon_result, dict) else {}
        updates = payload.get("state_updates", {})
        return updates if isinstance(updates, dict) else {}

    @property
    def blocked(self) -> bool:
        return self.verdict == "BLOCKED" or self.timed_out or self.exit_code != 0


def _extract_echelon_result(raw: str) -> Optional[dict]:
    """Find the last echelon_result block in raw output and parse it.

    Handles two YAML-compatible formats agents emit:

    1. YAML-key format (COMMANDER and ~10 agents):
         echelon_result:
           verdict: FAIL
           state_updates: ...

    2. Fenced-block format (SAGE, GATEKEEPER, and ~40 other agents):
         ```echelon_result
         verdict: FAIL
         state_updates: ...
         ```

    Uses rfind to find the last occurrence of each format, then picks
    whichever starts later in the text (most likely to be the actual
    agent output rather than a template or quoted example).

    Attempts full parse first. If YAML fails (commonly due to complex
    journal_entries content), retries with journal_entries stripped so
    that verdict and state_updates — the routing-critical fields — are
    still extracted. Journal entries are handled separately by
    _write_journal_entries, so losing them here is safe.
    """
    _FENCE = "```echelon_result"
    yaml_idx = raw.rfind("echelon_result:")
    fence_idx = raw.rfind(_FENCE)

    if yaml_idx == -1 and fence_idx == -1:
        return None

    snippet: str
    if fence_idx != -1 and fence_idx > yaml_idx:
        # Fenced format: extract body and wrap in echelon_result: key so
        # _parse sees a standard YAML mapping with the expected root key.
        body = raw[fence_idx + len(_FENCE):]
        fence_end = body.find("\n```")
        if fence_end != -1:
            body = body[:fence_end]
        # Indent each line by 2 spaces to nest it under echelon_result:.
        indented = "\n".join("  " + line for line in body.splitlines())
        snippet = "echelon_result:\n" + indented
    else:
        snippet = raw[yaml_idx:]
        # Trim at closing code fence if present.
        fence_end = snippet.find("\n```")
        if fence_end != -1:
            snippet = snippet[:fence_end]

    def _parse(text: str) -> Optional[dict]:
        try:
            parsed = yaml.safe_load(text)
            if isinstance(parsed, dict) and "echelon_result" in parsed:
                return parsed["echelon_result"]
        except yaml.YAMLError:
            pass
        return None

    # Full parse — preferred.
    result = _parse(snippet)
    if result is not None:
        return result

    # Retry without journal_entries — routing fields (verdict, state_updates)
    # appear before journal_entries in the block, so stripping journal_entries
    # lets the rest parse correctly even when entries have YAML formatting errors.
    for journal_key in ("  journal_entries:", "journal_entries:"):
        je_idx = snippet.find(f"\n{journal_key}")
        if je_idx != -1:
            result = _parse(snippet[:je_idx])
            if result is not None:
                return result

    return None


def _validation_block_result(reason: str, debug_path: Optional[str] = None) -> dict:
    state_updates = {"blocked_reason": f"echelon_result validation failed: {reason}"}
    if debug_path:
        state_updates["echelon_result_debug_path"] = debug_path
    return {
        "verdict": "BLOCKED",
        "state_updates": state_updates,
        "journal_entries": [],
    }


def _write_debug_capture(
    raw: str,
    result: object,
    exit_code: Optional[int],
    duration_ms: int,
) -> Optional[str]:
    debug_dir = os.environ.get("ECHELON_DEBUG_RAW_DIR", "")
    if not debug_dir:
        return None
    try:
        debug_root = Path(debug_dir)
        debug_root.mkdir(parents=True, exist_ok=True)
        tag = f"{os.getpid()}-{duration_ms}"
        raw_path = debug_root / f"raw-{tag}.txt"
        result_path = debug_root / f"result-{tag}.txt"
        raw_path.write_text(raw, errors="replace")
        result_path.write_text(
            f"echelon_result={result!r}\nexit_code={exit_code}\n"
        )
        return str(raw_path)
    except Exception:
        return None


def _validate_or_block_echelon_result(
    echelon_result: object,
    raw: str,
    exit_code: Optional[int],
    duration_ms: int,
) -> Optional[dict]:
    if echelon_result is None:
        return None
    try:
        return validate_echelon_result(echelon_result)
    except EchelonResultValidationError as exc:
        debug_path = _write_debug_capture(raw, echelon_result, exit_code, duration_ms)
        return _validation_block_result(str(exc), debug_path)


class SquadCliProvider(AICodingCliProvider):
    """Extends AICodingCliProvider with exec_agent() for squad phase dispatch.

    Inherits CLI selection (claude/copilot/opencode/codex via ECHELON_LLM env var).
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
        cost_usd = 0.0
        if self._cli == "claude":
            exit_code, raw, cost_usd = self._run_streaming_captured(cmd, project_root, env, timeout_ms)
        else:
            exit_code, raw = self._run_plain_captured(cmd, project_root, env, timeout_ms)

        duration_ms = int((time.monotonic() - start) * 1000)
        timed_out = exit_code is None
        echelon_result = _extract_echelon_result(raw)
        echelon_result = _validate_or_block_echelon_result(
            echelon_result,
            raw,
            exit_code,
            duration_ms,
        )

        # Debug capture: write raw + parse result to /tmp/echelon-raw-<pid>.txt
        # when the parse returns None or missing state_updates so we can inspect
        # what the harness actually received vs what the terminal shows.
        if echelon_result is None or not (echelon_result or {}).get("state_updates"):
            _write_debug_capture(raw, echelon_result, exit_code, duration_ms)

        return SquadAgentResult(
            exit_code=exit_code if exit_code is not None else -1,
            echelon_result=echelon_result,
            raw_output=raw,
            duration_ms=duration_ms,
            timed_out=timed_out,
            cost_usd=cost_usd,
        )

    def _run_streaming_captured(
        self, cmd: list, cwd: str, env: dict, timeout_ms: Optional[int]
    ) -> tuple[Optional[int], str, float]:
        timeout_s = (timeout_ms / 1000.0) if timeout_ms else self._timeout_s
        proc = subprocess.Popen(
            cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=None
        )
        text_chunks: list[str] = []
        timed_out = False
        cost_usd = 0.0
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
                    etype = event.get("type")
                    if etype == "assistant":
                        # Full assistant turn message — extract all text blocks.
                        # This is the primary format emitted by the Claude CLI.
                        for block in event.get("message", {}).get("content", []):
                            if block.get("type") == "text":
                                text_chunks.append(block.get("text", ""))
                    elif (
                        etype == "content_block_delta"
                        and event.get("delta", {}).get("type") == "text_delta"
                    ):
                        # Streaming delta format (older CLI versions).
                        text_chunks.append(event["delta"].get("text", ""))
                    elif etype == "result":
                        cost_usd = float(event.get("total_cost_usd") or 0)
                except json.JSONDecodeError:
                    print(line, flush=True)
                    text_chunks.append(line)
            proc.stdout.close()  # type: ignore[union-attr]
            proc.wait()
        finally:
            timer.cancel()

        exit_code = None if timed_out else proc.returncode
        return exit_code, "".join(text_chunks), cost_usd

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
