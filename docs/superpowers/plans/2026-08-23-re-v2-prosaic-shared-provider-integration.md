# RE v2 Prosaic Shared-Provider Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace protocol 2.2's API-only L1 call with the existing Prosaic and shared AI coding provider path while reusing the complete protocol-2.2 execution kernel.

**Architecture:** Protocol 2.3 retains run-manifest schema 2 and extends the existing `cli` executor seam. The inspected `ProsaicCommandArtifact` is pinned through the existing agent-contract hash and object store; one thin `SquadCliBaselineExecutor` adapts `SquadCliProvider` output into the existing capture/certification pipeline. No new provider, authority, graph, storage, budget, ledger, recovery, materialization, or status framework is introduced.

**Tech Stack:** Existing Prosaic loader, `SquadCliProvider`, `AICodingCliProvider`, protocol-2.2 dataclasses/stores/controller, Python 3.11+, pytest.

**Spec:** `docs/superpowers/specs/2026-08-23-re-v2-provider-neutral-execution-design.md`

## Global Constraints

- Every model-backed RE call uses `ProsaicPromptLoader` and `SquadCliProvider`.
- L0 performs no Prosaic inspection and constructs no provider.
- Existing provider adapters remain the sole authority for provider selection and neutral metadata mapping.
- Protocol 2.3 retains manifest schema 2 and protocol-2.2 graph/artifact identities.
- Existing `ObjectStore`, `InstalledAuthorityRegistry`, `ExecutionInputV1`, candidate capture, budget, ledger, recovery, materialization, and status are extended rather than copied.
- No concrete model, provider credential, API transport, or provider-specific mapping is added to RE.
- Protocols 2.0 through 2.2 remain readable; no new 2.2 direct provider dispatch is allowed after 2.3 activation.
- Preserve the unrelated snapshot changes in `src/harness/re_v2/snapshot.py` and `tests/unit/test_re_v2_workspace_snapshot.py`.

## Reuse Guard

Before accepting any production file in this plan, reject it if its responsibility
already belongs to one of these existing components:

| Responsibility | Required existing component |
|---|---|
| Prosaic loading/value | `ProsaicPromptLoader`, `ProsaicCommandArtifact` |
| Provider dispatch/mapping | `SquadCliProvider`, `AICodingCliProvider`, provider adapters |
| Result validation | `EchelonResultContract` |
| Agent authority/storage | `RequestRendererAuthorityV1.agent_contract_hash`, `InstalledAuthorityRegistry`, `ObjectStore` |
| Execution identity/capture | `ExecutionInputV1`, `PreparedExecutionV1`, `Protocol22ExecutionStore` |
| Candidate safety | existing protocol-2.2 candidate root/inventory/commit |
| Accounting | `DispatchReservationV1`, `NormalizedUsageV1`, protocol-2.2 budget replay |
| Retry/recovery | protocol-2.2 controller/events/recovery |
| Acceptance/output | existing certifier/ledger/materialization/status |

The only new production class authorized by this plan is the thin
`SquadCliBaselineExecutor` adapter.

---

### Task 1: Admit protocol 2.3 through schema 2

**Files:**

- Modify: `src/harness/re_v2/protocol_22/model.py`
- Modify: `src/harness/re_v2/model.py`
- Modify: `src/harness/re_v2/run_store.py`
- Modify: `tests/unit/test_re_v2_protocol_22_model.py`
- Modify: `tests/unit/test_re_v2_run_store.py`
- Test: `tests/unit/test_re_v2_model.py`
- Test: `tests/unit/test_re_v2_protocol_compatibility.py`

**Interfaces:**

- Consumes: existing `RunManifestV2` schema-2 representation.
- Produces: schema-2 decoding for `engine_protocol_version` in `{"2.2", "2.3"}`.
- Preserves: byte-identical decoding/encoding of every existing 2.2 manifest.

- [ ] **Step 1: Write the failing protocol-admission test**

Add a test that changes only the protocol literal on a valid schema-2 fixture:

```python
def test_schema_2_manifest_accepts_protocol_23_without_new_fields() -> None:
    raw = valid_run_manifest_v2_dict()
    raw["engine_protocol_version"] = "2.3"

    manifest = RunManifestV2.from_json_dict(raw)

    assert manifest.schema_version == 2
    assert manifest.engine_protocol_version == "2.3"
    assert set(manifest.to_json_dict()) == set(valid_run_manifest_v2_dict())
```

