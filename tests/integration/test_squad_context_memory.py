"""Integration coverage for Squad Phase 4 canonical context publication."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
import subprocess
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

EXT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(EXT_ROOT) not in sys.path:
    sys.path.insert(0, str(EXT_ROOT))

from echelon.context_metadata import artifact_hash, read_feature_metadata
from harness.phase_graph import PhaseGraph
from harness.squad import SquadController
from harness.squad_provider import SquadAgentResult
from harness.squad_state import SquadStateStore

DEFINITION = EXT_ROOT / "runtime/workflow/definition.yaml"
PROSAIC_SUBAGENTS = EXT_ROOT / "prosaic/subagents"


def _valid_plan_conformance_json() -> str:
    return json.dumps(
        {
            "status": "pass",
            "findings": [],
            "sources": [
                "spec.md",
                "requirements-overview.md",
                "plan.md",
                "tasks.md",
            ],
        },
        indent=2,
    ) + "\n"


def _ensure_git_repo(project_root: Path) -> None:
    if (project_root / ".git").exists():
        return
    subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=project_root,
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "config", "user.name", "Echelon Tests"], cwd=project_root, check=True)
    subprocess.run(
        ["git", "config", "user.email", "echelon@example.test"],
        cwd=project_root,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "base"],
        cwd=project_root,
        check=True,
        capture_output=True,
    )


def _mock_provider() -> MagicMock:
    provider = MagicMock()
    provider.exec_agent.return_value = SquadAgentResult(
        exit_code=0,
        echelon_result={"verdict": "DONE", "state_updates": {}},
        raw_output="",
        duration_ms=100,
        timed_out=False,
    )
    return provider


def _controller(tmp_path: Path, provider: MagicMock | None = None) -> tuple[SquadController, SquadStateStore]:
    _ensure_git_repo(tmp_path)
    squad_dir = tmp_path / "runs" / "run-test"
    squad_dir.mkdir(parents=True, exist_ok=True)
    (squad_dir / "staging").mkdir(exist_ok=True)
    graph = PhaseGraph(DEFINITION, prosaic_subagents_dir=PROSAIC_SUBAGENTS)
    store = SquadStateStore(squad_dir)
    ctrl = SquadController(
        provider=provider or _mock_provider(),
        state_store=store,
        phase_graph=graph,
        ext_dir=EXT_ROOT / "extension",
        project_root=tmp_path,
        token_budget=0,
        squad_dir=squad_dir,
    )
    return ctrl, store


def _mark_constitution_complete(project_root: Path, store: SquadStateStore) -> None:
    const_path = project_root / ".specify" / "memory" / "constitution.md"
    const_path.parent.mkdir(parents=True, exist_ok=True)
    const_path.write_text("# Constitution\n\nReal project rules.\n", encoding="utf-8")
    state = store.load()
    completed = state.get("completed_phases")
    completed_phases = completed if isinstance(completed, list) else []
    if "phase1-constitution" not in completed_phases:
        completed_phases.append("phase1-constitution")
    state["completed_phases"] = completed_phases
    store.save(state)


def _disable_lexicon_gate(project_root: Path) -> None:
    config_path = project_root / ".echelon" / "config.yml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("lexicon_gate:\n  enabled: false\n", encoding="utf-8")


def test_finalize_published_spec_metadata_can_be_generated(tmp_path: Path) -> None:
    spec_dir = tmp_path / "specs" / "001-photo-album"
    spec_dir.mkdir(parents=True)
    spec_file = spec_dir / "spec.md"
    spec_file.write_text("FR-001: Upload a photo.\n", encoding="utf-8")

    from echelon.context_metadata import FeatureMetadata, write_feature_metadata

    metadata = FeatureMetadata.from_spec_dir(spec_dir, run_id="spec-run")
    write_feature_metadata(spec_dir, metadata)

    loaded = read_feature_metadata(spec_dir)

    assert loaded is not None
    assert loaded.feature_id == "001-photo-album"
    assert loaded.requirements[0].artifact_hash == artifact_hash(spec_file)


def test_phase4_publish_creates_canonical_metadata_and_mines_canonical_spec(tmp_path: Path) -> None:
    _disable_lexicon_gate(tmp_path)
    memory_config = (
        tmp_path
        / ".specify"
        / "extensions"
        / "echelon"
        / "echelon-config.yml"
    )
    memory_config.parent.mkdir(parents=True)
    memory_config.write_text(
        "mempalace:\n  wing: photo-album\n",
        encoding="utf-8",
    )
    provider = _mock_provider()
    ctrl, store = _controller(tmp_path, provider=provider)
    store.initialize("run-test", "banzai", "msg", 0, "phase4-document", max_iterations=5)
    _mark_constitution_complete(tmp_path, store)

    active_spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001"
    active_spec_dir.mkdir(parents=True)
    spec_text = "# Photo Album\n\nFR-001: Upload a photo.\n"
    (active_spec_dir / "spec.md").write_text(spec_text, encoding="utf-8")
    for name in (
        "00-overview.md", "requirements-overview.md", "plan.md",
        "plan-conformance.md", "plan-conformance.json",
        "research.md", "data-model.md", "tasks.md",
        "test-strategy.md", "test-architecture.md", "coverage-map.md",
    ):
        content = (
            _valid_plan_conformance_json()
            if name == "plan-conformance.json"
            else f"# {name}\n"
        )
        (active_spec_dir / name).write_text(content, encoding="utf-8")

    published_dir = tmp_path / "specs" / "001-photo-album"
    assert not published_dir.exists()

    state = store.load()
    state["spec_id"] = "001"
    state["spec_dir"] = "runs/run-test/specs/001"
    store.save(state)

    source = "specs/001-photo-album/spec.md"
    expected_metadata = {
        "scope": "canonical",
        "canonical": True,
        "artifact_path": source,
        "artifact_hash": (
            f"sha256:{hashlib.sha256(spec_text.encode('utf-8')).hexdigest()}"
        ),
        "lifecycle_status": "active",
        "spec_id": "001",
        "feature_id": "001-photo-album",
    }
    from echelon.spec_memory_miner import (
        MineResult,
        plan_canonical_requirement_drawer_ids,
    )

    calls = []

    class FakeAdapter:
        wing = "demo-wing"
        palace_path = ".mempalace"

        def plan_canonical_bytes(self, content, *, source, artifact_metadata):
            return plan_canonical_requirement_drawer_ids(
                content,
                source=source,
                artifact_metadata=artifact_metadata,
                wing="photo-album",
            )

        def mine_canonical_bytes(self, content, *, source, artifact_metadata):
            calls.append((content, source, artifact_metadata))
            drawer_ids = self.plan_canonical_bytes(
                content,
                source=source,
                artifact_metadata=artifact_metadata,
            )
            return MineResult(
                wing="demo-wing",
                total=len(drawer_ids),
                written=len(drawer_ids),
                skipped=0,
                failed=0,
                drawer_ids=drawer_ids,
                expected_drawer_ids=drawer_ids,
            )

        def verify_canonical_bytes(
            self,
            content,
            *,
            source,
            artifact_metadata,
            drawer_ids,
        ):
            return drawer_ids == self.plan_canonical_bytes(
                content,
                source=source,
                artifact_metadata=artifact_metadata,
            )

    with patch(
        "echelon.mempalace_requirements.create_requirement_memory_adapter",
        return_value=FakeAdapter(),
    ) as mock_create_adapter:
        result = ctrl.run("msg", "banzai")

    assert result.status == "done"

    metadata = read_feature_metadata(published_dir)
    assert metadata is not None
    assert metadata.feature_id == "001-photo-album"
    assert metadata.spec_id == "001"

    spec_file = published_dir / "spec.md"
    assert artifact_hash(spec_file) == expected_metadata["artifact_hash"]

    mock_create_adapter.assert_called_once_with(tmp_path, "run-test")
    assert calls == [(spec_file.read_bytes(), source, expected_metadata)]
    assert calls[0][1] == "specs/001-photo-album/spec.md"
    assert calls[0][2]["canonical"] is True
    dispatch = store.load()["last_dispatch"]
    assert dispatch["post_dispatch_complete"] is True
    assert len(dispatch["completion_receipts_sha256"]) == 64


def test_phase4_publish_keeps_readiness_when_mempalace_setup_fails(tmp_path: Path) -> None:
    _disable_lexicon_gate(tmp_path)
    provider = _mock_provider()
    ctrl, store = _controller(tmp_path, provider=provider)
    store.initialize("run-test", "banzai", "msg", 0, "phase4-document", max_iterations=5)
    _mark_constitution_complete(tmp_path, store)

    active_spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001"
    active_spec_dir.mkdir(parents=True)
    spec_text = "# Photo Album\n\nFR-001: Upload a photo.\n"
    (active_spec_dir / "spec.md").write_text(spec_text, encoding="utf-8")
    for name in (
        "00-overview.md", "requirements-overview.md", "plan.md",
        "plan-conformance.md", "plan-conformance.json",
        "research.md", "data-model.md", "tasks.md",
        "test-strategy.md", "test-architecture.md", "coverage-map.md",
    ):
        content = (
            _valid_plan_conformance_json()
            if name == "plan-conformance.json"
            else f"# {name}\n"
        )
        (active_spec_dir / name).write_text(content, encoding="utf-8")

    state = store.load()
    state["spec_id"] = "001"
    state["spec_dir"] = "runs/run-test/specs/001"
    store.save(state)

    published_dir = tmp_path / "specs" / "001-photo-album"

    with patch(
        "codegen.memory.context.MemPalaceContext.from_project",
        side_effect=RuntimeError("mempalace unavailable"),
    ) as mock_from_project:
        result = ctrl.run("msg", "banzai")

    assert result.status == "done"
    assert published_dir.exists()
    assert (published_dir / "feature-metadata.yml").exists()
    assert read_feature_metadata(published_dir) is not None
    mock_from_project.assert_any_call(tmp_path, run_id="run-test")


def test_context_metadata_publication_staging_defers_mining(
    tmp_path: Path,
) -> None:
    ctrl, store = _controller(tmp_path)
    store.initialize(
        "run-test",
        "banzai",
        "msg",
        0,
        "phase4-document",
        max_iterations=5,
    )
    _mark_constitution_complete(tmp_path, store)
    active_spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001"
    active_spec_dir.mkdir(parents=True)
    for name in (
        "00-overview.md",
        "requirements-overview.md",
        "spec.md",
        "plan.md",
        "plan-conformance.md",
        "plan-conformance.json",
        "research.md",
        "data-model.md",
        "tasks.md",
        "test-strategy.md",
        "test-architecture.md",
        "coverage-map.md",
    ):
        content = (
            _valid_plan_conformance_json()
            if name == "plan-conformance.json"
            else "# Photo Album\n\nFR-001: Upload a photo.\n"
        )
        (active_spec_dir / name).write_text(
            content,
            encoding="utf-8",
        )
    state = store.load()
    state["spec_id"] = "001"
    state["spec_dir"] = str(active_spec_dir.relative_to(tmp_path))
    store.save(state)
    result = SquadAgentResult(
        exit_code=0,
        echelon_result={"verdict": "DONE", "state_updates": {}},
        raw_output="",
        duration_ms=0,
        timed_out=False,
    )
    mock_ctx = object()
    mock_miner = MagicMock()

    with patch(
        "codegen.memory.context.MemPalaceContext.from_project",
        return_value=mock_ctx,
    ) as mock_from_project:
        with patch(
            "echelon.spec_memory_miner.SpecMemoryMiner",
            return_value=mock_miner,
        ):
            prepared = ctrl._prepare_external_phase_effects(
                result,
                "phase4-document",
                store.load(),
                manual_phase_run=False,
            )

    assert prepared is not None
    assert not (tmp_path / "specs" / "001-photo-album").exists()
    mock_from_project.assert_not_called()
    mock_miner.mine_file.assert_not_called()
    mock_miner.mine_canonical_bytes.assert_not_called()

    prepared.publish()

    metadata = read_feature_metadata(
        tmp_path / "specs" / "001-photo-album"
    )
    assert metadata is not None
    assert metadata.requirements[0].artifact_path == (
        "specs/001-photo-album/spec.md"
    )


def _context_drawers():
    from codegen.memory.mempalace_reader import DrawerResult

    return [
        DrawerResult(
            drawer_id="selected",
            content="selected old requirement",
            room="functional-requirements",
            wing="demo",
            distance=0.1,
            metadata={
                "spec_id": "001-demo",
                "artifact_path": "specs/001-demo/spec.md",
            },
        ),
        DrawerResult(
            drawer_id="workspace-re",
            content="workspace RE fact",
            room="re-workspace-context",
            wing="demo",
            distance=0.2,
            metadata={"artifact_path": "re/workspace/overview.md"},
        ),
        DrawerResult(
            drawer_id="other-spec",
            content="other requirement",
            room="functional-requirements",
            wing="demo",
            distance=0.3,
            metadata={
                "spec_id": "002-other",
                "artifact_path": "specs/002-other/spec.md",
            },
        ),
    ]


@pytest.mark.integration
def test_retarget_replacement_context_excludes_only_selected_spec_drawers(
    tmp_path: Path,
) -> None:
    ctrl, store = _controller(tmp_path)
    store.initialize("run-test", "banzai", "msg", 0, "phase0-constitution")
    state = store.load()
    state["spec_id"] = "001-demo"
    state["retarget"] = {"memory_excluded": True}
    store.save(state)
    retrieval_state = store.load()
    source_drawers = _context_drawers()
    original = list(source_drawers)

    with patch(
        "codegen.memory.context.MemPalaceContext.from_project",
        return_value=SimpleNamespace(wing="demo", palace_path=".mempalace"),
    ), patch(
        "codegen.memory.mempalace_reader.MemPalaceReader.search_requirements",
        return_value=source_drawers,
    ):
        result = ctrl._retrieve_mempalace_context_drawers(
            "query",
            "run-test",
            retrieval_state,
        )

    assert [drawer.drawer_id for drawer in result] == [
        "workspace-re",
        "other-spec",
    ]
    assert source_drawers == original


@pytest.mark.integration
def test_normal_context_preserves_selected_spec_drawers(tmp_path: Path) -> None:
    ctrl, store = _controller(tmp_path)
    store.initialize("run-test", "banzai", "msg", 0, "phase0-constitution")
    state = store.load()
    state["spec_id"] = "001-demo"
    state["retarget"] = {"memory_excluded": False}
    store.save(state)
    retrieval_state = store.load()
    changed_state = store.load()
    changed_state["retarget"] = {"memory_excluded": True}
    store.save(changed_state)
    source_drawers = _context_drawers()

    with patch(
        "codegen.memory.context.MemPalaceContext.from_project",
        return_value=SimpleNamespace(wing="demo", palace_path=".mempalace"),
    ), patch(
        "codegen.memory.mempalace_reader.MemPalaceReader.search_requirements",
        return_value=source_drawers,
    ):
        result = ctrl._retrieve_mempalace_context_drawers(
            "query",
            "run-test",
            retrieval_state,
        )

    assert [drawer.drawer_id for drawer in result] == [
        "selected",
        "workspace-re",
        "other-spec",
    ]


@pytest.mark.integration
def test_retarget_replacement_context_rejects_contradictory_metadata(
    tmp_path: Path,
) -> None:
    ctrl, store = _controller(tmp_path)
    store.initialize("run-test", "banzai", "msg", 0, "phase0-constitution")
    state = store.load()
    state["spec_id"] = "001-demo"
    state["retarget"] = {"memory_excluded": True}
    store.save(state)
    retrieval_state = store.load()
    contradictory = _context_drawers()[:1]
    contradictory[0].metadata["spec_id"] = "002-other"

    with patch(
        "codegen.memory.context.MemPalaceContext.from_project",
        return_value=SimpleNamespace(wing="demo", palace_path=".mempalace"),
    ), patch(
        "codegen.memory.mempalace_reader.MemPalaceReader.search_requirements",
        return_value=contradictory,
    ):
        with pytest.raises(RuntimeError, match="ownership metadata"):
            ctrl._retrieve_mempalace_context_drawers(
                "query",
                "run-test",
                retrieval_state,
            )
