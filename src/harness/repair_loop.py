"""Reusable bounded draft/critique/repair/re-check loop primitive."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


class RepairVerdict(str, Enum):
    """Deterministic repair-loop verdict."""

    ACCEPT = "accept"
    BLOCK = "block"
    CONTINUE = "continue"


@dataclass(frozen=True)
class RepairCheck:
    """Draft or re-check result consumed by the repair loop."""

    verdict: RepairVerdict
    output: Any = None
    reason: str = ""
    tokens: int = 0


@dataclass(frozen=True)
class RepairCritique:
    """Critique result that decides whether repair should proceed."""

    summary: str
    signature: str = ""
    block_reason: str = ""
    tokens: int = 0


@dataclass(frozen=True)
class RepairAttempt:
    """Repair attempt output passed into the re-check step."""

    output: Any = None
    tokens: int = 0


@dataclass(frozen=True)
class RepairLoopEvent:
    """Structured event log entry for later audit/internalization."""

    stage: str
    iteration: int
    verdict: RepairVerdict | None = None
    reason: str = ""
    signature: str = ""
    tokens: int = 0


@dataclass(frozen=True)
class RepairLoopResult:
    """Final bounded repair-loop result."""

    verdict: RepairVerdict
    termination_reason: str
    iterations: int
    final_check: RepairCheck
    events: list[RepairLoopEvent] = field(default_factory=list)
    tokens_used: int = 0


CritiqueFn = Callable[[RepairCheck, int], RepairCritique]
RepairFn = Callable[[RepairCritique, int], RepairAttempt]
RecheckFn = Callable[[RepairAttempt, int], RepairCheck]


class RepairLoop:
    """Run Draft output -> Critique -> Repair -> Re-check -> Accept/Block.

    The primitive is intentionally deterministic: callers provide the critique,
    repair, and re-check functions. This class only bounds iterations, records
    events, and blocks repeated critique signatures before they can loop forever.
    """

    def __init__(
        self,
        *,
        max_repairs: int,
        critique: CritiqueFn,
        repair: RepairFn,
        recheck: RecheckFn,
        repeat_signature_threshold: int = 3,
    ) -> None:
        if max_repairs < 0:
            raise ValueError("max_repairs must be >= 0")
        if repeat_signature_threshold < 1:
            raise ValueError("repeat_signature_threshold must be >= 1")
        self._max_repairs = max_repairs
        self._critique = critique
        self._repair = repair
        self._recheck = recheck
        self._repeat_signature_threshold = repeat_signature_threshold

    def run(self, draft: RepairCheck) -> RepairLoopResult:
        """Execute the bounded repair loop from an initial draft/check result."""
        events: list[RepairLoopEvent] = [
            RepairLoopEvent(
                stage="draft",
                iteration=0,
                verdict=draft.verdict,
                reason=draft.reason,
                tokens=draft.tokens,
            )
        ]
        tokens_used = draft.tokens

        immediate = self._terminal_result(
            draft,
            events=events,
            iterations=0,
            tokens_used=tokens_used,
        )
        if immediate is not None:
            return immediate

        current = draft
        signatures: Counter[str] = Counter()

        for iteration in range(1, self._max_repairs + 1):
            critique = self._critique(current, iteration)
            tokens_used += critique.tokens
            events.append(
                RepairLoopEvent(
                    stage="critique",
                    iteration=iteration,
                    reason=critique.summary,
                    signature=critique.signature,
                    tokens=critique.tokens,
                )
            )

            if critique.block_reason:
                events.append(
                    RepairLoopEvent(
                        stage="block",
                        iteration=iteration,
                        verdict=RepairVerdict.BLOCK,
                        reason=critique.block_reason,
                        signature=critique.signature,
                    )
                )
                return RepairLoopResult(
                    verdict=RepairVerdict.BLOCK,
                    termination_reason=critique.block_reason,
                    iterations=iteration,
                    final_check=current,
                    events=events,
                    tokens_used=tokens_used,
                )

            if critique.signature:
                signatures[critique.signature] += 1
                if signatures[critique.signature] >= self._repeat_signature_threshold:
                    events.append(
                        RepairLoopEvent(
                            stage="block",
                            iteration=iteration,
                            verdict=RepairVerdict.BLOCK,
                            reason="repeated_critique_signature",
                            signature=critique.signature,
                        )
                    )
                    return RepairLoopResult(
                        verdict=RepairVerdict.BLOCK,
                        termination_reason="repeated_critique_signature",
                        iterations=iteration,
                        final_check=current,
                        events=events,
                        tokens_used=tokens_used,
                    )

            attempt = self._repair(critique, iteration)
            tokens_used += attempt.tokens
            events.append(
                RepairLoopEvent(
                    stage="repair",
                    iteration=iteration,
                    tokens=attempt.tokens,
                )
            )

            current = self._recheck(attempt, iteration)
            tokens_used += current.tokens
            events.append(
                RepairLoopEvent(
                    stage="recheck",
                    iteration=iteration,
                    verdict=current.verdict,
                    reason=current.reason,
                    tokens=current.tokens,
                )
            )

            terminal = self._terminal_result(
                current,
                events=events,
                iterations=iteration,
                tokens_used=tokens_used,
            )
            if terminal is not None:
                return terminal

        events.append(
            RepairLoopEvent(
                stage="exhaust",
                iteration=self._max_repairs,
                verdict=RepairVerdict.CONTINUE,
                reason="max_repairs_exhausted",
            )
        )
        return RepairLoopResult(
            verdict=RepairVerdict.CONTINUE,
            termination_reason="max_repairs_exhausted",
            iterations=self._max_repairs,
            final_check=current,
            events=events,
            tokens_used=tokens_used,
        )

    @staticmethod
    def _terminal_result(
        check: RepairCheck,
        *,
        events: list[RepairLoopEvent],
        iterations: int,
        tokens_used: int,
    ) -> RepairLoopResult | None:
        if check.verdict not in {RepairVerdict.ACCEPT, RepairVerdict.BLOCK}:
            return None
        reason = check.reason or check.verdict.value
        events.append(
            RepairLoopEvent(
                stage=check.verdict.value,
                iteration=iterations,
                verdict=check.verdict,
                reason=reason,
            )
        )
        return RepairLoopResult(
            verdict=check.verdict,
            termination_reason=reason,
            iterations=iterations,
            final_check=check,
            events=events,
            tokens_used=tokens_used,
        )
