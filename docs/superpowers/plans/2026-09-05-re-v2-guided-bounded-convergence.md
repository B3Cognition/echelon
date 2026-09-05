# RE v2 Guided and Bounded Convergence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:test-driven-development` for every task and `superpowers:verification-before-completion` before claiming completion. Execute tasks in order; do not combine commits or skip the stated RED checks.

**Goal:** Make L3 operator guidance provider-effective, explain semantic plateaus, and add an explicit one-successor Banzai path that can finish a valid remaining plateau as authenticated `complete_with_debt` without weakening structural or authority checks.

**Architecture:** Preserve immutable L3 history and the single public RE protocol presentation. Typed guidance is projected into every post-freeze provider context. A deterministic convergence coordinator creates at most one guided successor and either returns full completion or records exact residual debt. Protocol-2.7 synthesis and protocol-2.8 L4 consume partial L3 only by binding that debt acceptance hash.

**Tech Stack:** Python 3.11+, frozen dataclasses, canonical JSON/content digests, Typer, pytest, existing RE v2 ledgers and run-store primitives.

**Spec:** `docs/superpowers/specs/2026-09-05-re-v2-guided-bounded-convergence-design.md`

## Global constraints

- Keep one user-visible RE version/protocol presentation; internal module names stay internal.
- Preserve immutable run history. `complete_with_debt` is derived; the semantic child stays `blocked_plateau`.
- Banzai creates/reuses exactly one paid successor and never raises any budget or retry limit.
- Accept all semantic finding classes as debt only after a valid plateau. Never accept incomplete audit/root authority, dirty snapshots, indeterminate provider work, resource exhaustion, or schema/contract failures.
- Never put raw guidance, finding prose, evidence, or secrets in telemetry or suggested commands.
- Preserve old `SemanticContextV1` bytes and identity when guidance is absent.
- Preserve `/Users/michalbachorik/work/echelon/runs/`, all OptaSearch stashes, and clean source repositories.
- Commit the already-deployed zero-domain/compatibility fix separately before feature work.
- Do not start OptaSearch L4 without a new explicit request.

---

### Task 0: Stabilize and commit the existing L3 recovery fix

**Files:**

- Modify: `src/echelon/cli.py`
- Modify: `src/harness/re_v2/protocol_25/artifacts.py`
- Create: `src/harness/re_v2/protocol_25/compatibility.py`
- Modify: `tests/integration/test_re_v2_protocol_25_recovery.py`
- Create: `tests/unit/test_re_v2_protocol_25_compatibility.py`
- Preserve untracked: `runs/`

**Step 1: Verify isolation and focused behavior**

Run:

```bash
git diff --check -- src/echelon/cli.py src/harness/re_v2/protocol_25/artifacts.py src/harness/re_v2/protocol_25/compatibility.py tests/integration/test_re_v2_protocol_25_recovery.py tests/unit/test_re_v2_protocol_25_compatibility.py
pytest -q tests/unit/test_re_v2_protocol_25_artifacts.py tests/unit/test_re_v2_protocol_25_compatibility.py tests/integration/test_re_v2_protocol_25_recovery.py
```

Expected: PASS, including zero-domain source-root finalization and exact legacy/current implementation-digest compatibility. `runs/` remains untouched.

**Step 2: Commit only these five paths**

```bash
git add src/echelon/cli.py src/harness/re_v2/protocol_25/artifacts.py src/harness/re_v2/protocol_25/compatibility.py tests/integration/test_re_v2_protocol_25_recovery.py tests/unit/test_re_v2_protocol_25_compatibility.py
git commit -m "fix(re): preserve valid L3 recovery authority"
```

Expected: `git status --short` shows only `?? runs/`.

---

### Task 1: Introduce typed immutable guidance authority

**Files:**

- Create: `src/harness/re_v2/protocol_25/guidance.py`
- Modify: `src/harness/re_v2/protocol_25/lifecycle.py`
- Modify: `src/harness/re_v2/protocol_25/inputs.py`
- Create: `tests/unit/test_re_v2_protocol_25_guidance.py`
- Modify: `tests/unit/test_re_v2_protocol_25_lifecycle.py`
- Modify: `tests/unit/test_re_v2_protocol_25_inputs.py`

