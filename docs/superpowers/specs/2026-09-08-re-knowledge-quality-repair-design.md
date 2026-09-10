# General-purpose RE knowledge-quality repair

Status: M1 containment and M2 bounded knowledge acquisition are implemented and independently accepted. M2 includes Safe evidence projection, schema-aware category discovery/review, Reviewed protocol-2.8 activation, durable revision/reconciliation/debt authority, conservative configured-provider accounting, and replay-safe restart behavior. The configured-provider bridge remains opt-in; unsupported backends are refused rather than replaced, and installed routing remains unchanged. M3 source/workspace synthesis, publication and consumer integration, refresh, two-action CLI, native-provider isolation, live evaluation, and release readiness remain pending. Not release-ready.
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

RE must select its LLM through Echelon's existing effective configuration and
provider facade, including normal environment overrides. Do not bind the RE loop
directly to Codex or introduce a separate RE provider default. Backend-specific
transport, screening and usage normalization belong behind that shared boundary.
Freeze the resolved provider/model in run authority. If a selected backend cannot
meet the required execution contract, explain the missing capability before
dispatch; never silently substitute Codex or another provider.

This contract covers quick, standard and deep RE through the same product path.
Every depth produces repository knowledge and workspace synthesis. Depth changes
thoroughness, not whether users receive a usable document set. "Complete" means
the selected-depth obligations have been assessed and the validated documents are
available to consumers; it never means all possible behavior has been proven.

### Product contract: two actions, one depth choice

```bash
echelon re run
echelon re run --depth quick
echelon re run --depth deep

echelon re refresh
echelon re refresh --source repoA
echelon re refresh --source repoA --source repoB
```

These are the proposed release interfaces, not claims about the installed CLI.
`run` analyzes the declared repositories and their workspace, reusing valid prior
knowledge. `refresh` updates knowledge affected by local source changes; without
selectors it checks all declared sources. Repeated `--source` values form one
selection and one workspace update, not independent publications.

| Depth | Analysis obligations | Output and review |
| --- | --- | --- |
| `quick` | Discover source roles/domains; inspect representative entry points, declared interfaces, dependencies and deployment/configuration. Record sampling and unexamined behavior. | All source/workspace document families; grounded bounded overview, verified references and independent review of generated claims. No exhaustive claim. |
| `standard` (default) | Trace principal scenarios, state changes, boundaries, configuration/security, recovery and operations in each discovered domain; reconcile source and workspace contracts. | Behavioral knowledge with evidence, category coverage and independent review; explicitly record peripheral gaps. |
| `deep` | Assess all in-scope analyzable evidence and required behavioral categories, including edge cases, invariants, negative space and cross-domain/source reconciliation. | Detailed evidence-backed knowledge and stronger completeness review. Unexamined required work prevents completion. |

All three depths use the same evidence safety, bounded execution and atomic
publication safeguards. Quick review may be batched for speed; it cannot skip
grounding. Actual speed depends on workspace size and provider performance.
Resource exhaustion cannot silently turn a deep request into a quick success.
No fixed story/claim count substitutes for the obligations above.

Both `run` and `refresh` without `--depth` preserve each selected source's
established depth from its published request. Previously unanalyzed sources use
the configured default or standard; changing that default does not downgrade
established knowledge. Resuming a compatible unfinished request preserves its
frozen effective depths. An explicit `--depth` overrides the selection for a new
request. Reusing richer, compatible knowledge for a lighter request is allowed;
never silently replace unchanged deep knowledge with shallow output. If an
explicit lighter run or refresh replaces changed deep knowledge, disclose the
downgrade before dispatch and in the resulting manifest. Record requested and
actually retained depth separately. Mixed-depth workspaces label each source's
depth and the limits of derived conclusions.

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

### Simplify the implementation, not only the command names

Use one operator request, one resolved configuration, one aggregate budget and one
recovery path for analysis and refresh. Depth determines a bounded internal work
plan; it must not require separate operator-created L2/L3/L4 runs or independently
authorized synthesis jobs. Historical protocol readers remain compatibility code,
not competing user workflows.

Reuse existing provenance/recovery primitives where they establish a required
invariant. Do not preserve an internal layer or introduce another receipt type
merely because an old protocol has one. For each proposed stage/state/record, the
implementation plan must identify its correctness or recovery purpose, its owner,
and why an existing record cannot serve it. Collapse duplicate planning, budget,
retry, status and publication handling. No new policy-selection menu is allowed.

## 4. Required knowledge product

Preserve the existing publication layout at every depth. Quick documents may be
short and explicitly bounded, but never just empty headings or inventory counts:

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

### Frozen revisions, invalidation and restart

