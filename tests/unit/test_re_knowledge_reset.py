"""Recovery from stopped discovery without selecting legacy RE or deleting data."""
import json

import pytest

from echelon.cli import _parse_re_knowledge_action_options, _require_re_reset_stopped
from harness.re_v2.ledger import ObjectStore
from harness.re_v2.canonical import canonical_json_bytes

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("state", ["blocked", "proposal_ready"])
def test_reset_only_accepts_stopped_discovery(tmp_path, state):
    root = tmp_path / "v2"
    root.mkdir()
    (root / "knowledge-creation.json").write_text("{}")
    objects = ObjectStore(root / "objects")
    receipt = objects.put_blob(canonical_json_bytes({"state": state, "reason_code": "provider-failed"}))
    ledger = root / "knowledge-dispatch.jsonl"
    ledger.write_text(json.dumps({"type": "discovery_applied", "payload": {"receipt_id": receipt}}) + "\n")
    before = ledger.read_bytes()
    if state == "blocked":
        _require_re_reset_stopped(tmp_path)
    else:
        with pytest.raises(ValueError, match="confirmed stopped outcome"):
            _require_re_reset_stopped(tmp_path)
    assert ledger.read_bytes() == before


def test_reset_rejects_active_legacy_run(tmp_path):
    (tmp_path / "state.json").write_text('{"status":"running"}')
    with pytest.raises(ValueError, match="confirmed stopped outcome"):
        _require_re_reset_stopped(tmp_path)


def test_reset_is_only_valid_for_run():
    assert _parse_re_knowledge_action_options(["--reset"], allow_sources=False).reset
    with pytest.raises(ValueError, match="unknown option"):
        _parse_re_knowledge_action_options(["--reset"], allow_sources=True)
    with pytest.raises(ValueError, match="only once"):
        _parse_re_knowledge_action_options(["--reset", "--reset"], allow_sources=False)
