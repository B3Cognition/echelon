# General-purpose RE knowledge-quality repair

Status: Proposed — direction approved; written contract awaiting review.
Date: 2026-09-08
Decision owner: Echelon maintainer.

## 1. Outcome and boundaries

Restore useful, LLM-driven reverse engineering for arbitrary declared workspaces.
The deliverable is evidence-backed domain knowledge, individual repository
synthesis, and workspace synthesis that subsequent spec authoring can consume.
Successful scheduling, exact byte accounting, and schema-valid model output are
necessary operational checks, not proof of semantic completeness.

Retain the existing provider abstraction, neutral Prosaic roles, immutable
snapshots, controller-owned state, bounded retries, budgets, and publication
transaction. Repair the knowledge path incrementally; do not replace the whole
engine or add another user-facing protocol selector.

This contract covers deep/full RE. Existing lower-depth results remain valid for
their declared scope, but cannot be relabeled as full analysis. "Complete" means
the requested obligations have been assessed and the required artifacts produced;
it never means that all possible behavior has been mathematically proven.

No paid provider runs, installation, workspace migration, existing-run mutation,
or budget increases are authorized by this design-writing step. Keep existing
OptaSearch publications, source checkouts, and all 12 stashes unchanged. Synthetic
fixtures must contain no copied proprietary source or credentials.

## 2. Evidence motivating the repair

- The sized-reservation pilot accepted ten L4 slices; seven had no structured
  claims because their contexts had no primary or supporting subjects. Some
  observations were useful, but evidence acknowledgement also passed as analysis.
- Real preparation assigns generated domain subjects to `public-surfaces` and
  source subjects to `source-composition`. The planner interprets unassigned
  categories as vacant instead of requiring an applicability assessment.
- The published OptaSearch source and workspace documents are the August 30
  L2-based generation. Later L3 completion with 111 residual findings does not
  update that publication automatically.
- Current synthesis authority accepts L1–L3 parents, not terminal L4 authority.
  L4 status separately reports synthesis and publication as not run.
- The original `echelon.re-specifier` already describes source-owned overview,
  architecture, contracts, components, domain specs, and workspace synthesis.
  Recover this product contract rather than inventing a new document product.

Relevant seams: `protocol_28/preparation.py`, `planning.py`, `artifacts.py`,
`context.py`, `closure.py`, and `status.py`; `protocol_27/authority.py`,
`materialization.py`, and `publication.py`; `harness/re_publication.py`; neutral
RE roles under `prosaic/subagents/`. Protocol paths here identify implementation
seams, not new concepts the operator must learn.

## 3. Options and decision

1. Patch the two planner defects only: small change, but still cannot publish
   the deeper knowledge end to end. Necessary containment, insufficient release.
2. Return entirely to the original engine: useful comparison baseline, but would
   abandon recovery and provenance work without first proving a quality benefit.
3. Repair the existing engine around the original knowledge contract: selected.
   More work than a local patch, but preserves safety and tests the actual product.

Use option 3 in separately testable milestones. Compare against original RE on
the same synthetic inputs; do not assume the original engine is an oracle.

## 4. Required knowledge product

Preserve the existing publication layout:

| Output | Required content |
| --- | --- |
| `sources/<source>/specs/<domain>/spec.md` | Purpose, observed scenarios, behavior, interfaces, data/state, configuration/security, errors/recovery, operations, tests, limitations, source evidence |
| `sources/<source>/overview.md` | Repository responsibility, domain inventory, scope, freshness, depth and debt |
| `sources/<source>/architecture.md` | Internal boundaries, interactions, runtime and deployment shape |
| `sources/<source>/contracts.md` | Owned APIs/events, schema/state contracts, configuration and integration obligations |
| `sources/<source>/components.md` | Applications, workers, stores, integrations, deployment/configuration and test components |
| `workspace/overview.md` | All declared source decisions and system responsibilities |
| `workspace/relationships.md` | Evidence-supported cross-source call/data/deployment flows and unresolved links |
| `workspace/contracts.md` | Producer/consumer contracts, compatibility and observed inconsistencies |
| `workspace/domains/<domain>.md` | Cross-source domain composition where established, linking to source-owned knowledge |

Do not fabricate stories, requirements, performance guarantees, architecture
decisions, or relationships to satisfy a count or heading. Configuration-only
and deployment-only sources need useful source knowledge, not invented product
domains. Empty sources require an explicit inventory disposition. Unavailable
sources may retain old published knowledge only with explicit stale/partial status.

Every factual conclusion must resolve to snapshot evidence or accepted lower-level
claims whose evidence can be followed. Distinguish observed facts, reasoned
inferences, and unknowns. A workspace relationship must cite both endpoint
evidence when available; a one-sided external dependency is not a proven internal
connection. Matching names alone do not prove a relationship.

## 5. Responsibility and execution model

### LLM responsibilities

Discover candidate domains, subjects, behavioral obligations and relationships;
interpret source behavior; identify missing evidence; produce explanations; and
independently critique them. Discovery is a bounded, evidence-grounded proposal,
not authority to change the filesystem or controller state.