Complete bounded discovery before publishing the first analysis plan. Discovery
returns subject proposals, inventory ownership, category obligations, evidence
references and unresolved questions. Python validates and content-addresses the
proposal; rejected references never enter an analysis context.

After activation, evidence expansion uses a new immutable revision, not an edit
to a frozen plan or a context with a different evidence set under the same ID:

1. Persist a request keyed by logical run, originating obligation, current plan
   revision, normalized evidence selector and reason class. Resolve only against
   the same frozen source snapshot and recorded security policy.
2. Stage the replacement context, plan, subject catalogue, dependency map and
   invalidation receipt. The receipt identifies previous revision, cause,
   affected obligations, reusable results and invalidated derived results.
3. Validate all identities and publish the revision manifest last. Advance the
   active revision pointer atomically under the existing controller ownership
   lock. Do not dispatch replacement work before this commit.
4. Invalidate every result whose subject/evidence/obligation or policy dependency
   changed, plus transitive target/source roots and synthesized artifacts. If the
   dependency map cannot establish independence, invalidate the containing target.
   Unchanged siblings remain reusable only with a recorded compatibility receipt;
   bind reused evidence explicitly to the new context rather than copying old
   snapshot IDs into a new manifest.
5. On restart, replay the committed revision and request receipt. Reuse resolved
   requests, certified results and settled reservations. Incomplete staging is not
   an active revision. Crash tests cover every boundary above.

Implement revisions using the existing immutable child/run-store machinery and
controller, under one operator-visible logical run; do not introduce a second
scheduler. Historical manifests keep their existing bindings and readers. A
new internal contract is required for revision and compatibility receipts.

All revisions share one aggregate run budget, including unsettled reservations.
An internal child cannot reset that budget. Obligation splits/merges retain their
origin IDs and inherited attempt/expansion counters, preventing counter resets by
renaming work. A source checkout update is a new snapshot refresh request, not
an evidence expansion in an old snapshot.

### Codex CLI resource accounting (approved September 8)

Reuse the existing Codex provider with reservation-and-observed-usage accounting:
reserve from the aggregate run budget before each invocation, then charge its
reported usage. Missing or untrusted usage consumes the conservative reservation
or the larger observed amount. An observed reservation breach blocks further
dispatches and remains visible on recovery; it never raises the authorization,
resets the account or disappears through a retry.

These are admission and accounting limits, not a guaranteed native per-call token
cutoff. An in-flight Codex invocation can exceed its reserved allowance, including
the remaining logical-run allowance. A process deadline and bounded output capture
limit local execution, but cannot guarantee cancellation of remote token spend.
The controller bounds its rendered prompt, including its own framing; that byte
bound is not an exact count of Codex's internally assembled wire request.

Freeze this distinction in a new accounted-Codex execution contract. Preserve
existing offline/API contract identities and stricter guarantees where supported.
The existing normalizer requires complete disjoint usage classes for exact
charging. A native total with an incomplete breakdown remains an untrusted
observation: charge the greater of the reservation and observed total, without
inventing missing usage classes as zero.
This approval changes token-enforcement semantics only: it does not relax source
selection, evidence screening, tool restrictions, reviewer independence, run
ceiling authorization, or the requirement to approve live evaluation separately.

### Evidence security contract

Treat source code, comments, documentation and dependency output as untrusted
data, never instructions to the analyst or controller. The analyst may only emit
typed evidence requests; source text cannot grant tools, change budgets or alter
the allowed source set.

Apply a versioned exclusion and secret-screening policy before provider-context
assembly. Reject path escapes and symlink escapes; exclude credential/key stores
and secret-bearing environment files by default. For otherwise relevant tracked
files, redact recognized secret values while preserving safe configuration names
and surrounding behavior. Record the withheld ranges and limits of the analysis.
Fail closed if safe projection cannot be produced. A redacted value cannot support
a factual claim about the original value.

Retain original evidence identity only in the protected local snapshot store;
give the provider an authenticated safe projection and a mapping receipt. Raw
secret values must not appear in requests, diagnostics, telemetry, rendered output
or publication. Screen provider output before retaining ordinary logs or promoting
artifacts; quarantine unsafe results locally with restricted access and a sanitized
error. Never print matched values. Secret scanning is defense in depth, not a
claim to recognize every possible credential.

Tests plant synthetic canary secrets in tracked config, source literals, exception
text and model output, plus malicious comments requesting filesystem/network
access. Assert the canaries do not reach provider inputs, normal logs, publication
or consumer snapshots and that injected instructions cannot change execution.

## 6. Subject and category coverage