Add a run-store round-trip test for the `(2, "2.3")` pair and retain the exact
existing 2.2 digest assertions. Update the supported-protocol assertion so 2.3
is readable while `RE_V2_PROTOCOL` remains 2.2 until Task 5 activates new-run
creation.

- [ ] **Step 2: Verify RED**

Run:

```bash
pytest tests/unit/test_re_v2_protocol_22_model.py tests/unit/test_re_v2_model.py \
  tests/unit/test_re_v2_run_store.py -q
```

Expected: FAIL because `RunManifestV2` and `_decode_manifest` accept only 2.2.

- [ ] **Step 3: Generalize the existing literal checks only**

Change the manifest annotation and validation to:

```python
engine_protocol_version: Literal["2.2", "2.3"]

one_of(
    self.engine_protocol_version,
    {"2.2", "2.3"},
    "RunManifestV2.engine_protocol_version",
)
```

In `run_store._decode_manifest`, route both `(2, "2.2")` and `(2, "2.3")` to
`RunManifestV2.from_json_dict`. Extend `_validate_supported_manifest` with the
same closed set. Add 2.3 to `RE_V2_SUPPORTED_PROTOCOLS` without changing the
active `RE_V2_PROTOCOL` constant. Add no manifest class or field.

- [ ] **Step 4: Verify schema compatibility**

Run:

```bash
pytest tests/unit/test_re_v2_protocol_22_model.py tests/unit/test_re_v2_model.py \
  tests/unit/test_re_v2_run_store.py \
  tests/unit/test_re_v2_protocol_compatibility.py -q
```

Expected: PASS, including all unchanged protocol-2.2 digest tests.

- [ ] **Step 5: Commit**

```bash
git add src/harness/re_v2/protocol_22/model.py src/harness/re_v2/model.py \
  src/harness/re_v2/run_store.py tests/unit/test_re_v2_protocol_22_model.py \
  tests/unit/test_re_v2_model.py tests/unit/test_re_v2_run_store.py \
  docs/superpowers/plans/2026-08-23-re-v2-prosaic-shared-provider-integration.md
git commit -m "feat(re-v2): admit protocol 2.3 in schema 2"
```

### Task 2: Pin the existing inspected Prosaic artifact

**Files:**

- Modify: `src/echelon/cli.py`
- Modify: `src/harness/re_v2/protocol_22/provider.py`
- Modify: `tests/unit/test_cli_re_v2_protocol_22.py`
- Modify: `tests/unit/test_re_v2_protocol_22_provider.py`

**Interfaces:**

- Produces: `canonical_prosaic_agent_bytes(artifact: ProsaicCommandArtifact) -> bytes`.
- Produces: `decode_prosaic_agent_bytes(payload: bytes) -> ProsaicCommandArtifact`.
- Reuses: existing registry `agent_contracts` mapping and existing object-store publication.
- Keeps public creation on protocol 2.2 until Task 5; an internal schema-2
  preparation argument lets this task exercise the future 2.3 authority branch.

- [ ] **Step 1: Write failing canonical-contract tests**

Add provider tests:

```python
def test_prosaic_agent_contract_round_trips_body_and_frontmatter_separately() -> None:
    artifact = ProsaicCommandArtifact(
        body="Baseliner body.\n",
        frontmatter={
            "name": "echelon.re-baseliner",
            "execution": "agent",
            "tools": "write",
            "model_tier": "strong",
            "effort": "high",
        },
    )

    payload = canonical_prosaic_agent_bytes(artifact)

    assert decode_prosaic_agent_bytes(payload) == artifact
    assert not payload.startswith(b"---")
```

Add CLI creation tests that monkeypatch
`ProsaicPromptLoader.load_subagent`: inventory makes zero calls; baseline makes
one call and fails before run publication when it returns `None`. A successful
baseline preparation must place the canonical inspected artifact bytes under
the exact existing renderer agent-contract hash. Exercise these through an
explicit internal `engine_protocol_version="2.3"`; do not activate public 2.3
creation in this task.

- [ ] **Step 2: Verify RED**

Run:

```bash
pytest tests/unit/test_re_v2_protocol_22_provider.py tests/unit/test_cli_re_v2_protocol_22.py -q
```

