# Echelon Delta Review After EGR-011

**Review date:** 2026-06-24
**Reviewed HEAD:** `34b4857d5f9aa1cb74c30cddae169e77b7552009`
**Previous delta HEAD:** `665c7acbd3a6a2fae60a617e39c4a1aa7abfd808`
**Scope:** EGR-010 and EGR-011 changes only, plus the current EGR register.

## Summary

EGR-010 and EGR-011 materially improved the harness safety surface:

- EGR-010 added a deterministic staged-file secret scan before `GitOpsManager.commit()`.
- EGR-011 added per-phase `allowed_state_updates`, static role-contract checks,
  and runtime enforcement for normal `SquadStateStore.advance()` plus staged and
  conditional executor direct writes.

The full review snapshot remains broadly valid. RCA remains intentionally parked
because the team has a separate RCA pipeline that needs source-grounded
integration later. This delta review therefore does not recommend implementing
EGR-009 now.

The delta review found three follow-on gaps introduced or clarified by the new
state-update allowlist architecture.

## What Changed

### EGR-010

Implemented files:

- `src/harness/secret_scan.py`
- `src/harness/gitops.py`
- `tests/unit/test_secret_scan.py`
- `tests/integration/test_gitops_safety.py`

Grounded assessment:

- `GitOpsManager.commit()` stages changes, calls `scan_git_staged()`, and blocks
  before commit creation when findings exist.
- Secret findings are sanitized to path, line, column, rule ID, and severity.
- This is a useful first deterministic gate. No new blocking EGR is needed for
  this path right now.

Possible future hardening, not promoted here: file-size caps, configurable rule
sets, and optional external scanner integration.

### EGR-011

Implemented files:

- `extension/workflow/definition.yaml`
- `src/harness/echelon_result_schema.py`
- `src/harness/phase_graph.py`
- `src/harness/role_contracts.py`
- `src/harness/squad.py`
- `src/harness/squad_executors.py`
- `src/harness/squad_state.py`
- focused kernel/unit tests

Grounded assessment:

- Normal phase advancement is protected by `SquadStateStore.advance(...,
  allowed_state_update_keys=node.allowed_state_updates)`.
- Staged and conditional executor direct writes are protected by
  `PhaseExecutor._validate_result_state_updates()`.
- Static contract validation now fails routed roles missing an
  `allowed_state_updates` declaration.
- Remaining direct state-update paths are now clearer and should be closed as
  follow-up work.

## New Findings

### EGR-012: Pre-dispatch state updates bypass per-phase allowlists

**Priority:** P1

`src/harness/squad_executors.py::_run_pre_dispatch()` executes pre-dispatch
agents and writes `result.state_updates` directly into state:

```text
for k, v in result.state_updates.items():
    s = state_store.load()
    s[k] = v
    state_store.save(s)
```

This bypasses the EGR-011 allowlist validation used by normal advancement and
staged/conditional executor paths. `phase1-discover` currently has pre-dispatch
entries for GOLDDIGGER/guardian routing metadata, so this is not theoretical.

Recommended fix:

- Validate pre-dispatch results through the same helper as staged/conditional
  executors before applying state.
- Decide whether the parent phase allowlist is sufficient or whether
  pre-dispatch entries need their own `allowed_state_updates`.
- Add focused tests proving unexpected pre-dispatch keys block before mutation.

### EGR-013: COMMANDER judgment state updates bypass allowlists

**Priority:** P1

`src/harness/squad.py::_evaluate_transitions()` validates `next_phase`, but then
applies extra COMMANDER judgment updates directly:

```text
extra = {k: v for k, v in judgment.state_updates.items() if k not in routing_keys}
if extra:
    s = self._state_store.load()
    s.update(extra)
    self._state_store.save(s)
```

`_judgment_dispatch_escalation()` also applies returned state updates directly,
including null-as-delete behavior. These are agent-sourced updates outside the
phase allowlist path.

Recommended fix:

- Introduce a small deterministic helper for COMMANDER/judgment state updates.
- Use a narrow judgment allowlist, for example `next_phase`, `phase`,
  `iteration`, escalation-resolution keys, and explicitly documented recovery
  keys.
- Preserve intentional null-as-delete behavior only for approved keys.
- Add tests for invalid judgment keys and banzai escalation cleanup.

### EGR-014: Allowed state-update keys are enforced but not fully injected into prompts

**Priority:** P2

`PhaseExecutor._assemble_prompt()` appends `_routing_contract(node)` and the
canonical `echelon_result` template. `_routing_contract()` derives only fields
needed by transition conditions. It does not render the full
`node.allowed_state_updates` allowlist. Staged consensus prompts currently append
only the canonical template, not the allowlist.

This means EGR-011 can reject a key that the agent was never shown as disallowed.
The runtime behavior is safe, but the authoring/developer experience is rougher
than it needs to be.

Recommended fix:

- Add an "Allowed state_updates for this dispatch" prompt section for normal,
  staged, conditional, and pre-dispatch prompts.
- Keep `_routing_contract()` focused on required routing fields; add a separate
  allowlist rendering helper.
- Add tests that prompts include allowed keys and explicitly say `{}` when no
  state mutation is allowed.

## Parked Item

### EGR-009

EGR-009 remains valuable, but should not be implemented from the original review
alone. The team has a separate RCA pipeline that should be integrated with
Echelon using its actual source, artifacts, and operating assumptions.

Recommended status: `accepted-risk` until the RCA pipeline source is available.

## Recommended Next Path

1. Implement EGR-012 first. It closes the most direct remaining bypass in the
   state-update allowlist architecture.
2. Implement EGR-013 next. It narrows COMMANDER judgment writes without changing
   normal phase dispatch.
3. Implement EGR-014 after both enforcement paths are closed. It improves prompt
   compliance and reduces avoidable blocked runs.
4. Revisit EGR-009 only after the external RCA pipeline source is available.

## Verification During Review

No source code was changed by this delta review. The review used repository
evidence from:

- `git diff 665c7acbd3a6a2fae60a617e39c4a1aa7abfd808..HEAD -- src extension tests docs CHANGELOG.md`
- `src/harness/squad_executors.py`
- `src/harness/squad.py`
- `src/harness/squad_state.py`
- `src/harness/secret_scan.py`
- `docs/findings/echelon-grounded-review-register.md`
