# RE v2 operator runbook

Echelon presents one RE workflow. Internal protocol and schema revisions are
run-format details; operators choose an action from `echelon re status`, not a
protocol version.

## Start and inspect

Source repositories must be clean before RE starts or continues. Commit, stash,
or revert tracked and untracked source changes first.

```bash
echelon re run --engine v2
echelon re status
echelon re status --json
```

Status is authoritative. `complete` means the selected semantic scope closed.
`complete_with_debt` means Echelon safely accepted the exact remaining semantic
uncertainty; it does not mean that uncertainty disappeared.

## Choose how to leave an L3 plateau

Use exactly one mode:

```bash
echelon re resume --recommended
echelon re resume "The public timeout is 30 seconds; retries are caller-owned."
echelon re resume --banzai
```

- Use `--recommended` when accepted evidence may resolve the ambiguity. Its
  installed conservative guidance closes only evidence-supported findings and
  preserves everything else as unresolved.
- Use custom guidance when you can supply a product decision or interpretation.
  Guidance is normalized, content-addressed, and included in every post-freeze
  semantic provider request.
- Use `--banzai` when one bounded attempt is enough and remaining semantic
  uncertainty may remain explicit debt. It creates or reuses exactly one
  automatic successor. It cannot create successor two, raise budgets, or turn
  structural and execution failures into debt.

Banzai returns success only for `complete` or validated
`complete_with_debt`. Repeating the same command over the same authority reuses
the same successor/result and may make zero provider calls.

## Budgets are absolute

Token and active-time values are absolute run ceilings. They are not additions
and do not reset consumed usage.

```bash
echelon re continue <run-id> \
  --re-token-limit 300000000 \
  --re-time-limit-minutes 1440 \
  --re-semantic-token-limit 300000000 \
  --re-semantic-time-limit-minutes 1440
```

Echelon never raises these ceilings automatically. A resource pause reports the
minimum new absolute total needed. Provider operations with unknown outcomes
remain indeterminate and cannot be accepted as debt.

## What may become residual debt

Only authenticated semantic findings at a valid terminal L3 plateau may be
accepted. The debt record binds the run manifest, terminal event, frozen audit
epoch, closure root, source roots, exact findings grouped by source and class,
deferred observations, guidance, snapshot, selection, and finalization
operation.

These conditions always remain blocked:

- incomplete audit targets, roots, snapshots, or authority;
- dirty or changed source repositories;
- active or indeterminate provider operations;
- resource or context exhaustion;
- malformed output, schema failure, or contract failure; and
- structural or deterministic execution failure.

If status does not offer Banzai, fix the reported blocker or use the displayed
continuation command. Do not force a debt result.

## Downstream meaning

Workspace synthesis accepts a partial L3 parent only when the exact residual
debt acceptance is present and valid. Debt-bearing sources remain `partial`;
already-complete sources remain `complete`. The synthesis root and publication
retain `input_quality: partial` and the debt acceptance hash.

L4 follows the same rule. Raw blocked L3 authority is ineligible. Every L4
slice created from accepted debt authenticates that record and receives:

```text
input_quality: partial
residual_debt_disposition: accepted_not_closed_by_l4
```

L4 may collect deeper evidence, but it cannot erase the accepted L3 debt or
report that debt as closed. Status keeps the debt hash visible.

## Safe recovery sequence

1. Run `echelon re status <run-id>` and use its exact next action.
2. If the run is resource-paused, approve and set only the required higher
   absolute ceiling.
3. If it is a semantic plateau, choose recommended, custom, or Banzai guidance.
4. If Banzai returns `complete_with_debt`, continue to synthesis or L4 knowing
   downstream quality remains partial.
5. If the failure is structural, provider-indeterminate, or authority-related,
   repair that cause and create/reuse the compatible successor shown by status.

Telemetry records kinds, hashes, counts, limits, and fixed reason codes. It does
not record raw guidance, finding prose, evidence, source code, prompts,
responses, or secrets.