R1. Every analyzable evidence slice must carry at least one relevant, authenticated
primary or supporting subject. Splitting must preserve the evidence-to-subject
relationship; it must not invent a generic unrelated subject just to pass a gate.
Fail preparation before provider dispatch if this invariant cannot be satisfied.

R2. Assess every existing domain and source category in `protocol_28/policies.py`.
Use LLM discovery and review to establish applicability. Missing catalog entries
or missing parser output are not evidence of non-applicability. At quick or
standard depth, explicitly record work outside the requested depth as such; never
convert an unexamined category into not-applicable. Deep requires all categories.

R3. Track exactly-once primary evidence ownership separately from many-to-many
behavioral coverage. Reuse evidence as supporting context across categories;
avoid mechanically multiplying every source byte by the number of categories.
Each category retains an explicit obligation even when several are analyzed in
one bounded context.

R4. Category dispositions are: analyzed, not-applicable, unknown, not-analyzed,
or outside-requested-depth.
Not-applicable requires a scoped evidence-backed rationale and independent
review. Unknown carries the missing evidence or interpretation. Not-analyzed is
unfinished required work, not acceptable semantic debt. Outside-requested-depth
must bind the frozen quick/standard scope and remain visible in the documents;
it is forbidden as an escape from a deep obligation or exhausted resource ceiling.

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
repair loops. Repeated unchanged outcomes terminate. For new simple-workflow runs,
authentic reviewed uncertainty may finish as a visible limitation under the
bounded default described below. Preserve the explicit acceptance policies of
historical runs. Provider failure, malformed output, missing
subject authority, unassessed categories or incomplete synthesis remain failures.

Inherited debt stays visible through deeper analysis and publication until a
separate supported closure explicitly resolves it. A successful new slice or
synthesis cannot silently erase or accept debt.

### Newly discovered L4 debt

The current `PASS` prohibition on unknown/unresolved observations remains valid
for the legacy contract. Do not weaken it globally. The repaired contract adds
an explicit reviewed-with-debt outcome and typed acceptance receipt:

- Eligible debt: a specifically investigated ambiguity in product intent, an
  unresolved dynamic/external dependency, or unavailable permitted evidence.
  Record the attempted analysis, reason, evidence boundaries, affected claims and
  source/target IDs. Unsupported factual claims must be removed or revised into
  explicit unknowns before this outcome is eligible.
- Ineligible debt: work never attempted, dropped categories/evidence, absent
  subjects, invalid contracts, provider/resource failure, unsafe disclosure or
  unfinished reconciliation/synthesis. These remain blocked or paused.
- Independent review first certifies the supported content and eligibility of
  the exact debt set. For new simple-workflow runs, the normal invocation permits
  recording evidence-backed uncertainty as a limitation without asking the user
  to adjudicate every finding. Show this behavior before dispatch and bind it in
  the run configuration. Do not infer the same permission for a historical run.
- This bounded default cannot choose business intent, assert an unknown security
  guarantee, expand source access, or waive unfinished work. Keep disputed behavior
  unknown. Ask for input only when a decision is necessary to continue producing
  a valid requested output, not merely to turn uncertainty into certainty.
- Record the default authorization or explicit user decision, candidate/review
  hashes, snapshot, obligation IDs and exact debt IDs in an acceptance receipt.
  Existing L3 debt acceptance alone never authorizes new L4 debt on a legacy run.
- A slice with that receipt is usable as `accepted_with_debt`, not ordinary
  `PASS`. Target/source/run roots authenticate the union of ordinary acceptances
  and debt-backed acceptances. Quality is partial and completion is
  `complete_with_debt` for the full logical request only after all other
  obligations and synthesis are done. Layer-local roots retain their narrower
  completion scope.
- Synthesis and publication retain those exact receipts. Debt disappearing from
  a document does not close it. Any closure must have new evidence and a reviewed
  closure receipt. A new snapshot alone does not invalidate existing acceptance:
  carry forward a limitation only with a compatibility receipt proving that its
  evidence dependencies, obligation/scope, applicable policies and authorization
  conditions remain unchanged. Bind that receipt to both snapshots and the exact
  original debt/review/acceptance lineage; it is neither a new debt acceptance nor
  a closure. Changed or unproven dependencies or conditions require reassessment
  of the affected limitation under current authorization, preserving provenance.

These rules apply equally to new semantic debt identified during reconciliation
or synthesis. A finished synthesis that accurately describes uncertainty differs
from missing synthesis work. The normal new-workflow invocation authorizes atomic
publication of validated results with these visible limitations. It does not
authorize publishing incomplete required work or a raced/stale selected snapshot.
Legacy manual/debt-publication contracts remain unchanged for historical runs.

## 8. Synthesis, publication and consumer contract

