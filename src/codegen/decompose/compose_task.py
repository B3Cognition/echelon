"""The mandatory terminal COMPOSE task: produces the runnable entry point and
wires all feature components. Auto-injected by DECOMPOSE so composition is a
guaranteed, dependency-gated deliverable — never the agent's responsibility."""
from __future__ import annotations

from collections import deque

from .task_queue import CodeTask, TaskQueue, TaskComplexity

COMPOSE_TASK_ID = "T-999"   # reserved; matches ^T-\d{3,}$
COMPOSE_DESCRIPTION = (
    "Produce the runnable entry point and wire all feature components into a "
    "single composed application that satisfies runnable_contract (entry point, "
    "root composition, and any host scaffolding the chosen stack requires)."
)


def build_compose_task(feature_ids: list[str], language: str) -> CodeTask:
    return CodeTask(
        task_id=COMPOSE_TASK_ID,
        description=COMPOSE_DESCRIPTION,
        scope="composition",
        language=language,
        module_boundary="composition",
        complexity=TaskComplexity.MEDIUM,
        depends_on=list(feature_ids),
    )


def dependency_safe_order(queue: TaskQueue) -> list[str]:
    """Return task ids in a dependency-safe (topological) order using Kahn's algorithm.

    Every task appears AFTER all ids in its depends_on. Dependencies that are
    not present in the queue are treated as already-satisfied. Insertion order
    is preserved as the deterministic tie-break among tasks that are equally ready.
    """
    tasks = queue.all_tasks()
    task_ids = {t.task_id for t in tasks}
    # Build in-degree and adjacency list (dep -> dependents)
    in_degree: dict[str, int] = {t.task_id: 0 for t in tasks}
    dependents: dict[str, list[str]] = {t.task_id: [] for t in tasks}
    for t in tasks:
        for dep in t.depends_on:
            if dep in task_ids:
                in_degree[t.task_id] += 1
                dependents[dep].append(t.task_id)
    # Kahn's algorithm — ready queue preserves insertion order
    ready: deque[str] = deque(
        t.task_id for t in tasks if in_degree[t.task_id] == 0
    )
    result: list[str] = []
    while ready:
        node = ready.popleft()
        result.append(node)
        for dep_id in dependents[node]:
            in_degree[dep_id] -= 1
            if in_degree[dep_id] == 0:
                ready.append(dep_id)
    # If there are cycles (shouldn't happen) append remaining in insertion order
    remaining = [t.task_id for t in tasks if t.task_id not in result]
    result.extend(remaining)
    return result


def inject_compose_task(queue: TaskQueue, language: str) -> CodeTask:
    """Append the single mandatory COMPOSE task depending on every existing
    feature task. Raises if a COMPOSE task is already present (idempotency)."""
    existing = [t.task_id for t in queue.all_tasks()]
    if COMPOSE_TASK_ID in existing:
        raise ValueError(f"{COMPOSE_TASK_ID} already present in queue")
    compose = build_compose_task(existing, language)
    queue.add(compose)
    return compose
