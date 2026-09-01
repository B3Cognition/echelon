# RE v2 Bounded L3 Source Audit Design

**Date:** 2026-09-01

**Amends:** `2026-08-25-re-v2-l3-semantic-audit-closure-design.md`

**Status:** Approved direction; implementation pending

## Summary

The first all-source OptaSearch L3 run proved that protocol 2.5's source audit
projection is not bounded in practice. The source audit repeats every selected
domain baseline and every excerpt cited by those baselines even though each
domain already has an independent L3 audit. The next source target required a
2,701,823-byte provider context against a frozen 196,608-byte ceiling. Three
other selected sources required approximately 740 KiB, 950 KiB, and 1.1 MiB.

This amendment retains exact domain audits and changes only the source audit
projection. A bounded source audit inspects the accepted L2 source overview,
whose contract already owns selected cross-domain flows, boundaries, failure
propagation, and claim consistency. The source target continues to hash-bind
the complete selected-domain L2 closure, but the provider prompt no longer
duplicates every domain baseline and its cited evidence. The existing
post-resolution source-composition guard still checks all active domain and
source overlays together. L4 remains the exhaustive evidence layer.

New L3 layer contracts use protocol `2.5.1` inside the existing protocol-2.6
checkpoint-capable outer run. Protocol `2.5` remains readable with its original
source-target semantics. Domain target, template, work-item, artifact, and
candidate identities remain exact so compatible accepted domain audits can be
adopted into a new `2.5.1` run.

## Evidence and root cause

Run `re-20260901-110701-757460` accepted seven L3 audit candidates before the
next deterministic context projection failed. The failure was initially
reported only as:

```text
audit provider context cannot be reconstructed from accepted L2 authority
```

The preserved exception cause was:

```text
semantic context exceeds its byte ceiling
```

The accepted authority was complete and valid. The failure occurred because a
source target aggregated 31 audited L2 artifacts and 883 evidence excerpts into
one provider context. Exact-range deduplication still left hundreds of ranges;
raising the ceiling would preserve an unbounded cost function rather than fix
it.

Projecting only each source's accepted L2 source overview produced these exact
context sizes in the same immutable OptaSearch snapshot:

| Source | Bounded context bytes |
|---|---:|
| `opta-search-lokalise-lambda` | 58,051 |
| `optapulse-platform` | 53,465 |
| `pe-argocd-deployments-optapulse` | 29,148 |
| `pressbox-search` | 43,164 |
| `pressbox-search-api` | 51,934 |
| `pressbox-search-deployment` | 41,812 |
| `pressbox-search-soccer-api` | 83,438 |

Every measured context is below the existing 196,608-byte ceiling. No source
content was printed or copied during this measurement.

The lifecycle exposed a second bug: a deterministic pre-dispatch projection
failure escaped the command without a durable failure event. Status therefore
continued to report `in_progress` and recommended an identical continuation
that must fail again.

## Goals

- Keep every protocol-2.5 domain audit identity and provider contract exact.
- Bound source audit prompts by auditing the accepted L2 source overview rather
  than repeating every selected domain baseline.
- Retain the complete selected-domain L2 closure as hash-bound controller
  authority for the source target and final L3 source root.
- Preserve the source-composition guard over all active domain and source
  overlays.
- Preflight every ready L3 audit context before the first L3 provider call.
- Convert deterministic projection failures into durable, actionable terminal
  authority.
- Reuse compatible accepted domain candidates and all lower-layer checkpoints
  in successor runs.
- Keep existing protocol-2.5 runs readable under their frozen semantics.

## Non-goals

- Raising the semantic context ceiling to accommodate monolithic source
  prompts.
- Adding a recursive shard/reducer framework to L3.
- Weakening domain evidence, finding certification, source guard, or closure
  requirements.
- Claiming exhaustive cross-domain source evidence at L3; L4 owns exhaustive
  depth.
- Mutating or silently reinterpreting an existing protocol-2.5 target.
- Automatically spending provider tokens after a failed preflight.
- Changing workspace synthesis or L4 artifact contracts.

## Decisions

### 1. Version the corrected layer contract as protocol 2.5.1

`RunManifestV4` accepts two exact semantic layer versions:

- `2.5`: original domain-plus-monolithic-source audit semantics;
- `2.5.1`: exact domain audits plus bounded source-overview audits.

The outer checkpoint-capable manifest remains protocol `2.6`/schema 5 and pins
the embedded layer manifest bytes. New L3 preparation emits `2.5.1`. Recovery
branches only on the pinned embedded layer protocol; it never guesses from run
age, installed version, status, or available files.

