# Echelon Service and Workflow Robustness Review

**Review date:** 2026-07-23  
**Reviewed HEAD:** `4fc722d2`  
**Primary concern:** stable execution through deterministic, single-purpose
phase nodes rather than large agents, large roles, or controller code that
performs several workflow responsibilities implicitly.

## Executive Assessment

Echelon is substantially safer than it was at the first EGR review. The EGR
program has added deterministic result validation, state-update ownership,
workflow validation, Understanding and Lexicon nodes, immutable evidence,
bounded repair, execution locks, checkpoints, target ownership, provider
boundaries, and independent RE lifecycle controls. These changes are not
cosmetic. They have moved important failure decisions out of prompts and into
code.

The remaining stability risk is architectural concentration. Echelon's local
contracts are often strong, but its end-to-end behavior is still represented in
several places:

- `extension/workflow/definition.yaml`;
- phase dispatcher files under `extension/workflow/phases/`;
- large invariant role prompts under `extension/agents/`;
- routing guards and post-dispatch gates in `src/harness/squad.py`;
- compound executor behavior in `src/harness/squad_executors.py`;
- recovery and lifecycle inference in `src/echelon/cli.py`;
- separate spec, RE, and delivery controllers.

That makes Echelon robust at many individual boundaries but not yet uniformly
deterministic as a whole. The next architectural step should be to make the
workflow graph the only phase-order authority and make every certification,
repair, fan-out, and join visible as a typed node.

The recommended target is not "fewer agents" as a raw count. It is fewer
responsibilities per dispatch, fewer modes per role, fewer hidden controller
transitions, and fewer places that can decide what happens next.

## Grounded Evidence

### Improvements already working

The strongest current patterns are:

- `phase1-lexicon` and `phase1-understanding` are provider-free nodes with
  controller-owned evidence and state.
- Agent results are validated against per-dispatch verdict and state-update
  contracts before state mutation.
- Invalid registered journal entries are quarantined.
- Phase A readiness, publication, execution locking, checkpoints, product
  inputs, implementation targets, and RE publication have deterministic
  boundaries.
- Provider failures and missing `echelon_result` blocks preserve enough state
  for bounded recovery in many high-value paths.
- The focused graph/controller suite passed:

  ```text
  327 passed in 29.49s
  ```

  The suite covered phase graph, workflow validation, condition evaluation,
  executor contracts, and squad-controller integration.

### Concentration and representation pressure

Current core module sizes are a useful architectural signal:

| Module | Lines | Primary pressure |
|---|---:|---|
| `src/echelon/cli.py` | 9,224 | command parsing, lifecycle selection, recovery, status, compatibility |
| `src/harness/ralph.py` | 6,082 | delivery build/recovery/convergence behavior |
| `src/harness/squad.py` | 3,230 | phase execution, routing, guards, gates, recovery, publication, telemetry |
| `src/harness/re_controller.py` | 3,151 | RE scheduling, validation, repair, publication, lifecycle state |
| `src/harness/squad_executors.py` | 1,850 | prompt assembly plus seven execution semantics |

The largest active role prompts are also broad:

| Role | Lines | Current modes/responsibilities |
|---|---:|---|
| CARTOGRAPHER | 565 | rich spec authoring, derived Lexicon authoring/repair, diagnostics, product-input mapping |
| AUDITOR | 495 | several learning/audit output families |
| SAGE | 466 | WHY1, WHY2, WHY3 |
| GATEKEEPER | 400 | ASSESS and ASSESS2, estimates, feasibility, implementability |
| ARCHITECT | 389 | architecture, plans, ADRs, technology evidence |
| ORCHESTRATOR | 378 | PLAN and PLAN2, tasks, dependency repair, input mapping |

Large files are not automatically defects. Here they correlate with repeated
EGR incidents where a role or controller had to remember which subset of its
behavior applied in a particular phase.

### System-level validation drift

`bash scripts/bash/dry-run.sh` passed 138 checks with one warning, but its state
machine simulation still prints the simplified sequence:

```text
INIT → SCOUT → SAGE1 → CARTOGRAPHER → SAGE2 → GATEKEEPER
→ ARCHITECT → ORCHESTRATOR → SAGE3 → FINALIZE
```

That is not the executable Phase A graph. It omits visible current nodes
including SYNTHESIZER, MODELER, TRACKER, CHIEF, Lexicon, Understanding,
specialists, SENTINEL, ASSESS2/PLAN2 behavior, checkpoints, and documentation
finalization. It also prints VALIDATOR as a simulated ninth step although that
is not the corresponding forward-path node.

This is direct evidence that Echelon still permits more than one representation
of the workflow. A validation tool can pass while describing the wrong system.

## Architectural Findings

### R1 — P0: the executable graph is not yet the sole routing authority

