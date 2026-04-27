"""Unit tests for MemPalaceReader with MemPalaceContext."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from codegen.memory.context import MemPalaceContext
from codegen.memory.mempalace_reader import MemPalaceReader


def _make_ctx(wing="my-app", palace_path="/fake/palace"):
    return MemPalaceContext(wing=wing, run_id="r1", palace_path=palace_path)


def _empty_query_result():
    return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}


def test_reader_accepts_ctx():
    ctx = _make_ctx()
    reader = MemPalaceReader(ctx)
    assert reader.wing == "my-app"


def test_reader_uses_palace_path_from_ctx():
    ctx = _make_ctx(palace_path="/custom/palace")
    reader = MemPalaceReader(ctx)

    mock_col = MagicMock()
    mock_col.query.return_value = _empty_query_result()

    with patch("codegen.memory.mempalace_reader.get_collection", return_value=mock_col) as mock_get:
        reader.search("test query")

    mock_get.assert_called_once_with("/custom/palace")


def test_reader_filters_by_wing_from_ctx():
    ctx = _make_ctx(wing="scoped-wing")
    reader = MemPalaceReader(ctx)

    mock_col = MagicMock()
    mock_col.query.return_value = _empty_query_result()

    with patch("codegen.memory.mempalace_reader.get_collection", return_value=mock_col):
        reader.search("test")

    call_kwargs = mock_col.query.call_args.kwargs
    where = call_kwargs.get("where", {})
    assert where == {"wing": {"$eq": "scoped-wing"}}


def test_reader_returns_unavailable_when_get_collection_is_none():
    ctx = _make_ctx()
    with patch("codegen.memory.mempalace_reader.get_collection", None):
        reader = MemPalaceReader(ctx)
        result = reader.search("test")

    assert result.available is False
    assert result.drawers == []


def test_reader_returns_unavailable_on_collection_exception():
    ctx = _make_ctx()
    reader = MemPalaceReader(ctx)

    with patch("codegen.memory.mempalace_reader.get_collection", side_effect=Exception("db error")):
        result = reader.search("test")

    assert result.available is False
    assert result.drawers == []