The `2.5.1` semantic request identity explicitly binds the embedded layer
protocol version. Changing only the manifest version is insufficient because
the protocol-2.5 semantic request hash otherwise contains no version field and
could resolve to an older `2.5` child.

This patch version is a correction to the L3 layer contract, not a new layer.
It avoids consuming the next top-level protocol number and keeps the current
L3-to-L4 orchestration model intact.

### 2. Domain audit authority is byte-identical

For a domain plan, `2.5.1` produces the same:

- selected scope;
- required and audited template IDs;
- `AuditTargetV1` bytes and identity;
- semantic-audit work template and work-item identity;
- artifact policy and executor contract;
- provider context and response schema; and
- candidate, certification, and acceptance identities.

Tests compare canonical bytes from `2.5` and `2.5.1`, not merely selected
fields. Any domain identity drift blocks release.

### 3. Source audit projects the L2 source overview only

For a source plan under `2.5.1`:

- `audited_template_ids` contains only the selected L2 `source-overview`;
- `required_template_ids` retains the complete selected source closure,
  including selected domain roots and their transitive L0-L2 authority;
- `AuditTargetV1.lower_dependency_hashes` retains that complete closure;
- the provider context embeds the exact accepted L2 source-overview artifact;
- authorized evidence contains only excerpts cited by that overview; and
- coverage remains `full-source` or `selected-domains` exactly as selected.

The source overview is the correct L2 abstraction boundary: its existing
contract describes cross-domain flows, boundaries, failure propagation, and
claim consistency. Domain baselines remain independently audited. Repeating
them in the source prompt adds cost but no distinct authority.

The final `L3SourceRootV1` continues to bind both domain and source audit
targets, their accepted candidates, the selected L2 source root, coverage, and
closure authority. Nothing may infer full-source coverage from a partial
selection.

### 4. Source-composition closure remains mandatory when applicable

The bounded initial source audit does not replace the existing semantic source
guard. When frozen findings require resolution, the guard receives all active
domain and source overlays, target recheck assessments, and selected composed
authority for that source cycle. Finding closure receipts remain impossible
until the guard passes.

An all-PASS zero-finding epoch retains the existing zero-repair-call path. Its
source root binds every accepted domain and bounded source audit candidate.

### 5. Preflight all ready audit contexts before provider spending

After L2 prerequisites are complete and before the first L3 dispatch, recovery
deterministically constructs every selected domain and source audit context
without invoking a provider. It records only content-addressed context objects
after all contexts pass.

Preflight validates:

- exact target and accepted prerequisite authority;
- immutable object availability and hashes;
- context/evidence ownership;
- snapshot path, blob, range, and text integrity;
- response-schema authority; and
- canonical context byte ceiling.

Preflight order is stable and independent of audit-target hash ordering. A
failure spends zero additional provider tokens and cannot leave a dispatch
lease or open reservation.

### 6. Deterministic projection failures become durable blockers

A failed preflight records controller-owned failure authority containing:

- audit target and work-item IDs;
- controlled reason code;
- failed projection class;
- configured byte ceiling and measured canonical byte count when available;
- zero provider attempts and zero provider usage; and
- the terminal transition to `blocked_incomplete`.

The primary reason code for this incident is
`semantic_context_byte_ceiling_exceeded`. Missing/corrupt authority retains
distinct fail-closed reason codes and must not be mislabeled as size failure.

Status must show the target scope, measured/allowed size, that no provider call
occurred, and an exact successor action. It must never report `in_progress` or
recommend identical continuation after this terminal event.

Preflight uses two additive protocol-2.5 event types:

- `audit_context_preflight_completed` binds the ordered target/context-hash
  pairs, checked-target count, maximum measured bytes, and configured ceiling;
- `audit_context_preflight_failed` binds the failed target/work item,
  controlled reason, measured bytes when available, configured ceiling, and
  zero-dispatch fact.

Successful context blobs are written before the completion event. A crash
between object write and event append leaves only harmless unreferenced content
and causes exact preflight replay. On failure, the preflight-failed event and a
protocol-2.5-owned typed preflight failure receipt are recorded before the
controller's existing `terminal_blocked_incomplete` transition. The shared
`WorkItemFailureReceiptV1` is deliberately not reused: its contract requires a
real dispatch plus execution-capture or abandonment authority, while preflight
must happen before dispatch. Recovery completes any missing suffix without
calling a provider.

### 7. Existing runs are preserved; correction uses a successor request

Existing protocol-2.5 runs retain their target identities and remain readable.
They are not rewritten to `2.5.1`. Continuing the affected run after the
lifecycle fix records its already-deterministic source-context blocker without
issuing another provider call.

