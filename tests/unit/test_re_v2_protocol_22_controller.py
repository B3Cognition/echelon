from __future__ import annotations

from dataclasses import dataclass, field, replace
import json
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

import pytest

from harness.re_v2.protocol_22.controller import (
    Protocol22Controller,
    Protocol22ControllerError,
    Protocol22ControllerResult,
    accepted_dependencies_for,
)
from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.events import EventStore
from harness.re_v2.ledger import ObjectStore
from harness.re_v2.protocol_22.artifacts import (
    AcceptedDependencySetV2,
    ContextBundleV1,
    DeterministicAssessmentInputV2,
)
from harness.re_v2.protocol_22.baseline import (
    CertificationReceiptV2,
    CompactCandidateInputV1,
    CompactCertificationResultV2,
    certify_compact_candidate,
    certify_deterministic_artifact,
)
from harness.re_v2.protocol_22.context import (
    build_domain_context_bundle,
    build_source_baseline_root,
    build_source_overview_context_bundle,
)
from harness.re_v2.protocol_22.evidence import (
    build_evidence_pack,
    validate_evidence_pack,
)
from harness.re_v2.protocol_22.events import PROTOCOL_22_EVENTS
from harness.re_v2.protocol_22.execution import (
    DeterministicExecutionDependenciesV1,
    Protocol22ExecutionStore,
    ProviderExecutionDependenciesV1,
)
from harness.re_v2.protocol_22.graph import (
    AcceptedArtifactV2,
    build_protocol_22_graph,
)
from harness.re_v2.protocol_22.inputs import (
    Protocol22InputSet,
    create_protocol_22_run_store,
    load_protocol_22_inputs,
)
from harness.re_v2.protocol_22.inventory import (
    produce_domain_inventory,
    produce_source_inventory,
    produce_source_partition,
    validate_deterministic_artifact,
)
from harness.re_v2.protocol_22.ledger import Protocol22Ledger
from harness.re_v2.protocol_22.model import (
    DeterministicInvocationInputV1,
    DeterministicInvocationV1,
    WorkItemV2,
)
from harness.re_v2.protocol_22.policies import policy_for
from harness.re_v2.protocol_22.provider import (
    NormalizedUsageV1,
    RawExecutionResultV1,
    RawExecutionTimingV1,
    canonical_normalized_usage_bytes,
)
from harness.re_v2.protocol_22.recovery import (
    Protocol22RunContext,
    recover_protocol_22_run,
)
from harness.re_v2.protocol_22.response_schemas import (
    canonical_response_schema_bytes,
)
from harness.re_v2.protocol_22.schema import load_canonical_object
from tests.unit.test_re_v2_protocol_22_certification import (
    _candidate,
    _valid_domain_candidate,
    _valid_source_candidate,
)
from tests.unit.test_re_v2_protocol_22_graph import _fixture
from tests.unit.test_re_v2_protocol_22_inputs import _input_fixture
from tests.unit.test_re_v2_protocol_22_provider import _tokenizer
from tests.unit.test_re_v2_protocol_22_execution import (
    CLI_AGENT_BYTES,
    _provider_dependencies,
)
from tests.unit.test_re_v2_protocol_22_recovery import (
    NOW,
    _Inspector,
    _registry_from_inputs,
    interrupted_dispatch,
)
from harness.re_v2.recovery import ProcessState


@pytest.mark.unit
def test_controller_rejects_a_non_protocol_22_context(tmp_path: Path) -> None:
    fixture = interrupted_dispatch(
        tmp_path,
        started=False,
        staging=False,
        committed=False,
    )

    with pytest.raises(TypeError, match="Protocol22RunContext"):
        Protocol22Controller(object())

    controller = Protocol22Controller(fixture.context)
    assert isinstance(controller, Protocol22Controller)


@pytest.mark.unit
def test_controller_returns_pinned_authority_unavailable_without_execution(
    tmp_path: Path,
) -> None:
    fixture = interrupted_dispatch(
        tmp_path,
        started=False,
        staging=False,
        committed=False,
    )
    registry = replace(
        fixture.exact_registry,
        executor_implementations={"wrong": "sha256:" + "0" * 64},
    )
    context = replace(fixture.context, installed_authorities=registry)

    result = Protocol22Controller(context).run_until_stopped()

    assert isinstance(result, Protocol22ControllerResult)
    assert result.status == "pinned_authority_unavailable"
    assert fixture.provider.calls == 0


@dataclass(frozen=True)
class _SnapshotReader:
    partition: object
    payloads: Mapping[tuple[str, str], bytes]

    def read_file(
        self,
        source_id: str,
        source_relative_path: str,
        expected: object,
    ) -> bytes:
        payload = self.payloads[(source_id, source_relative_path)]
        assert content_digest(payload) == expected.content_hash
        return payload


