from __future__ import annotations

import hashlib
import json
import shutil
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from harness.re_fingerprint import ReFingerprintProfile, SourceFingerprint
from harness.re_planner import ReExecutionPlan, RePlanSource
from harness.re_publication import (
    RePublicationConflict,
    RePublicationValidationError,
    publish_re_run,
    recover_interrupted_publication,
)
from harness.re_registry import ensure_re_layout
from harness.re_registry import ReRegistryError


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _fingerprint(source_id: str, version: str, profile: ReFingerprintProfile) -> SourceFingerprint:
    value = hashlib.sha256(f"{source_id}:{version}".encode()).hexdigest()
    return SourceFingerprint(
        value=value,
        kind="file-tree",
        dirty=False,
        profile_hash=profile.profile_hash(),
    )


def _deep_spec(source_id: str, version: str) -> str:
    evidence = "\n".join(
        f"- `{source_id}/src/file-{number}.ts:{number}`" for number in range(1, 6)
    )
    return (
        f"# {source_id} domain {version}\n\n"
        "## User Scenarios & Testing\n\n"
        "Five source-backed scenarios describe the current behavior.\n\n"
        "## Requirements (Functional)\n\n"
        "The current behavior must remain observable.\n\n"
        "## Key Entities\n\n"
        "The source entity and its fields are preserved.\n\n"
        "## Edge Cases\n\n"
        "Invalid input follows the existing error path.\n\n"
        "## Source Evidence\n\n"
        f"{evidence}\n"
    )


def write_valid_re_run(
    root: Path,
    sources: tuple[str, ...],
    *,
    run_id: str = "run-1",
    status: str = "complete",
    versions: dict[str, str] | None = None,
    actions: dict[str, str] | None = None,
    removed_sources: tuple[str, ...] = (),
) -> Path:
    versions = versions or {source_id: "v1" for source_id in sources}
    actions = actions or {source_id: "refresh" for source_id in sources}
    run_dir = root / "runs" / run_id
    run_re = run_dir / "re"
    profile = ReFingerprintProfile()
    planned: list[RePlanSource] = []
    workspace_inputs: list[dict[str, object]] = []

    for source_id in sources:
        version = versions[source_id]
        source_root = root / "sources" / source_id
        if actions[source_id] == "skip-empty" and source_root.exists():
            shutil.rmtree(source_root)
        source_root.mkdir(parents=True, exist_ok=True)
        if actions[source_id] != "skip-empty":
            for number in range(1, 6):
                (source_root / "src").mkdir(exist_ok=True)
                (source_root / "src" / f"file-{number}.ts").write_text(
                    f"export const version{number} = '{version}';\n",
                    encoding="utf-8",
                )

        action = actions[source_id]
        classification = {
            "refresh": "refresh",
            "reuse": "current",
            "skip-empty": "empty",
            "missing": "unavailable",
        }[action]
        fingerprint = _fingerprint(source_id, version, profile)
        plan_source = RePlanSource(
            id=source_id,
            path=f"sources/{source_id}",
            absolute_path=str(source_root),
            action=action,
            fingerprint=fingerprint,
            cache_path=str(root / "re" / ".cache" / "sources" / source_id / fingerprint.value),
            dirty=False,
            selected=True,
            classification=classification,
        )
        planned.append(plan_source)
        workspace_inputs.append(
            {
                "id": source_id,
                "decision": classification,
                "source_path": plan_source.path,
                "fingerprint": fingerprint.value,
                "profile_hash": fingerprint.profile_hash,
                "input_path": (
                    f"runs/{run_id}/re/sources/{source_id}"
                    if action in {"refresh", "skip-empty"}
                    else f"re/sources/{source_id}/manifest.json"
                ),
            }
        )

        if action == "refresh":
            staged_source = run_re / "sources" / source_id
            _write_json(staged_source / "analysis.json", {"source_id": source_id, "version": version})
            (staged_source / "overview.md").write_text(
                f"# {source_id}\n\nVersion {version}.\n",
                encoding="utf-8",
            )
            spec = staged_source / "specs" / "001-re-domain" / "spec.md"
            spec.parent.mkdir(parents=True)
            spec.write_text(_deep_spec(source_id, version), encoding="utf-8")
        elif action == "skip-empty":
            (run_re / "sources" / source_id).mkdir(parents=True, exist_ok=True)

    for source_id in removed_sources:
        workspace_inputs.append({"id": source_id, "decision": "removed"})

    analysis_required = any(source.action == "refresh" for source in planned)
    plan = ReExecutionPlan(
        policy="changed",
        requested_policy="changed",
        target_source="",
        sources=tuple(planned),
        forbidden_source_roots=[],
        profile=profile,
        removed_sources=removed_sources,
        analysis_required=analysis_required,
        workspace_synthesis_required=True,
        publication_required=True,
    )
    _write_json(run_re / "re-execution-plan.json", plan.to_json_dict())
    _write_json(
        run_re / "re-source-index.json",
        {
            "schema_version": 1,
            "sources": [source.to_json_dict() for source in plan.sources],
        },
    )
    _write_json(
        run_re / "re-workspace-inputs.json",
        {"schema_version": 1, "sources": workspace_inputs},
    )
    _write_json(run_dir / "state.json", {"run_id": run_id, "status": "running", "golddigger_status": status})
    _write_json(run_re / "state.json", {"status": "done" if status != "failed" else "failed"})
    workspace = run_re / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "overview.md").write_text(f"# Workspace {run_id}\n", encoding="utf-8")
    (workspace / "relationships.md").write_text("# Relationships\n", encoding="utf-8")
    (workspace / "contracts.md").write_text("# Contracts\n", encoding="utf-8")
    return run_dir


