"""BuildResult — structured outcome of a claude -p build invocation."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from kernel.task_contract import TASK_ID_PATTERN

# Filename written by build-8-finalize (and codegen-7-deliver) to signal build outcome.
BUILD_STATUS_FILENAME = ".harness-build-status.json"
ECHELON_RESULT_FILENAME = "echelon_result.json"

_DONE_STATUS_ALIASES = {
    "build_done",
    "done",
    "iteration_done",
    "partial",
    "progress",
}
_OUTPUT_DONE_STATUSES = _DONE_STATUS_ALIASES | {
    "complete",
    "completed",
    "pass",
    "passed",
}
_OUTPUT_JSON_FENCE_RE = re.compile(
    r"```(?:json)?\s*(?P<body>\{.*?\})\s*```",
    re.IGNORECASE | re.DOTALL,
)
_TASK_ID_RE = re.compile(rf"^{TASK_ID_PATTERN}$")


def _normalize_status(status: object) -> str:
    raw = str(status or "unknown").strip()
    if not raw:
        return "unknown"
    normalized = raw.lower().replace("-", "_")
    if normalized in _DONE_STATUS_ALIASES:
        return "done"
    if normalized in {"blocked", "error", "impasse", "timeout", "unknown"}:
        return normalized
    return raw


@dataclass
class BuildResult:
    """Outcome of one LLM build or feedback invocation.

    status values:
      "done"     — build completed, files written to worktree
      "impasse"  — build hit an unresolvable conflict (codegen only)
      "timeout"  — claude -p process exceeded timeout_ms
      "unknown"  — status file missing or unreadable
    """
    exit_code: int
    status: str
    impasse_file: Optional[str]
    stdout: str
    stderr: str
    duration_ms: int
    token_usage: int = 0
    reason: Optional[str] = None
    task_ids: list[str] | None = None

    def __post_init__(self) -> None:
        self.status = _normalize_status(self.status)

    @property
    def succeeded(self) -> bool:
        return self.status == "done"

    @property
    def is_impasse(self) -> bool:
        return self.status == "impasse"

    @classmethod
    def from_status_file(
        cls,
        path: Path,
        *,
        exit_code: int,
        stdout: str,
        stderr: str,
        duration_ms: int,
    ) -> "BuildResult":
        """Read status from HARNESS_BUILD_STATUS_FILE, fall back to 'unknown'."""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("status file must be a JSON object")
            return cls._from_status_payload(
                data,
                exit_code=exit_code,
                stdout=stdout,
                stderr=stderr,
                duration_ms=duration_ms,
            )
        except Exception:
            return cls(
                exit_code=exit_code,
                status="unknown",
                impasse_file=None,
                reason=None,
                task_ids=None,
                stdout=stdout,
                stderr=stderr,
                duration_ms=duration_ms,
                token_usage=0,
            )

    @classmethod
    def from_echelon_result_file(
        cls,
        path: Path,
        *,
        exit_code: int,
        stdout: str,
        stderr: str,
        duration_ms: int,
    ) -> "BuildResult":
        """Recover only an explicit legacy blocker from an otherwise untrusted file."""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if (
                not isinstance(data, dict)
                or str(data.get("verdict") or "").strip().upper() != "BLOCKED"
            ):
                raise ValueError("echelon result must explicitly report BLOCKED")
            return cls._from_status_payload(
                data,
                exit_code=exit_code,
                stdout=stdout,
                stderr=stderr,
                duration_ms=duration_ms,
            )
        except Exception:
            return cls(
                exit_code=exit_code,
                status="unknown",
                impasse_file=None,
                reason=None,
                task_ids=None,
                stdout=stdout,
                stderr=stderr,
                duration_ms=duration_ms,
                token_usage=0,
            )

    @classmethod
    def _from_status_payload(
        cls,
        data: dict[str, object],
        *,
        exit_code: int,
        stdout: str,
        stderr: str,
        duration_ms: int,
    ) -> "BuildResult":
        verdict = str(data.get("verdict") or "").strip().upper()
        state_updates = data.get("state_updates")
        if not isinstance(state_updates, dict):
            state_updates = {}
        reason = data.get("reason")
        if verdict == "BLOCKED":
            reason = (
                reason
                or state_updates.get("blocked_reason")
                or state_updates.get("fulfillment_gap_blocked")
                or "build agent reported a blocker"
            )
        return cls(
            exit_code=exit_code,
            status="blocked" if verdict == "BLOCKED" else str(data.get("status", "unknown")),
            impasse_file=data.get("impasse_file"),
            reason=str(reason) if reason is not None else None,
            task_ids=_task_ids(data),
            stdout=stdout,
            stderr=stderr,
            duration_ms=duration_ms,
            token_usage=0,
        )


def _task_ids(data: dict[str, object]) -> list[str]:
    raw = data.get("completed_task_ids", data.get("task_ids"))
    if not isinstance(raw, list):
        return []
    ids: list[str] = []
    for value in raw:
        task_id = str(value).strip()
        if task_id:
            ids.append(task_id)
    return ids


def recover_done_result_from_output(
    *,
    stdout: str,
    stderr: str,
    exit_code: int,
    duration_ms: int,
) -> Optional[BuildResult]:
    """Recover a successful build result from explicit final JSON output.

    This is a narrow missing-marker escape hatch. It accepts only valid JSON
    objects that declare a successful status and canonical completed task IDs.
    Prose summaries such as ``completed_task_ids: [...]`` are intentionally not
    interpreted.
    """
    if exit_code != 0:
        return None
    for data in _output_json_objects(stdout, stderr):
        for payload in _candidate_payloads(data):
            if not _is_done_status(payload.get("status")):
                continue
            task_ids = _task_ids_from_output_payload(payload)
            if not task_ids:
                continue
            return BuildResult(
                exit_code=exit_code,
                status="done",
                impasse_file=None,
                reason=(
                    "recovered completed_task_ids from final JSON output after "
                    f"missing {BUILD_STATUS_FILENAME}"
                ),
                task_ids=task_ids,
                stdout=stdout,
                stderr=stderr,
                duration_ms=duration_ms,
                token_usage=0,
            )
    return None


def _output_json_objects(stdout: str, stderr: str) -> Iterable[dict[str, object]]:
    text = "\n".join(part for part in (stdout, stderr) if part)
    seen: set[str] = set()
    for match in _OUTPUT_JSON_FENCE_RE.finditer(text):
        body = match.group("body").strip()
        if body in seen:
            continue
        seen.add(body)
        parsed = _parse_json_object(body)
        if parsed is not None:
            yield parsed

    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}") and stripped not in seen:
        parsed = _parse_json_object(stripped)
        if parsed is not None:
            yield parsed


def _parse_json_object(raw: str) -> Optional[dict[str, object]]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return data


def _candidate_payloads(data: dict[str, object]) -> Iterable[dict[str, object]]:
    yield data
    nested = data.get("echelon_result")
    if isinstance(nested, dict):
        yield nested


def _is_done_status(status: object) -> bool:
    raw = str(status or "unknown").strip().lower().replace("-", "_")
    return raw in _OUTPUT_DONE_STATUSES


def _task_ids_from_output_payload(data: dict[str, object]) -> list[str]:
    task_ids = _canonical_task_ids(_task_ids(data))
    if task_ids:
        return task_ids
    state_updates = data.get("state_updates")
    if isinstance(state_updates, dict):
        return _canonical_task_ids(_task_ids(state_updates))
    return []


def _canonical_task_ids(values: list[str]) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not _TASK_ID_RE.fullmatch(value):
            continue
        if value in seen:
            continue
        seen.add(value)
        ids.append(value)
    return ids
