from __future__ import annotations

from pathlib import Path

import pytest

from harness.re_v2.protocol_25.controller import plan_next_protocol_25
from harness.re_v2.protocol_25.materialization import materialize_accepted_l3
from harness.re_v2.protocol_25.recovery import recover_protocol_25_run
from tests.integration.test_re_v2_protocol_25_recovery import (
    _accept_every_audit,
    _accept_every_prerequisite,
    _context,
)


@pytest.mark.unit
def test_l3_materialization_is_run_local_rebuildable_and_quarantines_changes(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path / "run")
    context.event_store.append(
        "run_created",
        {"run_manifest_id": context.semantic_graph.manifest.run_manifest_id},
        occurred_at=context.semantic_graph.manifest.created_at,
    )
    _accept_every_prerequisite(context)
    _accept_every_audit(context)
    for expected in ("freeze_epoch", "accept_roots", "terminal_complete"):
        action = plan_next_protocol_25(
            recover_protocol_25_run(context).controller_state
        )
        assert action is not None and action.kind == expected
        context.apply_controller_action(action)

    first = materialize_accepted_l3(context)
    root = context.paths.root.parent / "re" / "l3"
    epoch_json = root / "epoch.json"
    epoch_markdown = root / "epoch.md"
    source_root = root / "sources" / "api" / "root.json"
    overview = root / "sources" / "api" / "overview.md"

    assert epoch_json in first.paths
    assert epoch_markdown in first.paths
    assert source_root in first.paths
    assert overview in first.paths
    assert not (context.paths.root.parent.parent / "re").exists()
    original_epoch_markdown = epoch_markdown.read_bytes()
    assert b"workspace synthesis: not run" in original_epoch_markdown
    assert b"lower-layer authority remains immutable" in overview.read_bytes()

    epoch_markdown.unlink()
    rebuilt = materialize_accepted_l3(context)
    assert epoch_markdown.read_bytes() == original_epoch_markdown
    assert rebuilt.rebuilt_count == 1

    source_root.chmod(0o600)
    source_root.write_text('{"forged":true}\n')
    repaired = materialize_accepted_l3(context)
    assert repaired.quarantined_count == 1
    assert source_root.read_bytes() != b'{"forged":true}\n'
    assert repaired.quarantine_paths[0].is_file()
