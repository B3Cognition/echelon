"""Retained, task-bound browser baseline proposals (not verification approval)."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
import os
from pathlib import Path, PurePosixPath
from uuid import uuid4

from harness.durable_json import write_json_atomic
from harness.visual_ralph import (
    BrowserBaselineCapture, MAX_BROWSER_BASELINE_IMAGE_BYTES,
    MAX_BROWSER_BASELINE_IMAGES, MAX_BROWSER_BASELINE_TOTAL_BYTES,
)


class BrowserBaselineEvidenceError(ValueError):
    """A baseline proposal is missing, stale, or unsafe to hand to a provider."""


@dataclass(frozen=True)
class BrowserBaselineEvidenceRef:
    path: Path
    receipt_sha256: str


@dataclass(frozen=True)
class BrowserBaselineObservation:
    images: dict[str, Path]
    verification_passed: bool
    diagnostic: str


def write_browser_baseline_receipt(
    *, evidence_root: Path, operation_id: str, task_id: str,
    input_fingerprint: str, capture: BrowserBaselineCapture,
) -> BrowserBaselineEvidenceRef:
    """Store one exclusive proposal under the delivery operation's evidence root."""
    if not all(isinstance(value, str) and value for value in (
        operation_id, task_id, input_fingerprint, capture.candidate_fingerprint,
    )) or (not capture.images and not capture.verification.passed and not capture.diagnostic):
        raise BrowserBaselineEvidenceError("invalid browser baseline identity or images")
    if not isinstance(capture.diagnostic, str) or len(capture.diagnostic) > 4000:
        raise BrowserBaselineEvidenceError("invalid browser verification diagnostic")
    if (len(capture.images) > MAX_BROWSER_BASELINE_IMAGES
            or any(not isinstance(content, bytes) or len(content) > MAX_BROWSER_BASELINE_IMAGE_BYTES
                   for content in capture.images.values())
            or sum(len(content) for content in capture.images.values()) > MAX_BROWSER_BASELINE_TOTAL_BYTES):
        raise BrowserBaselineEvidenceError("invalid browser baseline image inventory")
    evidence_root = Path(evidence_root)
    if evidence_root.is_symlink():
        raise BrowserBaselineEvidenceError("symlinked browser evidence root")
    evidence_root.mkdir(parents=True, exist_ok=True)
    operation_root = evidence_root.resolve(strict=True) / "browser-baselines" / hashlib.sha256(
        operation_id.encode("utf-8")
    ).hexdigest()
    operation_root.mkdir(parents=True, exist_ok=True)
    if operation_root.is_symlink():
        raise BrowserBaselineEvidenceError("symlinked browser operation evidence root")
    root = operation_root / uuid4().hex
    root.mkdir()  # Unjournaled attempts remain inert; retries never overwrite them.
    artifact_dir = root / "artifacts"
    artifact_dir.mkdir()
    artifacts: list[dict[str, object]] = []
    for index, (candidate_path, content) in enumerate(sorted(capture.images.items()), start=1):
        relative = _candidate_path(candidate_path)
        if index > MAX_BROWSER_BASELINE_IMAGES:
            raise BrowserBaselineEvidenceError("invalid browser baseline image")
        artifact_path = Path("artifacts") / f"{index:04d}{relative.suffix.lower()}"
        _write_bytes_exclusive(root / artifact_path, content)
        artifacts.append({
            "candidate_path": relative.as_posix(),
            "path": artifact_path.as_posix(),
            "sha256": hashlib.sha256(content).hexdigest(),
            "size": len(content),
        })
    receipt = {
        "schema_version": 2,
        "authority": "browser-baseline-proposal",
        "operation_id": operation_id,
        "task_id": task_id,
        "candidate_fingerprint": capture.candidate_fingerprint,
        "input_fingerprint": input_fingerprint,
        "verification_passed": capture.verification.passed,
        "verification_diagnostic": capture.diagnostic,
        "artifacts": artifacts,
    }
    digest = _digest(receipt)
    receipt["receipt_sha256"] = digest
    path = root / "receipt.json"
    write_json_atomic(path, receipt, trusted_root=root)
    return BrowserBaselineEvidenceRef(path=path, receipt_sha256=digest)


def read_browser_baseline_receipt(
    ref: BrowserBaselineEvidenceRef, *, operation_id: str, task_id: str,
    candidate_fingerprint: str, input_fingerprint: str,
) -> dict[str, Path]:
    """Read validated baseline images; a capture can also contain only diagnostics."""
    return read_browser_baseline_observation(
        ref, operation_id=operation_id, task_id=task_id,
        candidate_fingerprint=candidate_fingerprint,
        input_fingerprint=input_fingerprint,
    ).images


