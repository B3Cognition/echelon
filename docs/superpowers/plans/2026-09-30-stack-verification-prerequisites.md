# Stack Verification Prerequisites Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for native, sequential implementation. Steps use checkbox syntax for tracking. Do not start the next task before verifying the current one.

**Goal:** Require explicit stack intent for Spec and a capability-complete verification contract before Spec readiness and Delivery dispatch.

**Architecture:** Extend the existing stack resolver/preflight and readiness consumers. The harness owns admission, application services render its outcome, and existing pending-step/journal machinery owns recovery. No new orchestration subsystem.

**Tech Stack:** Python dataclasses, existing YAML stack schema, pytest, Prosaic runtime assets.

**Spec:** `docs/superpowers/specs/2026-09-30-stack-verification-prerequisites-design.md` (approved; committed in `cd789e7f`).

## Global Constraints

- “No old-run migration or reset is part of this work.”
- “Do not make it an implicit default in workspace configuration.”
- “Detection may recommend stacks but never silently selects one.”
- “A source-owned empty selection must not fall back silently.”
- “Do not run product commands on the host to prove planning readiness.”
- “CLI wrappers gain no policy of their own.”
- Approved adjustment: permit empty capabilities/archetypes for policy stacks only; scoped policies and other stack kinds remain strict. No new fields or synthetic capabilities.
- Preserve the existing uncommitted capability-guard fix and tests; do not fold them into an unrelated implementation commit.
- Do not restart the paused acceptance Delivery, edit its state or generated code, select a live stack, change caps, or weaken review gates.
- Compatible npm/Three.js observers, semantic visual ordering and requirement-level repair routing remain separate tracked work.

## Review Focus

1. Source-local `selected: []` overriding a valid workspace stack: reject explicitly, never inherit silently (Task 1).
2. A generic marker composed with concrete capabilities: evaluate capabilities, not a blanket ban on the word generic (Task 2).
3. Coverage cases used by multiple targets: validate every responsible target without requiring unrelated capabilities on siblings (Task 2).
4. Owner configuration changes while a dispatch is pending: recover sealed effects without reinterpreting them; block incompatible new dispatches (Task 3).
5. One unsupported sibling in a multi-target run: launch no target before all admission checks pass (Task 3).

## Working checkout and baseline

Use the existing isolated checkout:
`/Users/michalbachorik/work/echelon_r/echelon/.worktrees/browser-evidence-handoff`.
Read its `AGENTS.md` and the approved spec before implementation. Do not create
another checkout or discard existing changes. Confirm `git status --short` at
the start and stage only exact files/patches belonging to each task.

The prior capability guard has 221 passing focused tests and a read-only probe
against the paused candidate. Repository fail-fast has a known failure:
`tests/e2e/test_ralph_convergence.py::TestRalphConvergence::test_converges_within_3_outer_iterations`
because its fixture lacks a canonical spec directory. Report it by name if it
persists; never claim full-suite success from focused tests.

## File responsibilities

- `src/harness/verification_stack_runtime.py`: authoritative project/target stack resolution and explicit Spec selection admission; do not duplicate configuration precedence.
- `src/harness/stacks/preflight.py`: pure capability findings using existing `StackPreflightFinding` values, not process exits or state writes.
- `src/harness/coverage_evidence.py`: existing canonical obligation and task/case ownership parsing; share browser-gate parsing here rather than importing the Delivery controller into readiness.
- `src/harness/phase_a_readiness.py`: structural readiness plus a separate explicit-context build-readiness entry point.
- `src/harness/squad.py`: Spec entry and publication gates at safe existing effect boundaries.
- `src/harness/delivery_controller.py`: direct single-target admission, current contract vs persisted snapshot checks, existing resume semantics.
- `src/echelon/spec_service.py`, `src/echelon/delivery_service.py`: call shared harness checks before expensive dispatch and display consistent findings; no policy duplication.
- `src/harness/squad_executors.py`, `src/harness/stacks/context.py`: keep prompts consistent with admitted owner selection.
- `runtime/stacks/generic/stack.yml`, `runtime/stacks/generic/context.md`: capability-free discovery selection.
- New regression files: `tests/unit/test_spec_stack_prerequisites.py`, `tests/unit/test_verification_capability_preflight.py`, `tests/unit/test_stack_admission_flow.py`.
- Existing tests to extend: `test_verification_stack_runtime.py`, `test_phase_a_readiness.py`, `test_squad_publication.py`, `test_delivery_controller_integration.py`, and Spec/Delivery service-boundary tests.