**Interfaces:**

```python
GuidanceKindV1 = Literal["custom", "recommended", "banzai"]

@dataclass(frozen=True)
class GuidancePolicyV1:
    kind: GuidanceKindV1
    answer: str
    accept_residual_debt: bool
    automatic_successor_limit: int
    automation_root_manifest_hash: str | None
    successor_index: int

@dataclass(frozen=True)
class GuidanceDirectiveV1:
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

RECOMMENDED_GUIDANCE_TEXT = (
    "Use only accepted bounded authority. Close a finding only when evidence "
    "supports correction or qualification; otherwise preserve it explicitly "
    "as unresolved. Never invent evidence or suppress a finding to converge."
)
```

**Step 1: Write RED tests**

Add tests named `test_custom_policy_cannot_enable_automation_or_debt`,
`test_recommended_policy_is_fixed_and_non_automatic`,
`test_banzai_policy_binds_root_and_exactly_one_successor`,
`test_guidance_directive_round_trips_exactly`,
`test_legacy_guidance_decodes_as_non_automatic_custom`, and
`test_guidance_rejects_unknown_fields_and_unsorted_authority`.

Run `pytest -q tests/unit/test_re_v2_protocol_25_guidance.py`.

Expected RED: import failure for `harness.re_v2.protocol_25.guidance`.

**Step 2: Implement strict schemas**

Implement exact-field `to_json_dict`/`from_json_dict`, NFC and 8-KiB normalization, and sorted-unique digest/ID validation. Enforce:

```python
if kind == "custom":
    require(not accept_residual_debt)
    require((automatic_successor_limit, successor_index) == (0, 0))
    require(automation_root_manifest_hash is None)
elif kind == "recommended":
    require(answer == RECOMMENDED_GUIDANCE_TEXT)
    require(not accept_residual_debt)
    require((automatic_successor_limit, successor_index) == (0, 0))
else:
    require(answer == RECOMMENDED_GUIDANCE_TEXT)
    require(accept_residual_debt)
    require((automatic_successor_limit, successor_index) == (1, 1))
    require(automation_root_manifest_hash is not None)
```

Export `custom_guidance_policy`, `recommended_guidance_policy`, `banzai_guidance_policy`, `build_guidance_directive`, and `load_guidance_directive`.

Legacy decoding accepts only the exact old full directive field set. It retains all parent/candidate/target/epoch/closure/finding bindings and adds disabled custom-policy fields; it must not accept an unbound `{"answer": "text only"}` object.

**Step 3: Replace untyped lifecycle/input handling**

Replace the `answer: str` parameter on `prepare_guided_successor` and
`_prepare_protocol_25_l3_child` with
`guidance_policy: GuidancePolicyV1 | None`; require `None` for new audit epochs
and a concrete policy for guided successors.

Build the directive from authenticated parent state, store canonical bytes at `human-guidance.json`, and make `_load_guidance` return `GuidanceDirectiveV1` after catalog/hash validation.

**Step 4: GREEN and commit**

```bash
pytest -q tests/unit/test_re_v2_protocol_25_guidance.py tests/unit/test_re_v2_protocol_25_lifecycle.py tests/unit/test_re_v2_protocol_25_inputs.py
git add src/harness/re_v2/protocol_25/guidance.py src/harness/re_v2/protocol_25/lifecycle.py src/harness/re_v2/protocol_25/inputs.py tests/unit/test_re_v2_protocol_25_guidance.py tests/unit/test_re_v2_protocol_25_lifecycle.py tests/unit/test_re_v2_protocol_25_inputs.py
git commit -m "feat(re): type immutable operator guidance"
```

---

### Task 2: Project guidance into every post-freeze provider request

**Files:**

