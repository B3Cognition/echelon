from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.re_fingerprint import ReFingerprintProfile, fingerprint_source
from harness.re_quality_contract import QUALITY_CONTRACT_VERSION
from harness.re_registry import ensure_re_layout
from harness.squad import ReGenerationMismatch, SquadController, assert_re_generation
from harness.squad_state import SquadStateStore


class _TerminalGraph:
    def entry_phase(self) -> str:
        return "DONE"

    def all_phase_ids(self) -> set[str]:
        return {"DONE"}


def _write_source(root: Path, source_id: str) -> None:
    source = root / "sources" / source_id
    source.mkdir(parents=True)
    (source / "package.json").write_text(f'{{"name":"{source_id}"}}\n', encoding="utf-8")
    (source / "index.ts").write_text(f"export const id = '{source_id}';\n", encoding="utf-8")


def _write_empty_source(root: Path, source_id: str) -> None:
    source = root / "sources" / source_id
    source.mkdir(parents=True)
    (source / ".git").mkdir()


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _publish_source(root: Path, source_id: str, profile: ReFingerprintProfile) -> None:
    source = root / "sources" / source_id
    fingerprint = fingerprint_source(source, profile)
    paths = ensure_re_layout(root)
    source_re = paths.sources / source_id
    spec = source_re / "specs/domain/spec.md"
    spec.parent.mkdir(parents=True)
    spec.write_text("# Domain\n", encoding="utf-8")
    (source_re / "overview.md").write_text(f"# {source_id} context\n", encoding="utf-8")
    _write_json(
        source_re / "manifest.json",
        {
            "schema_version": 1,
            "source_id": source_id,
            "source_path": f"sources/{source_id}",
            "source_fingerprint": fingerprint.value,
            "profile": profile.to_json_dict(),
            "profile_hash": fingerprint.profile_hash,
            "quality_contract_version": QUALITY_CONTRACT_VERSION,
            "publication_status": "complete",
            "overview": f"re/sources/{source_id}/overview.md",
            "specs": [f"re/sources/{source_id}/specs/domain/spec.md"],
        },
    )
    _write_json(
        paths.workspace / "manifest.json",
        {
            "schema_version": 1,
            "generation": 1,
            "sources": [{"source_id": source_id, "fingerprint": fingerprint.value}],
        },
    )
    for name in ("overview.md", "relationships.md", "contracts.md"):
        (paths.workspace / name).write_text(f"# {name}\n", encoding="utf-8")
    _write_json(
        paths.index,
        {
            "schema_version": 1,
            "generation": 1,
            "publication_status": "complete",
            "published_at": "2026-07-12T12:00:00+00:00",
            "published_from_run": "fixture",
            "sources": {
                source_id: {
                    "path": f"sources/{source_id}",
                    "published_path": f"re/sources/{source_id}",
                    "fingerprint": fingerprint.value,
                    "profile_hash": fingerprint.profile_hash,
                    "status": "complete",
                    "manifest": f"re/sources/{source_id}/manifest.json",
                }
            },
            "workspace": {
                "manifest": "re/workspace/manifest.json",
                "overview": "re/workspace/overview.md",
                "relationships": "re/workspace/relationships.md",
                "contracts": "re/workspace/contracts.md",
            },
            "warnings": [],
        },
    )


def test_re_generation_guard_pins_zero_when_no_publication_exists(tmp_path: Path) -> None:
    assert_re_generation(tmp_path, 0)

    paths = ensure_re_layout(tmp_path)
    _write_json(
        paths.index,
        {
            "schema_version": 1,
            "generation": 1,
            "publication_status": "complete",
            "published_at": "2026-07-12T12:00:00+00:00",
            "published_from_run": "fixture",
            "sources": {},
            "workspace": {
                "manifest": "re/workspace/manifest.json",
                "overview": "re/workspace/overview.md",
                "relationships": "re/workspace/relationships.md",
                "contracts": "re/workspace/contracts.md",
            },
            "warnings": [],
        },
    )

    with pytest.raises(ReGenerationMismatch) as exc_info:
        assert_re_generation(tmp_path, 0)

    assert exc_info.value.expected == 0
    assert exc_info.value.actual == 1


