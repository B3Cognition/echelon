"""
task_queue.py — CodeTask WME model and task queue management.
Spec 008: SOAR-Powered Claude Code Software Development Agent
Version: 1.0.0

T-020: Task queue initialization — CodeTask WME Group 1.

The task decomposition produces an ordered list of CodeTask WMEs injected
into SOAR Working Memory. Each CodeTask represents a single implementation
unit scoped to one module boundary.

CodeTask WME schema (data-model.md WME Group 1):
  ^task-id        — unique task identifier (T-NNN)
  ^description    — human-readable task description
  ^scope          — component/module name (single boundary)
  ^language       — implementation language (typescript | python | go | java)
  ^status         — PENDING | IN_PROGRESS | DONE | BLOCKED
  ^complexity     — low | medium | high
  ^psi-weight     — initial Ψ contribution weight (0.0 - 1.0)
  ^depends-on     — comma-separated task IDs this task depends on
  ^module-boundary — module name this task belongs to (used for boundary validation)

FR-IMPL-006: No task may span more than one module boundary without user approval.
FR-CMD-002: Task list is injected into SOAR Working Memory as CodeTask WMEs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class TaskStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    DONE = "DONE"
    BLOCKED = "BLOCKED"


class TaskComplexity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


VALID_LANGUAGES = {"typescript", "python", "go", "java", "unknown"}


# ---------------------------------------------------------------------------
# CodeTask WME
# ---------------------------------------------------------------------------

@dataclass
class CodeTask:
    """
    A single implementation unit as a SOAR CodeTask WME.

    Each CodeTask is scoped to exactly one module boundary (FR-IMPL-006).
    The task_id follows the pattern T-NNN (zero-padded, minimum 3 digits).
    """
    task_id: str
    description: str
    scope: str                          # component name (e.g., "route_handler")
    language: str                       # typescript | python | go | java
    module_boundary: str                # module this task belongs to
    status: TaskStatus = TaskStatus.PENDING
    complexity: TaskComplexity = TaskComplexity.MEDIUM
    psi_weight: float = 1.0
    depends_on: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not re.match(r"^T-\d{3,}$", self.task_id):
            raise ValueError(
                f"task_id must match pattern T-NNN (e.g. T-001). Got: {self.task_id!r}"
            )
        if self.language.lower() not in VALID_LANGUAGES:
            raise ValueError(
                f"language must be one of {VALID_LANGUAGES}. Got: {self.language!r}"
            )
        if not 0.0 <= self.psi_weight <= 1.0:
            raise ValueError(
                f"psi_weight must be in [0.0, 1.0]. Got: {self.psi_weight}"
            )

    def to_wme_dict(self) -> dict[str, Any]:
        """Serialise as a SOAR WME injection dict."""
        return {
            "wme_type": "CodeTask",
            "task-id": self.task_id,
            "description": self.description,
            "scope": self.scope,
            "language": self.language,
            "status": self.status.value,
            "complexity": self.complexity.value,
            "psi-weight": self.psi_weight,
            "depends-on": ",".join(self.depends_on) if self.depends_on else "",
            "module-boundary": self.module_boundary,
        }


# ---------------------------------------------------------------------------
# TaskQueue
# ---------------------------------------------------------------------------

class TaskQueue:
    """
    Ordered task queue for the /codegen pipeline.

    Manages:
      - Task ordering (dependency-safe)
      - Status tracking (PENDING → IN_PROGRESS → DONE | BLOCKED)
      - Module boundary validation (FR-IMPL-006)
      - WME serialization for SOAR injection
    """

    def __init__(self, tasks: list[CodeTask] | None = None) -> None:
        self._tasks: list[CodeTask] = []
        self._by_id: dict[str, CodeTask] = {}
        if tasks:
            for t in tasks:
                self.add(t)

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def add(self, task: CodeTask) -> None:
        """Add a task to the queue. Raises if task_id is duplicate."""
        if task.task_id in self._by_id:
            raise ValueError(f"Duplicate task_id: {task.task_id!r}")
        self._tasks.append(task)
        self._by_id[task.task_id] = task

    def update_status(self, task_id: str, status: TaskStatus) -> None:
        """Update the status of an existing task."""
        task = self._by_id.get(task_id)
        if task is None:
            raise KeyError(f"Task not found: {task_id!r}")
        task.status = status

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def pending(self) -> list[CodeTask]:
        """Return tasks with status PENDING, in insertion order."""
        return [t for t in self._tasks if t.status == TaskStatus.PENDING]

    def in_progress(self) -> list[CodeTask]:
        return [t for t in self._tasks if t.status == TaskStatus.IN_PROGRESS]

    def done(self) -> list[CodeTask]:
        return [t for t in self._tasks if t.status == TaskStatus.DONE]

    def blocked(self) -> list[CodeTask]:
        return [t for t in self._tasks if t.status == TaskStatus.BLOCKED]

    def get(self, task_id: str) -> Optional[CodeTask]:
        return self._by_id.get(task_id)

    def all_tasks(self) -> list[CodeTask]:
        return list(self._tasks)

    def total(self) -> int:
        return len(self._tasks)

    def are_dependencies_met(self, task: CodeTask) -> bool:
        """
        Return True if all tasks that `task` depends on have status DONE.
        A task with no dependencies is always ready to execute.
        """
        for dep_id in task.depends_on:
            dep = self._by_id.get(dep_id)
            if dep is None or dep.status != TaskStatus.DONE:
                return False
        return True

    def next_ready(self) -> Optional[CodeTask]:
        """
        Return the first PENDING task whose dependencies are all DONE.
        Returns None if no task is currently ready.
        """
        for task in self._tasks:
            if task.status == TaskStatus.PENDING and self.are_dependencies_met(task):
                return task
        return None

    # ------------------------------------------------------------------
    # Module boundary validation (FR-IMPL-006)
    # ------------------------------------------------------------------

    def validate_module_boundaries(self) -> list[str]:
        """
        Validate that no task spans more than one module boundary.

        A task is considered multi-boundary if:
          - Its `scope` contains '/' or ',' (multi-component scope)
          - Its `module_boundary` contains '/' or ','

        Returns a list of violation messages (empty = all valid).
        FR-IMPL-006: multi-boundary tasks require user approval before pipeline proceeds.
        """
        violations: list[str] = []
        for task in self._tasks:
            if _is_multi_boundary(task.scope):
                violations.append(
                    f"{task.task_id} ({task.description[:40]}): "
                    f"scope '{task.scope}' spans multiple module boundaries. "
                    f"Split into separate tasks or obtain user approval."
                )
            if _is_multi_boundary(task.module_boundary):
                violations.append(
                    f"{task.task_id} ({task.description[:40]}): "
                    f"module_boundary '{task.module_boundary}' spans multiple modules. "
                    f"Each task must belong to exactly one module."
                )
        return violations

    # ------------------------------------------------------------------
    # WME serialization
    # ------------------------------------------------------------------

    def to_wme_group(self) -> dict[str, Any]:
        """
        Serialize the full task queue as a CodeTask WME group dict for
        SOAR Working Memory injection.
        """
        return {
            "wme_group": "CodeTask",
            "tasks": [t.to_wme_dict() for t in self._tasks],
            "total": self.total(),
            "pending": len(self.pending()),
        }

    # ------------------------------------------------------------------
    # Counters
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._tasks)

    def __iter__(self):
        return iter(self._tasks)


# ---------------------------------------------------------------------------
# Task ID generator
# ---------------------------------------------------------------------------

def generate_task_ids(n: int, prefix: str = "T") -> list[str]:
    """Generate n sequential task IDs: T-001, T-002, ... T-{n}."""
    return [f"{prefix}-{i:03d}" for i in range(1, n + 1)]


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _is_multi_boundary(value: str) -> bool:
    """Return True if the value suggests a multi-boundary scope."""
    return "/" in value or "," in value
