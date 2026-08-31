# RE v2 L4 Orchestration, CLI, and Proof Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make protocol 2.8 user-runnable through durable L3-to-L4 orchestration, exact continuation, shadow planning, manifest-first status, run-local materialization, deterministic closure handoff, and installed-provider proof.

**Architecture:** Add a content-free orchestration authority beside immutable RE runs, then adapt the completed protocol-2.8 planning and execution kernel into a lifecycle that creates one exact L4 child and, when required, one zero-provider closure successor. Extend the existing Typer/legacy CLI by manifest-first routing only. Status and materialization remain protocol-local and derive solely from authenticated manifests, ledgers, events, roots, and orchestration links.

**Tech Stack:** Python 3.11+, frozen dataclasses, canonical JSON/content digests, append-only event chains, existing RE v2 run stores and provider adapters, Typer, pytest, Bash installation/dry-run scripts.

**Spec:** `docs/superpowers/specs/2026-08-31-re-v2-l4-exhaustive-depth-design.md`

## Global Constraints

- The durable intent lives below `runs/.re-v2-orchestrations/<request-id>/`; it is not an RE run and is excluded from run/checkpoint enumeration.
- The orchestration request identity includes semantic authority and selection but excludes resource authorization. Resource raises append authority; they never retarget an intent.
- The ordered intent state is `awaiting_l3 -> awaiting_l4 -> awaiting_closure -> complete`, with at most one authenticated child per transition.
- A missing selected L3 prerequisite may be created or reused automatically. An existing ineligible L3 authority blocks; it is never bypassed with older L2 authority.
- `--shadow` performs no write, pointer change, checkpoint staging, or dispatch. Resource flags with `--shadow` are invalid.
- L4 resource flags authorize only the exhaustive child. L3 prerequisite authorization stays on protocol-2.5 defaults and continuation flags.
- Exhaustive execution uses only staged immutable shard bytes after activation. A dirty pre-activation source stops with commit/stash/revert guidance.
- Closure-successor mode performs zero provider calls and rejects resource authorization.
- Materialization writes only `runs/<run-id>/re/l4/`, publishes its manifest last, and never writes workspace `re/` or lower-run output.
- Status is manifest-first, content-free, and renders the exact protocol plus the final prominent L4 banner. Protocol 2.9 synthesis/publication remains `not run`.
- Protocols 2.2 through 2.7 and checkpoint V1 retain their canonical behavior and bytes.

---

### Task 1: Persist and Recover Durable Deepening Intent

**Files:**
- Create: `src/harness/re_v2/protocol_28/orchestration.py`
- Create: `tests/unit/test_re_v2_protocol_28_orchestration.py`

**Interfaces:**
- `DeepenOrchestrationRequestV1`: immutable input manifest/terminal hashes, snapshot/partition/selection, L4 policy/executor authority, and L3 prerequisite request identity; `request_id` excludes resource limits.
- `DeepenOrchestrationProjectionV1`: state plus exact input, L3, L4, and closure child references.
- `OrchestrationPaths`, `OrchestrationEventStore`, and `DeepenOrchestrationController`.
- `find_exact_orchestration(workspace_root, request_id)`, `find_open_orchestrations_for_child(workspace_root, child_run_id)`, and `recover_orchestration(path)`.

- [x] Write failing closed-request, content-free-event, duplicate-child, hash-mismatch, projection-loss, crash-transition, and hidden-namespace-enumeration tests.
- [x] Run RED: `pytest -q tests/unit/test_re_v2_protocol_28_orchestration.py`.
- [x] Implement canonical request storage, a closed append-only event vocabulary, controller-only transitions, atomic projection rebuild, and authenticated child-link recovery.
- [x] Prove repeated semantic commands reuse the intent, higher authorization appends an event, ambiguous reverse lookup blocks, and source-authority change requires a new request.
- [x] Run GREEN with protocol-2.8 events/recovery and protocol-2.6 reconstruction tests.
- [x] Commit `feat(re): persist L4 orchestration intent`.

### Task 2: Assemble and Execute Exact Exhaustive Children

**Files:**
- Create: `src/harness/re_v2/protocol_28/context.py`
- Create: `src/harness/re_v2/protocol_28/lifecycle.py`
- Modify: `src/harness/re_v2/protocol_28/recovery.py`
- Modify: `src/harness/re_v2/protocol_28/controller.py`
- Create: `tests/unit/test_re_v2_protocol_28_lifecycle.py`
- Create: `tests/integration/test_re_v2_protocol_28_live.py`