## Task 1: Explicit Spec selection and generic discovery

Completed 2026-09-30: 129 focused tests passed, including disposable controller
dispatch and Git allocation probes. Schema adjustment: 89 schema/resolver tests.
Repository fail-fast: 96 passed, then the documented convergence fixture failed.
No live workspace edits, installation, or restart.

**Interfaces**

Extend `verification_stack_runtime.py` with:

```python
def require_spec_stack_selection(
    project_root: Path, *, target_roots: tuple[Path, ...] = (),
) -> tuple[ResolvedStacks, ...]:
    roots = target_roots or (project_root,)
    selections = tuple(resolve_verification_stacks(project_root, root) for root in roots)
    for root, resolved in zip(roots, selections, strict=True):
        if not resolved.selected_ids:
            raise VerificationStackResolutionError(
                f"stack_selection_required: {root}: explicitly select a concrete "
                "stack or generic for discovery using echelon stack select"
            )
    return selections
```

All selections are validated before provider dispatch. Existing resolver errors
for malformed IDs/conflicts propagate without turning into candidate repair.

- [x] Write failing tests using temporary owner configuration and the real loader/resolver. Pin empty selection, generic, concrete, unknown IDs, conflicts, and source-local empty override. The direct empty-selection regression starts with:

```python
def test_empty_spec_selection_is_actionable(tmp_path):
    with pytest.raises(VerificationStackResolutionError, match="stack_selection_required"):
        require_spec_stack_selection(tmp_path)
```

- [x] Add service and `SquadController.run`/`run_single_phase` boundary cases: empty selection produces no provider invocation; generic reaches the existing first dispatch. Use the repository's recording squad-provider fixtures; mock only provider execution, not admission.
- [x] Run `.venv/bin/python -m pytest tests/unit/test_spec_stack_prerequisites.py -q`; confirm behavioral failures, not fixture/import mistakes, before implementing the guard.
- [x] Add the helper and generic stack. Use schema 1.4, `stack.id: generic`, `kind: policy`, `owner: echelon`, empty `provides`, no observers/provisioners/requirements, and context explaining discovery-only authority. Do not add generic to configuration defaults or auto-detection recommendations.
- [x] Wire the helper into new-run Spec admission before run allocation/provider dispatch and into direct controller entry before new work. Known targets use existing owner precedence. Pending recovery is not a new-run entry: do not mutate or reject sealed-effect replay here.
- [x] Add the context message: generic leaves framework/package-manager choice open but requires concrete verification capabilities before readiness. Remove no-stack inference advice only from execution-facing paths now requiring explicit selection; read-only stack detection stays available.
- [x] Run the new tests plus `test_verification_stack_runtime.py`, `test_stacks_schema.py`, `test_stacks_resolver.py`, `test_stack_context_prompt.py`, `test_spec_service_boundary.py`. Exercise a disposable service/controller run with a recording provider to show empty selection makes zero calls and generic admits discovery. Do not use the live acceptance workspace.
- [x] Update `docs/simplification-control.md` with actual results; commit only this increment as `fix(spec): require explicit stack intent before dispatch`. Report failures and stop before Task 2 if the admission probe fails.

## Task 2: Capability-complete target-aware build readiness

Completed 2026-09-30: 183 focused tests passed, including static greenfield and
target-scoped capability probes. Adjacent controller tests: 60 passed, four
repair-count expectation failures (expected four chains/112 tokens; current
controller runs five chains/140 tokens). Repository fail-fast: 96 passed, then
the documented canonical-spec convergence fixture failed. These are not full-suite
success receipts.

