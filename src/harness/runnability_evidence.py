"""Immutable, content-addressed evidence for the user-runnability gate."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
import os
from pathlib import Path
from typing import Mapping, Sequence

from harness.durable_json import write_json_atomic
from harness.verification_evidence import (
    OUTPUT_TAIL_BYTES,
    redact_verification_text,
)


AUTHORITY = "echelon-user-runnability"
SCHEMA_VERSION = 1
VALID_STATUSES = frozenset(
    {"runnable", "not_runnable", "blocked", "deferred", "not_applicable"}
)


@dataclass(frozen=True)
class RunnabilityStage:
    name: str
    status: str
    command: tuple[str, ...] = ()
    exit_code: int | None = None
    duration_ms: int = 0
    stdout: bytes = b""
    stderr: bytes = b""


@dataclass(frozen=True)
class RunnabilityEvidenceRef:
    path: Path
    markdown_path: Path
    receipt_sha256: str
    evidence_sha256: str
    candidate_commit: str
    candidate_fingerprint: str
    contract_hash: str
    stack_hash: str
    status: str

    def as_mapping(self) -> dict[str, object]:
        return {
            "path": str(self.path),
            "markdown_path": str(self.markdown_path),
            "receipt_sha256": self.receipt_sha256,
            "evidence_sha256": self.evidence_sha256,
            "candidate_commit": self.candidate_commit,
            "candidate_fingerprint": self.candidate_fingerprint,
            "contract_hash": self.contract_hash,
            "stack_hash": self.stack_hash,
            "status": self.status,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "RunnabilityEvidenceRef":
        return cls(
            path=Path(str(value.get("path") or "")),
            markdown_path=Path(str(value.get("markdown_path") or "")),
            receipt_sha256=str(value.get("receipt_sha256") or ""),
            evidence_sha256=str(value.get("evidence_sha256") or ""),
            candidate_commit=str(value.get("candidate_commit") or ""),
            candidate_fingerprint=str(value.get("candidate_fingerprint") or ""),
            contract_hash=str(value.get("contract_hash") or ""),
            stack_hash=str(value.get("stack_hash") or ""),
            status=str(value.get("status") or ""),
        )


@dataclass(frozen=True)
class RunnabilityEvidenceValidation:
    valid: bool
    reason: str = ""


def write_runnability_report(
    *,
    evidence_dir: Path,
    spec_id: str,
    target_id: str,
    strategy_id: str,
    build_id: str,
    candidate_commit: str,
    candidate_fingerprint: str,
    contract_hash: str,
    stack_hash: str,
    status: str,
    failure_class: str,
    summary: str,
    stages: Sequence[RunnabilityStage],
    required_stages: Sequence[str],
    attempt_sequence: int,
    sensitive_environment: Mapping[str, str],
    user_commands: Mapping[str, Sequence[str]],
) -> RunnabilityEvidenceRef:
    """Write one immutable attempt and update bounded human-facing pointers."""
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid runnability status: {status}")
    if attempt_sequence < 1:
        raise ValueError("attempt_sequence must be positive")
    stage_by_name = {stage.name: stage for stage in stages}
    if len(stage_by_name) != len(stages):
        raise ValueError("runnability stage names must be unique")
    if status == "runnable":
        for name in required_stages:
            stage = stage_by_name.get(name)
            if stage is None or stage.status != "passed":
                raise ValueError(f"required stage {name} did not pass")

    root = Path(evidence_dir)
    if root.is_symlink():
        raise OSError("runnability evidence directory must not be a symlink")
    root.mkdir(parents=True, exist_ok=True)
    root = root.resolve(strict=True)
    for presentation_name in ("latest.json", "report.json", "report.md", "commands.log"):
        if (root / presentation_name).is_symlink():
            raise OSError(
                f"runnability evidence presentation file must not be a symlink: {presentation_name}"
            )

    redacted_summary = redact_verification_text(summary, sensitive_environment)
    payload: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "authority": AUTHORITY,
        "spec_id": spec_id,
        "target_id": target_id,
        "strategy_id": strategy_id,
        "build_id": build_id,
        "candidate_commit": candidate_commit,
        "candidate_fingerprint": candidate_fingerprint,
        "contract_hash": contract_hash,
        "stack_hash": stack_hash,
        "status": status,
        "failure_class": failure_class,
        "summary": redacted_summary,
        "contract_path": ".echelon/runnability.yml",
        "required_stages": list(required_stages),
        "stages": [
            _stage_payload(stage, sensitive_environment) for stage in stages
        ],
        "user_commands": {
            key: [
                redact_verification_text(str(command), sensitive_environment)
                for command in commands
            ]
            for key, commands in sorted(user_commands.items())
        },
    }
    evidence_sha256 = _stable_evidence_sha256(payload)
    payload["evidence_sha256"] = evidence_sha256
    receipt_sha256 = _sha256_json(payload)
    payload["receipt_sha256"] = receipt_sha256

    candidate_prefix = candidate_commit[:12] or "uncommitted"
    attempt_stem = f"attempt-{attempt_sequence:04d}-{candidate_prefix}"
    attempt_path = root / f"{attempt_stem}.json"
    markdown_path = root / f"{attempt_stem}.md"
    markdown = _render_markdown(payload)
    _write_bytes_exclusive(
        attempt_path,
        (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
    _write_bytes_exclusive(markdown_path, markdown.encode("utf-8"))
    write_json_atomic(
        root / "latest.json",
        {
            "path": attempt_path.name,
            "markdown_path": markdown_path.name,
            "receipt_sha256": receipt_sha256,
        },
        trusted_root=root,
    )
    write_json_atomic(root / "report.json", payload, trusted_root=root)
    _write_bytes_atomic(root / "report.md", markdown.encode("utf-8"))
    _write_bytes_atomic(
        root / "commands.log", _render_command_log(payload).encode("utf-8")
    )
    return RunnabilityEvidenceRef(
        path=attempt_path,
        markdown_path=markdown_path,
        receipt_sha256=receipt_sha256,
        evidence_sha256=evidence_sha256,
        candidate_commit=candidate_commit,
        candidate_fingerprint=candidate_fingerprint,
        contract_hash=contract_hash,
        stack_hash=stack_hash,
        status=status,
    )


def validate_runnability_report(
    ref: RunnabilityEvidenceRef,
    *,
    candidate_commit: str,
    candidate_fingerprint: str,
    contract_hash: str,
    stack_hash: str,
) -> RunnabilityEvidenceValidation:
    """Validate content identity; commit identity remains informational."""
    del candidate_commit
    try:
        path = ref.path
        if not path.is_absolute() or path.is_symlink():
            return _invalid("report path is not absolute and regular")
        root = path.parent.resolve(strict=True)
        resolved = path.resolve(strict=True)
        if resolved.parent != root or not resolved.is_file():
            return _invalid("report path escapes its evidence directory")
        payload = json.loads(resolved.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return _invalid("report is not a JSON object")
        embedded_receipt = str(payload.get("receipt_sha256") or "")
        digest_payload = dict(payload)
        digest_payload.pop("receipt_sha256", None)
        observed_receipt = _sha256_json(digest_payload)
        if not (
            hmac.compare_digest(observed_receipt, ref.receipt_sha256)
            and hmac.compare_digest(observed_receipt, embedded_receipt)
        ):
            return _invalid("report digest mismatch")
        if payload.get("authority") != AUTHORITY:
            return _invalid("report authority mismatch")
        observed_evidence = _stable_evidence_sha256(payload)
        embedded_evidence = str(payload.get("evidence_sha256") or "")
        if not (
            hmac.compare_digest(observed_evidence, ref.evidence_sha256)
            and hmac.compare_digest(observed_evidence, embedded_evidence)
        ):
            return _invalid("stable evidence digest mismatch")
        latest = _read_latest(root)
        if (
            latest.get("path") != resolved.name
            or not hmac.compare_digest(
                str(latest.get("receipt_sha256") or ""), ref.receipt_sha256
            )
        ):
            return _invalid("report is not the selected latest attempt")
        if payload.get("status") != "runnable" or ref.status != "runnable":
            return _invalid("report is not runnable")
        identities = {
            "candidate_fingerprint": candidate_fingerprint,
            "contract_hash": contract_hash,
            "stack_hash": stack_hash,
        }
        for field, expected in identities.items():
            if (
                str(payload.get(field) or "") != expected
                or str(getattr(ref, field)) != expected
            ):
                return _invalid(f"{field} mismatch")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RuntimeError):
        return _invalid("runnability report is unavailable or malformed")
    return RunnabilityEvidenceValidation(valid=True)


def _stage_payload(
    stage: RunnabilityStage,
    sensitive_environment: Mapping[str, str],
) -> dict[str, object]:
    if stage.status not in {"passed", "failed", "blocked", "not_run"}:
        raise ValueError(f"invalid stage status: {stage.status}")
    stdout = bytes(stage.stdout)
    stderr = bytes(stage.stderr)
    raw_command = b"\0".join(item.encode("utf-8") for item in stage.command)
    return {
        "name": stage.name,
        "status": stage.status,
        "command": [
            redact_verification_text(item, sensitive_environment)
            for item in stage.command
        ],
        "command_sha256": hashlib.sha256(raw_command).hexdigest(),
        "exit_code": stage.exit_code,
        "duration_ms": max(0, int(stage.duration_ms)),
        "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
        "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
        "stdout_tail": redact_verification_text(
            stdout[-OUTPUT_TAIL_BYTES:].decode("utf-8", errors="replace"),
            sensitive_environment,
        ),
        "stderr_tail": redact_verification_text(
            stderr[-OUTPUT_TAIL_BYTES:].decode("utf-8", errors="replace"),
            sensitive_environment,
        ),
    }


def _stable_evidence_sha256(payload: Mapping[str, object]) -> str:
    stages = payload.get("stages")
    stable_stages: list[dict[str, object]] = []
    if isinstance(stages, list):
        for raw in stages:
            if isinstance(raw, dict):
                stable_stages.append(
                    {
                        key: raw.get(key)
                        for key in (
                            "name",
                            "status",
                            "command_sha256",
                            "exit_code",
                            "stdout_sha256",
                            "stderr_sha256",
                        )
                    }
                )
    stable = {
        "authority": payload.get("authority"),
        "spec_id": payload.get("spec_id"),
        "target_id": payload.get("target_id"),
        "strategy_id": payload.get("strategy_id"),
        "build_id": payload.get("build_id"),
        "candidate_fingerprint": payload.get("candidate_fingerprint"),
        "contract_hash": payload.get("contract_hash"),
        "stack_hash": payload.get("stack_hash"),
        "status": payload.get("status"),
        "failure_class": payload.get("failure_class"),
        "required_stages": payload.get("required_stages"),
        "stages": stable_stages,
        "user_commands": payload.get("user_commands"),
    }
    return _sha256_json(stable)


def _render_markdown(payload: Mapping[str, object]) -> str:
    status = str(payload.get("status") or "blocked")
    failure_class = str(payload.get("failure_class") or "none")
    lines = [
        "# User Runnability Report",
        "",
        f"- Status: `{status}`",
        f"- Failure class: `{failure_class}`",
        f"- Summary: {payload.get('summary') or 'No summary.'}",
        "- Candidate contract: `.echelon/runnability.yml`",
        f"- Candidate fingerprint: `{payload.get('candidate_fingerprint')}`",
        f"- Contract hash: `{payload.get('contract_hash')}`",
        f"- Stack hash: `{payload.get('stack_hash')}`",
        "",
        "## Stages",
        "",
        "| Stage | Status | Exit code |",
        "|---|---|---:|",
    ]
    stages = payload.get("stages")
    if isinstance(stages, list):
        for stage in stages:
            if isinstance(stage, dict):
                exit_code = stage.get("exit_code")
                lines.append(
                    f"| {stage.get('name')} | {stage.get('status')} | "
                    f"{'' if exit_code is None else exit_code} |"
                )
    if status != "runnable":
        lines.extend(
            [
                "",
                "## Required Repair",
                "",
                "Repair the candidate product or `.echelon/runnability.yml`, then rerun delivery.",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _render_command_log(payload: Mapping[str, object]) -> str:
    lines: list[str] = []
    stages = payload.get("stages")
    if isinstance(stages, list):
        for stage in stages:
            if not isinstance(stage, dict):
                continue
            lines.extend(
                [
                    f"[{stage.get('name')}] {stage.get('status')}",
                    str(stage.get("stdout_tail") or ""),
                    str(stage.get("stderr_tail") or ""),
                ]
            )
    return "\n".join(lines).rstrip() + "\n"


def _read_latest(root: Path) -> dict[str, object]:
    path = root / "latest.json"
    if path.is_symlink():
        raise OSError("latest pointer is symlinked")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise OSError("latest pointer is malformed")
    selected = str(raw.get("path") or "")
    if Path(selected).name != selected or selected in {"", ".", ".."}:
        raise OSError("latest pointer path is unsafe")
    return raw


def _sha256_json(value: Mapping[str, object]) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _write_bytes_exclusive(path: Path, content: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    try:
        view = memoryview(content)
        while view:
            written = os.write(fd, view)
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)
    directory_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _write_bytes_atomic(path: Path, content: bytes) -> None:
    temporary = path.parent / f".{path.name}.{os.getpid()}.tmp"
    _write_bytes_exclusive(temporary, content)
    try:
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _invalid(reason: str) -> RunnabilityEvidenceValidation:
    return RunnabilityEvidenceValidation(valid=False, reason=reason)
