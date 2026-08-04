"""Strict JSON decoder tests."""

from __future__ import annotations

import pytest


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_strict_json_rejects_nonfinite_constants(constant: str) -> None:
    from echelon.strict_json import loads_strict_json

    with pytest.raises(ValueError, match="non-finite JSON constant"):
        loads_strict_json('{"value": ' + constant + "}")
