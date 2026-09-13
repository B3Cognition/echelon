# Fulfillment Preparation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Inline execution is the recommended choice for these sequential, shared-file tasks; do not dispatch implementation agents without the user's choice.

**Goal:** Provide a tested Python-owned preparation sequence for future controlled fulfillment without activating that sequence in delivery.

**Architecture:** Extract the preparation writers' CLI-owned state semantics into narrow reusable functions, then compose them behind an explicit, validated verify-run context. Keep the current runner and CLI dispatch behavior; preparation ends before semantic mapping and cannot report fulfillment success.

**Tech Stack:** Python, pytest, existing harness writers and atomic JSON utilities; existing scripted Node graph-tool fixtures.

**Spec:** `docs/superpowers/specs/2026-09-13-controlled-fulfillment-ownership-design.md`, Phase 1 only; approved after commit `8c582881`.

## Global Constraints

- "There is no extra COMMANDER role and no new \"when run from delivery\" branch in shared role prose."
- "Existing deterministic writers and parsers remain authoritative; do not duplicate their algorithms."
- "The controlled route is not wired into active delivery until all required full/scoped/recovery pieces pass."
- "Keep feature-off delivery and standalone spec verification on their existing contracts."
- "Retain identity guards and existing six-digit/unbounded ID compatibility."
- No edits to AGENTS.md/CLAUDE.md, provider adapters, Prosaic roles, legacy build behavior, public configuration or installation scripts in Phase 1.
- No semantic dispatch, model-result schema, report publication transaction, usage-accounting migration, cache cutover or durable semantic recovery in this phase. Those belong to design Phases 2–4.
- No live graph runtime installation, model calls, push, merge, workspace migration or rollout. Script graph execution at its external boundary in tests.

## Execution context and file boundaries

Worktree: `/Users/michalbachorik/work/echelon_r/echelon/.worktrees/delivery-controller-contract`.
Python: `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python`.
Run every command below from that worktree. Preserve unrelated work and use
`apply_patch` for edits. This plan was prepared against `8c582881`; verify HEAD
and the relevant signatures before execution.

| File | Responsibility |
| --- | --- |
| New `src/harness/fulfillment_preparation_steps.py` | Existing writer calls plus their existing CLI state stamps/degradation handling; no phase selection |
| New `src/harness/fulfillment_preparation.py` | Explicit context validation and fixed preparation order; no provider or model dependency |
| Modify `src/harness/__main__.py` | Delegate only the extracted preparation operations; retain arguments, stdout/stderr and exit behavior |
| New `tests/unit/test_fulfillment_preparation_steps.py` | Direct helper contracts, stamps, malformed prerequisites and degraded results |
| New `tests/unit/test_fulfillment_preparation.py` | Real preparation sequence, explicit scope/source binding and read/write boundaries |
| Existing relevant unit tests | CLI compatibility and existing runner full/scoped behavior |
| Design/boundary records | Record actual evidence and limits after implementation, not beforehand |

Do not change `FulfillmentRunner.refresh`, `_refresh_scoped`, Ralph or the direct
spec-verification CLI to call preparation in this phase. A callable with consuming
tests is the deliverable; absence of active wiring is intentional, not closure of
the fulfillment ownership gap.

## Task 1: Reusable preparation steps with CLI compatibility

**Files:** Create `fulfillment_preparation_steps.py` and its test file; modify
only preparation handlers in `src/harness/__main__.py`.

**Consumes:** Existing writer result types in `canonical_requirements`,
`product_inventory`, `codegraph_evidence`, `perlgraph_evidence`,
`codegraph_evidence_mapper`, and `coverage_evidence`.

**Produces:** Keyword-only helpers with these signatures (import the named result
types from their existing modules):

