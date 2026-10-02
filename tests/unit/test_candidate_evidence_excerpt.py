from harness.candidate_evidence import _failure_excerpt, _failed_test_case_details
import pytest


def test_failed_case_identity_uses_final_results_not_progress_or_log_mentions():
    output = "\n".join([
        "  ✘ 1 [chromium] › tests/retry.spec.ts:1:1 › [echelon:E2E-FLAKY-001] retried",
        "  ✓ 2 [chromium] › tests/pass.spec.ts:1:1 › [echelon:E2E-PASS-001] passed",
        "Error: mentions [echelon:E2E-NOISE-001]",
        "\x1b[31m  2 failed\x1b[0m",
        "    [chromium] › tests/pitch.spec.ts:1:1 › [echelon:E2E-PITCH-001] pitch",
        "    [chromium] › tests/pitch.spec.ts:1:1 › [echelon:E2E-PITCH-001] pitch",
        "  1 flaky",
        "    [chromium] › tests/retry.spec.ts:1:1 › [echelon:E2E-FLAKY-001] retried",
        "  20 passed (4.0m)",
    ])
    assert _failed_test_case_details(output, "") == {
        "failed_test_case_ids": ["E2E-PITCH-001"],
        "unidentified_test_failures": 0,
        "identity_source": "playwright_failed_summary",
    }


def test_incomplete_or_untagged_failure_summary_cannot_claim_complete_identity():
    output = (
        "  3 failed\n"
        "    [chromium] › tests/pitch.spec.ts:1:1 › [echelon:E2E-PITCH-001] pitch\n"
        "    [chromium] › tests/plain.spec.ts:1:1 › no case tag\n"
    )
    assert _failed_test_case_details(output, "")["unidentified_test_failures"] == 2
    assert _failed_test_case_details("Error: [echelon:E2E-PITCH-001]", "") == {}


@pytest.mark.parametrize("output", [
    "  1 failed\n    [chromium] › a.spec.ts:1:1 › [echelon:E2E-A-001] first\n"
    "  1 failed\n    [chromium] › b.spec.ts:1:1 › [echelon:E2E-B-001] second\n",
    "  1 failed\n    [chromium] › a.spec.ts:1:1 › [echelon:E2E-A-001] first\n"
    "    [chromium] › b.spec.ts:1:1 › [echelon:E2E-B-001] second\n",
])
def test_conflicting_summary_counts_do_not_claim_complete_failure_identity(output):
    details = _failed_test_case_details(output, "")
    assert not details or details["unidentified_test_failures"] > 0


def test_failed_case_extraction_supports_shared_comma_separated_tag_contract():
    output = "  1 failed\n    [chromium] › a.spec.ts:1:1 › case [echelon:E2E-A-001,E2E-B-001]\n"
    details = _failed_test_case_details(output, "")
    assert details["failed_test_case_ids"] == ["E2E-A-001", "E2E-B-001"]
    assert details["unidentified_test_failures"] == 0


def test_unittest_final_failure_block_supplies_tagged_repair_identity():
    output = "\n".join([
        "test_divide (test_app.DivisionTest.test_divide) ... FAIL",
        "Error: unrelated [echelon:TC-NOISE-001] log mention",
        "",
        "======================================================================",
        "FAIL: test_divide (test_app.DivisionTest.test_divide)",
        "[echelon:TC-001] divides numbers",
        "----------------------------------------------------------------------",
        "Traceback (most recent call last):",
        "AssertionError: 20 != 5",
        "",
        "----------------------------------------------------------------------",
        "Ran 1 test in 0.000s",
        "",
        "FAILED (failures=1)",
    ])

    assert _failed_test_case_details("", output) == {
        "failed_test_case_ids": ["TC-001"],
        "unidentified_test_failures": 0,
        "identity_source": "unittest_failed_summary",
    }


