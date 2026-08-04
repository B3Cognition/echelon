from __future__ import annotations

import pytest

from harness.re_source_evidence import source_references


pytestmark = pytest.mark.unit


@pytest.mark.parametrize("separator", ["–", "—"])
def test_source_references_accepts_unicode_line_range_separator(separator: str) -> None:
    reference = f"`src/io.ts:4{separator}12`"

    assert source_references(reference) == (reference,)