def _durable_snapshot(root: Path) -> dict[str, bytes]:
    re_root = root / "re"
    if not re_root.exists():
        return {}
    result: dict[str, bytes] = {}
    for path in sorted(re_root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(re_root)
        if relative.parts and relative.parts[0] in {".cache", ".staging", ".locks"}:
            continue
        result[relative.as_posix()] = path.read_bytes()
    return result


def _finish_run(run_dir: Path) -> None:
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    state["status"] = "done"
    _write_json(run_dir / "state.json", state)


@pytest.mark.unit
def test_complete_two_source_publish_creates_one_generation(tmp_path: Path) -> None:
    run_dir = write_valid_re_run(tmp_path, ("web", "api"))

    result = publish_re_run(tmp_path, run_dir)

    assert result.generation == 1
    assert result.changed_sources == ("api", "web")
    index = json.loads((tmp_path / "re" / "index.json").read_text(encoding="utf-8"))
    assert index["generation"] == 1
    assert set(index["sources"]) == {"api", "web"}
    assert json.loads((tmp_path / "re/sources/api/manifest.json").read_text())["source_id"] == "api"
    assert (tmp_path / "re/sources/web/specs/001-re-domain/spec.md").is_file()
    fingerprint = index["sources"]["api"]["fingerprint"]
    assert (tmp_path / f"re/.cache/sources/api/{fingerprint}/analysis.json").is_file()
    assert (tmp_path / "re/workspace/contracts.md").is_file()


@pytest.mark.unit
def test_partial_publication_requires_explicit_override(tmp_path: Path) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",), status="partial")

    with pytest.raises(RePublicationValidationError, match="allow-partial"):
        publish_re_run(tmp_path, run_dir)

    result = publish_re_run(tmp_path, run_dir, allow_partial=True)
    assert result.status == "partial"
    assert json.loads((tmp_path / "re/index.json").read_text())["publication_status"] == "partial"


@pytest.mark.unit
def test_failed_run_is_never_publishable(tmp_path: Path) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",), status="failed")

    with pytest.raises(RePublicationValidationError, match="failed"):
        publish_re_run(tmp_path, run_dir, allow_partial=True)
    assert not (tmp_path / "re/index.json").exists()


@pytest.mark.unit
def test_one_source_refresh_preserves_unchanged_source_bytes(tmp_path: Path) -> None:
    run_1 = write_valid_re_run(
        tmp_path,
        ("web", "api"),
        run_id="run-1",
        versions={"web": "v1", "api": "v1"},
    )
    publish_re_run(tmp_path, run_1)
    _finish_run(run_1)
    web_before = _durable_snapshot(tmp_path)["sources/web/manifest.json"]
    run_2 = write_valid_re_run(
        tmp_path,
        ("web", "api"),
        run_id="run-2",
        versions={"web": "v1", "api": "v2"},
        actions={"web": "reuse", "api": "refresh"},
    )

    result = publish_re_run(tmp_path, run_2, expected_generation=1)

    assert result.generation == 2
    assert result.changed_sources == ("api",)
    assert _durable_snapshot(tmp_path)["sources/web/manifest.json"] == web_before
    assert "Version v2" in (tmp_path / "re/sources/api/overview.md").read_text()


@pytest.mark.unit
def test_empty_source_publishes_manifest_without_specs(tmp_path: Path) -> None:
    run_dir = write_valid_re_run(
        tmp_path,
        ("empty",),
        actions={"empty": "skip-empty"},
    )

    result = publish_re_run(tmp_path, run_dir)

    assert result.generation == 1
    manifest = json.loads((tmp_path / "re/sources/empty/manifest.json").read_text())
    assert manifest["publication_status"] == "empty"
    assert manifest["specs"] == []
    assert "No analyzable source files" in (tmp_path / "re/sources/empty/overview.md").read_text()


@pytest.mark.unit
def test_generation_conflict_does_not_modify_publication(tmp_path: Path) -> None:
    run_1 = write_valid_re_run(tmp_path, ("api",), run_id="run-1")
    publish_re_run(tmp_path, run_1)
    _finish_run(run_1)
    before = _durable_snapshot(tmp_path)
    run_2 = write_valid_re_run(
        tmp_path,
        ("api",),
        run_id="run-2",
        versions={"api": "v2"},
    )

    with pytest.raises(RePublicationConflict, match="expected generation 0"):
        publish_re_run(tmp_path, run_2, expected_generation=0)
    assert _durable_snapshot(tmp_path) == before


@pytest.mark.unit
def test_failure_before_index_replace_rolls_back_byte_for_byte(tmp_path: Path) -> None:
    run_1 = write_valid_re_run(tmp_path, ("api",), run_id="run-1")
    publish_re_run(tmp_path, run_1)
    _finish_run(run_1)
    before = _durable_snapshot(tmp_path)
    run_2 = write_valid_re_run(
        tmp_path,
        ("api",),
        run_id="run-2",
        versions={"api": "v2"},
    )

    def fail_before_index(step: str) -> None:
        if step == "before_index_replace":
            raise OSError("injected failure")

    with pytest.raises(OSError, match="injected failure"):
        publish_re_run(
            tmp_path,
            run_2,
            expected_generation=1,
            fault_hook=fail_before_index,
        )

    assert _durable_snapshot(tmp_path) == before


@pytest.mark.unit
def test_explicit_removal_updates_source_and_workspace_atomically(tmp_path: Path) -> None:
    run_1 = write_valid_re_run(tmp_path, ("web", "api"), run_id="run-1")
    publish_re_run(tmp_path, run_1)
    _finish_run(run_1)
    run_2 = write_valid_re_run(
        tmp_path,
        ("api",),
        run_id="run-2",
        actions={"api": "reuse"},
        removed_sources=("web",),
    )

    result = publish_re_run(tmp_path, run_2, expected_generation=1)

    assert result.removed_sources == ("web",)
    assert not (tmp_path / "re/sources/web").exists()
    index = json.loads((tmp_path / "re/index.json").read_text())
    assert set(index["sources"]) == {"api"}
    workspace = json.loads((tmp_path / "re/workspace/manifest.json").read_text())
    assert [source["source_id"] for source in workspace["sources"]] == ["api"]


@pytest.mark.unit
def test_populated_to_empty_replaces_old_specs_only_after_success(tmp_path: Path) -> None:
    run_1 = write_valid_re_run(tmp_path, ("api",), run_id="run-1")
    publish_re_run(tmp_path, run_1)
    _finish_run(run_1)
    assert (tmp_path / "re/sources/api/specs/001-re-domain/spec.md").is_file()
    run_2 = write_valid_re_run(
        tmp_path,
        ("api",),
        run_id="run-2",
        versions={"api": "empty"},
        actions={"api": "skip-empty"},
    )

    publish_re_run(tmp_path, run_2, expected_generation=1)

    manifest = json.loads((tmp_path / "re/sources/api/manifest.json").read_text())
    assert manifest["publication_status"] == "empty"
    assert manifest["specs"] == []
    assert not (tmp_path / "re/sources/api/specs").exists()


@pytest.mark.unit
def test_workspace_inputs_must_match_plan_fingerprint(tmp_path: Path) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    inputs_path = run_dir / "re/re-workspace-inputs.json"
    inputs = json.loads(inputs_path.read_text())
    inputs["sources"][0]["fingerprint"] = "wrong"
    _write_json(inputs_path, inputs)

    with pytest.raises(RePublicationValidationError, match="workspace input fingerprint"):
        publish_re_run(tmp_path, run_dir)
    assert not (tmp_path / "re/index.json").exists()


@pytest.mark.unit
def test_shallow_full_depth_spec_is_not_publishable(tmp_path: Path) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    spec = run_dir / "re/sources/api/specs/001-re-domain/spec.md"
    spec.write_text("# Architecture summary\n", encoding="utf-8")

    with pytest.raises(RePublicationValidationError, match="shallow"):
        publish_re_run(tmp_path, run_dir)


@pytest.mark.unit
def test_stale_interrupted_replacement_restores_backup(tmp_path: Path) -> None:
    run_1 = write_valid_re_run(tmp_path, ("api",), run_id="run-1")
    publish_re_run(tmp_path, run_1)
    _finish_run(run_1)
    before = _durable_snapshot(tmp_path)
    paths = ensure_re_layout(tmp_path)
    stage = paths.staging / "run-stale"
    backup = stage / "rollback/sources/api"
    backup.parent.mkdir(parents=True)
    shutil.copytree(tmp_path / "re/sources/api", backup)
    shutil.rmtree(tmp_path / "re/sources/api")
    (tmp_path / "re/sources/api").mkdir(parents=True)
    (tmp_path / "re/sources/api/corrupt.md").write_text("corrupt\n")
    _write_json(
        stage / "rollback-journal.json",
        {
            "schema_version": 1,
            "status": "replacing",
            "operations": [
                {
                    "final": "sources/api",
                    "staged": "new/sources/api",
                    "backup": "rollback/sources/api",
                    "backed_up": True,
                    "installed": True,
                }
            ],
        },
    )
    lock = paths.locks / "publish.lock"
    lock.mkdir()
    _write_json(
        lock / "owner.json",
        {
            "run_id": "run-stale",
            "run_dir": str(tmp_path / "runs/run-stale"),
            "pid": 999_999_999,
            "hostname": socket.gethostname(),
            "acquired_at": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
        },
    )

    assert recover_interrupted_publication(tmp_path, stale_after_seconds=0)
    assert _durable_snapshot(tmp_path) == before
    assert not lock.exists()
    assert not stage.exists()


@pytest.mark.unit
def test_invalid_installed_index_rolls_back_before_cleanup(tmp_path: Path) -> None:
    run_1 = write_valid_re_run(tmp_path, ("api",), run_id="run-1")
    publish_re_run(tmp_path, run_1)
    _finish_run(run_1)
    before = _durable_snapshot(tmp_path)
    run_2 = write_valid_re_run(
        tmp_path,
        ("api",),
        run_id="run-2",
        versions={"api": "v2"},
    )

    def corrupt_index(step: str) -> None:
        if step == "after_index_replace":
            (tmp_path / "re/index.json").write_text("not json\n", encoding="utf-8")

    with pytest.raises(ReRegistryError, match="cannot read RE index"):
        publish_re_run(
            tmp_path,
            run_2,
            expected_generation=1,
            fault_hook=corrupt_index,
        )

    assert _durable_snapshot(tmp_path) == before
