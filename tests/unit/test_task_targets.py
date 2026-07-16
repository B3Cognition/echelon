from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


TASKS = """# Tasks

- [ ] T-001 complexity=standard phase=api req=FR-001 depends=none target=sources/api

  **Title:** Add dashboard API contract

  **Files:**
  - `sources/api/src/dashboard.ts` — API implementation

- [ ] T-002 complexity=standard phase=web req=FR-002 depends=T-001 target=sources/web

  **Title:** Render dashboard view

  **Files:**
  - `sources/web/src/dashboard.tsx` — frontend implementation

- [ ] T-003 complexity=standard phase=test req=INFRA depends=T-002

  **Files:**
  - `e2e/dashboard.spec.ts` — cross-repo test with unspecified ownership
"""


@pytest.mark.unit
def test_task_target_analysis_maps_qualified_source_paths() -> None:
    module = importlib.import_module("harness.task_targets")

    analysis = module.analyze_task_targets(TASKS)

    assert analysis.target_tasks == {
        "sources/api": ("T-001",),
        "sources/web": ("T-002",),
    }
    assert analysis.unowned_tasks == ("T-003",)
    assert analysis.cross_target_tasks == {}
    assert analysis.task_titles == {
        "T-001": "Add dashboard API contract",
        "T-002": "Render dashboard view",
        "T-003": "",
    }


@pytest.mark.unit
def test_explicit_task_target_is_authoritative_without_files_section() -> None:
    module = importlib.import_module("harness.task_targets")
    tasks = """# Tasks

- [ ] T-001 complexity=standard phase=api req=FR-001 depends=none target=sources/api

  **Title:** Add dashboard API contract
"""

    analysis = module.analyze_task_targets(tasks)

    assert analysis.target_tasks == {"sources/api": ("T-001",)}
    assert analysis.unowned_tasks == ()


@pytest.mark.unit
def test_explicit_task_target_rejects_mismatched_files_source() -> None:
    module = importlib.import_module("harness.task_targets")
    tasks = """# Tasks

- [ ] T-001 complexity=standard phase=api req=FR-001 depends=none target=sources/api

  **Files:**
  - `sources/web/src/dashboard.tsx` — wrong repository
"""

    result = module.validate_task_targets(
        tasks,
        declared_targets=["sources/api", "sources/web"],
    )

    assert result.valid is False
    assert result.path_target_mismatches == {
        "T-001": ("sources/api", ("sources/web",)),
    }


@pytest.mark.unit
def test_task_target_validation_reports_optasearch_style_mismatch() -> None:
    module = importlib.import_module("harness.task_targets")

    result = module.validate_task_targets(
        TASKS,
        declared_targets=["sources/selected-web"],
    )

    assert result.valid is False
    assert result.missing_targets == ("sources/api", "sources/web")
    assert result.unreferenced_targets == ("sources/selected-web",)
    assert result.unowned_tasks == ("T-003",)
    assert result.task_titles["T-001"] == "Add dashboard API contract"


@pytest.mark.unit
def test_single_target_tasks_may_use_repo_relative_paths() -> None:
    module = importlib.import_module("harness.task_targets")
    tasks = TASKS.replace("sources/api/src/dashboard.ts", "src/dashboard.ts").replace(
        "sources/web/src/dashboard.tsx", "src/dashboard.tsx"
    ).replace("target=sources/api", "target=sources/app").replace(
        "target=sources/web", "target=sources/app"
    )

    result = module.validate_task_targets(tasks, declared_targets=["sources/app"])

    assert result.valid is True
    assert result.target_tasks == {"sources/app": ("T-001", "T-002", "T-003")}


@pytest.mark.unit
def test_cross_target_task_must_be_split() -> None:
    module = importlib.import_module("harness.task_targets")
    tasks = TASKS.replace(
        "- `sources/api/src/dashboard.ts` — API implementation",
        "- `sources/api/src/dashboard.ts` — API implementation\n"
        "  - `sources/web/src/client.ts` — frontend implementation",
    )

    result = module.validate_task_targets(
        tasks,
        declared_targets=["sources/api", "sources/web"],
    )

    assert result.valid is False
    assert result.cross_target_tasks == {
        "T-001": ("sources/api", "sources/web"),
    }


@pytest.mark.unit
def test_validate_task_targets_never_rewrites_declared_repositories(
    tmp_path: Path,
    monkeypatch,
) -> None:
    spec_dir = tmp_path / "specs" / "001-dashboard"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Dashboard\n", encoding="utf-8")
    from harness.spec_frontmatter import write_targets

    write_targets(spec_dir, ["sources/api", "sources/web"])
    (spec_dir / "tasks.md").write_text(
        TASKS.replace(
            "depends=T-002",
            "depends=T-002 target=sources/web",
        ).replace(
            "- `e2e/dashboard.spec.ts` — cross-repo test with unspecified ownership",
            "- `sources/web/e2e/dashboard.spec.ts` — frontend E2E test",
        ),
        encoding="utf-8",
    )
    before = (spec_dir / "targets.yml").read_text(encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        ["python -m harness", "validate-task-targets", str(spec_dir)],
    )

    from harness.__main__ import main

    main()

    assert (spec_dir / "targets.yml").read_text(encoding="utf-8") == before