Expected: FAIL because canonical inspected-agent helpers and 2.3 creation loading
do not exist.

- [ ] **Step 3: Implement canonical serialization with existing values**

In `provider.py`, add functions—not a wrapper class:

```python
def canonical_prosaic_agent_bytes(artifact: ProsaicCommandArtifact) -> bytes:
    if not isinstance(artifact, ProsaicCommandArtifact):
        raise Protocol22ProviderError("agent contract requires inspected Prosaic artifact")
    return canonical_json_bytes(
        {"body": artifact.body, "frontmatter": artifact.frontmatter}
    )


def decode_prosaic_agent_bytes(payload: bytes) -> ProsaicCommandArtifact:
    raw = load_canonical_object(payload, lambda value: value)
    exact = exact_object(raw, {"body", "frontmatter"}, "Prosaic agent contract")
    body = exact["body"]
    frontmatter = exact["frontmatter"]
    if not isinstance(body, str) or not body or not isinstance(frontmatter, dict):
        raise Protocol22ProviderError("Prosaic agent contract is incomplete")
    return ProsaicCommandArtifact(frontmatter=dict(frontmatter), body=body)
```

Give `_prepare_re_v22_creation` an internal protocol-version argument whose
default remains the active `RE_V2_PROTOCOL` (still 2.2). For protocol-2.3
baseline preparation, call the existing loader and give these canonical bytes
to the existing registry builder. For inventory, pass no agent bytes and do not
construct a loader. Factor the current registry construction so both the legacy
raw bytes and inspected bytes enter the same builder; do not create a second
registry model. Keep `_re_v22_agent_bytes` exclusively for legacy 2.2 reading.

- [ ] **Step 4: Verify the L0/L1 authority boundary**

Run:

```bash
pytest tests/unit/test_re_v2_protocol_22_provider.py tests/unit/test_cli_re_v2_protocol_22.py tests/unit/test_prosaic_prompt_loader.py -q
```

Expected: PASS; inventory observes zero loader/provider calls and baseline pins
the exact inspected artifact.

- [ ] **Step 5: Commit**

```bash
git add src/echelon/cli.py src/harness/re_v2/protocol_22/provider.py \
  tests/unit/test_cli_re_v2_protocol_22.py tests/unit/test_re_v2_protocol_22_provider.py
git commit -m "feat(re-v2): pin inspected Prosaic baseliner"
```

### Task 3: Add the thin shared-provider executor adapter

**Files:**

- Create: `src/harness/re_v2/protocol_22/cli_provider.py`
- Create: `tests/unit/test_re_v2_protocol_22_cli_provider.py`
- Modify: `src/harness/re_v2/protocol_22/executors.py`
- Modify: `src/harness/re_v2/protocol_22/provider.py`
- Modify: `tests/unit/test_re_v2_protocol_22_executors.py`
- Modify: `tests/unit/test_re_v2_protocol_22_provider.py`
- Test: `tests/unit/test_squad_provider.py`

**Interfaces:**

- Produces: `SquadCliBaselineExecutor.execute(...) -> RawExecutionResultV1`.
- Reuses: `SquadCliProvider.exec_agent`, `EchelonResultContract`,
  `DispatchReservationV1`, `RawExecutionResultV1`, and `NormalizedUsageV1`.
- Produces adapter ID: `shared-ai-cli-baseline-v1` using existing `execution_mode="cli"`.

- [ ] **Step 1: Write failing adapter contract tests**

Use a provider spy exposing the existing `exec_agent` signature and assert:

```python
result = adapter.execute(
    execution_input,
    agent_bytes,
    context_bytes,
    response_schema_bytes,
    reservation,
    candidate_root,
    deadline,
)

assert provider.calls[0]["project_root"] == str(candidate_root)
assert provider.calls[0]["prompt_metadata"] == inspected_frontmatter
assert provider.calls[0]["allow_result_repair"] is False
assert provider.calls[0]["strict_result_envelope"] is True
assert provider.calls[0]["result_contract"] == EchelonResultContract(
    allowed_state_update_keys=frozenset(),
    allowed_verdicts=frozenset({"DONE"}),
    unexpected_state_updates="reject",
)
assert result.outcome == "candidate_ready"
assert result.provider_name == "codex"
assert result.resolved_model_revision == "gpt-5.6-codex"
```