Synthesis consumes a common validated knowledge view with requested depth, source
and domain results, category assessments, snapshot/policy identities, evidence
references and exact limitations/debt. Quick and standard can synthesize and
publish when their own obligations finish; they must not run deeper stages just
to unlock publication. Adapt existing lower-stage outputs only when they meet the
selected-depth product contract, not merely because a legacy stage says complete.

For deep results, add the missing authenticated terminal-L4 input adapter to that
same view, including source/domain completion roots and the complete dependency
chain. Do not merely add `L4` to an accepted-layer string set. Validate adapted
inputs before dispatch and again before publication; do not create separate
quick, standard and deep synthesis/publication engines.

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
New ordinary `run` and `refresh` commands publish validated results automatically.
Their success is not reported until the atomic generation is available to the
consumer. This supersedes the earlier proposed publish opt-in for new runs only.
Do not automatically launch downstream spec/delivery work or change the manual
publication semantics of historical runs. An optional advanced staging-only mode
is not required for the first repair release.

## 9. Status and compatibility

Report execution state separately from analysis scope, evidence freshness,
knowledge quality, synthesis state and published generation. A previous publication
must not look like the current active run's output. Show a useful next action
for stopped work; active work must not appear terminally blocked solely because
completion roots have not yet been written.

Scope-complete lower-depth synthesis cannot expose an unqualified full-quality
claim. Full-depth analysis completion requires every selected source's obligations,
source reconciliation, workspace synthesis and validation of publishable outputs.
Publication is an internal atomic transition of the normal workflow; accepted
semantic debt changes quality to partial. Never show ordinary success while
publication is pending or failed. Preserve the previous usable generation on
analysis or publication failure.

Historical ledgers, accepted candidates and publications remain immutable.
Changed semantic contracts require versioned internal identities and a supported
successor/migration route. Preserve old readers and distinguish legacy acceptance
from acceptance under the repaired contract. Existing candidates may be reused
as inputs but receive new certification before satisfying strengthened gates.
Do not auto-adopt the pilot's old 10/10 acceptance as proof of repaired completeness.

### Operator journey and release routing

At release, route new ordinary runs and refreshes to the repaired engine. Until
the release gate passes, leave installed defaults unchanged. Existing runs always
resume through their pinned reader/engine. Keep explicit legacy engine options
for compatibility and comparison, not as prerequisites for ordinary use.

For both `run` and `refresh`, resolve depth per source: explicit
`--depth quick|standard|deep`, otherwise established published depth, otherwise
workspace default, otherwise standard. Preserve frozen depths when resuming as
defined in section 1. Map an explicit legacy `full` depth to deep without rewriting
old run manifests. An unrecognized legacy setting needs one actionable migration
message, not guessed behavior.

Existing resource profiles and ceiling flags remain advanced compatibility
controls, not additional ordinary choices. For the initial implementation, reuse
the existing new-request balanced ceilings: 5,000,000 tokens and 180 active minutes,
unless explicit workspace/CLI authorization supplies different finite ceilings.
Depth must not silently multiply those limits. Any revised release defaults need
evaluation and approval, and never raise existing run authorizations. Depth
controls analysis obligations; budgets only bound execution. Display effective depth,
source selection, provider and aggregate limits before dispatch. Reject conflicting
advanced settings that disable a required gate rather than silently reduce quality.

| User action | Repaired behavior |
| --- | --- |
| `echelon re run [--depth quick\|standard\|deep]` | Analyze declared sources and workspace, preserving established per-source depths unless explicitly overridden and reusing adequate current knowledge; validate and publish automatically. |
| `echelon re refresh [--depth quick\|standard\|deep]` | Check all declared sources for changes, update affected knowledge and synthesis, then validate and publish automatically. Preserve existing depths unless explicitly overridden. |
| `echelon re refresh --source repoA [--source repoB ...]` | Check the selected repositories, update their changed knowledge and affected workspace/source views, then publish one validated generation with honest retained-input limitations. No forced reanalysis when inputs are unchanged. |

Manual deepening, synthesis, publication, policy selection and banzai/resume modes
are not steps in these journeys. Legacy/diagnostic commands can remain available
under advanced help, routed according to pinned contracts. Historical explicit
`publish --allow-partial` permissions do not weaken the new workflow's gates.
Update basic CLI help and README to lead with the two actions and depth alone.

The existing `--re-token-limit` and `--re-time-limit-minutes` options and configured
resource limits remain absolute logical-run ceilings, including discovery,
analysis, review, revisions and synthesis. No hidden fresh allowance per layer.
An insufficient ceiling produces a resource pause with accepted work preserved.