**Interfaces**

Extend `stacks/preflight.py` with one pure function:

```python
def verification_capability_findings(
    resolved: ResolvedStacks, *, coverage_test_types: Iterable[str],
    browser_required: bool, semantic_visual_required: bool,
    visual_execution_available: bool,
) -> list[StackPreflightFinding]:
    findings = []
    if not resolved.selected_ids:
        findings.append(StackPreflightFinding(
            severity="error", code="stack_selection_required",
            message="Explicit owner stack selection is required.",
        ))
    elif not set(resolved.resolved_ids).difference({"generic"}):
        findings.append(StackPreflightFinding(
            severity="error", code="stack_capabilities_unresolved",
            message="Generic permits discovery, not Delivery readiness.",
        ))
    findings.extend(coverage_observer_preflight_findings(
        resolved, coverage_test_types=coverage_test_types,
    ))
    runtime = resolved.runnability
    browser_capabilities = {"install", "start", "readiness", "primary_journey", "stop"}
    if browser_required and not (
        runtime.classification == "user_facing" and runtime.policy == "required"
        and runtime.runner == "linux_container"
        and browser_capabilities.issubset(runtime.capabilities)
        and "browser_dom" in runtime.required_observations
    ):
        findings.append(StackPreflightFinding(
            severity="error", code="verification_runtime_unavailable",
            message="Required browser execution lacks a supported runtime contract.",
        ))
    if semantic_visual_required and not visual_execution_available:
        findings.append(StackPreflightFinding(
            severity="error", code="semantic_visual_capability_unavailable",
            message="Required semantic visual execution is unavailable.",
        ))
    if runtime.policy == "required" and runtime.runner != "linux_container":
        findings.append(StackPreflightFinding(
            severity="error", code="verification_runtime_unavailable",
            message=f"Required runtime {runtime.runner!r} is unsupported by this executor.",
        ))
    if not browser_required and not runtime.sources:
        findings.append(StackPreflightFinding(
            severity="error", code="stack_capabilities_unresolved",
            message="Declare a runtime or an explicit non-runnable disposition.",
        ))
    return findings
```

These branches enforce the following rules:

- Empty resolved selection: `stack_selection_required`.
- No resolved ID other than generic: `stack_capabilities_unresolved`, even with zero coverage types.
- Required browser execution: require `user_facing`, required runnability policy, supported Linux runner, install/start/readiness/primary_journey/stop capabilities, and browser DOM observation. Missing values yield `verification_runtime_unavailable`; no probing of future candidate commands.
- Required semantic visual execution without the existing configured validator/visual-phase path: `semantic_visual_capability_unavailable`.
- Required non-Linux runtime unsupported by the current executor: explicit unsupported-runner finding, never substitute another runner.

Expose a separate full readiness entry point in `phase_a_readiness.py`:

```python
validate_phase_a_build_readiness(
    state: dict, candidate_spec_dirs: list[Path], *, project_root: Path,
    visual_execution_available: bool,
    allow_pending_retarget_finalization: bool = False,
) -> PhaseAReadinessResult
```

This is the interface declaration; the integration sequence is specified below.
Keep the original structural helper unchanged for artifact-only inspection;
production readiness callers move in Task 3.

- [x] Write literal pure-function tests. For example:

```python
def test_generic_without_obligations_is_not_build_ready():
    resolved = ResolvedStacks(
        selected_ids=["generic"], resolved_ids=["generic"], implied_by={},
        capabilities={}, tools={}, required_commands=[],
        required_registries=[], context_files=[],
    )
    findings = verification_capability_findings(
        resolved, coverage_test_types=(), browser_required=False,
        semantic_visual_required=False, visual_execution_available=False,
    )
    assert "stack_capabilities_unresolved" in {finding.code for finding in findings}
```

