import json
from pathlib import Path

import pytest

from echelon.spec_add_input import _find_current_run_dir
from echelon.spec_lifecycle import SpecRunNotFound, resolve_active_spec_run


def _write_state(run_dir: Path) -> None:
    run_dir.mkdir(parents=True)
    spec_dir = run_dir / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "run_id": run_dir.name,
                "spec_id": "001-demo",
                "feature_branch": "001-demo",
                "spec_dir": str(spec_dir),
            }
        ),
        encoding="utf-8",
    )


def test_core_cli_run_discovery_ignores_legacy_squad_pointer(tmp_path: Path) -> None:
    legacy_run = tmp_path / "squad" / "legacy-run"
    _write_state(legacy_run)
    (legacy_run.parent / ".current").write_text("legacy-run\n", encoding="utf-8")

    with pytest.raises(SpecRunNotFound, match="active spec pointer is missing"):
        resolve_active_spec_run(tmp_path)
    assert _find_current_run_dir(tmp_path) is None


def test_core_cli_run_discovery_uses_exact_canonical_runs_pointer(
    tmp_path: Path,
) -> None:
    canonical_run = tmp_path / "runs" / "spec-001"
    legacy_run = tmp_path / "squad" / "legacy-newer"
    _write_state(canonical_run)
    _write_state(legacy_run)
    (canonical_run.parent / ".current").write_text(
        f"{canonical_run.name}\n",
        encoding="utf-8",
    )

    assert resolve_active_spec_run(tmp_path).run_dir == canonical_run
    assert _find_current_run_dir(tmp_path) == canonical_run