### Harness responsibilities

Freeze inputs and scope; validate proposals and evidence references; assign stable
identities; schedule bounded work; provide evidence; enforce resource limits;
persist outcomes; validate contracts; and atomically publish accepted knowledge.
Domain discovery must account for orphan/unassigned inventory and overlaps.
Do not equate a directory name with a business domain or require one language's
parser to recognize every analyzable source.

### Bounded evidence acquisition

The analyst may request a snapshot-relative path, symbol or relationship expansion
with a reason and the affected obligation. The controller resolves it within the
declared frozen inventory, records the request and outcome, and constructs a new
immutable context. No live workspace reads, arbitrary shell access, network
fetching, or undeclared-repository traversal are introduced.

Repeated identical requests reuse the recorded outcome. Denied or unavailable
evidence produces an explicit unknown, not a retry loop. Discovery and acquisition
consume the same run-wide budgets as analysis; each analysis obligation permits
at most two evidence-expansion rounds. More work requires an explicit scoped
continuation, never an automatic increase in limits.

## 6. Subject and category coverage

R1. Every analyzable evidence slice must carry at least one relevant, authenticated
primary or supporting subject. Splitting must preserve the evidence-to-subject
relationship; it must not invent a generic unrelated subject just to pass a gate.
Fail preparation before provider dispatch if this invariant cannot be satisfied.

R2. Assess every existing domain and source category in `protocol_28/policies.py`.
Use LLM discovery and review to establish applicability. Missing catalog entries
or missing parser output are not evidence of non-applicability.

R3. Track exactly-once primary evidence ownership separately from many-to-many
behavioral coverage. Reuse evidence as supporting context across categories;
avoid mechanically multiplying every source byte by the number of categories.
Each category retains an explicit obligation even when several are analyzed in
one bounded context.

R4. Category dispositions are: analyzed, not-applicable, unknown, or not-analyzed.
Not-applicable requires a scoped evidence-backed rationale and independent
review. Unknown carries the missing evidence or interpretation. Not-analyzed is
unfinished work, not acceptable semantic debt.

R5. Zero-claim output is not universally forbidden. Empty/generated/opaque input
may warrant a reviewed disposition. For analyzable behavior, mere inventory,
byte acknowledgement, or "no subject assigned" is a repair/failure condition.

R6. Review within each slice is followed by target-level reconciliation. Slice
boundaries cannot hide missing call chains, contradictions, or category gaps.
Source-level reconciliation connects domains before workspace synthesis connects
repositories. A slice PASS alone cannot certify a domain or source.

## 7. Semantic review and bounded convergence

Deterministic checks establish structural validity, evidence identity, scope,
coverage obligations and resource accounting. Independent LLM review assesses
whether the explanation is supported, substantive, consistent and adequate for
the assigned behavior. Neither check substitutes for the other.

The reviewer receives the candidate, evidence and obligations, not producer
reasoning. Repair feedback names the missing/incorrect behavior and relevant
evidence. Persist feedback so the next permitted attempt sees it after restart.

Retain the current frozen attempt ceilings; do not create nested unaccounted
repair loops. Repeated unchanged outcomes terminate. Authentic semantic uncertainty
may finish with debt only under the existing explicit acceptance policy, including
bounded autonomy where enabled. Provider failure, malformed output, missing
subject authority, unassessed categories or incomplete synthesis remain failures.

Inherited debt stays visible through deeper analysis and publication until a
separate supported closure explicitly resolves it. A successful new slice or
synthesis cannot silently erase or accept debt.

## 8. Synthesis, publication and consumer contract

Add an authenticated terminal-L4 input adapter to synthesis, including source and
domain completion roots, accepted knowledge, category assessments, snapshot and
policy identities, evidence references, and exact debt provenance. Do not merely
add `L4` to the current accepted-layer string set. Validate the complete dependency
chain before dispatch and again before publication.

Generate source synthesis first, then workspace synthesis from the complete
declared-source union. Preserve retained/unavailable/removed source decisions.
Do not silently combine evidence from incompatible snapshots; explicitly mark
retained stale sources and the relationships they affect.

Validate synthesized claims against accepted inputs and review behavioral
omissions and cross-source inconsistencies. Record conflicts as conflicts, not
an invented resolution. Use bounded hierarchical synthesis if the union exceeds
context capacity; summaries must retain claim/evidence and debt references.

Materialize into run-local staging. Publish one immutable generation through the
existing atomic transaction, with a manifest mapping every artifact to its run,
snapshot, input roots, depth, quality and debt. A failed publication leaves the
previous generation intact. Unindexed legacy directories must not appear as
current participants or enter the spec consumer snapshot.

Verify the real spec-authoring RE snapshot consumer receives that generation,
including both source-owned and workspace artifacts and quality limitations.
Do not change the existing publish opt-in or automatically launch downstream
spec/delivery work. The operator should not need a protocol-specific synthesis
command sequence; existing RE lifecycle entrypoints must expose the full path.

## 9. Status and compatibility

