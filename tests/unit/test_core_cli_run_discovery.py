import json
from pathlib import Path

from echelon.checkpoint_cli import _active_run_dir
from echelon.spec_add_input import _find_current_run_dir


def _write_state(run_dir: Path) -> None:
    run_dir.mkdir(parents=True)
    (run_dir / "state.json").write_text(json.dumps({"run_id": run_dir.name}), encoding="utf-8")


def test_core_cli_run_discovery_ignores_legacy_squad_pointer(tmp_path: Path) -> None:
    legacy_run = tmp_path / "squad" / "legacy-run"
    _write_state(legacy_run)
    (legacy_run.parent / ".current").write_text("legacy-run\n", encoding="utf-8")

    assert _active_run_dir(tmp_path) is None
    assert _find_current_run_dir(tmp_path) is None


def test_core_cli_run_discovery_uses_canonical_runs_fallback(tmp_path: Path) -> None:
    canonical_run = tmp_path / "runs" / "spec-001"
    legacy_run = tmp_path / "squad" / "legacy-newer"
    _write_state(canonical_run)
    _write_state(legacy_run)

    assert _active_run_dir(tmp_path) == canonical_run
    assert _find_current_run_dir(tmp_path) == canonical_run
