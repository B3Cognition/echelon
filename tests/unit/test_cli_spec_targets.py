from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest


def _write_spec(
    root: Path,
    *,
    tasks: str,
    targets: tuple[str, ...],
) -> Path:
    spec_dir = root / "specs" / "001-dashboard"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Dashboard\n", encoding="utf-8")
    (spec_dir / "tasks.md").write_text(tasks, encoding="utf-8")
    target_rows = "\n".join(
        f"  - id: {Path(target).name}\n    path: {target}" for target in targets
    )
    (spec_dir / "targets.yml").write_text(
        f"schema_version: 1\ntargets:\n{target_rows}\n",
        encoding="utf-8",
    )
    return spec_dir


def _rendered_task_lines(output: str) -> list[str]:
    return [line for line in output.splitlines() if re.match(r"^  T-[A-Za-z0-9-]+", line)]


@pytest.mark.unit
def test_spec_targets_prints_every_task_once_grouped_by_declared_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_spec(
        tmp_path,
        targets=("sources/api", "sources/web"),
        tasks="""# Tasks

- [ ] T-001 complexity=standard phase=api req=FR-001 depends=none target=sources/api

  **Title:** Add dashboard API contract

  **Files:**
  - `sources/api/src/dashboard.ts` — API implementation

- [ ] T-002 complexity=standard phase=web req=FR-002 depends=T-001 target=sources/web

  **Title:** Render dashboard view

  **Files:**
  - `sources/web/src/dashboard.tsx` — frontend implementation
""",
    )
    monkeypatch.chdir(tmp_path)
    cli = importlib.import_module("echelon.cli")
    handler = getattr(cli, "_cmd_spec_targets", None)

    assert callable(handler)
    handler(["001"])

    output = capsys.readouterr().out
    assert "Spec: 001-dashboard" in output
    assert "sources/api [declared]" in output
    assert "sources/web [declared]" in output
    assert "  T-001  Add dashboard API contract" in output
    assert "  T-002  Render dashboard view" in output
    assert _rendered_task_lines(output) == [
        "  T-001  Add dashboard API contract",
        "  T-002  Render dashboard view",
    ]
    assert "Tasks: 2 total; 2 assigned; 0 unowned; 0 cross-target" in output
    assert "Result: valid" in output


@pytest.mark.unit
def test_spec_targets_prints_all_invalid_groups_before_nonzero_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    spec_dir = _write_spec(
        tmp_path,
        targets=("sources/api", "sources/unused"),
        tasks="""# Tasks

- [ ] T-001 complexity=standard phase=api req=FR-001 depends=none target=sources/api

  **Title:** Add dashboard API contract

  **Files:**
  - `sources/api/src/dashboard.ts` — API implementation

- [ ] T-002 complexity=standard phase=web req=FR-002 depends=T-001 target=sources/web

  **Title:** Render dashboard view

  **Files:**
  - `sources/web/src/dashboard.tsx` — frontend implementation

- [ ] T-003 complexity=standard phase=test req=INFRA depends=T-002

  **Title:** Add workspace integration test

  **Files:**
  - `e2e/dashboard.spec.ts` — ownership is unspecified

- [ ] T-004 complexity=standard phase=integration req=INFRA depends=T-003 target=sources/api

  **Title:** Wire API and frontend

  **Files:**
  - `sources/api/src/contract.ts` — API contract
  - `sources/web/src/client.ts` — frontend client
""",
    )
    tasks_before = (spec_dir / "tasks.md").read_bytes()
    targets_before = (spec_dir / "targets.yml").read_bytes()
    monkeypatch.chdir(tmp_path)
    cli = importlib.import_module("echelon.cli")
    handler = getattr(cli, "_cmd_spec_targets", None)

    assert callable(handler)
    with pytest.raises(SystemExit) as exc:
        handler(["001"])

    assert exc.value.code == 2
    output = capsys.readouterr().out
    assert "sources/api [declared]" in output
    assert "sources/web [missing declaration]" in output
    assert "UNOWNED" in output
    assert "  T-003  Add workspace integration test" in output
    assert "CROSS-TARGET" in output
    assert "  T-004  Wire API and frontend [sources/api, sources/web]" in output
    assert "Missing declared targets:" in output
    assert "  sources/web" in output
    assert "Declared but unreferenced targets:" in output
    assert "  sources/unused" in output
    assert len(_rendered_task_lines(output)) == 4
    assert len(set(_rendered_task_lines(output))) == 4
    assert "Tasks: 4 total; 2 assigned; 1 unowned; 1 cross-target" in output
    assert "Result: invalid" in output
    assert (spec_dir / "tasks.md").read_bytes() == tasks_before
    assert (spec_dir / "targets.yml").read_bytes() == targets_before


@pytest.mark.unit
def test_spec_targets_rejects_missing_canonical_tasks_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    spec_dir = tmp_path / "specs" / "001-dashboard"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Dashboard\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    cli = importlib.import_module("echelon.cli")
    handler = getattr(cli, "_cmd_spec_targets", None)

    assert callable(handler)
    with pytest.raises(SystemExit) as exc:
        handler(["001"])

    assert exc.value.code == 1
    assert "canonical tasks file not found" in capsys.readouterr().err
