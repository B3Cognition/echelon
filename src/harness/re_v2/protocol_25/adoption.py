"""Authenticated protocol-2.5 parent and successor-mode authority."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from harness.re_v2.canonical import content_digest
from harness.re_v2.protocol_22.schema import (
    Protocol22SchemaError,
    digest_value,
    exact_object,
    literal,
    one_of,
    optional_digest,
    sorted_unique_digests,
)
from harness.re_v2.protocol_24.model import ParentAuthorityBundleV1

from .model import Protocol25SchemaError


_PARENT_LAYERS = frozenset({"L1", "L2", "L3"})
_PARENT_STATES = frozenset(
    {
        "running_audit",
        "paused_resource",
        "blocked_incomplete",
        "blocked_plateau",
        "next_epoch_required",
        "complete",
    }
)
_TERMINAL_STATES = frozenset(
    {"blocked_incomplete", "blocked_plateau", "next_epoch_required", "complete"}
)
_RUN_MODES = frozenset(
    {"new-audit-epoch", "audit-successor", "closure-successor"}
)


class Protocol25AdoptionError(Protocol25SchemaError):
    """Raised when parent authority is ineligible for the requested successor."""


def _schema(function, *args):  # type: ignore[no-untyped-def]
    try:
        return function(*args)
    except Protocol25AdoptionError:
        raise
    except Protocol22SchemaError as exc:
        raise Protocol25AdoptionError(str(exc)) from exc


def _digests(values: object, field: str) -> tuple[str, ...]:
    return _schema(sorted_unique_digests, values, field)


@dataclass(frozen=True, slots=True)
class ParentSemanticAuthorityV1:
    schema_version: int
    accepted_audit_target_ids: tuple[str, ...]
    accepted_audit_candidate_hashes: tuple[str, ...]
    unresolved_audit_target_ids: tuple[str, ...]
    audit_epoch_id: str | None
    resolution_overlay_hashes: tuple[str, ...]
    target_assessment_hashes: tuple[str, ...]
    source_assessment_hashes: tuple[str, ...]
    closure_receipt_ids: tuple[str, ...]
    closure_root_hash: str | None
    unresolved_finding_ids: tuple[str, ...]
    deferred_observation_ids: tuple[str, ...]
    l3_source_root_hashes: tuple[str, ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "accepted_audit_target_ids",
        "accepted_audit_candidate_hashes",
        "unresolved_audit_target_ids",
        "audit_epoch_id",
        "resolution_overlay_hashes",
        "target_assessment_hashes",
        "source_assessment_hashes",
        "closure_receipt_ids",
        "closure_root_hash",
        "unresolved_finding_ids",
        "deferred_observation_ids",
        "l3_source_root_hashes",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "parent semantic schema_version")
        for field in (
            "accepted_audit_target_ids",
            "accepted_audit_candidate_hashes",
            "unresolved_audit_target_ids",
            "resolution_overlay_hashes",
            "target_assessment_hashes",
            "source_assessment_hashes",
            "closure_receipt_ids",
            "unresolved_finding_ids",
            "deferred_observation_ids",
            "l3_source_root_hashes",
        ):
            object.__setattr__(
                self,
                field,
                _digests(getattr(self, field), f"ParentSemanticAuthorityV1.{field}"),
            )
        _schema(optional_digest, self.audit_epoch_id, "parent semantic audit_epoch_id")
        _schema(optional_digest, self.closure_root_hash, "parent semantic closure_root_hash")
        if len(self.accepted_audit_target_ids) != len(
            self.accepted_audit_candidate_hashes
        ):
            raise Protocol25AdoptionError(
                "parent semantic candidate authority does not cover accepted targets"
            )
        if set(self.accepted_audit_target_ids) & set(self.unresolved_audit_target_ids):
            raise Protocol25AdoptionError(
                "parent semantic accepted and unresolved audit targets overlap"
            )
        closure_values = (
            self.resolution_overlay_hashes,
            self.target_assessment_hashes,
            self.source_assessment_hashes,
            self.closure_receipt_ids,
            self.unresolved_finding_ids,
            self.deferred_observation_ids,
            self.l3_source_root_hashes,
        )
        if self.audit_epoch_id is None:
            if self.closure_root_hash is not None or any(closure_values):
                raise Protocol25AdoptionError(
                    "parent semantic closure authority requires an audit epoch"
                )
        else:
            if self.unresolved_audit_target_ids:
                raise Protocol25AdoptionError(
                    "parent semantic audit epoch cannot retain an unresolved audit target"
                )
            if self.closure_root_hash is None or not self.l3_source_root_hashes:
                raise Protocol25AdoptionError(
                    "parent semantic audit epoch requires closure and L3 root authority"
                )
        if self.unresolved_audit_target_ids and not self.accepted_audit_candidate_hashes:
            raise Protocol25AdoptionError(
                "parent semantic incomplete audit requires retained candidate authority"
            )

    @classmethod
    def empty(cls) -> "ParentSemanticAuthorityV1":
        return cls(1, (), (), (), None, (), (), (), (), None, (), (), ())

    @property
    def is_empty(self) -> bool:
        return self == self.empty()

    @property
    def object_ids(self) -> tuple[str, ...]:
        values = {
            *self.accepted_audit_candidate_hashes,
            *self.resolution_overlay_hashes,
            *self.target_assessment_hashes,
            *self.source_assessment_hashes,
            *self.closure_receipt_ids,
            *self.deferred_observation_ids,
            *self.l3_source_root_hashes,
        }
        if self.audit_epoch_id is not None:
            values.add(self.audit_epoch_id)
        if self.closure_root_hash is not None:
            values.add(self.closure_root_hash)
        return tuple(sorted(values))

    @property
    def identity(self) -> str:
        return content_digest(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        result = {field: getattr(self, field) for field in self.FIELDS}
        for field in (
            "accepted_audit_target_ids",
            "accepted_audit_candidate_hashes",
            "unresolved_audit_target_ids",
            "resolution_overlay_hashes",
            "target_assessment_hashes",
            "source_assessment_hashes",
            "closure_receipt_ids",
            "unresolved_finding_ids",
            "deferred_observation_ids",
            "l3_source_root_hashes",
        ):
            result[field] = list(getattr(self, field))
        return result

    @classmethod
    def from_json_dict(cls, value: object) -> "ParentSemanticAuthorityV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class Protocol25ParentCandidateV1:
    schema_version: int
    parent_layer: str
    parent_state: str
    source_snapshot_id: str
    selection_id: str
    terminal_event_hash: str | None
    authentication_state: str
    workspace_state: str
    lineage_state: str
    lower_authority_bundle: ParentAuthorityBundleV1
    semantic_authority: ParentSemanticAuthorityV1

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "parent_layer",
        "parent_state",
        "source_snapshot_id",
        "selection_id",
        "terminal_event_hash",
        "authentication_state",
        "workspace_state",
        "lineage_state",
        "lower_authority_bundle",
        "semantic_authority",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "parent candidate schema_version")
        _schema(one_of, self.parent_layer, _PARENT_LAYERS, "parent candidate layer")
        _schema(one_of, self.parent_state, _PARENT_STATES, "parent candidate state")
        _schema(digest_value, self.source_snapshot_id, "parent candidate snapshot")
        _schema(digest_value, self.selection_id, "parent candidate selection")
        _schema(optional_digest, self.terminal_event_hash, "parent candidate terminal event")
        _schema(
            one_of,
            self.authentication_state,
            frozenset({"authenticated", "corrupt"}),
            "parent authentication state",
        )
        _schema(
            one_of,
            self.workspace_state,
            frozenset({"clean_exact_commits", "dirty", "commit_drift"}),
            "parent workspace state",
        )
        _schema(
            one_of,
            self.lineage_state,
            frozenset({"acyclic", "cyclic"}),
            "parent lineage state",
        )
        if not isinstance(self.lower_authority_bundle, ParentAuthorityBundleV1):
            raise Protocol25AdoptionError("parent lower authority bundle is invalid")
        if not isinstance(self.semantic_authority, ParentSemanticAuthorityV1):
            raise Protocol25AdoptionError("parent semantic authority is invalid")
        if self.parent_state in _TERMINAL_STATES:
            if self.terminal_event_hash is None:
                raise Protocol25AdoptionError("terminal parent requires terminal event")
            if (
                self.terminal_event_hash
                != self.lower_authority_bundle.source_terminal_event_hash
            ):
                raise Protocol25AdoptionError(
                    "parent terminal event disagrees with lower authority bundle"
                )
        elif self.terminal_event_hash is not None:
            raise Protocol25AdoptionError(
                "nonterminal parent cannot claim a terminal event"
            )

    def to_json_dict(self) -> dict[str, object]:
        result = {field: getattr(self, field) for field in self.FIELDS}
        result["lower_authority_bundle"] = self.lower_authority_bundle.to_json_dict()
        result["semantic_authority"] = self.semantic_authority.to_json_dict()
        return result

    @classmethod
    def from_json_dict(cls, value: object) -> "Protocol25ParentCandidateV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(
            **{
                field: raw[field]
                for field in cls.FIELDS
                if field not in {"lower_authority_bundle", "semantic_authority"}
            },
            lower_authority_bundle=ParentAuthorityBundleV1.from_json_dict(
                raw["lower_authority_bundle"]
            ),
            semantic_authority=ParentSemanticAuthorityV1.from_json_dict(
                raw["semantic_authority"]
            ),
        )


@dataclass(frozen=True, slots=True)
class ValidatedProtocol25ParentV1:
    candidate: Protocol25ParentCandidateV1
    mode: str

    @property
    def adopted_audit_candidate_hashes(self) -> tuple[str, ...]:
        return self.candidate.semantic_authority.accepted_audit_candidate_hashes

    @property
    def remaining_audit_target_ids(self) -> tuple[str, ...]:
        return self.candidate.semantic_authority.unresolved_audit_target_ids

    @property
    def audit_epoch_id(self) -> str | None:
        return self.candidate.semantic_authority.audit_epoch_id

    @property
    def closure_root_hash(self) -> str | None:
        return self.candidate.semantic_authority.closure_root_hash

    @property
    def unresolved_finding_ids(self) -> tuple[str, ...]:
        return self.candidate.semantic_authority.unresolved_finding_ids

    @property
    def adopted_semantic_object_ids(self) -> tuple[str, ...]:
        return self.candidate.semantic_authority.object_ids


@dataclass(frozen=True, slots=True)
class ParentAuthorityBundleV2:
    schema_version: int
    parent_layer: str
    parent_state: str
    source_snapshot_id: str
    selection_id: str
    lower_authority_bundle: ParentAuthorityBundleV1
    semantic_authority: ParentSemanticAuthorityV1

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "parent_layer",
        "parent_state",
        "source_snapshot_id",
        "selection_id",
        "lower_authority_bundle",
        "semantic_authority",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 2, "ParentAuthorityBundleV2.schema_version")
        _schema(one_of, self.parent_layer, _PARENT_LAYERS, "parent bundle layer")
        _schema(one_of, self.parent_state, _PARENT_STATES, "parent bundle state")
        _schema(digest_value, self.source_snapshot_id, "parent bundle snapshot")
        _schema(digest_value, self.selection_id, "parent bundle selection")
        if not isinstance(self.lower_authority_bundle, ParentAuthorityBundleV1):
            raise Protocol25AdoptionError("parent bundle lower authority is invalid")
        if not isinstance(self.semantic_authority, ParentSemanticAuthorityV1):
            raise Protocol25AdoptionError("parent bundle semantic authority is invalid")

    @property
    def identity(self) -> str:
        return content_digest(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "parent_layer": self.parent_layer,
            "parent_state": self.parent_state,
            "source_snapshot_id": self.source_snapshot_id,
            "selection_id": self.selection_id,
            "lower_authority_bundle": self.lower_authority_bundle.to_json_dict(),
            "semantic_authority": self.semantic_authority.to_json_dict(),
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "ParentAuthorityBundleV2":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(
            schema_version=raw["schema_version"],
            parent_layer=raw["parent_layer"],
            parent_state=raw["parent_state"],
            source_snapshot_id=raw["source_snapshot_id"],
            selection_id=raw["selection_id"],
            lower_authority_bundle=ParentAuthorityBundleV1.from_json_dict(
                raw["lower_authority_bundle"]
            ),
            semantic_authority=ParentSemanticAuthorityV1.from_json_dict(
                raw["semantic_authority"]
            ),
        )


def validate_protocol_25_parent(
    candidate: Protocol25ParentCandidateV1,
    *,
    mode: str,
    expected_source_snapshot_id: str | None = None,
    expected_selection_id: str | None = None,
) -> ValidatedProtocol25ParentV1:
    if not isinstance(candidate, Protocol25ParentCandidateV1):
        raise Protocol25AdoptionError("parent candidate authority is invalid")
    _schema(one_of, mode, _RUN_MODES, "protocol-2.5 parent mode")
    if candidate.authentication_state != "authenticated":
        raise Protocol25AdoptionError("parent authority is not authenticated")
    if candidate.lineage_state != "acyclic":
        raise Protocol25AdoptionError("parent lineage contains a cycle")
    if candidate.workspace_state == "dirty":
        raise Protocol25AdoptionError(
            "Sources must be clean. Commit, stash, or revert changes before proceeding."
        )
    if candidate.workspace_state == "commit_drift":
        raise Protocol25AdoptionError(
            "source commits do not match the authenticated parent snapshot"
        )
    if candidate.parent_state not in _TERMINAL_STATES or candidate.terminal_event_hash is None:
        raise Protocol25AdoptionError("parent must be terminal before adoption")
    if (
        expected_source_snapshot_id is not None
        and candidate.source_snapshot_id != expected_source_snapshot_id
    ):
        raise Protocol25AdoptionError("parent source snapshot does not match request")
    if expected_selection_id is not None and candidate.selection_id != expected_selection_id:
        raise Protocol25AdoptionError("parent selection does not match request")

    semantic = candidate.semantic_authority
    eligible = False
    if mode == "new-audit-epoch":
        if candidate.parent_layer in {"L1", "L2"}:
            eligible = candidate.parent_state == "complete" and semantic.is_empty
        elif candidate.parent_layer == "L3":
            eligible = (
                candidate.parent_state in {"complete", "next_epoch_required"}
                and semantic.audit_epoch_id is not None
                and not semantic.unresolved_finding_ids
            )
            if candidate.parent_state == "next_epoch_required" and not semantic.deferred_observation_ids:
                eligible = False
    elif mode == "audit-successor":
        eligible = (
            candidate.parent_layer == "L3"
            and candidate.parent_state == "blocked_incomplete"
            and semantic.audit_epoch_id is None
            and bool(semantic.accepted_audit_candidate_hashes)
            and bool(semantic.unresolved_audit_target_ids)
        )
    elif mode == "closure-successor":
        eligible = (
            candidate.parent_layer == "L3"
            and candidate.parent_state == "blocked_plateau"
            and semantic.audit_epoch_id is not None
            and semantic.closure_root_hash is not None
            and bool(semantic.unresolved_finding_ids)
        )
    if not eligible:
        if (
            mode == "new-audit-epoch"
            and candidate.parent_state == "next_epoch_required"
            and semantic.unresolved_finding_ids
        ):
            raise Protocol25AdoptionError(
                "next audit epoch requires every frozen finding to be closed"
            )
        raise Protocol25AdoptionError(
            f"parent state {candidate.parent_state!r} is ineligible for {mode!r}"
        )
    return ValidatedProtocol25ParentV1(candidate=candidate, mode=mode)


def build_parent_authority_bundle_v2(
    parent: ValidatedProtocol25ParentV1,
) -> ParentAuthorityBundleV2:
    if not isinstance(parent, ValidatedProtocol25ParentV1):
        raise Protocol25AdoptionError("V2 parent bundle requires validated authority")
    candidate = parent.candidate
    return ParentAuthorityBundleV2(
        schema_version=2,
        parent_layer=candidate.parent_layer,
        parent_state=candidate.parent_state,
        source_snapshot_id=candidate.source_snapshot_id,
        selection_id=candidate.selection_id,
        lower_authority_bundle=candidate.lower_authority_bundle,
        semantic_authority=candidate.semantic_authority,
    )


def import_protocol_25_parent_closure(
    parent: ValidatedProtocol25ParentV1,
    semantic_objects: dict[str, bytes],
) -> tuple[str, ...]:
    """Authenticate a self-contained semantic object set before durable import.

    The typed ledger facade records these objects in Task 8; this boundary proves
    that the supplied copied object closure exactly covers the validated bundle.
    """
    if not isinstance(parent, ValidatedProtocol25ParentV1):
        raise Protocol25AdoptionError("semantic import requires validated parent")
    expected = parent.adopted_semantic_object_ids
    if set(semantic_objects) != set(expected):
        raise Protocol25AdoptionError("semantic object import is incomplete")
    for object_id, payload in semantic_objects.items():
        _schema(digest_value, object_id, "semantic imported object ID")
        if content_digest(payload) != object_id:
            raise Protocol25AdoptionError("semantic imported object hash mismatch")
    return expected


__all__ = (
    "ParentAuthorityBundleV2",
    "ParentSemanticAuthorityV1",
    "Protocol25AdoptionError",
    "Protocol25ParentCandidateV1",
    "ValidatedProtocol25ParentV1",
    "build_parent_authority_bundle_v2",
    "import_protocol_25_parent_closure",
    "validate_protocol_25_parent",
)
