import pytest
from codegen.decompose.task_queue import CodeTask, TaskQueue, TaskStatus
from codegen.decompose.compose_task import (
    build_compose_task, inject_compose_task, COMPOSE_TASK_ID, dependency_safe_order,
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
def test_dependency_safe_order_puts_compose_last():
    """After inject_compose_task, dependency_safe_order must return COMPOSE_TASK_ID last,
    with all feature tasks preceding it."""
    q = TaskQueue([_feature(1), _feature(2)])
    inject_compose_task(q, language="typescript")
    order = dependency_safe_order(q)
    assert order[-1] == COMPOSE_TASK_ID
    assert "T-001" in order
    assert "T-002" in order
    assert order.index("T-001") < order.index(COMPOSE_TASK_ID)
    assert order.index("T-002") < order.index(COMPOSE_TASK_ID)


@pytest.mark.unit
def test_dependency_safe_order_respects_feature_deps():
    """dependency_safe_order must respect depends_on among feature tasks too:
    if T-002 depends on T-001, T-001 must appear before T-002."""
    q = TaskQueue([
        _feature(1),
        CodeTask(task_id="T-002", description="feature 2 depends on 1", scope="c2",
                 language="typescript", module_boundary="m2", depends_on=["T-001"]),
    ])
    order = dependency_safe_order(q)
    assert order.index("T-001") < order.index("T-002")


@pytest.mark.unit
def test_decompose_phase_invokes_compose_injection():
    import pathlib
    spec = pathlib.Path("runtime/workflow/phases/codegen-2-decompose.md").read_text()
    assert "inject_compose_task" in spec
    assert "T-999" in spec or "COMPOSE_TASK_ID" in spec
