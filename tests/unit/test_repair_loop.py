"""Tests for the reusable draft/critique/repair/re-check loop."""

from __future__ import annotations

from harness.repair_loop import (
    RepairAttempt,
    RepairCheck,
    RepairCritique,
    RepairLoop,
    RepairVerdict,
)


def test_repair_loop_accepts_after_recheck() -> None:
    calls: list[str] = []
    checks = [RepairCheck(verdict=RepairVerdict.ACCEPT, output="rechecked")]

    loop = RepairLoop(
        max_repairs=3,
        critique=lambda check, iteration: calls.append(f"critique:{iteration}:{check.output}")
        or RepairCritique(summary="missing tests", signature="missing-tests"),
        repair=lambda critique, iteration: calls.append(f"repair:{iteration}:{critique.signature}")
        or RepairAttempt(output="patched"),
        recheck=lambda attempt, iteration: calls.append(f"recheck:{iteration}:{attempt.output}")
        or checks.pop(0),
    )

    result = loop.run(RepairCheck(verdict=RepairVerdict.CONTINUE, output="draft"))

    assert result.verdict == RepairVerdict.ACCEPT
    assert result.iterations == 1
    assert result.final_check.output == "rechecked"
    assert calls == [
        "critique:1:draft",
        "repair:1:missing-tests",
        "recheck:1:patched",
    ]
    assert [event.stage for event in result.events] == [
        "draft",
        "critique",
        "repair",
        "recheck",
        "accept",
    ]


def test_repair_loop_blocks_on_critique() -> None:
    loop = RepairLoop(
        max_repairs=3,
        critique=lambda check, iteration: RepairCritique(
            summary="human decision needed",
            signature="needs-human",
            block_reason="human_input_required",
        ),
        repair=lambda critique, iteration: RepairAttempt(output="unused"),
        recheck=lambda attempt, iteration: RepairCheck(
            verdict=RepairVerdict.ACCEPT,
            output="unused",
        ),
    )

    result = loop.run(RepairCheck(verdict=RepairVerdict.CONTINUE, output="draft"))

    assert result.verdict == RepairVerdict.BLOCK
    assert result.termination_reason == "human_input_required"
    assert result.iterations == 1
    assert [event.stage for event in result.events] == [
        "draft",
        "critique",
        "block",
    ]


def test_repair_loop_blocks_repeated_critique_signature_before_infinite_loop() -> None:
    repair_count = 0

    def repair(_critique: RepairCritique, _iteration: int) -> RepairAttempt:
        nonlocal repair_count
        repair_count += 1
        return RepairAttempt(output=f"patched-{repair_count}")

    loop = RepairLoop(
        max_repairs=5,
        repeat_signature_threshold=2,
        critique=lambda check, iteration: RepairCritique(
            summary="same failure",
            signature="same-failure",
        ),
        repair=repair,
        recheck=lambda attempt, iteration: RepairCheck(
            verdict=RepairVerdict.CONTINUE,
            output=attempt.output,
        ),
    )

    result = loop.run(RepairCheck(verdict=RepairVerdict.CONTINUE, output="draft"))

    assert result.verdict == RepairVerdict.BLOCK
    assert result.termination_reason == "repeated_critique_signature"
    assert result.iterations == 2
    assert repair_count == 1


def test_repair_loop_exhausts_after_max_repairs() -> None:
    loop = RepairLoop(
        max_repairs=2,
        critique=lambda check, iteration: RepairCritique(
            summary=f"failure {iteration}",
            signature=f"failure-{iteration}",
        ),
        repair=lambda critique, iteration: RepairAttempt(output=f"patched-{iteration}"),
        recheck=lambda attempt, iteration: RepairCheck(
            verdict=RepairVerdict.CONTINUE,
            output=attempt.output,
        ),
    )

    result = loop.run(RepairCheck(verdict=RepairVerdict.CONTINUE, output="draft"))

    assert result.verdict == RepairVerdict.CONTINUE
    assert result.termination_reason == "max_repairs_exhausted"
    assert result.iterations == 2
    assert result.final_check.output == "patched-2"