```python
def prepare_codegraph(*, project_root: Path, verify_run_dir: Path,
                      spec_dir: Path) -> CodeGraphEvidenceResult: ...
def prepare_perlgraph(*, project_root: Path, verify_run_dir: Path,
                     spec_dir: Path) -> PerlGraphEvidenceResult: ...
def prepare_canonical_requirements(*, spec_dir: Path,
                                   verify_run_dir: Path) -> CanonicalRequirementInventoryResult: ...
def prepare_product_inventory(*, project_root: Path,
                              verify_run_dir: Path) -> ProductInventoryResult: ...
def prepare_requirement_audit(*, verify_run_dir: Path) -> RequirementAuditResult: ...
def prepare_evidence_map(*, requirement_audit_path: Path, codegraph_analysis_path: Path,
                         tasks_path: Path, out_json_path: Path, out_md_path: Path,
                         coverage_map_path: Path | None = None) -> EvidenceMapResult | None: ...
def prepare_coverage(*, spec_dir: Path, verify_run_dir: Path,
                     observer_required: bool = False,
                     observation_path: Path | None = None) -> CoverageEvidenceResult: ...
def load_preparation_observation(*, spec_dir: Path, verify_run_dir: Path,
                                observer_required: bool,
                                observation_path: Path | None
                                ) -> tuple[bool, CoverageObservationResult | None]: ...
```

Here `None` from `prepare_evidence_map` means the existing explicit
`skipped_degraded_codegraph` result, not success with inferred evidence.

- [ ] **1. Characterize existing boundaries before extraction.** Run and retain
  results for the existing CLI artifact/graph tests and `test_fulfillment_runner.py`.
  Add direct-versus-CLI assertions to the new steps test file, starting with:

```python
def test_inventory_step_preserves_run_fields_and_counts(tmp_path):
    import json
    from harness.fulfillment_preparation_steps import prepare_canonical_requirements
    spec, run = tmp_path / "spec", tmp_path / "run"
    spec.mkdir()
    run.mkdir()
    (spec / "spec.md").write_text("# Spec\nFR-000001: Return a greeting.\n")
    (run / "state.json").write_text(json.dumps({"keep": "sentinel"}))
    result = prepare_canonical_requirements(spec_dir=spec, verify_run_dir=run)
    state = json.loads((run / "state.json").read_text())
    assert result.count == state["canonical_requirements_count"] == 1
    assert state["canonical_requirements"] == "ready"
    assert state["keep"] == "sentinel"
```

- [ ] **2. Run the new test and observe the missing helper failure.**

```bash
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest tests/unit/test_fulfillment_preparation_steps.py -xq
```

- [ ] **3. Extract, do not recreate, the existing behavior.** Move the writer-call
  and state-update portions of `_write_codegraph_evidence`,
  `_write_perlgraph_evidence`, `_write_canonical_requirements`,
  `_write_product_inventory`, `_write_requirement_audit`,
  `_write_codegraph_evidence_map` and `_write_coverage_evidence` into the helpers.
  Keep CLI parsing/printing/SystemExit in `__main__.py`. The canonical helper's
  body follows this pattern; the other helpers move their own exact existing stamps:

```python
_require_preparation_state(verify_run_dir)
result = write_canonical_requirements(spec_dir=spec_dir, verify_run_dir=verify_run_dir)
_stamp_preparation_state(verify_run_dir, {
    "canonical_requirements": "ready",
    "canonical_requirements_count": result.count,
})
return result
```

  Define `_require_preparation_state(Path) -> None` and
  `_stamp_preparation_state(Path, dict[str, object]) -> None` locally from the
  existing preparation state semantics. Preserve valid-state fields, require an
  existing state file, and use `write_json_atomic(..., trusted_root=verify_run_dir)`
  for writes. Preserve legacy malformed-JSON behavior at the CLI compatibility
  boundary; the controlled sequence in Task 2 rejects malformed state before
  calling these steps. Do not globally change unrelated CLI state helpers.

  Graph helpers stamp ready/degraded exactly as today and re-raise the original
  typed graph exception after its degraded stamp; the CLI still prints its current
  diagnostic and exits 1. Move the exact skipped-map payload/rendering rather than
  creating a second schema. Missing input errors must retain the CLI's nonzero
  result without synthesizing an upstream artifact.

  `load_preparation_observation` extracts the existing context lookup, observation
  loading and coverage-map hash check as a read-only function. `prepare_coverage`
  calls it, extracts active deferred IDs, invokes the existing coverage writer and
  owns the ready/invalid state updates. Keep explicit-option precedence and required-observer behavior; never
  interpret a malformed present context as optional evidence. Raise the existing
  observation exception to the CLI diagnostic boundary, rather than SystemExit
  inside the library function.

