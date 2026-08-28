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
def test_installed_codex_completes_and_exactly_reuses_l3_pilot(
    tmp_path: Path,
) -> None:
    from harness.prosaic_prompt_loader import ProsaicPromptLoader
    from harness.re_v2.ledger import ObjectStore
    from harness.re_v2.protocol_22.provider import canonical_prosaic_agent_bytes
    from harness.re_v2.protocol_26.inputs import load_protocol_26_inputs
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
    loader = ProsaicPromptLoader(fixture.root)
    validator = loader.load_subagent("echelon.re-validator")
    resolver = loader.load_subagent("echelon.re-resolver")
    assert validator is not None and resolver is not None
    role_bytes = {
        "echelon.re-validator": canonical_prosaic_agent_bytes(validator),
        "echelon.re-resolver": canonical_prosaic_agent_bytes(resolver),
    }

    baseline = _run(
        [
            "echelon",
            "re",
            "run",
            "--engine",
            "v2",
            "--re-token-limit",
            "2000000",
            "--re-time-limit-minutes",
            "1000",
        ],
        fixture.root,
        environment,
        timeout=1800,
    )
    assert "L1 COMPACT BASELINE COMPLETE" in baseline.stdout
    l1 = _only_run(fixture.root, layer="L1")
    deepen_l2 = _run(
        [
            "echelon",
            "re",
            "deepen",
            "--to",
            "L2",
            "--all",
            "--from-run",
            l1.name,
            "--token-limit",
            "2000000",
            "--active-ms-limit",
            "60000000",
        ],
        fixture.root,
        environment,
        timeout=1800,
    )
    assert "L2 SELECTED SCOPE COMPLETE" in deepen_l2.stdout
    l2 = _only_run(fixture.root, layer="L2")
    l3_command = [
        "echelon",
        "re",
        "deepen",
        "--to",
        "L3",
        "--all",
        "--from-run",
        l2.name,
        "--token-limit",
        "4400000",
        "--active-ms-limit",
        "120000000",
        "--semantic-token-limit",
        "4400000",
        "--semantic-active-ms-limit",
        "120000000",
    ]
    deepen_l3 = _run(
        l3_command,
        fixture.root,
        environment,
        timeout=2400,
    )
    assert "L3 SELECTED SCOPE COMPLETE" in deepen_l3.stdout
    l3 = _only_run(fixture.root, layer="L3")
    paths = ReV2Paths.for_run(l3)
    dispatches_before = _dispatch_count(paths)
    repeated = _run(
        l3_command,
        fixture.root,
        environment,
        timeout=300,
    )
    assert "L3 SELECTED SCOPE COMPLETE" in repeated.stdout
    assert _dispatch_count(paths) == dispatches_before

    manifest = load_run_manifest(l3)
    assert isinstance(manifest, RunManifestV5)
    objects = ObjectStore(paths.objects)
    inputs = load_protocol_26_inputs(paths, manifest).layer_inputs
    for family, role_id in (
        ("semantic-audit", "echelon.re-validator"),
        ("semantic-resolution", "echelon.re-resolver"),
    ):
        renderer = inputs.executor_contract.entry_for(family).request_renderer
        assert renderer is not None
        assert objects.read_blob(renderer.agent_contract_hash) == role_bytes[role_id]

    status = protocol_26_status_document(l3)
    assert status["status"] == "complete"
    assert status["banner"] == "L3 SELECTED SCOPE COMPLETE"
    assert status["selection"]["selected_domains"] >= 2
    assert status["semantic"]["unresolved_audit_targets"] == 0
    assert status["not_run"] == {
        "exhaustive_re_l4": "not run",
        "workspace_synthesis": "not run",
    }
    assert dispatches_before >= status["selection"]["selected_domains"] + 1
    assert (l3 / "re" / "l3" / "epoch.json").is_file()
    assert (l3 / "re" / "l3" / "sources" / "api" / "root.json").is_file()
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


def _only_run(workspace: Path, *, layer: str) -> Path:
    from harness.re_v2.protocol_26.model import RunManifestV5
    from harness.re_v2.run_store import load_run_manifest

    matches = tuple(
        path
        for path in workspace.joinpath("runs").glob("re-*")
        if isinstance((manifest := load_run_manifest(path)), RunManifestV5)
        and manifest.target_layer == layer
    )
    assert len(matches) == 1
    return matches[0]


def _dispatch_count(paths: object) -> int:
    from harness.re_v2.events import EventStore
    from harness.re_v2.protocol_26.events import protocol_26_events_for

    return sum(
        event.type == "dispatch_started"
        for event in EventStore(
            paths, protocol=protocol_26_events_for("L3")
        ).replay()
    )
