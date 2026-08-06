"""Controlled RunContextError rendering at standalone harness boundaries."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness.skills.run_skill import RunContextError


_NEXT_STEP = (
    "run delivery from the workspace that owns specs/, or repair the supplied "
    "orchestration root"
)


@pytest.mark.unit
def test_standalone_run_renders_invalid_orchestration_context(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("HARNESS_SPEC", "042")

    with patch("harness.config.load_config", return_value=MagicMock()), \
         patch("harness.gitops.GitOpsManager", return_value=MagicMock()), \
         patch("harness.docker_provider.DockerWorktreeProvider", return_value=MagicMock()), \
         patch(
             "harness.skills.run_skill.run",
             side_effect=RunContextError("workspace has no matching spec"),
         ):
        from harness.__main__ import _run

        with pytest.raises(SystemExit) as exc:
            _run()

    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "HARNESS — INVALID ORCHESTRATION CONTEXT" in err
    assert "problem" in err
    assert "workspace has no matching spec" in err
    assert _NEXT_STEP in err
    assert "Traceback" not in err


@pytest.mark.unit
def test_legacy_resume_renders_invalid_orchestration_context(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from harness.paths import build_dir, current_build_marker
    from harness.skills.resume_skill import resume

    spec_id = "042"
    build_id = "build-existing"
    marker = current_build_marker(tmp_path, spec_id)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(build_id, encoding="utf-8")
    state_dir = build_dir(tmp_path, build_id) / "state"
    state_dir.mkdir(parents=True)
    (state_dir / "default.json").write_text(
        json.dumps(
            {
                "spec_id": spec_id,
                "strategy_id": "default",
                "status": "blocked",
                "mode": "semi",
                "termination_reason": "blocker_escalation",
            }
        ),
        encoding="utf-8",
    )

    with patch("harness.config.load_config", return_value=MagicMock()), \
         patch(
             "harness.skills.run_skill.run",
             side_effect=RunContextError("workspace has no matching spec"),
         ):
        with pytest.raises(SystemExit) as exc:
            resume(
                "resume spec 042 strategy default answer: use option A",
                provider=MagicMock(),
                gitops=MagicMock(),
                base_dir=str(tmp_path),
            )

    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "HARNESS — INVALID ORCHESTRATION CONTEXT" in err
    assert "problem" in err
    assert "workspace has no matching spec" in err
    assert _NEXT_STEP in err
    assert "Traceback" not in err