A new L3 request from the same completed L2 authority emits a `2.5.1` layer
contract and therefore has a distinct semantic request identity. Protocol 2.6
checkpoint selection may adopt:

- all exact compatible L0-L2 authority; and
- exact accepted domain L3 candidates whose complete work and certification
  identities match.

The obsolete monolithic source target and its candidates are incompatible and
must not be remapped. The affected run has no accepted monolithic source
candidate for the oversized target.

The current L4 orchestration intent remains forensic because it binds the old
L3 prerequisite request. Repeating `deepen --to L4` after installation creates
or reuses an intent bound to the corrected `2.5.1` prerequisite request. It
must not mutate or rebind the old intent.

## Data flow

```text
accepted L0-L2 authority
          |
          v
  construct all L3 targets
          |
          v
 preflight every context --------> durable preflight blocker
          |                                  (zero calls)
          v
 domain audits (unchanged) + source-overview audits (bounded)
          |
          v
 freeze one finding epoch
          |
          v
 resolution + target rechecks + source composition guard
          |
          v
 accepted L3 source roots -> existing L4 orchestration
```

## Status and telemetry

Human status uses the shared Echelon RE card and reports:

- pinned outer and embedded L3 protocol versions;
- preflight state: not run, passed, or failed;
- selected target count and contexts checked;
- maximum measured context bytes and configured ceiling;
- failed source/domain scope and controlled reason;
- provider dispatches avoided by preflight;
- adopted versus generated domain/source audits; and
- exact successor/deepening command.

Durable telemetry adds preflight counts and measurements to the existing v2
event/ledger stream. It records no source text, prompt body, evidence excerpt,
credential, or provider stderr.

## Compatibility requirements

- Protocols 2.0-2.4 and their canonical bytes remain unchanged.
- Protocol-2.5 manifests and graph behavior remain unchanged when their pinned
  embedded version is `2.5`.
- Protocol-2.6 outer manifests continue to route L3 through their embedded
  layer authority.
- Protocols 2.7 synthesis and 2.8 L4 remain readable and executable.
- L4 accepts a completed `2.5.1`/protocol-2.6 L3 prerequisite through the same
  validated L3 projection contract.
- JSON status remains machine-compatible; new fields are additive.
- Human status and errors use the shared Echelon UI.

## Verification strategy

### Identity and graph

- Golden-byte comparison proves every domain plan, target, template, and work
  item is identical between `2.5` and `2.5.1`.
- Source target identity changes and audits only the L2 source overview.
- Source required closure and final root still bind all selected domains.
- Partial source selection cannot claim full-source coverage.
- Old manifests reconstruct the original monolithic source target.

### Preflight and lifecycle

- A synthetic oversized source context fails before any lease, reservation,
  provider call, candidate, or usage record.
- The failure records exact durable blocker authority and terminal status.
- Missing/corrupt authority uses a different reason code.
- Crash recovery at each preflight event boundary is idempotent.
- Identical continuation of a terminal preflight blocker issues zero calls.

### Reuse

- A corrected successor adopts accepted domain candidates from a blocked `2.5`
  sibling without remapping identity.
- It rejects monolithic source candidates and any domain candidate whose
  policy, executor, target, work item, or certification differs.
- The old and new L4 orchestration request IDs differ and never rebind.

### Real OptaSearch proof

1. Install the corrected CLI/runtime.
2. Continue `re-20260901-110701-757460` once and verify it records a zero-call
   durable preflight blocker rather than crashing.
3. Start/reuse corrected all-source L4 deepening from the same accepted lower
   authority.
4. Verify all 81 L3 contexts (74 domains plus seven sources) pass preflight and
   the largest is below 196,608 bytes.
5. Verify compatible lower and domain checkpoints are adopted.
6. Monitor L3 to terminal completion, then allow the authorized L4
   orchestration to advance.
7. Confirm all source repositories and preserved stashes remain unchanged.

## Success criteria

The amendment is complete when:

1. new L3 runs pin `2.5.1` semantics without rewriting old runs;
2. domain audit identities are byte-identical and adoptable;
3. source audit contexts use only accepted L2 source-overview artifacts and
   their cited evidence;
4. the complete selected-domain closure remains hash-bound;
5. every planned context is preflighted before provider spending;
6. deterministic preflight failure is a durable actionable blocker;
7. source composition and finding closure guarantees remain intact;
8. focused, compatibility, full-suite, installed, and real-workspace gates
   pass; and
9. the OptaSearch L3 prerequisite can complete and advance into L4 without a
   monolithic source prompt.
