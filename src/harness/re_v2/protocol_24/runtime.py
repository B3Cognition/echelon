"""Protocol-2.4 registrations over the shared deterministic/provider runtime seams."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from harness.re_v2.canonical import content_digest
from harness.re_v2.protocol_22.artifacts import (
    ContextBundleV1,
    DeterministicAssessmentInputV2,
    EvidencePackV1,
)
from harness.re_v2.protocol_22.baseline import certify_deterministic_artifact
from harness.re_v2.protocol_22.schema import load_canonical_object

from .artifacts import (
    L2SourceBaselineRootV1,
    build_l2_domain_context_bundle,
    build_l2_domain_evidence_pack,
    build_l2_source_baseline_root,
    build_l2_source_overview_context_bundle,
    certify_l2_compact_candidate,
)


@dataclass(frozen=True, slots=True)
class Protocol24DeterministicRuntime:
    """Register only L2 semantics; execution and durability remain shared."""

    inputs: object
    snapshot: object
    adopted_artifacts: Mapping[tuple[str, str | None, str, str], bytes] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        if not isinstance(self.adopted_artifacts, Mapping):
            raise ValueError("adopted_artifacts must be a mapping")
        object.__setattr__(
            self,
            "adopted_artifacts",
            MappingProxyType(dict(self.adopted_artifacts)),
        )

    def produce(self, item: object, dependencies: object) -> bytes:
        kind = getattr(getattr(item, "output_key"), "artifact_kind")
        if kind == "domain-evidence-pack":
            return build_l2_domain_evidence_pack(
                item,
                dependencies,
                self.inputs.artifact_policy,
                self.snapshot,
                self.adopted_artifacts,
            )
        if kind == "domain-context-bundle":
            return build_l2_domain_context_bundle(
                item,
                dependencies,
                self.inputs.artifact_policy,
            )
        if kind == "source-overview-context-bundle":
            return build_l2_source_overview_context_bundle(
                item,
                dependencies,
                self.inputs.artifact_policy,
            )
        if kind == "source-baseline-root":
            return build_l2_source_baseline_root(
                item,
                dependencies,
                self.inputs.workspace_partition,
            )
        raise ValueError(f"unsupported protocol-2.4 deterministic artifact: {kind}")

    def certify_deterministic(
        self,
        item: object,
        payload: bytes,
        dependencies: object,
    ) -> object:
        expected = self.produce(item, dependencies)
        kind = getattr(getattr(item, "output_key"), "artifact_kind")
        depth_debt = None
        canonical_valid = True
        try:
            if kind == "domain-evidence-pack":
                value = load_canonical_object(payload, EvidencePackV1.from_json_dict)
                depth_debt = value.depth_debt
            elif kind in {
                "domain-context-bundle",
                "source-overview-context-bundle",
            }:
                value = load_canonical_object(payload, ContextBundleV1.from_json_dict)
                depth_debt = value.depth_debt
            elif kind == "source-baseline-root":
                load_canonical_object(payload, L2SourceBaselineRootV1.from_json_dict)
            else:
                raise ValueError(f"unsupported deterministic artifact: {kind}")
        except Exception:
            canonical_valid = False
            depth_debt = None
        diagnostics = tuple(
            sorted(
                {
                    *(() if canonical_valid else ("canonical_schema_invalid",)),
                    *(
                        ()
                        if payload == expected
                        else ("deterministic_reconstruction_mismatch",)
                    ),
                }
            )
        )
        assessment = DeterministicAssessmentInputV2(
            canonical_schema_valid=canonical_valid,
            dependency_closure_valid=True,
            policy_conformance_valid=payload == expected,
            depth_debt=depth_debt,
            normalized_diagnostics=diagnostics,
        )
        executor = self.inputs.executor_contract.entry_for(
            getattr(item, "producer_family")
        )
        return certify_deterministic_artifact(
            item,
            content_digest(payload),
            assessment,
            executor.verifier,
        )

    def certify_candidate(
        self,
        candidate: object,
        item: object,
        context: object,
    ) -> object:
        executor = self.inputs.executor_contract.entry_for(
            getattr(item, "producer_family")
        )
        scope = getattr(getattr(item, "output_key"), "scope")
        kind = getattr(getattr(item, "output_key"), "artifact_kind")
        lower = self.adopted_artifacts.get(
            (scope.source_id, scope.domain_key, "L1", kind)
        )
        return certify_l2_compact_candidate(
            candidate,
            item,
            context,
            self.snapshot,
            executor.verifier,
            adopted_l1_artifacts=() if lower is None else (lower,),
        )


__all__ = ("Protocol24DeterministicRuntime",)