- Modify: `src/harness/re_v2/protocol_25/runtime.py`
- Modify: `src/harness/re_v2/protocol_25/recovery.py`
- Modify: `src/harness/re_v2/protocol_25/cli_provider.py`
- Modify: `tests/unit/test_re_v2_protocol_25_runtime.py`
- Modify: `tests/unit/test_re_v2_protocol_25_cli_provider.py`
- Modify: `tests/integration/test_re_v2_protocol_25_recovery.py`

**Interface:**

```python
@dataclass(frozen=True)
class GuidanceProjectionV1:
    directive_hash: str
    directive: GuidanceDirectiveV1

```

Add `operator_guidance: GuidanceProjectionV1 | None = None` to the existing
`SemanticContextV1` dataclass without changing the order or encoding of its
existing fields.

When guidance is `None`, omit the JSON key. The decoder accepts exactly the legacy field set or that set plus `operator_guidance`.

**Step 1: Write RED tests**

Add tests that prove an unguided context retains its exact old bytes/identity, a guided context carries exact text/hash, tampering fails, and `AUDIT_EPOCH_TARGET` rejects guidance. Run:

```bash
pytest -q tests/unit/test_re_v2_protocol_25_runtime.py -k guidance
```

Expected RED: no `operator_guidance` field.

**Step 2: Implement validation and all three projections**

Validate `content_digest(directive.to_json_dict()) == directive_hash == manifest guidance hash` before size enforcement and provider reservation. Load once from `ValidatedProtocol25Inputs`; pass the same projection into `SEMANTIC_RESOLUTION`, `CLOSURE_RECHECK`, and `SOURCE_COMPOSITION_GUARD` context builders. A guided manifest with missing/invalid guidance fails before provider calls.

**Step 3: Render visible guidance**

In `_render_semantic_prompt`, add:

```text
Operator guidance (authenticated; obey within the bounded authority below)
<normalized directive answer>
```

The canonical context remains authoritative. Do not expose the answer in telemetry/errors.

**Step 4: GREEN and commit**

```bash
pytest -q tests/unit/test_re_v2_protocol_25_runtime.py tests/unit/test_re_v2_protocol_25_cli_provider.py tests/integration/test_re_v2_protocol_25_recovery.py
git add src/harness/re_v2/protocol_25/runtime.py src/harness/re_v2/protocol_25/recovery.py src/harness/re_v2/protocol_25/cli_provider.py tests/unit/test_re_v2_protocol_25_runtime.py tests/unit/test_re_v2_protocol_25_cli_provider.py tests/integration/test_re_v2_protocol_25_recovery.py
git commit -m "feat(re): project operator guidance into L3 requests"
```

---

### Task 3: Derive an actionable deterministic plateau summary

**Files:**

- Create: `src/harness/re_v2/protocol_25/guidance_status.py`
- Modify: `src/harness/re_v2/protocol_25/status.py`
- Modify: `src/echelon/re_ui.py`
- Create: `tests/unit/test_re_v2_protocol_25_guidance_status.py`
- Modify: `tests/unit/test_re_v2_protocol_25_status.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class GuidanceActionV1:
    action_id: Literal["recommended", "banzai", "custom"]
    command: str
    enabled: bool

@dataclass(frozen=True)
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
```

**Step 1: Write RED tests**

Test exact class/source counts, stable ordering, incomplete audit/root ineligibility, and an adversarial provider-authored finding title that never appears in output or commands. Fixed commands are:

```python
RECOMMENDED_COMMAND = "echelon re resume --recommended"
BANZAI_COMMAND = "echelon re resume --banzai"
CUSTOM_COMMAND = 'echelon re resume "<your guidance>"'
```

Run `pytest -q tests/unit/test_re_v2_protocol_25_guidance_status.py`.

Expected RED: missing module.

**Step 2: Implement pure derivation and UI routing**

Use only authenticated findings, closure receipts, selected targets, roots, and terminal state. Banzai is eligible only for `blocked_plateau` with every selected audit accepted plus frozen epoch, final closure root, and all selected roots. Authenticated `blocked_incomplete` may offer recommended/custom guidance, but never Banzai. Replace the generic status action with grouped counts and typed JSON. Resource, provider, structural, and audit-target-incomplete states must not show Banzai.

