from __future__ import annotations

import pytest

from harness.re_semantic_contract import (
    classify_semantic_finding,
    stable_finding_id,
)


pytestmark = pytest.mark.unit


def test_classifies_observed_md_distribution_findings() -> None:
    assert (
        classify_semantic_finding("The read error propagates uncaught")
        == "error-recovery"
    )
    assert (
        classify_semantic_finding("The public remove operation is unspecified")
        == "public-surface"
    )
    assert (
        classify_semantic_finding("An invalid backupRetention value is omitted")
        == "configuration"
    )


def test_stable_finding_id_ignores_whitespace_but_not_evidence() -> None:
    first = stable_finding_id(
        "error-recovery", "Read  failure", ("`src/a.ts:3`",)
    )
    second = stable_finding_id(
        "error-recovery", "Read failure", ("`src/a.ts:3`",)
    )
    changed = stable_finding_id(
        "error-recovery", "Read failure", ("`src/a.ts:4`",)
    )

    assert first == second
    assert first != changed