The primary UI has four outcomes: running, completed, completed with limitations,
and needs attention. Running progress names the stage, repository, finished/total
work when known, and recent activity. Needs attention names the reason and one
safe next action. Internal paused, blocked, guidance, debt and publication states
remain in machine-readable diagnostics; do not flatten their recovery semantics.
Completion includes the published generation and effective scope/depth. Limited
sampling is labelled as quick depth; additional material unknowns, accepted debt
or unchecked retained sources yield completed with limitations. Lower-stage
completion is never reported as the ordinary command's completion.

Reissuing the same action resumes an interrupted compatible request automatically
without duplicate dispatch or reset counters. A live compatible controller is
observed, not duplicated. Exhausted budgets, terminal failures or decisions that
need the user remain needs attention; repeating the command cannot reset them.
If selected inputs changed and the old controller is stopped, the user action
creates a new immutable refresh request, preserving old work and displaying the
new snapshot/limits. Do not resume an old snapshot as if it represented new code.
If an incompatible controller is active, leave it untouched and explain the
conflict. No manual `--reset` or protocol-specific successor command is required
for the normal stopped-run/update case.

If a recoverable publication write/transaction failure occurs with unchanged
selected inputs and expected generation, retry only that safe transaction on the
next identical action; do not repeat provider work. First check whether the same
validated manifest already committed: return that generation without incrementing
it. A competing publication is different: reconcile against the latest generation
as specified in U7, reusing only still-valid analysis and regenerating affected
synthesis before a new atomic publication attempt. Do not repeatedly retry an
obsolete expected generation. Recovery retains the logical request's charged
budget and finite attempt counters; exhaustion or unsafe reconciliation produces
needs attention, not a fresh allowance or an endless conflict loop.

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
   Include missing subjects, unassessed obligations and stale synthesis. A false
   verifier PASS must be rejected when it contradicts a deterministic invariant.
   Script semantic repair verdicts only to test their routing and persistence;
   do not claim those tests prove detection of omitted or invented behavior.
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

### Independent scoring and repeated-run release gate

Store the expected facts, forbidden claims, evidence references, depth and criticality in
an evaluation-only manifest outside the source snapshots and production prompt
inputs. Freeze it before a trial. Producers and in-run reviewers cannot read the
manifest or previous trial scores; do not include fixture names that disclose the
expected answer in their task instructions.

Score the actual published source/workspace documents. For each expected fact,
record supported, missing, contradicted, or appropriately unknown. A supported
fact must match its scope and resolve to the expected evidence; matching words
or headings is insufficient. For each planted defect, score whether the live
reviewer rejects/repairs it or incorrectly accepts it. Include bookkeeping-only
knowledge, omitted authentication/retry behavior, unsupported absence and
contradictory cross-source contracts as semantic mutation challenges.

Use a separate evaluation context without producer/reviewer conversation; model
judging may assist but cannot alone sign off the release. An engineer reviews
every critical score and the evidence supporting it and records the rationale.
Freeze provider/model, prompts, policies and fixture revision for each comparison.
Run three independent repaired trials per fixture and three original-engine
baseline trials under the same per-trial caps and declared comparable scope.
All repaired trials must meet the critical-fact/defect gate for the requested
depth. Freeze quick/standard/deep expectation sets before trials; quick must
produce useful source/workspace knowledge without being scored as exhaustive.
Unsupported claims and failure to disclose limited scope fail at every depth.
Report every
trial, noncritical recall, false acceptance, token/time cost and operational
failures; do not average away a critical failure or repeatedly retry until green.
After a change, repeat the affected fixtures and the end-to-end two-service gate.
Every live batch requires explicit authorization of its cumulative maximum spend.

### Live two-version refresh gate

Static fixture evaluation and scripted update tests are not sufficient for
release. At each supported depth, include a real-model A1-to-A2 two-service trial:
run the ordinary `re run` on A1, commit A2 locally, then use only `re refresh`.
Change a behavior and a published API/event schema, remove a previously documented
path, and leave consumer repoB unchanged so a cross-source mismatch must be found.
Use synthetic source content only; no remote fetch or proprietary source is needed.

Freeze separate A1 and A2 evaluation-only manifests before the trial. Apply the
same hidden-answer isolation, independent scoring and three-trial release gate
above to the complete initial-run-plus-refresh sequence, including the comparable
original-engine baseline. Count both stages and any bounded recovery in each
trial's spend and the explicitly authorized aggregate batch maximum; the update
stage does not receive an unapproved extra allowance.

