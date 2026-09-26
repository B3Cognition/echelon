# Provider Dispatch Finalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every command-driven Phase A provider assignment one typed artifact contract, one exclusive write boundary, one shared finalization path, and one receipt set sealed by the existing spec-step kernel.

**Architecture:** Workflow and runtime assignment descriptors compile immutable artifact contracts before dispatch. The shared finalizer projects each contract into provider permissions, proves current-dispatch publication, classifies blocked outcomes, and returns a trusted result plus receipt. Executors accumulate accepted child results without durable journal/state/cost writes; the controller seals their execution manifest and effects into the existing spec step, whose publication effect also performs CHIEF's canonical constitution promotion.

**Tech Stack:** Python 3.11, frozen dataclasses, strict canonical JSON, existing Claude/Codex write-scope adapters, descriptor-safe filesystem operations, YAML workflow definitions, pytest, Git.

**Spec:** `docs/superpowers/specs/2026-09-26-provider-dispatch-finalization-design.md`

## Global Constraints

- `pending_spec_step` remains the only durable authority for an incomplete Phase A step.
- `SquadStateStore` remains the sole owner of atomic state writes and CAS.
- Do not add a publication marker to `state.json`, another outbox, another effect kind, or another recovery loop.
- The compiled assignment contract is the sole source of product write permissions and post-dispatch publication validation.
- Provider claims and receipt-shaped provider fields are untrusted; the harness creates every accepted receipt.
- Existing artifacts never satisfy a required output for a new dispatch, including identical-content output without changed filesystem identity.
- Preserve Commander decisions, routing policy, semantic validators, modes, and project topology.
- Preserve managed discovery's stronger private-directory protocol; do not pass it through the new finalizer.
- Support only newly initialized current-version runs after the current bundle is installed or refreshed. Do not migrate historical run state or infer missing contracts.
- RE and Delivery keep their own contracts; do not create a generic workflow framework.
- Every production change follows RED, GREEN, REFACTOR and ends in an independently testable commit.

Before Task 1, bind the reviewed implementation baseline outside the working tree:

```bash
implementation_base=$(git rev-parse HEAD)
printf '%s\n' "$implementation_base" > "$(git rev-parse --git-dir)/last-provider-finalization-base"
```

## Review Focus

- A provider that cannot enforce an exclusive write projection fails before execution, while Claude and Codex admit exact-target and sibling-temp atomic writes; Tasks 2 and 3 pin this.
- A legitimate `BLOCKED` or `STOP_AND_ASK` result with no artifact is preserved without being rewritten as missing-output recovery, while any unauthorized mutation still fails; Tasks 3 and 4 pin this.
- Initial WHY3, work assessment, final revalidation, skipped specialists, deferred PLAN2, and reused PLAN2 remain distinct manifest occurrences; Tasks 1, 4, and 5 pin this.
- A crash after a child is finalized but before the outer spec step is sealed leaves no accepted journal, cost, state, route, or canonical constitution effect; Tasks 4-6 pin this.
- Managed discovery remains the sole named stronger boundary and a new direct `exec_agent` call fails the structural guard; Task 6 pins this.

---

### Task 1: Compile Typed Provider Assignment Contracts

**Files:**
- Modify: `src/harness/provider_output_publication.py`
- Modify: `src/harness/phase_graph.py`
- Create: `src/harness/phase_a_provider_assignments.py`
- Modify: `runtime/workflow/definition.yaml`
- Modify: `tests/kernel/test_phase_graph.py`
- Create: `tests/unit/test_provider_artifact_contract.py`

**Interfaces:**
- Produces: `ProviderArtifactRule`, `ProviderReadRule`, `ProviderArtifactContract`, `ResolvedProviderArtifactContract`, and `ProviderArtifactContractError`.
- Produces: `compile_provider_artifact_contract(raw, *, assignment_id) -> ProviderArtifactContract`.
- Produces: `resolve_provider_artifact_contract(contract, *, roots) -> ResolvedProviderArtifactContract`.
- Produces: `provider_artifact_contract_sha256(contract) -> str`.
- Produces: `CompiledProviderAssignment(assignment_id, agent_id, mode, contract)`.
- Produces: `PhaseNode.provider_assignment(*, collection: str | None = None, index: int | None = None) -> CompiledProviderAssignment` and `runtime_provider_assignment(assignment_id: str, *, artifact_path: str | None = None) -> CompiledProviderAssignment`.
- Consumes: exact controller-resolved roots `active_spec`, `squad`, and `proposal`; read roots `active_spec`, `project`, `squad`, `context`, `runtime`, and `staging`.

- [ ] **Step 1: Write failing contract and graph tests**

Add strict contract tests before production types exist:

```python
def test_compile_publish_contract_preserves_typed_rules() -> None:
    contract = compile_provider_artifact_contract(
        {
            "mode": "publish",
            "allow_shadow_recovery": True,
            "artifacts": [
                {"root": "active_spec", "path": "spec.md", "kind": "file", "requirement": "required"},
                {"root": "active_spec", "path": "adr", "kind": "directory", "requirement": "optional"},
            ],
            "read_inputs": [
                {"root": "active_spec", "path": "assumptions.md", "kind": "file"},
            ],
        },
        assignment_id="phase1-what",
    )
    assert contract.mode == "publish"
    assert contract.artifacts[0].path == "spec.md"
    assert len(provider_artifact_contract_sha256(contract)) == 64


@pytest.mark.parametrize(
    "raw",
    [
        None,
        {"mode": "publish", "artifacts": [{"root": "active_spec", "path": "../spec.md", "kind": "file", "requirement": "required"}]},
        {"mode": "result_only", "artifacts": [{"root": "active_spec", "path": "spec.md", "kind": "file", "requirement": "required"}]},
        {"mode": "publish", "artifacts": [
            {"root": "active_spec", "path": "contracts", "kind": "directory", "requirement": "required"},
            {"root": "active_spec", "path": "contracts/http.md", "kind": "file", "requirement": "required"},
        ]},
    ],
)
def test_compile_contract_rejects_missing_unsafe_or_overlapping_rules(raw: object) -> None:
    with pytest.raises(ProviderArtifactContractError):
        compile_provider_artifact_contract(raw, assignment_id="phase")
```

