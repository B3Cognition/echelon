from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LIDA = ROOT / "scripts/bash/lida_broadcast.sh"
CALIBRATE = ROOT / "scripts/bash/calibrate-endocrine.sh"


def test_lida_broadcast_resolves_active_echelon_run(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "spec-test"
    run_dir.mkdir(parents=True)
    (tmp_path / "runs/.current").write_text("spec-test\n", encoding="utf-8")

    result = subprocess.run(
        ["bash", str(LIDA), "broadcast", '{"message":"ok"}'],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert (run_dir / "lida-payload.json").read_text(encoding="utf-8") == '{"message":"ok"}'


def test_lida_broadcast_does_not_create_legacy_speckit_state(tmp_path: Path) -> None:
    result = subprocess.run(
        ["bash", str(LIDA), "broadcast", '{"message":"ok"}'],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "No active Echelon run" in result.stderr
    assert not (tmp_path / ".specify").exists()


def test_endocrine_calibration_does_not_probe_legacy_speckit_state(
    tmp_path: Path,
) -> None:
    result = subprocess.run(
        ["bash", str(CALIBRATE)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert ".specify" not in result.stdout + result.stderr
    assert not (tmp_path / ".specify").exists()


def test_one_time_extension_agent_rewriter_is_removed() -> None:
    assert not (ROOT / "scripts/bash/agent-endocrine-rewire.sh").exists()
