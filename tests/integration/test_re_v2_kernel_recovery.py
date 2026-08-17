"""Integrated crash/restart proof for the pinned RE v2 execution kernel."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Callable

import pytest

from harness.re_v2.budget import evaluate_budget
from harness.re_v2.candidates import CandidateStore, DispatchLease, ProcessIdentity
from harness.re_v2.canonical import canonical_json_bytes, content_digest
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
from harness.re_v2.projection import project_run
from harness.re_v2.publication import (
    GenerationManifest,
    current_index_hash,
    load_published_v2_index,
    publish_generation,
)
from harness.re_v2.recovery import ProcessState, ReV2RunContext
from harness.re_v2.run_store import (
    ReV2Paths,
    create_run_store,
    load_run_manifest,
)
from harness.re_v2.snapshot import (
    CapturedSnapshot,
    capture_source_snapshot,
    validate_source_snapshot,
)


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

DISPATCH_EVENT_PREFIX = (
    "run_created",
    "work_planned",
    "dispatch_leased",
    "dispatch_started",
)
PERSISTED_CANDIDATE_EVENT_PREFIX = (
    *DISPATCH_EVENT_PREFIX,
    "dispatch_observed",
    "candidate_persisted",
)
CHECKPOINT_EVENT_PREFIX = (
    *PERSISTED_CANDIDATE_EVENT_PREFIX,
    "candidate_certified",
    "artifact_accepted",
    "checkpoint_recorded",
)
COMPLETED_EVENT_PREFIX = (
    *CHECKPOINT_EVENT_PREFIX,
    "work_planned",
    "run_completed",
)

EXPECTED_EVENT_PREFIXES = {
    "dispatch_started": DISPATCH_EVENT_PREFIX,
    "provider_terminated": DISPATCH_EVENT_PREFIX,
    "candidate_renamed": DISPATCH_EVENT_PREFIX,
    "certification_written": PERSISTED_CANDIDATE_EVENT_PREFIX,
    "checkpoint_recorded": CHECKPOINT_EVENT_PREFIX,
    "generation_promoted": COMPLETED_EVENT_PREFIX,
    "index_replaced": COMPLETED_EVENT_PREFIX,
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

    @property
    def execution_mode(self) -> str:
        return "in_process"

    def execute(
        self,
        snapshot_root: Path,
        work_item: WorkItem,
        lease: DispatchLease,
    ) -> tuple[Path, ExecutionObservation]:
        assert snapshot_root.is_dir()
        self.calls.append(lease.dispatch_id)
        self.output_root.mkdir(parents=True, exist_ok=True)
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

    @property
    def expected_dispatches(self) -> int:
        return EXPECTED_DISPATCHES[self.fail_once_at]

    @property
    def work_item_id(self) -> str:
        snapshot = self._load_persisted_snapshot()
        context = self._new_context(snapshot)
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

    def start_and_crash(self, *, verify_prefix: bool = True) -> None:
        try:
            snapshot = self._capture_snapshot()
            self.fault("snapshot_created")
            context = self._new_context(snapshot)
            executor = RecordingExecutor(self.outputs)
            self._controller(
                context,
                executor=executor,
                fault_hook=self.fault,
            ).run_until_stopped()
            self._publish(context, fault_hook=self.fault)
        except InjectedCrash as exc:
            assert exc.boundary == self.fail_once_at
        else:  # pragma: no cover - every matrix row must hit its named seam.
            pytest.fail(f"fault hook {self.fail_once_at!r} did not fire")
        assert self.fault.fired is True
        if verify_prefix:
            self.assert_durable_prefix()

    def restart(self) -> RecoveredRun:
        # Simulate a new process: every restart authority is reconstructed from
        # persisted bytes, with a new executor and no fail-once hook object.
        snapshot = self._load_persisted_snapshot()
        context = self._new_context(snapshot)
        executor = RecordingExecutor(self.outputs)
        result = self._controller(
            context,
            executor=executor,
            fault_hook=None,
        ).run_until_stopped()
        assert result.status == "complete"
        published = self._publish(context, fault_hook=None)

        history = context.event_store.replay()
        ledger = context.ledger.replay()
        expected_projection = canonical_json_bytes(
            project_run(context.manifest, history, ledger)
        )
        assert context.paths.projection.read_bytes() == expected_projection
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

    def assert_durable_prefix(self, boundary: str | None = None) -> None:
        """Validate the exact on-disk prefix immediately after one crash."""
        selected = boundary or self.fail_once_at
        snapshot = self._load_persisted_snapshot()
        validate_source_snapshot(snapshot)
        provider_outputs = self._provider_output_directories()

        if selected == "snapshot_created":
            assert not self.run_dir.exists(), "snapshot seam created a run attempt"
            assert provider_outputs == (), "snapshot seam invoked the provider"
            return

        paths = ReV2Paths.for_run(self.run_dir)
        manifest = load_run_manifest(self.run_dir)
        assert manifest.source_snapshot_id == snapshot.snapshot_id
        history = EventStore(paths).replay()
        event_types = tuple(event.type for event in history)
        assert event_types == EXPECTED_EVENT_PREFIXES[selected], (
            f"{selected} durable event prefix mismatch: {event_types}"
        )

        candidates = CandidateStore(
            paths,
            process_probe=lambda pid: f"fixture-process:{pid}",
            clock=lambda: NOW,
        ).discover()
        candidate_expected = selected in {
            "candidate_renamed",
            "certification_written",
            "checkpoint_recorded",
            "generation_promoted",
            "index_replaced",
        }
        assert len(candidates) == int(candidate_expected), (
            f"{selected} committed candidate durable prefix mismatch"
        )
        provider_expected = selected != "dispatch_started"
        assert len(provider_outputs) == int(provider_expected), (
            f"{selected} provider-output durable prefix mismatch"
        )

        objects = ObjectStore(paths.objects)
        ledger = Ledger(
            paths,
            objects,
            supported_verifiers={"fixture-verifier": "v1"},
        ).replay()
        certification_expected = selected in {
            "certification_written",
            "checkpoint_recorded",
            "generation_promoted",
            "index_replaced",
        }
        artifact_expected = selected in {
            "checkpoint_recorded",
            "generation_promoted",
            "index_replaced",
        }
        assert len(ledger.certifications) == int(certification_expected), (
            f"{selected} certification receipt durable prefix mismatch"
        )
        assert len(ledger.accepted_artifacts) == int(artifact_expected), (
            f"{selected} artifact receipt durable prefix mismatch"
        )
        if selected == "certification_written":
            assert "candidate_certified" not in event_types, (
                "certification event must follow the durable receipt boundary"
            )
        if selected in {
            "checkpoint_recorded",
            "generation_promoted",
            "index_replaced",
        }:
            assert event_types.count("checkpoint_recorded") == 1

        generation_root = self.workspace / "re" / "v2" / "generations"
        generations = (
            tuple(
                path
                for path in generation_root.iterdir()
                if path.is_dir() and not path.name.startswith(".")
            )
            if generation_root.is_dir()
            else ()
        )
        generation_expected = selected in {"generation_promoted", "index_replaced"}
        assert len(generations) == int(generation_expected), (
            f"{selected} generation durable prefix mismatch"
        )
        index_path = self.workspace / "re" / "v2" / "index.json"
        assert index_path.exists() is (selected == "index_replaced"), (
            f"{selected} workspace index durable prefix mismatch"
        )
        if generation_expected:
            GenerationManifest.from_bytes(
                (generations[0] / "manifest.json").read_bytes()
            )
        if selected == "generation_promoted":
            assert load_published_v2_index(self.workspace) is None
        elif selected == "index_replaced":
            assert load_published_v2_index(self.workspace) is not None

    def _capture_snapshot(self) -> CapturedSnapshot:
        self.source.mkdir()
        self.snapshots.mkdir()
        (self.source / "api.py").write_text("VALUE = 1\n", encoding="utf-8")
        return capture_source_snapshot(
            self.source,
            self.snapshots,
            exclusions=(),
        )

    def _load_persisted_snapshot(self) -> CapturedSnapshot:
        assert self.snapshots.is_dir(), "durable source snapshot root is missing"
        bundles = tuple(
            path
            for path in self.snapshots.iterdir()
            if path.is_dir() and not path.name.startswith(".")
        )
        assert len(bundles) == 1, "exactly one durable source snapshot is required"
        bundle = bundles[0]
        manifest_path = bundle / "manifest.json"
        raw = json.loads(manifest_path.read_bytes())
        kind = raw.get("kind")
        assert kind in {"git-worktree", "content-snapshot"}
        snapshot = CapturedSnapshot(
            snapshot_id=str(raw["snapshot_id"]),
            kind=kind,
            read_root=bundle / "source",
            manifest_path=manifest_path,
        )
        validate_source_snapshot(snapshot)
        return snapshot

    def _provider_output_directories(self) -> tuple[Path, ...]:
        if not self.outputs.is_dir():
            return ()
        return tuple(
            path
            for path in sorted(self.outputs.iterdir())
            if path.is_dir() and not path.name.startswith(".")
        )

    def _new_context(self, snapshot: CapturedSnapshot) -> ReV2RunContext:
        if not self.run_dir.exists():
            manifest = RunManifest(
                schema_version=1,
                engine="re-v2",
                engine_protocol_version="2.0",
                run_id=self.run_dir.name,
                created_at=NOW,
                source_snapshot_id=snapshot.snapshot_id,
                source_snapshot_kind=snapshot.kind,
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
        manifest = load_run_manifest(self.run_dir)
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
        graph = validate_work_graph(
            (template,),
            requested_goals=manifest.requested_goals,
            source_snapshot_id=manifest.source_snapshot_id,
            partition_manifest_id=manifest.partition_manifest_id,
        )
        objects = ObjectStore(paths.objects)
        return ReV2RunContext(
            paths=paths,
            snapshot=snapshot,
            graph=graph,
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

    def _controller(
        self,
        context: ReV2RunContext,
        *,
        executor: WorkExecutor,
        fault_hook: Callable[[str], None] | None,
    ) -> ReV2Controller:
        return ReV2Controller(
            context,
            executor=executor,
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
            fault_hook=fault_hook,
        )

    def _publish(
        self,
        context: ReV2RunContext,
        *,
        fault_hook: Callable[[str], None] | None,
    ):
        self.workspace.mkdir(exist_ok=True)
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
            fault_hook=fault_hook,
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


@pytest.mark.integration
def test_crash_prefix_oracle_rejects_certification_hook_before_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mutation proof: the named seam cannot move before its durable write."""
    harness = FaultHarness(tmp_path, fail_once_at="certification_written")
    original = Ledger.record_certification

    def moved_hook_before_receipt(
        ledger: Ledger,
        receipt: CertificationReceipt,
        work_item: WorkItem,
    ) -> object:
        harness.fault("certification_written")
        return original(ledger, receipt, work_item)

    monkeypatch.setattr(Ledger, "record_certification", moved_hook_before_receipt)
    harness.start_and_crash(verify_prefix=False)

    with pytest.raises(AssertionError, match="certification receipt"):
        harness.assert_durable_prefix()