In `test_phase_graph.py`, add tests proving an agent phase without a contract fails, deterministic nodes with a contract fail, nested staged/conditional assignments compile distinct stable IDs, parallel mutable overlap fails, the checked-in workflow compiles, and every provider-backed entry returned by the graph has a contract.

Add runtime-registry assertions for:

```python
EXPECTED_RUNTIME_ASSIGNMENTS = {
    "phase3-consensus/sage-work-assessment": "result_only",
    "phase3-consensus/sage-decision-proposal": "publish",
    "commander/routing-judgment": "result_only",
    "commander/human-resolution": "result_only",
    "provider/echelon-result-repair": "result_only",
}
```

- [ ] **Step 2: Run the contract partition to verify RED**

```bash
../../.venv/bin/python -m pytest -q \
  tests/unit/test_provider_artifact_contract.py tests/kernel/test_phase_graph.py \
  -k 'artifact_contract or provider_assignment or runtime_assignment' -x
```

Expected: collection fails because the contract types and runtime registry do not exist.

- [ ] **Step 3: Implement immutable parsing, resolution, and digests**

Add exact frozen types and strict canonical serialization:

```python
ArtifactMode = Literal["publish", "result_only", "read_only"]
ArtifactRoot = Literal["active_spec", "squad", "proposal"]
ReadRoot = Literal["active_spec", "project", "squad", "context", "runtime", "staging"]

@dataclass(frozen=True)
class ProviderArtifactRule:
    root: ArtifactRoot
    path: str
    kind: Literal["file", "directory"]
    requirement: Literal["required", "optional"]

@dataclass(frozen=True)
class ProviderReadRule:
    root: ReadRoot
    path: str
    kind: Literal["file", "directory"]

@dataclass(frozen=True)
class ProviderArtifactContract:
    mode: ArtifactMode
    artifacts: tuple[ProviderArtifactRule, ...]
    read_inputs: tuple[ProviderReadRule, ...] = ()
    allow_shadow_recovery: bool = False

@dataclass(frozen=True)
class ResolvedProviderArtifactContract:
    assignment_id: str
    contract_sha256: str
    contract: ProviderArtifactContract
    write_paths: tuple[Path, ...]
    read_paths: tuple[Path, ...]
```

Reject unknown keys, booleans where strings are required, absolute paths, `.`/`..`, empty segments, unsupported roots, duplicate targets, ancestor/descendant write overlap, and rules on `result_only` or `read_only`. Resolve each target beneath its named root and re-check containment after `resolve(strict=False)`.

- [ ] **Step 4: Compile top-level, nested, and runtime assignments**

Add `artifact_contract` and immutable compiled-assignment fields to `PhaseNode`. Top-level IDs use the phase ID. Nested IDs use `phase/{collection}/{index}/{agent}:{mode-or-default}` so duplicate roles cannot collide. Compilation rejects a missing contract before any provider can be constructed.

Register only the five runtime assignments listed in Step 1. The SAGE proposal descriptor is an optional contract overlay whose exact `proposal` target is supplied per WHY2/WHY3 occurrence and merged into that review dispatch's resolved contract; it is not a second provider call. The other four descriptors contain no artifacts.

- [ ] **Step 5: Add explicit checked-in workflow contracts**

Add inline `artifact_contract` blocks using this exact inventory; state-like prose outputs are never artifact paths:

| Assignment | Required mutable outputs | Optional mutable outputs |
|---|---|---|
| `phase1-discover` | `glossary.md`, `mental-model.md`, `boundaries.md`, `assumptions.md`, `unknowns.md` | `reference-architectures.md` |
| `phase1-synthesizer` | `glossary.md`, `mental-model.md`, `boundaries.md`, `assumptions.md`, `unknowns.md`, `contradictions-and-gaps.md`, `risks.md` | `people-and-teams.md`, `timeline.md`, `qa-test-strategy-inputs.md` |
| `phase1-modeler` | `mental-model-code.md` | `codebase-graph.md` |
| `phase1-tracker` | `user-intent.md` | `stakeholder-model.md` |
| `phase1-why1` | `assumption-review.md` | `unknowns.md`, `issues.md` |
| `phase1-constitution` | `squad:constitution.draft.md` | none |
| `phase1-what` | `spec.md`, `requirements-overview.md` | none |
| `phase1-why2` | `issues.md`, `quality-gates.md` | exact per-occurrence `proposal` target supplied by the runtime descriptor |
| `phase1-investigate` | `investigation/`, `evidence-resolution.md`, `evidence-grades.md`, `evidence-inventory.json` | none |
| `phase1-lexicon-derive` | `requirements.lexicon.md` | none |
| `phase2-decide` | `feasibility.md`, `prioritization.md`, `estimates.md`, `mvp-scope.md` | `kill-report.md` |
| `phase2-strategic-overview` | `strategic-overview.md` | none |
| `phase2-tracker-alignment` | `intent-alignment-check.md` | none |
| `phase3-how` | `plan.md`, `research.md`, `data-model.md`, `contracts/` | `constitution-amendment-candidates.md`, `architecture.md`, `adr/` |
| GUARDIAN | `security-findings.md`, `risk-acceptance-log.md` | none |
| specialist INVESTIGATOR | `research.md` | `experiment-results.md` |
| ORACLE | `domain-knowledge.md` | none |
| BENCHMARK | `performance-model.md` | none |
| ADVOCATE | `ux-report.md` | none |
| MAVERICK | `alternatives.md` | none |
| `phase3-sentinel` | `test-strategy.md`, `test-architecture.md`, `coverage-map.md` | none |
| `phase3-plan` | `tasks.md`, `critical-path.md`, `risk-matrix.md`, `dependencies.md` | none |
| WHY3 | `issues.md`, `quality-gates.md` | exact per-occurrence `proposal` target |
| ASSESS2 | `implementability-report.md` | `estimates.md` |
| PLAN2 | `tasks.md`, `critical-path.md`, `risk-matrix.md`, `dependencies.md` | none |
| experimental constitution quality | `constitution-quality-report.md` | none |
| experimental tasks quality | `tasks.md`, `tasks-quality-report.md` | none |
| experimental ADR quality | `adr-quality-report.md` | none |
| bugfix DEBUGGER, SENTINEL, and SPEC GUARD | `result_only` | none |