**Interfaces:**
- `Protocol28RunContext` and `load_protocol_28_run_context(run_dir)` for exhaustive and closure variants.
- `prepare_protocol_28_request(workspace_root, intent, eligible_l3, options)` stages snapshot evidence, target-local L3 projections, subjects, policy, executor authority, deterministic plan, checkpoint selection, and manifest before publication.
- `find_exact_protocol_28_child(workspace_root, request_id)` and `run_protocol_28_exhaustive(run_dir, provider_factory)`.
- `continue_protocol_28_run(run_dir, token_limit, active_ms_limit, provider_factory)` appends only valid resource authority and resumes unresolved work.

- [x] Write failing manifest-last, exact-child reuse, dirty-source, minimum paired reservation, adopted/generated execution, partial-budget resume, complete zero-call replay, and post-activation source-unavailable tests.
- [x] Run RED on the new lifecycle/live tests.
- [x] Implement authority assembly from authenticated protocol-2.5/2.6 parents, Prosaic analyst/verifier loading, shared CLI executor contracts, private staging, V2 checkpoint adoption, and active-pointer update after publication.
- [x] Drive the existing scheduler/execution/ledger/controller until accepted roots or a truthful terminal blocker; never reopen accepted siblings.
- [x] Recover raw captures, parsed candidates, verification, acceptance, roots, and projection seams before any provider dispatch; materialization remains Task 5.
- [x] Run GREEN with all protocol-2.8 unit tests and protocol-2.6 recovery regressions.
- [x] Commit `feat(re): run exhaustive L4 children`.

### Task 3: Orchestrate L3 Prerequisites and Zero-Call Closure

**Files:**
- Modify: `src/harness/re_v2/protocol_28/orchestration.py`
- Modify: `src/harness/re_v2/protocol_28/lifecycle.py`
- Create: `src/harness/re_v2/protocol_28/closure.py`
- Create: `tests/integration/test_re_v2_protocol_28_orchestration.py`
- Create: `tests/unit/test_re_v2_protocol_28_closure.py`

**Interfaces:**
- `resolve_l4_parent(workspace_root, from_run, selection)` traverses supported L2/L3/checkpoint/synthesis lineage to exact analysis authority.
- `evaluate_l3_eligibility(parent, selection)` accepts selected complete targets or frozen deeper-evidence-only findings and rejects mixed, human, mutation, unfinished, and next-epoch blockers.
- `execute_deepen_orchestration(workspace_root, options, provider_factory)` advances one durable chain.
- `create_or_reuse_l4_closure_successor(intent, blocked_l3, complete_l4)` builds and completes one schema-7 closure run with zero provider calls.

- [x] Write failing parent matrix tests for direct L3, missing L3, ineligible L3, synthesis complete/partial selected/unselected/next-epoch, strict selection, and zero-domain sources.
- [x] Write crash/idempotency tests before and after each child bind and transition.
- [x] Implement automatic protocol-2.5 prerequisite creation/reuse, pause retention, continuation advancement, exact L4 binding, deterministic finding-to-evidence closure, and closure-integrity blockers.
- [x] Prove an L3 child linked to exactly one open intent auto-advances after continuation; multiple open intents block.
- [x] Prove completed closure replay performs zero calls and cannot start a new L3 epoch.
- [x] Run GREEN with protocol-2.5 audit/closure and protocol-2.7 synthesis lineage regressions.
- [x] Commit `feat(re): orchestrate L3 to L4 closure`.

### Task 4: Register L4 CLI, Continue, and Shadow

**Files:**
- Modify: `src/echelon/cli_app.py`
- Modify: `src/echelon/cli.py`
- Modify: `src/harness/re_v2/protocol_28/lifecycle.py`
- Create: `tests/integration/test_re_v2_protocol_28_cli.py`
- Modify: `tests/unit/test_cli_help.py`

**Interfaces:**
- `ReDeepeningLayer.L4`; Typer and legacy `--to` validation list `L2`, `L3`, and `L4` truthfully.
- `_cmd_re_deepen` routes L4 through orchestration and supports `--shadow` without resource flags.
- `_re_v2_context` and `_run_re_v2_continue` dispatch schema 7 by `run_mode`.
- Explicit `echelon re continue <run-id>` accepts protocol 2.7 and 2.8; exhaustive mode maps public token/time flags to L4 authority, closure mode rejects them.

