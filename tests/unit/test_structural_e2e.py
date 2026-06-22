"""E2E fixture test: gate-clean feasibility_ok.md passes structural_validate.

Tests that the committed fixture pair (spec_ok.md + feasibility_ok.md) under
tests/fixtures/structural/ satisfies every Tier-2 check in structural_validate:
  - all required H2 sections present and non-empty
  - no angle-bracket placeholder tokens
  - verdict section carries a recognised enum value (PASS/KILL/DEFER)
  - no cross-ref findings (feasibility entry has no cross_refs config)
"""
import pytest
import pathlib

from lexicon.structural import structural_validate
from lexicon.manifest import load_governance

FX = pathlib.Path("tests/fixtures/structural")


@pytest.mark.unit
def test_fixture_feasibility_is_gate_clean():
    entry = load_governance(pathlib.Path("extension/echelon-config.yml"))["feasibility"]
    r = structural_validate(
        (FX / "feasibility_ok.md").read_text(),
        entry,
        (FX / "spec_ok.md").read_text(),
    )
    assert r.ok is True, [f.code for f in r.findings]
