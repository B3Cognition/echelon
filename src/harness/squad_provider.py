"""SquadAgentResult + SquadCliProvider for pre-code squad phase dispatch."""
from __future__ import annotations

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
    result_repair_used: bool = False
    result_repair_reason: Optional[str] = None

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

    The block is parsed as one atomic contract. If any part of the final
    echelon_result is malformed — including journal_entries or trailing prose —
    extraction fails so the controller blocks instead of routing on a partial
    payload.
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

    return _parse(snippet)


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


def _echelon_result_repair_reason(raw: str) -> str:
    return (
        "malformed_echelon_result"
        if "echelon_result:" in raw or "```echelon_result" in raw
        else "missing_echelon_result"
    )


def _echelon_result_schema_error(echelon_result: object) -> Optional[str]:
    try:
        validate_echelon_result(echelon_result)
    except EchelonResultValidationError as exc:
        return str(exc)
    return None


def _build_echelon_result_repair_prompt(
    raw: str,
    reason: str,
    detail: Optional[str] = None,
    allowed_state_update_keys: Optional[object] = None,
) -> str:
    raw_tail = raw[-12000:]
    detail_block = f"Validation error: {detail}\n\n" if detail else ""
    allowed_block = ""
    if allowed_state_update_keys is not None:
        if isinstance(allowed_state_update_keys, (list, tuple, set, frozenset)):
            allowed = ", ".join(f"`{key}`" for key in allowed_state_update_keys)
            allowed_block = f"Allowed state_updates keys: {allowed or 'none'}.\n\n"
        else:
            allowed_block = "Allowed state_updates keys: not declared for this phase.\n\n"
    return (
        "You are repairing an Echelon squad agent control payload.\n\n"
        "Rules:\n"
        "- Do not modify files.\n"
        "- Do not rerun the phase.\n"
        "- Do not produce prose before or after the YAML block.\n"
        "- Return only one unfenced YAML block rooted at `echelon_result:`.\n"
        "- Use `state_updates: {}` when no state changes are needed.\n"
        "- Use `journal_entries: []` when no valid journal entries can be reconstructed.\n\n"
        f"Repair reason: {reason}\n"
        f"{detail_block}"
        f"{allowed_block}"
        "Original agent output tail:\n"
        "```text\n"
        f"{raw_tail}\n"
        "```\n\n"
        "Required output shape:\n"
        "echelon_result:\n"
        "  verdict: <DONE|COMPLETE|PASS|FAIL|BLOCKED|KILL|DEFER>\n"
        "  output_files: []\n"
        "  state_updates: {}\n"
        "  journal_entries: []\n"
    )


class SquadCliProvider(AICodingCliProvider):
    """Extends AICodingCliProvider with exec_agent() for squad phase dispatch.

    Inherits CLI selection (claude/copilot/opencode/codex via ECHELON_LLM env var).
    Adds output capture + echelon_result: extraction on top of streaming.
    """

    supports_echelon_result_repair = True

    def repair_echelon_result(
        self,
        project_root: str,
        raw: str,
        reason: str,
        detail: Optional[str] = None,
        *,
        timeout_ms: Optional[int] = None,
        allowed_state_update_keys: Optional[object] = None,
    ) -> Optional[dict]:
        repair_prompt = _build_echelon_result_repair_prompt(
            raw,
            reason,
            detail,
            allowed_state_update_keys,
        )
        repair_backend_result = self.run_agent_result(
            project_root,
            repair_prompt,
            timeout_ms=timeout_ms,
        )
        if repair_backend_result.exit_code != 0 or repair_backend_result.timed_out:
            return None
        repaired = _extract_echelon_result(repair_backend_result.stdout)
        if repaired is None:
            return None
        try:
            return validate_echelon_result(
                repaired,
                allowed_state_update_keys=allowed_state_update_keys,
            )
        except EchelonResultValidationError:
            return None

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
        echelon_result = _extract_echelon_result(raw)
        repair_used = False
        repair_reason: Optional[str] = None
        repair_detail: Optional[str] = None
        if exit_code == 0 and not timed_out:
            if echelon_result is None:
                repair_reason = _echelon_result_repair_reason(raw)
            else:
                repair_detail = _echelon_result_schema_error(echelon_result)
                if repair_detail:
                    repair_reason = "schema_invalid_echelon_result"
            repair_prompt = (
                _build_echelon_result_repair_prompt(
                    raw,
                    repair_reason,
                    repair_detail,
                )
                if repair_reason
                else ""
            )
        if repair_reason:
            repair_backend_result = self.run_agent_result(
                project_root,
                repair_prompt,
                timeout_ms=timeout_ms,
            )
            repair_used = True
            raw = backend_result.stdout
            timed_out = backend_result.timed_out
            exit_code = backend_result.exit_code
            if (
                repair_backend_result.exit_code == 0
                and not repair_backend_result.timed_out
            ):
                repaired = _extract_echelon_result(repair_backend_result.stdout)
                if repaired is not None:
                    echelon_result = repaired
            backend_result.cost_usd += repair_backend_result.cost_usd
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
            cost_usd=backend_result.cost_usd,
            result_repair_used=repair_used,
            result_repair_reason=repair_reason,
        )