- [ ] Write failing parser/help tests for L4, invalid L3-only flags, shadow/resource conflicts, selection conflicts, and absence of any public `hard_` setting.
- [ ] Write failing CLI integration tests for new/reused intent, missing/paused L3, schema-7 continuation, closure rejection, and complete zero-call replay.
- [ ] Implement additive routing while preserving V1 lifecycle option translation and all earlier v2 routes.
- [ ] Render shadow target/entry counts, realized/conditional checkpoint reuse, and minimum/maximum dispatch/resource intervals without mutation.
- [ ] Run GREEN for CLI help, protocol-2.4-through-2.8 CLI matrices, and V1 continuation tests.
- [ ] Commit `feat(re): expose exhaustive L4 CLI`.

### Task 5: Add Manifest-First Status and Run-Local Materialization

**Files:**
- Create: `src/harness/re_v2/protocol_28/status.py`
- Create: `src/harness/re_v2/protocol_28/materialization.py`
- Modify: `src/harness/re_v2/status.py`
- Create: `tests/unit/test_re_v2_protocol_28_status.py`
- Create: `tests/unit/test_re_v2_protocol_28_materialization.py`

**Interfaces:**
- `protocol_28_status_document(run_dir, intent=None)` and `render_protocol_28_status(run_dir, intent=None, as_json=False)`.
- `materialize_l4_closure(context)` and `validate_or_repair_l4_materialization(context)`.
- Manifest-first shared status router selects `2.8` dynamically and attaches a unique open orchestration without changing explicit-run authority.

- [ ] Write failing text/JSON tests for protocol header, intent chain, selected/all scope, per-target progress, producer/verifier usage, avoided reservations, historical failures, L3 closure, synthesis `not run`, exact next action, and every specified final banner.
- [ ] Write failing materialization tests for `runs/<run-id>/re/l4/`, deterministic ordering, manifest-last publication, crash repair, tamper quarantine, and no lower/workspace output mutation.
- [ ] Implement content-free document projection and prominent final banner precedence, including pending L3, pre-activation, evidence-incomplete, closure-integrity, selected-complete, and all-scope-synthesis-required cases.
- [ ] Implement root-bound Markdown/JSON projection from durable accepted objects and record materialization only after exact file-set validation.
- [ ] Run GREEN with protocol-2.4-through-2.7 status/materialization regressions.
- [ ] Commit `feat(re): report and materialize exhaustive L4`.

### Task 6: Install, Exercise Providers, and Prove a Real Workspace

**Files:**
- Modify only if defects are found: protocol-2.8 modules and focused tests above.
- Create: `tests/fixtures/create_re_v2_protocol_28_pilot.py`
- Create: `tests/integration/test_re_v2_protocol_28_provider.py`

**Interfaces:**
- Synthetic installed-provider pilot covers analyst/verifier contracts, one repair, interruption recovery, V2 checkpoint adoption, and zero-call replay.
- Real OptaSearch pilot deepens one representative clean selected domain, records content-free telemetry, hides/removes checkpoint origins/cache, and proves self-contained continuation/replay.

- [ ] Run the complete protocol-2.8, compatibility, CLI, status, materialization, and provider integration gate.
- [ ] Run `bash scripts/bash/dry-run.sh`, then install from this worktree with `bash scripts/install.sh`.
- [ ] Run a clean synthetic selected-domain and `--all` proof, including a manufactured deeper-evidence L3 blocker and zero-provider closure successor.
- [ ] Run an installed-provider interruption/recovery pilot and verify identical completion performs no new calls.
- [ ] Confirm the OptaSearch source repositories are clean; otherwise stop with commit/stash/revert guidance and do not include untracked source files.
- [ ] Run one representative OptaSearch selected-domain L4 pilot, verify lower authority adoption and complete new shard coverage, then hide checkpoint origins/cache and prove self-contained status/replay.
- [ ] Record provider/model/effort, counts, avoided dispatch/reservation, charged/trusted resources, active time, roots, and clean-snapshot evidence without source content.
- [ ] Run the full repository `pytest`, `git diff --check`, and bundle dry run.
- [ ] Commit any pilot-driven fixes as focused commits; leave full OptaSearch `--all` deferred to protocol 2.9.

## Completion Gate

```bash
pytest -q tests/unit/test_re_v2_protocol_28_*.py \
  tests/integration/test_re_v2_protocol_28_*.py \
  tests/unit/test_re_v2_protocol_2{4,5,6,7}_*.py \
  tests/integration/test_re_v2_protocol_2{4,5,6,7}_cli.py
pytest -q
git diff --check
bash scripts/bash/dry-run.sh
```

Protocol 2.8 is complete only when an installed `echelon re deepen --to L4` can durably traverse or create its L3 prerequisite, execute and resume exact L4 work, optionally close inherited deeper-evidence findings without provider calls, report its true authority prominently, and replay from its own run-local bytes. It does not synthesize or publish workspace output; that remains protocol 2.9.