Read inputs remain narrowly rooted declarations. Use directory reads for the active spec and project source when an assignment's context is dynamic; never convert a read root into a write root.

- [ ] **Step 6: Run graph and contract tests GREEN**

```bash
../../.venv/bin/python -m pytest -q \
  tests/unit/test_provider_artifact_contract.py tests/kernel/test_phase_graph.py -x
```

Expected: PASS, including checked-in workflow completeness and overlap rejection.

- [ ] **Step 7: Commit**

```bash
git add src/harness/provider_output_publication.py src/harness/phase_graph.py \
  src/harness/phase_a_provider_assignments.py runtime/workflow/definition.yaml \
  tests/kernel/test_phase_graph.py tests/unit/test_provider_artifact_contract.py
git commit -m "feat: compile Phase A provider artifact contracts"
```

---

### Task 2: Enforce Contract-Derived Provider Permissions and Repair Isolation

**Files:**
- Modify: `src/harness/provider_output_publication.py`
- Modify: `src/harness/ai_cli_backend.py`
- Modify: `src/harness/ai_cli_backends/claude.py`
- Modify: `src/harness/ai_cli_backends/codex.py`
- Modify: `src/harness/llm_provider.py`
- Modify: `src/harness/squad_provider.py`
- Modify: `src/harness/prepared_phase_result.py`
- Modify: `tests/unit/test_ai_cli_backend.py`
- Modify: `tests/unit/test_squad_provider.py`
- Modify: `tests/kernel/test_prepared_phase_result.py`

**Interfaces:**
- Produces: `ExclusiveWriteScopeBackend` runtime-checkable capability protocol.
- Produces: `AICodingCliProvider.supports_exclusive_write_scope: bool`.
- Produces: `permission_metadata(resolved_contract) -> dict[str, object]` with exact `tool_read_roots`, `tool_write_paths`, and `tool_write_scope_exclusive=True`.
- Produces: `SquadAgentResult.provider_attempts: tuple[dict[str, object], ...]` with harness-generated attempt IDs and bounded metadata.
- Consumes: `ResolvedProviderArtifactContract` from Task 1.

- [ ] **Step 1: Write failing capability and repair-scope tests**

```python
def test_publish_projection_is_exact_and_exclusive(tmp_path: Path) -> None:
    resolved = _resolved_contract(tmp_path, mode="publish", outputs=("issues.md",))
    assert permission_metadata(resolved) == {
        "tool_read_roots": [str(tmp_path / "spec")],
        "tool_write_paths": [str(tmp_path / "spec/issues.md")],
        "tool_write_scope_exclusive": True,
    }


def test_result_repair_cannot_inherit_publish_scope(monkeypatch, tmp_path: Path) -> None:
    provider = _provider("codex")
    requests: list[dict[str, object]] = []
    monkeypatch.setattr(provider, "run_agent_result", _invalid_then_valid_result(requests))
    result = provider.exec_agent(
        str(tmp_path),
        "prompt",
        prompt_metadata={
            "tool_write_paths": [str(tmp_path / "spec.md")],
            "tool_write_scope_exclusive": True,
        },
    )
    repair = requests[1]["prompt_metadata"]
    assert repair["tool_write_paths"] == []
    assert repair["tool_write_scope_exclusive"] is True
    assert [attempt["kind"] for attempt in result.provider_attempts] == ["primary", "result_repair"]
```

Also test that an unsupported backend returns the bounded `exclusive-write-scope-unsupported` failure before its `run_agent` method is called, and that Claude/Codex preserve allowed sibling-temp atomic replacement while denying arbitrary siblings, source files, state, and journal paths.

- [ ] **Step 2: Run provider permission tests to verify RED**

```bash
../../.venv/bin/python -m pytest -q \
  tests/unit/test_ai_cli_backend.py tests/unit/test_squad_provider.py \
  tests/kernel/test_prepared_phase_result.py \
  -k 'exclusive_write or result_repair or provider_attempt' -x
```

Expected: FAIL because capability detection and attempt identities do not exist and repair inherits `run_kwargs`.

- [ ] **Step 3: Add an explicit backend capability**

```python
@runtime_checkable
class ExclusiveWriteScopeBackend(Protocol):
    exclusive_write_scope_contract_id: str


class ClaudeCliBackend:
    exclusive_write_scope_contract_id = "echelon.exclusive-write-scope.v1"


class CodexCliBackend:
    exclusive_write_scope_contract_id = "echelon.exclusive-write-scope.v1"
```

`AICodingCliProvider.run_agent_result()` rejects a request containing `tool_write_scope_exclusive=True` unless its backend satisfies the protocol. Keep the existing Claude/Codex argument builders as the native enforcement points; do not emulate containment with prompt prose for Copilot, OpenCode, plain, or openai-compatible backends.

- [ ] **Step 4: Isolate structured-result repair**

Generate a random attempt ID before each provider call. Build repair request metadata from a fresh mapping:

```python
repair_request_metadata = {
    "prompt_metadata": {
        "tool_read_roots": [str(Path(project_root).resolve(strict=False))],
        "tool_write_paths": [],
        "tool_write_scope_exclusive": True,
    }
}
```

