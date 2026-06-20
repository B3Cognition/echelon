# Tasks Grammar + Cross-Document Governance — Design

**Date:** 2026-06-20
**Status:** Design (approved to plan)
**Depends on:** Lexicon controlled-grammar gate for `spec.md` (PR #11)

## Problem

Of the ~18 documents an echelon run emits, only `spec.md` is governed by a deterministic
gate (`lexicon`) + soft scoring (`understanding`). The rest are free markdown or have
ad-hoc structural checks. The highest-value ungoverned artifact is **`tasks.md`** — it is
the **single most-consumed build input** (the IMPLEMENTER executes it), yet today it is
validated only by a loose `validate-tasks` structural pass.

Because the only consumers of these documents are **AI build agents** (no human reads
them), the qualities that matter are *explicitness, completeness, determinism, and
machine-traceability* — not prose readability. That makes a controlled grammar the right
instrument for `tasks.md`, and it unlocks the thing that actually guarantees a correct
build: a **machine-verifiable `REQ → AC → TASK → TEST` chain**.

`tasks.md` is already a near-grammar. Its "Task Row Contract" defines a canonical row:

```
- [ ] T-### [P] complexity=<trivial|standard|complex> phase=<token> req=<REQ-IDs|INFRA> depends=<none|T-IDs>
```

Typed fields and cross-document links (`req=`, `depends=`) already exist — but nothing
enforces them. Grammar-izing `tasks.md` formalizes and enforces structure that is already
present but unchecked.

## Goal

1. A `TASKS` controlled grammar + deterministic validator (`lexicon validate --type tasks`).
2. A **cross-document gate** that verifies `tasks.md` against `spec.md`:
   coverage, referential integrity, dependency acyclicity, field completeness, test linkage.
3. ORCHESTRATOR authors `tasks.md` in the grammar with an **in-dispatch repair loop**, and
   COMMANDER **re-dispatches `phase3-plan`** on the controlled `tasks_lexicon_pass` outcome.
4. The cross-doc gate is **re-runnable**, making `REQ↔TASK↔TEST` drift always detectable.

### Non-goals

- Grammar-izing reasoning-heavy docs (`research`/ADRs, `strategic-overview`) — their value is
  NL reasoning; they get structure/link governance later, not a rigid grammar.
- Human readability — out of scope by definition (AI-only consumers).
- Changing the spec grammar or the existing `phase1-what` gate.

## Architecture

Reuses the existing `src/lexicon/` engine (Python + lark). No new tool.

### Unit 1 — `TASKS` grammar (`src/lexicon/grammar_tasks.lark`)

A new artifact type. One `TASK` block per executable task; AC checkboxes nest as `VERIFY`
lines. Phases/checkpoints are structural headers.

```
ARTIFACT: TASKS
TITLE: <title>

TASK: T-001
PHASE: foundation
COMPLEXITY: standard            # trivial | standard | complex
PARALLEL: no                    # yes | no
REQ: REQ-028                    # one or more REQ ids, or INFRA
DEPENDS: none                   # none | T-ids
ACCEPTANCE: <observable done-condition>
TEST: <how completion is verified>
```

Structural (parse-level) rules: every `TASK` has `PHASE`, `COMPLEXITY`, `REQ`, `DEPENDS`,
`ACCEPTANCE`, `TEST`; `REQ`/`DEPENDS` hold id-shaped tokens or the literals `INFRA`/`none`.

### Unit 2 — tasks validator (`src/lexicon/tasks.py`) — **full parity with the spec gate**

The `tasks` validator reuses the *same* `lexicon` modules the spec gate uses, applied to the
NL fields (`ACCEPTANCE`, `TEST`, and the task body). It is not a thinner gate — every
within-document check the spec gets, tasks get too:

- **P — parse** (`parser`): conforms to the `TASKS` grammar.
- **banned-word** (`linter.banned_word_findings`): `ACCEPTANCE`/`TEST` must be measurable —
  no `works correctly`, `robust`, `fast`, `as needed`, etc. A task whose done-condition is
  vague is not verifiable.
- **T — term resolution** (`resolver`): domain identifiers in task fields resolve to the
  **same glossary `spec.md` uses** (shared controlled vocabulary across the two artifacts).
- **A — atomicity** (the `tasks` analogue of spec's single-modal `D`): each `TASK` states
  **one deliverable** — exactly one `ACCEPTANCE` condition and one `TEST`; compound
  acceptance (`and`-joined obligations) → `task-not-atomic`.
- **C — completeness / no-placeholder** (`completeness`): required fields present AND no
  leftover `<placeholder>`/`TBD`/`TODO` in any field.
- **O — observability**: `ACCEPTANCE` (observable done-condition) + `TEST` (verification)
  are mandatory and non-empty — the task's observable outcome.

These run *standalone* on `tasks.md` (no `--spec` needed), exactly as the spec gates run on
`spec.md`. The cross-document checks (Unit 3) are the *additional* layer tasks gets on top.

### Unit 3 — cross-document gate (`src/lexicon/crossdoc.py`)

Takes `tasks.md` + `spec.md`. Deterministic checks, each emitting localized `Finding`s:

| Check | Rule | Finding code |
|---|---|---|
| Coverage | every `REQ` in spec has ≥1 `TASK` with `REQ=` referencing it | `req-uncovered` |
| Referential integrity | every `TASK.REQ` (≠INFRA) resolves to a real spec `REQ` | `task-orphan-req` |
| Dependency acyclicity | `DEPENDS` graph is a DAG; all `T-ids` exist | `dep-cycle` / `dep-missing` |
| Test linkage | every `TASK` has a `TEST`; every spec `AC` is *tasked* — i.e. the REQ it belongs to (spec `REQ → EXAMPLE → AC`) has ≥1 covering task | `task-no-test` / `ac-untasked` |

`Valid_tasks(A) = parse ∧ no-banned ∧ terms-resolve ∧ atomic ∧ complete ∧ observable`
` ∧ coverage ∧ refint ∧ acyclic ∧ test-linked` — i.e. the spec-parity within-doc gates
(Unit 2) **and** the cross-doc gates (Unit 3), all binary, all deterministic.

### Unit 3b — soft quality score (parity with `understanding` at WHY2)

Just as `spec.md` gets the 34-metric `understanding` soft score *after* its hard gate, the
hard-clean `tasks.md` gets a lightweight **task-quality score** (advisory, never the gate):
`acceptance_measurability` (numeric/observable terms present), `test_concreteness`,
`atomicity_ratio`, `dependency_depth` (over-coupling signal). Reported for repair-priority
ordering; it does not block. This keeps the two-layer model identical to spec (hard gate +
soft score), so tasks is governed at the same depth, not just structurally.

### Unit 4 — CLI surface (`src/lexicon/cli.py`)

```
lexicon validate tasks.md --type tasks --spec-ref spec.md --glossary glossary.md [--json]
```
`--glossary` feeds term resolution (T), shared with the spec gate; `--spec-ref` feeds the
cross-doc checks (named `--spec-ref` because the positional argument is already the file under
validation). Exit 0 iff `Valid_tasks`; findings localized to `tasks.md:line`.

### Unit 5 — ORCHESTRATOR "Tasks Gate Mode" (`extension/agents/.../orchestrator.md`)

Mirrors CARTOGRAPHER's Lexicon Gate Mode exactly:
1. **Self-read** `lexicon_gate` from `.specify/extensions/echelon/echelon-config.yml` (deterministic; not prompt-injected).
2. If enabled for `tasks`: author `tasks.md` in the `TASKS` grammar.
3. **In-dispatch repair loop** (the "fix"): run `lexicon validate --type tasks --spec spec.md`,
   apply localized fixes per finding code, re-run, up to `max_repair_attempts`.
4. Emit `tasks_lexicon_pass` (+ attempts, findings) in `echelon_result.state_updates`.

Repair table (finding → localized fix):
- within-doc (parity gates): `banned-word` → replace vague text with a measurable condition;
  `unresolved-term` → use/add a glossary term; `task-not-atomic` → split into single-deliverable
  tasks; `incomplete-slot` → fill the placeholder; `task-no-test` → add a `TEST`.
- cross-doc: `req-uncovered` → add a TASK for the REQ; `task-orphan-req` → fix the `REQ=` ref or
  drop the task; `dep-cycle`/`dep-missing` → fix `DEPENDS`; `ac-untasked` → add a task covering
  the AC's REQ.

### Unit 6 — COMMANDER re-dispatch wiring (`definition.yaml` + `phase3-plan.md`)

`phase3-plan` transition (mirrors the `phase1-what` re-dispatch, capped):
```
transitions:
  - to: phase3-plan
    condition: "lexicon_gate.enabled AND lexicon_gate.artifacts.tasks.enabled AND NOT tasks_lexicon_pass AND iteration < max_iterations"
    action: increment_iteration
  - to: phase3-consensus
    condition: always
```

### Unit 7 — persist the pass flag (fix the known gap)

`spec.md`'s `lexicon_pass` failed to land in `state.json`, forcing COMMANDER to re-derive it.
Here, the harness MUST persist `tasks_lexicon_pass` (and we backfill the same for
`lexicon_pass`) so the transition is evaluable without re-derivation. Deterministic fallback
(COMMANDER re-runs the validator) remains as defense-in-depth.

## Data flow

```
ORCHESTRATOR (phase3-plan)
  reads spec.md (REQ+AC) ──► authors tasks.md (TASK, req=REQ, TEST)
        │
        └─ in-dispatch: lexicon validate --type tasks --spec spec.md ──► repair ──► (loop ≤N)
        │
        ▼ returns tasks_lexicon_pass
COMMANDER: tasks_lexicon_pass? ── false & iter<max ─► re-dispatch phase3-plan
                                 └ true ─► phase3-consensus
```

The same `lexicon validate --type tasks --spec spec.md` is re-runnable any time (CI,
pre-commit, phase re-entry), so `REQ↔TASK↔TEST` drift is always detectable after a spec or
tasks edit.

## Error handling

Every gate failure is a localized `Finding(code, message, line, span)` (reusing
`linter.Finding`). The validator never raises on a bad doc — it returns `ok=False` + findings.
A dangling/cyclic dependency or uncovered REQ is a finding, not a crash. Unparseable input →
`parse-error`. Missing `--spec` → cross-doc checks are skipped with an explicit warning (so
`tasks.md` can still be structurally validated standalone).

## Testing (TDD, mirrors the lexicon suite)

- grammar: valid TASKS doc parses; missing field / bad `REQ=` token → fail.
- parity (within-doc): vague `ACCEPTANCE` ("works correctly") → `banned-word`; ungoverned
  identifier in `TEST` → `unresolved-term`; `and`-joined compound acceptance → `task-not-atomic`;
  `<TBD>` in a field → `incomplete-slot`; a glossary-bound term resolves clean.
- coverage: spec with an uncovered REQ → `req-uncovered`; full coverage → pass.
- refint: `REQ=REQ-999` (no such REQ) → `task-orphan-req`.
- acyclicity: `T-001 depends=T-002`, `T-002 depends=T-001` → `dep-cycle`.
- test linkage: TASK without `TEST` → `task-no-test`; spec `AC` with no task → `ac-untasked`.
- CLI: valid → exit 0; each violation → exit 1 with the localized finding.
- regression: existing lexicon spec suite stays green.

## Configuration

Extend `lexicon_gate` to be artifact-keyed (back-compatible default):
```yaml
lexicon_gate:
  enabled: true
  artifacts:
    spec:  { enabled: true, type: spec }
    tasks: { enabled: true, type: tasks, spec_ref: spec.md }   # new; gates phase3-plan
  max_repair_attempts: 3
```

## Honest limits / risks

- **"Maintain" = always *detectable*, not automatically *zero*.** Keeping `REQ↔TASK↔TEST`
  drift at zero requires the gate to actually run on every change AND the amendment loop to
  update tasks when the spec changes. The grammar makes drift impossible to *hide*; it does
  not auto-fix it.
- **Re-dispatch is COMMANDER/LLM-adherence-dependent** (as seen for `phase1-what`). Unit 7
  (persisting the pass flag) reduces but does not eliminate this; the deterministic
  re-derivation fallback is the safety net.
- **Verbosity/context cost** — a `TASK` block is larger than a one-line row; for large specs
  this consumes build-agent context. Keep fields minimal; do not restate.
- **Scope discipline** — do NOT let this expand into grammar-izing the reasoning docs; that is
  a separate, later decision.

## Incremental delivery

1. `TASKS` grammar + `tasks.py` structural validator + CLI `--type tasks` (standalone), TDD.
2. `crossdoc.py` cross-doc checks + `--spec` wiring, TDD.
3. ORCHESTRATOR Tasks Gate Mode + config `artifacts.tasks`.
4. `definition.yaml` `phase3-plan` re-dispatch transition + persist `tasks_lexicon_pass`.
5. Validate end-to-end on the existing 029 `spec.md` + `tasks.md`.