@dataclass(frozen=True)
class _DeterministicRuntime:
    inputs: object
    snapshot: _SnapshotReader

    def produce(
        self,
        item: WorkItemV2,
        dependencies: AcceptedDependencySetV2,
    ) -> bytes:
        kind = item.output_key.artifact_kind
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
        raise AssertionError(f"unexpected inventory goal artifact: {kind}")

    def certify_deterministic(
        self,
        item: WorkItemV2,
        payload: bytes,
        dependencies: AcceptedDependencySetV2,
    ) -> CertificationReceiptV2:
        kind = item.output_key.artifact_kind
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
            policy_valid = payload == expected
            diagnostic_values: set[str] = set()
            if not canonical_valid:
                diagnostic_values.add("canonical_schema_invalid")
            if not policy_valid:
                diagnostic_values.add("context_reconstruction_mismatch")
            diagnostics = tuple(sorted(diagnostic_values))
            assessment = DeterministicAssessmentInputV2(
                canonical_schema_valid=canonical_valid,
                dependency_closure_valid=True,
                policy_conformance_valid=policy_valid,
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
        executor = self.inputs.executor_contract.entry_for(item.producer_family)
        return certify_deterministic_artifact(
            item,
            content_digest(payload),
            assessment,
            executor.verifier,
        )

    def certify_candidate(
        self,
        candidate: CompactCandidateInputV1,
        item: WorkItemV2,
        context: ContextBundleV1,
    ) -> CompactCertificationResultV2:
        executor = self.inputs.executor_contract.entry_for(item.producer_family)
        return certify_compact_candidate(
            candidate,
            item,
            context,
            self.snapshot,
            executor.verifier,
        )


def _dependency_role(kind: str) -> str:
    return {
        "source-inventory": "source_inventory",
        "source-partition": "source_partition",
        "domain-inventory": "domain_inventory",
    }[kind]


def _inventory_context(
    tmp_path: Path,
    *,
    active_ms_limit: int | None = None,
) -> Protocol22RunContext:
    raw_manifest, raw_inputs = _fixture({"api": ("src",)}, goal="inventory")
    budget = raw_manifest.initial_budget_policy
    if active_ms_limit is not None:
        budget = replace(budget, active_ms_limit=active_ms_limit)
    manifest = replace(
        raw_manifest,
        run_id=f"re-controller-{tmp_path.name}",
        initial_budget_policy=budget,
    )
    input_set = Protocol22InputSet(
        workspace_partition=raw_inputs.workspace_partition,
        artifact_policy=raw_inputs.artifact_policy,
        executor_contract=raw_inputs.executor_contract,
        immutable_objects={},
    )
    paths = create_protocol_22_run_store(
        tmp_path / manifest.run_id, manifest, input_set
    )
    inputs = load_protocol_22_inputs(paths, manifest)
    graph = build_protocol_22_graph(manifest, inputs)
    objects = ObjectStore(paths.objects)
    ledger = Protocol22Ledger(paths, objects)
    registry = _registry_from_inputs(inputs)
    workspace_bytes = canonical_json_bytes(inputs.workspace_partition.to_json_dict())
    workspace_hash = content_digest(workspace_bytes)
    by_template = {template.template_id: template for template in graph.templates}

    def accepted_dependencies(item: WorkItemV2) -> AcceptedDependencySetV2:
        view = ledger.replay()
        required_template_ids = by_template[item.template_id].required_template_ids
        accepted_by_template: dict[str, AcceptedArtifactV2] = {}
        by_role: dict[str, AcceptedArtifactV2] = {}
        payloads: dict[str, bytes] = {}
        for template_id in required_template_ids:
            dependency_item = next(
                value
                for value in view.certification_work_items.values()
                if value.template_id == template_id
            )
            accepted = view.artifact_for_key(dependency_item.output_key.identity)
            assert accepted is not None
            accepted_by_template[template_id] = accepted
            role = _dependency_role(by_template[template_id].artifact_kind)
            by_role[role] = accepted
            payloads[accepted.artifact_hash] = objects.read_blob(accepted.artifact_hash)
        assert set(accepted_by_template) == set(required_template_ids)
        return AcceptedDependencySetV2(by_role, payloads)

    def dependencies_for(
        item: WorkItemV2,
        _attempt_kind: str,
    ) -> DeterministicExecutionDependenciesV1:
        if not by_template[item.template_id].required_template_ids:
            invocation_inputs = (
                DeterministicInvocationInputV1(
                    role="workspace_partition",
                    object_hash=workspace_hash,
                ),
            )
            referenced = {workspace_hash: workspace_bytes}
            partition_hash: str | None = workspace_hash
        else:
            dependencies = accepted_dependencies(item)
            invocation_inputs = tuple(
                DeterministicInvocationInputV1(
                    role=role,
                    object_hash=accepted.artifact_hash,
                )
                for role, accepted in dependencies.by_role.items()
            )
            referenced = dict(dependencies.payloads_by_hash)
            partition_hash = None
        invocation = DeterministicInvocationV1(
            schema_version=1,
            producer_family=item.producer_family,
            output_key=item.output_key,
            artifact_policy_hash=item.output_key.layer_policy_hash,
            inputs=invocation_inputs,
        )
        return DeterministicExecutionDependenciesV1(
            executor=inputs.executor_contract.entry_for(item.producer_family),
            registry=registry,
            invocation=invocation,
            workspace_partition_hash=partition_hash,
            referenced_objects=referenced,
        )

    payloads = {
        (source.source_id, record.source_relative_path): (
            f"{source.source_id}:src\n".encode()
        )
        for source in inputs.workspace_partition.sources
        for record in source.files
    }
    runtime = _DeterministicRuntime(
        inputs,
        _SnapshotReader(inputs.workspace_partition, payloads),
    )
    verifier_id = inputs.executor_contract.entries[0].verifier.verifier_id
    return Protocol22RunContext(
        paths=paths,
        inputs=inputs,
        graph=graph,
        event_store=EventStore(paths, protocol=PROTOCOL_22_EVENTS),
        object_store=objects,
        ledger=ledger,
        execution_store=Protocol22ExecutionStore(paths, objects),
        installed_authorities=registry,
        dependencies_for=dependencies_for,
        executors=MappingProxyType({}),
        producers=MappingProxyType(
            {
                "evidence-pack": runtime,
                "inventory": runtime,
                "partition": runtime,
            }
        ),
        verifiers=MappingProxyType({verifier_id: runtime}),
        clock=lambda: NOW,
    )


@pytest.mark.unit
def test_deterministic_inventory_graph_commits_certifies_and_accepts_in_order(
    tmp_path: Path,
) -> None:
    context = _inventory_context(tmp_path)

    result = Protocol22Controller(context).run_until_stopped()

    assert result.status == "completed"
    assert result.ledger is not None
    assert len(result.ledger.accepted_artifacts) == len(context.graph.templates)
    assert all(
        event.type not in {"candidate_persisted", "candidate_certified"}
        for event in result.events
    )
    for started in (
        event for event in result.events if event.type == "dispatch_started"
    ):
        dispatch_id = started.payload["dispatch_id"]
        ordered = [
            event.type
            for event in result.events
            if event.payload.get("dispatch_id") == dispatch_id
            or event.payload.get("work_item_id") == started.payload["work_item_id"]
        ]
        assert ordered.index("dispatch_started") < ordered.index("dispatch_observed")
        assert ordered.index("dispatch_observed") < ordered.index("artifact_accepted")


@pytest.mark.unit
def test_dispatch_started_hook_runs_immediately_after_durable_start(
    tmp_path: Path,
) -> None:
    context = _inventory_context(tmp_path)
    observed: list[tuple[str, str]] = []

    def hook(item: WorkItemV2, prepared: object) -> None:
        events = context.event_store.replay()
        assert events[-1].type == "dispatch_started"
        assert events[-1].payload["work_item_id"] == item.work_item_id
        observed.append((item.work_item_id, getattr(prepared, "dispatch_id")))

    context = replace(context, dispatch_started_hook=hook)

    result = Protocol22Controller(context).run_until_stopped()

    assert result.status == "completed"
    assert len(observed) == len(context.graph.templates)
    assert len({dispatch_id for _work_id, dispatch_id in observed}) == len(observed)


@dataclass
class _ScriptedProvider:
    malformed_result: bool = False
    scripts: Mapping[str, list[str]] | None = None
    calls: int = 0
    calls_by_kind: dict[str, int] = field(default_factory=dict)
    envelopes: list[object] = field(default_factory=list)

    def execute(self, _execution_input: object, *args: object) -> RawExecutionResultV1:
        self.calls += 1
        if len(args) == 4:
            envelope, reservation, candidate_root, _deadline = args
            self.envelopes.append(envelope)
            kind = envelope.target_artifact_kind
            context_bytes = envelope.messages[1].content_utf8.encode("utf-8")
            cli_mode = False
        elif len(args) == 6:
            _agent, context_bytes, _schema, reservation, candidate_root, _deadline = args
            self.envelopes.append(None)
            context_value = load_canonical_object(
                context_bytes,
                ContextBundleV1.from_json_dict,
            )
            kind = context_value.target_artifact_kind
            cli_mode = True
        else:  # pragma: no cover - controller signature contract
            raise AssertionError(f"unexpected provider arguments: {len(args)}")
        self.calls_by_kind[kind] = self.calls_by_kind.get(kind, 0) + 1
        context = load_canonical_object(
            context_bytes,
            ContextBundleV1.from_json_dict,
        )
        configured = None
        if self.scripts is not None:
            keys = (
                f"{kind}:{context.scope.source_id}:{context.scope.domain_key}",
                f"{kind}:{context.scope.source_id}",
                kind,
            )
            configured = next(
                (self.scripts[key] for key in keys if self.scripts.get(key)),
                None,
            )
        mode = (
            configured.pop(0)
            if configured
            else "malformed_valid_candidate"
            if self.malformed_result
            else "valid"
        )
        if mode == "invalid_candidate":
            raw = {}
        elif mode == "minimum_utility":
            raw = _candidate(context.target_artifact_kind)
        else:
            raw = (
                _valid_domain_candidate(context)
                if context.target_artifact_kind == "domain-baseline"
                else _valid_source_candidate(context)
            )
        if mode != "missing_result":
            (candidate_root / "baseline.json").write_bytes(canonical_json_bytes(raw))
        invalid_result = mode in {"missing_result", "malformed_valid_candidate"}
        stdout = (
            b"malformed\n"
            if invalid_result
            else b"echelon_result:\n  schema_version: 1\n  outcome: candidate_ready\n"
        )
        usage = (
            canonical_normalized_usage_bytes(
                NormalizedUsageV1(
                    "trusted_exact",
                    15,
                    {
                        "cached_input_tokens": 2,
                        "input_tokens": 8,
                        "reasoning_output_tokens": 1,
                        "visible_output_tokens": 4,
                    },
                )
            )
            if cli_mode
            else None
        )
        if mode == "usage_overflow":
            total = reservation.billable_tokens + 1
            usage = (
                canonical_json_bytes(
                    {
                        "billable_tokens": total,
                        "classes": {},
                        "status": "untrusted",
                    }
                )
                if cli_mode
                else canonical_json_bytes(
                    {
                        "completion_tokens": 0,
                        "completion_tokens_details": {"reasoning_tokens": 0},
                        "prompt_tokens": total,
                        "prompt_tokens_details": {"cached_tokens": 0},
                        "total_tokens": total,
                    }
                )
            )
        return RawExecutionResultV1(
            stdout=stdout,
            stderr=b"",
            provider_usage=usage,
            timing=RawExecutionTimingV1(NOW, NOW, 0),
            outcome=("invalid_response" if invalid_result else "candidate_ready"),
            provider_name="codex" if cli_mode else None,
            resolved_model_revision="gpt-5.6-codex" if cli_mode else None,
        )


def _accepted_for_item(
    context: Protocol22RunContext,
    item: WorkItemV2,
) -> AcceptedDependencySetV2:
    return accepted_dependencies_for(context, item)


def _baseline_context(
    tmp_path: Path,
    *,
    malformed_result: bool = False,
    scripts: Mapping[str, list[str]] | None = None,
    tokenizer_override: object | None = None,
    source_domains: Mapping[str, tuple[str, ...]] | None = None,
    active_ms_limit: int | None = None,
    token_limit: int | None = None,
    provider_mode: str = "api",
    engine_protocol_version: str = "2.2",
) -> tuple[Protocol22RunContext, _ScriptedProvider]:
    if source_domains is None:
        input_set, raw_manifest = _input_fixture()
    else:
        raw_manifest, validated = _fixture(source_domains, goal="baseline")
        agent = b"agent contract"
        domain_schema = canonical_response_schema_bytes("domain-baseline")
        source_schema = canonical_response_schema_bytes("source-overview")
        input_set = Protocol22InputSet(
            workspace_partition=validated.workspace_partition,
            artifact_policy=validated.artifact_policy,
            executor_contract=validated.executor_contract,
            immutable_objects={
                content_digest(agent): agent,
                content_digest(domain_schema): domain_schema,
                content_digest(source_schema): source_schema,
            },
        )
    if provider_mode == "cli":
        _item, cli_dependencies = _provider_dependencies("cli")
        cli_entry = cli_dependencies.executor
        entries = tuple(
            cli_entry if entry.producer_family == "compact-baseline" else entry
            for entry in input_set.executor_contract.entries
        )
        executor_catalog = replace(input_set.executor_contract, entries=entries)
        immutable_objects = {
            reference.schema_hash: canonical_response_schema_bytes(
                reference.artifact_kind
            )
            for reference in cli_entry.request_renderer.response_schemas
        }
        immutable_objects[content_digest(CLI_AGENT_BYTES)] = CLI_AGENT_BYTES
        input_set = replace(
            input_set,
            executor_contract=executor_catalog,
            immutable_objects=immutable_objects,
        )
        raw_manifest = replace(
            raw_manifest,
            executor_contract_catalog=replace(
                raw_manifest.executor_contract_catalog,
                object_hash=content_digest(
                    canonical_json_bytes(executor_catalog.to_json_dict())
                ),
            ),
        )
    budget = raw_manifest.initial_budget_policy
    if active_ms_limit is not None:
        budget = replace(budget, active_ms_limit=active_ms_limit)
    if token_limit is not None:
        budget = replace(budget, token_limit=token_limit)
    manifest = replace(
        raw_manifest,
        run_id=f"re-baseline-controller-{tmp_path.name}",
        initial_budget_policy=budget,
        engine_protocol_version=engine_protocol_version,
    )
    paths = create_protocol_22_run_store(
        tmp_path / manifest.run_id, manifest, input_set
    )
    inputs = load_protocol_22_inputs(paths, manifest)
    graph = build_protocol_22_graph(manifest, inputs)
    objects = ObjectStore(paths.objects)
    ledger = Protocol22Ledger(paths, objects)
    registry = _registry_from_inputs(inputs)
    workspace_bytes = canonical_json_bytes(inputs.workspace_partition.to_json_dict())
    workspace_hash = content_digest(workspace_bytes)
    context_ref: dict[str, Protocol22RunContext] = {}

    def dependencies_for(
        item: WorkItemV2,
        _attempt_kind: str,
    ) -> DeterministicExecutionDependenciesV1 | ProviderExecutionDependenciesV1:
        executor = inputs.executor_contract.entry_for(item.producer_family)
        if executor.execution_mode in {"api", "cli"}:
            accepted = _accepted_for_item(context_ref["context"], item)
            context_bytes = accepted.payload_for_role("context_bundle")
            renderer = executor.request_renderer
            assert renderer is not None
            return ProviderExecutionDependenciesV1(
                executor=executor,
                registry=registry,
                agent_bytes=objects.read_blob(renderer.agent_contract_hash),
                context_bytes=context_bytes,
                response_schema_bytes=canonical_response_schema_bytes(
                    item.output_key.artifact_kind
                ),
                tokenizer=(
                    None
                    if executor.execution_mode == "cli"
                    else tokenizer_override
                    if tokenizer_override is not None
                    else _tokenizer(executor, 100)
                ),
            )
        accepted = _accepted_for_item(context_ref["context"], item)
        if set(accepted.by_role) == {"workspace_partition"}:
            invocation_inputs = (
                DeterministicInvocationInputV1(
                    role="workspace_partition",
                    object_hash=workspace_hash,
                ),
            )
            referenced = {workspace_hash: workspace_bytes}
            partition_hash: str | None = workspace_hash
        else:
            invocation_inputs = tuple(
                DeterministicInvocationInputV1(
                    role=role,
                    object_hash=value.artifact_hash,
                )
                for role, value in accepted.by_role.items()
            )
            referenced = dict(accepted.payloads_by_hash)
            partition_hash = None
        return DeterministicExecutionDependenciesV1(
            executor=executor,
            registry=registry,
            invocation=DeterministicInvocationV1(
                schema_version=1,
                producer_family=item.producer_family,
                output_key=item.output_key,
                artifact_policy_hash=item.output_key.layer_policy_hash,
                inputs=invocation_inputs,
            ),
            workspace_partition_hash=partition_hash,
            referenced_objects=referenced,
        )

    snapshot_payloads: dict[tuple[str, str], bytes] = {}
    for source in inputs.workspace_partition.sources:
        for record in source.files:
            if source_domains is None:
                payload = b"print('ok')\n"
            else:
                domain = next(
                    domain
                    for domain in source.domains
                    if record.source_relative_path.startswith(
                        f"{domain.source_relative_root}/"
                    )
                )
                payload = f"{source.source_id}:{domain.source_relative_root}\n".encode()
            snapshot_payloads[(source.source_id, record.source_relative_path)] = payload
    runtime = _DeterministicRuntime(
        inputs,
        _SnapshotReader(inputs.workspace_partition, snapshot_payloads),
    )
    provider = _ScriptedProvider(
        malformed_result=malformed_result,
        scripts=scripts,
    )
    provider_entry = inputs.executor_contract.entry_for("compact-baseline")
    producer_registrations = {
        entry.producer_family: runtime
        for entry in inputs.executor_contract.entries
        if entry.execution_mode == "in_process"
    }
    context = Protocol22RunContext(
        paths=paths,
        inputs=inputs,
        graph=graph,
        event_store=EventStore(paths, protocol=PROTOCOL_22_EVENTS),
        object_store=objects,
        ledger=ledger,
        execution_store=Protocol22ExecutionStore(paths, objects),
        installed_authorities=registry,
        dependencies_for=dependencies_for,
        executors=MappingProxyType({provider_entry.adapter_id: provider}),
        producers=MappingProxyType(producer_registrations),
        verifiers=MappingProxyType({provider_entry.verifier.verifier_id: runtime}),
        clock=lambda: NOW,
    )
    context_ref["context"] = context
    return context, provider


@pytest.mark.unit
@pytest.mark.parametrize("provider_mode", ("api", "cli"))
@pytest.mark.parametrize("malformed_result", (False, True))
def test_provider_candidates_are_durable_certified_and_reconstructed_without_retry(
    tmp_path: Path,
    malformed_result: bool,
    provider_mode: str,
) -> None:
    context, provider = _baseline_context(
        tmp_path,
        malformed_result=malformed_result,
        provider_mode=provider_mode,
    )

    result = Protocol22Controller(context).run_until_stopped()

    assert result.status == "completed"
    provider_items = [
        item
        for item in context.graph.templates
        if item.artifact_kind in {"domain-baseline", "source-overview"}
    ]
    assert provider.calls == len(provider_items)
    assert [event.type for event in result.events].count("candidate_persisted") == len(
        provider_items
    )
    assert [event.type for event in result.events].count("candidate_certified") == len(
        provider_items
    )
    captures = [
        context.execution_store.capture_state(event.payload["dispatch_id"])
        for event in result.events
        if event.type == "dispatch_started"
    ]
    provider_captures = [
        state.closure.capture
        for state in captures
        if hasattr(state, "closure")
        and state.closure.capture.execution_mode in {"api", "cli"}
    ]
    assert provider_captures
    assert {capture.execution_mode for capture in provider_captures} == {
        provider_mode
    }
    if provider_mode == "cli":
        provider_dispatches = {
            event.payload["dispatch_id"]
            for event in result.events
            if event.type == "dispatch_started"
            and event.payload["billable_token_reservation"] > 0
        }
        observations = [
            event
            for event in result.events
            if event.type == "dispatch_observed"
            and event.payload["dispatch_id"] in provider_dispatches
        ]
        assert observations
        assert {
            (event.payload["token_usage_status"], event.payload["reported_token_usage"])
            for event in observations
        } == {("trusted_exact", 15)}
    assert [event.type for event in result.events].count(
        "result_contract_reconstructed"
    ) == (len(provider_items) if malformed_result else 0)
    assert all(
        event.payload.get("attempt_kind") == "initial_generation"
        for event in result.events
        if event.type == "dispatch_started"
        and event.payload["billable_token_reservation"] > 0
    )


@pytest.mark.unit
def test_candidate_workspace_symlink_is_rejected_before_provider_dispatch(
    tmp_path: Path,
) -> None:
    context, provider = _baseline_context(tmp_path)
    outside = tmp_path / "outside-candidate-work"
    outside.mkdir()
    (context.paths.root / "candidate-work").symlink_to(
        outside,
        target_is_directory=True,
    )

    with pytest.raises(Protocol22ControllerError, match="candidate-work"):
        Protocol22Controller(context).run_until_stopped()

    assert provider.calls == 0
    assert tuple(outside.iterdir()) == ()
    assert not any(
        event.type == "dispatch_started"
        and event.payload["billable_token_reservation"] > 0
        for event in context.event_store.replay()
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("first_mode", "retry_kind"),
    (
        ("missing_result", "result_contract_retry"),
        ("invalid_candidate", "artifact_contract_retry"),
    ),
)
def test_provider_uses_only_the_classified_shared_retry_and_preserves_context(
    tmp_path: Path,
    first_mode: str,
    retry_kind: str,
) -> None:
    context, provider = _baseline_context(
        tmp_path,
        scripts={"domain-baseline": [first_mode, "valid"]},
    )

    result = Protocol22Controller(context).run_until_stopped()

    assert result.status == "completed"
    assert provider.calls_by_kind["domain-baseline"] == 2
    domain_starts = [
        event
        for event in result.events
        if event.type == "dispatch_started"
        and event.payload["billable_token_reservation"] > 0
        and event.payload["work_item_id"]
        == next(
            item.work_item_id
            for item in result.ledger.certification_work_items.values()
            if item.output_key.artifact_kind == "domain-baseline"
        )
    ]
    assert [event.payload["attempt_kind"] for event in domain_starts] == [
        "initial_generation",
        retry_kind,
    ]
    assert provider.envelopes[0].messages[1] == provider.envelopes[1].messages[1]
    assert len(provider.envelopes[0].messages) == 2
    assert len(provider.envelopes[1].messages) == 3
    retry_diagnostics = json.loads(provider.envelopes[1].messages[2].content_utf8)
    assert retry_diagnostics == {
        "diagnostics": [
            "result_unrecoverable"
            if retry_kind == "result_contract_retry"
            else "authorial_schema_invalid"
        ],
        "schema_version": 1,
    }
    retry_kinds = {
        event.payload["attempt_kind"]
        for event in result.events
        if event.type == "dispatch_started"
        and event.payload["attempt_kind"] != "initial_generation"
    }
    assert retry_kinds == {retry_kind}


@pytest.mark.unit
@pytest.mark.parametrize(
    ("mode", "failure_class", "reason_code"),
    (
        ("invalid_candidate", "artifact_contract", "authorial_schema_invalid"),
        ("minimum_utility", "minimum_utility", "minimum_utility_not_met"),
        ("missing_result", "result_contract", "result_unrecoverable"),
    ),
)
def test_second_provider_failure_is_terminal_but_keeps_independent_acceptance(
    tmp_path: Path,
    mode: str,
    failure_class: str,
    reason_code: str,
) -> None:
    context, provider = _baseline_context(
        tmp_path,
        scripts={"domain-baseline": [mode, mode]},
    )

    result = Protocol22Controller(context).run_until_stopped()

    assert result.status == "failed"
    assert provider.calls_by_kind["domain-baseline"] == 2
    assert provider.calls <= 2
    assert result.ledger is not None
    failure = next(iter(result.ledger.work_item_failures.values()))
    assert (failure.failure_class, failure.reason_code) == (
        failure_class,
        reason_code,
    )
    if failure_class == "result_contract":
        assert failure.candidate_id is not None
        assert failure.candidate_assessment_id is None
    assert result.ledger.accepted_artifacts
    assert result.events[-1].type == "run_failed"
    assert [event.type for event in result.events].count("run_failed") == 1
    calls = provider.calls
    event_hashes = tuple(event.event_hash for event in result.events)

    replayed = Protocol22Controller(context).run_until_stopped()

    assert replayed.status == "failed"
    assert provider.calls == calls
    assert tuple(event.event_hash for event in replayed.events) == event_hashes


@pytest.mark.unit
def test_usage_overflow_fails_only_the_exact_executor_contract(
    tmp_path: Path,
) -> None:
    context, provider = _baseline_context(
        tmp_path,
        scripts={"domain-baseline": ["usage_overflow"]},
    )

    result = Protocol22Controller(context).run_until_stopped()

    assert result.status == "failed"
    assert provider.calls == 1
    assert result.ledger is not None
    failure = next(iter(result.ledger.executor_failures.values()))
    assert failure.reason_code == "usage_exceeded_reservation"
    assert failure.candidate_id is not None
    assert all(
        receipt.certification_receipt_id
        not in {
            assessment.certification_receipt_id
            for assessment in result.ledger.candidate_assessments.values()
            if assessment.candidate_id == failure.candidate_id
        }
        for receipt in result.ledger.accepted_artifacts.values()
    )
    assert result.ledger.accepted_artifacts


@pytest.mark.unit
def test_shared_executor_breach_blocks_all_matching_provider_work_without_calls(
    tmp_path: Path,
) -> None:
    context, provider = _baseline_context(
        tmp_path,
        source_domains={"api": ("orders",), "web": ("ui",)},
        scripts={"domain-baseline:api": ["usage_overflow"]},
    )

    result = Protocol22Controller(context).run_until_stopped()

    assert result.status == "failed"
    assert provider.calls == 1
    assert provider.calls_by_kind == {"domain-baseline": 1}
    assert result.ledger is not None
    assert len(result.ledger.executor_failures) == 1
    failure = next(iter(result.ledger.executor_failures.values()))
    matching_provider_items = [
        item
        for item in result.ledger.certification_work_items.values()
        if item.executor_contract_hash == failure.executor_contract_hash
    ]
    assert matching_provider_items == []
    accepted_kinds = {
        result.ledger.certification_work_items[
            receipt.certification_receipt_id
        ].output_key.artifact_kind
        for receipt in result.ledger.accepted_artifacts.values()
    }
    assert "domain-context-bundle" in accepted_kinds
    assert not accepted_kinds.intersection(
        {"domain-baseline", "source-overview", "source-baseline-root"}
    )


@pytest.mark.unit
@pytest.mark.parametrize("provider_mode", ("api", "cli"))
def test_abandoned_provider_dispatch_gets_one_counted_result_retry(
    tmp_path: Path,
    provider_mode: str,
) -> None:
    context, provider = _baseline_context(tmp_path, provider_mode=provider_mode)

    def crash_after_provider_start(boundary: str) -> None:
        if not boundary.startswith("dispatch_started:"):
            return
        started = context.event_store.replay()[-1]
        if started.payload["billable_token_reservation"] > 0:
            raise RuntimeError("simulated provider owner death")

    with pytest.raises(RuntimeError, match="owner death"):
        Protocol22Controller(context, crash_after_provider_start).run_until_stopped()
    dead_context = replace(
        context,
        process_inspector=_Inspector(ProcessState.DEAD),
    )
    started = next(
        event
        for event in context.event_store.replay()
        if event.type == "dispatch_started"
        and event.payload["billable_token_reservation"] > 0
    )

    recovered = recover_protocol_22_run(dead_context)

    assert recovered.dispatch_actions[started.payload["dispatch_id"]] == "abandon"
    assert recovered.budget is not None
    assert recovered.budget.charged_tokens == started.payload[
        "billable_token_reservation"
    ]
    assert provider.calls == 0

    result = Protocol22Controller(dead_context).run_until_stopped()

    assert result.status == "completed"
    assert provider.calls_by_kind["domain-baseline"] == 1
    assert [event.type for event in result.events].count("dispatch_abandoned") == 1
    assert any(
        event.type == "dispatch_started"
        and event.payload["attempt_kind"] == "result_contract_retry"
        for event in result.events
    )


@pytest.mark.unit
def test_abandoned_deterministic_dispatch_becomes_terminal_item_failure(
    tmp_path: Path,
) -> None:
    context = _inventory_context(tmp_path)

    def crash_after_start(boundary: str) -> None:
        if boundary.startswith("dispatch_started:"):
            raise RuntimeError("simulated deterministic owner death")

    with pytest.raises(RuntimeError, match="owner death"):
        Protocol22Controller(context, crash_after_start).run_until_stopped()
    dead_context = replace(
        context,
        process_inspector=_Inspector(ProcessState.DEAD),
    )

    result = Protocol22Controller(dead_context).run_until_stopped()

    assert result.status == "failed"
    assert result.ledger is not None
    failure = next(iter(result.ledger.work_item_failures.values()))
    assert failure.failure_class == "execution_indeterminate"
    assert failure.reason_code == "execution_outcome_indeterminate"
    assert failure.execution_capture_hash is None
    assert failure.dispatch_abandonment_event_hash is not None


@pytest.mark.unit
def test_exact_next_reservation_pauses_before_start_and_resumes_after_authorization(
    tmp_path: Path,
) -> None:
    context = _inventory_context(tmp_path, active_ms_limit=1)

    paused = Protocol22Controller(context).run_until_stopped()

    assert paused.status == "paused"
    assert paused.events[-1].type == "run_paused"
    assert all(event.type != "dispatch_started" for event in paused.events)
    context.event_store.append(
        "budget_authorized",
        {
            "authorized_by": "test-operator",
            "dimension": "active_ms",
            "new_value": 2_000_000,
            "old_value": 1,
            "reason": "complete the bounded inventory graph",
        },
        occurred_at=NOW,
    )
    context.event_store.append(
        "run_resumed",
        {"reason": "higher active-time authorization is durable"},
        occurred_at=NOW,
    )

    completed = Protocol22Controller(context).run_until_stopped()

    assert completed.status == "completed"
    assert completed.events[-1].type == "run_completed"


@dataclass(frozen=True)
class _BrokenDeterministicRuntime:
    delegate: _DeterministicRuntime
    mode: str

    def produce(
        self,
        item: WorkItemV2,
        dependencies: AcceptedDependencySetV2,
    ) -> bytes:
        if self.mode == "exception":
            raise RuntimeError("deterministic fixture failure")
        return b"{}\n"

    def certify_deterministic(
        self,
        item: WorkItemV2,
        payload: bytes,
        dependencies: AcceptedDependencySetV2,
    ) -> CertificationReceiptV2:
        return self.delegate.certify_deterministic(item, payload, dependencies)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("mode", "reason_code"),
    (
        ("exception", "deterministic_execution_failed"),
        ("invalid", "deterministic_artifact_invalid"),
    ),
)
def test_deterministic_executor_breach_preserves_independent_siblings(
    tmp_path: Path,
    mode: str,
    reason_code: str,
) -> None:
    context = _inventory_context(tmp_path)
    delegate = context.producers["partition"]
    broken = _BrokenDeterministicRuntime(delegate, mode)
    producers = dict(context.producers)
    producers["partition"] = broken
    broken_context = replace(
        context,
        producers=MappingProxyType(producers),
    )

    result = Protocol22Controller(broken_context).run_until_stopped()

    assert result.status == "failed"
    assert result.ledger is not None
    failure = next(iter(result.ledger.executor_failures.values()))
    assert failure.reason_code == reason_code
    assert result.ledger.accepted_artifacts
    accepted_kinds = {
        result.ledger.certification_work_items[
            receipt.certification_receipt_id
        ].output_key.artifact_kind
        for receipt in result.ledger.accepted_artifacts.values()
    }
    assert "domain-inventory" in accepted_kinds


