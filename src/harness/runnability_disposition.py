"""Owner-controlled disposition for a required user-runnability gate."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat
from typing import Mapping

from harness.durable_json import DurableJsonError, write_json_atomic
from harness.runnability_evidence import AUTHORITY as RUNNABILITY_AUTHORITY


LEDGER_FILENAME = "runnability-disposition.json"
FOLLOW_UP_FILENAME = "runnability-follow-up.md"
SCHEMA_VERSION = 1
FAILED_REPORT_STATUSES = frozenset({"not_runnable", "blocked"})


class RunnabilityDispositionError(ValueError):
    """Raised when an owner disposition or its evidence is invalid."""


@dataclass(frozen=True)
class RunnabilityDisposition:
    status: str
    target: str
    reason: str
    at: str
    evidence_report: str
    follow_up_proposal: str

    @classmethod
    def from_mapping(cls, value: object) -> "RunnabilityDisposition":
        if not isinstance(value, dict):
            raise RunnabilityDispositionError("runnability disposition event must be an object")
        status = _required_text(value, "status")
        if status not in {"deferred", "planned"}:
            raise RunnabilityDispositionError(
                f"unsupported runnability disposition status: {status}"
            )
        return cls(
            status=status,
            target=_required_text(value, "target"),
            reason=_required_text(value, "reason"),
            at=_required_text(value, "at"),
            evidence_report=_required_text(value, "evidence_report"),
            follow_up_proposal=_required_text(value, "follow_up_proposal"),
        )

    def to_mapping(self) -> dict[str, str]:
        return {
            "status": self.status,
            "target": self.target,
            "reason": self.reason,
            "at": self.at,
            "evidence_report": self.evidence_report,
            "follow_up_proposal": self.follow_up_proposal,
        }


def disposition_path(spec_dir: Path) -> Path:
    return Path(spec_dir) / LEDGER_FILENAME


def follow_up_path(spec_dir: Path) -> Path:
    return Path(spec_dir) / FOLLOW_UP_FILENAME


def read_runnability_history(spec_dir: Path) -> tuple[RunnabilityDisposition, ...]:
    path = disposition_path(spec_dir)
    if not path.exists():
        return ()
    if path.is_symlink() or not path.is_file():
        raise RunnabilityDispositionError("runnability disposition ledger must be a regular file")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RunnabilityDispositionError(f"invalid runnability disposition ledger: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        raise RunnabilityDispositionError("unsupported runnability disposition ledger schema")
    events = payload.get("events")
    if not isinstance(events, list):
        raise RunnabilityDispositionError("runnability disposition events must be a list")
    return tuple(RunnabilityDisposition.from_mapping(event) for event in events)


def read_runnability_disposition(spec_dir: Path) -> RunnabilityDisposition | None:
    history = read_runnability_history(spec_dir)
    return history[-1] if history else None


def defer_runnability(
    *,
    spec_dir: Path,
    target: str,
    reason: str,
    evidence_report: Path,
    approved_at: str | None = None,
) -> RunnabilityDisposition:
    """Record an explicit owner deferral backed by a current failed report."""
    owner_reason = str(reason).strip()
    if not owner_reason:
        raise RunnabilityDispositionError("runnability deferral requires a non-empty reason")
    target_name = str(target).strip()
    if not target_name:
        raise RunnabilityDispositionError("runnability deferral requires a target")
    history = read_runnability_history(spec_dir)
    if history and history[-1].status == "deferred":
        raise RunnabilityDispositionError("an active runnability deferral already exists")

    report_path, report = _load_failed_report(evidence_report)
    observed_target = str(report.get("target_id") or "").strip()
    if observed_target and observed_target != target_name:
        raise RunnabilityDispositionError(
            f"runnability report target {observed_target!r} does not match {target_name!r}"
        )
    timestamp = _timestamp(approved_at)
    event = RunnabilityDisposition(
        status="deferred",
        target=target_name,
        reason=owner_reason,
        at=timestamp,
        evidence_report=str(report_path),
        follow_up_proposal=FOLLOW_UP_FILENAME,
    )
    proposal = _render_follow_up(event, report)
    _write_text_atomic_safe(follow_up_path(spec_dir), proposal, trusted_root=Path(spec_dir))
    _write_history(spec_dir, (*history, event))
    return event


def plan_runnability(
    spec_dir: Path,
    *,
    planned_at: str | None = None,
) -> RunnabilityDisposition:
    """Restore current-spec blocking while retaining the owner decision history."""
    history = read_runnability_history(spec_dir)
    if not history or history[-1].status != "deferred":
        raise RunnabilityDispositionError("no active runnability deferral to plan")
    deferred = history[-1]
    event = RunnabilityDisposition(
        status="planned",
        target=deferred.target,
        reason=deferred.reason,
        at=_timestamp(planned_at),
        evidence_report=deferred.evidence_report,
        follow_up_proposal=deferred.follow_up_proposal,
    )
    _write_history(spec_dir, (*history, event))
    return event


def find_latest_runnability_report(
    workspace_root: Path,
    spec_id: str,
) -> Path | None:
    """Find the newest authoritative report presentation for one spec."""
    selector = str(spec_id).strip()
    candidates: list[tuple[int, str, Path]] = []
    pattern = "runs/targets/*/runs/*/evidence/user-runnability/report.json"
    for path in Path(workspace_root).glob(pattern):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            report_spec = str(payload.get("spec_id") or "") if isinstance(payload, dict) else ""
            if not _spec_matches(selector, report_spec):
                continue
            modified = path.stat(follow_symlinks=False).st_mtime_ns
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        candidates.append((modified, str(path), path.resolve()))
    if not candidates:
        return None
    return max(candidates)[2]


def _load_failed_report(path: Path) -> tuple[Path, dict[str, object]]:
    candidate = Path(path).expanduser()
    if not candidate.exists():
        raise RunnabilityDispositionError(f"runnability report does not exist: {candidate}")
    if candidate.is_symlink() or not candidate.is_file():
        raise RunnabilityDispositionError("runnability report must be a regular file")
    report_path = candidate.resolve(strict=True)
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RunnabilityDispositionError(f"invalid runnability report: {exc}") from exc
    if not isinstance(payload, dict):
        raise RunnabilityDispositionError("invalid runnability report: expected an object")
    if payload.get("authority") != RUNNABILITY_AUTHORITY:
        raise RunnabilityDispositionError("runnability report authority mismatch")
    if str(payload.get("status") or "") not in FAILED_REPORT_STATUSES:
        raise RunnabilityDispositionError("deferral requires a failed current report")
    receipt = str(payload.get("receipt_sha256") or "")
    digest_payload = dict(payload)
    digest_payload.pop("receipt_sha256", None)
    if not receipt or receipt != _sha256_json(digest_payload):
        raise RunnabilityDispositionError("runnability report digest mismatch")
    return report_path, payload


def _render_follow_up(
    event: RunnabilityDisposition,
    report: Mapping[str, object],
) -> str:
    title = f"Make {event.target} locally runnable"
    required = _string_list(report.get("required_stages"))
    raw_stages = report.get("stages")
    stage_status = {
        str(stage.get("name") or ""): str(stage.get("status") or "missing")
        for stage in raw_stages
        if isinstance(stage, dict) and str(stage.get("name") or "")
    } if isinstance(raw_stages, list) else {}
    failed = tuple(
        stage for stage in required if stage_status.get(stage, "missing") != "passed"
    )
    if not failed:
        failure_class = str(report.get("failure_class") or "runnability")
        failed = (failure_class,)
    command = (
        f'echelon spec run "{_shell_double_quote(title)}" '
        f"--target {_shell_argument(event.target)}"
    )
    lines = [
        f"# {title}",
        "",
        "> Advisory owner-reviewed follow-up proposal. This file does not create or approve a specification.",
        "",
        "## Intent",
        "",
        f"Make `{event.target}` runnable through its real composed local journey.",
        "",
        "## Evidence",
        "",
        f"- Report: `{event.evidence_report}`",
        f"- Failure class: `{report.get('failure_class') or 'unknown'}`",
        f"- Summary: {report.get('summary') or 'No summary was recorded.'}",
        f"- Resolved stack contract: `{report.get('stack_hash') or 'unknown'}`",
        "",
        "## Failed or absent capabilities",
        "",
    ]
    lines.extend(f"- `{stage}` ({stage_status.get(stage, 'missing')})" for stage in failed)
    lines.extend(
        [
            "",
            "## Draft acceptance criteria",
            "",
            *[
                f"- The `{stage}` runnability stage passes in a fresh harness-owned sandbox."
                for stage in failed
            ],
            "- The full composed user journey produces authoritative runnability evidence.",
            "",
            "## Proposed command",
            "",
            "```sh",
            command,
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def _write_history(
    spec_dir: Path,
    events: tuple[RunnabilityDisposition, ...],
) -> None:
    root = _regular_directory(spec_dir)
    try:
        write_json_atomic(
            root / LEDGER_FILENAME,
            {
                "schema_version": SCHEMA_VERSION,
                "events": [event.to_mapping() for event in events],
            },
            trusted_root=root,
        )
    except DurableJsonError as exc:
        raise RunnabilityDispositionError(str(exc)) from exc


def _write_text_atomic_safe(path: Path, content: str, *, trusted_root: Path) -> None:
    root = _regular_directory(trusted_root)
    destination = root / path.name
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    directory_fd = os.open(root, directory_flags)
    temporary = f".{path.name}-{secrets.token_hex(16)}.tmp"
    temporary_fd: int | None = None
    try:
        try:
            metadata = os.stat(destination.name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            if not stat.S_ISREG(metadata.st_mode):
                raise RunnabilityDispositionError(
                    "runnability follow-up proposal must be a regular file"
                )
        temporary_fd = os.open(temporary, flags, 0o600, dir_fd=directory_fd)
        data = content.encode("utf-8")
        view = memoryview(data)
        while view:
            written = os.write(temporary_fd, view)
            view = view[written:]
        os.fsync(temporary_fd)
        os.close(temporary_fd)
        temporary_fd = None
        os.replace(temporary, destination.name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        os.fsync(directory_fd)
    finally:
        if temporary_fd is not None:
            os.close(temporary_fd)
        try:
            os.unlink(temporary, dir_fd=directory_fd)
        except FileNotFoundError:
            pass
        os.close(directory_fd)


def _regular_directory(path: Path) -> Path:
    value = Path(path)
    if value.is_symlink() or not value.is_dir():
        raise RunnabilityDispositionError(
            f"spec directory is unavailable or unsafe: {value}"
        )
    return value.resolve(strict=True)


def _required_text(value: Mapping[str, object], key: str) -> str:
    text = str(value.get(key) or "").strip()
    if not text:
        raise RunnabilityDispositionError(f"runnability disposition event missing {key}")
    return text


def _string_list(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def _sha256_json(value: Mapping[str, object]) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _timestamp(value: str | None) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat()
    text = str(value).strip()
    if not text:
        raise RunnabilityDispositionError("runnability disposition timestamp is empty")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RunnabilityDispositionError("invalid runnability disposition timestamp") from exc
    if parsed.tzinfo is None:
        raise RunnabilityDispositionError("runnability disposition timestamp requires a timezone")
    return text


def _spec_matches(selector: str, report_spec: str) -> bool:
    return report_spec == selector or report_spec.startswith(f"{selector}-")


def _shell_double_quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("`", "\\`")


def _shell_argument(value: str) -> str:
    if value and all(character.isalnum() or character in "-._/" for character in value):
        return value
    return f'"{_shell_double_quote(value)}"'