Never reuse the primary `run_kwargs`. Preserve timeout only. Record primary and repair attempt ID, kind, provider/model, start/end timestamps, outcome, and response digest in `provider_attempts`. Add this field to prepared-result bounded detachment, reconstruction, and attestation so a forged mutable attempt list cannot cross the boundary.

- [ ] **Step 5: Run provider and prepared-result tests GREEN**

```bash
../../.venv/bin/python -m pytest -q \
  tests/unit/test_ai_cli_backend.py tests/unit/test_squad_provider.py \
  tests/kernel/test_prepared_phase_result.py -x
```

Expected: PASS, including the original provider repair and Git-boundary tests.

- [ ] **Step 6: Commit**

```bash
git add src/harness/provider_output_publication.py src/harness/ai_cli_backend.py \
  src/harness/ai_cli_backends/claude.py \
  src/harness/ai_cli_backends/codex.py src/harness/llm_provider.py \
  src/harness/squad_provider.py src/harness/prepared_phase_result.py \
  tests/unit/test_ai_cli_backend.py tests/unit/test_squad_provider.py \
  tests/kernel/test_prepared_phase_result.py
git commit -m "fix: enforce provider artifact write scopes"
```

---

### Task 3: Build the Shared Dispatch Finalizer

**Files:**
- Create: `src/harness/provider_dispatch_finalizer.py`
- Modify: `src/harness/provider_output_publication.py`
- Create: `tests/unit/test_provider_dispatch_finalizer.py`
- Modify: `tests/kernel/test_squad_executors_journal.py`

**Interfaces:**
- Produces: `ProviderDispatchContext`, `ProviderDispatchReceipt`, `FinalizedProviderResult`, and `ProviderDispatchFailure`.
- Produces: `ProviderDispatchFinalizer.dispatch(context, execute, validate_result, classify_outcome, semantic_validator=None) -> FinalizedProviderResult`.
- Produces: outcome values `published`, `domain_blocked`, and `invalid`.
- Consumes: one resolved contract, one detached `SquadAgentResult`, and optional assignment-owned semantic validator.

- [ ] **Step 1: Write failing finalizer behavior tests**

```python
def test_finalizer_accepts_identical_content_with_new_identity(tmp_path: Path) -> None:
    target = tmp_path / "spec/issues.md"
    target.parent.mkdir()
    target.write_text("same\n", encoding="utf-8")
    finalized = _dispatch(
        tmp_path,
        outputs=("issues.md",),
        execute=lambda metadata: _replace_and_claim(target, "same\n", metadata),
    )
    assert finalized.receipt.outcome == "published"
    assert finalized.receipt.outputs[0]["evidence_kind"] == "replaced"
    assert finalized.receipt.outputs[0]["preimage_identity_sha256"] != finalized.receipt.outputs[0]["postimage_identity_sha256"]


def test_domain_blocked_without_artifact_preserves_policy_outcome(tmp_path: Path) -> None:
    finalized = _dispatch(
        tmp_path,
        outputs=("issues.md",),
        execute=lambda metadata: _result("BLOCKED", output_files=[]),
        classify=lambda result: "domain_blocked",
    )
    assert finalized.result.verdict == "BLOCKED"
    assert finalized.receipt.outputs == ()
```

Add separate cases for missing first generation, stale claim, false claim, optional omission, optional unclaimed mutation, forged receipt removal, file/directory mismatch, symlink, special file, empty directory, directory-metadata-only touch, sorted member manifests, fresh/stale shadow recovery, prompt/input digest binding, validator identity binding, and repair-attempt-chain binding.

Add parallel isolation with two contracts and a provider callback that attempts the other assignment's path. Add retry isolation proving an unsealed prior write becomes the next baseline and must be rewritten.

- [ ] **Step 2: Run finalizer tests to verify RED**

```bash
../../.venv/bin/python -m pytest -q tests/unit/test_provider_dispatch_finalizer.py -x
```

Expected: collection fails because `provider_dispatch_finalizer` does not exist.

- [ ] **Step 3: Implement the trusted dispatch boundary**

```python
@dataclass(frozen=True)
class ProviderDispatchContext:
    phase_id: str
    assignment_id: str
    occurrence_id: str
    state_revision: int
    contract: ResolvedProviderArtifactContract
    prompt_sha256: str
    prompt_metadata_sha256: str

@dataclass(frozen=True)
class FinalizedProviderResult:
    result: SquadAgentResult
    receipt: ProviderDispatchReceipt

class ProviderDispatchFinalizer:
    def dispatch(
        self,
        context: ProviderDispatchContext,
        *,
        execute: Callable[[dict[str, object]], SquadAgentResult],
        validate_result: Callable[[SquadAgentResult], SquadAgentResult],
        classify_outcome: Callable[[SquadAgentResult], str],
        semantic_validator: ProviderSemanticValidator | None = None,
    ) -> FinalizedProviderResult:
        guard = ProviderOutputGuard.capture(context)
        raw_result = execute(permission_metadata(context.contract))
        result = strip_provider_receipt_fields(validate_result(raw_result))
        outcome = classify_outcome(result)
        proof = guard.finalize(result.echelon_result, outcome=outcome)
        if proof.failure is not None:
            raise proof.failure
        receipt = build_dispatch_receipt(context, result, outcome, proof)
        if semantic_validator is not None:
            receipt = semantic_validator.validate(result, receipt)
        return FinalizedProviderResult(result=result, receipt=receipt)
```

Implement the helpers called by this exact orchestration in the same module. They must snapshot before permissioned execution, detach and validate before classification, remove provider-forged receipt fields, recover only current shadow output, prove the claimed artifact set, bind the versioned semantic result to that same receipt, and return immutable detached values.

- [ ] **Step 4: Strengthen filesystem proof and directory manifests**

