from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor

import pytest

from harness.re_v2.events import EventStore
from harness.re_v2.canonical import content_digest
from harness.re_v2.ledger import ObjectStore
from harness.re_v2.protocol_22.ledger import Protocol22Ledger
from harness.re_v2.protocol_24.events import PROTOCOL_24_EVENTS
from harness.re_v2.protocol_24.model import RunManifestV3
from harness.re_v2.protocol_26.events import protocol_26_events_for
from harness.re_v2.protocol_26.inputs import load_protocol_26_inputs
from harness.re_v2.protocol_26.model import RunManifestV5
from harness.re_v2.run_store import ReV2Paths, load_run_manifest
from tests.integration.test_re_v2_protocol_24_controller import (
    _child_context,
    _completed_parent,
    _registry,
)
from tests.unit.test_re_v2_protocol_24_prosaic import _role_artifact
from tests.unit.test_re_v2_protocol_22_controller import _SnapshotReader


@pytest.mark.integration
def test_deepen_creates_one_manifest_last_child_and_reuses_semantic_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon import cli as legacy_cli

    parent = _completed_parent(tmp_path / "authority", provider_mode="cli")
    workspace = tmp_path / "workspace"
    (workspace / "runs").mkdir(parents=True)
    monkeypatch.setattr(
        "harness.re_v2.protocol_24.adoption.validate_parent_for_deepening",
        lambda _run, _workspace: parent,
    )
    monkeypatch.setattr(
        legacy_cli,
        "ProsaicPromptLoader",
        lambda _workspace: SimpleNamespace(
            load_subagent=lambda _agent_id: _role_artifact()
        ),
    )
    monkeypatch.setattr(
        legacy_cli,
        "_re_schema2_installed_registry",
        lambda agent, *, provider_mode: (_registry(parent), agent, {}),
    )
    contexts: list[Path] = []
    monkeypatch.setattr(
        legacy_cli,
        "_re_v2_context",
        lambda _workspace, run_dir: SimpleNamespace(run_dir=run_dir),
    )
    monkeypatch.setattr(
        legacy_cli,
        "_run_re_v2_live",
        lambda context: contexts.append(context.run_dir),
    )
    options = legacy_cli._parse_re_deepen_options(
        ["--to", "L2", "--source", "api", "--from-run", "re-parent"]
    )

    first = legacy_cli._run_re_v24_deepen(workspace, options)
    second = legacy_cli._run_re_v24_deepen(workspace, options)

    children = tuple(
        path
        for path in (workspace / "runs").iterdir()
        if path.is_dir() and (path / "v2" / "run.json").is_file()
    )
    assert first == second
    assert children == (first,)
    manifest = load_run_manifest(first)
    assert isinstance(manifest, RunManifestV5)
    outer_inputs = load_protocol_26_inputs(ReV2Paths.for_run(first), manifest)
    layer_manifest = outer_inputs.layer_execution_contract.layer_manifest
    assert isinstance(layer_manifest, RunManifestV3)
    assert layer_manifest.parent_run_id == parent.manifest.run_id
    assert layer_manifest.selection.source_ids == ("api",)
    assert (workspace / "runs" / ".current-re").read_text() == first.name + "\n"
    paths = ReV2Paths.for_run(first)
    events = EventStore(paths, protocol=protocol_26_events_for("L2")).replay()
    ledger = Protocol22Ledger(paths, ObjectStore(paths.objects)).replay()
    assert events[0].type == "run_created"
    assert sum(event.type == "artifact_adopted" for event in events) == len(
        parent.inputs.parent_authority_bundle.artifacts
        if hasattr(parent.inputs, "parent_authority_bundle")
        else parent.ledger.accepted_artifacts
    )
    assert ledger.accepted_artifacts == parent.ledger.accepted_artifacts
    assert contexts == [first, first]