Also test timeout, nonzero exit, malformed shared result, missing/extra candidate
file, unavailable usage, and provider-reported model telemetry. Do not test model
tier translation here; existing adapter tests own that behavior.

- [ ] **Step 2: Verify RED**

Run:

```bash
pytest tests/unit/test_re_v2_protocol_22_cli_provider.py -q
```

Expected: collection ERROR because the thin adapter does not exist.

- [ ] **Step 3: Implement only the adapter**

The production file may import only existing shared/provider and protocol values:

```python
from harness.echelon_result_schema import EchelonResultContract
from harness.squad_provider import SquadCliProvider
from .provider import DispatchReservationV1, RawExecutionResultV1
```

It must not import a provider backend, networking module, credential helper, or
concrete model map. Decode the pinned artifact, render the existing context and
schema instructions, invoke `exec_agent`, and normalize its result into
`RawExecutionResultV1`. Carry `SquadAgentResult.provider_name` and `model_name`
on that existing raw-result surface. Convert token observations to the existing
`NormalizedUsageV1` value and encode it canonically in the existing usage blob
slot; do not fabricate an OpenAI response shape. Unknown/incomplete token
details remain unavailable or untrusted so existing replay charges the
reservation.

Add `shared-ai-cli-baseline-v1` to the existing executor registry. For CLI mode,
require provider ID, renderer, verifier, calculator, accounting, and limits;
require `api_transport is None`; and require `model`, `generation`, and request
tokenizer to be null because Prosaic/provider adapters own those choices.

- [ ] **Step 4: Verify adapter and existing provider behavior**

Run:

```bash
pytest tests/unit/test_re_v2_protocol_22_cli_provider.py \
  tests/unit/test_re_v2_protocol_22_executors.py \
  tests/unit/test_re_v2_protocol_22_provider.py \
  tests/unit/test_squad_provider.py tests/unit/test_ai_cli_backend.py -q
```

Expected: PASS without changing existing provider metadata tests.

- [ ] **Step 5: Commit**

```bash
git add src/harness/re_v2/protocol_22/cli_provider.py \
  src/harness/re_v2/protocol_22/executors.py \
  src/harness/re_v2/protocol_22/provider.py \
  tests/unit/test_re_v2_protocol_22_cli_provider.py \
  tests/unit/test_re_v2_protocol_22_executors.py \
  tests/unit/test_re_v2_protocol_22_provider.py
git commit -m "feat(re-v2): adapt shared provider for compact baseline"
```

### Task 4: Generalize the existing provider-backed execution branch

**Files:**

- Modify: `src/harness/re_v2/protocol_22/model.py`
- Modify: `src/harness/re_v2/protocol_22/execution.py`
- Modify: `src/harness/re_v2/protocol_22/controller.py`
- Modify: `src/harness/re_v2/protocol_22/recovery.py`
- Modify: `tests/unit/test_re_v2_protocol_22_execution.py`
- Modify: `tests/unit/test_re_v2_protocol_22_controller.py`
- Modify: `tests/unit/test_re_v2_protocol_22_recovery.py`
- Modify: `tests/integration/test_re_v2_protocol_22_recovery.py`

**Interfaces:**

- Reuses: existing `ProviderExecutionDependenciesV1`, `ExecutionInputV1`,
  `PreparedExecutionV1`, `ExecutionCaptureV1`, and recovery states.
- Generalizes: provider-backed execution from `api` to `api | cli` without
  adding durable schema fields.

- [ ] **Step 1: Write failing CLI-branch tests beside API tests**

Clone no test fixture wholesale. Parameterize existing provider-path tests by
execution mode and assert:

```python
assert prepared.execution_input.agent_contract_hash is not None
assert prepared.execution_input.context_bundle_hash is not None
assert (
    prepared.execution_input.provider_request_envelope_hash is None
    if mode == "cli"
    else prepared.execution_input.provider_request_envelope_hash is not None
)
assert committed.closure.capture.execution_mode == mode
```

For CLI mode also assert that capture provider/model fields equal the shared
provider observations, normalized usage survives recovery, and certification
loads the context object named by `ExecutionInputV1.context_bundle_hash` without
a `ProviderRequestEnvelopeV1`.

Recovery tests must prove a started CLI dispatch is never reissued and an
abandoned CLI dispatch uses the existing full-reservation charge/retry path.