**Step 3: GREEN and commit**

```bash
pytest -q tests/unit/test_re_v2_protocol_25_guidance_status.py tests/unit/test_re_v2_protocol_25_status.py
git add src/harness/re_v2/protocol_25/guidance_status.py src/harness/re_v2/protocol_25/status.py src/echelon/re_ui.py tests/unit/test_re_v2_protocol_25_guidance_status.py tests/unit/test_re_v2_protocol_25_status.py
git commit -m "feat(re): explain semantic plateaus"
```

---

### Task 4: Add recommended and Banzai resume syntax

**Files:**

- Modify: `src/echelon/cli_app.py`
- Modify: `src/echelon/cli.py`
- Modify: `tests/unit/test_cli_typer_app.py`
- Modify: `tests/unit/test_cli_re_v2_protocol_25.py`
- Modify: `tests/integration/test_re_v2_protocol_25_cli.py`

**Interface:**

```python
@dataclass(frozen=True)
class _ReResumeOptions:
    guidance: str | None
    recommended: bool
    banzai: bool
    token_limit: int | None
    time_limit_minutes: int | None
    semantic_token_limit: int | None
    semantic_time_limit_minutes: int | None
```

Exactly one of guidance, recommended, or Banzai must be selected.

**Step 1: Write RED help/exclusivity tests**

The following three parse:

```text
echelon re resume "decision"
echelon re resume --recommended
echelon re resume --banzai
```

Missing mode, positional plus flag, and both flags exit 2 with copyable usage. Help states Banzai uses one successor and may finish with documented debt. Run:

```bash
pytest -q tests/unit/test_cli_typer_app.py -k re_resume tests/unit/test_cli_re_v2_protocol_25.py -k resume
```

Expected RED: required positional answer/unrecognized flags.

**Step 2: Implement one parser**

Make the Typer answer optional; add `--recommended`, `--banzai`, and the semantic budget flags already supported by continue. Parse once, validate mutual exclusion, and convert to one `GuidancePolicyV1`. Preserve v1 answer-only behavior and reject the new modes for v1 directly.

Pass the policy to `_run_re_v25_resume`. Identical policies over identical blocked authority must resolve the same request ID and child.

**Step 3: GREEN and commit**

```bash
pytest -q tests/unit/test_cli_typer_app.py tests/unit/test_cli_re_v2_protocol_25.py tests/integration/test_re_v2_protocol_25_cli.py
git add src/echelon/cli_app.py src/echelon/cli.py tests/unit/test_cli_typer_app.py tests/unit/test_cli_re_v2_protocol_25.py tests/integration/test_re_v2_protocol_25_cli.py
git commit -m "feat(re): add recommended and banzai resume modes"
```

---

### Task 5: Record exact residual-debt acceptance for v2 L3

**Files:**

- Create: `src/harness/re_v2/protocol_25/debt.py`
- Modify: `src/harness/re_v2/protocol_25/status.py`
- Modify: `src/echelon/cli.py`
- Modify: `src/echelon/cli_app.py`
- Create: `tests/unit/test_re_v2_protocol_25_debt.py`
- Modify: `tests/integration/test_re_v2_protocol_25_cli.py`

**Interface:**

```python
@dataclass(frozen=True)
class DebtGroupV1:
    source_id: str
    finding_class: str
    finding_ids: tuple[str, ...]

@dataclass(frozen=True)
class ResidualDebtAcceptanceV1:
    schema_version: Literal[1]
    run_manifest_hash: str
    terminal_event_hash: str
    audit_epoch_id: str
    closure_root_hash: str
    source_root_hashes: tuple[tuple[str, str], ...]
    unresolved_by_source_and_class: tuple[DebtGroupV1, ...]
    deferred_observation_ids: tuple[str, ...]
    guidance_directive_hash: str
    acceptance_policy_id: Literal["re-v2-banzai-residual-debt-v1"]
    source_snapshot_id: str
    selection_id: str
    operation_id: str

def finalize_protocol_25_debt(
    *, project_root: Path, run_dir: Path, require_banzai: bool
) -> ResidualDebtAcceptanceV1:
    return validate_or_create_residual_debt_acceptance(
        project_root=project_root,
        run_dir=run_dir,
        require_banzai=require_banzai,
    )
```

