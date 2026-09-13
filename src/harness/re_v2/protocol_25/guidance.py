"""Typed immutable operator-guidance authority for RE v2 L3."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
import unicodedata

from harness.re_v2.canonical import content_digest
from harness.re_v2.protocol_22.schema import (
    Protocol22SchemaError,
    boolean,
    digest_value,
    exact_object,
    literal,
    nonnegative_int,
    one_of,
    optional_digest,
    sorted_unique_digests,
)

GuidanceKindV1 = Literal["custom", "recommended", "banzai"]
_GUIDANCE_KINDS = frozenset({"custom", "recommended", "banzai"})

RECOMMENDED_GUIDANCE_TEXT = (
    "Use only accepted bounded authority. Close a finding only when evidence "
    "supports correction or qualification; otherwise preserve it explicitly "
    "as unresolved. Never invent evidence or suppress a finding to converge. "
    "Record deeper-evidence and human-decision needs explicitly."
)

_LEGACY_FIELDS = frozenset(
    {
        "accepted_audit_candidate_hashes",
        "answer",
        "audit_epoch_id",
        "closure_root_hash",
        "parent_manifest_hash",
        "parent_terminal_event_hash",
        "schema_version",
        "unresolved_audit_target_ids",
        "unresolved_finding_ids",
    }
)
_FIELDS = frozenset(
    {
        *_LEGACY_FIELDS,
        "kind",
        "accept_residual_debt",
        "automatic_successor_limit",
        "automation_root_manifest_hash",
        "successor_index",
    }
)


def normalize_guidance_answer(answer: object) -> str:
    """Return bounded NFC guidance suitable for immutable publication."""
    if not isinstance(answer, str):
        raise ValueError("guidance answer must be text")
    normalized = unicodedata.normalize(
        "NFC",
        answer.replace("\r\n", "\n").replace("\r", "\n"),
    ).strip()
    if not normalized:
        raise ValueError("guidance answer must be nonempty")
    if len(normalized.encode("utf-8", errors="strict")) > 8192:
        raise ValueError("guidance answer must be at most 8192 UTF-8 bytes")
    if any(
        unicodedata.category(character) == "Cc" and character != "\n"
        for character in normalized
    ):
        raise ValueError("guidance answer contains unsupported control characters")
    return normalized


@dataclass(frozen=True, slots=True)
class GuidancePolicyV1:
    """Operator-selected behavior, separate from blocked-parent authority."""

    kind: GuidanceKindV1
    answer: str
    accept_residual_debt: bool
    automatic_successor_limit: int
    automation_root_manifest_hash: str | None
    successor_index: int

    def __post_init__(self) -> None:
        try:
            kind = one_of(self.kind, _GUIDANCE_KINDS, "guidance policy kind")
            debt = boolean(
                self.accept_residual_debt,
                "guidance policy residual-debt acceptance",
            )
            limit = nonnegative_int(
                self.automatic_successor_limit,
                "guidance policy automatic successor limit",
            )
            index = nonnegative_int(
                self.successor_index,
                "guidance policy successor index",
            )
            root = optional_digest(
                self.automation_root_manifest_hash,
                "guidance policy automation root",
            )
        except Protocol22SchemaError as exc:
            raise ValueError(str(exc)) from exc
        answer = normalize_guidance_answer(self.answer)
        if kind == "custom":
            if debt or limit != 0 or root is not None or index != 0:
                raise ValueError(
                    "custom guidance cannot enable debt acceptance or automation"
                )
        elif kind == "recommended":
            if answer != RECOMMENDED_GUIDANCE_TEXT:
                raise ValueError("recommended guidance must use the installed answer")
            if debt or limit != 0 or root is not None or index != 0:
                raise ValueError(
                    "recommended guidance cannot enable debt acceptance or automation"
                )
        else:
            if answer != RECOMMENDED_GUIDANCE_TEXT:
                raise ValueError("banzai guidance must use the installed answer")
            if not debt or limit != 1 or index != 1 or root is None:
                raise ValueError(
                    "banzai guidance must authorize exactly one automatic successor"
                )
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "answer", answer)
        object.__setattr__(self, "accept_residual_debt", debt)
        object.__setattr__(self, "automatic_successor_limit", limit)
        object.__setattr__(self, "automation_root_manifest_hash", root)
        object.__setattr__(self, "successor_index", index)


def custom_guidance_policy(answer: str) -> GuidancePolicyV1:
    return GuidancePolicyV1("custom", answer, False, 0, None, 0)


def recommended_guidance_policy() -> GuidancePolicyV1:
    return GuidancePolicyV1(
        "recommended",
        RECOMMENDED_GUIDANCE_TEXT,
        False,
        0,
        None,
        0,
    )


def banzai_guidance_policy(
    automation_root_manifest_hash: str,
) -> GuidancePolicyV1:
    return GuidancePolicyV1(
        "banzai",
        RECOMMENDED_GUIDANCE_TEXT,
        True,
        1,
        automation_root_manifest_hash,
        1,
    )


@dataclass(frozen=True, slots=True)
class GuidanceDirectiveV1:
    """Exact blocked authority plus the operator policy allowed to affect it."""

    schema_version: Literal[1]
    kind: GuidanceKindV1
    answer: str
    parent_manifest_hash: str
    parent_terminal_event_hash: str
    accepted_audit_candidate_hashes: tuple[str, ...]
    unresolved_audit_target_ids: tuple[str, ...]
    audit_epoch_id: str | None
    closure_root_hash: str | None
    unresolved_finding_ids: tuple[str, ...]
    accept_residual_debt: bool
    automatic_successor_limit: int
    automation_root_manifest_hash: str | None
    successor_index: int

    def __post_init__(self) -> None:
        try:
            literal(self.schema_version, 1, "guidance directive schema version")
            parent_manifest_hash = digest_value(
                self.parent_manifest_hash,
                "guidance parent manifest",
            )
            parent_terminal_event_hash = digest_value(
                self.parent_terminal_event_hash,
                "guidance parent terminal event",
            )
            candidates = sorted_unique_digests(
                self.accepted_audit_candidate_hashes,
                "guidance accepted audit candidates",
            )
            targets = sorted_unique_digests(
                self.unresolved_audit_target_ids,
                "guidance unresolved audit targets",
            )
            findings = sorted_unique_digests(
                self.unresolved_finding_ids,
                "guidance unresolved findings",
            )
            audit_epoch_id = optional_digest(
                self.audit_epoch_id,
                "guidance audit epoch",
            )
            closure_root_hash = optional_digest(
                self.closure_root_hash,
                "guidance closure root",
            )
        except Protocol22SchemaError as exc:
            raise ValueError(str(exc)) from exc
        policy = GuidancePolicyV1(
            self.kind,
            self.answer,
            self.accept_residual_debt,
            self.automatic_successor_limit,
            self.automation_root_manifest_hash,
            self.successor_index,
        )
        pre_epoch = audit_epoch_id is None and closure_root_hash is None
        if pre_epoch:
            if not candidates or not targets or findings:
                raise ValueError(
                    "pre-epoch guidance requires retained candidates and unresolved targets"
                )
        elif audit_epoch_id is None or not findings or targets:
            raise ValueError(
                "closure guidance requires an epoch and unresolved findings"
            )
        object.__setattr__(self, "kind", policy.kind)
        object.__setattr__(self, "answer", policy.answer)
        object.__setattr__(self, "parent_manifest_hash", parent_manifest_hash)
        object.__setattr__(
            self,
            "parent_terminal_event_hash",
            parent_terminal_event_hash,
        )
        object.__setattr__(self, "accepted_audit_candidate_hashes", candidates)
        object.__setattr__(self, "unresolved_audit_target_ids", targets)
        object.__setattr__(self, "audit_epoch_id", audit_epoch_id)
        object.__setattr__(self, "closure_root_hash", closure_root_hash)
        object.__setattr__(self, "unresolved_finding_ids", findings)
        object.__setattr__(
            self,
            "accept_residual_debt",
            policy.accept_residual_debt,
        )
        object.__setattr__(
            self,
            "automatic_successor_limit",
            policy.automatic_successor_limit,
        )
        object.__setattr__(
            self,
            "automation_root_manifest_hash",
            policy.automation_root_manifest_hash,
        )
        object.__setattr__(self, "successor_index", policy.successor_index)

    @property
    def identity(self) -> str:
        return content_digest(self.to_json_dict())

    @property
    def policy(self) -> GuidancePolicyV1:
        return GuidancePolicyV1(
            self.kind,
            self.answer,
            self.accept_residual_debt,
            self.automatic_successor_limit,
            self.automation_root_manifest_hash,
            self.successor_index,
        )

    def to_json_dict(self) -> dict[str, object]:
        return {
            "accepted_audit_candidate_hashes": list(
                self.accepted_audit_candidate_hashes
            ),
            "accept_residual_debt": self.accept_residual_debt,
            "answer": self.answer,
            "audit_epoch_id": self.audit_epoch_id,
            "automatic_successor_limit": self.automatic_successor_limit,
            "automation_root_manifest_hash": self.automation_root_manifest_hash,
            "closure_root_hash": self.closure_root_hash,
            "kind": self.kind,
            "parent_manifest_hash": self.parent_manifest_hash,
            "parent_terminal_event_hash": self.parent_terminal_event_hash,
            "schema_version": self.schema_version,
            "successor_index": self.successor_index,
            "unresolved_audit_target_ids": list(self.unresolved_audit_target_ids),
            "unresolved_finding_ids": list(self.unresolved_finding_ids),
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "GuidanceDirectiveV1":
        if not isinstance(value, dict):
            raise ValueError(
                "GuidanceDirectiveV1 must be an object with exact fields"
            )
        present = frozenset(value)
        legacy = present == _LEGACY_FIELDS
        try:
            raw = exact_object(
                value,
                _LEGACY_FIELDS if legacy else _FIELDS,
                "GuidanceDirectiveV1",
            )
            literal(raw["schema_version"], 1, "guidance directive schema version")
        except Protocol22SchemaError as exc:
            raise ValueError(str(exc)) from exc
        answer = normalize_guidance_answer(raw["answer"])
        if answer != raw["answer"]:
            raise ValueError("guidance directive answer must already be normalized")
        if legacy:
            policy = custom_guidance_policy(answer)
        else:
            try:
                policy = GuidancePolicyV1(
                    kind=one_of(raw["kind"], _GUIDANCE_KINDS, "guidance kind"),
                    answer=answer,
                    accept_residual_debt=boolean(
                        raw["accept_residual_debt"],
                        "guidance residual-debt acceptance",
                    ),
                    automatic_successor_limit=nonnegative_int(
                        raw["automatic_successor_limit"],
                        "guidance automatic successor limit",
                    ),
                    automation_root_manifest_hash=optional_digest(
                        raw["automation_root_manifest_hash"],
                        "guidance automation root",
                    ),
                    successor_index=nonnegative_int(
                        raw["successor_index"],
                        "guidance successor index",
                    ),
                )
            except Protocol22SchemaError as exc:
                raise ValueError(str(exc)) from exc
        return cls(
            schema_version=1,
            kind=policy.kind,
            answer=policy.answer,
            parent_manifest_hash=raw["parent_manifest_hash"],  # type: ignore[arg-type]
            parent_terminal_event_hash=raw["parent_terminal_event_hash"],  # type: ignore[arg-type]
            accepted_audit_candidate_hashes=tuple(
                raw["accepted_audit_candidate_hashes"]  # type: ignore[arg-type]
            ),
            unresolved_audit_target_ids=tuple(
                raw["unresolved_audit_target_ids"]  # type: ignore[arg-type]
            ),
            audit_epoch_id=raw["audit_epoch_id"],  # type: ignore[arg-type]
            closure_root_hash=raw["closure_root_hash"],  # type: ignore[arg-type]
            unresolved_finding_ids=tuple(
                raw["unresolved_finding_ids"]  # type: ignore[arg-type]
            ),
            accept_residual_debt=policy.accept_residual_debt,
            automatic_successor_limit=policy.automatic_successor_limit,
            automation_root_manifest_hash=policy.automation_root_manifest_hash,
            successor_index=policy.successor_index,
        )


def build_guidance_directive(
    *,
    policy: GuidancePolicyV1,
    parent_manifest_hash: str,
    parent_terminal_event_hash: str,
    accepted_audit_candidate_hashes: tuple[str, ...],
    unresolved_audit_target_ids: tuple[str, ...],
    audit_epoch_id: str | None,
    closure_root_hash: str | None,
    unresolved_finding_ids: tuple[str, ...],
) -> GuidanceDirectiveV1:
    if not isinstance(policy, GuidancePolicyV1):
        raise ValueError("guidance policy has an unsupported type")
    return GuidanceDirectiveV1(
        schema_version=1,
        kind=policy.kind,
        answer=policy.answer,
        parent_manifest_hash=parent_manifest_hash,
        parent_terminal_event_hash=parent_terminal_event_hash,
        accepted_audit_candidate_hashes=accepted_audit_candidate_hashes,
        unresolved_audit_target_ids=unresolved_audit_target_ids,
        audit_epoch_id=audit_epoch_id,
        closure_root_hash=closure_root_hash,
        unresolved_finding_ids=unresolved_finding_ids,
        accept_residual_debt=policy.accept_residual_debt,
        automatic_successor_limit=policy.automatic_successor_limit,
        automation_root_manifest_hash=policy.automation_root_manifest_hash,
        successor_index=policy.successor_index,
    )


__all__ = (
    "GuidanceDirectiveV1",
    "GuidanceKindV1",
    "GuidancePolicyV1",
    "RECOMMENDED_GUIDANCE_TEXT",
    "banzai_guidance_policy",
    "build_guidance_directive",
    "custom_guidance_policy",
    "normalize_guidance_answer",
    "recommended_guidance_policy",
)
