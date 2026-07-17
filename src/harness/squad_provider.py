"""SquadAgentResult + SquadCliProvider for pre-code squad phase dispatch."""
from __future__ import annotations

import json
import os
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


@dataclass
class SquadAgentResult:
    exit_code: int
    echelon_result: Optional[dict]
    raw_output: str
    duration_ms: int
    timed_out: bool
    cost_usd: float = 0.0
    echelon_result_repair_attempted: bool = False
    echelon_result_repair_succeeded: bool = False
    provider_limit_message: str = ""

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


def _provider_session_limit_message(*transcripts: str) -> str:
    """Return the provider's actionable session-limit line, when present."""
    needles = ("session limit", "usage limit", "rate limit", "quota exceeded")
    for transcript in transcripts:
        for line in transcript.splitlines():
            message = line.strip()
            if message and any(needle in message.lower() for needle in needles):
                return message
    return ""


def _quote_unquoted_yaml_scalar_colons(text: str) -> str:
    """Recover free-text YAML scalars that contain an unquoted ``: `` delimiter.

    Agent output is required to be valid YAML. This narrow recovery supports a
    common LLM mistake in prose fields such as ``rationale`` while leaving
    structured values and correctly quoted scalars untouched. Schema validation
    remains mandatory after parsing.
    """
    recovered: list[str] = []
    for line in text.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        newline = line[len(content):]
        if ": " not in content:
            recovered.append(line)
            continue
        prefix, value = content.split(": ", 1)
        stripped_value = value.lstrip()
        if (
            ": " not in value
            or not prefix.lstrip().startswith(("rationale", "reasoning", "section", "artifact"))
            or stripped_value.startswith(("'", '"', "[", "{", "|", ">"))
        ):
            recovered.append(line)
            continue
        recovered.append(f"{prefix}: {json.dumps(value, ensure_ascii=False)}{newline}")
    return "".join(recovered)


def _trim_trailing_renderer_output(text: str) -> str:
    """Keep the indented YAML payload and discard provider status rendering."""
    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() and not line[0].isspace():
            return "".join(lines[:index])
    return text


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

    snippet = _trim_trailing_renderer_output(snippet)

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

    recovered_snippet = _quote_unquoted_yaml_scalar_colons(snippet)
    if recovered_snippet != snippet:
        result = _parse(recovered_snippet)
        if result is not None:
            return result

    # Retry without journal_entries — routing fields (verdict, state_updates)
    # appear before journal_entries in the block, so stripping journal_entries
    # lets the rest parse correctly even when entries have YAML formatting errors.
    for journal_key in ("  journal_entries:", "journal_entries:"):
        je_idx = recovered_snippet.find(f"\n{journal_key}")
        if je_idx != -1:
            result = _parse(recovered_snippet[:je_idx])
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


def _validate_echelon_result_or_reason(
    echelon_result: object,
) -> tuple[Optional[dict], Optional[str]]:
    if echelon_result is None:
        return None, "missing echelon_result"
    try:
        return validate_echelon_result(echelon_result), None
    except EchelonResultValidationError as exc:
        return None, str(exc)


def _build_echelon_result_repair_prompt(
    original_prompt: str,
    raw_output: str,
    reason: str,
) -> str:
    return (
        "The previous agent invocation exited cleanly, but its final "
        "`echelon_result` control payload was missing or invalid.\n\n"
        "Do not edit files. Do not inspect the repository. Do not rerun tests. "
        "Only reconstruct the final `echelon_result` block from the original "
        "prompt and raw output below.\n\n"
        f"Validation problem: {reason}\n\n"
        "Return exactly one valid YAML block starting with `echelon_result:`. "
        "Do not wrap it in Markdown fences and do not add prose before or after it. "
        "Double-quote every free-text scalar (including rationale and reasoning), "
        "escaping embedded quotes; unquoted text containing `: ` is invalid YAML.\n\n"
        "## Original Prompt\n"
        f"{original_prompt}\n\n"
        "## Raw Output From Clean Invocation\n"
        f"{raw_output}\n"
    )


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
        start = time.monotonic()
        backend_result = self.run_agent_result(
            project_root,
            prompt,
            timeout_ms=timeout_ms,
        )
        duration_ms = int((time.monotonic() - start) * 1000)
        exit_code = backend_result.exit_code
        raw = backend_result.stdout
        timed_out = backend_result.timed_out
        cost_usd = backend_result.cost_usd
        provider_limit_message = ""
        if exit_code != 0 or timed_out:
            provider_limit_message = _provider_session_limit_message(
                backend_result.stdout,
                backend_result.stderr,
            )
        parsed_result = _extract_echelon_result(raw)
        echelon_result, validation_reason = _validate_echelon_result_or_reason(
            parsed_result
        )
        repair_attempted = False
        repair_succeeded = False

        if (
            echelon_result is None
            and exit_code == 0
            and not timed_out
            and validation_reason
        ):
            repair_attempted = True
            repair_prompt = _build_echelon_result_repair_prompt(
                prompt,
                raw,
                validation_reason,
            )
            repair_result = self.run_agent_result(
                project_root,
                repair_prompt,
                timeout_ms=timeout_ms,
            )
            cost_usd += repair_result.cost_usd
            if repair_result.exit_code == 0 and not repair_result.timed_out:
                repair_parsed = _extract_echelon_result(repair_result.stdout)
                repaired, repair_reason = _validate_echelon_result_or_reason(
                    repair_parsed
                )
                if repaired is not None:
                    echelon_result = repaired
                    repair_succeeded = True
                else:
                    validation_reason = repair_reason or validation_reason

        if echelon_result is None and parsed_result is not None:
            echelon_result = _validation_block_result(validation_reason or "invalid")

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
            echelon_result_repair_attempted=repair_attempted,
            echelon_result_repair_succeeded=repair_succeeded,
            provider_limit_message=provider_limit_message,
        )