- [ ] **4. Cover both library and real CLI consumers.** Add parametrized direct
  helper cases for missing state, preserved unrelated fields, absent analysis
  with and without recorded degradation, missing audit/tasks, observer missing,
  malformed context and changed coverage map. Check exact existing state keys and
  resulting artifact schemas. Reuse graph fake-process fixtures already in
  `test_harness_main_codegraph_evidence.py` and
  `test_harness_main_perlgraph_evidence.py`; never call installed graph services.

- [ ] **5. Verify and commit this extraction separately.**

```bash
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest tests/unit/test_fulfillment_preparation_steps.py tests/unit/test_harness_main_fulfillment_artifacts.py tests/unit/test_harness_main_codegraph_evidence.py tests/unit/test_harness_main_perlgraph_evidence.py tests/unit/test_coverage_evidence.py -q
git diff --check
git add src/harness/fulfillment_preparation_steps.py src/harness/__main__.py tests/unit/test_fulfillment_preparation_steps.py
git commit -m "refactor: share deterministic fulfillment preparation steps"
```

## Task 2: Explicitly bound preparation sequence

**Files:** Create `fulfillment_preparation.py` and its test file. Task 1 helpers
may receive only fixes demonstrated by these consuming tests.

**Consumes:** Task 1 functions, `write_topology_evidence_receipt`, and a caller-owned
run previously initialized by `init_verify_spec_run`.

**Produces:** These dataclasses and entry point; all paths are explicit caller inputs:

```python
@dataclass(frozen=True)
class FulfillmentPreparationContext:
    project_root: Path
    workspace_root: Path
    source_id: str
    source_root: Path
    spec_id: str
    spec_dir: Path
    verify_run_dir: Path
    scope: str = "full"
    scoped_ids: tuple[str, ...] = ()
    base_full_verify_commit: str = ""
    observer_required: bool = False
    observation_path: Path | None = None

@dataclass(frozen=True)
class PreparedFulfillmentInputs:
    verify_run_dir: Path
    canonical_ids: tuple[str, ...]
    scoped_ids: tuple[str, ...]
    topology_status: str

class FulfillmentPreparationError(ValueError):
    pass

def prepare_fulfillment_inputs(context: FulfillmentPreparationContext) -> PreparedFulfillmentInputs:
    ...
```

- [ ] **1. Build a real temporary source/spec/run fixture and write the admission
  test first.** Imports are `json`, `pytest`, the context/entry/error above and
  `init_verify_spec_run`. The following fixture is local to the new test file:

```python
@pytest.fixture
def preparation_context(tmp_path):
    workspace = tmp_path / "workspace"
    source = workspace / "sources/api"
    spec = workspace / "specs/001-greeting"
    source.mkdir(parents=True)
    spec.mkdir(parents=True)
    (workspace / ".echelon").mkdir()
    (workspace / ".echelon/config.yml").write_text(
        "workspace:\n  sources:\n    - id: api\n      path: sources/api\n")
    (source / "app.py").write_text("def hello(): return 'hello'\n")
    (spec / "spec.md").write_text("# Spec\nFR-000001: Return a greeting.\n")
    (spec / "tasks.md").write_text(
        "- [ ] T-000001 complexity=standard phase=build req=FR-000001 depends=none\n")
    run = init_verify_spec_run(project_root=source, spec_id="001", spec_dir=spec,
                               timestamp="preparation").verify_run_dir
    return FulfillmentPreparationContext(source, workspace, "api", source, "001", spec, run)

def test_wrong_spec_binding_is_rejected_before_writes(preparation_context):
    context = preparation_context
    state_path = context.verify_run_dir / "state.json"
    state = json.loads(state_path.read_text())
    state["spec_id"] = "different"
    state_path.write_text(json.dumps(state))
    before = state_path.read_bytes()
    with pytest.raises(FulfillmentPreparationError, match="spec"):
        prepare_fulfillment_inputs(context)
    assert state_path.read_bytes() == before
    assert not (context.verify_run_dir / "canonical-requirements.json").exists()
```

- [ ] **2. Run the new tests and observe the missing entry point failure.**

```bash
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest tests/unit/test_fulfillment_preparation.py -xq
```

