# RE Cost, Convergence, and Layering Findings

**Date:** 2026-08-14
**Evidence workspace:** `/Users/michalbachorik/work/optasearch`
**Primary retained run:** `runs/re-20260807-143720-822514`

## Context

The retained OptaSearch RE campaign consumed at least 1,324,261,341 known
tokens across four runs and 1,043 provider dispatches. The primary run alone
recorded 1,010 dispatches over approximately 53.6 active provider hours. It
eventually published a partial generation, but only after repeated source
specification, semantic validation, repair, and workspace-synthesis cycles.

This was partly a moving-engine torture run: Echelon provider, result-contract,
partitioning, continuation, and RE fixes were installed while the run was in
progress. That does not make its absolute cost a normal benchmark. It does,
however, expose architectural behavior that a stable run must not retain:
verified work is insufficiently reusable, validation can keep discovering a
moving set of findings, synthesis happens before source outcomes are final, and
the analyzer cannot yet report the resulting behavior reliably.

## Grounded Findings

### EGR-163: RE telemetry correctness

The current analyzer can materially misstate the run:

- it prefers the creation manifest's original execution profile over the
  authoritative continued-run state, reporting a 25M token ceiling instead of
  the final 1.325B ceiling and ignoring twenty recorded budget overrides;
- it classifies controller audit strings as non-blocking and suppresses
  aggregate failures, reporting zero blocking findings while the canonical
  semantic report contains 53;
- its reported first-pass repair rate can exceed 100 percent because it divides
  total repaired counters by current audit count rather than measuring
  first-pass outcomes;
- it derives wall-clock duration from arbitrary copied-file mtimes, producing
  roughly 21.8 days for a run whose provider-active time was about 53.6 hours;
- ten dispatches in the retained run have unknown token usage, but completeness
  is not carried through all summaries.

Until these are corrected, cost reductions and convergence changes cannot be
benchmarked honestly.

**Implemented evidence:** The corrected adapter now reads the current inner
profile and active duration, uses the canonical aggregate failure count,
intersects repair history with current audit identities, leaves unrecorded
first-pass outcomes unavailable, and derives wall clock from lifecycle
intervals. Against the retained run it reports a 1.325B ceiling, 1.2978B known
tokens plus 10 unknown dispatches, 53 blocking failures, 57 repaired current
domains out of 63 audited, 195,537,764ms active duration, and a 571,017,536ms
wall clock. The telemetry-focused matrix passes 76 tests.

### EGR-164: pinned RE execution kernel

An RE run does not yet pin one immutable source snapshot, domain partition,
extractor/protocol version, and artifact dependency graph for its lifetime.
Continuation migrations can alter protocol or partition behavior inside an
active run. A redesigned kernel must make the execution snapshot explicit and
keep controller state, events, artifact identities, and publication decisions
separate.

### EGR-165: layered artifact identities

Current source currency requires an exact profile hash and a complete published
source. A higher-detail profile therefore cannot reference lower-detail verified
artifacts as prerequisites; it treats their profile difference as staleness.
Artifact keys need independent source-content, extractor/protocol, domain,
layer, and layer-profile components so higher layers add deltas without
invalidating lower ones.

### EGR-166: adoptable domain checkpoints

Continuation preserves the current run and refresh staging can seed canonical
published source artifacts, but blocked unpublished runs are stranded, partial
sources are forced through refresh, and ordinary refresh does not generally
accept already-passing seeded domain artifacts. Verified source/domain
checkpoints need durable receipts and an adoption contract independent of final
workspace publication.

### EGR-167: stable semantic audit epochs

The primary run recorded 340 validator dispatches. Twenty-one final domain keys
were validated more than five times, five more than ten times, and some domain
identities were dispatched 22-35 times. Fifteen obsolete or migrated domain
identities consumed 107 validation calls and approximately 163.5M tokens but no
longer exist in final audit state. Finding IDs and wording churned enough that
the repeated-finding detector remained empty even when final prose explicitly
said the issue had been raised before.

Semantic validation must freeze the finding set for an audit epoch, repair only
that set, and recheck closure. Newly discovered findings belong to an explicit
next layer or audit epoch. Semantic repair must have its own budget and a
plateau rule; increasing a source-generation ceiling must not silently increase
semantic repair rounds.

### EGR-168: synthesis scheduling

Workspace synthesis ran 34 times, consuming approximately 76.9M known tokens
and 2.6 provider hours. The final accepted synthesis used approximately 2.9M
tokens, so most earlier synthesis work was invalidated. Source repair currently
marks workspace synthesis stale and sends control back through specification and
validation paths. Synthesis should run only after each selected source reaches
an accepted terminal outcome, with incremental recomposition considered only
after the layer dependency model is stable.

### EGR-169: selective deepening

The current `fast`, `balanced`, and `high` execution profiles primarily control
time, token, audit, and repair budgets. The separate fingerprint profile changes
artifact shape and participates in exact source currency. Neither contract gives
an operator a composable way to deepen selected sources or domains while reusing
a trustworthy baseline. The target UX should support a compact baseline by
default and an explicit operation such as `echelon re deepen --source ...
--domain ... --goal ...` for costly behavioral or exhaustive layers.

### EGR-170: atomic repair after the kernel refactor

Whole-domain `spec.md` repair remains too coarse and contributed to repeated
broad specification turns. The accepted atomic element-repair invariants remain
valuable: stable element units, normalized diagnostics, isolated candidates,
compare-and-swap promotion, controller-certified receipts, and bounded
no-progress handling. Its RE adapter, state, phase, gate, budget, and publication
integration must be designed against EGR-164 through EGR-169 rather than the
current controller.

## Recommended Order

1. EGR-163: correct telemetry and prove metrics against the retained run.
2. EGR-164: define and implement the pinned execution-kernel boundary.
3. EGR-165 and EGR-166: introduce layered identities and adoptable checkpoints.
4. EGR-167: make semantic convergence epoch-based and independently bounded.
5. EGR-168: move synthesis behind accepted source outcomes.
6. EGR-169: expose selective deepening over the reusable layers.
7. EGR-170: implement atomic element repair on the stable kernel.

## Initial Layer Model

- **L0 deterministic inventory:** source snapshot, topology, manifests, symbol
  and evidence indexes.
- **L1 compact baseline:** bounded source/domain overviews and core behavioral
  specification.
- **L2 behavioral depth:** selected contracts, flows, integration behavior, and
  evidence-backed detail.
- **L3 semantic audit overlay:** a frozen finding epoch and closure receipts.
- **L4 exhaustive depth:** explicitly selected critical domains only.

Higher layers reference lower-layer artifact identities. They do not replace or
invalidate them merely because their execution or depth profile differs.