Reuse the current descriptor-safe snapshot primitives but store pre/post identity and content separately. Directory receipts list sorted regular-file leaves. Reject empty required directories, symlinks, special files, disappearing members, and identity-only directory changes. An optional target changed without a matching claim fails. A shadow promotion records the shadow pre/post identity and the canonical postimage as `shadow_promoted`.

Canonical receipt serialization contains only bounded JSON values and includes schema version, dispatch ID, phase/assignment/occurrence IDs, state revision, contract/prompt/metadata digests, outcome, output evidence, semantic validator identity/result digest, provider attempt chain digest, and validated provider result digest.

- [ ] **Step 5: Run finalizer and legacy primitive tests GREEN**

```bash
../../.venv/bin/python -m pytest -q \
  tests/unit/test_provider_dispatch_finalizer.py \
  tests/kernel/test_squad_executors_journal.py \
  -k 'provider_output or finalizer or shadow or directory or blocked' -x
```

Expected: PASS. Keep the old guard temporarily only as a compatibility shim for executor tests not yet cut over.

- [ ] **Step 6: Commit**

```bash
git add src/harness/provider_dispatch_finalizer.py \
  src/harness/provider_output_publication.py \
  tests/unit/test_provider_dispatch_finalizer.py \
  tests/kernel/test_squad_executors_journal.py
git commit -m "feat: finalize Phase A provider dispatches"
```

---

### Task 4: Cut Executors Over and Accumulate Accepted Children

**Files:**
- Create: `src/harness/phase_execution.py`
- Modify: `src/harness/squad_executors.py`
- Modify: `tests/kernel/test_squad_executors_journal.py`
- Modify: `tests/kernel/test_phase3_work_assessment.py`
- Modify: `tests/kernel/test_phase3_repair_handoff.py`
- Modify: `tests/unit/test_consensus_routing.py`
- Modify: `tests/unit/test_kb_proposals.py`

**Interfaces:**
- Produces: `ProviderExecutionManifestEntry`, `PhaseExecutionAccumulator`, `FinalizedPhaseExecution`, and `extend_phase_execution(execution, finalized, *, occurrence_id) -> FinalizedPhaseExecution`.
- Produces: `PhaseExecutionAccumulator.record(finalized: FinalizedProviderResult)`, `.skip(assignment, occurrence_id, reason)`, `.defer(assignment, occurrence_id, reason)`, `.reuse(assignment, occurrence_id, sealed_reference)`, `.project_state(base)`, and `.freeze(result)`.
- Changes: every `PhaseExecutor.execute(node, state_store)` returns `FinalizedPhaseExecution | ExecutorBlockedResult`.
- Changes: `ExecutorBlockedResult` retains the complete accepted accumulator prefix.
- Consumes: shared finalizer and graph/runtime assignments from Tasks 1 and 3.

- [ ] **Step 1: Write failing accumulator and executor-cutover tests**

```python
def test_accumulator_keeps_repeated_occurrences_in_manifest() -> None:
    acc = PhaseExecutionAccumulator("phase3-consensus")
    acc.record(_finalized("why3/initial", state_updates={"why3_verdict": "PASS"}))
    acc.record(_finalized("why3/final-revalidation", state_updates={"why3_verdict": "PASS"}))
    execution = acc.freeze(_result("DONE"))
    assert [row.occurrence_id for row in execution.manifest] == [
        "why3/initial",
        "why3/final-revalidation",
    ]
    assert len(execution.receipts) == 2


def test_stage_one_acceptance_does_not_persist_before_outer_seal(tmp_path: Path) -> None:
    store, executor, provider = _staged_fixture(tmp_path)
    before = (store.load(), _journal_bytes(tmp_path))
    provider.side_effect = [_accepted_why3(), RuntimeError("stage two failed")]
    with pytest.raises(RuntimeError, match="stage two failed"):
        executor.execute(_consensus_node(), store)
    assert store.load() == before[0]
    assert _journal_bytes(tmp_path) == before[1]
```

Add tests proving: conditional specialist skips produce manifest entries; PLAN2 defer/reuse is explicit; SAGE work assessment is `result_only`; revalidation does not replace the initial WHY3 receipt; blocked and early-return paths retain accepted prefixes; no executor calls `state_store.increment_cost`, saves accepted child updates, or appends accepted journal entries; ASSESS2 `REJECTED` preserves its report; and SAGE evidence `BLOCKED` is not converted to missing output.

- [ ] **Step 2: Run executor tests to verify RED**

```bash
../../.venv/bin/python -m pytest -q \
  tests/kernel/test_squad_executors_journal.py \
  tests/kernel/test_phase3_work_assessment.py \
  tests/kernel/test_phase3_repair_handoff.py \
  tests/unit/test_consensus_routing.py tests/unit/test_kb_proposals.py \
  -k 'accumulator or manifest or receipt or no_persist or work_assessment or revalidation' -x
```

Expected: FAIL because executors return raw results, persist child effects, and overwrite revalidation results.

- [ ] **Step 3: Implement immutable phase execution records**

```python
@dataclass(frozen=True)
class ProviderExecutionManifestEntry:
    assignment_id: str
    occurrence_id: str
    contract_sha256: str
    status: Literal["executed", "skipped", "deferred", "reused"]
    reason: str
    receipt_sha256: str | None
    reused_step_id: str | None
    reused_dispatch_id: str | None

@dataclass(frozen=True)
class FinalizedPhaseExecution:
    result: SquadAgentResult
    manifest: tuple[ProviderExecutionManifestEntry, ...]
    receipts: tuple[dict[str, object], ...]
    accepted_results: tuple[SquadAgentResult, ...]
    projected_state_updates: Mapping[str, object]
    cost_usd_delta: float
```

The mutable accumulator exists only during one executor call, locks its `record()` method for staged parallel completion, and freezes in declared assignment/occurrence order rather than thread completion order. It detaches every appended result and receipt. Duplicate occurrence IDs or a receipt on skipped/deferred entries fail closed.

- [ ] **Step 4: Add one executor-owned `_dispatch_provider` helper**