**Step 1: Write RED eligibility/idempotency tests**

Test a valid plateau and repeat, plus rejection for missing audit target, epoch, closure root, selected source root, dirty/changed source, active/indeterminate provider operation, resource/context/schema/authority failure, non-Banzai guidance, altered unresolved set, and altered persisted acceptance. Run `pytest -q tests/unit/test_re_v2_protocol_25_debt.py`.

Expected RED: missing module.

**Step 2: Implement fail-closed reconstruction and atomic persistence**

Reconstruct from ledger/object authority, not status JSON. Reuse clean-workspace and no-follow/atomic run-store helpers. Derive the operation from all authority:

```python
operation_id = content_digest({
    "kind": "re-v2-residual-debt-acceptance-v1",
    "run_manifest_hash": run_manifest_hash,
    "terminal_event_hash": terminal_event_hash,
    "guidance_directive_hash": guidance_hash,
    "unresolved_finding_ids": unresolved_ids,
})
```

Store canonical content in the v2 authority store and an atomic `inputs/residual-debt-acceptance.json` pointer. Repeats validate and return the existing record; mismatches never overwrite it.

**Step 3: Route v2 finalize and derived status**

Route `echelon re finalize [run] --allow-partial` to this implementation for v2 L3; keep `re_finalization.py` for v1. Manual finalization requires existing guidance that explicitly authorizes debt; it may not manufacture Banzai authority.

A valid record derives:

```text
L3 COMPLETE WITH DEBT
semantic child: blocked_plateau
accepted residual findings: <count>
quality: partial
```

JSON includes `status=complete_with_debt`, `semantic_status=blocked_plateau`, `quality=partial`, and `debt_manifest_hash`.

**Step 4: GREEN and commit**

```bash
pytest -q tests/unit/test_re_v2_protocol_25_debt.py tests/unit/test_re_v2_protocol_25_status.py tests/integration/test_re_v2_protocol_25_cli.py
git add src/harness/re_v2/protocol_25/debt.py src/harness/re_v2/protocol_25/status.py src/echelon/cli.py src/echelon/cli_app.py tests/unit/test_re_v2_protocol_25_debt.py tests/integration/test_re_v2_protocol_25_cli.py
git commit -m "feat(re): authenticate residual L3 debt"
```

---

### Task 6: Implement one-successor Banzai orchestration and telemetry

**Files:**

- Create: `src/harness/re_v2/protocol_25/convergence.py`
- Modify: `src/echelon/cli.py`
- Modify: `src/harness/re_v2/protocol_25/events.py`
- Modify: `src/harness/re_v2/protocol_25/status.py`
- Create: `tests/unit/test_re_v2_protocol_25_convergence.py`
- Modify: `tests/integration/test_re_v2_protocol_25_cli.py`

**Interface:**

```python
@dataclass(frozen=True)
class BanzaiResultV1:
    run_id: str
    semantic_status: str
    public_status: Literal["complete", "complete_with_debt"]
    successor_created: bool
    provider_call_count: int
    debt_manifest_hash: str | None

def run_banzai_resume(
    *, project_root: Path, blocked_run_dir: Path,
    execute_successor: Callable[[Path], object],
) -> BanzaiResultV1:
    return BanzaiCoordinator(
        project_root=project_root,
        blocked_run_dir=blocked_run_dir,
        execute_successor=execute_successor,
    ).run()
```

**Step 1: Write RED boundedness tests**

Add tests for one successor maximum, full closure without debt, valid plateau with exact debt, repeated zero-call reuse, prohibition on successor index 2, and nonsemantic blocker failure. Run `pytest -q tests/unit/test_re_v2_protocol_25_convergence.py`.

