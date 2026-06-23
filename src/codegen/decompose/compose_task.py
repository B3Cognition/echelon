"""The mandatory terminal COMPOSE task: produces the runnable entry point and
wires all feature components. Auto-injected by DECOMPOSE so composition is a
guaranteed, dependency-gated deliverable — never the agent's responsibility."""
from __future__ import annotations

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


def inject_compose_task(queue: TaskQueue, language: str) -> CodeTask:
    """Append the single mandatory COMPOSE task depending on every existing
    feature task. Raises if a COMPOSE task is already present (idempotency)."""
    existing = [t.task_id for t in queue.all_tasks()]
    if COMPOSE_TASK_ID in existing:
        raise ValueError(f"{COMPOSE_TASK_ID} already present in queue")
    compose = build_compose_task(existing, language)
    queue.add(compose)
    return compose