- [ ] **3. Implement admission before any preparation write or graph call.**
  Add `_validate_context(context) -> dict[str, object]` in the sequence module.
  Require a regular, readable state JSON object with `status=in_progress`; exact
  spec ID, project/spec/workspace/run paths, scope/ordered scoped IDs and base full
  commit matching the supplied context. Validate full/scoped constraints already
  defined by `init_verify_spec_run`. Reject paths outside the authorized run root,
  symlinked state/output destinations and missing spec/tasks. Use the existing
  workspace manifest to validate source ID/root, allowing a registered delivery
  worktree distinct from the source checkout as the topology helper does. Do not
  replace source identity with the current directory's basename.

  Reject present semantic artifacts (`implementation-map.md`,
  `judgment-prepass.json`, `fulfillment-report.fallback.md`) before preparation;
  recovery of those inputs is Phase 3, not permission to overwrite them now.
  Validate the required observation/context before graph execution by calling
  Task 1's non-writing `load_preparation_observation` with the context fields.
  Do not initialize a replacement run, search `runs/.current`, or guess "latest".

  For the persisted binding check use the existing state's field names, not a
  new competing context schema:

```python
expected = {
    "spec_id": context.spec_id,
    "project_root": str(context.project_root.resolve()),
    "orchestration_root": str(context.workspace_root.resolve()),
    "spec_dir": str(context.spec_dir.resolve()),
    "verify_run_dir": str(context.verify_run_dir.resolve()),
    "verify_scope": context.scope,
    "scoped_ids": list(context.scoped_ids),
    "base_full_verify_commit": context.base_full_verify_commit,
}
for key, value in expected.items():
    if state.get(key) != value:
        raise FulfillmentPreparationError(f"verify run {key} binding mismatch")
load_preparation_observation(
    spec_dir=context.spec_dir, verify_run_dir=context.verify_run_dir,
    observer_required=context.observer_required,
    observation_path=context.observation_path)
```

- [ ] **4. Compose the existing writers in fixed order.** No dynamic phase graph,
  plugin registry or provider parameter is needed. The body after admission uses:

```python
for write_graph, degraded_error in (
    (prepare_codegraph, CodeGraphEvidenceError),
    (prepare_perlgraph, PerlGraphEvidenceError),
):
    try:
        write_graph(project_root=context.project_root, verify_run_dir=context.verify_run_dir,
                    spec_dir=context.spec_dir)
    except degraded_error:
        pass  # the step already persisted the exact degraded result
topology = write_topology_evidence_receipt(
    context.project_root, context.verify_run_dir, context.spec_dir,
    workspace_root=context.workspace_root, source_id=context.source_id,
    source_root=context.source_root)
prepare_canonical_requirements(spec_dir=context.spec_dir, verify_run_dir=context.verify_run_dir)
prepare_product_inventory(project_root=context.project_root, verify_run_dir=context.verify_run_dir)
prepare_requirement_audit(verify_run_dir=context.verify_run_dir)
prepare_coverage(spec_dir=context.spec_dir, verify_run_dir=context.verify_run_dir,
                 observer_required=context.observer_required,
                 observation_path=context.observation_path)
coverage_map = context.spec_dir / "coverage-map.md"
prepare_evidence_map(
    requirement_audit_path=context.verify_run_dir / "requirement-audit.md",
    codegraph_analysis_path=context.verify_run_dir / "codegraph-analysis.json",
    tasks_path=context.spec_dir / "tasks.md",
    out_json_path=context.verify_run_dir / "codegraph-evidence-map.json",
    out_md_path=context.verify_run_dir / "codegraph-evidence-map.md",
    coverage_map_path=coverage_map if coverage_map.is_file() else None)
```

  Read ordered canonical IDs from the actual generated inventory (reject invalid
  rows and duplicate IDs); require every scoped ID to exist. Return
  `PreparedFulfillmentInputs(context.verify_run_dir, canonical_ids,
  context.scoped_ids, topology.status)`. Keep full inventories in scoped mode;
  scoped IDs define subsequent semantic selection, not permission to erase
  canonical rows. Translate prerequisite/writer errors to
  `FulfillmentPreparationError` with step-specific context. Do not catch unexpected
  exceptions as graph degradation, mark lifecycle complete, or report fulfillment
  as passed. Preserve partial diagnostic artifacts on failure.

