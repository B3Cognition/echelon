"""Regression coverage for reused and renumbered SAGE findings."""
import pytest

from harness.issue_identity import (
    issue_fingerprint,
    matching_issue_resolution,
    record_issue_resolution,
)


BODY = """- **Severity:** HIGH
- **Description:** Discovery records contradict the resolved feature evidence.
- **Affected artifact:** mental-model.md
- **Affected section:** Source Gaps
- **Evidence:** The shared seed is established in evidence-resolution.md.
- **Action Required:** Reconcile the mental model.

### Resolution Guidance
- **Decision required:** No user decision — agent repair
- **Suggested option:** Record the resolved shared-seed lifecycle.
- **Evidence basis:** Evidence resolution U-004.
- **Banzai eligible:** yes

## Certified Evidence Interpretation
- Iteration 5 passed all numeric gates.
"""


def test_renumbering_whitespace_and_report_footer_do_not_reopen_a_finding():
    identity = issue_fingerprint("ISS-001: Stale model", BODY)
    revised = BODY.replace("shared seed", "shared   seed").replace("Iteration 5", "Iteration 6")
    assert issue_fingerprint("ISS-017: Stale model", revised) == identity
    ledger = {"ISS-001": {"status": "validated", "issue_fingerprint": identity}}
    assert matching_issue_resolution(ledger, issue_fingerprint("Stale model", revised))["status"] == "validated"


@pytest.mark.parametrize("before,after", [
    ("mental-model.md", "boundaries.md"),
    ("Source Gaps", "Behavioral Patterns"),
    ("The shared seed is established", "The per-session seed is established"),
    ("Reconcile the mental model.", "Reconcile the boundaries."),
    ("Evidence resolution U-004.", "Evidence resolution U-008."),
])
def test_changed_finding_does_not_inherit_a_validated_resolution(before, after):
    original = issue_fingerprint("ISS-001: Stale model", BODY)
    ledger = {"ISS-001": {"status": "validated", "issue_fingerprint": original}}
    changed = issue_fingerprint("ISS-001: Stale model", BODY.replace(before, after))
    assert not matching_issue_resolution(ledger, changed)


def test_legacy_issue_number_alone_cannot_hide_current_evidence():
    ledger = {"ISS-001": {"status": "validated", "title": "Stale model"}}
    assert not matching_issue_resolution(ledger, issue_fingerprint("ISS-001: Stale model", BODY))


def test_reusing_an_id_preserves_history_and_can_recognize_an_older_resolution():
    first = {"issue_fingerprint": "first", "status": "validated"}
    second = {"issue_fingerprint": "second", "status": "validated"}
    original = {"ISS-001": first}
    ledger = record_issue_resolution(original, "ISS-001", second)
    ledger = record_issue_resolution(ledger, "ISS-001", {"issue_fingerprint": "third", "status": "selected"})
    assert ledger["ISS-001"]["previous_resolutions"] == [first, second]
    assert matching_issue_resolution(ledger, "first") == first
    assert original == {"ISS-001": first}


def test_superseded_unvalidated_selection_does_not_suppress_a_finding():
    ledger = record_issue_resolution(
        {"ISS-001": {"issue_fingerprint": "old", "status": "selected"}},
        "ISS-001", {"issue_fingerprint": "new", "status": "selected"},
    )
    assert not matching_issue_resolution(ledger, "old")


def test_current_selection_takes_precedence_over_historical_validation():
    current = {"issue_fingerprint": "same", "status": "selected"}
    ledger = {
        "ISS-001": {"issue_fingerprint": "different", "status": "selected",
                    "previous_resolutions": [{"issue_fingerprint": "same", "status": "validated"}]},
        "ISS-002": current,
    }
    assert matching_issue_resolution(ledger, "same") == current