- [ ] **Step 2: Verify RED**

Run:

```bash
pytest tests/unit/test_re_v2_protocol_22_execution.py tests/unit/test_re_v2_protocol_22_controller.py tests/unit/test_re_v2_protocol_22_recovery.py -q
```

Expected: FAIL at existing API-only validation branches.

- [ ] **Step 3: Generalize existing branches without parallel classes**

Make these closed changes:

- `ExecutionCaptureV1.execution_mode` accepts `"in_process" | "api" | "cli"`.
- `ExecutionInputV1` accepts a provider branch with agent/context hashes and a
  null API-envelope hash only when the referenced executor is CLI; external
  validation retains that cross-object check.
- `PreparedExecutionV1` determines provider-backed status from agent/context
  hashes rather than envelope presence.
- `_prepare_provider` retains API rendering and uses the CLI adapter's
  conservative `DispatchReservationV1` for CLI.
- `capture_provider_result` records the executor's actual provider-backed mode
  and, for CLI, the provider/model values observed by `SquadCliProvider`.
- controller execution selects the already-registered executor by adapter ID and
  passes existing dependency bytes to CLI mode.
- candidate certification reads pinned context bytes by
  `execution_input.context_bundle_hash`; API mode may use the same path instead
  of treating its envelope as a second context authority.
- observation/recovery decodes API usage with the existing OpenAI normalizer and
  CLI usage as the canonically stored existing `NormalizedUsageV1` value.
- recovery/status replace `== "api"` assumptions with the closed provider-backed
  set `{"api", "cli"}` where semantics are shared.

Do not create protocol-2.3 copies of these models or stores.

- [ ] **Step 4: Verify execution, budget, and recovery**

Run:

```bash
pytest tests/unit/test_re_v2_protocol_22_execution.py \
  tests/unit/test_re_v2_protocol_22_controller.py \
  tests/unit/test_re_v2_protocol_22_budget.py \
  tests/unit/test_re_v2_protocol_22_recovery.py \
  tests/integration/test_re_v2_protocol_22_recovery.py -q
```

Expected: PASS for unchanged API fixtures and new CLI fixtures.

- [ ] **Step 5: Commit**

```bash
git add src/harness/re_v2/protocol_22/model.py \
  src/harness/re_v2/protocol_22/execution.py \
  src/harness/re_v2/protocol_22/controller.py \
  src/harness/re_v2/protocol_22/recovery.py \
  tests/unit/test_re_v2_protocol_22_execution.py \
  tests/unit/test_re_v2_protocol_22_controller.py \
  tests/unit/test_re_v2_protocol_22_recovery.py \
  tests/integration/test_re_v2_protocol_22_recovery.py
git commit -m "feat(re-v2): run provider-backed work through CLI mode"
```

### Task 5: Activate protocol 2.3 and align the baseliner contract

**Files:**

- Modify: `prosaic/subagents/echelon.re-baseliner.md`
- Modify: `src/echelon/cli.py`
- Modify: `src/harness/re_v2/protocol_22/status.py`
- Modify: `tests/unit/test_prosaic_agent_authoring.py`
- Modify: `tests/unit/test_cli_re_v2_protocol_22.py`
- Modify: `tests/unit/test_re_v2_protocol_22_status.py`
- Test: `tests/integration/test_re_v2_v1_isolation.py`

**Interfaces:**

- New runs: protocol 2.3, existing schema 2.
- L1 result: existing shared `DONE` verdict plus empty state updates.
- Legacy 2.2: readable/adoptable; no new direct provider dispatch.

- [ ] **Step 1: Write failing activation and agent-contract tests**

Assert the baseliner says:

```markdown
ALWAYS use write authority only to write exactly `baseline.json` in the supplied candidate root.
NEVER perform filesystem discovery, read the live source workspace, or write any other path.
```

Assert its final output block is:

```yaml
echelon_result:
  verdict: DONE
  state_updates: {}
```

CLI tests assert new baseline and inventory manifests use protocol 2.3/schema 2,
inventory constructs no provider, and continuation of unresolved 2.2 work emits
the migration diagnostic before any provider call.

- [ ] **Step 2: Verify RED**

Run:

```bash
pytest tests/unit/test_prosaic_agent_authoring.py tests/unit/test_cli_re_v2_protocol_22.py tests/unit/test_re_v2_protocol_22_status.py -q
```