- [x] Cover generic plus concrete observers, optional-only observers, unmapped/malformed coverage, owner deferrals, supported custom npm/browser capability contracts with no product files, missing visual availability, and unsupported runners. Assert capabilities, not particular framework names.
- [x] Add full readiness tests using the existing valid Phase A artifact fixtures. Two targets with different test types must each pass with only their own observer. Missing task ownership must block; a case owned by tasks on both targets must be checked on both.
- [x] Run `.venv/bin/python -m pytest tests/unit/test_verification_capability_preflight.py -q` and verify the expected red cases.
- [x] Implement pure findings with existing `StackPreflightFinding` objects. Parse active canonical obligations with `parse_coverage_map_obligations` and `active_entries`; reject invalid maps before type selection. For each canonical target, use `validate_task_targets` and `task_owned_coverage_case_ids` to project case IDs. Require every active case to have declared target ownership. Shared cases apply to every owner target. For a true single-repository spec without target declarations, all active obligations apply to the project root.
- [x] Move the existing published browser/semantic-gate parsing into `coverage_evidence.py` as `published_browser_gate_required(spec_dir)` and `published_semantic_visual_gate_required(spec_dir)`. Preserve existing parsing semantics and reuse it from Delivery and readiness. Apply those obligations to declared browser/visual task owners, not unrelated backend siblings; ambiguous ownership is a blocker. Browser e2e obligations also require the supported browser runtime. Do not create a second Markdown parser or infer UI modality from filenames.
- [x] Implement `validate_phase_a_build_readiness`: retain structural failure unchanged; resolve every canonical target through `resolve_verification_stacks`; evaluate scoped capabilities; return target-qualified findings while preserving missing-artifact diagnostics. Treat missing authoritative context as an error; never infer it from a candidate worktree or a spec parent-directory guess.
- [x] Run new tests plus `test_phase_a_readiness.py`, `test_stacks_preflight.py`, `test_coverage_evidence.py`, `test_task_targets.py`, and `test_verification_stack_runtime.py`. Probe temporary valid Spec artifacts with generic-only versus concrete-capable owner configuration: the former cannot become ready and the latter can, before code exists.
- [x] Record results and commit as `fix(spec): validate target verification capabilities for readiness`. Stop on failed functional readiness probe.

## Task 3: Publication, Delivery admission and recovery integration

Completed 2026-09-30, locally verified; not installed, pushed, or live-accepted.
Current-tree named gate: 295 passed in 35.15s. Expanded admission/recovery gate:
699 passed in 206.14s; adjacent retarget/readiness/prompt/review gate: 394 passed
in 19.68s. Counts overlap; do not sum them as unique tests. Final repository
fail-fast: 96 passed, one known convergence-fixture failure in 39.55s. Dry-run:
156 RE modules import and all nine bundle checks pass.

One independent review found three Important issues (continuation forwarding,
effects-only recovery ordering, per-phase Spec admission) and a prompt archetype
regression regraded Important. All were reproduced and corrected. Functional
probes use real state stores, receipt journals, dispatch/finalization and temporary
Git repositories; external providers are recorded, not executed. Saved publication
and review effects settle despite current contract drift, then new work blocks.
Review effects now restore the saved review phase through existing valid state
transitions. Source-owner prompt context uses orchestration-owned custom stack
definitions, including in target-specific harness directories.

The prior missing-coverage guard is separately committed as `1466833f`. The
accidental test salvage commit is retained on `backup/accidental-salvage-88033cd9`;
legitimate changes were recovered with explicit user approval. Test artifacts and
command logs remain in `.superpowers/sdd/2026-09-30-stack-verification-prerequisites/`.
No generated demo source, Delivery state, caps, or review gates were changed.

Follow-ups remain: compatible npm/Three.js observers with real evidence,
semantic visual ordering, requirement-level repair routing, preserved-candidate
Delivery acceptance and fresh-workspace acceptance. This plan does not close STAB-1.

**Interfaces**

