"""Pure published-plan correction for an omitted runnability owner."""

from __future__ import annotations

import pytest

from harness.runnability_amendment_plan import (
    RunnabilityAmendmentPlanError,
    plan_owner_tasks,
    project_progress,
    render_owner_tasks,
)
from kernel.task_contract import validate_tasks_markdown


def _tasks(*, target: str = "apps/web", file: str = "apps/web/package.json") -> str:
    return (
        "# Tasks\n\n## Summary\n\n- Total tasks: 1\n\n## Phase: Release\n\n"
        f"- [ ] T-001 complexity=standard phase=release req=INFRA depends=none target={target}\n"
        "  **Status:** PENDING\n\n"
        "  **Title:** Existing implementation\n\n"
        "  **Files:**\n"
        f"  - `{file}` - original implementation\n\n"
        "  **Acceptance Criteria:**\n"
        "  - [ ] Existing behavior is verified.\n"
    )


def test_missing_owner_appends_pending_target_qualified_task() -> None:
    published = _tasks()

    proposals = plan_owner_tasks(published, published, ("apps/web",), ("apps/web",))

    assert len(proposals) == 1
    assert proposals[0].task_id == "T-002"
    assert proposals[0].target_id == "apps/web"
    assert proposals[0].contract_path == "apps/web/.echelon/runnability.yml"
    assert "req=INFRA depends=T-001 target=apps/web" in proposals[0].markdown
    assert "- [ ] T-002" in proposals[0].markdown
    assert "`apps/web/.echelon/runnability.yml`" in proposals[0].markdown


def test_existing_owner_or_valid_deferral_is_noop() -> None:
    owned = _tasks(file="apps/web/.echelon/runnability.yml")
    unowned = _tasks()

    assert plan_owner_tasks(owned, owned, ("apps/web",), ("apps/web",)) == ()
    assert plan_owner_tasks(unowned, unowned, ("apps/web",), ()) == ()


def test_unrecognized_old_task_change_blocks_projection() -> None:
    published = _tasks()

    with pytest.raises(RunnabilityAmendmentPlanError, match="old task definition"):
        plan_owner_tasks(
            published,
            published.replace("original implementation", "altered implementation"),
            ("apps/web",),
            ("apps/web",),
        )


def test_duplicate_owner_is_not_repaired_by_appending_third_owner() -> None:
    published = _tasks(file="apps/web/.echelon/runnability.yml")
    duplicate = (
        "\n- [ ] T-002 complexity=standard phase=release req=INFRA "
        "depends=T-001 target=apps/web\n"
        "  **Files:**\n"
        "  - `apps/web/.echelon/runnability.yml`\n"
    )
    published = published.replace("- Total tasks: 1", "- Total tasks: 2") + duplicate

    with pytest.raises(RunnabilityAmendmentPlanError, match="ambiguous owner"):
        plan_owner_tasks(published, published, ("apps/web",), ("apps/web",))


def test_malformed_task_row_is_rejected_instead_of_skipped() -> None:
    published = _tasks().replace("complexity=standard", "complexity=unknown")

    with pytest.raises(RunnabilityAmendmentPlanError, match="malformed"):
        plan_owner_tasks(published, published, ("apps/web",), ("apps/web",))


def test_multiple_targets_get_unique_ids_and_local_dependencies() -> None:
    first = _tasks()
    second = (
        "\n- [ ] T-005 complexity=standard phase=release req=INFRA "
        "depends=none target=apps/api\n"
        "  **Files:**\n"
        "  - `apps/api/package.json`\n"
    )
    published = first.replace("- Total tasks: 1", "- Total tasks: 2") + second

    proposals = plan_owner_tasks(
        published,
        published,
        ("apps/web", "apps/api"),
        ("apps/web", "apps/api"),
    )

    assert [(item.target_id, item.task_id) for item in proposals] == [
        ("apps/web", "T-006"),
        ("apps/api", "T-007"),
    ]
    assert "depends=T-001 target=apps/web" in proposals[0].markdown
    assert "depends=T-005 target=apps/api" in proposals[1].markdown
    assert "`apps/api/.echelon/runnability.yml`" in proposals[1].markdown


def test_progress_projection_keeps_old_task_bytes_and_adds_valid_task() -> None:
    published = _tasks()
    working = published.replace("- [ ] T-001", "- [x] T-001")
    working = working.replace("**Status:** PENDING", "**Status:** DONE")
    working = working.replace("- [ ] Existing behavior", "- [x] Existing behavior")
    proposals = plan_owner_tasks(published, working, ("apps/web",), ("apps/web",))
    proposed_tasks = published.replace("- Total tasks: 1", "- Total tasks: 2") + proposals[0].markdown

    projected = project_progress(published, working, proposed_tasks)

    assert projected.startswith(working.replace("- Total tasks: 1", "- Total tasks: 2"))
    assert projected.endswith(proposals[0].markdown)
    assert validate_tasks_markdown(projected).valid
    assert validate_tasks_markdown(projected).task_count == 2


def test_projection_refuses_old_task_definition_change_in_proposed_commit() -> None:
    published = _tasks()
    working = published.replace("- [ ] T-001", "- [x] T-001")
    proposed = published.replace("- Total tasks: 1", "- Total tasks: 2")
    proposed = proposed.replace("original implementation", "surreptitious rewrite")
    proposed += (
        "\n- [ ] T-002 complexity=standard phase=release req=INFRA "
        "depends=T-001 target=apps/web\n"
    )

    with pytest.raises(RunnabilityAmendmentPlanError, match="old task definition"):
        project_progress(published, working, proposed)


def test_render_updates_real_plan_footer_counts_without_rewriting_old_task() -> None:
    published = _tasks() + (
        "\n## Checkpoint: Release Complete\n\n"
        "**Verify before continuing:**\n"
        "- [ ] All canonical release task rows are complete.\n\n"
        "## Summary by Phase\n\n"
        "| Phase | Tasks | Most-likely effort | Notes |\n"
        "| --- | ---: | ---: | --- |\n"
        "| release | 1 | 0.25 person-day | Original work |\n"
        "| **Total** | **1** | **0.25 person-day** | Original estimate |\n"
    )
    proposals = plan_owner_tasks(published, published, ("apps/web",), ("apps/web",))

    amended = render_owner_tasks(published, proposals)

    assert "- Total tasks: 2" in amended
    assert "| release | 2 | 0.25 person-day | Original work |" in amended
    assert "| **Total** | **2** | **0.25 person-day** | Original estimate |" in amended
    assert amended.startswith(published.split("## Summary by Phase")[0].replace(
        "- Total tasks: 1", "- Total tasks: 2"))
    assert amended.endswith(proposals[0].markdown)
    assert validate_tasks_markdown(amended).task_count == 2
