from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.skills.status_skill import show_status


@pytest.mark.unit
def test_status_banner_shows_dirty_adjudication_counts(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state_dir = tmp_path / "runs" / "build-1" / "state"
    state_dir.mkdir(parents=True)
    (state_dir / "default.json").write_text(
        json.dumps(
            {
                "status": "converged",
                "outer_iter": 1,
                "inner_iter": 0,
                "tokens_used": 100,
                "dirty_worktree_adjudication": {
                    "summary": {
                        "total": 3,
                        "committed": 1,
                        "ignored": 2,
                        "left": 0,
                        "blocked": 0,
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    payload = show_status(str(tmp_path))
    rendered = capsys.readouterr().err

    assert payload["strategies"]["default"]["dirty_worktree_adjudication"][
        "summary"
    ]["ignored"] == 2
    assert "dirty: 1 committed, 2 ignored, 0 left, 0 blocked" in rendered
