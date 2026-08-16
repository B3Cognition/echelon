"""Integration gate for the hard RE v1/v2 engine boundary."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import stat
from types import SimpleNamespace
from typing import Callable

import pytest

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.run_store import detect_re_engine


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


@dataclass(frozen=True)
class LegacyFixture:
    name: str
    project_root: Path
    run_dir: Path | None


def _legacy_fixture(project_root: Path, name: str) -> LegacyFixture:
    if name == "fresh":
        project_root.mkdir(exist_ok=True)
        return LegacyFixture(name, project_root, None)

    run_id = f"re-v1-{name}"
    run_dir = project_root / "runs" / run_id
    re_dir = run_dir / "re"
    re_dir.mkdir(parents=True)
    (project_root / "runs" / ".current-re").write_text(
        run_id + "\n",
        encoding="utf-8",
    )
    outer: dict[str, object] = {
        "run_id": run_id,
        "run_kind": "re",
        "status": "running",
        "phase": "re-extract-2-specify",
        "re_policy": "changed",
        "expected_generation": 0,
        "extraction_complete": False,
        "publication_pending": False,
        "publication_complete": False,
    }
    inner: dict[str, object] = {
        "status": "in_progress",
        "phase": "re-extract-2-specify",
        "coverage_threshold": 99,
        "resolution_threshold": 99,
        "re_workspace_synthesis_complete": False,
        "re_source_order": ["api"],
        "re_source_states": {
            "api": {"status": "active", "coverage_pct": 50.0}
        },
    }
    if name == "blocked":
        outer.update(
            status="blocked",
            blocked_reason="re_token_budget_exhausted",
        )
        inner.update(
            status="blocked",
            blocked_reason="re_token_budget_exhausted",
        )
    elif name == "partial":
        outer.update(
            status="done",
            extraction_complete=True,
            publication_pending=True,
            golddigger_status="partial",
            finalized_partial=True,
        )
        inner.update(
            status="done",
            publication_status="partial",
            re_source_states={
                "api": {
                    "status": "partial_quality_debt",
                    "coverage_pct": 95.0,
                }
            },
        )
    elif name == "published":
        outer.update(
            status="done",
            extraction_complete=True,
            publication_complete=True,
            generation=4,
            golddigger_status="complete",
        )
        inner.update(
            status="done",
            publication_status="complete",
            publication_generation=4,
            re_workspace_synthesis_complete=True,
            re_source_states={"api": {"status": "passed", "coverage_pct": 100.0}},
        )
    elif name != "running":  # pragma: no cover - test matrix owns names.
        raise AssertionError(f"unknown legacy fixture {name}")
    _write_json(run_dir / "state.json", outer)
    _write_json(re_dir / "state.json", inner)
    return LegacyFixture(name, project_root, run_dir)


class RecordingV1Controller:
    def __init__(self) -> None:
        self.run_calls: list[dict[str, object]] = []
        self.continue_calls: list[tuple[int | None, dict[str, int]]] = []

    def run(self, **kwargs: object) -> SimpleNamespace:
        self.run_calls.append(kwargs)
        return SimpleNamespace(
            status="done",
            run_id="re-v1-fresh",
            generation=0,
            no_work=False,
        )

    def continue_run(
        self,
        re_max_inner: int | None,
        **overrides: int,
    ) -> SimpleNamespace:
        self.continue_calls.append((re_max_inner, overrides))
        return SimpleNamespace(
            status="done",
            run_id="re-v1-blocked",
            generation=0,
            no_work=False,
        )


def _assert_no_v2_state(project_root: Path) -> None:
    assert not (project_root / "re" / "v2").exists()
    runs = project_root / "runs"
    if runs.exists():
        assert not any(path.name == "v2" for path in runs.glob("*/v2"))


def _assert_valid_v1_state(fixture: LegacyFixture) -> None:
    if fixture.run_dir is None:
        return
    from harness.re_lifecycle import ReLifecycleController

    controller = ReLifecycleController(
        project_root=fixture.project_root,
        extension_root=fixture.project_root / "extension",
        provider_factory=lambda: pytest.fail("state validation constructed a provider"),
    )
    state = controller._load_state(fixture.run_dir)
    assert state["run_id"] == fixture.run_dir.name
    assert state["run_kind"] == "re"
    assert detect_re_engine(fixture.run_dir) == "v1"


def _never_v2(*_args: object, **_kwargs: object) -> object:
    pytest.fail("a legacy RE operation constructed or invoked the v2 controller")


@pytest.mark.integration
@pytest.mark.parametrize(
    ("fixture_name", "operation"),
    (
        ("fresh", "run"),
        ("running", "status"),
        ("blocked", "continue"),
        ("partial", "publish"),
        ("published", "status"),
    ),
)
def test_legacy_lifecycle_operations_remain_v1_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fixture_name: str,
    operation: str,
) -> None:
    from echelon.cli import (
        _cmd_re_continue,
        _cmd_re_publish,
        _cmd_re_run,
        _cmd_re_status,
    )

    fixture = _legacy_fixture(tmp_path, fixture_name)
    before_fixture = (
        _tree_snapshot(fixture.run_dir) if fixture.run_dir is not None else None
    )
    v1 = RecordingV1Controller()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("echelon.cli._re_lifecycle_controller", lambda _root: v1)
    monkeypatch.setattr("echelon.cli._run_re_v2_create", _never_v2)
    monkeypatch.setattr("echelon.cli._run_re_v2_continue", _never_v2)
    monkeypatch.setattr("harness.re_v2.controller.ReV2Controller", _never_v2)
    monkeypatch.setattr("harness.re_v2.status.render_v2_status", _never_v2)

    if operation == "run":
        _cmd_re_run([])
        assert v1.run_calls == [
            {
                "policy": "changed",
                "re_max_inner": None,
                "reset": False,
                "reuse_published": True,
                "profile_name": None,
                "hard_token_limit": None,
                "hard_active_minutes": None,
            }
        ]
    elif operation == "continue":
        _cmd_re_continue([])
        assert v1.continue_calls == [(None, {})]
    elif operation == "status":
        assert fixture.run_dir is not None
        before_outer = (fixture.run_dir / "state.json").read_bytes()
        before_inner = (fixture.run_dir / "re" / "state.json").read_bytes()
        _cmd_re_status([])
        assert (fixture.run_dir / "state.json").read_bytes() == before_outer
        assert (fixture.run_dir / "re" / "state.json").read_bytes() == before_inner
    elif operation == "publish":
        assert fixture.run_dir is not None
        published: list[tuple[Path, bool, int]] = []

        def publish_v1(
            _project_root: Path,
            run_dir: Path,
            *,
            allow_partial: bool,
            expected_generation: int,
            allow_same_run_republish: bool,
        ) -> SimpleNamespace:
            assert allow_same_run_republish is True
            published.append((run_dir, allow_partial, expected_generation))
            return SimpleNamespace(
                status="partial",
                generation=1,
                changed_sources=("api",),
                removed_sources=(),
            )

        monkeypatch.setattr("harness.re_migration.import_legacy_re_cache", lambda _root: ())
        monkeypatch.setattr("harness.re_publication.publish_re_run", publish_v1)
        _cmd_re_publish([fixture.run_dir.name, "--allow-partial"])
        assert published == [(fixture.run_dir, True, 0)]
        outer = json.loads((fixture.run_dir / "state.json").read_text())
        inner = json.loads((fixture.run_dir / "re" / "state.json").read_text())
        assert outer["publication_complete"] is True
        assert outer["generation"] == 1
        assert inner["publication_status"] == "partial"
    else:  # pragma: no cover - parameter matrix owns operation names.
        raise AssertionError(operation)

    _assert_valid_v1_state(fixture)
    if fixture.run_dir is not None and operation != "publish":
        assert _tree_snapshot(fixture.run_dir) == before_fixture
    _assert_no_v2_state(tmp_path)


def _unsupported_manifest(run_id: str) -> bytes:
    return canonical_json_bytes(
        {
            "artifact_policy_versions": {"L0": "egr-164-v1"},
            "created_at": "2026-08-14T12:00:00Z",
            "engine": "re-v2",
            "engine_protocol_version": "99.0",
            "initial_budget_policy": {
                "active_ms_limit": 60_000,
                "artifact_generation_attempt_limit": 1,
                "provider_attempt_limit": 1,
                "result_contract_retry_limit": 0,
                "semantic_repair_round_limit": 0,
                "token_limit": 100,
            },
            "parent_run_id": None,
            "partition_manifest_id": content_digest(b"partitions"),
            "provider_contract": {
                "provider": "deterministic-inventory",
                "provider_protocol_version": "re-v2-l0-v1",
                "result_contract_id": "deterministic-inventory-v1",
            },
            "requested_goals": ["inventory"],
            "run_id": run_id,
            "schema_version": 1,
            "source_snapshot_id": content_digest(b"snapshot"),
            "source_snapshot_kind": "content-snapshot",
        }
    )


def _tree_snapshot(root: Path) -> dict[str, tuple[str, int, bytes | None]]:
    snapshot: dict[str, tuple[str, int, bytes | None]] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        details = path.lstat()
        kind = "dir" if stat.S_ISDIR(details.st_mode) else "file"
        payload = path.read_bytes() if kind == "file" else None
        snapshot[relative] = (kind, stat.S_IMODE(details.st_mode), payload)
    return snapshot


@pytest.mark.integration
@pytest.mark.parametrize(
    "manifest_payload",
    (
        b"{malformed-json",
        pytest.param(_unsupported_manifest("re-v2-invalid"), id="unsupported-protocol"),
    ),
)
@pytest.mark.parametrize("operation", ("continue", "status"))
def test_invalid_v2_pin_fails_before_execution_or_side_effects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    manifest_payload: bytes,
    operation: str,
) -> None:
    from echelon.cli import _cmd_re_continue, _cmd_re_status

    run_id = "re-v2-invalid"
    run_dir = tmp_path / "runs" / run_id
    v2_dir = run_dir / "v2"
    v2_dir.mkdir(parents=True)
    (v2_dir / "run.json").write_bytes(manifest_payload)
    (tmp_path / "runs" / ".current-re").write_text(run_id + "\n", encoding="utf-8")
    before = _tree_snapshot(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("echelon.cli._re_lifecycle_controller", _never_v2)
    monkeypatch.setattr("echelon.cli._re_v2_context", _never_v2)
    monkeypatch.setattr("harness.re_v2.controller.ReV2Controller", _never_v2)
    monkeypatch.setattr("harness.re_v2.controller.production_executor_registry", _never_v2)

    command: Callable[[list[str]], None] = (
        _cmd_re_continue if operation == "continue" else _cmd_re_status
    )
    with pytest.raises(SystemExit) as exc:
        command([])

    assert exc.value.code == 2
    assert _tree_snapshot(tmp_path) == before
    assert not (v2_dir / "events.jsonl").exists()
    assert not (v2_dir / "ledger.jsonl").exists()
    assert not (v2_dir / "candidates").exists()
    assert not (v2_dir / ".execution").exists()
