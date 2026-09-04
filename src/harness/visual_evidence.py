"""Immutable visual verification receipts and retained image artifacts."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from harness.durable_json import write_json_atomic


AUTHORITY = "visual-sandbox-verifier"
SCHEMA_VERSION = 1
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True)
class VisualEvidenceRef:
    """Digest-bound reference to one immutable visual attempt."""

    path: Path
    receipt_sha256: str
    evidence_sha256: str
    candidate_commit: str
    candidate_fingerprint: str
    passed: bool
    artifact_count: int

    def as_mapping(self) -> dict[str, object]:
        return {
            "path": str(self.path),
            "receipt_sha256": self.receipt_sha256,
            "evidence_sha256": self.evidence_sha256,
            "candidate_commit": self.candidate_commit,
            "candidate_fingerprint": self.candidate_fingerprint,
            "passed": self.passed,
            "artifact_count": self.artifact_count,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "VisualEvidenceRef":
        return cls(
            path=Path(str(value.get("path") or "")),
            receipt_sha256=str(value.get("receipt_sha256") or ""),
            evidence_sha256=str(value.get("evidence_sha256") or ""),
            candidate_commit=str(value.get("candidate_commit") or ""),
            candidate_fingerprint=str(value.get("candidate_fingerprint") or ""),
            passed=value.get("passed") is True,
            artifact_count=int(value.get("artifact_count") or 0),
        )


@dataclass(frozen=True)
class VisualEvidenceValidation:
    valid: bool
    reason: str = ""


def write_visual_receipt(
    *,
    evidence_dir: Path,
    spec_id: str,
    strategy_id: str,
    build_id: str,
    candidate_commit: str,
    candidate_fingerprint: str,
    screenshot_dir: str,
    playwright: Mapping[str, Any],
    artifact_paths: Sequence[Path],
    required_artifacts: bool,
    attempt_sequence: int,
) -> VisualEvidenceRef:
    """Retain image bytes and write one immutable visual attempt receipt."""
    if attempt_sequence < 1:
        raise ValueError("attempt_sequence must be positive")
    root = Path(evidence_dir)
    if root.is_symlink():
        raise OSError("visual evidence directory must not be a symlink")
    root.mkdir(parents=True, exist_ok=True)
    root = root.resolve(strict=True)

    artifact_dir = root / "artifacts" / f"attempt-{attempt_sequence:04d}"
    artifact_dir.mkdir(parents=True, exist_ok=False)
    retained: list[dict[str, object]] = []
    for index, source_value in enumerate(artifact_paths, start=1):
        source = Path(source_value)
        if source.is_symlink() or not source.is_file():
            raise OSError(f"visual artifact is not a regular file: {source}")
        suffix = source.suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg"}:
            continue
        safe_name = _SAFE_NAME.sub("-", source.name).strip(".-") or f"image{suffix}"
        destination = artifact_dir / f"{index:04d}-{safe_name}"
        content = source.read_bytes()
        _write_bytes_exclusive(destination, content)
        retained.append(
            {
                "path": destination.relative_to(root).as_posix(),
                "sha256": hashlib.sha256(content).hexdigest(),
                "size": len(content),
            }
        )

    total = _integer(playwright.get("total"))
    failed = _integer(playwright.get("failed"))
    skipped = _integer(playwright.get("skipped"))
    failure_id = ""
    if total < 1:
        failure_id = "playwright_no_tests"
    elif failed:
        failure_id = "playwright_tests_failed"
    elif skipped:
        failure_id = "playwright_tests_skipped"
    elif required_artifacts and not retained:
        failure_id = "visual_artifacts_missing"
    passed = not failure_id

    payload: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "authority": AUTHORITY,
        "spec_id": spec_id,
        "strategy_id": strategy_id,
        "build_id": build_id,
        "candidate_commit": candidate_commit,
        "candidate_fingerprint": candidate_fingerprint,
        "screenshot_dir": screenshot_dir,
        "required_artifacts": required_artifacts,
        "playwright": dict(playwright),
        "artifacts": retained,
        "status": "passed" if passed else "failed",
    }
    if failure_id:
        payload["failure_id"] = failure_id
    evidence_sha256 = _stable_evidence_sha256(payload)
    payload["evidence_sha256"] = evidence_sha256
    receipt_sha256 = _sha256_json(payload)
    payload["receipt_sha256"] = receipt_sha256

    commit_prefix = candidate_commit[:12] or "uncommitted"
    receipt_path = root / f"attempt-{attempt_sequence:04d}-{commit_prefix}.json"
    _write_json_exclusive(receipt_path, payload)
    write_json_atomic(
        root / "latest.json",
        {"path": receipt_path.name, "receipt_sha256": receipt_sha256},
        trusted_root=root,
    )
    return VisualEvidenceRef(
        path=receipt_path,
        receipt_sha256=receipt_sha256,
        evidence_sha256=evidence_sha256,
        candidate_commit=candidate_commit,
        candidate_fingerprint=candidate_fingerprint,
        passed=passed,
        artifact_count=len(retained),
    )


def validate_visual_receipt(
    ref: VisualEvidenceRef, *, candidate_fingerprint: str
) -> VisualEvidenceValidation:
    """Validate receipt selection, digests, artifacts, and product identity."""
    try:
        path = ref.path
        if not path.is_absolute() or path.is_symlink():
            return _invalid("receipt path is not absolute and regular")
        root = path.parent.resolve(strict=True)
        resolved = path.resolve(strict=True)
        if resolved.parent != root or not resolved.is_file():
            return _invalid("receipt path escapes its evidence directory")
        payload = json.loads(resolved.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return _invalid("receipt is not a JSON object")
        digest_payload = dict(payload)
        embedded_receipt = str(digest_payload.pop("receipt_sha256", ""))
        observed_receipt = _sha256_json(digest_payload)
        if not (
            hmac.compare_digest(observed_receipt, embedded_receipt)
            and hmac.compare_digest(observed_receipt, ref.receipt_sha256)
        ):
            return _invalid("receipt digest mismatch")
        observed_evidence = _stable_evidence_sha256(payload)
        if not (
            hmac.compare_digest(observed_evidence, str(payload.get("evidence_sha256") or ""))
            and hmac.compare_digest(observed_evidence, ref.evidence_sha256)
        ):
            return _invalid("stable evidence digest mismatch")
        latest = json.loads((root / "latest.json").read_text(encoding="utf-8"))
        if not isinstance(latest, dict) or latest.get("path") != resolved.name:
            return _invalid("receipt is not the selected latest attempt")
        if not hmac.compare_digest(
            str(latest.get("receipt_sha256") or ""), ref.receipt_sha256
        ):
            return _invalid("latest receipt digest mismatch")
        if payload.get("authority") != AUTHORITY:
            return _invalid("receipt authority mismatch")
        if (
            str(payload.get("candidate_fingerprint") or "") != candidate_fingerprint
            or ref.candidate_fingerprint != candidate_fingerprint
        ):
            return _invalid("receipt candidate identity mismatch")
        artifacts = payload.get("artifacts")
        if not isinstance(artifacts, list):
            return _invalid("receipt artifacts are malformed")
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                return _invalid("receipt artifact is malformed")
            relative = Path(str(artifact.get("path") or ""))
            if relative.is_absolute() or ".." in relative.parts:
                return _invalid("artifact path is unsafe")
            retained = (root / relative).resolve(strict=True)
            if not retained.is_file() or not retained.is_relative_to(root):
                return _invalid("artifact is unavailable")
            observed = hashlib.sha256(retained.read_bytes()).hexdigest()
            if not hmac.compare_digest(observed, str(artifact.get("sha256") or "")):
                return _invalid("artifact digest mismatch")
        if payload.get("status") != "passed" or ref.passed is not True:
            return _invalid("receipt is not passing")
        if len(artifacts) != ref.artifact_count:
            return _invalid("artifact count mismatch")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RuntimeError, ValueError):
        return _invalid("visual receipt is unavailable or malformed")
    return VisualEvidenceValidation(valid=True)


def _integer(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _stable_evidence_sha256(payload: Mapping[str, object]) -> str:
    stable = {
        key: payload.get(key)
        for key in (
            "authority", "spec_id", "strategy_id", "build_id",
            "candidate_fingerprint", "screenshot_dir", "required_artifacts",
            "playwright", "artifacts", "status", "failure_id",
        )
    }
    return _sha256_json(stable)


def _sha256_json(value: Mapping[str, object]) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _write_json_exclusive(path: Path, value: Mapping[str, object]) -> None:
    content = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    _write_bytes_exclusive(path, content)


def _write_bytes_exclusive(path: Path, content: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        remaining = memoryview(content)
        while remaining:
            remaining = remaining[os.write(descriptor, remaining):]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _invalid(reason: str) -> VisualEvidenceValidation:
    return VisualEvidenceValidation(valid=False, reason=reason)
