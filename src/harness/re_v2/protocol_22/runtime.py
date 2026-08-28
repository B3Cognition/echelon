"""Installed deterministic runtime seams for protocol 2.2."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ConservativeTokenizerV1:
    """Pinned provider-neutral tokenizer that returns the byte-count fallback."""

    tokenizer_id: str
    tokenizer_version: str
    implementation_digest: str

    @classmethod
    def for_executor(cls, executor: object) -> "ConservativeTokenizerV1":
        authority = getattr(executor, "request_tokenizer", None)
        if authority is None:
            raise ValueError("protocol-2.2 provider executor has no tokenizer")
        return cls(
            tokenizer_id=str(getattr(authority, "tokenizer_id")),
            tokenizer_version=str(getattr(authority, "tokenizer_version")),
            implementation_digest=str(getattr(authority, "implementation_digest")),
        )

    def count_tokens(self, payload: bytes) -> None:
        del payload
        return None


@dataclass(frozen=True, slots=True)
class DeterministicRuntimeV1:
    """Produce and certify the closed in-process artifact families."""

    inputs: object
    snapshot: object

    def produce(self, item: object, dependencies: object) -> bytes:
        from .context import (
            build_domain_context_bundle,
            build_source_baseline_root,
            build_source_overview_context_bundle,
        )
        from .evidence import build_evidence_pack
        from .inventory import (
            produce_domain_inventory,
            produce_source_inventory,
            produce_source_partition,
        )
        from .policies import policy_for

        kind = getattr(getattr(item, "output_key"), "artifact_kind")
        if kind == "source-inventory":
            return produce_source_inventory(item, self.inputs)
        if kind == "domain-inventory":
            return produce_domain_inventory(item, self.inputs)
        if kind == "source-partition":
            return produce_source_partition(item, self.inputs)
        if kind in {"source-evidence-pack", "domain-evidence-pack"}:
            inventory_role = (
                "source_inventory"
                if kind == "source-evidence-pack"
                else "domain_inventory"
            )
            return build_evidence_pack(
                item,
                dependencies.payload_for_role(inventory_role),
                self.snapshot,
                policy_for(self.inputs.artifact_policy, "L0", kind),
            )
        if kind == "domain-context-bundle":
            return build_domain_context_bundle(
                item,
                dependencies,
                self.inputs.artifact_policy,
            )
        if kind == "source-overview-context-bundle":
            return build_source_overview_context_bundle(
                item,
                dependencies,
                self.inputs.artifact_policy,
            )
        if kind == "source-baseline-root":
            return build_source_baseline_root(
                item,
                dependencies,
                self.inputs.workspace_partition,
            )
        raise ValueError(f"unsupported protocol-2.2 deterministic artifact: {kind}")

    def certify_deterministic(
        self,
        item: object,
        payload: bytes,
        dependencies: object,
    ) -> object:
        from harness.re_v2.canonical import content_digest

        from .artifacts import ContextBundleV1, DeterministicAssessmentInputV2
        from .baseline import certify_deterministic_artifact
        from .evidence import validate_evidence_pack
        from .inventory import validate_deterministic_artifact
        from .policies import policy_for
        from .schema import load_canonical_object

        kind = getattr(getattr(item, "output_key"), "artifact_kind")
        if kind.endswith("evidence-pack"):
            inventory_role = (
                "source_inventory"
                if kind == "source-evidence-pack"
                else "domain_inventory"
            )
            assessment = validate_evidence_pack(
                item,
                payload,
                dependencies.payload_for_role(inventory_role),
                self.snapshot,
                policy_for(self.inputs.artifact_policy, "L0", kind),
            )
        elif kind in {
            "domain-context-bundle",
            "source-overview-context-bundle",
        }:
            expected = self.produce(item, dependencies)
            try:
                context = load_canonical_object(
                    payload,
                    ContextBundleV1.from_json_dict,
                )
                canonical_valid = True
                depth_debt = context.depth_debt
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
                            else ("context_reconstruction_mismatch",)
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
        else:
            assessment = validate_deterministic_artifact(
                item,
                payload,
                self.inputs,
                dependencies,
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
        from .baseline import certify_compact_candidate

        executor = self.inputs.executor_contract.entry_for(
            getattr(item, "producer_family")
        )
        return certify_compact_candidate(
            candidate,
            item,
            context,
            self.snapshot,
            executor.verifier,
        )


__all__ = ("ConservativeTokenizerV1", "DeterministicRuntimeV1")
