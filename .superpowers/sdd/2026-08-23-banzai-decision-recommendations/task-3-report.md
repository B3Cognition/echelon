# Task 3 Report: Applied Resolution Audit, Routing, and Legacy Compatibility

## Status

Complete. Task 3 behavior is implemented and its focused slice is green. The
remaining routing-suite failures are exclusively the Task 4 controller
recommendation preparers for checkpoint assessment, dispatch caps, and
proportional quality.

## TDD evidence

### Baseline

Command:

```bash
uv run --frozen --extra dev pytest -q tests/unit/test_human_input_resolution_contract.py tests/integration/test_human_input_routing.py tests/unit/test_cli_continue.py
```

Pre-implementation output:

```text
103 failed, 158 passed
```

This established the expected Task 1/2 integration gap: the controller still
required prepared schema 1, consumed only blocked-decision schema 2, discarded
COMMANDER audit fields, rejected every Banzai human answer, and had no v2
Banzai migration transaction.

### RED: applied audit, human-only Banzai, retained v2 human authority, and migration failure

The first focused run covered the new applied type, low-confidence COMMANDER
audit, Banzai human-only routing, v2 awaiting-human retention, and canonical
unreconstructable-v2 failure.

Captured output:

```text
FFFFF                                                                    [100%]
5 failed
```

The failures were the intended missing contract/class, schema-1-only
controller validation, blanket Banzai human rejection, and provider dispatch
instead of migration failure. A separate success-path migration test produced:

```text
F                                                                        [100%]
1 failed
```

because pending v2 Banzai authority was still sent directly through the old
policy path rather than migrated.

### GREEN: initial Task 3 behavior

After implementing the applied type and version-aware routing, the same six
core behaviors produced:

```text
......                                                                   [100%]
6 passed in 1.21s
```

### Final focused Task 3 slice

Command:

```bash
uv run --frozen --extra dev pytest -q tests/unit/test_human_input_resolution_contract.py tests/integration/test_human_input_routing.py tests/unit/test_cli_continue.py tests/kernel/test_squad_state.py -k 'applied_resolution_retains or commander_resolution_persists or commander_override_uses or semi_resolution_copies or banzai_human_only or legacy_v2_awaiting or legacy_v2_semi or unreconstructable_pending_v2 or pending_v2_banzai_human_only or pending_or_resolving_v2 or continue_nonautomatic_v2 or continue_routes_eligible_semi or v3_commander_override_persists_complete_resolution_audit'
```

Output:

```text
20 passed, 492 deselected in 2.28s
```

### Broader verification

Command:

```bash
uv run --frozen --extra dev pytest -q tests/unit/test_human_input_resolution_contract.py tests/unit/test_cli_continue.py tests/kernel/test_squad_state.py
```

Output:

```text
324 passed in 2.45s
```

Command:

```bash
uv run --frozen --extra dev pytest -q tests/integration/test_human_input_routing.py --tb=no
```

Output:

```text
19 failed, 169 passed in 28.65s
```

All 19 failures are Task 4-owned producer preparation: four checkpoint-assess
cases, nine dispatch-cap cases, and six proportional-quality cases. No Task 3
audit, routing, migration, restart, or compatibility test remains red.

Additional checks:

```bash
git diff --check
python -m py_compile src/harness/human_input.py src/harness/squad.py src/harness/squad_state.py tests/unit/test_human_input_resolution_contract.py tests/integration/test_human_input_routing.py tests/unit/test_cli_continue.py tests/kernel/test_squad_state.py
```

Both exited 0 with no output.

## Files

- `src/harness/human_input.py`
- `src/harness/squad.py`
- `src/harness/squad_state.py`
- `tests/unit/test_human_input_resolution_contract.py`
- `tests/integration/test_human_input_routing.py`
- `tests/unit/test_cli_continue.py`
- `tests/kernel/test_squad_state.py` (updated existing Task 2 CAS call sites to
  carry audit on `AppliedHumanInputResolution`)

## Implemented behavior

- Added `AppliedHumanInputResolution` with nullable rationale and confidence;
  retained `HumanInputResolution` as a compatibility alias for historical
  internal callers.
- Changed all closed controller handlers and the state CAS to consume the
  complete applied resolution value.
- COMMANDER now copies the full validated decision resolution, including low
  confidence and rationale. Semi copies the sealed recommendation rationale and
  confidence. User answers provide null audit fields.
- The atomic state transition derives followed/override state solely from the
  sealed recommendation. A COMMANDER divergence stores its rationale as the
  durable override reason.
- Fresh v3 Banzai decisions dispatch only when intrinsically
  `automatic_eligible`; human-only free text waits and accepts a user answer.
  Human injection is rejected only for automatic v3 Banzai authority.
- Version-neutral controller reads and resume paths now validate either v2 or
  v3 authority.
- Existing v2 `awaiting_human` decisions stay v2, including choice decisions
  with zero recommendation flags. Existing v2 semi `pending` and `resolving`
  decisions recover/select deterministically, remain v2, invent no audit, and
  call no provider.
