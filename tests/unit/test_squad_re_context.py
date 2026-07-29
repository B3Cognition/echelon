from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.human_input import HumanInputPolicyRegistry
from harness.re_fingerprint import ReFingerprintProfile, fingerprint_source
from harness.re_quality_contract import QUALITY_CONTRACT_VERSION
from harness.re_registry import ensure_re_layout
from harness.squad import SquadController
from harness.squad_state import SquadStateStore


class _TerminalGraph:
    def entry_phase(self) -> str:
        return "DONE"

    def all_phase_ids(self) -> set[str]:
        return {"DONE"}

    def human_input_policy_registry(self) -> HumanInputPolicyRegistry:
        return HumanInputPolicyRegistry(())


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


def test_squad_initialization_attaches_published_re_snapshot(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write_source(root, "original-a")
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
    )

    result = controller.run(user_message="add feature")

    assert result.status == "done"
    state = store.load()
    assert "telemetry_trace_id" not in state
    context = state["published_re_context"]
    assert context["status"] == "attached"
    assert context["generation"] == 1
    assert Path(context["snapshot_root"]) == squad_dir / "context/published-re"
    assert context["artifacts"]["manifest"] == str(
        squad_dir / "context/published-re/index.json"
    )
    assert (squad_dir / "context/published-re/sources/original-a/overview.md").exists()
    assert "re_execution_plan" not in state
    assert not (squad_dir / "re").exists()


def test_squad_initialization_can_ignore_published_re(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write_source(root, "api")
    _publish_source(root, "api", ReFingerprintProfile())
    squad_dir = root / "runs/run-1"
    store = SquadStateStore(squad_dir)
    controller = SquadController(
        provider=object(),
        state_store=store,
        phase_graph=_TerminalGraph(),
        ext_dir=root / "ext",
        project_root=root,
        squad_dir=squad_dir,
        ignore_re=True,
    )

    result = controller.run(user_message="inspect api")

    assert result.status == "done"
    assert store.load()["published_re_context"] == {
        "status": "ignored",
        "generation": 0,
        "artifacts": {},
    }
    assert not (squad_dir / "context/published-re").exists()


def test_squad_initialization_records_absent_re_without_blocking(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    squad_dir = root / "runs" / "run-1"
    store = SquadStateStore(squad_dir)
    controller = SquadController(
        provider=object(),
        state_store=store,
        phase_graph=_TerminalGraph(),
        ext_dir=root / "ext",
        project_root=root,
        squad_dir=squad_dir,
    )

    result = controller.run(user_message="new feature")

    assert result.status == "done"
    assert store.load()["published_re_context"] == {
        "status": "absent",
        "generation": 0,
        "artifacts": {},
    }


def test_phase_a_finalization_publishes_canonical_re_context(
    monkeypatch,
    tmp_path: Path,
) -> None:
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "constitution.md").write_text("# Constitution\n", encoding="utf-8")
    controller = object.__new__(SquadController)
    controller._project_root = tmp_path
    monkeypatch.setattr(controller, "_write_plan_conformance_outputs", lambda _path: None)
    monkeypatch.setattr(controller, "_write_final_overview", lambda _path, _state: None)
    monkeypatch.setattr(controller, "_constitution_hash", lambda _path: "sha256:test")
    monkeypatch.setattr(controller, "_write_squad_report", lambda _path, _state: None)
    monkeypatch.setattr("harness.squad.append_phase_a_run", lambda *args, **kwargs: None)

    controller._write_phase_a_finalization_outputs(
        spec_dir,
        {
            "run_id": "spec-run",
            "published_re_context": {
                "status": "absent",
                "generation": 0,
                "artifacts": {},
            },
        },
    )

    assert json.loads((spec_dir / "re-context.json").read_text(encoding="utf-8")) == {
        "schema_version": 1,
        "status": "absent",
        "generation": 0,
        "artifacts": [],
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