Consume `validate_phase_a_build_readiness` from Task 2. Supply visual availability
from actual owner runtime configuration and role/executor support used by
`DeliveryController`, not a hard-coded `True`. Static availability means the
installed semantic-validator role can be resolved and the configured controller
will enable its phase; it does not mean a provider has issued a passing verdict.

Keep `validate_phase_a_readiness` for explicitly structural inspection only.
Production publication/admission, readiness summaries, retarget completion and
review-reentry readiness must use the same capability-aware result.

- [x] Add failing tests to `test_stack_admission_flow.py`, using existing real state stores/controllers and recording external providers. Pin the outcomes:

```python
assert result.ready is False
assert "coverage_observer_unavailable" in "\n".join(result.blockers)
assert provider.calls == []
assert state_after["pending_spec_step"] == state_before["pending_spec_step"]
```

Use separate cases for readiness rejection and pending replay; a provider call
that is the authorized replay is not counted as a new dispatch. For the pending
case, assert the exact saved assignment and input digest, then no subsequent
dispatch under incompatible current config. Also assert that supported concrete
selection reaches implementation rather than only asserting rejection.

- [x] Add a multi-target service test where target A is valid and target B lacks a required observer. Assert zero child launches, no task-progress mutation, and a target-B diagnostic. Swap target ordering to prove this is not a first-target shortcut.
- [x] Add drift cases: changed stack selection, changed observer definition under the same ID, and source-local empty override. Existing passing evidence must not be reused under a different contract hash; pending effects must not be rewritten.
- [x] Run `.venv/bin/python -m pytest tests/unit/test_stack_admission_flow.py -q`; confirm failures at real readiness/dispatch boundaries.
- [x] Wire full readiness into Squad publication preparation before effects are sealed. Keep replay of already sealed effects under the existing pending-step contract; revalidate before the next new dispatch and before reporting current readiness. Update Spec status/continue/readiness service consumers to render the same result, without a second recovery policy.
- [x] Wire shared admission into `DeliveryController` after authoritative context resolution and before new implementer dispatch. For multi-target service dispatch, evaluate all targets before launching the first child. Services only forward context/render findings. Direct-controller entry must enforce the same check; no Typer-wrapper-only validation.
- [x] Reuse existing persisted stack snapshots and receipt fingerprints. If current owner inputs differ while an operation is pending, preserve/recover that operation under its saved identity; do not fabricate a new snapshot or update sealed dispatch fields. Block any new dispatch requiring an unsupported current contract. Keep prerequisite failures out of product repair and meaningful-attempt accounting.
- [x] Update readiness fixtures intentionally: give positive fixtures an explicit owner contract; keep dedicated negative empty-selection tests. Do not loosen production gates or silently default every test to generic.
- [x] Run `test_stack_admission_flow.py`, `test_spec_service_boundary.py`, `test_delivery_service_boundary.py`, `test_squad_publication.py`, `test_squad_publication_inspection.py`, `test_delivery_controller_integration.py`, `test_phase_a_readiness.py`, `test_coverage_capability_gate.py`, and existing current-state recovery tests selected by touched call sites.
- [x] Run a disposable admission flow: generic admits Spec discovery; generic-only cannot publish ready; compatible custom capabilities permit readiness and first Delivery dispatch; missing sibling capability yields zero target launches. Use retained controller/provider traces, not generated product edits or status-text matching.
- [x] Run `.venv/bin/python -m pytest -x -q` and `bash scripts/bash/dry-run.sh`. Record exact failures, including the known fixture if still present. A stopped fail-fast run is not a full-suite pass.
- [x] Update `docs/simplification-control.md` with completed/pending items, functional receipts and verification results. Request one independent read-only branch review under the native execution method. Fix important findings and rerun affected functional checks before committing this increment as `fix(delivery): enforce capability-ready admission across entry points`.

## Stop and handoff

After each increment, report its actual functional outcome and next item. Do not
start configuring the live demo or implementing the separate observer bundle
inside this plan. No push or Delivery restart is included. Once all three
increments pass, propose native validation of compatible observers on the
preserved candidate; a from-scratch twelve-task build is not required for these
admission checks.
