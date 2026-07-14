from __future__ import annotations

from pathlib import Path

from harness.deferred_scope import (
    apply_defer,
    apply_restore,
    plan_defer,
    read_ledger,
)


def _spec(tmp_path: Path, *, tasks: str, requirements: str) -> Path:
    spec_dir = tmp_path / "specs" / "906-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text(requirements, encoding="utf-8")
    (spec_dir / "tasks.md").write_text(tasks, encoding="utf-8")
    return spec_dir


def test_defer_requirement_derives_only_direct_mapped_tasks(tmp_path: Path) -> None:
    spec_dir = _spec(
        tmp_path,
        tasks=(
            "- [ ] T-001 complexity=standard phase=build req=NFR-008,FR-001 depends=none\n"
            "- [ ] T-002 complexity=standard phase=build req=FR-001 depends=T-001\n"
        ),
        requirements="FR-001\nNFR-008\n",
    )

    plan = plan_defer(spec_dir, ["NFR-008"], reason="contradictory contrast rule")

    assert plan.selected_ids == ("NFR-008",)
    assert plan.derived_task_ids == ("T-001",)
    assert plan.related_active_ids == ("FR-001",)


def test_restore_preserves_deferral_history(tmp_path: Path) -> None:
    spec_dir = _spec(
        tmp_path,
        tasks="- [ ] T-001 complexity=standard phase=build req=NFR-008 depends=none\n",
        requirements="NFR-008\n",
    )

    apply_defer(spec_dir, ["NFR-008"], reason="owner decision")
    apply_restore(spec_dir, ["NFR-008"])

    entry = read_ledger(spec_dir).entries[0]
    assert entry.status == "planned"
    assert entry.reason == "owner decision"
    assert entry.planned_at is not None


def test_defer_marks_derived_pending_task_and_plan_restores_it(tmp_path: Path) -> None:
    spec_dir = _spec(
        tmp_path,
        tasks="- [ ] T-001 complexity=standard phase=build req=NFR-008 depends=none\n",
        requirements="NFR-008\n",
    )

    apply_defer(spec_dir, ["NFR-008"], reason="owner decision")
    assert "**Status:** DEFERRED" in (spec_dir / "tasks.md").read_text(encoding="utf-8")

    apply_restore(spec_dir, ["NFR-008"])
    assert "**Status:** PENDING" in (spec_dir / "tasks.md").read_text(encoding="utf-8")