def read_browser_baseline_observation(
    ref: BrowserBaselineEvidenceRef, *, operation_id: str, task_id: str,
    candidate_fingerprint: str, input_fingerprint: str,
) -> BrowserBaselineObservation:
    """Validate every binding and byte before exposing retained proposal paths."""
    try:
        path = ref.path
        if not path.is_absolute() or path.is_symlink() or path.name != "receipt.json":
            raise BrowserBaselineEvidenceError("invalid browser receipt path")
        if path.parent.is_symlink():
            raise BrowserBaselineEvidenceError("browser receipt escaped evidence root")
        root = path.parent.resolve(strict=True)
        if path.resolve(strict=True).parent != root:
            raise BrowserBaselineEvidenceError("browser receipt escaped evidence root")
        payload = json.loads(path.read_text(encoding="utf-8"))
        expected_keys = {
            "schema_version", "authority", "operation_id", "task_id",
            "candidate_fingerprint", "input_fingerprint", "verification_passed",
            "verification_diagnostic", "artifacts", "receipt_sha256",
        }
        if not isinstance(payload, dict) or set(payload) != expected_keys:
            raise BrowserBaselineEvidenceError("invalid browser receipt schema")
        digest = payload.pop("receipt_sha256")
        if not isinstance(digest, str) or not (
            hmac.compare_digest(_digest(payload), digest)
            and hmac.compare_digest(digest, ref.receipt_sha256)
        ):
            raise BrowserBaselineEvidenceError("browser receipt digest mismatch")
        if (payload["schema_version"] != 2
                or payload["authority"] != "browser-baseline-proposal"
                or payload["operation_id"] != operation_id
                or payload["task_id"] != task_id
                or payload["candidate_fingerprint"] != candidate_fingerprint
                or payload["input_fingerprint"] != input_fingerprint
                or type(payload["verification_passed"]) is not bool
                or not isinstance(payload["verification_diagnostic"], str)
                or len(payload["verification_diagnostic"]) > 4000):
            raise BrowserBaselineEvidenceError("browser receipt binding mismatch")
        artifacts = payload["artifacts"]
        if (not isinstance(artifacts, list) or len(artifacts) > MAX_BROWSER_BASELINE_IMAGES
                or (not artifacts and not payload["verification_passed"]
                    and not payload["verification_diagnostic"])):
            raise BrowserBaselineEvidenceError("invalid browser artifact inventory")
        artifact_dir = root / "artifacts"
        if artifact_dir.is_symlink() or not artifact_dir.is_dir():
            raise BrowserBaselineEvidenceError("browser artifact directory unavailable")
        retained: dict[str, Path] = {}
        total_image_bytes = 0
        for artifact in artifacts:
            if not isinstance(artifact, dict) or set(artifact) != {
                "candidate_path", "path", "sha256", "size",
            }:
                raise BrowserBaselineEvidenceError("invalid browser artifact record")
            candidate_path = _candidate_path(artifact["candidate_path"]).as_posix()
            relative = PurePosixPath(artifact["path"])
            if (relative.is_absolute() or ".." in relative.parts
                    or len(relative.parts) != 2 or relative.parts[0] != "artifacts"):
                raise BrowserBaselineEvidenceError("unsafe browser artifact path")
            retained_path = root / relative.as_posix()
            if retained_path.is_symlink() or not retained_path.is_file():
                raise BrowserBaselineEvidenceError("browser artifact unavailable")
            content = retained_path.read_bytes()
            total_image_bytes += len(content)
            if (type(artifact["size"]) is not int or len(content) != artifact["size"]
                    or len(content) > MAX_BROWSER_BASELINE_IMAGE_BYTES
                    or total_image_bytes > MAX_BROWSER_BASELINE_TOTAL_BYTES
                    or not isinstance(artifact["sha256"], str)
                    or not hmac.compare_digest(hashlib.sha256(content).hexdigest(), artifact["sha256"])):
                raise BrowserBaselineEvidenceError("browser artifact digest mismatch")
            if candidate_path in retained:
                raise BrowserBaselineEvidenceError("duplicate browser baseline path")
            retained[candidate_path] = retained_path
        return BrowserBaselineObservation(
            images=retained,
            verification_passed=payload["verification_passed"],
            diagnostic=payload["verification_diagnostic"],
        )
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        if isinstance(exc, BrowserBaselineEvidenceError):
            raise
        raise BrowserBaselineEvidenceError("browser baseline evidence unavailable") from exc


def _candidate_path(value: object) -> PurePosixPath:
    if not isinstance(value, str) or not value or value.startswith("./"):
        raise BrowserBaselineEvidenceError("invalid browser candidate path")
    path = PurePosixPath(value)
    if (path.is_absolute() or ".." in path.parts or "." in path.parts
            or not any(part.endswith("-snapshots") for part in path.parts[:-1])
            or path.suffix.lower() not in {".png", ".jpg", ".jpeg"}):
        raise BrowserBaselineEvidenceError("invalid browser candidate path")
    return path


def _digest(value: dict[str, object]) -> str:
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _write_bytes_exclusive(path: Path, content: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        view = memoryview(content)
        while view:
            view = view[os.write(descriptor, view):]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
