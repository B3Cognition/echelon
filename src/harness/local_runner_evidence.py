"""Immutable evidence for opt-in host-local user-runnability checks."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
from typing import Mapping

from harness.local_runner_candidate import EffectiveLocalCandidate
from harness.verification_evidence import redact_verification_text


_SCHEMA_VERSION = 1
_AUTHORITY = "echelon-macos-local-runner"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ATTEMPT = re.compile(r"^attempt-(?P<sequence>[0-9]{4,})-[a-z0-9-]+\.json$")
_STATUSES = frozenset(
    {"passed", "failed", "host_preflight_failed", "cleanup_failed", "recovery_required", "not_runnable"}
)


class LocalRunnabilityEvidenceError(ValueError):
    """Raised when a local attestation cannot be written or trusted."""


@dataclass(frozen=True)
class LocalRunnabilityAttestationRef:
    path: Path
    attestation_sha256: str
    product_fingerprint: str
    status: str


@dataclass(frozen=True)
class LocalRunnabilityAttestationInput:
    status: str
    candidate: EffectiveLocalCandidate
    sandbox_receipt_sha256: str
    runner_profile_digest: str
    cleanup_complete: bool
    redacted_logs: str
    attempt_sequence: int
    local_run_id: str


@dataclass(frozen=True)
class LocalRunnabilityAttestation:
    ref: LocalRunnabilityAttestationRef
    candidate_commit: str
    contract_hash: str
    stack_hash: str
    observer_plan_hash: str
    cleanup_complete: bool


@dataclass(frozen=True)
class LocalVerificationStatus:
    display_status: str
    valid_pass_path: Path | None
    latest_attempt_path: Path | None
    latest_attempt_status: str = ""


def write_local_runnability_attestation(
    evidence_root: Path,
    input: LocalRunnabilityAttestationInput,
) -> LocalRunnabilityAttestationRef:
    """Append one immutable local attempt; no failure can replace an earlier pass."""
    root = _evidence_root(evidence_root, create=True)
    _validate_input(input)
    filename = f"attempt-{input.attempt_sequence:04d}-{input.local_run_id}.json"
    if not _ATTEMPT.fullmatch(filename):
        raise LocalRunnabilityEvidenceError("local run identifier is invalid")
    path = root / filename
    payload = {
        "schema_version": _SCHEMA_VERSION,
        "authority": _AUTHORITY,
        "status": input.status,
        "local_run_id": input.local_run_id,
        "attempt_sequence": input.attempt_sequence,
        "candidate": {
            "sandbox_candidate_commit": input.candidate.sandbox_candidate_commit,
            "effective_candidate_commit": input.candidate.effective_candidate_commit,
            "product_fingerprint": input.candidate.product_fingerprint,
            "contract_hash": input.candidate.contract_hash,
            "stack_hash": input.candidate.stack_hash,
            "observer_plan_hash": input.candidate.observer_plan_hash,
        },
        "sandbox_receipt_sha256": input.sandbox_receipt_sha256,
        "runner_profile_digest": input.runner_profile_digest,
        "cleanup_complete": input.cleanup_complete,
        "logs": redact_verification_text(input.redacted_logs, os.environ)[-16_384:],
    }
    digest = _digest(payload)
    payload["attestation_sha256"] = digest
    markdown_path = path.with_suffix(".md")
    markdown_written = False
    try:
        _write_exclusive_text(markdown_path, _render_markdown(payload))
        markdown_written = True
        _write_exclusive(path, payload)
    except Exception:
        if markdown_written:
            try:
                if markdown_path.is_file() and not markdown_path.is_symlink():
                    markdown_path.unlink()
            except OSError:
                pass
        raise
    return LocalRunnabilityAttestationRef(
        path=path,
        attestation_sha256=digest,
        product_fingerprint=input.candidate.product_fingerprint,
        status=input.status,
    )


def validate_local_runnability_attestation(
    attestation_path: Path,
    candidate: EffectiveLocalCandidate,
) -> LocalRunnabilityAttestation:
    path = Path(attestation_path)
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise LocalRunnabilityEvidenceError("local attestation path is unsafe")
    if not _ATTEMPT.fullmatch(path.name):
        raise LocalRunnabilityEvidenceError("local attestation filename is invalid")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LocalRunnabilityEvidenceError("local attestation is unreadable") from exc
    if not isinstance(payload, dict):
        raise LocalRunnabilityEvidenceError("local attestation is malformed")
    digest = str(payload.get("attestation_sha256") or "")
    without_digest = dict(payload)
    without_digest.pop("attestation_sha256", None)
    if not _SHA256.fullmatch(digest) or not hmac.compare_digest(digest, _digest(without_digest)):
        raise LocalRunnabilityEvidenceError("local attestation digest mismatch")
    if payload.get("schema_version") != _SCHEMA_VERSION or payload.get("authority") != _AUTHORITY:
        raise LocalRunnabilityEvidenceError("local attestation authority mismatch")
    status = payload.get("status")
    if not isinstance(status, str) or status not in _STATUSES:
        raise LocalRunnabilityEvidenceError("local attestation status is invalid")
    details = payload.get("candidate")
    if not isinstance(details, dict):
        raise LocalRunnabilityEvidenceError("local attestation candidate is malformed")
    expected = {
        "product_fingerprint": candidate.product_fingerprint,
        "contract_hash": candidate.contract_hash,
        "stack_hash": candidate.stack_hash,
        "observer_plan_hash": candidate.observer_plan_hash,
    }
    if any(details.get(key) != value for key, value in expected.items()):
        raise LocalRunnabilityEvidenceError("local attestation candidate is stale")
    if payload.get("sandbox_receipt_sha256") != candidate.sandbox_receipt_sha256:
        raise LocalRunnabilityEvidenceError("local attestation sandbox receipt is stale")
    if payload.get("runner_profile_digest") != local_runner_profile_digest(candidate):
        raise LocalRunnabilityEvidenceError("local attestation runner profile is stale")
    cleanup_complete = payload.get("cleanup_complete")
    if type(cleanup_complete) is not bool:
        raise LocalRunnabilityEvidenceError("local attestation cleanup status is invalid")
    if status == "passed" and not cleanup_complete:
        raise LocalRunnabilityEvidenceError("passed local attestation lacks cleanup confirmation")
    ref = LocalRunnabilityAttestationRef(
        path=path,
        attestation_sha256=digest,
        product_fingerprint=candidate.product_fingerprint,
        status=status,
    )
    return LocalRunnabilityAttestation(
        ref=ref,
        candidate_commit=candidate.effective_candidate_commit,
        contract_hash=candidate.contract_hash,
        stack_hash=candidate.stack_hash,
        observer_plan_hash=candidate.observer_plan_hash,
        cleanup_complete=cleanup_complete,
    )


def select_local_verification_status(
    evidence_root: Path,
    candidate: EffectiveLocalCandidate,
) -> LocalVerificationStatus:
    """Show the latest valid pass even if a later host preflight failed."""
    root = _evidence_root(evidence_root, create=False)
    attempts = sorted(
        (path for path in root.glob("attempt-*.json") if path.is_file() and not path.is_symlink()),
        key=_attempt_sort_key,
    ) if root is not None else []
    if not attempts:
        return LocalVerificationStatus("not_run", None, None)
    latest = attempts[-1]
    latest_status = _status_from_path(latest)
    valid_pass: Path | None = None
    stale_seen = False
    for path in attempts:
        try:
            attestation = validate_local_runnability_attestation(path, candidate)
        except LocalRunnabilityEvidenceError as exc:
            if "stale" in str(exc):
                stale_seen = True
            continue
        if attestation.ref.status == "passed":
            valid_pass = path
    if valid_pass is not None:
        return LocalVerificationStatus("passed", valid_pass, latest, latest_status)
    if stale_seen:
        return LocalVerificationStatus("stale", None, latest, latest_status)
    return LocalVerificationStatus(latest_status or "invalid", None, latest, latest_status)


def _evidence_root(path: Path, *, create: bool) -> Path | None:
    root = Path(path).expanduser()
    if root.is_symlink():
        raise LocalRunnabilityEvidenceError("local evidence root is symlinked")
    if create:
        root.mkdir(parents=True, exist_ok=True)
    if not root.exists():
        return None
    try:
        root = root.resolve(strict=True)
    except OSError as exc:
        raise LocalRunnabilityEvidenceError("local evidence root is unavailable") from exc
    if not root.is_dir():
        raise LocalRunnabilityEvidenceError("local evidence root is unavailable")
    return root


def _validate_input(input: LocalRunnabilityAttestationInput) -> None:
    if input.status not in _STATUSES or input.attempt_sequence < 1:
        raise LocalRunnabilityEvidenceError("local attestation input is invalid")
    if not isinstance(input.cleanup_complete, bool):
        raise LocalRunnabilityEvidenceError("local attestation cleanup status is invalid")
    if input.status == "passed" and not input.cleanup_complete:
        raise LocalRunnabilityEvidenceError("passed local attestation requires cleanup confirmation")
    for value in (input.sandbox_receipt_sha256, input.runner_profile_digest):
        if not _SHA256.fullmatch(value):
            raise LocalRunnabilityEvidenceError("local attestation digest input is invalid")
    if input.sandbox_receipt_sha256 != input.candidate.sandbox_receipt_sha256:
        raise LocalRunnabilityEvidenceError("local attestation sandbox receipt input is stale")
    if input.runner_profile_digest != local_runner_profile_digest(input.candidate):
        raise LocalRunnabilityEvidenceError("local attestation runner profile input is stale")


def local_runner_profile_digest(candidate: EffectiveLocalCandidate) -> str:
    """Digest the frozen stack snapshot that owns the local runner profile."""
    snapshot = json.dumps(candidate.stack_snapshot, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256((candidate.stack_hash + "\0" + snapshot).encode("utf-8")).hexdigest()


def _write_exclusive(path: Path, payload: Mapping[str, object]) -> None:
    encoded = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    _write_exclusive_bytes(path, encoded)


def _write_exclusive_text(path: Path, text: str) -> None:
    _write_exclusive_bytes(path, text.encode("utf-8"))


def _write_exclusive_bytes(path: Path, encoded: bytes) -> None:
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError as exc:
        raise LocalRunnabilityEvidenceError("local attestation already exists or cannot be created") from exc
    try:
        os.write(descriptor, encoded)
        os.fsync(descriptor)
    except OSError as exc:
        raise LocalRunnabilityEvidenceError("could not write local attestation") from exc
    finally:
        os.close(descriptor)


def _render_markdown(payload: Mapping[str, object]) -> str:
    candidate = payload.get("candidate")
    details = candidate if isinstance(candidate, Mapping) else {}
    lines = [
        "# Echelon local verification",
        "",
        f"- Status: `{payload.get('status')}`",
        f"- Local run: `{payload.get('local_run_id')}`",
        f"- Cleanup complete: `{payload.get('cleanup_complete')}`",
        f"- Product fingerprint: `{details.get('product_fingerprint', '')}`",
        f"- Contract hash: `{details.get('contract_hash', '')}`",
        f"- Stack hash: `{details.get('stack_hash', '')}`",
        f"- Observer plan hash: `{details.get('observer_plan_hash', '')}`",
        f"- Attestation SHA-256: `{payload.get('attestation_sha256', '')}`",
        "",
        "## Redacted runner summary",
        "",
        "```text",
        str(payload.get("logs") or ""),
        "```",
        "",
    ]
    return "\n".join(lines)


def _digest(value: Mapping[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def _attempt_sort_key(path: Path) -> tuple[int, str]:
    match = _ATTEMPT.fullmatch(path.name)
    return (int(match.group("sequence")) if match else -1, path.name)


def _status_from_path(path: Path) -> str:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "invalid"
    return str(payload.get("status") or "invalid") if isinstance(payload, dict) else "invalid"