- Pending v2 Banzai decisions are re-prepared and migrated only through a
  revision/ID/status checked state transaction. Resolving v2 Banzai authority
  first follows the existing recovery transition, then migrates.
- Successful migration preserves decision ID, creation time, attempts, and the
  structural policy/question/option contract while adding the v3 recommendation
  snapshot. Human-only migrations become v3 `awaiting_human` without dispatch.
- Unsafe reconstruction commits one failed v2 decision/recovery pair with
  `decision_recommendation_unavailable`, preserving every v2 identity, policy,
  question, option, attempt, source revision, and timestamp field and issuing
  zero provider calls.
- CLI continue coverage now explicitly retains operational v2 Banzai
  awaiting-human authority without filesystem mutation.

## Self-review

- Re-read the Task 3 brief against the complete production diff.
- Confirmed no checkpoint recommendation synthesis or producer integration was
  added; those paths remain isolated for Task 4.
- Confirmed only v2 Banzai `pending` may enter either migration transaction;
  state revision, decision ID, status, schema, autonomy mode, and prepared
  revision are checked while holding the store lock.
- Confirmed interrupted `resolving` authority is recovered before routing and
  that semi authority never enters migration.
- Confirmed migration failure retains the original validated v2 mapping except
  for terminal status/failure code, and the generated recovery remains schema 2
  and bound to the same decision ID/reason.
- Confirmed automatic resolution audit cannot be sourced from provider target
  claims: follow state compares the applied target with the sealed target, and
  override reason comes from the validated applied rationale.
- Confirmed all production `HumanInputResolution` usages now consume the new
  concrete type and all removed audit keyword call sites were updated.
- Reviewed compatibility fixture changes to ensure fresh legacy-v1 adaptation
  is correctly expected to seal v3, while already durable v2 authority remains
  v2 unless it is pending Banzai.

## Concerns

- The exact three-file requested routing command is not yet globally green:
  its remaining 19 failures require Task 4's registered checkpoint,
  dispatch-cap, and proportional-quality preparers. They are not regressions in
  Task 3 and were deliberately left out of this implementation.
- No unresolved Task 3 defect was found in self-review.

## Fix round 1/5: canonical v2 provider-choice migration

### Finding addressed

Canonical v2 provider choices always contain an `outcome` key, including when
its value is null, while the provider preparation boundary rejects provider
ownership of that field. Migration had passed the canonical option wholesale,
so even a reconstructable low-risk provider recommendation was incorrectly
retired as `decision_recommendation_unavailable`.

### RED

Command:

```bash
uv run --frozen --extra dev pytest -q tests/integration/test_human_input_routing.py -k 'provider_choice_migration_preserves_outcome_ownership' --tb=short
```

Output:

```text
F.                                                                       [100%]
1 failed, 1 passed, 188 deselected in 0.73s
```

The canonical null-outcome case returned `False` instead of migrating and
dispatching. The non-null-outcome case already passed, proving that the existing
failure path did not silently erase provider-owned outcome semantics.

### GREEN

The migration adapter now requires every validated legacy provider option to
have `outcome is None`, removes only that canonical null key, and passes the
remaining provider-owned fields through the strict provider normalizer.

Command:

```bash
uv run --frozen --extra dev pytest -q tests/integration/test_human_input_routing.py -k 'provider_choice_migration_preserves_outcome_ownership' --tb=short
```

Output:

```text
..                                                                       [100%]
2 passed, 188 deselected in 0.62s
```

### Regression verification

Commands and outputs:

```text
uv run --frozen --extra dev pytest -q tests/integration/test_human_input_routing.py -k 'unreconstructable_pending_v2 or provider_choice_migration_preserves_outcome_ownership or pending_v2_banzai_human_only or pending_or_resolving_v2_banzai'
6 passed, 184 deselected in 1.10s

uv run --frozen --extra dev pytest -q tests/unit/test_human_input_resolution_contract.py tests/unit/test_cli_continue.py tests/kernel/test_squad_state.py
324 passed in 2.46s

uv run --frozen --extra dev pytest -q tests/integration/test_human_input_routing.py --tb=no
19 failed, 171 passed in 29.05s
```

The same 19 Task 4 producer-preparation failures remain; the provider-choice
migration cases add two passing cases without introducing another failure.

### Fix-round self-review

- Confirmed the source decision is version-neutrally validated before the
  migration adapter reads `option["outcome"]`, so canonical key presence and
  option shape are already guaranteed.
- Confirmed only a null canonical `outcome` is removed. A non-null value enters
  the canonical v2 failure transaction unchanged, preserving the ownership
  boundary and issuing no provider call.
- Confirmed the remaining option fields still pass through
  `HumanInputPolicyRegistry.prepare()` and its strict provider normalization;
  the adapter does not bypass recommendation, route, or option validation.
- Confirmed the successful case migrates to schema v3, retains the same
  decision ID, dispatches once, resolves the sealed recommended option, and
  persists the COMMANDER audit.
