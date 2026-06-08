"""CLI tests for deterministic reopen planning."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_plan_reopen_gaps_cli_writes_plan(tmp_path: Path) -> None:
    gaps = tmp_path / "fulfillment-gaps.md"
    tasks = tmp_path / "tasks.md"
    out_dir = tmp_path / "out"
    gaps.write_text(
        "# Fulfillment Gaps\n\n"
        "| ID | What Is Missing | Next Action |\n"
        "|----|----------------|-------------|\n"
        "| FR-001 | Missing formula | Implement formula |\n",
        encoding="utf-8",
    )
    tasks.write_text(
        "- [ ] T-001 complexity=standard phase=foundation req=INFRA depends=none\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "harness",
            "plan-reopen-gaps",
            str(gaps),
            str(tasks),
            str(out_dir),
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "reopen gap plan wrote" in result.stdout
    assert (out_dir / "reopen-plan.json").exists()
    assert (out_dir / "reopen-plan.md").exists()