Report execution state separately from analysis scope, evidence freshness,
knowledge quality, synthesis state and published generation. A previous publication
must not look like the current active run's output. Show a useful next action
for stopped work; active work must not appear terminally blocked solely because
completion roots have not yet been written.

Scope-complete lower-depth synthesis cannot expose an unqualified full-quality
claim. Full-depth completion requires every selected source's obligations,
source reconciliation, workspace synthesis and required publication gates;
accepted semantic debt changes quality to partial.

Historical ledgers, accepted candidates and publications remain immutable.
Changed semantic contracts require versioned internal identities and a supported
successor/migration route. Preserve old readers and distinguish legacy acceptance
from acceptance under the repaired contract. Existing candidates may be reused
as inputs but receive new certification before satisfying strengthened gates.
Do not auto-adopt the pilot's old 10/10 acceptance as proof of repaired completeness.

## 10. Known-answer evaluation

Create synthetic workspaces, checked-in expected behaviors, and deliberately
defective candidate outputs. Expectations describe semantics and evidence, not
exact prose or fabricated minimum document sizes.

| Fixture | Required facts and negative checks |
| --- | --- |
| Single application | Authentication rejection before mutation; validation bounds; state transitions; retry ceiling and terminal failure; meaningful operator signal. Reject claims that retries are infinite or mutation precedes authentication. |
| Two services | Producer topic/payload and consumer handler; deliberately mismatched schema version; consumer retry/deduplication behavior. Preserve mismatch and do not invent successful compatibility. |
| Deployment/configuration-only source | Service-to-image mapping; required environment configuration; port/health-check wiring. Do not invent user APIs or application domains. |
| Mixed language and limited evidence | Trace a Python/TypeScript boundary where supported; distinguish dynamic/unresolved links and missing tests from absence of behavior. |
| Empty and retained sources | Explicit empty result; stale retained knowledge clearly identified; removed source excluded from current publication and consumer input. |

Exercise real snapshot, preparation, planning, context and publication code. Do
not pre-populate subjects/categories in a way that bypasses discovery defects.
Test evidence split boundaries, including a long file whose key behavior appears
only in later chunks. Cover all seven domain and five source categories.

Two complementary suites are required:

1. Offline deterministic tests with scripted provider outputs: prove routing,
   invariants, rejection, repair persistence, resume, synthesis and publication.
   Include missing subjects, bookkeeping-only outputs, unsupported absence,
   omitted security/recovery, contradictory claims, stale synthesis and a false
   verifier PASS. These tests cannot establish real-model understanding.
2. Explicitly budgeted live evaluation on the same fixtures: measure expected
   behavior recall, claim support, contradiction handling and false acceptance.
   Inspect published prose and evidence, not just candidate counts. Run original
   and repaired RE under the same provider/model and comparable scope and budgets;
   record their actual spend and repeated-run variability.

The small golden suite release gate is every enumerated critical fact represented
with valid support, every seeded contradiction surfaced, every deliberately bad
candidate rejected or repaired, and no unsupported critical claim. Additional
noncritical findings can remain explicit debt. Passing fixtures demonstrates this
test scope, not universal completeness for arbitrary real repositories.

## 11. Milestones and stop conditions

M1 — Prevent false completeness: reproduce subjectless overflow and false category
vacancy through real preparation, repair subject binding and obligation accounting,
and add target-level semantic adequacy/review tests. Keep this a bounded patch.

M2 — LLM-led discovery and evidence expansion: implement the bounded proposal and
request loop, orphan reconciliation, and durable restart behavior. Keep semantic
instructions in neutral roles and dispatch contracts in runtime workflow files.
New or revised agent behavior uses paired ALWAYS/NEVER rules.

M3 — Small complete vertical path: connect terminal deeper authority to source
and workspace synthesis, atomic publication and the actual spec snapshot consumer.
An offline two-service fixture must reach usable published knowledge before
authorizing a new large L4 run.

M4 — Cross-workspace evaluation: run the approved live fixture comparison, then a
representative small real workspace. Only after those pass, request a separately
budgeted OptaSearch validation. OptaSearch is a scale test, not the only oracle.

Each milestone receives a focused implementation plan, regression checks and
review. Do not build a second scheduler, generic agent framework or new parser
platform. If a milestone requires replacing the controller architecture, stop
and review that scope expansion instead of hiding it in a local fix.

Do not install or declare RE repaired after M1 alone. Release readiness requires
the end-to-end product contract and live evaluation; report interim progress as
such. Preserve existing source/stash state throughout every test.

## 12. Trade-offs and consequences

LLM discovery is less deterministic than a directory-derived catalogue; freezing
validated proposals preserves replay but does not make the original interpretation
infallible. Semantic review and target reconciliation add cost, bounded by the
same visible budgets. More honest partial results may initially reduce apparent
completion rates while improving trustworthiness.

The benefit is a workspace-independent contract: useful explanations at domain,
repository and system level, with evidence and explicit limits, rather than an
OptaSearch-specific collection of successful dispatch receipts.