def test_unittest_untagged_failure_retains_uncertainty():
    output = "\n".join([
        "======================================================================",
        "FAIL: test_divide (test_app.DivisionTest.test_divide)",
        "division test without a case tag",
        "----------------------------------------------------------------------",
        "AssertionError: 20 != 5",
        "Ran 1 test in 0.000s",
        "FAILED (failures=1)",
    ])

    assert _failed_test_case_details("", output) == {
        "failed_test_case_ids": [],
        "unidentified_test_failures": 1,
        "identity_source": "unittest_failed_summary",
    }


@pytest.mark.parametrize("suffix", [
    "",  # A failure block without the final summary is not authoritative.
    "FAILED (failures=1)\nFAILED (failures=1)",
    "  1 failed\n    [chromium] › tests/test_app.py:1:1 › [echelon:TC-001] divide\n"
    "FAILED (failures=1)",
])
def test_unittest_missing_or_conflicting_final_summary_cannot_authorize_repair(suffix):
    output = "\n".join([
        "======================================================================",
        "FAIL: test_divide (test_app.DivisionTest.test_divide)",
        "[echelon:TC-001] divides numbers",
        "----------------------------------------------------------------------",
        suffix,
    ])
    assert _failed_test_case_details("", output) == {}


def test_unittest_mismatched_failure_count_does_not_claim_complete_identity():
    output = "\n".join([
        "======================================================================",
        "FAIL: test_divide (test_app.DivisionTest.test_divide)",
        "[echelon:TC-001] divides numbers",
        "----------------------------------------------------------------------",
        "Ran 2 tests in 0.000s",
        "FAILED (failures=2)",
    ])
    details = _failed_test_case_details("", output)
    assert details["failed_test_case_ids"] == ["TC-001"]
    assert details["unidentified_test_failures"] > 0


def test_unittest_malformed_extra_tag_cannot_authorize_partial_identity():
    output = "\n".join([
        "======================================================================",
        "FAIL: test_divide (test_app.DivisionTest.test_divide)",
        "[echelon:TC-001] divides [echelon:",
        "----------------------------------------------------------------------",
        "Ran 1 test in 0.000s",
        "FAILED (failures=1)",
    ])
    details = _failed_test_case_details("", output)
    assert details["unidentified_test_failures"] == 1


def test_unittest_truncated_failure_header_cannot_use_tag_from_traceback():
    output = "\n".join([
        "======================================================================",
        "FAIL: test_divide (test_app.DivisionTest.test_divide)",
        "Traceback mentions [echelon:TC-001] but has no result separator",
        "Ran 1 test in 0.000s",
        "FAILED (failures=1)",
    ])
    details = _failed_test_case_details("", output)
    assert details["unidentified_test_failures"] == 1


def test_unittest_error_block_with_tag_has_exact_identity():
    output = "\n".join([
        "======================================================================",
        "ERROR: test_divide (test_app.DivisionTest.test_divide)",
        "[echelon:TC-001] divides numbers",
        "----------------------------------------------------------------------",
        "RuntimeError: broken",
        "Ran 1 test in 0.000s",
        "FAILED (errors=1)",
    ])
    assert _failed_test_case_details("", output) == {
        "failed_test_case_ids": ["TC-001"],
        "unidentified_test_failures": 0,
        "identity_source": "unittest_failed_summary",
    }


def test_playwright_final_summary_wins_over_nested_unittest_output():
    output = "\n".join([
        "FAILED (failures=1)",
        "  1 failed",
        "    [chromium] › tests/pitch.spec.ts:1:1 › [echelon:E2E-PITCH-001] pitch",
    ])
    assert _failed_test_case_details(output, "") == {
        "failed_test_case_ids": ["E2E-PITCH-001"],
        "unidentified_test_failures": 0,
        "identity_source": "playwright_failed_summary",
    }


