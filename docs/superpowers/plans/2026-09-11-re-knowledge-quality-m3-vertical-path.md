# RE Knowledge Quality M3 Vertical Path Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:test-driven-development` to implement this plan task-by-task in
> the current checkout. Do not delegate unless the user explicitly requests
> subagents. Keep changes uncommitted unless the user explicitly requests a
> commit.

**Goal:** Turn one terminal reviewed RE knowledge run into source and workspace
knowledge that is synthesized, atomically published, and consumed by a new spec
or delivery run through Echelon's existing provider-neutral path.

**Architecture:** Add an authenticated adapter from the protocol-2.8
`ReviewedKnowledgeRunRootV1` closure to the existing protocol-2.7 synthesis
input contract. The adapter freezes each accepted source reconciliation's
reviewed Markdown and debt lineage as content-addressed authority; protocol 2.7
continues to own the synthesis graph, configured-provider execution,
materialization, publication CAS, and compatibility registry. A small workflow
coordinator then composes reviewed analysis and synthesis/publication as one
logical user action. No second scheduler, provider implementation, or publication
format is introduced.

**Tech Stack:** Python dataclasses and canonical JSON, existing RE v2 object and
event stores, protocol-2.8 reviewed knowledge authority, protocol-2.7 synthesis
and publication, configured `SquadCliProvider`, Typer CLI, pytest with synthetic
Git workspaces and scripted providers.

**Spec:** `docs/superpowers/specs/2026-09-08-re-knowledge-quality-repair-design.md`

## Global Constraints

- Work in the current checkout on `main`; do not create another worktree.
- Do not invoke a live or paid provider, install Echelon, migrate OptaSearch,
  alter external source repositories or stashes, raise resource ceilings, push,
  merge, or publish outside synthetic test workspaces.
- Preserve the configured provider facade. RE must not import a concrete Codex,
  Claude, Copilot, OpenCode, or HTTP adapter and must not silently fall back.
- Preserve immutable snapshots, controller-owned durable writes, bounded attempts,
  independent review, one aggregate resource account, and atomic publication.
- Raw source secrets and raw provider diagnostics must never enter provider
  contexts, ordinary logs, status, publications, or consumer snapshots.
- Historical protocol readers and identities remain valid. New authority gets an
  explicit adapter schema and materializer identity; historical runs are not
  reinterpreted by a flag.
- Every production behavior starts with a focused failing test that is observed
  failing for the intended reason, followed by the minimum implementation and
  focused plus regression verification.

---

### Task 1: Authenticate reviewed knowledge as synthesis-parent authority

**Files:**
- Create: `src/harness/re_v2/reviewed_synthesis_parent.py`
- Modify: `src/harness/re_v2/protocol_27/authority.py`
- Modify: `src/harness/re_v2/protocol_27/model.py`
- Test: `tests/unit/test_re_v2_reviewed_synthesis_parent.py`
- Test: `tests/unit/test_re_v2_protocol_27_authority.py`

**Interfaces:**

- Add `ReviewedSourceKnowledgeProjectionV1`, binding one source reconciliation
  root, its reviewed candidate, review, accepted debt authorities, and exact
  rendered Markdown hash.
- Add `resolve_reviewed_synthesis_parent(workspace_root, from_run)` returning the
  existing `ResolvedSynthesisParentV1` shape with `selected_layer="reviewed"`.
- Extend the protocol-2.7 source-overview projection enum only for the explicit
  reviewed adapter. Existing L1/L2/L3 values and identities remain unchanged.
- Authenticate the protocol-2.8 manifest, terminal `knowledge_run_completed`
  event, run root, active revision, target/source closure, and every referenced
  record before producing bytes. Event payloads and materialized files are not
  authority.
- A source with accepted debt is `partial`; a debt-free source is `complete`.
  The adapter emits an exact content-addressed per-source debt summary and never
  weakens or discards inherited or newly accepted debt.

- [x] **Step 1: Write failing reviewed-parent tests.**

  Complete a synthetic protocol-2.8 reviewed run with the existing scripted
  backend. Assert exact source coverage, reviewed overview bytes, root/review/
  candidate lower authority, complete-vs-partial outcomes, and deterministic
  identities. Tamper with the completion event, active revision pointer,
  candidate bytes, review, source-root membership, or debt binding and assert
  failure before a synthesis request can be created.

- [x] **Step 2: Run the focused test and observe RED.**

  ```bash
  pytest -q tests/unit/test_re_v2_reviewed_synthesis_parent.py
  ```

  Expected: import failure because the reviewed synthesis-parent adapter does not
  exist.