Replace `_exec_agent_with_contract` at each command-driven executor call with one helper that:

```python
def _dispatch_provider(
    self,
    *,
    node: PhaseNode,
    assignment: CompiledProviderAssignment,
    occurrence_id: str,
    state: Mapping[str, object],
    prompt: str,
    result_contract: EchelonResultContract,
    prompt_metadata: Mapping[str, object],
    outcome_classifier: OutcomeClassifier,
    semantic_validator: ProviderSemanticValidator | None = None,
) -> FinalizedProviderResult:
    resolved = resolve_provider_artifact_contract(
        assignment.contract,
        roots=self._provider_artifact_roots(node, state, occurrence_id),
    )
    metadata = {
        **dict(prompt_metadata),
        **permission_metadata(resolved),
    }
    context = self._provider_dispatch_context(
        node=node,
        assignment=assignment,
        occurrence_id=occurrence_id,
        state=state,
        prompt=prompt,
        prompt_metadata=metadata,
        resolved_contract=resolved,
    )
    return self._provider_finalizer.dispatch(
        context,
        execute=lambda permissions: self._exec_raw_agent_with_contract(
            prompt,
            result_contract,
            {**metadata, **permissions},
        ),
        validate_result=lambda result: self._validate_result_state_updates(
            node,
            result,
            result_contract=result_contract,
        ),
        classify_outcome=outcome_classifier,
        semantic_validator=semantic_validator,
    )
```

Resolve contract roots from the current controller state, merge only contract-derived permission metadata with model/tool metadata, execute through `ProviderDispatchFinalizer`, and return no accepted raw result. Remove filename parsing from `_phase_prompt_metadata`; it may retain non-permission metadata only.

- [ ] **Step 5: Cut over ordinary, pre-dispatch, staged, revalidation, and conditional paths**

Use stable occurrence suffixes: `ordinary`, `pre-dispatch/{index}`, `stage1/{index}`, `stage2/{index}`, `why3/initial`, `why3/final-revalidation`, `sage/work-assessment`, and `specialist/{index}`. Record unselected specialists and deferred PLAN2. A sealed PLAN2 reuse cites its prior spec-step/receipt IDs rather than manufacturing a new receipt.

Replace direct accepted-result calls to `_write_journal_entries`, `increment_cost`, and `state_store.save` with accumulator records and projected state. Preserve durable controller attempt claims such as `claim_phase3_revalidation` only when they contain no accepted provider result. On every early return, freeze or attach the accumulator prefix to `ExecutorBlockedResult`.

- [ ] **Step 6: Run the full executor partition GREEN**

```bash
../../.venv/bin/python -m pytest -q \
  tests/kernel/test_squad_executors_journal.py \
  tests/kernel/test_phase3_work_assessment.py \
  tests/kernel/test_phase3_repair_handoff.py \
  tests/unit/test_consensus_routing.py tests/unit/test_kb_proposals.py -x
```

Expected: PASS with no executor-local provider publication branches or accepted child persistence.

- [ ] **Step 7: Commit**

```bash
git add src/harness/phase_execution.py src/harness/squad_executors.py \
  tests/kernel/test_squad_executors_journal.py \
  tests/kernel/test_phase3_work_assessment.py \
  tests/kernel/test_phase3_repair_handoff.py \
  tests/unit/test_consensus_routing.py tests/unit/test_kb_proposals.py
git commit -m "refactor: accumulate finalized Phase A dispatches"
```

---

### Task 5: Seal Execution Manifests and Deferred Effects into the Spec Step

**Files:**
- Modify: `src/harness/spec_step.py`
- Modify: `src/harness/squad_completion.py`
- Modify: `src/harness/spec_step_effects.py`
- Modify: `src/harness/prepared_phase_result.py`
- Modify: `src/harness/squad_state.py`
- Modify: `src/harness/squad.py`
- Modify: `tests/unit/test_spec_step.py`
- Modify: `tests/unit/test_squad_completion.py`
- Modify: `tests/unit/test_spec_step_effects.py`
- Modify: `tests/kernel/test_spec_step_state.py`
- Modify: `tests/integration/test_squad_controller.py`

**Interfaces:**
- Produces: `validate_provider_execution_provenance(value) -> dict[str, object]` inside `spec_step.py`, with no phase-graph or executor imports.
- Changes: `PreparedRoutingDecision` gains sealed `cost_usd_delta: float`.
- Changes: `_prepare_spec_step_effects` gains required keyword `accepted_results: Sequence[SquadAgentResult]` and seals all accepted provider results for the existing journal effect.
- Changes: `_advance_prepared_result_or_block(node, decision, *, execution, prepared_publication=None, human_input=None, human_input_initial_status=None)` seals `provider_execution` provenance and applies cost only in the final state postimage.
- Consumes: `FinalizedPhaseExecution` from Task 4.

- [ ] **Step 1: Write failing manifest-authentication tests**

```python
def test_spec_step_rejects_executed_occurrence_without_exact_receipt(tmp_path: Path) -> None:
    provenance = _provider_execution_provenance(
        manifest=[_manifest("why3/initial", status="executed", receipt_sha256="a" * 64)],
        receipts=[],
    )
    with pytest.raises(SpecStepError, match="intent_invalid"):
        _prepare(tmp_path, provenance=provenance)


def test_spec_step_accepts_skipped_deferred_reused_and_repeated_occurrences(tmp_path: Path) -> None:
    provenance = _complete_provider_execution_provenance()
    prepared = _prepare(tmp_path, provenance=provenance)
    assert prepared.intent.provenance["provider_execution"] == provenance["provider_execution"]
```

Cover unknown keys, invalid status/reason combinations, duplicate occurrence IDs, receipt digest mismatch, contract mismatch, receipts on skipped/deferred entries, malformed reuse references, non-deterministic order, forged receipt fields, and oversized manifests.

- [ ] **Step 2: Write failing deferred-effect and crash tests**

