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