Inspect the actual published source and workspace documents, not just routing or
changed hashes. All depth-required A2 facts must be supported; obsolete A1 claims
must be absent as current facts (clearly labelled historical comparisons are
allowed). The new contract mismatch must appear in affected source/workspace
views, unaffected facts must remain sound, and current citations must resolve to
the proper new or authenticated retained evidence. Start an actual spec consumer
before and after refresh: the older consumer retains its pinned A1 generation,
while the newer consumer receives the A2 source/workspace generation. Every trial
must pass both initial and refreshed quality gates; refresh correctness cannot
be inferred from a successful static analysis or a scripted provider response.

## 10a. Source updates and incremental refresh

### Current implementation audit (2026-09-08)

This is observed behavior, not the promised repaired behavior:

- `re run` defaults to v1. Its changed-source planner compares published source
  fingerprint, profile, usable publication and quality-contract version. A Git
  source fingerprint includes local HEAD and relevant dirty-state content, so a
  local pull advancing HEAD invalidates that source even if the diff is small.
- It schedules selected stale sources and workspace synthesis, retaining reusable
  source knowledge. Publication is separate for `run`. The original
  `re refresh --source <id>` forces one source and publishes on success.
- Forced targeted refresh deliberately does not fingerprint sibling checkouts:
  it substitutes their published fingerprints and marks usable siblings current.
  A synthetic changed-repoB reproduction confirms repoB is reused/current even
  when its live fingerprint differs. This label must not imply checked freshness.
- The targeted refresh command directly enters the v1 lifecycle. With a current
  v2 marker it refuses through the v1 engine guard; it is not an incremental
  refresh path for the new L3/L4 knowledge chain.
- Spec authoring attaches the latest published immutable generation, not the live
  source tree. Neither a pull nor spec startup refreshes RE automatically. Already
  started spec runs retain their attached generation.

Evidence: `src/echelon/cli.py:_cmd_re_run/_cmd_re_refresh`,
`src/harness/re_fingerprint.py:_fingerprint_git_source`,
`src/harness/re_planner.py:build_re_execution_plan`,
`src/harness/re_lifecycle.py:_require_v1_engine`, and
`src/harness/published_re_context.py:attach_published_re_context`.

### Required refresh contract

U1. RE does not fetch, pull, merge, switch branches or alter source repositories.
It analyzes the user's local checkout. Updating remote-tracking refs without
changing local source inputs does not change the analysis. Changed local HEAD,
source content, declared-source topology, effective depth, evidence/security
policy or semantic contract triggers a freshness decision. Clean source snapshots
remain required for the repaired engine; refuse dirty selected sources before
dispatch, leaving the user's changes and stashes alone.

U2. After a local repoA update, compare the new snapshot with the publication's
recorded inputs, not only with the last attempted run. Compute additions,
modifications, removals, renames and relevant configuration/dependency changes.
Content identity is the basis for evidence reuse; record commit identity as
provenance and invalidate history-derived claims when their history input changes.
Record analysis-policy and prompt-contract identities in reuse decisions.

U3. First implement safe source-granular invalidation: reanalyze changed repoA,
reuse proven-current independent sources, and rebuild source/workspace synthesis
whose inputs changed. Do not promise per-file savings before the dependency graph
can prove independence. Once proven, finer reuse must invalidate claims and
obligations transitively through evidence, imports/callees, schemas/configuration,
domain ownership and negative-space scope. A new file can invalidate an old
absence claim even though every previously cited file is unchanged. If dependency
information is incomplete, reanalyze the containing source; never assume unchanged.

U4. A changed repoA contract invalidates cross-source conclusions even if repoB's
checkout is unchanged. Reuse repoB's intrinsic code facts, but revalidate derived
compatibility/relationship claims against the new repoA evidence. Refresh affected
repoB synthesis and workspace documents. Record missing consumer evidence as an
unknown; do not claim compatibility from the old producer contract. Every such
derived claim must record cross-source input roots, not just its owning repo's hash.

U5. `re refresh --source repoA --source repoB` selects the union for freshness
checking and reanalysis, not a sequence of independent publications. With only
repoA selected, it does not grant fresh source reads of repoB. Revalidate
relationships against repoB's authenticated publication/snapshot and label its
checkout freshness `not_checked`, never `current`. The normal command can publish
a validated generation with that clearly described limitation; it cannot claim
a current-whole-workspace result. If missing sibling evidence prevents a valid
requested product, show needs attention and recommend `echelon re refresh`.
Do not silently broaden source-read scope. A selector-free refresh checks all
declared sources and avoids the unchecked-sibling limitation when they are available.