@pytest.mark.integration
@pytest.mark.parametrize(
    "boundary",
    (
        "manifest_published",
        "parent_closure_imported",
        "run_created",
        "artifact_adopted:",
        "active_pointer_published",
    ),
)
def test_deepen_creation_faults_recover_the_same_authoritative_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
) -> None:
    from echelon import cli as legacy_cli

    parent = _completed_parent(tmp_path / "authority", provider_mode="cli")
    workspace = tmp_path / "workspace"
    (workspace / "runs").mkdir(parents=True)
    monkeypatch.setattr(
        "harness.re_v2.protocol_24.adoption.validate_parent_for_deepening",
        lambda _run, _workspace: parent,
    )
    monkeypatch.setattr(
        legacy_cli,
        "ProsaicPromptLoader",
        lambda _workspace: SimpleNamespace(
            load_subagent=lambda _agent_id: _role_artifact()
        ),
    )
    monkeypatch.setattr(
        legacy_cli,
        "_re_schema2_installed_registry",
        lambda agent, *, provider_mode: (_registry(parent), agent, {}),
    )
    contexts: list[Path] = []
    monkeypatch.setattr(
        legacy_cli,
        "_re_v2_context",
        lambda _workspace, run_dir: SimpleNamespace(run_dir=run_dir),
    )
    monkeypatch.setattr(
        legacy_cli,
        "_run_re_v2_live",
        lambda context: contexts.append(context.run_dir),
    )
    options = legacy_cli._parse_re_deepen_options(
        ["--to", "L2", "--source", "api", "--from-run", "re-parent"]
    )
    crashed = False

    def fail_once(point: str) -> None:
        nonlocal crashed
        if not crashed and point.startswith(boundary):
            crashed = True
            raise RuntimeError(f"fault at {point}")

    with pytest.raises(RuntimeError, match="fault at"):
        legacy_cli._run_re_v24_deepen(
            workspace,
            options,
            creation_fault_hook=fail_once,
        )
    assert crashed

    recovered = legacy_cli._run_re_v24_deepen(workspace, options)
    manifest = load_run_manifest(recovered)
    assert isinstance(manifest, RunManifestV5)
    paths = ReV2Paths.for_run(recovered)
    events = EventStore(paths, protocol=protocol_26_events_for("L2")).replay()
    ledger = Protocol22Ledger(paths, ObjectStore(paths.objects)).replay()

    assert (workspace / "runs" / ".current-re").read_text() == recovered.name + "\n"
    assert events[0].type == "run_created"
    assert sum(event.type == "run_created" for event in events) == 1
    assert sum(event.type == "artifact_adopted" for event in events) == len(
        parent.ledger.accepted_artifacts
    )
    assert ledger.accepted_artifacts == parent.ledger.accepted_artifacts
    assert contexts == [recovered]


@pytest.mark.integration
def test_deepen_preflight_failure_creates_no_child_or_active_pointer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon import cli as legacy_cli
    from harness.re_v2.protocol_24.adoption import Protocol24AdoptionError

    workspace = tmp_path / "workspace"
    (workspace / "runs").mkdir(parents=True)
    monkeypatch.setattr(
        "harness.re_v2.protocol_24.adoption.validate_parent_for_deepening",
        lambda _run, _workspace: (_ for _ in ()).throw(
            Protocol24AdoptionError(
                "sources must be clean; Commit, stash, or revert before retrying"
            )
        ),
    )
    options = legacy_cli._parse_re_deepen_options(
        ["--to", "L2", "--all", "--from-run", "re-parent"]
    )

    with pytest.raises(Protocol24AdoptionError, match="Commit, stash, or revert"):
        legacy_cli._run_re_v24_deepen(workspace, options)

    assert tuple((workspace / "runs").iterdir()) == ()


@pytest.mark.integration
def test_schema3_context_dispatches_to_protocol24_builder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon import cli as legacy_cli

    child, _provider = _child_context(tmp_path, paused=True, provider_mode="cli")
    marker = object()
    calls: list[tuple[Path, Path, object]] = []

    def build(project_root: Path, run_dir: Path, manifest: object) -> object:
        calls.append((project_root, run_dir, manifest))
        return marker

    monkeypatch.setattr(legacy_cli, "_re_v24_context", build)

    result = legacy_cli._re_v2_context(tmp_path, child.paths.root.parent)

    assert result is marker
    assert calls[0][0:2] == (tmp_path, child.paths.root.parent)
    assert isinstance(calls[0][2], RunManifestV3)