def test_explicit_playwright_command_uses_its_stdout_summary_over_nested_unittest_stderr():
    playwright = "\n".join([
        "  1 failed",
        "    [chromium] › tests/pitch.spec.ts:1:1 › [echelon:E2E-PITCH-001] pitch",
    ])
    nested_unittest = "\n".join([
        "Ran 1 test in 0.000s",
        "FAILED (failures=1)",
    ])

    assert _failed_test_case_details(
        playwright, nested_unittest, command="npx playwright test",
    ) == {
        "failed_test_case_ids": ["E2E-PITCH-001"],
        "unidentified_test_failures": 0,
        "identity_source": "playwright_failed_summary",
    }


def test_competing_stream_summaries_without_runner_hint_remain_ambiguous():
    playwright = "  1 failed\n    [chromium] › a.spec.ts:1:1 › [echelon:E2E-001] a\n"
    nested_unittest = "Ran 1 test in 0.000s\nFAILED (failures=1)\n"
    assert _failed_test_case_details(playwright, nested_unittest) == {}


def test_runner_hint_requires_an_executed_runner_not_an_incidental_argument():
    playwright = "  1 failed\n    [chromium] › a.spec.ts:1:1 › [echelon:E2E-001] a\n"
    unittest = "\n".join([
        "======================================================================",
        "FAIL: test_a (test_app.TestA.test_a)",
        "[echelon:TC-001] a",
        "----------------------------------------------------------------------",
        "Ran 1 test in 0.000s",
        "FAILED (failures=1)",
    ])

    assert _failed_test_case_details(
        playwright, unittest, command="python -m unittest --pattern playwright",
    ) == {
        "failed_test_case_ids": ["TC-001"],
        "unidentified_test_failures": 0,
        "identity_source": "unittest_failed_summary",
    }


@pytest.mark.parametrize("command", [
    "python runner.py -m unittest",
    "python -c 'pass' -m unittest",
    "python -- runner.py -m unittest",
])
def test_runner_hint_does_not_treat_script_arguments_as_python_modules(command):
    playwright = "  1 failed\n    [chromium] › a.spec.ts:1:1 › [echelon:E2E-001] a\n"
    nested_unittest = "Ran 1 test in 0.000s\nFAILED (failures=1)\n"

    assert _failed_test_case_details(
        playwright, nested_unittest, command=command,
    ) == {}


def test_unittest_claim_without_terminal_run_footer_cannot_select_repair():
    output = "\n".join([
        "======================================================================",
        "FAIL: test_divide (test_app.DivisionTest.test_divide)",
        "[echelon:TC-001] divides numbers",
        "----------------------------------------------------------------------",
        "FAILED (failures=1)",
    ])
    assert _failed_test_case_details("", output) == {}


def test_unittest_failure_kind_must_match_terminal_count():
    output = "\n".join([
        "======================================================================",
        "ERROR: test_divide (test_app.DivisionTest.test_divide)",
        "[echelon:TC-001] divides numbers",
        "----------------------------------------------------------------------",
        "Ran 1 test in 0.000s",
        "FAILED (failures=1)",
    ])
    details = _failed_test_case_details("", output)
    assert details["unidentified_test_failures"] > 0


@pytest.mark.parametrize("tags", [
    "[echelon:E2E-A-001] [echelon:bad]",
    "[echelon:E2E-A-001] [echelon:",
    "[echelon:E2E-A-001,]",
])
def test_malformed_extra_tags_do_not_authorize_partial_ownership(tags):
    details = _failed_test_case_details(f"  1 failed\n    [chromium] › a.spec.ts:1:1 › {tags}\n", "")
    assert details["unidentified_test_failures"] == 1



def test_failure_excerpt_keeps_early_timeout_and_cleanup_context() -> None:
    output = "\n".join(
        ["passing test output"] * 1200
        + [
            "[chromium] tests/concurrent-sessions.spec.ts:4 Test timeout of 60000ms exceeded.",
            "Error: Object with guid response@abc was not bound in the connection",
        ]
        + ["late framework warning"] * 1200
    )

    excerpt = _failure_excerpt(output, "")

    assert "Test timeout of 60000ms exceeded" in excerpt
    assert "Object with guid response@abc" in excerpt
    assert "late framework warning" in excerpt
    assert len(excerpt) <= 4_000
