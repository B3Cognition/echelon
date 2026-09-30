"""Canonical scope and strict dispatch-bound results for delivery slices."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re

from harness.task_progress import summarize_task_progress
from kernel.task_contract import parse_task_rows
from harness.coverage_evidence import task_owned_coverage_case_ids
from harness.coverage_contract import is_coverage_case_id
from harness.runnability_contract import CONTRACT_PATH as RUNNABILITY_CONTRACT_PATH
from harness.task_targets import task_declares_file


class DeliverySliceError(ValueError):
    """A slice cannot be dispatched or accepted under its declared contract."""


class DeliveryTasksComplete(DeliverySliceError):
    """No implementation remains in scope; authoritative verification is still owed."""


def _delivery_failure_cases_by_owner(
    spec_dir: Path, feedback: dict, allowed_task_ids: set[str] | None,
) -> dict[str, list[str]]:
    """Validate every failure before grouping uniquely owned, in-scope cases."""
    def blocked(reason: str) -> None:
        raise DeliverySliceError("delivery_repair_ownership_required: " + reason)

    failures = feedback.get("failures")
    if not isinstance(failures, list) or not failures:
        blocked("missing failed test identity")
    cases: set[str] = set()
    for failure in failures:
        if not isinstance(failure, dict):
            blocked("invalid failure evidence")
        details = failure.get("details", {})
        if not isinstance(details, dict):
            blocked("invalid failure details")
        if details.get("unidentified_test_failures", 0) != 0:
            blocked("unidentified test failures remain")
        ids = details.get("failed_test_case_ids")
        if ids is None and failure.get("id") == "coverage-observation-gaps":
            observed = details.get("test_cases")
            if isinstance(observed, dict):
                statuses = {"unbound", "duplicate_binding", "invalid_report",
                            "observer_missing", "observer_failed", "provenance_mismatch",
                            "failed", "skipped", "not_executed"}
                if any(not isinstance(value, dict) or value.get("status") not in statuses
                       for value in observed.values()):
                    blocked("invalid coverage failure identity")
                ids = list(observed)
        if ids is None and is_coverage_case_id(str(failure.get("id", ""))):
            ids = [failure["id"]]
        if (not isinstance(ids, list) or not ids
                or any(not isinstance(case, str) or not is_coverage_case_id(case) for case in ids)):
            blocked("missing failed test identity for " + str(failure.get("id", "unknown")))
        cases.update(ids)
    ownership = task_owned_coverage_case_ids(spec_dir / "tasks.md")
    owners: dict[str, list[str]] = {}
    for case in sorted(cases):
        matches = {task for task, owned in ownership.items() if case in owned}
        if len(matches) != 1:
            blocked(f"no unique owner for {case}: {', '.join(sorted(matches)) or 'none'}")
        task_id = next(iter(matches))
        if allowed_task_ids is not None and task_id not in allowed_task_ids:
            blocked(f"{task_id} is outside the permitted target scope")
        owners.setdefault(task_id, []).append(case)
    return owners


def resolve_delivery_failure_owner(
    spec_dir: Path, feedback: dict, allowed_task_ids: set[str] | None,
) -> dict[str, object]:
    """Resolve one strict owner; browser handoffs must never select a subset."""
    owners = _delivery_failure_cases_by_owner(spec_dir, feedback, allowed_task_ids)
    if len(owners) != 1:
        raise DeliverySliceError(
            "delivery_repair_ownership_required: multiple task owners: " + ", ".join(sorted(owners))
        )
    task_id = next(iter(owners))
    return {"task_id": task_id, "failed_test_case_ids": owners[task_id],
            "reason": "unique_test_case_owner"}


def select_delivery_repair_task(
    spec_dir: Path, feedback: dict, allowed_task_ids: set[str] | None,
) -> dict[str, object]:
    """Bind one accepted owner, deriving remaining coverage debt on reverify.

    Ralph retains the complete failure report in its existing durable operation.
    Only the selected owner's cases authorize this repair; there is no persisted
    queue and pending operations continue replaying their original selection.
    Other failure formats retain strict single-owner resolution.
    """
    failures = feedback.get("failures")
    if (isinstance(failures, list) and len(failures) == 1
            and isinstance(failures[0], dict)
            and failures[0].get("id") in {
                "user-runnability-contract-missing",
                "user-runnability-contract-invalid",
                "user-runnability-contract-disabled",
            }):
        details = failures[0].get("details")
        if (not isinstance(details, dict)
                or details.get("contract") != RUNNABILITY_CONTRACT_PATH.as_posix()
                or details.get("unidentified_test_failures", 0) != 0
                or "failed_test_case_ids" in details):
            raise DeliverySliceError("delivery_repair_ownership_required: invalid runnability contract identity")
        text = (spec_dir / "tasks.md").read_text(encoding="utf-8")
        owner_rows = [row for row in parse_task_rows(text)
                      if task_declares_file(
                          text, row.task_id,
                          (Path(row.target or ".") / RUNNABILITY_CONTRACT_PATH).as_posix(),
                      )]
        owners_by_target: dict[str, list[str]] = {}
        for row in owner_rows:
            owners_by_target.setdefault(row.target or ".", []).append(row.task_id)
        if any(len(owners) != 1 for owners in owners_by_target.values()):
            raise DeliverySliceError("delivery_repair_ownership_required: runnability contract has "
                                     "multiple declared task owners for one target")
        owners = [row.task_id for row in owner_rows
                  if allowed_task_ids is None or row.task_id in allowed_task_ids]
        if len(owners) != 1:
            raise DeliverySliceError("delivery_repair_ownership_required: runnability contract has "
                                     f"{len(owners)} declared task owners in the permitted target scope")
        task_id = owners[0]
        summary = summarize_task_progress(text)
        if not summary.valid or summary.task_statuses.get(task_id) not in {"DONE", "DONE_WITH_CONCERNS"}:
            raise DeliverySliceError(f"delivery_repair_ownership_required: {task_id} is not an accepted task eligible for repair")
        return {"task_id": task_id, "failed_test_case_ids": [],
                "reason": "unique_runnability_contract_owner"}
    coverage_only = isinstance(failures, list) and bool(failures) and all(
        isinstance(failure, dict) and failure.get("id") == "coverage-observation-gaps"
        and isinstance(failure.get("details"), dict)
        and isinstance(failure["details"].get("test_cases"), dict)
        and "failed_test_case_ids" not in failure["details"]
        for failure in failures
    )
    if coverage_only:
        owners = _delivery_failure_cases_by_owner(spec_dir, feedback, allowed_task_ids)
        text = (spec_dir / "tasks.md").read_text(encoding="utf-8")
        summary = summarize_task_progress(text)
        for task_id in owners:
            if not summary.valid or summary.task_statuses.get(task_id) not in {"DONE", "DONE_WITH_CONCERNS"}:
                raise DeliverySliceError(
                    f"delivery_repair_ownership_required: {task_id} is not an accepted task eligible for repair"
                )
        task_id = next(row.task_id for row in parse_task_rows(text) if row.task_id in owners)
        return {"task_id": task_id, "failed_test_case_ids": owners[task_id],
                "reason": "unique_test_case_owner"}
    selection = resolve_delivery_failure_owner(spec_dir, feedback, allowed_task_ids)
    task_id = selection["task_id"]
    summary = summarize_task_progress((spec_dir / "tasks.md").read_text(encoding="utf-8"))
    if not summary.valid or summary.task_statuses.get(task_id) not in {"DONE", "DONE_WITH_CONCERNS"}:
        raise DeliverySliceError(
            f"delivery_repair_ownership_required: {task_id} is not an accepted task eligible for repair"
        )
    return selection


STEP_VERDICTS = {
    "implementer": frozenset({"DONE", "BLOCKED", "NEEDS_CONTEXT", "BROWSER_EVIDENCE_REQUIRED"}),
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
    if repair_task_id is None and scope <= done:
        required = set(scope)
        pending = list(scope)
        while pending:
            for dependency in by_id[pending.pop()].dependencies:
                if dependency not in required:
                    required.add(dependency)
                    pending.append(dependency)
        if required <= done:
            raise DeliveryTasksComplete("delivery task scope is complete")
    raise DeliverySliceError("no dependency-ready task in the permitted scope")


def validate_delivery_result(raw: str, assignment: DeliveryAssignment) -> dict[str, object]:
    """No markers, Markdown fences, implicit success, skips, or stale responses."""
    if len(raw.encode("utf-8")) > 100_000:
        raise DeliverySliceError("delivery result exceeds size limit")
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise DeliverySliceError("delivery result must be JSON") from exc
    identity = assignment.identity()
    if not isinstance(payload, dict):
        raise DeliverySliceError("invalid delivery result fields")
    browser_request = payload.get("verdict") == "BROWSER_EVIDENCE_REQUIRED"
    expected_fields = set(identity) | {"verdict", "summary", "findings"}
    if browser_request:
        expected_fields.add("browser_evidence_request")
    if assignment.step in {"spec_guard", "test_guardian"} and "reviewed_test_paths" in payload:
        expected_fields.add("reviewed_test_paths")
    if set(payload) != expected_fields:
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
    if "reviewed_test_paths" in payload:
        paths = payload["reviewed_test_paths"]
        if (not isinstance(paths, list) or len(paths) > 500
                or any(not _valid_review_test_path(path) for path in paths)
                or len(set(paths)) != len(paths)):
            raise DeliverySliceError("invalid reviewed test paths")
    if browser_request:
        if findings or payload["browser_evidence_request"] != {"purpose": "baseline_capture"}:
            raise DeliverySliceError("invalid browser evidence request")
    return payload


def bind_delivery_result(raw: str, assignment: DeliveryAssignment) -> dict[str, object]:
    """Bind controller-owned fingerprints after strict transport identity validation.

    Providers must still return the complete result envelope.  The dispatch,
    step, task, and schema fields prove which call produced the response.  The
    two long content fingerprints are controller observations, so their raw
    echoes are retained for diagnosis but never made authoritative by a model.
    """
    if len(raw.encode("utf-8")) > 100_000:
        raise DeliverySliceError("delivery result exceeds size limit")
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise DeliverySliceError("delivery result must be JSON") from exc
    identity = assignment.identity()
    if not isinstance(payload, dict):
        raise DeliverySliceError("invalid delivery result fields")
    expected_fields = set(identity) | {"verdict", "summary", "findings"}
    if payload.get("verdict") == "BROWSER_EVIDENCE_REQUIRED":
        expected_fields.add("browser_evidence_request")
    if assignment.step in {"spec_guard", "test_guardian"} and "reviewed_test_paths" in payload:
        expected_fields.add("reviewed_test_paths")
    if set(payload) != expected_fields:
        raise DeliverySliceError("invalid delivery result fields")
    for key in ("schema_version", "dispatch_id", "step", "task_id"):
        if type(payload[key]) is not type(identity[key]) or payload[key] != identity[key]:
            raise DeliverySliceError("delivery result identity mismatch")
    for key in ("candidate_fingerprint", "input_fingerprint"):
        if not isinstance(payload[key], str) or not payload[key] or len(payload[key]) > 128:
            raise DeliverySliceError("invalid delivery result fingerprint echo")
    bound = dict(payload)
    bound["candidate_fingerprint"] = assignment.candidate_fingerprint
    bound["input_fingerprint"] = assignment.input_fingerprint
    return validate_delivery_result(json.dumps(bound), assignment)


def _valid_review_test_path(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and not value.startswith("/")
        and not re.match(r"^[A-Za-z]:", value)
        and "\\" not in value
        and not any(ord(char) < 32 for char in value)
        and all(part not in {"", ".", ".."} for part in value.split("/"))
    )
