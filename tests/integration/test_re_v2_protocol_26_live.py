from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

import pytest

from tests.integration.test_re_v2_protocol_22_live import _git_state
from tests.support.re_v2_layered_workspace import build_and_commit_fixture


@pytest.mark.integration
@pytest.mark.live
@pytest.mark.skipif(
    os.environ.get("ECHELON_RUN_LIVE_CODEX") != "1"
    or shutil.which("codex") is None
    or shutil.which("echelon") is None,
    reason="set ECHELON_RUN_LIVE_CODEX=1 with installed codex and echelon CLIs",
)
def test_installed_codex_adopts_self_contained_protocol_26_sibling(
    tmp_path: Path,
) -> None:
    from harness.re_v2.events import EventStore
    from harness.re_v2.protocol_26.events import protocol_26_events_for
    from harness.re_v2.protocol_26.model import RunManifestV5
    from harness.re_v2.protocol_26.status import protocol_26_status_document
    from harness.re_v2.run_store import ReV2Paths, load_run_manifest

    fixture = build_and_commit_fixture(tmp_path, "live-codex")
    source = fixture.root / "sources" / "api"
    source_git_before = _git_state(source)
    environment = {
        **os.environ,
        "ECHELON_HOME": str(tmp_path / "echelon-home"),
        "ECHELON_LLM": "codex",
    }
    _run(
        ["echelon", "workspace", "migrate-to-prosaic"],
        fixture.root,
        environment,
        timeout=180,
    )
    command = [
        "echelon",
        "re",
        "run",
        "--engine",
        "v2",
        "--re-token-limit",
        "2000000",
        "--re-time-limit-minutes",
        "1000",
    ]
    _run(command, fixture.root, environment, timeout=900)
    origin = fixture.run_directories()[0]
    _run(command, fixture.root, environment, timeout=300)
    child = fixture.run_directories()[-1]

    manifest = load_run_manifest(child)
    assert isinstance(manifest, RunManifestV5)
    status = protocol_26_status_document(child)
    assert status["status"] == "complete"
    assert status["checkpoints"]["adopted_count"] == status["artifact_counts"][
        "total"
    ]["accepted"]
    assert status["checkpoints"]["generated_count"] == 0
    events = EventStore(
        ReV2Paths.for_run(child),
        protocol=protocol_26_events_for("L1"),
    ).replay()
    assert not any(event.type == "dispatch_started" for event in events)

    event_bytes = ReV2Paths.for_run(child).events.read_bytes()
    hidden = tmp_path / "hidden-origin"
    shutil.move(origin, hidden)
    shutil.rmtree(fixture.root / ".echelon" / "re-v2" / "checkpoints")
    _run(["echelon", "re", "continue"], fixture.root, environment, timeout=300)
    assert ReV2Paths.for_run(child).events.read_bytes() == event_bytes

    _run(command, fixture.root, environment, timeout=300)
    repeated = fixture.run_directories()[-1]
    repeated_status = protocol_26_status_document(repeated)
    assert repeated_status["checkpoints"]["adopted_count"] == status[
        "checkpoints"
    ]["adopted_count"]
    assert repeated_status["checkpoints"]["generated_count"] == 0
    assert _git_state(source) == source_git_before


def _run(
    command: list[str],
    cwd: Path,
    environment: dict[str, str],
    *,
    timeout: int,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result
