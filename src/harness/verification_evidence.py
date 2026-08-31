"""Immutable, redacted evidence from Ralph-owned host verification."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from harness.durable_json import write_json_atomic
from harness.secret_scan import RULES


AUTHORITY = "ralph-host-verifier"
SCHEMA_VERSION = 1
OUTPUT_TAIL_BYTES = 64 * 1024
_SENSITIVE_ENV_NAME = re.compile(
    r"(?:TOKEN|SECRET|PASSWORD|PASS|KEY|CREDENTIAL|AUTH|DATABASE_URL)",
    re.IGNORECASE,
)
_URL_USERINFO = re.compile(
    r"(?P<scheme>\b[a-z][a-z0-9+.-]*://)[^/@\s]+@", re.IGNORECASE
)
_BEARER = re.compile(
    r"(?P<prefix>\bBearer\s+)[A-Za-z0-9._~+/=-]+", re.IGNORECASE
)


@dataclass(frozen=True)
class VerificationStage:
    """One ordered command executed by the host verifier."""

    name: str
    command: tuple[str, ...]
    exit_code: int
    duration_ms: int
    stdout: bytes
    stderr: bytes
    started_at: str | None = None
    completed_at: str | None = None


@dataclass(frozen=True)
class VerificationEvidenceRef:
    """Digest-bound reference to one immutable attempt receipt."""

    path: Path
    receipt_sha256: str
    evidence_sha256: str
    candidate_commit: str
    candidate_fingerprint: str
    passed: bool

    def as_mapping(self) -> dict[str, object]:
        return {
            "path": str(self.path),
            "receipt_sha256": self.receipt_sha256,
            "evidence_sha256": self.evidence_sha256,
            "candidate_commit": self.candidate_commit,
            "candidate_fingerprint": self.candidate_fingerprint,
            "passed": self.passed,
        }

    @classmethod
    def from_mapping(
        cls, value: Mapping[str, object]
    ) -> "VerificationEvidenceRef":
        return cls(
            path=Path(str(value.get("path") or "")),
            receipt_sha256=str(value.get("receipt_sha256") or ""),
            evidence_sha256=str(value.get("evidence_sha256") or ""),
            candidate_commit=str(value.get("candidate_commit") or ""),
            candidate_fingerprint=str(
                value.get("candidate_fingerprint") or ""
            ),
            passed=value.get("passed") is True,
        )


@dataclass(frozen=True)
class VerificationReceiptValidation:
    """Fail-closed result from validating one receipt reference."""

    valid: bool
    reason: str = ""


def redact_verification_text(
    text: str, sensitive_environment: Mapping[str, str]
) -> str:
    """Remove known environment values and high-confidence secret forms."""
    redacted = text
    sensitive_values = {
        str(value)
        for name, value in sensitive_environment.items()
        if _SENSITIVE_ENV_NAME.search(str(name)) and str(value)
    }
    for value in sorted(sensitive_values, key=lambda item: (-len(item), item)):
        redacted = redacted.replace(value, "[REDACTED:environment]")
    redacted = _URL_USERINFO.sub(
        lambda match: f"{match.group('scheme')}[REDACTED:url-userinfo]@",
        redacted,
    )
    redacted = _BEARER.sub(
        lambda match: f"{match.group('prefix')}[REDACTED:bearer]",
        redacted,
    )
    for rule in RULES:
        redacted = rule.pattern.sub(f"[REDACTED:{rule.rule_id}]", redacted)
    return redacted


def write_verification_receipt(
    *,
    evidence_dir: Path,
    spec_id: str,
    strategy_id: str,
    build_id: str,
    candidate_commit: str,
    fingerprint_before: str,
    fingerprint_after: str,
    verifier_source: str,
    stages: Sequence[VerificationStage],
    attempt_sequence: int,
    sensitive_environment: Mapping[str, str],
    started_at: str | None = None,
    target_id: str = "",
    detection_evidence: Sequence[str] = (),
) -> VerificationEvidenceRef:
    """Persist one immutable attempt and atomically select it as latest."""
    root = Path(evidence_dir)
    if root.is_symlink():
        raise OSError("verification evidence directory must not be a symlink")
    root.mkdir(parents=True, exist_ok=True)
    root = root.resolve(strict=True)
    if attempt_sequence < 1:
        raise ValueError("attempt_sequence must be positive")

    passed = bool(stages) and all(stage.exit_code == 0 for stage in stages)
    failure_id = ""
    if fingerprint_before != fingerprint_after:
        passed = False
        failure_id = "candidate_mutated_during_verification"
    elif not stages:
        passed = False
        failure_id = "verification_no_stages"
    elif not passed:
        failure_id = "verification_stage_failed"

    stage_payloads = [
        _stage_payload(stage, started_at, sensitive_environment)
        for stage in stages
    ]
    receipt: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "authority": AUTHORITY,
        "spec_id": spec_id,
        "target_id": target_id,
        "build_id": build_id,
        "strategy_id": strategy_id,
        "candidate_commit": candidate_commit,
        "candidate_fingerprint": fingerprint_after,
        "fingerprint_before": fingerprint_before,
        "fingerprint_after": fingerprint_after,
        "verifier_source": verifier_source,
        "detection_evidence": [
            redact_verification_text(str(item), sensitive_environment)
            for item in detection_evidence
        ],
        "started_at": started_at or "",
        "stages": stage_payloads,
        "status": "passed" if passed else "failed",
    }
    if failure_id:
        receipt["failure_id"] = failure_id
    evidence_sha256 = _stable_evidence_sha256(receipt)
    receipt["evidence_sha256"] = evidence_sha256
    receipt_sha256 = _sha256_json(receipt)
    receipt["receipt_sha256"] = receipt_sha256

    candidate_prefix = candidate_commit[:12] or "uncommitted"
    attempt_path = root / (
        f"attempt-{attempt_sequence:04d}-{candidate_prefix}.json"
    )
    _write_json_exclusive(attempt_path, receipt)
    write_json_atomic(
        root / "latest.json",
        {"path": attempt_path.name, "receipt_sha256": receipt_sha256},
        trusted_root=root,
    )
    return VerificationEvidenceRef(
        path=attempt_path,
        receipt_sha256=receipt_sha256,
        evidence_sha256=evidence_sha256,
        candidate_commit=candidate_commit,
        candidate_fingerprint=fingerprint_after,
        passed=passed,
    )


def validate_verification_receipt(
    ref: VerificationEvidenceRef,
    *,
    candidate_commit: str,
    candidate_fingerprint: str,
) -> VerificationReceiptValidation:
    """Validate authority, digests, latest selection, pass, and candidate."""
    try:
        path = ref.path
        if not path.is_absolute() or path.is_symlink():
            return _invalid("receipt path is not absolute and regular")
        root = path.parent.resolve(strict=True)
        resolved = path.resolve(strict=True)
        if resolved.parent != root or not resolved.is_file():
            return _invalid("receipt path escapes its evidence directory")
        raw = resolved.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            return _invalid("receipt is not a JSON object")
        embedded_receipt_digest = str(payload.get("receipt_sha256") or "")
        digest_payload = dict(payload)
        digest_payload.pop("receipt_sha256", None)
        observed_receipt_digest = _sha256_json(digest_payload)
        if not (
            hmac.compare_digest(observed_receipt_digest, ref.receipt_sha256)
            and hmac.compare_digest(
                observed_receipt_digest, embedded_receipt_digest
            )
        ):
            return _invalid("receipt digest mismatch")
        if payload.get("authority") != AUTHORITY:
            return _invalid("receipt authority mismatch")
        observed_evidence_digest = _stable_evidence_sha256(payload)
        embedded_evidence_digest = str(payload.get("evidence_sha256") or "")
        if not (
            hmac.compare_digest(observed_evidence_digest, ref.evidence_sha256)
            and hmac.compare_digest(
                observed_evidence_digest, embedded_evidence_digest
            )
        ):
            return _invalid("stable evidence digest mismatch")
        latest_path = root / "latest.json"
        if latest_path.is_symlink():
            return _invalid("latest pointer is symlinked")
        latest = json.loads(latest_path.read_text(encoding="utf-8"))
        if not isinstance(latest, dict):
            return _invalid("latest pointer is malformed")
        selected = str(latest.get("path") or "")
        if Path(selected).name != selected or selected in {"", ".", ".."}:
            return _invalid("latest pointer path is unsafe")
        if selected != resolved.name or not hmac.compare_digest(
            str(latest.get("receipt_sha256") or ""), ref.receipt_sha256
        ):
            return _invalid("receipt is not the selected latest attempt")
        if payload.get("status") != "passed" or ref.passed is not True:
            return _invalid("receipt is not passing")
        if (
            str(payload.get("candidate_commit") or "") != candidate_commit
            or ref.candidate_commit != candidate_commit
            or str(payload.get("candidate_fingerprint") or "")
            != candidate_fingerprint
            or ref.candidate_fingerprint != candidate_fingerprint
        ):
            return _invalid("receipt candidate identity mismatch")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RuntimeError):
        return _invalid("verification receipt is unavailable or malformed")
    return VerificationReceiptValidation(valid=True)


def _stage_payload(
    stage: VerificationStage,
    receipt_started_at: str | None,
    sensitive_environment: Mapping[str, str],
) -> dict[str, object]:
    stdout = bytes(stage.stdout)
    stderr = bytes(stage.stderr)
    raw_command = b"\0".join(
        item.encode("utf-8", errors="surrogatepass") for item in stage.command
    )
    return {
        "name": stage.name,
        "command": [
            redact_verification_text(item, sensitive_environment)
            for item in stage.command
        ],
        "command_sha256": hashlib.sha256(raw_command).hexdigest(),
        "started_at": stage.started_at or receipt_started_at or "",
        "completed_at": stage.completed_at or receipt_started_at or "",
        "duration_ms": int(stage.duration_ms),
        "exit_code": int(stage.exit_code),
        "status": "passed" if stage.exit_code == 0 else "failed",
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


def _stable_evidence_sha256(receipt: Mapping[str, object]) -> str:
    stages = receipt.get("stages")
    stable_stages: list[dict[str, object]] = []
    if isinstance(stages, list):
        for raw in stages:
            if not isinstance(raw, dict):
                continue
            stable_stages.append(
                {
                    key: raw.get(key)
                    for key in (
                        "name",
                        "command_sha256",
                        "exit_code",
                        "status",
                        "stdout_sha256",
                        "stderr_sha256",
                    )
                }
            )
    stable = {
        "authority": receipt.get("authority"),
        "spec_id": receipt.get("spec_id"),
        "target_id": receipt.get("target_id"),
        "build_id": receipt.get("build_id"),
        "strategy_id": receipt.get("strategy_id"),
        "candidate_commit": receipt.get("candidate_commit"),
        "candidate_fingerprint": receipt.get("candidate_fingerprint"),
        "verifier_source": receipt.get("verifier_source"),
        "detection_evidence": receipt.get("detection_evidence"),
        "status": receipt.get("status"),
        "failure_id": receipt.get("failure_id"),
        "stages": stable_stages,
    }
    return _sha256_json(stable)


def _sha256_json(value: Mapping[str, object]) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _write_json_exclusive(path: Path, value: Mapping[str, object]) -> None:
    content = (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")
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


def _invalid(reason: str) -> VerificationReceiptValidation:
    return VerificationReceiptValidation(valid=False, reason=reason)