U6. Removed/renamed files or domains must not leave orphan claims, duplicate domain
documents or stale citations in the new generation. Reconcile staged artifacts
against the new manifest; preserve old generations/run objects for provenance.
Removed declared sources leave the current union; unavailable declared sources
remain explicitly retained/stale, with affected relationships marked uncertain.
Retained debt is reusable across snapshots only with the compatibility receipt
defined in section 7: prove unchanged evidence dependencies, obligation/scope,
policies and authorization conditions and retain the original acceptance lineage.
Changed or unproven compatibility requires reassessment of affected debt under
current authorization, not silent carry-over or closure. An unrelated repoA change
does not by itself require reopening independently supported repoB debt.

U7. New source knowledge and all affected synthesized views publish atomically as
one generation. Before publication, recheck selected live inputs and the expected
publication generation. Changed selected live inputs prevent publishing the
prepared snapshot; show needs attention and use the stopped-run/new-input recovery
above on the next action. A competing publication generation rejects the stale
transaction but is eligible for bounded reconciliation on the next identical
action: read the latest generation, retain its newer source knowledge, and reuse
prepared analysis only where its input/depth/contract roots remain compatible with
the current selected snapshot. Recompute the affected source/workspace synthesis
against the reconciled union, validate it, then atomically publish with the newly
expected generation. Do not overwrite newer knowledge with obsolete prepared
results or read additional live sources beyond the selection. Recheck selected
inputs and generation at commit; another race consumes the remaining finite
recovery allowance, never resets counters. If reconciliation cannot prove safe
reuse or finish within the existing budget/attempt ceilings, show needs attention
with the conflict and a safe next action. A known-raced selected snapshot is not
an automatically acceptable limitation. Historical publication remains an advanced
operation, not the suggested remedy in the normal workflow. Do not combine
incompatible roots as though they were one current snapshot.

U8. A second `re run` or `re refresh` is a no-op with zero provider calls and no
generation increment only when inputs, effective depth, contracts, accepted debt
and publication-relevant source-selection, freshness and retained-source decisions
are unchanged. Check timestamps alone do not require a new generation.
If a whole-workspace check verifies previously unchecked retained sources against
their recorded inputs, reuse the valid analysis but publish the changed freshness
decisions and affected source/workspace status text atomically under U7. For a
freshness-only change, use validated metadata/status rendering without provider
calls; do not reanalyze unchanged behavior or silently leave the old limitation in
consumer documents. Remove only the now-disproved unchecked-source limitation,
not independently accepted semantic debt; preserve historical generations.
Accepted partial quality alone does not trigger endless reanalysis; explicit
advanced reevaluation, a deeper request or changed relevant inputs are required
to reopen it. Failed unaccepted work is not reusable as successful knowledge.

U9. New spec runs use the newly published generation; existing spec runs keep their
pinned generation. The consumer displays snapshot/quality provenance but does not
automatically refresh RE or mutate running spec context. Do not promise automatic
freshness checking during spec startup as part of this repair.

### Update acceptance scenarios

Use local temporary Git repositories and scripted providers for the deterministic
suite; no external origin is required. These tests prove lifecycle and reuse
invariants, not real-model explanation quality; the live two-version gate in
section 10 is separately mandatory. Include the ordinary full lifecycle, not only
planner unit tests:

- Run `echelon re run` for repoA at A1, commit a behavior change at A2, then invoke
  `echelon re refresh`: revised source facts and workspace synthesis both reflect
  A2 in the automatically published generation. No manual deepen/synthesize/publish
  call is permitted in this acceptance test. Unaffected sources are reused.
- Change repoA's event schema with unchanged repoB: reject old compatibility,
  surface the mismatch in affected source/workspace documents, and retain sound
  repoB code facts. Missing dependency metadata forces conservative reanalysis.
- Add a recovery path/new file: invalidate old negative-space claims. Rename and
  delete files/domains: no stale current citations or duplicated knowledge.
- Advance remote-tracking refs without changing checkout: no content-analysis
  refresh. Change only commit/history inputs: revalidate history-derived facts and
  preserve reuse of proven-identical content facts.
- Targeted repoA refresh with changed repoB: repoB remains explicitly not checked;
  an otherwise valid product completes with limitations, never a full-current
  claim. A selector-free refresh checks both and updates affected knowledge.
- After a targeted repoA refresh publishes repoB as not checked, leave both
  checkouts unchanged and run a selector-free refresh. Verify repoB matches its
  retained inputs and publish one new generation with corrected freshness and
  source/workspace status text, without provider calls. New spec consumers receive
  the corrected generation; existing consumers remain pinned. Preserve unrelated
  semantic debt. Repeat the full refresh: no provider calls or further generation
  increment merely because the check timestamp changed.
- Select repoA and repoB together: preserve each depth, update the union and
  workspace synthesis in one generation. A failure in required selected work
  leaves the preceding publication intact.