def test_squad_initialization_materializes_re_plan_and_artifacts(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    for source_id in ("original-a", "prosaic"):
        _write_source(root, source_id)
    profile = ReFingerprintProfile()
    _publish_source(root, "original-a", profile)

    squad_dir = root / "runs" / "run-1"
    store = SquadStateStore(squad_dir)
    controller = SquadController(
        provider=object(),
        state_store=store,
        phase_graph=_TerminalGraph(),
        ext_dir=root / "ext",
        project_root=root,
        squad_dir=squad_dir,
        implementation_targets=["sources/prosaic"],
    )

    result = controller.run(user_message="add prosaic feature")

    assert result.status == "done"
    state = store.load()
    assert state["re_policy"] == "changed"
    assert state["requested_re_policy"] == ""
    assert state["implementation_targets"] == ["sources/prosaic"]
    assert state["target_source"] == ""
    assert state["re_refresh_sources"] == ["prosaic"]
    assert state["re_missing_sources"] == []
    assert state["re_generation"] == 1
    assert state["re_artifacts"]["manifest"] == str(root / "re/index.json")
    assert state["re_artifacts"]["per_repo"] == [str(root / "re/sources/original-a")]
    assert str(root / "re/sources/original-a/overview.md") in state["re_artifacts"]["re_contexts"]
    assert not (squad_dir / "re" / "sources/original-a").exists()
    assert not (squad_dir / "re" / "sources/prosaic").exists()

    source_index = json.loads((squad_dir / "re" / "re-source-index.json").read_text())
    assert {source["id"]: source["action"] for source in source_index["sources"]} == {
        "original-a": "reuse",
        "prosaic": "refresh",
    }


def test_squad_initialization_uses_resolved_re_profile_overrides(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write_source(root, "api")
    config = root / ".echelon/config.yml"
    config.parent.mkdir(parents=True)
    config.write_text(
        "re:\n"
        "  profile: deep\n"
        "  depth:\n"
        "    level: logic\n"
        "    max_lines_per_file: 3210\n"
        "  sources:\n"
        "    git_history_limit: 456\n",
        encoding="utf-8",
    )
    squad_dir = root / "runs/run-1"
    store = SquadStateStore(squad_dir)
    controller = SquadController(
        provider=object(),
        state_store=store,
        phase_graph=_TerminalGraph(),
        ext_dir=root / "ext",
        project_root=root,
        squad_dir=squad_dir,
    )

    result = controller.run(user_message="inspect api")

    assert result.status == "done"
    profile = store.load()["re_execution_plan"]["profile"]
    assert profile == {
        "codegraph_version": None,
        "depth": "logic",
        "git_history_limit": 456,
        "max_lines_per_file": 3210,
        "profile": "deep",
    }


def test_squad_initialization_does_not_use_implementation_target_as_re_scope(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write_source(root, "original-a")
    _write_empty_source(root, "prosaic")

    squad_dir = root / "runs" / "run-1"
    store = SquadStateStore(squad_dir)
    controller = SquadController(
        provider=object(),
        state_store=store,
        phase_graph=_TerminalGraph(),
        ext_dir=root / "ext",
        project_root=root,
        squad_dir=squad_dir,
        implementation_targets=["sources/prosaic"],
    )

    result = controller.run(user_message="add prosaic feature")

    assert result.status == "done"
    state = store.load()
    assert state["re_policy"] == "changed"
    assert state["target_source"] == ""
    assert state["implementation_targets"] == ["sources/prosaic"]
    assert state["re_refresh_sources"] == ["original-a"]
    assert state["re_missing_sources"] == []
    assert state["re_empty_sources"] == ["prosaic"]
    assert state["re_source_actions"] == {
        "original-a": "refresh",
        "prosaic": "skip-empty",
    }

    source_index = json.loads((squad_dir / "re" / "re-source-index.json").read_text())
    assert {source["id"]: source["action"] for source in source_index["sources"]} == {
        "original-a": "refresh",
        "prosaic": "skip-empty",
    }


def test_squad_materializes_run_targets_into_active_spec_metadata(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    squad_dir = root / "runs" / "run-1"
    spec_dir = squad_dir / "specs" / "001-dashboard"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Dashboard\n", encoding="utf-8")
    store = SquadStateStore(squad_dir)
    store.initialize(
        "run-1",
        "brownfield",
        "add dashboard",
        0,
        "phase3-how",
        implementation_targets=["sources/web", "sources/api"],
    )
    state = store.load()
    state["spec_id"] = "001-dashboard"
    state["spec_dir"] = str(spec_dir)
    store.save(state)
    controller = SquadController(
        provider=object(),
        state_store=store,
        phase_graph=_TerminalGraph(),
        ext_dir=root / "ext",
        project_root=root,
        squad_dir=squad_dir,
        implementation_targets=["sources/web", "sources/api"],
    )

    controller._materialize_implementation_targets()

    from harness.spec_frontmatter import read_targets

    assert read_targets(spec_dir) == ["sources/web", "sources/api"]
