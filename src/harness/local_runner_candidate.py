"""Resolve delivery-attested candidates for opt-in local verification."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import json
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Iterator, Mapping

from harness.coverage_observation import (
    CoverageObservationError,
    CoverageObservationRef,
    load_coverage_observation,
    validate_coverage_observation,
)
from harness.land import read_landed_candidate_commit
from harness.paths import build_dir, current_build_marker, mirror_path
from harness.product_inventory import product_evidence_fingerprint
from harness.runnability_contract import (
    RunnabilityContractError,
    load_runnability_contract,
    runnability_contract_sha256,
)


_BUILD_ID = re.compile(r"^build-[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_COMMIT = re.compile(r"^[0-9a-fA-F]{40,64}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class LocalCandidateError(RuntimeError):
    """Raised when a local runner cannot prove its candidate provenance."""


@dataclass(frozen=True)
class LocalCandidateRequest:
    workspace_root: Path
    target_root: Path
    spec_id: str
    target_id: str
    build_id: str | None = None


@dataclass(frozen=True)
class EffectiveLocalCandidate:
    build_id: str
    sandbox_candidate_commit: str
    effective_candidate_commit: str
    product_fingerprint: str
    contract_hash: str
    stack_hash: str
    observer_plan_hash: str
    sandbox_receipt_sha256: str
    mirror_path: Path
    stack_snapshot: Mapping[str, object]


def resolve_effective_local_candidate(
    request: LocalCandidateRequest,
) -> EffectiveLocalCandidate:
    """Resolve a verified build, accepting a landed commit only if content matches."""
    workspace = _resolve_directory(request.workspace_root, "workspace root")
    target = _resolve_directory(request.target_root, "target root")
    if not request.spec_id.strip() or not request.target_id.strip():
        raise LocalCandidateError("spec_id and target_id are required")
    harness_root = _harness_root(workspace, request.target_id)
    build_id = _resolve_build_id(harness_root, request.spec_id, request.build_id)
    state = _load_converged_state(harness_root, build_id, request.spec_id)
    sandbox_commit = _commit_value(state.get("verified_commit"), "verified commit")
    snapshot = _stack_snapshot(state.get("delivery_stack_snapshot"))
    stack_hash = str(snapshot["resolved_stack_hash"])
    observer_plan_hash = str(snapshot["observer_plan_hash"])
    mirror = mirror_path(harness_root)
    if mirror.is_symlink() or not mirror.is_dir():
        raise LocalCandidateError("managed delivery mirror is unavailable")
    _ensure_commit_in_mirror(mirror, target, sandbox_commit)

    with _temporary_candidate(mirror, harness_root, build_id, sandbox_commit) as candidate:
        product_fingerprint, contract_hash = _candidate_hashes(candidate)
    _validate_sandbox_observation(
        state,
        candidate_commit=sandbox_commit,
        product_fingerprint=product_fingerprint,
        contract_hash=contract_hash,
        stack_hash=stack_hash,
        observer_plan_hash=observer_plan_hash,
        allow_equivalent_product=False,
    )

    effective_commit = sandbox_commit
    landed_commit = read_landed_candidate_commit(
        workspace, request.spec_id, request.target_id
    )
    if landed_commit is not None:
        landed_commit = _commit_value(landed_commit, "landed commit")
        _ensure_commit_in_mirror(mirror, target, landed_commit)
        with _temporary_candidate(mirror, harness_root, build_id, landed_commit) as candidate:
            landed_fingerprint, landed_contract_hash = _candidate_hashes(candidate)
        if landed_fingerprint != product_fingerprint:
            raise LocalCandidateError("landed product fingerprint is stale")
        if landed_contract_hash != contract_hash:
            raise LocalCandidateError("landed runnability contract hash is stale")
        _validate_sandbox_observation(
            state,
            candidate_commit=landed_commit,
            product_fingerprint=landed_fingerprint,
            contract_hash=landed_contract_hash,
            stack_hash=stack_hash,
            observer_plan_hash=observer_plan_hash,
            allow_equivalent_product=True,
        )
        effective_commit = landed_commit

    return EffectiveLocalCandidate(
        build_id=build_id,
        sandbox_candidate_commit=sandbox_commit,
        effective_candidate_commit=effective_commit,
        product_fingerprint=product_fingerprint,
        contract_hash=contract_hash,
        stack_hash=stack_hash,
        observer_plan_hash=observer_plan_hash,
        sandbox_receipt_sha256=_sandbox_receipt_sha256(state),
        mirror_path=mirror.resolve(strict=True),
        stack_snapshot=snapshot,
    )


def materialize_local_candidate(
    candidate: EffectiveLocalCandidate,
    destination: Path,
) -> Path:
    """Create a detached effective-candidate worktree below its managed build root."""
    mirror = candidate.mirror_path.resolve(strict=True)
    allowed_root = mirror.parent / candidate.build_id / "local-runs"
    if allowed_root.is_symlink():
        raise LocalCandidateError("managed local-run root is symlinked")
    allowed_root.mkdir(parents=True, exist_ok=True)
    allowed_root = allowed_root.resolve(strict=True)
    requested = Path(destination).expanduser()
    resolved_destination = requested.resolve(strict=False)
    try:
        resolved_destination.relative_to(allowed_root)
    except ValueError as exc:
        raise LocalCandidateError("local candidate destination escapes managed build root") from exc
    if requested.exists() or requested.is_symlink():
        raise LocalCandidateError("local candidate destination already exists")
    requested.parent.mkdir(parents=True, exist_ok=True)
    _git(mirror, "worktree", "add", "--detach", str(requested), candidate.effective_candidate_commit)
    return requested.resolve(strict=True)


def _resolve_directory(path: Path, label: str) -> Path:
    raw = Path(path).expanduser()
    if raw.is_symlink():
        raise LocalCandidateError(f"{label} must not be symlinked")
    try:
        resolved = raw.resolve(strict=True)
    except OSError as exc:
        raise LocalCandidateError(f"{label} is unavailable") from exc
    if not resolved.is_dir() or resolved.is_symlink():
        raise LocalCandidateError(f"{label} must be a regular directory")
    return resolved


def _harness_root(workspace: Path, target_id: str) -> Path:
    targeted = workspace / "runs" / "targets" / target_id
    if targeted.is_dir() and not targeted.is_symlink():
        return targeted.resolve(strict=True)
    return workspace


def _resolve_build_id(harness_root: Path, spec_id: str, requested: str | None) -> str:
    if requested is not None:
        build_id = requested.strip()
    else:
        marker = current_build_marker(harness_root, spec_id)
        if marker.is_symlink() or not marker.is_file():
            raise LocalCandidateError("delivery build marker is unavailable")
        try:
            build_id = marker.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise LocalCandidateError("could not read delivery build marker") from exc
    if not _BUILD_ID.fullmatch(build_id):
        raise LocalCandidateError("delivery build identity is invalid")
    root = build_dir(harness_root, build_id)
    if root.is_symlink() or not root.is_dir():
        raise LocalCandidateError("delivery build directory is unavailable")
    return build_id


def _load_converged_state(harness_root: Path, build_id: str, spec_id: str) -> dict[str, object]:
    state_root = build_dir(harness_root, build_id) / "state"
    if state_root.is_symlink() or not state_root.is_dir():
        raise LocalCandidateError("delivery state directory is unavailable")
    states: list[dict[str, object]] = []
    for path in sorted(state_root.glob("*.json")):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LocalCandidateError("delivery state is unreadable") from exc
        if (
            isinstance(value, dict)
            and value.get("status") == "converged"
            and value.get("spec_id") == spec_id
        ):
            states.append(value)
    if len(states) != 1:
        raise LocalCandidateError(
            "delivery build must contain exactly one converged strategy for local verification"
        )
    return states[0]


def _stack_snapshot(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise LocalCandidateError(
            "delivery stack snapshot is unavailable; rerun delivery with a current Echelon"
        )
    resolved = value.get("resolved")
    stack_hash = value.get("resolved_stack_hash")
    observer_plan_hash = value.get("observer_plan_hash")
    if not isinstance(resolved, dict):
        raise LocalCandidateError("delivery stack snapshot is malformed")
    if not isinstance(stack_hash, str) or not _SHA256.fullmatch(stack_hash):
        raise LocalCandidateError("delivery stack snapshot has an invalid stack hash")
    if not isinstance(observer_plan_hash, str) or not _SHA256.fullmatch(observer_plan_hash):
        raise LocalCandidateError("delivery stack snapshot has an invalid observer plan hash")
    return {
        "schema_version": 1,
        "resolved": resolved,
        "resolved_stack_hash": stack_hash,
        "observer_plan_hash": observer_plan_hash,
    }


def _commit_value(value: object, label: str) -> str:
    commit = str(value or "").strip()
    if not _COMMIT.fullmatch(commit):
        raise LocalCandidateError(f"{label} is invalid")
    return commit.lower()


def _ensure_commit_in_mirror(mirror: Path, target: Path, commit: str) -> None:
    if _git(mirror, "cat-file", "-e", f"{commit}^{{commit}}", check=False).returncode == 0:
        return
    fetched = _git(
        mirror,
        "fetch",
        "--no-tags",
        "--no-write-fetch-head",
        str(target),
        commit,
        check=False,
    )
    if fetched.returncode != 0 or _git(
        mirror, "cat-file", "-e", f"{commit}^{{commit}}", check=False
    ).returncode != 0:
        raise LocalCandidateError("delivery candidate commit is unavailable in the managed mirror")


@contextmanager
def _temporary_candidate(
    mirror: Path,
    harness_root: Path,
    build_id: str,
    commit: str,
) -> Iterator[Path]:
    root = build_dir(harness_root, build_id) / ".local-candidate-provenance"
    if root.is_symlink():
        raise LocalCandidateError("candidate provenance root is symlinked")
    root.mkdir(parents=True, exist_ok=True)
    root = root.resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="candidate-", dir=root) as temporary:
        path = Path(temporary)
        _git(mirror, "worktree", "add", "--detach", str(path), commit)
        try:
            yield path
        finally:
            _git(mirror, "worktree", "remove", "--force", str(path), check=False)
            _git(mirror, "worktree", "prune", check=False)


def _candidate_hashes(worktree: Path) -> tuple[str, str]:
    try:
        fingerprint = product_evidence_fingerprint(worktree)
        contract = load_runnability_contract(worktree)
    except (OSError, RuntimeError, RunnabilityContractError, ValueError) as exc:
        raise LocalCandidateError(f"could not load candidate runnability contract: {exc}") from exc
    if contract is None or not contract.enabled:
        raise LocalCandidateError("candidate has no enabled runnability contract")
    return fingerprint, runnability_contract_sha256(contract)


def _validate_sandbox_observation(
    state: Mapping[str, object],
    *,
    candidate_commit: str,
    product_fingerprint: str,
    contract_hash: str,
    stack_hash: str,
    observer_plan_hash: str,
    allow_equivalent_product: bool,
) -> None:
    raw_summary = state.get("coverage_observation")
    if not isinstance(raw_summary, dict) or raw_summary.get("status") != "passed":
        raise LocalCandidateError("passing sandbox coverage observation is unavailable")
    raw_ref = raw_summary.get("ref")
    if not isinstance(raw_ref, dict):
        raise LocalCandidateError("sandbox coverage observation lacks an immutable reference")
    try:
        ref = CoverageObservationRef.from_mapping(raw_ref)
        observation = load_coverage_observation(ref.path)
    except (CoverageObservationError, OSError, ValueError) as exc:
        raise LocalCandidateError("sandbox coverage observation is unreadable") from exc
    if observation.ref != ref:
        raise LocalCandidateError("sandbox coverage observation reference mismatch")
    observed_stack_hash = str(observation.fingerprints.get("resolved_stack_hash") or "")
    observed_plan_hash = str(observation.fingerprints.get("observer_plan_hash") or "")
    if observed_stack_hash != stack_hash:
        raise LocalCandidateError("resolved stack hash mismatch")
    if observed_plan_hash != observer_plan_hash:
        raise LocalCandidateError("observer plan hash mismatch")
    try:
        validation = validate_coverage_observation(
            ref,
            candidate_commit=candidate_commit,
            candidate_fingerprint=product_fingerprint,
            coverage_map_hash=str(observation.fingerprints.get("coverage_map_hash") or ""),
            resolved_stack_hash=stack_hash,
            observer_plan_hash=observer_plan_hash,
            runnability_contract_hash=contract_hash,
            allow_equivalent_product=allow_equivalent_product,
        )
    except (CoverageObservationError, OSError, ValueError) as exc:
        raise LocalCandidateError("sandbox coverage observation is invalid") from exc
    if not validation.valid:
        raise LocalCandidateError("sandbox coverage observation is stale: " + validation.reason)


def _sandbox_receipt_sha256(state: Mapping[str, object]) -> str:
    raw_summary = state.get("coverage_observation")
    raw_ref = raw_summary.get("ref") if isinstance(raw_summary, dict) else None
    value = raw_ref.get("receipt_sha256") if isinstance(raw_ref, dict) else None
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise LocalCandidateError("sandbox coverage observation lacks a valid receipt digest")
    return value


def _git(
    cwd: Path,
    *args: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise LocalCandidateError("managed Git operation could not start") from exc
    if check and result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "Git operation failed"
        raise LocalCandidateError(message)
    return result
