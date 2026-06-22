"""Depth metric: explicit lexicon DEPENDS links count as cross-references.

The `understanding` requirement extractor flattens each lexicon REQ block to a
prose GIVEN/WHEN/THEN sentence and drops the OUTPUT/DEPENDS/CONSTRAINT lines, so
inter-requirement links expressed via `DEPENDS:` never reached the
cross-reference index. The depth analyzer now reads DEPENDS lines from the full
spec text directly, so an explicitly-linked spec scores a non-zero CRI.
"""

import pytest

from understanding.depth_metrics import DepthAnalyzer

# Flattened requirement prose, as understanding.extract_requirements produces
# (no IDs survive the flattening — mirrors the real lexicon-spec behaviour).
REQUIREMENTS = [
    "Given run dirs exist, when the developer opens the catalog, the catalog MUST list every run",
    "Given an active-run pointer, when the developer views the catalog, the active run MUST be distinguished",
    "Given many runs, when the developer filters by status, the catalog MUST show only matching runs",
]

SPEC_NO_DEPENDS = """ARTIFACT: SPEC
TITLE: Catalog
REQ: FR-001
OUTPUT: a run catalog
REQ: FR-002
OUTPUT: an active-run indicator
DEPENDS: none
REQ: FR-003
OUTPUT: a filtered list
DEPENDS: none
"""

SPEC_WITH_DEPENDS = """ARTIFACT: SPEC
TITLE: Catalog
REQ: FR-001
OUTPUT: a run catalog
DEPENDS: none
REQ: FR-002
OUTPUT: an active-run indicator
DEPENDS: FR-001
REQ: FR-003
OUTPUT: a filtered list
DEPENDS: FR-001, FR-002
"""


@pytest.mark.unit
def test_depends_links_raise_cross_reference_index():
    analyzer = DepthAnalyzer()
    without = analyzer.analyze(REQUIREMENTS, SPEC_NO_DEPENDS)
    with_deps = analyzer.analyze(REQUIREMENTS, SPEC_WITH_DEPENDS)
    assert without.cross_reference_index == 0.0
    assert with_deps.cross_reference_index > 0.0
    # 3 referenced IDs (FR-001 once, FR-001+FR-002) across 3 reqs lifts depth too.
    assert with_deps.depth_score > without.depth_score


@pytest.mark.unit
def test_depends_none_is_not_a_cross_reference():
    analyzer = DepthAnalyzer()
    result = analyzer.analyze(REQUIREMENTS, SPEC_NO_DEPENDS)
    assert result.cross_reference_index == 0.0