In controller/state tests, finalize a child and inject failure before `prepare_spec_step`, after preparation but before `begin_spec_step`, and after `begin_spec_step`. Before begin, assert state, journal, cost, route, and completion are unchanged. After begin, call normal recovery and assert each effect occurs once.

Add exact cost accounting:

```python
def test_provider_cost_is_applied_only_by_spec_step_commit(tmp_path: Path) -> None:
    controller, store = _controller_with_finalized_execution(tmp_path, cost_usd=1.25)
    controller._fault_after_provider_finalization = True
    with pytest.raises(InjectedFailure):
        controller._run_current_phase_step(mode="banzai", next_phase_override="")
    assert store.load()["cost_usd"] == 0.0
    controller._fault_after_provider_finalization = False
    controller._run_current_phase_step(mode="banzai", next_phase_override="")
    assert store.load()["cost_usd"] == 1.25
```

- [ ] **Step 3: Run manifest and durability tests to verify RED**

```bash
../../.venv/bin/python -m pytest -q \
  tests/unit/test_spec_step.py tests/unit/test_squad_completion.py \
  tests/unit/test_spec_step_effects.py tests/kernel/test_spec_step_state.py \
  tests/integration/test_squad_controller.py \
  -k 'provider_execution or accepted_result or cost_usd or child_finalization' -x
```

Expected: FAIL because provenance is arbitrary, journals contain only Commander judgments, and cost is executor-persisted.

- [ ] **Step 4: Add graph-independent closed manifest validation**

Validate `provider_execution` as an exact object containing schema version, manifest digest, ordered manifest rows, and ordered harness receipts. Recompute every receipt digest. Require a bijection between `executed` rows and receipts. Authenticate `reused` rows through bounded prior step/dispatch/receipt IDs, while `skipped` and `deferred` rows require a non-empty bounded reason and no receipt.

Do not import `phase_graph`, `squad_executors`, or `provider_dispatch_finalizer` from `spec_step.py`; validate only the sealed JSON structure and cross-references.

- [ ] **Step 5: Carry accumulated results through routing and existing effects**

The controller unwraps `FinalizedPhaseExecution` before prepared-result validation, but passes its accepted results, manifest, receipts, and cost delta through routing preparation. Include all accepted provider results plus Commander judgments in the existing completion journal payload, preserving manifest order. Extend routing attestation and `SquadStateStore.prepare_advance_postimage()` with a finite non-negative `cost_usd_delta`, applied exactly where token usage is applied.

Seal this exact key in the `provenance` argument passed to `prepare_spec_step`:

```python
"provider_execution": {
    "schema_version": 1,
    "manifest_sha256": execution.manifest_sha256,
    "manifest": [entry.to_dict() for entry in execution.manifest],
    "receipts": [dict(receipt) for receipt in execution.receipts],
    "cost_usd_delta": execution.cost_usd_delta,
},
```

Conditional top-level skips create a one-row skipped manifest. Managed discovery uses no `provider_execution` field because its existing completion intent remains the stronger authority.

- [ ] **Step 6: Run spec-step and controller tests GREEN**

```bash
../../.venv/bin/python -m pytest -q \
  tests/unit/test_spec_step.py tests/unit/test_squad_completion.py \
  tests/unit/test_spec_step_effects.py tests/kernel/test_spec_step_state.py \
  tests/integration/test_squad_controller.py -x
```

Expected: PASS, including saved-then-raised recovery and exactly-once cost/journal assertions.

- [ ] **Step 7: Commit**

```bash
git add src/harness/spec_step.py src/harness/squad_completion.py \
  src/harness/spec_step_effects.py src/harness/prepared_phase_result.py \
  src/harness/squad_state.py src/harness/squad.py \
  tests/unit/test_spec_step.py tests/unit/test_squad_completion.py \
  tests/unit/test_spec_step_effects.py tests/kernel/test_spec_step_state.py \
  tests/integration/test_squad_controller.py
git commit -m "feat: seal provider execution into spec steps"
```

---

### Task 6: Integrate CHIEF and Direct Controller Dispatches, Then Remove Bypasses

**Files:**
- Create: `src/harness/constitution_publication.py`
- Modify: `src/harness/spec_step.py`
- Modify: `src/harness/spec_step_effects.py`
- Modify: `src/harness/squad.py`
- Modify: `src/harness/squad_executors.py`
- Modify: `runtime/workflow/phases/phase1-constitution.md`
- Create: `tests/unit/test_constitution_publication.py`
- Modify: `tests/unit/test_spec_step_effects.py`
- Modify: `tests/integration/test_squad_controller.py`
- Modify: `tests/unit/test_spec_step_ownership.py`
- Modify: `tests/kernel/test_squad_executors_journal.py`

**Interfaces:**
- Produces: `prepare_constitution_publication(draft, target, provider_receipt) -> dict[str, object]`.
- Produces: `apply_or_verify_constitution_publication(prepared, request) -> dict[str, object]`.
- Changes: existing spec-step `publication` intent accepts a closed tagged union for external spec publication, constitution publication, or both; the effect name remains `publication`.
- Changes: direct Commander provider calls use runtime `result_only` descriptors and the shared finalizer.
- Produces: a structural call-site guard with `managed_discovery` as the sole explicit stronger-boundary exemption.

- [ ] **Step 1: Write failing constitution and bypass tests**

```python
def test_constitution_is_not_promoted_before_spec_step_authority(tmp_path: Path) -> None:
    draft, target, receipt = _constitution_inputs(tmp_path)
    request = prepare_constitution_publication(draft, target, receipt)
    assert not target.exists()
    prepared = _prepare_step(tmp_path, publication={"kind": "constitution", "request": request})
    applied = apply_or_verify_step_publication(prepared=prepared, project_root=tmp_path)
    assert target.read_bytes() == draft.read_bytes()
    assert applied["target_sha256"] == request["draft_sha256"]


def test_all_command_driven_phase_a_provider_calls_use_finalizer() -> None:
    findings = provider_dispatch_call_sites(Path("src/harness"))
    assert findings == {
        "finalized": EXPECTED_FINALIZED_CALL_SITES,
        "stronger_boundaries": {"discovery_turns.py:run_inspection_turn": "managed_discovery"},
        "bypasses": set(),
    }
```

