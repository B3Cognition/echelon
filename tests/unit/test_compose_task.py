import pytest
from codegen.decompose.task_queue import CodeTask, TaskQueue, TaskStatus
from codegen.decompose.compose_task import (
    build_compose_task, inject_compose_task, COMPOSE_TASK_ID,
)


def _feature(n):
    return CodeTask(task_id=f"T-{n:03d}", description=f"feature {n}", scope=f"c{n}",
                    language="typescript", module_boundary=f"m{n}")


@pytest.mark.unit
def test_compose_task_has_valid_id_and_depends_on_all_features():
    q = TaskQueue([_feature(1), _feature(2)])
    compose = inject_compose_task(q, language="typescript")
    assert compose.task_id == COMPOSE_TASK_ID            # "T-999", matches ^T-\d{3,}$
    assert compose.scope == "composition"
    assert set(compose.depends_on) == {"T-001", "T-002"}


@pytest.mark.unit
def test_compose_runs_last_only_after_features_done():
    q = TaskQueue([_feature(1), _feature(2)])
    inject_compose_task(q, language="typescript")
    # COMPOSE not ready while features pending
    assert q.next_ready().task_id == "T-001"
    q.get("T-001").status = TaskStatus.DONE
    q.get("T-002").status = TaskStatus.DONE
    assert q.next_ready().task_id == COMPOSE_TASK_ID     # now COMPOSE is ready, last


@pytest.mark.unit
def test_decompose_phase_invokes_compose_injection():
    import pathlib
    spec = pathlib.Path("extension/workflow/phases/codegen-2-decompose.md").read_text()
    assert "inject_compose_task" in spec
    assert "T-999" in spec or "COMPOSE_TASK_ID" in spec