`SquadController` applies `_guard_spec_lexicon_evidence()`,
`_guard_understanding_evidence()`, `_apply_phase_recommendation_guard()`, and
`_guard_constitution_provenance()` before dispatch. It also performs terminal
publication/readiness routing and several recovery rewrites.

Some guards are valuable invariants. The problem is that they can change the
current phase outside the graph. EGR-084 already demonstrated the failure mode:
the constitution provenance guard skipped required graph phases. The fix
adjusted the parallel controller model; it did not eliminate that model.

**Required direction:** controller guards may block a node, but should not select
a different workflow node. Prerequisites should be explicit deterministic nodes
or declarative preconditions with graph-defined failure edges.

### R2 — P1: compound nodes hide independent resume and certification points

`phase3-consensus` is one `staged_parallel` node containing three materially
different operations:

1. WHY3 qualitative cross-artifact review;
2. ASSESS2 feasibility and estimate revision;
3. PLAN2 task repair after both prior results.

The node has a join prerequisite, several artifact owners, different verdict
vocabularies, different state ownership, task Lexicon post-validation, and
multiple backward edges. A provider failure after one expensive Stage 1
dispatch or during PLAN2 requires compound-node recovery logic rather than
ordinary node resumption.

`phase3-specialists` similarly combines selection, cap enforcement, sequential
fan-out, optional parallelism, six specialist contracts, result aggregation,
and timing transition behavior.

**Required direction:** split compound execution into graph-visible nodes:

```text
consensus-understanding
  → consensus-why3
  → consensus-assess2
  → consensus-join
  → consensus-plan2
  → tasks-lexicon
  → consensus-route
```

Specialists should use a deterministic `specialist-plan` node, one resumable
dispatch node per selected specialist, and a deterministic `specialist-join`
node. Dynamic fan-out is acceptable; invisible fan-out is not.

### R3 — P1: deterministic validators are inconsistently represented

Spec Lexicon and Understanding are visible nodes. Tasks Lexicon, feasibility
structural validation, and intent-alignment structural validation are
post-dispatch hooks inside `SquadController._evaluate_transitions()`.

This creates two execution models for the same architectural concept:

- visible provider-free certification nodes;
- hidden validators that mutate a model result before transition evaluation.

The hidden model makes status, checkpointing, rerun, telemetry, repair counts,
and operator explanations less consistent.

**Required direction:** every artifact certification should be a first-class
node with the same contract:

- immutable input artifact and source hash;
- deterministic report artifact;
- controller-owned verdict;
- bounded repair counter;
- explicit author/repair edge;
- checkpoint and telemetry event;
- no agent authority over the certification field.

Initial candidates are `tasks-lexicon`, `feasibility-structural`,
`intent-alignment-structural`, estimate consistency, product-input traceability,
documentation currency, and Phase A publication readiness.

### R4 — P1: unresolved routing can still become an LLM decision

`ConditionEvaluator` intentionally returns `None` for unknown values.
`SquadController._evaluate_transitions()` can then dispatch COMMANDER for a
judgment. This is useful for genuinely semantic choices, but it also turns
missing state, misspelled fields, unexpected result shapes, or incomplete
condition models into nondeterministic routing.

EGR-025, EGR-083, EGR-094, and several no-progress EGRs show how often routing
bugs originate in condition semantics rather than real judgment.

**Required direction:** classify transitions at workflow-compile time:

- `deterministic`: every referenced field is typed and must evaluate to true or
  false; unknown is a blocking contract error;
- `semantic-decision`: points to a dedicated decision node with a typed output
  enum and explicit evidence;
- `human-decision`: points to a human gate.

Do not use COMMANDER as the fallback for an indeterminate deterministic
condition.

### R5 — P1: workflow validation covers syntax better than executable semantics

`workflow_validator.py` explicitly validates only the top-level `phases` graph.
The repository also carries build, bugfix, codegen, verify-spec, and RE workflow
sections or lifecycle implementations. `PhaseGraph` accepts the node `type` as
a string and ignores unmodeled YAML fields; runtime falls back to COMMANDER when
no executor exists for a type.

The current validator catches many useful errors, but it does not yet prove:

- every node type has a registered executor;
- no YAML phase field is silently ignored;
- every required artifact has one owner and a schema;
- every backward edge has a bounded repair policy;
- every compound stage has durable completion identity;
- every executable lifecycle uses an equivalent contract level;
- the documented/dry-run path equals the loaded graph.

**Required direction:** compile all workflow definitions into one typed
intermediate representation and fail on unknown fields, unknown node types,
unowned outputs, ambiguous writers, unbounded cycles, and non-resumable joins.
Generate roadmap, dry-run simulation, Mermaid, status output, and docs tables
from that representation.

### R6 — P1: multi-mode roles remain too broad