@dataclass
class _FlakyTokenizer:
    tokenizer_id: str
    tokenizer_version: str
    implementation_digest: str
    calls: int = 0

    def count_tokens(self, _payload: bytes) -> int:
        self.calls += 1
        return 100 + self.calls


@pytest.mark.unit
def test_pre_dispatch_reservation_mismatch_fails_executor_without_provider_call(
    tmp_path: Path,
) -> None:
    input_set, _manifest = _input_fixture()
    provider_entry = input_set.executor_contract.entry_for("compact-baseline")
    authority = provider_entry.request_tokenizer
    assert authority is not None
    tokenizer = _FlakyTokenizer(
        authority.tokenizer_id,
        authority.tokenizer_version,
        authority.implementation_digest,
    )
    context, provider = _baseline_context(
        tmp_path,
        tokenizer_override=tokenizer,
    )

    result = Protocol22Controller(context).run_until_stopped()

    assert result.status == "failed"
    assert provider.calls == 0
    assert result.ledger is not None
    failure = next(iter(result.ledger.executor_failures.values()))
    assert failure.reason_code == "reservation_mismatch"
    assert failure.dispatch_id is None
    assert failure.execution_capture_hash is None
    assert result.ledger.accepted_artifacts


@pytest.mark.unit
def test_bad_domain_does_not_discard_independent_source_root(
    tmp_path: Path,
) -> None:
    context, provider = _baseline_context(
        tmp_path,
        source_domains={"api": ("orders",), "web": ("ui",)},
        scripts={
            "domain-baseline:api": [
                "invalid_candidate",
                "invalid_candidate",
            ]
        },
    )

    result = Protocol22Controller(context).run_until_stopped()

    assert result.status == "failed"
    assert result.ledger is not None
    accepted_items = [
        result.ledger.certification_work_items[receipt.certification_receipt_id]
        for receipt in result.ledger.accepted_artifacts.values()
    ]
    roots = [
        item
        for item in accepted_items
        if item.output_key.artifact_kind == "source-baseline-root"
    ]
    assert [item.output_key.scope.source_id for item in roots] == ["web"]
    failure = next(iter(result.ledger.work_item_failures.values()))
    assert failure.failure_class == "artifact_contract"
    assert provider.calls_by_kind["domain-baseline"] == 3
    assert provider.calls_by_kind["source-overview"] == 1
    assert result.events[-1].type == "run_failed"
