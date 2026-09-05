"""Pure, provider-prose-free operator guidance status for L3 blockers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping

from harness.re_v2.protocol_22.schema import digest_value, safe_id

from .findings import SemanticFindingV1


RECOMMENDED_COMMAND = "echelon re resume --recommended"
BANZAI_COMMAND = "echelon re resume --banzai"
CUSTOM_COMMAND = 'echelon re resume "<your guidance>"'

GuidanceActionIdV1 = Literal["recommended", "banzai", "custom"]


@dataclass(frozen=True, slots=True)
class GuidanceActionV1:
    action_id: GuidanceActionIdV1
    command: str
    enabled: bool

    def __post_init__(self) -> None:
        expected = {
            "recommended": RECOMMENDED_COMMAND,
            "banzai": BANZAI_COMMAND,
            "custom": CUSTOM_COMMAND,
        }
        if self.action_id not in expected or self.command != expected[self.action_id]:
            raise ValueError("guidance action is not an installed fixed command")
        if not isinstance(self.enabled, bool):
            raise ValueError("guidance action enabled must be boolean")

    def to_json_dict(self) -> dict[str, object]:
        return {
            "action_id": self.action_id,
            "command": self.command,
            "enabled": self.enabled,
        }


@dataclass(frozen=True, slots=True)
class GuidanceSummaryV1:
    run_id: str
    manifest_hash: str
    frozen_count: int
    closed_count: int
    unresolved_count: int
    unresolved_by_class: tuple[tuple[str, int], ...]
    unresolved_by_source: tuple[tuple[str, int], ...]
    recommended_eligible: bool
    banzai_eligible: bool
    actions: tuple[GuidanceActionV1, ...]

    def __post_init__(self) -> None:
        safe_id(self.run_id, "guidance summary run")
        digest_value(self.manifest_hash, "guidance summary manifest")
        counts = (self.frozen_count, self.closed_count, self.unresolved_count)
        if any(not isinstance(item, int) or isinstance(item, bool) or item < 0 for item in counts):
            raise ValueError("guidance summary counts must be nonnegative integers")
        if self.closed_count + self.unresolved_count != self.frozen_count:
            raise ValueError("guidance summary finding counts do not close")
        for label, groups in (
            ("class", self.unresolved_by_class),
            ("source", self.unresolved_by_source),
        ):
            if tuple(groups) != tuple(sorted(groups)) or len({key for key, _ in groups}) != len(groups):
                raise ValueError(f"guidance summary {label} groups are not stable")
            for key, count in groups:
                safe_id(key, f"guidance summary {label}")
                if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
                    raise ValueError(f"guidance summary {label} count is invalid")
            if sum(count for _, count in groups) != self.unresolved_count:
                raise ValueError(f"guidance summary {label} counts do not close")
        if not isinstance(self.recommended_eligible, bool) or not isinstance(
            self.banzai_eligible, bool
        ):
            raise ValueError("guidance eligibility must be boolean")
        expected_ids = ("recommended", "banzai", "custom")
        if tuple(item.action_id for item in self.actions) != expected_ids:
            raise ValueError("guidance actions must use installed stable order")

    def to_json_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "manifest_hash": self.manifest_hash,
            "frozen_count": self.frozen_count,
            "closed_count": self.closed_count,
            "unresolved_count": self.unresolved_count,
            "unresolved_by_class": [
                {"finding_class": key, "count": count}
                for key, count in self.unresolved_by_class
            ],
            "unresolved_by_source": [
                {"source_id": key, "count": count}
                for key, count in self.unresolved_by_source
            ],
            "recommended_eligible": self.recommended_eligible,
            "banzai_eligible": self.banzai_eligible,
            "actions": [item.to_json_dict() for item in self.actions],
        }


def derive_guidance_summary(
    *,
    run_id: str,
    manifest_hash: str,
    status: str,
    frozen_finding_ids: tuple[str, ...],
    unresolved_finding_ids: tuple[str, ...],
    findings: tuple[SemanticFindingV1, ...],
    source_by_target: Mapping[str, str],
    all_selected_audits_accepted: bool,
    has_frozen_epoch: bool,
    has_final_closure_root: bool,
    all_selected_roots_accepted: bool,
) -> GuidanceSummaryV1:
    """Derive fixed operator actions from authenticated structural authority only."""
    frozen = frozenset(frozen_finding_ids)
    unresolved = frozenset(unresolved_finding_ids)
    if not unresolved.issubset(frozen):
        raise ValueError("unresolved guidance findings are outside the frozen epoch")
    by_id: dict[str, SemanticFindingV1] = {}
    for finding in findings:
        if not isinstance(finding, SemanticFindingV1):
            raise ValueError("guidance finding authority is invalid")
        existing = by_id.get(finding.finding_key_id)
        if existing is not None and existing != finding:
            raise ValueError("guidance finding authority conflicts")
        by_id[finding.finding_key_id] = finding
    missing = unresolved - set(by_id)
    if missing:
        raise ValueError("unresolved guidance finding has no authenticated authority")

    by_class: dict[str, int] = {}
    by_source: dict[str, int] = {}
    for finding_id in sorted(unresolved):
        finding = by_id[finding_id]
        finding_class = finding.finding_key.finding_class
        source = source_by_target.get(finding.finding_key.audit_target_id)
        if source is None:
            raise ValueError("unresolved guidance finding has no authenticated source")
        by_class[finding_class] = by_class.get(finding_class, 0) + 1
        by_source[source] = by_source.get(source, 0) + 1

    recommended = status in {"blocked_incomplete", "blocked_plateau"}
    banzai = bool(
        status == "blocked_plateau"
        and unresolved
        and all_selected_audits_accepted
        and has_frozen_epoch
        and has_final_closure_root
        and all_selected_roots_accepted
    )
    return GuidanceSummaryV1(
        run_id=run_id,
        manifest_hash=manifest_hash,
        frozen_count=len(frozen),
        closed_count=len(frozen - unresolved),
        unresolved_count=len(unresolved),
        unresolved_by_class=tuple(sorted(by_class.items())),
        unresolved_by_source=tuple(sorted(by_source.items())),
        recommended_eligible=recommended,
        banzai_eligible=banzai,
        actions=(
            GuidanceActionV1("recommended", RECOMMENDED_COMMAND, recommended),
            GuidanceActionV1("banzai", BANZAI_COMMAND, banzai),
            GuidanceActionV1("custom", CUSTOM_COMMAND, recommended),
        ),
    )


__all__ = (
    "BANZAI_COMMAND",
    "CUSTOM_COMMAND",
    "GuidanceActionV1",
    "GuidanceSummaryV1",
    "RECOMMENDED_COMMAND",
    "derive_guidance_summary",
)