- [ ] **5. Add consuming acceptance cases.** With real writers and fake external
  graph processes, assert the fixed helper order using pass-through spies and
  inspect every resulting artifact/state stamp. Add ready/degraded/unsupported
  graph cases, unavailable topology evidence, wrong source binding, malformed or
  terminal state, wrong scope/base commit, symlink escape, missing tasks,
  preserved prior reports, and invalid required observations. Full/scoped cases
  must retain `FR-000001`, a legacy ID and a seven-digit ID exactly as authored.
  Assert no implementation map, final report, completion marker or ledger is created.

  Snapshot canonical spec/source bytes before and after successful preparation;
  only existing graph-tool scratch behavior and files under the selected run are
  allowed to change. Reuse the actual graph writers; mock their external process
  boundary only. Use the topology fixture patterns in `test_topology_evidence.py`
  for managed delivery worktrees rather than stubbing the topology validator.

- [ ] **6. Verify and commit the callable without activation.**

```bash
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest tests/unit/test_fulfillment_preparation.py tests/unit/test_fulfillment_preparation_steps.py tests/unit/test_topology_evidence.py tests/unit/test_canonical_requirements.py tests/unit/test_product_inventory.py tests/unit/test_codegraph_evidence_mapper.py -q
git diff --check
git add src/harness/fulfillment_preparation.py tests/unit/test_fulfillment_preparation.py
git commit -m "feat: add bound deterministic fulfillment preparation"
```

## Task 3: Phase 1 compatibility acceptance and handoff

**Files:** Existing tests below, the new preparation test files, and the design/
convergence records. No new production feature belongs to this task.

**Consumes:** Tasks 1–2. **Produces:** Verified Phase 1 checkpoint and exact remaining
limits. The next phase can call `prepare_fulfillment_inputs` only with an admitted,
explicit run context; it must supply its own semantic/recovery boundary.

- [ ] **1. Run the complete affected batch once after final code changes.**

```bash
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest tests/unit/test_fulfillment_preparation.py tests/unit/test_fulfillment_preparation_steps.py tests/unit/test_harness_main_fulfillment_artifacts.py tests/unit/test_harness_main_codegraph_evidence.py tests/unit/test_harness_main_perlgraph_evidence.py tests/unit/test_canonical_requirements.py tests/unit/test_product_inventory.py tests/unit/test_codegraph_evidence_mapper.py tests/unit/test_coverage_evidence.py tests/unit/test_topology_evidence.py tests/unit/test_verify_spec_run_init.py tests/unit/test_fulfillment_runner.py tests/unit/test_scoped_verify.py tests/unit/test_verified_fulfillment_ledger.py tests/unit/test_cli_fulfillment_commands.py tests/unit/test_cli_spec_reconcile_fulfillment.py -q
```

- [ ] **2. Check scope and actual consumers.**

```bash
git diff --check
git diff --stat 8c582881
rg -n 'prepare_fulfillment_inputs|fulfillment_preparation' src tests
```

  No new call from Ralph, `FulfillmentRunner.refresh`, `_refresh_scoped` or
  `cli_app.py` is allowed. Existing full/scoped cache, fallback, provider execution,
  reconciliation and failure behavior must pass unchanged. Record pre-existing
  failures separately; do not widen this phase to unrelated repairs.

- [ ] **3. Request one scoped independent review using requesting-code-review.**
  Give the reviewer the design, this plan and the exact diff. Focus on CLI state
  parity, source/run binding, graph-degradation classification, observer evidence
  and absence of activation. Reuse test receipts rather than rerunning unchanged
  suites. Fix demonstrated Phase 1 defects with a failing test; stop on a required
  design expansion.

- [ ] **4. Record and commit evidence.** Update this checklist and the convergence
  boundary with actual test counts, reviewer result, external stubs and remaining
  phases. Say explicitly that semantic mapping, fulfillment completion, provider
  support acceptance and delivery cutover have not been exercised by preparation.
  Commit only scoped records and report the clean/dirty state truthfully.

## Plan self-review and execution choice

This plan covers design Phase 1 only. Tasks 1–2 provide shared deterministic
preparation; Task 3 proves legacy compatibility and records its limits. Phases
2–4 remain separate by design. No new provider abstraction, workflow engine,
identity feature or activation flag is introduced.

Choose inline execution with `executing-plans` for the sequential shared-file
work, or explicitly choose subagent-driven execution with its review gates.