- [x] **Step 3: Implement the immutable adapter.**

  Reuse protocol-2.8 replay and `authenticate_knowledge_record`; read canonical
  objects from the run-local object store; serialize only the reviewed source
  candidate's `rendered_markdown`; bind the adapter's implementation closure as
  `materializer_authority_hash`; and populate the existing frozen overview
  catalog/payload seam. Do not read mutable source repositories.

- [x] **Step 4: Verify Task 1.**

  ```bash
  pytest -q tests/unit/test_re_v2_reviewed_synthesis_parent.py \
    tests/unit/test_re_v2_protocol_27_authority.py
  git diff --check
  ```

### Task 2: Route terminal reviewed runs into the existing synthesis lifecycle

**Files:**
- Modify: `src/harness/re_v2/protocol_27/authority.py`
- Modify: `src/harness/re_v2/protocol_27/lifecycle.py`
- Modify: `src/harness/re_v2/protocol_27/inputs.py`
- Test: `tests/integration/test_re_v2_reviewed_synthesis.py`

**Interfaces:**

- `resolve_synthesis_parent()` detects the explicit terminal reviewed authority
  and delegates to Task 1; incomplete ordinary L4 runs remain rejected.
- `_protocol_27_input_set()` reuses the configured CLI executor frozen by the
  protocol-2.8 parent and builds the unchanged protocol-2.7 synthesis graph.
- For this vertical increment, reviewed synthesis requires the reviewed source
  set to exactly cover the frozen workspace partition. Source-granular merge is
  introduced only in Tasks 6-7, so partial selection cannot silently erase
  existing sources.
- Existing exact-child reuse, resource bounds, checkpoints, provider facade, and
  CAS bases remain authoritative.

- [x] **Step 1: Write a failing offline synthesis-input integration test.**
- [x] **Step 2: Observe RED on the unsupported terminal reviewed parent.**
- [x] **Step 3: Add the reviewed-parent route and preserve all old routes.**
- [x] **Step 4: Verify the new path plus protocol-2.7 lifecycle/input regressions.**

### Task 3: Publish and consume reviewed knowledge atomically

**Files:**
- Modify: `src/harness/re_v2/protocol_27/publication.py`
- Modify: `src/harness/re_v2/protocol_28/status.py`
- Test: `tests/integration/test_re_v2_reviewed_publication.py`
- Test: `tests/unit/test_published_re_context.py`

**Interfaces:**

- A completed reviewed synthesis uses the existing two-CAS protocol-2.7
  publication transaction and legacy compatibility registry.
- Publication descriptors retain reviewed parent/root/debt identities through the
  existing synthesis root and source outcome authority.
- Protocol-2.8 status reports the linked synthesis/publication outcome without
  claiming publication from an event alone.
- `attach_published_re_context()` snapshots the new generation for a new consumer;
  an already-created consumer remains pinned to its old generation.

- [x] **Step 1: Write failing publish/consumer tests with crash seams.**
- [x] **Step 2: Observe RED for the missing reviewed lineage/status bridge.**
- [x] **Step 3: Add the smallest linkage needed around the existing publisher.**
- [x] **Step 4: Verify old-or-complete-new publication, replay, and pinning.**

### Task 4: Compose analysis, synthesis, and publication as one logical action

**Files:**
- Create: `src/harness/re_v2/knowledge_workflow.py`
- Modify: `src/harness/re_v2/protocol_28/lifecycle.py`
- Modify: `src/harness/re_v2/protocol_28/status.py`
- Test: `tests/integration/test_re_v2_knowledge_workflow.py`

**Interfaces:**

- Add one coordinator facade that resumes or advances the existing reviewed
  protocol-2.8 run, creates/reuses exactly one protocol-2.7 child after terminal
  review, and publishes it after synthesis completion.
- The facade owns no scheduler or provider code; it calls the existing lifecycle
  functions with one configured provider factory and existing absolute limits.
- Retry is idempotent after every preparation, activation, synthesis,
  materialization, and publication fault boundary.
- Status uses user concepts: `analyzing`, `synthesizing`, `publishing`,
  `complete`, `complete-with-limitations`, or `needs-attention`.

- [x] **Step 1: Write a failing crash/replay workflow test.**
- [x] **Step 2: Observe RED for the missing composed coordinator.**
- [x] **Step 3: Implement the thin coordinator over existing lifecycles.**
- [x] **Step 4: Verify zero duplicate provider calls and one publication.**

### Task 5: Expose the two-action depth-based CLI without losing advanced tools

**Files:**
- Modify: `src/echelon/cli_app.py`
- Modify: `src/echelon/cli.py`
- Modify: `src/echelon/re_cli_options.py`
- Test: `tests/integration/test_re_v2_knowledge_cli.py`
- Test: `tests/unit/test_cli_help.py`