SAGE, GATEKEEPER, and ORCHESTRATOR are each reused across phases with modes that
change what evidence they read, what artifacts they may write, and what verdict
means. CARTOGRAPHER combines canonical spec authoring with derived artifact
authoring, diagnostic interpretation, repair, and product-input traceability.

This saves role files, but it increases prompt branching and makes a valid
response depend on remembering the current mode after long tool output. That is
exactly where missing result blocks, wrong state keys, wrong output shapes, and
provider no-progress failures tend to appear.

**Required direction:** keep domain reasoning identities if they are useful, but
dispatch phase-specific protocols:

- `assumption-challenger` instead of SAGE WHY1;
- `spec-quality-interpreter` instead of SAGE WHY2;
- `cross-artifact-consistency-reviewer` instead of SAGE WHY3;
- `feasibility-assessor` and `implementability-assessor`;
- `task-author` and `task-repairer`;
- `spec-author` separate from `lexicon-projector` and `input-trace-mapper`.

These can share short appendices or libraries. They should not share a large
conditional protocol.

### R7 — P2: phase dispatcher files still duplicate agent protocol

The repository guidance correctly says phase files own context, mode, outputs,
and routing while agent files own the invariant method. Several phase files
still reproduce detailed methodology. `phase3-consensus.md` embeds the six-point
implementability method and detailed PLAN2 repair behavior.
`phase3-specialists.md` is 228 lines and contains selection logic, role methods,
prompt bodies, execution semantics, and aggregation behavior.

This duplication makes prompt behavior sensitive to which copy was updated.

**Required direction:** reduce a phase spec to a generated or declarative
dispatch contract. Put reusable method in a small, phase-specific protocol.
Static validation should reject procedural sections in dispatcher files where
the corresponding protocol owns them.

### R8 — P2: lifecycle controllers repeat control-plane concepts

Spec, RE, and delivery each implement current-run resolution, blocking,
continuation, resume, budgets, retries, evidence, terminal summaries, and
publication. EGR-149 already tracks this as an open finding.

The answer is not one giant universal controller. That would reproduce the
current concentration at a higher level.

**Required direction:** extract only small deterministic primitives:

- `NodeRunIdentity`;
- `NodeAttempt`;
- `Blocker` with typed recoverability;
- `EvidenceRef`;
- `RetryBudget`;
- `CheckpointRef`;
- `NodeOutcome`;
- atomic state transition and event append.

Spec, RE, and delivery should remain separate graphs using the same primitives
and conformance suite.

### R9 — P2: checkpoint and rerun semantics are not node-uniform

EGR-144 and EGR-146 remain open. Partial checkpoint coverage and the absence of
a supported rerun command are consequences of phase behavior not being modeled
uniformly. Compound and hidden nodes are especially difficult to invalidate and
replay safely.

**Required direction:** every artifact-producing or certifying node declares:

- checkpoint policy;
- owned outputs;
- downstream invalidation set derived from graph edges;
- replay safety;
- whether the provider can be skipped when certified output is current.

`spec rerun` should execute this generic node contract rather than grow a second
phase-specific recovery table.

### R10 — P1: estimate consistency remains an unimplemented deterministic gate

EGR-142 remains open. GATEKEEPER can update summary estimates while retaining a
contradictory detailed breakdown, and the workflow can publish both. This is a
clear candidate for the same visible deterministic-node architecture used for
Understanding and Lexicon.

**Required direction:** introduce `estimate-consistency` after every estimate
writer and before publication. It should parse one canonical template, reconcile
section totals, record source artifact hashes and material deltas, and route
repair to the exact estimate owner.

### R11 — P1: authoring contracts are not fully aligned with deterministic analyzers

EGR-150 remains open. CARTOGRAPHER can write grammatically reasonable
constraints that Understanding does not recognize, causing expensive amendment
loops. This is broader than one `equals` syntax bug: a deterministic analyzer
and its authoring agent need a versioned shared contract.

**Required direction:** publish analyzer-recognized authoring syntax as a
machine-readable contract and generate prompt examples from it. The analyzer,
Lexicon grammar, rich-spec templates, CARTOGRAPHER contract, and compatibility
tests should consume the same versioned definitions.

## Recommended Target Architecture

### Node contract

Every executable unit should have one typed contract:

```yaml
id: phase3-estimate-consistency
kind: deterministic_gate
reads:
  - artifact: estimates.md
    schema: estimates/v2
writes:
  - artifact: estimate-consistency-report.json
    schema: estimate-consistency/v1
state_writes:
  - estimate_consistency
outcomes: [passed, repairable, blocked]
retry:
  owner_node: phase3-assess2
  max_attempts: 2
checkpoint: on_pass
```

Provider nodes use the same shell but add a protocol reference and provider
policy. Fan-out and join are their own node kinds. Human decisions are not
encoded as provider nodes.

### Ownership rules

For each durable artifact or state field:

- exactly one node owns creation;
- zero or more named nodes may propose changes;
- exactly one deterministic gate certifies it;
- only the controller writes certification state;
- a repair edge returns to the owner;
- publication consumes only certified versions.

### Controller rules

Controllers should:

- load the compiled graph;
- execute one node;
- validate one `NodeOutcome`;
- atomically append one event and transition state;
- stop, retry, or advance according to graph data.

Controllers should not:

- infer a different phase from missing artifacts;
- mutate provider results to simulate a hidden node;
- select a repair owner outside the graph;
- use an LLM because a deterministic condition is unknown;
- contain phase-specific output or routing tables.

## Prioritized Roadmap

### Wave 0 — make the model observable

1. Replace the dry-run's hardcoded simulation with graph-derived output.
2. Add a generated node inventory showing type, owner, inputs, outputs,
   certification, retry edge, and checkpoint policy.
3. Fail static validation on unknown phase fields and unregistered node types.
4. Add graph checks for unbounded cycles, ambiguous output ownership, and
   deterministic conditions that can evaluate to unknown.

This wave should not change execution behavior. It establishes one trustworthy
map before refactoring.

### Wave 1 — expose hidden deterministic work

1. Extract tasks Lexicon from `phase3-plan` and `phase3-consensus`.
2. Extract feasibility and intent-alignment structural gates.
3. Add estimate consistency for EGR-142.
4. Represent Phase A publication readiness and documentation verification as
   visible certification nodes where practical.

This is the highest stability return because it follows the proven
Understanding/Lexicon pattern.

### Wave 2 — split compound nodes

1. Split `phase3-consensus` into WHY3, ASSESS2, join, PLAN2, certification, and
   route nodes.
2. Split specialist selection, dispatches, and join.
3. Give every split node independent attempt identity, evidence, telemetry,
   checkpoint policy, and resume behavior.

### Wave 3 — narrow provider roles

1. Extract phase-specific SAGE protocols.
2. Separate GATEKEEPER feasibility from implementability/estimate revision.
3. Separate ORCHESTRATOR task creation from repair.
4. Reduce CARTOGRAPHER to canonical rich-spec authoring and explicit repair;
   move projection and trace mapping to dedicated nodes.
5. Enforce dispatcher/protocol separation statically.

### Wave 4 — converge lifecycle primitives

After production evidence from the RE lifecycle, implement EGR-149 with shared
small control-plane types and a cross-lifecycle conformance suite. Do not merge
the spec, RE, and delivery state machines.

### Wave 5 — uniform replay

Close EGR-144 and EGR-146 on top of node-owned outputs, checkpoints, and derived
downstream invalidation. Rerun should become a generic graph operation rather
than a growing set of recovery exceptions.

## Stability Acceptance Criteria

The architecture should be considered stable enough for sustained production
use when:

- the graph is the only component allowed to choose the next node;
- every deterministic condition either resolves or blocks as a contract error;
- every certification action is a visible node;
- every provider dispatch has one purpose, one output family, and one verdict
  vocabulary;
- a process may stop after any node and resume without repeating a completed,
  certified provider call;
- every loop has a named owner, finding report, and bounded budget;
- status, dry-run, diagrams, docs, checkpoints, and rerun all derive from the
  same compiled graph;
- spec, RE, and delivery pass one shared control-plane conformance suite;
- a full representative run can be fault-injected at every node boundary and
  recover without ambiguous state or duplicate paid work.

## Suggested New EGR Tracking

The review supports promoting the following findings:

| Candidate | Priority | Scope |
|---|---:|---|
| Graph-only routing authority | P0 | Replace phase-changing controller guards with graph preconditions/gates |
| Visible deterministic certification nodes | P1 | Extract hidden tasks/structural/estimate gates |
| Compound-node resumability | P1 | Split consensus and specialist fan-out/join |
| Deterministic-vs-semantic transition typing | P1 | Remove COMMANDER fallback for unknown deterministic conditions |
| Whole-system workflow compiler | P1 | Typed node registry, unknown-field rejection, generated views |
| Phase-specific role protocols | P2 | Split large multi-mode role behavior |

These should be assigned final EGR IDs only after the team agrees on boundaries,
because the first five are related and should not be implemented as overlapping
refactors.

## Verification Performed

```text
bash scripts/bash/dry-run.sh
PASS: 138, WARN: 1, FAIL: 0

.venv/bin/pytest -q \
  tests/kernel/test_phase_graph.py \
  tests/kernel/test_workflow_validator.py \
  tests/kernel/test_condition_evaluator.py \
  tests/kernel/test_squad_executors_journal.py \
  tests/integration/test_squad_controller.py
327 passed in 29.49s
```

An initial `pytest` invocation used the system Python and failed collection
because PyYAML was unavailable. Re-running through the repository `.venv`
produced the passing result above. No source behavior was changed during this
review.