Expected: FAIL because the old agent/result contract and 2.2 creation path remain active.

- [ ] **Step 3: Activate the existing integration path**

- Select protocol 2.3/schema 2 for new v2 runs.
- Resolve compact-baseline entries to `shared-ai-cli-baseline-v1` using the
  normally configured provider.
- Construct `SquadCliProvider` through the existing CLI provider factory only
  when a CLI L1 entry is dispatchable.
- Keep inventory provider-free.
- Block new direct 2.2 dispatch while retaining read/status/capture-adoption paths.
- Revise the Prosaic prose and result block exactly as tested.
- Extend existing status lines to show the provider/model already reported by
  `SquadAgentResult`; add no new telemetry store.

- [ ] **Step 4: Run the complete offline gate**

Run:

```bash
pytest tests/unit/test_prosaic_agent_authoring.py \
  tests/unit/test_cli_re_v2_protocol_22.py \
  tests/unit/test_re_v2_protocol_22_status.py \
  tests/unit/test_re_v2_protocol_compatibility.py \
  tests/integration/test_re_v2_v1_isolation.py -q
```

Expected: PASS with unchanged protocol-2.0/2.1/2.2 compatibility fixtures.

- [ ] **Step 5: Commit**

```bash
git add prosaic/subagents/echelon.re-baseliner.md src/echelon/cli.py \
  src/harness/re_v2/protocol_22/status.py \
  tests/unit/test_prosaic_agent_authoring.py \
  tests/unit/test_cli_re_v2_protocol_22.py \
  tests/unit/test_re_v2_protocol_22_status.py
git commit -m "feat(re-v2): activate Prosaic shared-provider baseline"
```

### Task 6: Prove real provider execution without RE-specific provider code

**Files:**

- Modify: `tests/integration/test_re_v2_protocol_22_live.py`
- Modify: `tests/support/re_v2_layered_workspace.py`
- Modify: `CHANGELOG.md`

**Interfaces:**

- Consumes: installed Echelon/Prosaic bundle and configured Codex provider.
- Produces: one real clean-workspace L0+L1 run plus one provider-neutral fixture.

- [ ] **Step 1: Add an installed Codex pilot assertion**

The pilot must assert from durable telemetry, not terminal prose:

```python
assert manifest.engine_protocol_version == "2.3"
assert provider_observation["provider_name"] == "codex"
assert provider_observation["raw_result_contract_status"] == "valid"
assert status.terminal_banner == "L1 COMPACT BASELINE COMPLETE"
```

Also assert the live source Git tree is unchanged and every accepted candidate
contains only `baseline.json`.

- [ ] **Step 2: Run the offline provider fixture first**

Run:

```bash
pytest tests/integration/test_re_v2_protocol_22_live.py -q
```

Expected: PASS without network or provider credentials.

- [ ] **Step 3: Install and run the real Codex pilot**

Run:

```bash
bash scripts/install.sh
pytest tests/integration/test_re_v2_protocol_22_live.py -m live -v
```

Expected: the configured Codex provider completes L1 through
`SquadCliProvider`; no OpenAI API credential is required.

- [ ] **Step 4: Run the full RE v2 regression gate**

Run:

```bash
pytest tests/unit/test_re_v2_protocol_22_*.py \
  tests/integration/test_re_v2_protocol_22_*.py \
  tests/unit/test_re_v2_protocol_compatibility.py \
  tests/integration/test_re_v2_v1_isolation.py -q
```

Expected: PASS. Inspect `git diff --check` and confirm no new provider mapping,
authority store, budget, recovery, or status package exists.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_re_v2_protocol_22_live.py \
  tests/support/re_v2_layered_workspace.py CHANGELOG.md
git commit -m "test(re-v2): prove shared-provider baseline execution"
```

## Checkpoints

- After Task 1: protocol label admitted with zero runtime behavior change.
- After Task 2: inspected Prosaic bytes are pinned through existing authority.
- After Task 3: thin adapter works in isolation; shared provider code is unchanged.
- After Task 4: existing execution/recovery kernel supports CLI fixtures.
- After Task 5: new runs use protocol 2.3; legacy protocols remain readable.
- After Task 6: real Codex telemetry proves end-to-end shared-provider execution.

Stop for review after every task. Do not batch these commits.