Expected RED: missing module.

**Step 2: Implement only these transitions**

```text
authenticated blocked parent
  -> create/reuse Banzai successor index 1
  -> execute/recover child
  -> complete: return complete
  -> blocked_plateau: finalize exact debt; return complete_with_debt
  -> any other state: fail closed
```

Validate root hash, index 1, and limit 1 before each transition. A child carrying Banzai guidance is never eligible to create a child.

Emit only guidance kind/hash, successor created/reused, start/end counts, automatic count/limit, zero-call reuse, debt ID/count, or fixed rejection reason. Never emit answer/finding/evidence content.

**Step 3: Connect CLI, GREEN, and commit**

```bash
pytest -q tests/unit/test_re_v2_protocol_25_convergence.py tests/unit/test_re_v2_protocol_25_events.py tests/integration/test_re_v2_protocol_25_cli.py
git add src/harness/re_v2/protocol_25/convergence.py src/harness/re_v2/protocol_25/events.py src/harness/re_v2/protocol_25/status.py src/echelon/cli.py tests/unit/test_re_v2_protocol_25_convergence.py tests/unit/test_re_v2_protocol_25_events.py tests/integration/test_re_v2_protocol_25_cli.py
git commit -m "feat(re): bound autonomous L3 convergence"
```

Banzai exits 0 only for complete or validated complete-with-debt.

---

### Task 7: Let workspace synthesis bind accepted L3 debt

**Files:**

- Modify: `src/harness/re_v2/protocol_27/authority.py`
- Modify: `src/harness/re_v2/protocol_27/model.py`
- Modify: `src/harness/re_v2/protocol_27/lifecycle.py`
- Modify: `src/harness/re_v2/protocol_27/inputs.py`
- Modify: `src/harness/re_v2/protocol_27/publication.py`
- Modify: `tests/unit/test_re_v2_protocol_27_authority.py`
- Modify: `tests/unit/test_re_v2_protocol_27_inputs.py`
- Modify: `tests/unit/test_re_v2_protocol_27_publication.py`
- Modify: `tests/integration/test_re_v2_protocol_27_downstream.py`

**Step 1: Write RED accepted-debt parent tests**

Assert raw blocked L3 is ineligible; exact acceptance makes only debt-bearing
sources partial; each partial debt hash equals the acceptance identity; any
altered acceptance/root/finding/snapshot/selection/terminal hash fails;
synthesis context/root says `input_quality="partial"`; publication cannot claim
full quality.

Run:

```bash
pytest -q tests/unit/test_re_v2_protocol_27_authority.py tests/integration/test_re_v2_protocol_27_downstream.py -k debt
```

Expected RED: protocol-2.7 rejects the blocked L3 parent.

**Step 2: Authenticate and preserve debt**

Validate `ResidualDebtAcceptanceV1` at the deterministic parent boundary. Reuse
`PartialSourceAcceptanceV1`, but bind its debt authority to the verified
acceptance identity, not the raw source-root hash. A source is partial when its
authenticated root is blocked/next-epoch-required or its accepted debt groups
retain findings; an already-complete debt-free source remains complete. The
accepted-partial set must exactly equal that derived subset, and each partial
source retains its exact source-local debt groups.

Ensure request, manifest, context, checkpoint, synthesis root, materialization, and publication retain:

```python
input_quality = "partial"
debt_manifest_hashes = (residual_debt_acceptance.identity,)
```

Provider output cannot remove these fields or claim complete input.

**Step 3: GREEN and commit**

