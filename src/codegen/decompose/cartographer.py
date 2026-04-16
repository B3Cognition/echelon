"""
cartographer.py — CartographerDispatcher for autonomous FR respecification.

Spec 026: FR-013–FR-024.
ADR-001: Lives in decompose/ for single responsibility (not in soar_bridge.py).
ADR-002: JSON extraction strategy: json.loads → regex → confidence=0.0 fallback.

Dispatches LLM with FR content + bug context and returns a structured revision
proposal with confidence score.
"""
from __future__ import annotations

import concurrent.futures
import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# FR-024: Configurable timeout via environment variable (default 30s)
RESPECIFY_TIMEOUT = int(os.environ.get("CODEGEN_RESPECIFY_TIMEOUT", "30"))

# FR-017: Confidence thresholds for RESPECIFY apply logic
CONFIDENCE_THRESHOLD_AUTO = 0.85
CONFIDENCE_THRESHOLD_FLAGGED = 0.60

_SYSTEM_PROMPT = """You are CARTOGRAPHER, an expert software requirements analyst.
You receive a functional requirement (FR) that has failed implementation after multiple
retries, along with bug reports from those failures. Your task is to propose a revised
FR that addresses the root causes of the failures.

You MUST respond with ONLY a JSON object in this exact format (no preamble, no explanation):
{"revised_fr": "<revised requirement text>", "rationale": "<explanation of changes>", "confidence": <float 0.0-1.0>}

The confidence field must be a float between 0.0 and 1.0 reflecting how certain you are
that the revised FR will resolve the failures. Be conservative: prefer lower confidence
over false confidence."""

_USER_TEMPLATE = """\
Original FR:
{original_fr}

Bug reports from failed implementation attempts:
{bug_context}

Last test output / violation summary:
{test_output}

Propose a revised FR that fixes the root causes. Return ONLY the JSON object.
"""


@dataclass
class CartographerResult:
    """Result of a CartographerDispatcher.dispatch() call."""
    revised_fr: str
    rationale: str
    confidence: float
    raw_response: str
    parse_success: bool


class CartographerDispatcher:
    """
    Dispatches the LLM to propose a revised functional requirement.

    FR-016: Returns structured JSON {"revised_fr", "rationale", "confidence"}.
    FR-024: Enforces RESPECIFY_TIMEOUT second timeout; timeout → confidence=0.0.
    ADR-002: Two-tier JSON extraction; failure → confidence=0.0 → escalate.
    """

    def __init__(self, model: Optional[str] = None) -> None:
        self.model = model or os.environ.get("CODEGEN_MODEL", "claude-opus-4-6")
        self.timeout = RESPECIFY_TIMEOUT

    def dispatch(
        self,
        original_fr: str,
        bug_context: str,
        test_output: str,
    ) -> CartographerResult:
        """
        Call the LLM and extract a structured revision proposal.

        FR-016: JSON parse failure → confidence defaults to 0.0.
        FR-024: Timeout → treat as parse failure → confidence=0.0.

        Returns:
            CartographerResult with revised_fr, rationale, confidence.
        """
        raw = ""
        try:
            raw = self._call_llm(original_fr, bug_context, test_output)
            return self._parse_response(raw)
        except TimeoutError:
            logger.warning(
                "[CartographerDispatcher] LLM call timed out after %ds — "
                "defaulting confidence=0.0 (FR-024)",
                self.timeout,
            )
        except Exception as exc:
            logger.warning("[CartographerDispatcher] Dispatch failed: %s", exc)
        return CartographerResult(
            revised_fr="",
            rationale="dispatch error or timeout",
            confidence=0.0,
            raw_response=raw,
            parse_success=False,
        )

    def _call_llm(self, original_fr: str, bug_context: str, test_output: str) -> str:
        """Call Anthropic API with ThreadPoolExecutor timeout (FR-024)."""
        import anthropic  # type: ignore[import]

        client = anthropic.Anthropic()
        user_msg = _USER_TEMPLATE.format(
            original_fr=original_fr,
            bug_context=bug_context,
            test_output=test_output,
        )

        def _do_call() -> str:
            response = client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_msg}],
            )
            return response.content[0].text if response.content else ""

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_do_call)
            try:
                return future.result(timeout=self.timeout)
            except concurrent.futures.TimeoutError:
                raise TimeoutError(
                    f"CartographerDispatcher timed out after {self.timeout}s"
                )

    def _parse_response(self, raw: str) -> CartographerResult:
        """
        ADR-002: Two-tier JSON extraction.

        Attempt 1: json.loads on stripped full response.
        Attempt 2: re.search for first {...} block.
        Fallback: confidence=0.0, parse_success=False.
        """
        # Attempt 1: full response is valid JSON
        try:
            data = json.loads(raw.strip())
            return self._build_result(data, raw, parse_success=True)
        except (json.JSONDecodeError, ValueError):
            pass

        # Attempt 2: extract first {...} block (handles preamble text)
        match = re.search(r"\{[^{}]*\}", raw, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(0))
                return self._build_result(data, raw, parse_success=True)
            except (json.JSONDecodeError, ValueError):
                pass

        logger.warning(
            "[CartographerDispatcher] JSON parse failure — confidence defaults to 0.0. "
            "Raw response logged to respec-log."
        )
        return CartographerResult(
            revised_fr="",
            rationale="JSON parse failure",
            confidence=0.0,
            raw_response=raw,
            parse_success=False,
        )

    def _build_result(
        self, data: dict, raw: str, parse_success: bool
    ) -> CartographerResult:
        """Build CartographerResult from parsed dict; clamp confidence to [0, 1]."""
        confidence = max(0.0, min(1.0, float(data.get("confidence", 0.0))))
        return CartographerResult(
            revised_fr=str(data.get("revised_fr", "")),
            rationale=str(data.get("rationale", "")),
            confidence=confidence,
            raw_response=raw,
            parse_success=parse_success,
        )