@pytest.mark.integration
@pytest.mark.parametrize(
    ("expected_boundary", "premature_boundary"),
    (
        ("dispatch_started", "dispatch_leased"),
        ("provider_terminated", "dispatch_started"),
        ("candidate_renamed", "provider_terminated"),
        ("certification_written", "candidate_renamed"),
        ("checkpoint_recorded", "artifact_acceptance_written"),
        ("generation_promoted", "generation_temporary_written"),
        ("index_replaced", "index_temporary_written"),
    ),
)
def test_crash_prefix_oracle_rejects_each_premature_boundary(
    tmp_path: Path,
    expected_boundary: str,
    premature_boundary: str,
) -> None:
    """Each named post-write seam fails if observed at its prior prefix."""
    harness = FaultHarness(tmp_path, fail_once_at=premature_boundary)
    harness.start_and_crash(verify_prefix=False)

    with pytest.raises(AssertionError):
        harness.assert_durable_prefix(expected_boundary)


@pytest.mark.integration
def test_snapshot_prefix_oracle_rejects_hook_before_snapshot_commit(
    tmp_path: Path,
) -> None:
    harness = FaultHarness(tmp_path, fail_once_at="snapshot_created")

    with pytest.raises(AssertionError, match="source snapshot"):
        harness.assert_durable_prefix("snapshot_created")