```bash
pytest -q tests/unit/test_re_v2_protocol_27_authority.py tests/unit/test_re_v2_protocol_27_model.py tests/unit/test_re_v2_protocol_27_inputs.py tests/unit/test_re_v2_protocol_27_publication.py tests/integration/test_re_v2_protocol_27_downstream.py
git add src/harness/re_v2/protocol_27/authority.py src/harness/re_v2/protocol_27/model.py src/harness/re_v2/protocol_27/lifecycle.py src/harness/re_v2/protocol_27/inputs.py src/harness/re_v2/protocol_27/publication.py tests/unit/test_re_v2_protocol_27_authority.py tests/unit/test_re_v2_protocol_27_model.py tests/unit/test_re_v2_protocol_27_inputs.py tests/unit/test_re_v2_protocol_27_publication.py tests/integration/test_re_v2_protocol_27_downstream.py
git commit -m "feat(re): preserve accepted L3 debt in synthesis"
```

---

### Task 8: Let L4 consume only explicitly accepted partial L3 authority

**Files:**

- Modify: `src/harness/re_v2/protocol_28/authority.py`
- Modify: `src/harness/re_v2/protocol_28/orchestration.py`
- Modify: `src/harness/re_v2/protocol_28/preparation.py`
- Modify: `src/harness/re_v2/protocol_28/inputs.py`
- Modify: `src/harness/re_v2/protocol_28/context.py`
- Modify: `tests/unit/test_re_v2_protocol_28_authority.py`
- Modify: `tests/unit/test_re_v2_protocol_28_orchestration.py`
- Modify: `tests/unit/test_re_v2_protocol_28_preparation.py`
- Modify: `tests/integration/test_re_v2_protocol_28_orchestration.py`

**Interface:**

Add rather than mutating frozen V1 bytes:

```python
@dataclass(frozen=True)
class ValidatedL3ParentV2:
    parent: ValidatedL3ParentV1
    input_quality: Literal["complete", "partial"]
    residual_debt_acceptance_hash: str | None
    unresolved_finding_ids: tuple[str, ...]
    deferred_observation_ids: tuple[str, ...]
```

**Step 1: Write RED eligibility tests**

Assert unaccepted blocked parents fail; accepted debt permits every semantic class including `requires_human_decision`; missing/mismatched debt fails; complete-parent V1 identity remains unchanged; partial protocol-2.7 synthesis resolves to the exact underlying accepted L3; L4 inputs/context retain partial quality/hash; output cannot erase or claim closure of accepted debt.

Run:

```bash
pytest -q tests/unit/test_re_v2_protocol_28_orchestration.py -k debt tests/integration/test_re_v2_protocol_28_orchestration.py -k debt
```

Expected RED: existing eligibility rejects blocker classes other than `requires_deeper_evidence`.

**Step 2: Authenticate partial authority and bind it downstream**

Make `_validated_l3_parent_from_context` return V2. Broaden semantic eligibility only after exact debt validation. Preserve clean-exact-source validation before graph creation/provider reservation. Include acceptance hash plus unresolved/deferred IDs in L4 request/input/context identity. Raw `blocked_plateau` never becomes directly eligible.

**Step 3: GREEN and commit**

```bash
pytest -q tests/unit/test_re_v2_protocol_28_authority.py tests/unit/test_re_v2_protocol_28_orchestration.py tests/unit/test_re_v2_protocol_28_preparation.py tests/unit/test_re_v2_protocol_28_inputs.py tests/unit/test_re_v2_protocol_28_context.py tests/integration/test_re_v2_protocol_28_orchestration.py
git add src/harness/re_v2/protocol_28/authority.py src/harness/re_v2/protocol_28/orchestration.py src/harness/re_v2/protocol_28/preparation.py src/harness/re_v2/protocol_28/inputs.py src/harness/re_v2/protocol_28/context.py tests/unit/test_re_v2_protocol_28_authority.py tests/unit/test_re_v2_protocol_28_orchestration.py tests/unit/test_re_v2_protocol_28_preparation.py tests/unit/test_re_v2_protocol_28_inputs.py tests/unit/test_re_v2_protocol_28_context.py tests/integration/test_re_v2_protocol_28_orchestration.py
git commit -m "feat(re): bind accepted L3 debt into L4"
```

---

### Task 9: Document, verify, install, and exercise safely

**Files:**

