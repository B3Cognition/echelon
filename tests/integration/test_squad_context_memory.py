"""Integration coverage for Squad Phase 4 canonical context publication."""
from __future__ import annotations

import sys
from pathlib import Path
import subprocess
from unittest.mock import MagicMock, patch

EXT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(EXT_ROOT) not in sys.path:
    sys.path.insert(0, str(EXT_ROOT))

from echelon.context_metadata import artifact_hash, read_feature_metadata
from harness.phase_graph import PhaseGraph
from harness.squad import SquadController
from harness.squad_provider import SquadAgentResult
from harness.squad_state import SquadStateStore

DEFINITION = EXT_ROOT / "extension/workflow/definition.yaml"
EXT_YML = EXT_ROOT / "extension/extension.yml"


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
    graph = PhaseGraph(DEFINITION, EXT_YML)
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
    provider = _mock_provider()
    ctrl, store = _controller(tmp_path, provider=provider)
    store.initialize("run-test", "banzai", "msg", 0, "phase4-document", max_iterations=5)
    _mark_constitution_complete(tmp_path, store)

    active_spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001"
    active_spec_dir.mkdir(parents=True)
    spec_text = "# Photo Album\n\nFR-001: Upload a photo.\n"
    (active_spec_dir / "spec.md").write_text(spec_text, encoding="utf-8")
    for name in (
        "plan.md", "research.md", "data-model.md", "tasks.md",
        "test-strategy.md", "test-architecture.md", "coverage-map.md",
    ):
        (active_spec_dir / name).write_text(f"# {name}\n", encoding="utf-8")

    published_dir = tmp_path / "specs" / "001-photo-album"
    assert not published_dir.exists()

    state = store.load()
    state["spec_id"] = "001"
    state["spec_dir"] = "runs/run-test/specs/001"
    store.save(state)

    mock_ctx = object()
    mock_miner = MagicMock()
    with patch("codegen.memory.context.MemPalaceContext.from_project", return_value=mock_ctx) as mock_from_project:
        with patch("codegen.memory.requirements_miner.RequirementsMiner", return_value=mock_miner) as mock_miner_cls:
            result = ctrl.run("msg", "banzai")

    assert result.status == "done"

    metadata = read_feature_metadata(published_dir)
    assert metadata is not None
    assert metadata.feature_id == "001-photo-album"
    assert metadata.spec_id == "001"

    spec_file = published_dir / "spec.md"
    expected_metadata = {
        "scope": "canonical",
        "canonical": True,
        "artifact_path": "specs/001-photo-album/spec.md",
        "artifact_hash": artifact_hash(spec_file),
        "lifecycle_status": "active",
        "spec_id": "001",
        "feature_id": "001-photo-album",
    }

    mock_from_project.assert_any_call(tmp_path, run_id="run-test")
    mock_miner_cls.assert_called_once_with(mock_ctx, project_dir=tmp_path)
    mock_miner.mine_file.assert_called_once_with(spec_file, artifact_metadata=expected_metadata)


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
        "plan.md", "research.md", "data-model.md", "tasks.md",
        "test-strategy.md", "test-architecture.md", "coverage-map.md",
    ):
        (active_spec_dir / name).write_text(f"# {name}\n", encoding="utf-8")

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
        "spec.md",
        "plan.md",
        "research.md",
        "data-model.md",
        "tasks.md",
        "test-strategy.md",
        "test-architecture.md",
        "coverage-map.md",
    ):
        (active_spec_dir / name).write_text(
            "# Photo Album\n\nFR-001: Upload a photo.\n",
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
            "codegen.memory.requirements_miner.RequirementsMiner",
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
