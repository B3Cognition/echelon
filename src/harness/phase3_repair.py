"""Pure contracts for Phase 3 repair evidence; no agent-owned state authority."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import PurePosixPath
import re


class RepairContractError(ValueError):
    """A repair result does not match its controller-owned dispatch envelope."""


@dataclass(frozen=True)
class RepairIdentity:
    run_id: str
    issue_fingerprint: str
    selection_revision: int


@dataclass(frozen=True)
class IssueReview:
    identity: RepairIdentity
    outcome: str
    reviewed_artifacts: tuple[tuple[str, str], ...]
    rationale: str


@dataclass(frozen=True)
class RepairAction:
    identity: RepairIdentity
    kind: str
    owner_phase: str
    affected_artifacts: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    action: str
    constraints: tuple[str, ...]


def validate_repair_action(payload: Mapping[str, object], *, expected: RepairIdentity,
                           allowed_owner_phases: frozenset[str],
                           allowed_artifacts: frozenset[str]) -> RepairAction:
    """Validate work syntax, not authority to adopt an answer or weaken a gate."""
    fields = {"schema_version", "identity", "kind", "owner_phase", "affected_artifacts",
              "evidence_refs", "action", "constraints"}
    if not isinstance(payload, Mapping) or set(payload) != fields:
        raise RepairContractError("repair action must be one complete assessment")
    if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
        raise RepairContractError("unsupported repair action version")
    identity = payload["identity"]
    if (not isinstance(identity, Mapping) or dict(identity) != asdict(expected)
            or type(identity.get("selection_revision")) is not int
            or identity["selection_revision"] < 0):
        raise RepairContractError("repair action identity does not match issue")
    kind = _text(payload["kind"], "action kind")
    if kind not in {"apply_evidenced_resolution", "investigate_or_design", "human_decision", "external_prerequisite"}:
        raise RepairContractError("unknown repair action kind")
    owner = _text(payload["owner_phase"], "owner phase")
    if owner not in allowed_owner_phases:
        raise RepairContractError("repair owner is outside the allowed phases")

    def strings(field: str) -> tuple[str, ...]:
        values = payload[field]
        if not isinstance(values, (list, tuple)) or not values or len(values) > 256:
            raise RepairContractError(f"{field} requires a bounded nonempty list")
        result = tuple(_text(value, field) for value in values)
        if len(set(result)) != len(result):
            raise RepairContractError(f"{field} contains duplicates")
        return result

    artifacts, references, constraints = (strings(field) for field in
        ("affected_artifacts", "evidence_refs", "constraints"))
    # Reuse the same canonical path rules as review manifests.
    _manifest({path: "0" * 64 for path in artifacts})
    _manifest({ref.split("#", 1)[0]: "0" * 64 for ref in references})
    if not set(artifacts).issubset(allowed_artifacts):
        raise RepairContractError("repair artifacts are outside owner scope")
    return RepairAction(expected, kind, owner, artifacts, references,
                        _text(payload["action"], "action"), constraints)


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 16000:
        raise RepairContractError(f"{label} must be nonempty bounded text")
    return value


def _manifest(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping) or not value or len(value) > 256:
        raise RepairContractError("review requires a nonempty artifact manifest")
    result = {}
    for path, digest in value.items():
        _text(path, "artifact path")
        parsed = PurePosixPath(path)
        if (parsed.is_absolute() or ".." in parsed.parts or "\\" in path
                or ":" in path or str(parsed) != path or path == "."):
            raise RepairContractError("artifact path must be canonical and relative")
        if not isinstance(digest, str) or re.fullmatch(r"[a-f0-9]{64}", digest) is None:
            raise RepairContractError("artifact digest must be SHA256")
        result[path] = digest
    return result


def validate_issue_review(
    payload: Mapping[str, object], *, expected: RepairIdentity,
    expected_manifest: Mapping[str, str],
) -> IssueReview:
    """Validate an explicit assessment against harness identity and input hashes."""
    fields = {"schema_version", "identity", "outcome", "reviewed_artifacts", "rationale"}
    if not isinstance(payload, Mapping) or set(payload) != fields:
        raise RepairContractError("issue review must be one complete assessment")
    if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
        raise RepairContractError("unsupported issue review version")
    identity = payload["identity"]
    if (not isinstance(identity, Mapping) or dict(identity) != asdict(expected)
            or type(identity.get("selection_revision")) is not int
            or identity["selection_revision"] < 0):
        raise RepairContractError("issue review identity does not match selection")
    manifest = _manifest(expected_manifest)
    if _manifest(payload["reviewed_artifacts"]) != manifest:
        raise RepairContractError("issue review manifest does not match candidate")
    outcome = payload["outcome"]
    if not isinstance(outcome, str) or outcome not in {"resolved", "unresolved", "unverifiable"}:
        raise RepairContractError("invalid issue review outcome")
    return IssueReview(expected, outcome, tuple(sorted(manifest.items())), _text(payload["rationale"], "rationale"))


def review_from_result(
    result: Mapping[str, object], *, agent_id: str, mode: str,
    expected: RepairIdentity, expected_manifest: Mapping[str, str],
) -> IssueReview | None:
    """Only a WHY3 SAGE dispatch can supply selected-issue closure evidence."""
    if "phase3_issue_review" not in result:
        return None
    if agent_id != "echelon.sage" or mode != "WHY3":
        raise RepairContractError("selected-issue review is owned by SAGE WHY3")
    return validate_issue_review(result["phase3_issue_review"], expected=expected, expected_manifest=expected_manifest)
