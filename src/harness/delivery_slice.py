"""Canonical scope and strict dispatch-bound results for delivery slices."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re

from harness.task_progress import summarize_task_progress
from kernel.task_contract import parse_task_rows


class DeliverySliceError(ValueError):
    """A slice cannot be dispatched or accepted under its declared contract."""


STEP_VERDICTS = {
    "implementer": frozenset({"DONE", "BLOCKED", "NEEDS_CONTEXT"}),
    "spec_guard": frozenset({"PASS", "FAIL"}),
    "code_reviewer": frozenset({"APPROVED", "CHANGES_REQUESTED", "BLOCKED"}),
    "test_guardian": frozenset({"PASS", "FAIL"}),
}
PASSING_VERDICTS = frozenset({"DONE", "PASS", "APPROVED"})


@dataclass(frozen=True)
class DeliveryAssignment:
    dispatch_id: str
    step: str
    task_id: str
    candidate_fingerprint: str
    input_fingerprint: str
    schema_version: int = 1

    def identity(self) -> dict[str, object]:
        return asdict(self)


def select_delivery_task(
    spec_dir: Path, allowed_task_ids: set[str] | None = None,
    repair_task_id: str | None = None,
) -> str:
    """Pick one ready task; explicit empty scope never means unrestricted."""
    markdown = (spec_dir / "tasks.md").read_text(encoding="utf-8")
    markdown = "\n".join(line.rstrip() for line in markdown.splitlines())
    rows = parse_task_rows(markdown)
    summary = summarize_task_progress(markdown)
    if not summary.valid:
        raise DeliverySliceError("invalid task inventory: " + "; ".join(summary.errors))
    # The shared parser skips malformed rows. Do not silently skip work here.
    unfenced = re.sub(r"(?ms)^```.*?^```[^\n]*", "", markdown)
    if len(re.findall(r"(?m)^- \[[ xX]\]\s+T-", unfenced)) != len(rows):
        raise DeliverySliceError("malformed canonical task row")
    by_id = {row.task_id: row for row in rows}
    scope = set(by_id) if allowed_task_ids is None else set(allowed_task_ids)
    if not scope or not scope.issubset(by_id):
        raise DeliverySliceError("empty or unknown delivery task scope")
    # Validate the whole graph before selecting a dependency-ready node.
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(task_id: str) -> None:
        if task_id not in by_id:
            raise DeliverySliceError(f"unknown dependency: {task_id}")
        if task_id in visiting:
            raise DeliverySliceError(f"dependency cycle at {task_id}")
        if task_id in visited:
            return
        visiting.add(task_id)
        for dependency in by_id[task_id].dependencies:
            visit(dependency)
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in by_id:
        visit(task_id)
    done = {key for key, value in summary.task_statuses.items()
            if value in {"DONE", "DONE_WITH_CONCERNS"}}
    if repair_task_id is not None:
        if repair_task_id not in scope:
            raise DeliverySliceError("repair task is outside the permitted scope")
        candidates = [by_id[repair_task_id]]
    else:
        candidates = [row for row in rows if row.task_id in scope
                      and summary.task_statuses[row.task_id] == "PENDING"]
    for row in candidates:
        if all(dependency in done for dependency in row.dependencies):
            return row.task_id
    raise DeliverySliceError("no dependency-ready task; finalization-only dispatch is not migrated")


def validate_delivery_result(raw: str, assignment: DeliveryAssignment) -> dict[str, object]:
    """No markers, Markdown fences, implicit success, skips, or stale responses."""
    if len(raw.encode("utf-8")) > 100_000:
        raise DeliverySliceError("delivery result exceeds size limit")
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise DeliverySliceError("delivery result must be JSON") from exc
    identity = assignment.identity()
    if not isinstance(payload, dict) or set(payload) != set(identity) | {"verdict", "summary", "findings"}:
        raise DeliverySliceError("invalid delivery result fields")
    if type(payload["schema_version"]) is not int or any(payload[key] != value for key, value in identity.items()):
        raise DeliverySliceError("delivery result identity mismatch")
    verdict = payload["verdict"]
    if not isinstance(verdict, str) or verdict not in STEP_VERDICTS.get(assignment.step, ()):
        raise DeliverySliceError("unsupported delivery verdict")
    summary = payload["summary"]
    findings = payload["findings"]
    if not isinstance(summary, str) or not summary.strip() or len(summary) > 8000:
        raise DeliverySliceError("invalid delivery summary")
    if not isinstance(findings, list) or len(findings) > 50 or any(
        not isinstance(item, str) or not item.strip() or len(item) > 8000 for item in findings
    ):
        raise DeliverySliceError("invalid delivery findings")
    if verdict in PASSING_VERDICTS and findings:
        raise DeliverySliceError("passing result cannot contain unresolved findings")
    if verdict in {"FAIL", "CHANGES_REQUESTED"} and not findings:
        raise DeliverySliceError("failed review must identify findings")
    return payload
