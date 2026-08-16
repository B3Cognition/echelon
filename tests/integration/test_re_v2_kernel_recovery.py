"""Integrated crash/restart proof for the pinned RE v2 execution kernel."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pytest

from harness.re_v2.budget import evaluate_budget
from harness.re_v2.candidates import CandidateStore, DispatchLease, ProcessIdentity
from harness.re_v2.canonical import content_digest
from harness.re_v2.controller import ReV2Controller, WorkExecutor
from harness.re_v2.events import EventStore
from harness.re_v2.ledger import (
    CertificationDecision,
    Ledger,
    ObjectStore,
)
from harness.re_v2.model import (
    ArtifactReceipt,
    BudgetPolicy,
    CertificationKey,
    CertificationReceipt,
    ExecutionObservation,
    RunManifest,
    WorkItem,
    WorkTemplate,
)
from harness.re_v2.planner import plan_next, validate_work_graph
from harness.re_v2.publication import (
    GenerationManifest,
    current_index_hash,
    load_published_v2_index,
    publish_generation,
)
from harness.re_v2.recovery import ProcessState, ReV2RunContext
from harness.re_v2.run_store import ReV2Paths, create_run_store
from harness.re_v2.snapshot import CapturedSnapshot, capture_source_snapshot


NOW = "2026-08-14T12:00:00Z"
PROVIDER_CONTRACT = {"provider": "fixture-provider"}
PROVIDER_CONTRACT_HASH = content_digest(PROVIDER_CONTRACT)
POLICY_VERSION = "egr-164-integration-v1"
SYNTHESIS_POLICY_HASH = content_digest(b"egr-164-integration-synthesis-v1")

FAULT_POINTS = (
    "snapshot_created",
    "dispatch_started",
    "provider_terminated",
    "candidate_renamed",
    "certification_written",
    "checkpoint_recorded",
    "generation_promoted",
    "index_replaced",
)

# Snapshot creation precedes the first attempt. Once dispatch_started is durable,
# an interruption before candidate publication is one failed attempt plus exactly
# one replacement. Candidate rename is the durable reuse boundary.
EXPECTED_DISPATCHES = {
    "snapshot_created": 1,
    "dispatch_started": 2,
    "provider_terminated": 2,
    "candidate_renamed": 1,
    "certification_written": 1,
    "checkpoint_recorded": 1,
    "generation_promoted": 1,
    "index_replaced": 1,
}


class InjectedCrash(BaseException):
    """Stand in for abrupt controller death at one durable boundary."""

    def __init__(self, boundary: str) -> None:
        super().__init__(f"injected crash after {boundary}")
        self.boundary = boundary


class FailOnce:
    def __init__(self, boundary: str) -> None:
        self.boundary = boundary
        self.fired = False

    def __call__(self, observed: str) -> None:
        if observed == self.boundary and not self.fired:
            self.fired = True
            raise InjectedCrash(observed)


class DeadInspector:
    def inspect(self, _identity: ProcessIdentity) -> ProcessState:
        return ProcessState.DEAD


class RecordingExecutor(WorkExecutor):
    def __init__(self, output_root: Path) -> None:
        self.output_root = output_root
        self.calls: list[str] = []

    @property
    def provider_name(self) -> str:
        return "fixture-provider"

    @property
    def provider_contract_hash(self) -> str:
        return PROVIDER_CONTRACT_HASH

    def execute(
        self,
        snapshot_root: Path,
        work_item: WorkItem,
        lease: DispatchLease,
    ) -> tuple[Path, ExecutionObservation]:
        assert snapshot_root.is_dir()
        self.calls.append(lease.dispatch_id)
        output = self.output_root / lease.dispatch_id
        output.mkdir(parents=True)
        (output / "artifact.json").write_text(
            f'{{"work_item_id":"{work_item.work_item_id}"}}\n',
            encoding="utf-8",
        )
        return output, ExecutionObservation(
            started_at=NOW,
            ended_at=NOW,
            duration_ms=0,
            exit_code=0,
            timed_out=False,
            output_truncated=False,
            result_contract_valid=True,
            token_usage=1,
            provider_name=self.provider_name,
            model_name="fixture-model",
            stderr_digest=None,
        )


@dataclass
class AcceptingCertifier:
    objects: ObjectStore
    verifier_id: str = "fixture-verifier"
    verifier_version: str = "v1"

    def certify(
        self,
        candidate: object,
        work_item: WorkItem,
    ) -> CertificationDecision:
        candidate_id = str(getattr(candidate, "candidate_id"))
        artifact_hash = self.objects.put_tree(Path(getattr(candidate, "payload_path")))
        certification = CertificationReceipt(
            certification_key=CertificationKey(
                artifact_hash=artifact_hash,
                verifier_id=self.verifier_id,
                verifier_version=self.verifier_version,
                source_snapshot_id=work_item.output_key.source_snapshot_id,
                audit_epoch_id=None,
            ),
            candidate_id=candidate_id,
            work_item_id=work_item.work_item_id,
            verdict="accepted",
            normalized_diagnostics=(),
            evidence_references=("artifact.json",),
            scope_verified=True,
            certified_at=NOW,
        )
        artifact = ArtifactReceipt(
            artifact_key=work_item.output_key,
            artifact_hash=artifact_hash,
            certification_id=certification.identity,
            candidate_id=candidate_id,
            work_item_id=work_item.work_item_id,
            accepted_at=NOW,
        )
        return CertificationDecision(certification, artifact)


@dataclass(frozen=True)
class RecoveredRun:
    certified_work_ids: frozenset[str]
    dispatches_by_work_item: Counter[str]
    certification_count: int
    acceptance_count: int
    checkpoint_count: int
    candidate_count: int
    generation_count: int
    published_generation_id: str
    accepted_root_hashes: frozenset[str]
    published_root_hashes: frozenset[str]

    def dispatch_count(self, work_item_id: str) -> int:
        return self.dispatches_by_work_item[work_item_id]


class FaultHarness:
    """Drive one real kernel item through crash, restart, and publication."""

    def __init__(self, root: Path, *, fail_once_at: str) -> None:
        self.root = root
        self.fail_once_at = fail_once_at
        self.fault = FailOnce(fail_once_at)
        self.source = root / "source"
        self.snapshots = root / "snapshots"
        self.run_dir = root / "runs" / "re-fault-matrix"
        self.workspace = root / "workspace"
        self.outputs = root / "provider-output"
        self.executor = RecordingExecutor(self.outputs)
        self.snapshot: CapturedSnapshot | None = None
        self._graph = None

    @property
    def expected_dispatches(self) -> int:
        return EXPECTED_DISPATCHES[self.fail_once_at]

    @property
    def work_item_id(self) -> str:
        context = self._new_context()
        budget = evaluate_budget(
            context.manifest.initial_budget_policy,
            context.event_store.replay(),
            now=NOW,
        )
        decision = plan_next(
            context.graph,
            context.ledger.replay(),
            budget,
            requested_goals=context.manifest.requested_goals,
        )
        if decision.ready:
            return decision.ready[0].work_item_id
        work_items = context.ledger.replay().certification_work_items.values()
        return next(iter(work_items)).work_item_id

    def start_and_crash(self) -> None:
        try:
            self._ensure_snapshot()
            context = self._new_context()
            self._controller(context).run_until_stopped()
            self._publish(context)
        except InjectedCrash as exc:
            assert exc.boundary == self.fail_once_at
        else:  # pragma: no cover - every matrix row must hit its named seam.
            pytest.fail(f"fault hook {self.fail_once_at!r} did not fire")
        assert self.fault.fired is True

    def restart(self) -> RecoveredRun:
        self._ensure_snapshot()
        context = self._new_context()
        result = self._controller(context).run_until_stopped()
        assert result.status == "complete"
        published = self._publish(context)

        history = context.event_store.replay()
        ledger = context.ledger.replay()
        dispatches = Counter(
            str(event.payload["work_item_id"])
            for event in history
            if event.type == "dispatch_started"
        )
        accepted = {
            receipt.work_item_id
            for certification_id, receipt in ledger.certifications.items()
            if receipt.verdict == "accepted"
            and receipt.scope_verified
            and certification_id in ledger.certification_work_items
        }
        generation_root = self.workspace / "re" / "v2" / "generations"
        generations = tuple(
            path
            for path in generation_root.iterdir()
            if path.is_dir() and not path.name.startswith(".")
        )
        installed = load_published_v2_index(self.workspace)
        assert installed == published
        generation = GenerationManifest.from_bytes(
            (
                generation_root
                / installed.generation_id
                / "manifest.json"
            ).read_bytes()
        )
        accepted_roots = frozenset(
            receipt.artifact_hash
            for receipt in ledger.accepted_artifacts.values()
        )
        return RecoveredRun(
            certified_work_ids=frozenset(accepted),
            dispatches_by_work_item=dispatches,
            certification_count=len(ledger.certifications),
            acceptance_count=sum(
                event.type == "artifact_accepted" for event in history
            ),
            checkpoint_count=sum(
                event.type == "checkpoint_recorded" for event in history
            ),
            candidate_count=len(context.candidate_store.discover()),
            generation_count=len(generations),
            published_generation_id=installed.generation_id,
            accepted_root_hashes=accepted_roots,
            published_root_hashes=frozenset(generation.accepted_root_hashes),
        )

    def _ensure_snapshot(self) -> None:
        if self.snapshot is not None:
            return
        self.source.mkdir()
        self.snapshots.mkdir()
        self.workspace.mkdir()
        self.outputs.mkdir()
        (self.source / "api.py").write_text("VALUE = 1\n", encoding="utf-8")
        self.snapshot = capture_source_snapshot(
            self.source,
            self.snapshots,
            exclusions=(),
        )
        self.fault("snapshot_created")

    def _new_context(self) -> ReV2RunContext:
        assert self.snapshot is not None
        if not self.run_dir.exists():
            manifest = RunManifest(
                schema_version=1,
                engine="re-v2",
                engine_protocol_version="2.0",
                run_id=self.run_dir.name,
                created_at=NOW,
                source_snapshot_id=self.snapshot.snapshot_id,
                source_snapshot_kind=self.snapshot.kind,
                partition_manifest_id=content_digest(b"fault-matrix-partitions"),
                requested_goals=("inventory",),
                initial_budget_policy=BudgetPolicy(
                    token_limit=100,
                    active_ms_limit=60_000,
                    provider_attempt_limit=3,
                    artifact_generation_attempt_limit=3,
                    semantic_repair_round_limit=1,
                    result_contract_retry_limit=2,
                ),
                provider_contract=PROVIDER_CONTRACT,
                artifact_policy_versions={"L0": POLICY_VERSION},
                parent_run_id=None,
            )
            paths = create_run_store(self.run_dir, manifest)
        else:
            paths = ReV2Paths.for_run(self.run_dir)
        if self._graph is None:
            template = WorkTemplate(
                goal_id="inventory",
                artifact_kind="fixture-inventory",
                layer="L0",
                producer_id="fixture-producer",
                producer_protocol_version="v1",
                layer_policy_hash=content_digest(
                    {
                        "artifact_kind": "fixture-inventory",
                        "policy_version": POLICY_VERSION,
                    }
                ),
                required_template_ids=(),
                verifier_id="fixture-verifier",
                verifier_version="v1",
                result_contract_id="fixture-result-v1",
                max_provider_attempts=3,
                max_generation_attempts=3,
                max_semantic_rounds=1,
                max_result_contract_retries=2,
            )
            self._graph = validate_work_graph(
                (template,),
                requested_goals=("inventory",),
                source_snapshot_id=self.snapshot.snapshot_id,
                partition_manifest_id=content_digest(b"fault-matrix-partitions"),
            )
        objects = ObjectStore(paths.objects)
        return ReV2RunContext(
            paths=paths,
            snapshot=self.snapshot,
            graph=self._graph,
            event_store=EventStore(paths),
            object_store=objects,
            ledger=Ledger(
                paths,
                objects,
                supported_verifiers={"fixture-verifier": "v1"},
            ),
            candidate_store=CandidateStore(
                paths,
                process_probe=lambda pid: f"fixture-process:{pid}",
                clock=lambda: NOW,
            ),
            certifier=AcceptingCertifier(objects),
        )

    def _controller(self, context: ReV2RunContext) -> ReV2Controller:
        return ReV2Controller(
            context,
            executor=self.executor,
            process_inspector=DeadInspector(),
            process_identity_factory=lambda item, kind, index, started: ProcessIdentity(
                pid=4_000 + index,
                process_start_identity=f"fixture-process:{4_000 + index}",
                command_hash=content_digest(
                    f"{item.work_item_id}:{kind}:{index}".encode()
                ),
                provider_identity=content_digest(b"fixture-provider"),
                started_at=started,
            ),
            clock=lambda: NOW,
            fault_hook=self.fault,
        )

    def _publish(self, context: ReV2RunContext):
        roots = tuple(
            receipt.artifact_hash
            for receipt in context.ledger.replay().accepted_artifacts.values()
        )
        return publish_generation(
            self.workspace,
            self.run_dir.name,
            roots,
            SYNTHESIS_POLICY_HASH,
            expected_index_hash=current_index_hash(self.workspace),
            fault_hook=self.fault,
        )


@pytest.mark.integration
@pytest.mark.parametrize("fault_point", FAULT_POINTS)
def test_restart_preserves_certified_work_without_duplicate_dispatch(
    tmp_path: Path,
    fault_point: str,
) -> None:
    harness = FaultHarness(tmp_path, fail_once_at=fault_point)

    harness.start_and_crash()
    recovered = harness.restart()

    assert recovered.certified_work_ids == {harness.work_item_id}
    assert recovered.dispatch_count(harness.work_item_id) == harness.expected_dispatches
    assert recovered.certification_count == 1
    assert recovered.acceptance_count == 1
    assert recovered.checkpoint_count == 1
    assert recovered.candidate_count == 1
    assert recovered.generation_count == 1
    assert recovered.published_generation_id.startswith("sha256:")
    assert recovered.published_root_hashes == recovered.accepted_root_hashes
