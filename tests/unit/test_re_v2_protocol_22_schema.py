from __future__ import annotations

import pytest

from harness.re_v2.protocol_22.schema import Protocol22SchemaError, safe_relative_path


@pytest.mark.unit
def test_safe_relative_path_accepts_hidden_source_segments() -> None:
    assert (
        safe_relative_path(".echelon/config.yml", "source path")
        == ".echelon/config.yml"
    )
    assert safe_relative_path(".github/workflows/ci.yml", "source path") == (
        ".github/workflows/ci.yml"
    )


@pytest.mark.unit
@pytest.mark.parametrize("relative", (".", "..", "src/../secret", ".hidden/.."))
def test_safe_relative_path_still_rejects_navigation(relative: str) -> None:
    with pytest.raises(Protocol22SchemaError, match="normalized relative path"):
        safe_relative_path(relative, "source path")