- Change selected source inputs after analysis: reject stale publication and
  preserve the latest usable generation; repeating the action plans the new inputs.
- Race another publisher that updates an independent source: reject the obsolete
  transaction, then repeat the action and reconcile against the winner. Preserve
  its newer knowledge, reuse compatible analysis, regenerate affected synthesis
  and publish against the new expected generation. A same-source incompatible
  update cannot be overwritten with old prepared results. Repeated races exhaust
  finite recovery attempts without resetting budget or looping forever.
- Repeat with unchanged accepted debt and other U8 inputs: no provider calls.
  Change repoA while independently supported repoB debt is unchanged: carry repoB's limitation with
  a compatibility receipt and its original acceptance lineage, without rerunning
  repoB analysis. Change that debt's evidence, scope, policy or authorization
  conditions: reassess affected debt without erasing provenance. Missing proof
  of compatibility must not pass as unchanged acceptance.
- Start spec S1 before and S2 after refreshed publication: S1 retains the old
  immutable generation and S2 receives the new one with source/workspace views.

### Simple-workflow acceptance scenarios

- Run a fresh fixture at each depth using only `re run --depth <depth>`: all
  required document families and consumer context exist after that command. The
  quick result is useful and explicitly bounded, not an inventory-only baseline.
- Run a previously unanalyzed source without depth/configuration: standard is
  selected and displayed. Both run and refresh without depth retain existing
  per-source depths, including mixed-depth inputs. Analyze repoA at deep, change
  it, then issue plain `re run`: repoA remains deep even if the workspace default
  is standard; newly added repoB uses that default. An explicit lighter request
  discloses any downgrade and never silently discards compatible richer knowledge.
- Request deep with insufficient remaining budget: needs attention with saved
  progress, no shallow success and no increase of the ceiling.
- Interrupt each stage, then repeat the same action: recover without duplicate
  provider work or new per-layer budgets. A still-active controller is not duplicated.
- Fail a publication write with unchanged inputs and expected generation, then
  repeat: only publication is retried; the old generation remains available until
  the transaction succeeds. A committed manifest with a lost acknowledgement is
  returned without a second generation. A competing generation instead follows
  U7's bounded reconciliation tests, not this publication-only retry path.
- Exhaust semantic repair with a reviewed honest unknown: publish completed with
  limitations without a banzai/policy-selection step. A missing mandatory artifact,
  unsupported factual claim or unsafe output must not take that path.
- Assert basic help explains only run, refresh, source selection and depth. No
  ordinary success or recovery message requires choosing a protocol or layer.

## 11. Milestones and stop conditions

M1 — Prevent false completeness: reproduce subjectless overflow and false category
vacancy through real preparation, repair subject binding and obligation accounting,
and add structural false-PASS regression tests. Until M2 supplies reviewed category
assessments, unassessed categories block full completion rather than becoming
vacant. Keep this a bounded containment patch, not a claim of complete repair.

M2 — LLM-led discovery and evidence expansion: implement the bounded proposal and
request loop, orphan reconciliation, atomic revision/invalidation receipts,
aggregate accounting and durable restart behavior. Implement evidence security,
target/source semantic reconciliation and the explicit new-debt acceptance path
here, before any live validation. Keep semantic instructions in neutral roles and
dispatch contracts in runtime workflow files. New or revised agent behavior uses
paired ALWAYS/NEVER rules.

M3 — Small complete vertical path: connect terminal deeper authority to source
and workspace synthesis, atomic publication and the actual spec snapshot consumer.
Unify new-run and refresh routing and automatic publication, retaining the
installed default until release. Implement the two-action CLI and depth contracts;
legacy commands remain compatibility paths, not required orchestration steps.
Implement source-granular incremental invalidation and the deterministic section
10a update acceptance scenarios, including cross-source dependencies and stale-sibling
handling. Fine-grained optimization is deferred until compatibility receipts can
prove reuse. An offline two-service fixture must reach usable published knowledge
before authorizing a new large L4 run.

M4 — Cross-workspace evaluation: run the approved live fixture comparison, then a
representative small real workspace. Only after those pass, request a separately
budgeted OptaSearch validation. OptaSearch is a scale test, not the only oracle.
Apply the independent per-depth scoring and three-trial gate, including the
mandatory real-model A1-to-A2 refresh sequence and actual spec-consumer checks in
section 10. Scripted refresh tests alone cannot satisfy this release gate. Change
ordinary creation and refresh defaults only after release approval. Document
pinned-run compatibility and the two simple user journeys in CLI help and README
together. Release is
blocked if a fixture passes only by issuing manual deepening, synthesis,
publication or policy-selection commands.

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