@pytest.mark.integration
def test_schema3_live_execution_uses_protocol24_controller(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from echelon import cli as legacy_cli

    context, _provider = _child_context(tmp_path, paused=True, provider_mode="cli")
    calls: list[object] = []

    class Controller:
        def __init__(self, received: object) -> None:
            assert received is context

        def run_until_stopped(self) -> object:
            calls.append(context)
            return SimpleNamespace(status="paused")

    monkeypatch.setattr(
        "harness.re_v2.protocol_24.controller.Protocol24Controller",
        Controller,
    )

    legacy_cli._run_re_v2_live(context)

    assert calls == [context]
    assert "PROTOCOL 2.4" in capsys.readouterr().out


@pytest.mark.integration
def test_protocol24_context_rebuilds_only_from_child_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon import cli as legacy_cli

    original, _provider = _child_context(tmp_path, paused=True, provider_mode="cli")
    manifest = load_run_manifest(original.paths.root.parent)
    payloads = {
        (source.source_id, record.source_relative_path): b"print('ok')\n"
        for source in original.inputs.workspace_partition.sources
        for record in source.files
    }
    reader = _SnapshotReader(original.inputs.workspace_partition, payloads)
    monkeypatch.setattr(legacy_cli, "_load_re_v2_snapshot", lambda *_args: object())
    monkeypatch.setattr(
        "harness.re_v2.protocol_22.evidence.PinnedSnapshotReaderV1",
        lambda _snapshot, _partition: reader,
    )
    monkeypatch.setattr(
        "harness.re_v2.snapshot.validate_source_snapshot",
        lambda _snapshot: None,
    )
    registry_parent = _completed_parent(tmp_path / "registry-parent", provider_mode="cli")
    monkeypatch.setattr(
        legacy_cli,
        "_re_schema2_installed_registry",
        lambda agent, *, provider_mode: (_registry(registry_parent), agent, {}),
    )
    monkeypatch.setattr(
        legacy_cli,
        "_re_v22_implementation_digest",
        lambda *_modules: content_digest(b"protocol-2.4 test runtime"),
    )

    rebuilt = legacy_cli._re_v24_context(
        tmp_path,
        original.paths.root.parent,
        manifest,
    )

    assert rebuilt.graph == original.graph
    assert rebuilt.event_store.protocol is PROTOCOL_24_EVENTS
    assert "compact-deepening" not in rebuilt.producers
    assert "targeted-evidence-pack" in rebuilt.producers
    assert tuple(rebuilt.executors) == ("shared-ai-cli-baseline-v1",)


@pytest.mark.integration
def test_semantic_child_budget_increase_reuses_paused_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon import cli as legacy_cli

    context, _provider = _child_context(tmp_path, paused=True, provider_mode="cli")
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        legacy_cli,
        "_run_re_v22_continue",
        lambda _context, **kwargs: calls.append(kwargs),
    )
    options = legacy_cli._parse_re_deepen_options(
        [
            "--to",
            "L2",
            "--all",
            "--token-limit",
            "2000000",
            "--active-ms-limit",
            "7200000",
        ]
    )

    legacy_cli._continue_re_v24_semantic_child(context, options)

    assert calls == [
        {
            "token_limit": 2_000_000,
            "time_limit_minutes": None,
            "active_ms_limit": 7_200_000,
        }
    ]


@pytest.mark.integration
def test_concurrent_semantic_creation_publishes_one_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon import cli as legacy_cli

    parent = _completed_parent(tmp_path / "authority", provider_mode="cli")
    workspace = tmp_path / "workspace"
    (workspace / "runs").mkdir(parents=True)
    monkeypatch.setattr(
        "harness.re_v2.protocol_24.adoption.validate_parent_for_deepening",
        lambda _run, _workspace: parent,
    )
    monkeypatch.setattr(
        legacy_cli,
        "ProsaicPromptLoader",
        lambda _workspace: SimpleNamespace(
            load_subagent=lambda _agent_id: _role_artifact()
        ),
    )
    monkeypatch.setattr(
        legacy_cli,
        "_re_schema2_installed_registry",
        lambda agent, *, provider_mode: (_registry(parent), agent, {}),
    )
    monkeypatch.setattr(
        legacy_cli,
        "_re_v2_context",
        lambda _workspace, run_dir: SimpleNamespace(run_dir=run_dir),
    )
    monkeypatch.setattr(legacy_cli, "_run_re_v2_live", lambda _context: None)
    options = legacy_cli._parse_re_deepen_options(
        ["--to", "L2", "--source", "api", "--from-run", "re-parent"]
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(
            executor.map(
                lambda _index: legacy_cli._run_re_v24_deepen(workspace, options),
                range(2),
            )
        )

    assert results[0] == results[1]
    assert len(
        tuple(
            path
            for path in (workspace / "runs").iterdir()
            if path.is_dir() and (path / "v2" / "run.json").is_file()
        )
    ) == 1
