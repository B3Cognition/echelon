"""Request identity and exact child reuse for protocol-2.7 synthesis."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from harness.squad_provider import SquadCliProvider

if TYPE_CHECKING:
    from .controller import Protocol27ControllerResult

from harness.re_v2.protocol_27.authority import (
    Protocol27AuthorityError,
    ResolvedSynthesisParentV1,
    freeze_accepted_source_overviews,
    frozen_overview_payloads,
    resolve_synthesis_parent,
)
from harness.re_v2.protocol_27.model import (
    PartialSourceAcceptanceV1,
    RunManifestV6,
    SynthesisBudgetPolicyV1,
    SynthesisRequestV1,
)
from harness.re_v2.run_store import load_run_manifest


class Protocol27LifecycleError(RuntimeError):
    """Raised when synthesis creation or exact reuse cannot proceed."""


def synthesis_request(
    parent: ResolvedSynthesisParentV1,
    budget_policy: SynthesisBudgetPolicyV1,
    *,
    expected_v2_index_hash: str,
    expected_compatibility_generation: int,
) -> SynthesisRequestV1:
    if not isinstance(parent, ResolvedSynthesisParentV1):
        raise Protocol27LifecycleError("synthesis request requires resolved parent authority")
    if not isinstance(budget_policy, SynthesisBudgetPolicyV1):
        raise Protocol27LifecycleError("synthesis request requires a synthesis budget policy")
    return SynthesisRequestV1(
        schema_version=1,
        parent_manifest_hash=parent.parent_manifest_hash,
        accepted_source_outcome_ids=tuple(
            sorted(item.identity for item in parent.accepted_sources)
        ),
        accepted_partial_source_ids=tuple(
            item.source_id for item in parent.accepted_sources if item.outcome == "partial"
        ),
        budget_policy_hash=budget_policy.identity,
        expected_v2_index_hash=expected_v2_index_hash,
        expected_compatibility_generation=expected_compatibility_generation,
    )


def partial_acceptance_for(
    parent: ResolvedSynthesisParentV1,
    source_id: str,
    request: SynthesisRequestV1,
) -> PartialSourceAcceptanceV1:
    source = next(
        (item for item in parent.accepted_sources if item.source_id == source_id),
        None,
    )
    if source is None:
        raise Protocol27AuthorityError(f"unknown partial source: {source_id}")
    if source.outcome != "partial" or source.debt_manifest_hash is None:
        raise Protocol27AuthorityError(
            f"complete source cannot be accepted as partial: {source_id}"
        )
    summary_hash = parent.debt_summary_hashes.get(source_id)
    if summary_hash is None:
        raise Protocol27AuthorityError(
            f"partial source has no authenticated debt summary: {source_id}"
        )
    if source_id not in request.accepted_partial_source_ids:
        raise Protocol27AuthorityError(
            f"request does not accept partial source: {source_id}"
        )
    return PartialSourceAcceptanceV1(
        schema_version=1,
        parent_run_id=parent.parent_run_id,
        parent_manifest_hash=parent.parent_manifest_hash,
        source_id=source.source_id,
        source_root_key_id=source.source_root_key_id,
        source_root_hash=source.source_root_hash,
        debt_manifest_hash=source.debt_manifest_hash,
        debt_summary_hash=summary_hash,
        operation_id=request.request_id,
    )


def partial_acceptances_for(
    parent: ResolvedSynthesisParentV1,
    request: SynthesisRequestV1,
) -> tuple[PartialSourceAcceptanceV1, ...]:
    expected = tuple(
        item.source_id for item in parent.accepted_sources if item.outcome == "partial"
    )
    if request.parent_manifest_hash != parent.parent_manifest_hash:
        raise Protocol27AuthorityError("request parent manifest does not match authority")
    if request.accepted_partial_source_ids != expected:
        raise Protocol27AuthorityError(
            "request partial acceptance set differs from parent authority"
        )
    return tuple(partial_acceptance_for(parent, source_id, request) for source_id in expected)


def find_exact_protocol_27_child(
    workspace_root: Path,
    request_id: str,
) -> Path | None:
    runs = Path(workspace_root).resolve() / "runs"
    if not runs.is_dir():
        return None
    matches: list[Path] = []
    for candidate in sorted(runs.iterdir(), key=lambda item: item.name):
        manifest_path = candidate / "v2" / "run.json"
        if candidate.is_symlink() or not manifest_path.is_file() or manifest_path.is_symlink():
            continue
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(raw, dict) or (
            raw.get("schema_version"), raw.get("engine_protocol_version")
        ) != (6, "2.7"):
            continue
        try:
            manifest = load_run_manifest(candidate)
        except Exception as exc:
            raise Protocol27AuthorityError(
                f"invalid protocol-2.7 child manifest: {candidate.name}"
            ) from exc
        if isinstance(manifest, RunManifestV6) and manifest.request_id == request_id:
            matches.append(candidate)
    if len(matches) > 1:
        raise Protocol27AuthorityError(
            "multiple protocol-2.7 children share one exact request identity"
        )
    return matches[0] if matches else None


def execute_protocol_27_request(
    workspace_root: Path,
    options: object,
    provider_factory: Callable[[], SquadCliProvider],
) -> "Protocol27ControllerResult":
    """Find or create the exact immutable child, activate it, and run it."""
    from echelon.cli import _activate_re_v2_run, _new_re_v2_run_id, _re_v2_now
    from harness.re_registry import load_published_index
    from harness.re_v2.publication import current_index_hash, load_published_v2_index

    root = Path(workspace_root).resolve()
    from_run = getattr(options, "from_run", None)
    accepted = getattr(options, "accepted_partial_sources", None)
    if not isinstance(from_run, str) or not isinstance(accepted, tuple):
        raise Protocol27LifecycleError("invalid protocol-2.7 synthesis options")
    parent = resolve_synthesis_parent(root, from_run, accepted)
    budget = SynthesisBudgetPolicyV1(
        schema_version=1,
        token_limit=getattr(options, "token_limit", None),
        active_ms_limit=getattr(options, "active_ms_limit", None),
        provider_attempt_limit=2,
        generation_attempt_limit=2,
        result_contract_retry_limit=1,
        artifact_contract_retry_limit=1,
    )
    published = load_published_index(root)
    published_v2 = load_published_v2_index(root)
    request = synthesis_request(
        parent,
        budget,
        expected_v2_index_hash=current_index_hash(root),
        expected_compatibility_generation=(
            0 if published is None else published.generation
        ),
    )
    existing = _published_equivalent_child(
        root,
        parent,
        budget,
        published,
        published_v2,
    )
    if existing is None:
        existing = find_exact_protocol_27_child(root, request.request_id)
    if existing is None:
        run_id = _new_re_v2_run_id(root)
        inputs = _protocol_27_input_set(
            root,
            run_id,
            _re_v2_now(),
            parent,
            request,
            budget,
        )
        from .inputs import prepare_protocol_27_child

        existing = prepare_protocol_27_child(root, run_id, inputs).run_dir
    _activate_re_v2_run(root, existing.name)
    return run_protocol_27_synthesis(existing, provider_factory)


def _published_equivalent_child(
    workspace_root: Path,
    parent: ResolvedSynthesisParentV1,
    budget: SynthesisBudgetPolicyV1,
    compatibility_index: object | None,
    v2_index: object | None,
) -> Path | None:
    """Reuse the currently published exact operation after its CAS bases advanced."""
    compatibility_run = getattr(compatibility_index, "published_from_run", None)
    v2_run = getattr(v2_index, "run_id", None)
    if not isinstance(compatibility_run, str) or compatibility_run != v2_run:
        return None
    candidate = workspace_root / "runs" / compatibility_run
    if candidate.is_symlink() or not candidate.is_dir():
        return None
    manifest = load_run_manifest(candidate)
    if not isinstance(manifest, RunManifestV6):
        return None
    expected_outcomes = tuple(
        sorted(item.identity for item in parent.accepted_sources)
    )
    expected_partials = tuple(
        item.source_id for item in parent.accepted_sources if item.outcome == "partial"
    )
    if (
        manifest.parent_manifest_hash != parent.parent_manifest_hash
        or tuple(sorted(item.identity for item in manifest.accepted_sources))
        != expected_outcomes
        or tuple(item.source_id for item in manifest.partial_acceptances)
        != expected_partials
        or manifest.budget_policy != budget
    ):
        return None
    return candidate


def run_synthesis_child(
    workspace_root: Path,
    options: object,
    provider_factory: Callable[[], SquadCliProvider],
) -> "Protocol27ControllerResult":
    """Compatibility name for the registered protocol-2.7 lifecycle seam."""
    return execute_protocol_27_request(workspace_root, options, provider_factory)


def _protocol_27_input_set(
    workspace_root: Path,
    run_id: str,
    created_at: str,
    parent: ResolvedSynthesisParentV1,
    request: SynthesisRequestV1,
    budget: SynthesisBudgetPolicyV1,
) -> object:
    from harness.re_v2.canonical import canonical_json_bytes, content_digest
    from harness.re_v2.ledger import ObjectStore
    from harness.re_v2.protocol_22.executors import SHARED_AI_CLI_ADAPTER_ID
    from harness.re_v2.protocol_22.provider import canonical_prosaic_agent_bytes

    from .checkpoints import (
        reconstruct_synthesis_checkpoints,
        select_synthesis_checkpoints,
        stage_synthesis_checkpoint_selection,
    )
    from .context import default_synthesis_context_policy
    from .execution import compose_synthesis_executor
    from .graph import (
        SynthesisGraphInputsV1,
        build_synthesis_graph,
        build_workspace_synthesis_topology,
    )
    from .inputs import Protocol27InputSet, load_protocol_27_inputs
    from .policies import (
        SynthesisImplementationAuthorityV1,
        build_synthesis_policy_catalog,
    )
    from .schemas import (
        SYNTHESIS_GENERATED_KINDS,
        canonical_synthesis_response_schema_bytes,
    )

    overviews = freeze_accepted_source_overviews(parent)
    overview_payloads = frozen_overview_payloads(parent)
    parent_run_dir = workspace_root / "runs" / parent.parent_run_id
    parent_manifest = load_run_manifest(parent_run_dir)
    if isinstance(parent_manifest, RunManifestV6):
        inherited = load_protocol_27_inputs(parent_run_dir)
        graph = inherited.graph
        prosaic = inherited.prosaic_authority_bytes
        implementation = graph.policy_catalog.implementation_authority
        required = {
            *(
                value
                for source in parent.accepted_sources
                for value in (
                    source.source_root_hash,
                    source.debt_manifest_hash,
                    *source.lower_authority_ids,
                )
                if value is not None
            ),
            *graph.response_schema_hashes.values(),
            graph.context_policy_hash,
            implementation.producer_authority_hash,
            implementation.executor_contract_hash,
            implementation.verifier_authority_hash,
        }
        old_objects = ObjectStore(inherited.paths.objects)
        authority_objects = {
            object_hash: old_objects.read_blob(object_hash)
            for object_hash in sorted(required)
        }
    else:
        if parent._context is None:
            raise Protocol27LifecycleError(
                "lower-layer synthesis parent has no authenticated context"
            )
        from harness.prosaic_prompt_loader import (
            ProsaicPromptLoadError,
            ProsaicPromptLoader,
        )
        from harness.re_v2.protocol_26.authority import resolve_run_authority

        resolved = resolve_run_authority(parent._context)  # type: ignore[arg-type]
        topology = build_workspace_synthesis_topology(
            resolved.shared_inputs.workspace_partition
        )
        try:
            artifact = ProsaicPromptLoader(workspace_root).load_subagent(
                "echelon.re-synthesizer"
            )
        except ProsaicPromptLoadError as exc:
            raise Protocol27LifecycleError(str(exc)) from exc
        if artifact is None:
            raise Protocol27LifecycleError(
                "installed Prosaic agent echelon.re-synthesizer is missing; run "
                "`echelon workspace migrate-to-prosaic` before synthesis"
            )
        prosaic = canonical_prosaic_agent_bytes(artifact)
        response_bytes = {
            kind: canonical_synthesis_response_schema_bytes(kind)
            for kind in SYNTHESIS_GENERATED_KINDS
        }
        context_policy = default_synthesis_context_policy()
        context_bytes = canonical_json_bytes(context_policy.to_json_dict())
        renderer_bytes = _implementation_authority_payload(
            "harness.re_v2.protocol_27.execution",
            "harness.re_v2.protocol_27.context",
            "harness.re_v2.protocol_27.schemas",
        )
        verifier_bytes = _implementation_authority_payload(
            "harness.re_v2.protocol_27.runtime",
            "harness.re_v2.protocol_27.schemas",
        )
        cli_entries = tuple(
            entry
            for entry in resolved.shared_inputs.executor_contract.entries
            if entry.execution_mode == "cli"
            and entry.adapter_id == SHARED_AI_CLI_ADAPTER_ID
        )
        if not cli_entries:
            raise Protocol27LifecycleError(
                "synthesis parent has no pinned shared CLI executor"
            )
        inherited_cli = sorted(cli_entries, key=lambda item: item.producer_family)[0]
        executor = compose_synthesis_executor(
            inherited_cli,
            agent_contract_hash=content_digest(prosaic),
            response_schema_hashes={
                kind: content_digest(payload)
                for kind, payload in response_bytes.items()
            },
            renderer_implementation_digest=content_digest(renderer_bytes),
            verifier_implementation_digest=content_digest(verifier_bytes),
        )
        implementation = SynthesisImplementationAuthorityV1(
            schema_version=1,
            producer_authority_hash=content_digest(prosaic),
            executor_contract_hash=executor.executor_contract_hash,
            verifier_authority_hash=content_digest(verifier_bytes),
        )
        graph = build_synthesis_graph(
            SynthesisGraphInputsV1(
                accepted_sources=parent.accepted_sources,
                source_overviews=overviews,
                topology=topology,
                policy_catalog=build_synthesis_policy_catalog(implementation),
                response_schema_hashes={
                    kind: content_digest(payload)
                    for kind, payload in response_bytes.items()
                },
                context_policy_hash=context_policy.identity,
            )
        )
        authority_objects = dict(parent.authority_objects)
        authority_objects.update(
            {content_digest(payload): payload for payload in response_bytes.values()}
        )
        authority_objects.update(
            {
                context_policy.identity: context_bytes,
                content_digest(prosaic): prosaic,
                executor.executor_contract_hash: canonical_json_bytes(
                    executor.to_json_dict()
                ),
                content_digest(verifier_bytes): verifier_bytes,
            }
        )
    inventory = reconstruct_synthesis_checkpoints(workspace_root)
    selection = select_synthesis_checkpoints(
        graph,
        inventory.only_origin(parent.parent_run_id),
        inventory,
    )
    checkpoint_objects = stage_synthesis_checkpoint_selection(
        workspace_root / "runs" / run_id,
        selection,
    )
    return Protocol27InputSet(
        run_id=run_id,
        created_at=created_at,
        parent=parent,
        request=request,
        partial_acceptances=partial_acceptances_for(parent, request),
        source_overview_catalog=overviews,
        source_overview_bytes=overview_payloads,
        graph=graph,
        prosaic_authority_bytes=prosaic,
        budget_policy=budget,
        checkpoint_selection_bytes=canonical_json_bytes(selection.to_json_dict()),
        authority_objects=authority_objects,
        checkpoint_objects=checkpoint_objects,
    )


def _implementation_authority_payload(*module_names: str) -> bytes:
    """Freeze the same logical closure shape used by existing RE authorities."""
    from harness.re_v2.canonical import canonical_json_bytes, content_digest

    rows: list[dict[str, str]] = []
    for module_name in module_names:
        module = __import__(module_name, fromlist=["authority"])
        module_path = Path(str(getattr(module, "__file__", "")))
        if module_path.suffix == ".pyc" and module_path.with_suffix(".py").is_file():
            module_path = module_path.with_suffix(".py")
        if module_path.is_symlink() or not module_path.is_file():
            raise Protocol27LifecycleError(
                f"synthesis implementation authority is unavailable: {module_name}"
            )
        rows.append(
            {
                "content_hash": content_digest(module_path.read_bytes()),
                "logical_path": module_name.replace(".", "/") + ".py",
            }
        )
    return canonical_json_bytes(
        {
            "closure_schema": "implementation-closure-v1",
            "files": sorted(rows, key=lambda item: item["logical_path"].encode("utf-8")),
        }
    )


def run_protocol_27_synthesis(
    run_dir: Path,
    provider_factory: Callable[[], SquadCliProvider],
    fault_hook: Callable[[str], None] | None = None,
) -> "Protocol27ControllerResult":
    """Recover first, then execute only unresolved synthesis work."""
    from .budget import evaluate_synthesis_budget
    from .controller import Protocol27Controller, Protocol27ControllerResult
    from .recovery import load_protocol_27_run_context, recover_protocol_27_run

    context = load_protocol_27_run_context(Path(run_dir))
    recovered = recover_protocol_27_run(context, fault_hook)
    if recovered.pending_action is not None:
        ledger = context.ledger.replay()
        budget = evaluate_synthesis_budget(
            context.inputs.manifest,
            context.events.replay(),
            ledger,
        )
        return Protocol27ControllerResult(
            synthesis_closure_complete=False,
            terminal_kind=recovered.pending_action,
            accepted_artifact_count=len(ledger.accepted_artifacts),
            required_artifact_count=len(context.inputs.graph.required_nodes),
            provider_attempts=budget.provider_attempts,
            contract_retries=(
                sum(budget.result_contract_retries.values())
                + sum(budget.artifact_contract_retries.values())
            ),
            synthesis_root_id=(
                None
                if ledger.synthesis_root is None
                else ledger.synthesis_root.identity
            ),
        )
    return Protocol27Controller(
        context.inputs,
        provider_factory=provider_factory,
        clock=context.clock,
        fault_hook=fault_hook,
    ).run_to_closure()


__all__ = (
    "Protocol27LifecycleError",
    "execute_protocol_27_request",
    "find_exact_protocol_27_child",
    "partial_acceptance_for",
    "partial_acceptances_for",
    "run_protocol_27_synthesis",
    "run_synthesis_child",
    "synthesis_request",
)