Add crash tests before/after constitution publication, changed draft after sealing, symlinked draft/target parent, repeated recovery, direct routing judgment receipt sealing, human-resolution result-only enforcement, and a synthetic new `exec_agent` call that makes the structural guard fail.

- [ ] **Step 2: Run integration and ownership tests to verify RED**

```bash
../../.venv/bin/python -m pytest -q \
  tests/unit/test_constitution_publication.py \
  tests/unit/test_spec_step_effects.py tests/unit/test_spec_step_ownership.py \
  tests/integration/test_squad_controller.py \
  tests/kernel/test_squad_executors_journal.py \
  -k 'constitution_publication or provider_call or routing_judgment or managed_discovery' -x
```

Expected: FAIL because CHIEF promotes before sealing and direct controller calls bypass the finalizer.

- [ ] **Step 3: Move CHIEF promotion into the existing publication effect**

Seal only controller-resolved draft/target paths, the draft file identity/content digest, and the provider receipt digest. Re-open through descriptor-safe parents, verify the draft still matches, atomically replace `.echelon/constitution.md`, fsync, and return an idempotent postimage receipt. Extend the existing publication adapter with a tagged union; do not add an effect, cursor, state key, or outbox.

Remove the pre-route `_promote_constitution_draft()` call. Set `constitution_status=exists` only in the final state postimage authorized by the same sealed step.

- [ ] **Step 4: Finalize direct Commander calls**

Replace direct calls to `self._telemetry_provider.exec_agent` for routing judgment and provider-backed human resolution with a controller helper using the registered `result_only` assignment, zero write paths, a unique occurrence ID, and `extend_phase_execution` from Task 4. Preserve judgment prompts, verdicts, routing policy, and telemetry.

Each SAGE review merges the exact optional `proposal` descriptor into the review contract before its one provider call, so the review receipt proves reports and any proposal together. The later Commander decision judgment remains a separate `result_only` occurrence. Managed discovery remains on `run_inspection_turn` and is named in the structural exemption table.

- [ ] **Step 5: Delete transitional publication authorities**

Delete `_MANDATORY_PHASE_OUTPUTS`, `_SAGE_REVIEW_OUTPUTS` as an authority, `_provider_output_guard`, executor-local WHY2/WHY3/ASSESS2 filename selection, filename parsing in `_phase_prompt_metadata`, raw `_exec_agent_with_contract` calls outside the shared dispatch helper, and duplicate provider receipt insertion/stripping branches. Keep domain semantic validators and error reason mapping.

Update `phase1-constitution.md` only to state the already-designed ownership: CHIEF writes the exact run-local draft; the controller promotes it after receipt validation through the sealed spec step.

- [ ] **Step 6: Run the complete focused cutover suite GREEN**

```bash
../../.venv/bin/python -m pytest -q \
  tests/unit/test_provider_artifact_contract.py \
  tests/unit/test_provider_dispatch_finalizer.py \
  tests/unit/test_constitution_publication.py \
  tests/unit/test_ai_cli_backend.py tests/unit/test_squad_provider.py \
  tests/kernel/test_prepared_phase_result.py \
  tests/unit/test_spec_step.py tests/unit/test_spec_step_effects.py \
  tests/unit/test_spec_step_ownership.py tests/unit/test_squad_completion.py \
  tests/kernel/test_phase_graph.py tests/kernel/test_spec_step_state.py \
  tests/kernel/test_squad_executors_journal.py \
  tests/kernel/test_phase3_work_assessment.py \
  tests/kernel/test_phase3_repair_handoff.py \
  tests/unit/test_consensus_routing.py tests/unit/test_kb_proposals.py \
  tests/integration/test_squad_controller.py -x
```

Expected: PASS with no structural bypasses and no legacy manual output authority.

- [ ] **Step 7: Commit**

```bash
git add src/harness/constitution_publication.py src/harness/spec_step.py \
  src/harness/spec_step_effects.py src/harness/squad.py \
  src/harness/squad_executors.py runtime/workflow/phases/phase1-constitution.md \
  tests/unit/test_constitution_publication.py \
  tests/unit/test_spec_step_effects.py tests/unit/test_spec_step_ownership.py \
  tests/integration/test_squad_controller.py \
  tests/kernel/test_squad_executors_journal.py
git commit -m "refactor: complete provider finalization cutover"
```

---

## Final Verification

- [ ] **Run whitespace and stale-authority checks**

```bash
git diff --check "$(cat "$(git rev-parse --git-dir)/last-provider-finalization-base")"..HEAD
! rg -n '_MANDATORY_PHASE_OUTPUTS|_provider_output_guard|ProviderOutputSpec' src/harness
```

Expected: both commands exit zero.

- [ ] **Run the repository unit gate**

```bash
../../.venv/bin/python -m pytest -m unit
```

Expected: PASS with zero failures.

- [ ] **Run the complete repository test suite**

```bash
../../.venv/bin/python -m pytest
```

Expected: PASS with zero failures. Record every unrelated pre-existing failure by exact test name instead of omitting it.

- [ ] **Run installation/dry-run validation for workflow bundle changes**

```bash
bash scripts/bash/dry-run.sh
```

Expected: PASS and the checked-in Prosaic/runtime workflow resolves all provider assignments.

- [ ] **Review the full branch range**

```bash
base=$(cat "$(git rev-parse --git-dir)/last-provider-finalization-base")
git log --oneline "$base"..HEAD
git diff --stat "$base"..HEAD
git diff --check "$base"..HEAD
```

Expected: six implementation commits, the intended files only, and no whitespace errors.