**Interfaces:**

- Normal commands become:

  ```text
  echelon re run [--depth quick|standard|deep]
  echelon re refresh [--source SOURCE ...] [--depth quick|standard|deep]
  ```

- `standard` is the default for a new source; refresh preserves established depth
  unless explicitly overridden. Depth changes obligations and resource defaults,
  not the output family.
- `deepen`, `continue`, `synthesize`, and `publish` remain documented advanced/
  compatibility commands. They are not required in the normal success path.
- Provider selection comes only from the standard Echelon configuration facade.
  Help and errors name the current action and exact next step without protocol
  archaeology.

- [ ] **Step 1: Write failing command/help and provider-routing tests.**
- [ ] **Step 2: Observe RED for missing depth and automatic continuation.**
- [ ] **Step 3: Implement CLI parsing and facade dispatch.**
- [ ] **Step 4: Verify historical advanced commands and normal commands.**

### Task 6: Plan source-granular refresh from immutable snapshot freshness

**Files:**
- Create: `src/harness/re_v2/knowledge_refresh.py`
- Modify: `src/harness/re_v2/knowledge_workflow.py`
- Test: `tests/unit/test_re_v2_knowledge_refresh.py`

**Interfaces:**

- Compare current local Git snapshot identities to the latest publication. Never
  fetch, pull, merge, checkout, or modify a source repository.
- Produce an immutable `KnowledgeRefreshPlanV1` naming changed sources, unchanged
  reusable source authority, invalidated source/workspace outputs, requested
  depth, and explicitly `not_checked` targeted siblings.
- A no-change refresh produces a durable no-op result and performs no provider
  dispatch or publication.
- Changed sources are reanalyzed; unchanged sources are reused only through exact
  authenticated compatibility. Cross-source workspace outputs depending on a
  changed source are regenerated.

- [x] **Step 1: Write failing U1-U5 refresh-planning tests.**
- [x] **Step 2: Observe RED for the missing planner.**
- [x] **Step 3: Implement pure freshness and invalidation planning.**
- [x] **Step 4: Verify no repository mutation and deterministic plans.**

### Task 7: Execute and atomically publish refresh generations

**Files:**
- Modify: `src/harness/re_v2/knowledge_refresh.py`
- Modify: `src/harness/re_v2/knowledge_workflow.py`
- Modify: `src/harness/re_v2/protocol_27/publication.py`
- Test: `tests/integration/test_re_v2_knowledge_refresh.py`

**Interfaces:**

- Merge freshly reviewed source authority with explicitly compatible unchanged
  source authority into one synthesis parent.
- Targeted refresh publishes updated selected sources and required cross-source
  workspace derivations; unselected siblings remain visible as `not_checked`, not
  silently current.
- Concurrent refresh uses the existing compare-and-swap publication bases. One
  winner publishes; stale candidates return a visible retryable conflict.
- Old consumers remain pinned; new consumers see only the complete new generation.

- [x] **Step 1: Write failing U6-U9 execution/race/pinning tests.**
- [x] **Step 2: Observe RED for missing compatible-source merge.**
- [x] **Step 3: Implement the immutable merge and workflow continuation.**
- [x] **Step 4: Verify atomicity, conflicts, no-op, and pinning.**

### Task 8: Offline two-service acceptance and release gate

**Files:**
- Create: `tests/integration/test_re_v2_knowledge_end_to_end.py`
- Modify: `docs/reference/commands.md`
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-09-08-re-knowledge-quality-repair-design.md`

**Acceptance:**

- Synthetic service A calls service B. A standard run publishes source overviews,
  architectures, contracts, components, workspace overview, relationships,
  contracts, and domain composition.
- A new spec consumes the published generation. Then A changes from A1 to A2,
  refresh reuses B, regenerates A and dependent workspace outputs, and publishes
  exactly one new generation. The old spec stays on generation 1; a new spec uses
  generation 2.
- Candidate/reviewer contradictions, unsupported absence, omitted categories,
  debt, secret canaries, provider failures, crashes, stale CAS, and no-op refresh
  are covered without a live provider.
- The installed default remains gated until this offline suite and the scoped
  regression suite pass. Live multi-workspace evaluation and any paid budget are
  M4 and require separate explicit authorization.

- [ ] **Step 1: Write the failing end-to-end fixture.**
- [ ] **Step 2: Complete the smallest missing seams until it passes.**
- [ ] **Step 3: Run scoped RE v2, CLI, publication, and consumer regressions.**
- [ ] **Step 4: Run `git diff --check` and update truthful docs/status.**