- Modify: `README.md`
- Create: `docs/re-v2-operator-runbook.md`
- Modify: `tests/unit/test_cli_typer_app.py`
- Modify exact compatibility constants/tests only if the implementation closure changes: `src/harness/re_v2/protocol_25/compatibility.py`, `tests/unit/test_re_v2_protocol_25_compatibility.py`

**Step 1: Document the operator decision**

Document all resume modes, the one-successor bound, `complete` versus `complete_with_debt`, zero-call reuse, fail-closed blockers, partial synthesis/L4 labels, and absolute budget semantics:

```text
Use --recommended when accepted evidence may resolve the ambiguity.
Use custom guidance when you can supply a product decision or interpretation.
Use --banzai when one bounded attempt is enough and remaining semantic uncertainty may remain explicit debt.
```

**Step 2: Update exact in-flight implementation compatibility**

The guidance/runtime/renderer work changes the installed L3 implementation
closure. Compute its new digest with the same implementation-authority helper
used by `_re_v25_context`. Add only the reviewed mapping from the exact digest
frozen by the preserved OptaSearch run to this exact installed digest in
`protocol_25/compatibility.py`. Add tests proving that pair is accepted while a
different expected digest, different installed digest, or mixed expected set
still fails closed. Do not add a wildcard, version range, or transitive alias.

**Step 3: Focused and full verification**

```bash
git diff --check
pytest -q tests/unit/test_re_v2_protocol_25_guidance.py tests/unit/test_re_v2_protocol_25_guidance_status.py tests/unit/test_re_v2_protocol_25_convergence.py tests/unit/test_re_v2_protocol_25_debt.py tests/integration/test_re_v2_protocol_25_cli.py tests/integration/test_re_v2_protocol_27_downstream.py tests/integration/test_re_v2_protocol_28_orchestration.py
pytest
bash scripts/bash/dry-run.sh
```

Expected: PASS. For any unrelated pre-existing failure, rerun the exact test and record evidence; never weaken the assertion.

**Step 4: Install and inspect CLI**

```bash
bash scripts/install.sh
echelon re resume --help
```

Expected: help visibly offers custom, `--recommended`, and `--banzai`.

**Step 5: Exercise a synthetic plateau**

Verify status actions/counts, provider-effective recommended guidance, at-most-one Banzai successor, valid `complete_with_debt`, repeat zero-call behavior, partial synthesis, partial L4 authority construction, and dirty-source pre-dispatch rejection. Confirm telemetry contains no raw guidance/finding/source content.

**Step 6: Inspect OptaSearch read-only**

From `/Users/michalbachorik/work/optasearch`:

```bash
git stash list
echelon re status re-20260904-065536-022296
```

Use the existing workspace preflight to verify all seven selected source repositories are clean. Expected: 12 stashes remain and status offers deterministic choices. Do not run live Banzai or L4 without separate authorization.

**Step 7: Commit documentation and exact compatibility bridge**

```bash
git add README.md docs/re-v2-operator-runbook.md tests/unit/test_cli_typer_app.py src/harness/re_v2/protocol_25/compatibility.py tests/unit/test_re_v2_protocol_25_compatibility.py
git commit -m "docs(re): explain bounded L3 convergence"
```

---

## Completion audit

Run:

```bash
rg -n 'TO''DO|TB''D|implement la''ter|appropri''ate' src/harness/re_v2/protocol_25 src/harness/re_v2/protocol_27 src/harness/re_v2/protocol_28 src/echelon/cli.py src/echelon/cli_app.py docs/re-v2-operator-runbook.md
git log --oneline -12
git status --short
```

Manually confirm:

- guidance bytes/hash are in all three post-freeze contexts;
- old unguided identities are unchanged;
- commands never interpolate provider text;
- no Banzai transition creates successor index 2;
- partial finalization is zero-token and idempotent;
- raw blocked L3 remains unusable downstream;
- accepted debt remains visible through synthesis and L4;
- all invalid/nonsemantic stops remain blocked;
- no public protocol-choice burden was added; and
- OptaSearch stashes and source cleanliness remain preserved.
