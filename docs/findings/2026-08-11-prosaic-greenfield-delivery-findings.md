# EGR-153 Through EGR-159 Prosaic-First Greenfield Delivery Findings

**Review date:** 2026-08-11
**Source incident:** Greenfield `Hello, World!` specification and delivery
**Workspace:** `/Users/michalbachorik/work/echelon-greenfield-hello`
**Provider:** Codex CLI
**Migration mode:** Prosaic-first; no `.specify` directory was present

## Summary

A full greenfield run proved that Echelon can create a specification and build a
working product from deployed `.echelon/prosaic` and `.echelon/runtime` bundles.
The resulting program, unit test, and measured runtime verifier pass. The
delivery nevertheless exhausted its outer-iteration cap because three
repository-wide cardinality claims remained unverified.

The run also exposed independent opportunities in delivery diagnostics,
specification proportionality, documentation convergence, provider telemetry,
test-runner interpreter selection, and generated-artifact retention. They are
tracked separately below so migration correctness is not confused with later
prompt-quality or operational-efficiency work.

## Reproduction Evidence

Canonical retained evidence:

- run: `runs/targets/hello-world/runs/build-20260811-094606-389227`
- state: `state/default.json`
- specification: `specs/001-create-minimal-python-hello/spec.md`
- plan: `specs/001-create-minimal-python-hello/plan.md`
- tasks: `specs/001-create-minimal-python-hello/tasks.md`
- fulfillment gaps: `specs/001-create-minimal-python-hello/fulfillment-gaps.md`
- final delivery worktree: `worktrees/default/iter-4`

Observed successful product checks:

- `python hello.py` wrote exactly `Hello, World!` followed by a newline.
- `python -m unittest discover` passed one test.
- `python verify_runtime.py` recorded 10 of 10 conforming invocations,
  dependency-isolated execution, no prohibited network or protected-data
  instructions, and zero durable product changes.
- `find ... -name .specify` returned no paths.

Observed delivery cost and terminal state:

- 18 build/fix provider calls;
- 5,472.361 seconds of recorded provider duration, approximately 91 minutes;
- longest provider call: 1,311.235 seconds;
- all provider calls recorded `tokens: 0`;
- terminal status: `blocked`, reason `outer_cap`;
- all 24 canonical tasks were complete;
- three fulfillment rows remained `UNVERIFIED`: AC-016, FR-001, and FR-022.

## EGR-153: Product Evidence Boundary Includes Deployed Runtime

**Priority:** P0
**Status:** fixed

The target delivery worktree contains deployed `.echelon/prosaic` and
`.echelon/runtime` alongside product files. Fulfillment evidence did not
establish repository-wide cardinality for exactly one `README` and exactly one
executable `hello.py`, even though the intended product artifacts were present
and directly verified.

The verifier needs an explicit product evidence boundary. Echelon-owned runtime
and prose deployment is orchestration infrastructure, not product inventory.
Cardinality and product-source evidence must exclude it without excluding
legitimate hidden product files generally.

### Acceptance direction

- Product inventory excludes deployed `.echelon/prosaic` and
  `.echelon/runtime` paths.
- Direct source, test, and measured-evidence changes at the product root still
  invalidate fulfillment caches.
- The retained greenfield run reaches a verified cardinality judgment without
  weakening AC-016, FR-001, or FR-022.

### Resolution evidence

Fresh run `build-20260811-153057-254453` generated the bounded product inventory
from the deployed target worktree. It counted exactly one root `README.md` and
one root `hello.py` while excluding `.echelon`, `.git`, and the harness status
marker. AC-016, FR-001, and FR-022 were judged `IMPLEMENTED`; the final full
refresh reported 42 reused rows and zero unresolved rows.

## EGR-154: Fulfillment Feedback Hides Actionable Gaps

**Priority:** P1
**Status:** fixed

Most failed verification entries contained only the generic message that the
fulfillment report had unresolved statuses. The actual three requirement IDs,
their statuses, and the recommended deterministic inventory evidence remained
inside `fulfillment-gaps.md`. Consequently, repair agents repeatedly spent time
rediscovering the same terminal condition.

No-progress detection also operated on the generic failure signature rather
than the concrete gap set. The run consumed every available inner and outer
iteration despite all tasks being complete and the final unresolved set being
stable.

### Acceptance direction

- Verify results include each unresolved requirement ID, status, summary, and
  recommended action.
- Failure fingerprints use the normalized concrete gap set.
- An unchanged gap set with no product/evidence delta routes to COMMANDER or a
  deterministic blocker before exhausting every configured repair iteration.
- A changed gap set remains eligible for repair even when the wrapper failure
  category is still `fulfillment-gaps`.

### Implementation status

Implemented: verification failures now carry normalized structured gap
rows, repair text names every concrete row, and an unchanged gap/evidence pair
blocks after one COMMANDER attempt. Focused Ralph and fulfillment regressions
exercise both the deterministic blocker and evidence/gap changes that remain
eligible for repair.

## EGR-155: CARTOGRAPHER Output Is Disproportionate To Feature Scope

**Priority:** P1
**Status:** fixed

The request was to create a minimal Python Hello World program. First-pass
artifacts expanded it into:

- a 245-line specification;
- 42 requirements: 22 FRs, 7 NFRs, and 13 ACs;
- a 182-line plan;
- a 528-line task document containing 24 tasks.

The requirements are individually rigorous, but many restate the same observable
contract across FR, AC, test-oracle, documentation, and measured-evidence forms.
That multiplication materially increased implementation, fulfillment, and
repair cost and introduced repository-cardinality obligations unrelated to the
user's minimal outcome.

This is a prompt-quality improvement, not a Prosaic migration blocker. Preserve
the exact artifacts and metrics above as the regression fixture when changing
CARTOGRAPHER.

### Acceptance direction

- CARTOGRAPHER classifies feature complexity before authoring.
- Small deterministic features use a bounded, evidence-backed requirement set
  without quotas that force redundant FR/NFR/AC rows.
- Acceptance criteria verify requirements rather than restating every
  implementation and observation detail as another requirement.
- Quality gates retain atomicity, testability, negative behavior, and explicit
  uncertainty without rewarding document volume.
- A repeated Hello World benchmark demonstrates materially smaller artifacts
  while preserving the grounded output, no-other-output, successful-termination,
  and no-input contract. Unsupported raw line-ending and numeric exit-code
  values remain explicit unknowns rather than becoming guessed requirements.

### Implementation evidence

The canonical Prosaic CARTOGRAPHER prose now classifies features as small,
moderate, or complex before authoring. It requires one canonical formal
requirement per distinct observable obligation, treats acceptance criteria as
verification paths, and prohibits invented NFR categories, entities, scenarios,
post-MVP scope, and document-volume quotas. The canonical template keeps stable
top-level headings while marking unsupported entries and subsections as
conditional; it no longer demonstrates multiple FR or NFR rows as an implicit
minimum.

Focused Cartographer and Phase 1 contract verification passes 15 tests. The
supported Python 3.11 environment also passes 67 Cartographer, Phase 1, Prosaic
package-install, optional-codegen-install, and runtime-deployment tests with:

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_cartographer_templates.py \
  tests/unit/test_phase1_quality.py \
  tests/unit/test_optional_codegen_install.py \
  tests/unit/test_prosaic_package_install.py \
  tests/unit/test_workspace_init_deploy_runtime.py
```

### Real-provider benchmark

Fresh Codex banzai run `spec-20260811-175308-671946` in
`/Users/michalbachorik/work/echelon-greenfield-proportionality-20260811`
used the exact request `do hello world in python` and the deployed current
Prosaic/runtime bundles.

- First-pass `spec.md`: 90 lines, 4 FRs, 0 NFRs, and 3 ACs.
- Quality-certified `spec.md`: 122 lines, 9 FRs, 0 NFRs, and 9 ACs.
- Final Understanding scores: overall `0.7516`, structure `0.8722`,
  testability `0.7526`, semantic `0.8407`, cognitive `0.6879`, readability
  `0.6533`, depth `0.5602`, and behavioral `0.8396`.
- SAGE WHY2 passed, and the deterministic Spec Lexicon gate reported zero
  findings.

The certified contract retains one directly runnable Python script, exactly 13
visible characters matching `Hello, World!`, exactly one greeting on standard
output, exactly zero application-output items on other channels, no input,
file, network, or retained-state effects, and observable process completion.
The original generated requirement for a numeric zero exit status and a raw
newline byte was not grounded in the short user request; the new specification
keeps those evaluator-specific values open instead of guessing.

The benchmark required seven CARTOGRAPHER passes despite remaining at 18 formal
rows. EGR-150 now carries the reproduced numeric-syntax compatibility evidence,
and EGR-162 separately tracks aggregate-gate convergence so the proportionality
fix is not conflated with validation efficiency.

## EGR-156: Documentation Repair Does Not Converge Reliably

**Priority:** P1
**Status:** fixed

The documentation phase successively produced three deterministic gate
failures:

1. `documentation-impact-report.md` did not set `docs_required`;
2. `docs_required: true` did not establish both expected documentation updates;
3. `docs_required: false` did not include the required reason.

The Prosaic TECH WRITER prose already contains the report schema. The follow-up
must therefore trace rendered prose, companion availability, dispatch context,
and repair feedback before changing prose. Do not assume that the neutral source
is missing the contract.

### Acceptance direction

- Capture the rendered TECH WRITER and DOCS VERIFIER instructions used by the
  failing provider dispatch.
- Make the exact deterministic schema finding mandatory repair context.
- Add a greenfield no-doc-change regression that converges in one documentation
  repair cycle at most.

### Confirmed root cause and implementation

The deployed `echelon.tech-writer` prose already contained the canonical
`not_applicable_reason` field and both required version-2 examples. The retained
repair invocation did not read that prose; it consumed Ralph's context packs,
the existing reports, and the generic deterministic error "must explain why".
It therefore added a narrative section while retaining the invented `reason`
alias, and the gate rejected the same report again.

Ralph's deterministic documentation failures now name the exact required YAML
keys and values. In particular, no-impact repair requires a non-empty
`not_applicable_reason` and explicitly rejects narrative prose or `reason` as a
schema substitute. A focused inner-loop regression converges in one repair
cycle. Fresh run `build-20260811-163139-773440` reproduced the alias failure,
fed the schema-exact finding to COMMANDER, changed the field to
`not_applicable_reason`, and passed the immediate verify.

## EGR-157: Provider Usage Telemetry Reports Misleading Zeroes

**Priority:** P2
**Status:** open

All 18 Codex calls recorded `tokens: 0` despite approximately 91 minutes of
provider execution. A numeric zero implies measured zero consumption, while the
actual state is that token usage was unavailable from this provider path.

### Acceptance direction

- Distinguish measured zero from unavailable usage.
- Always retain provider, model/profile, effort, duration, exit status, and
  invocation count.
- Record token/input/output usage when the provider exposes it; otherwise emit
  an explicit availability/status field rather than fabricated zeroes.

## EGR-158: Repository Test Runner Can Select Unsupported Python

**Priority:** P2
**Status:** open

`bash tests/run-all.sh` selected a system Python that does not support
`dataclass(slots=True)`, causing two Integration/RE scripts to fail. Both scripts
passed unchanged when rerun with the repository's Python 3.11 virtual
environment: 31 checks in `test-discover-repos.sh` and 60 checks in
`test-run-analysis-polyrepo.sh`.

The same runner also labels an empty shim suite as `FAIL`, even though the shim
tests were intentionally removed during Spec-Kit cleanup.

### Acceptance direction

- Prefer the active project virtual environment or validate the selected
  interpreter against Echelon's minimum Python version before running tests.
- Print the resolved interpreter and version.
- Treat an intentionally absent test group as skipped or remove the obsolete
  group from the runner; do not report `FAIL` with zero failed tests.

## EGR-159: Greenfield Runs Retain Excess Generated State

**Priority:** P3
**Status:** open

The test retained multiple spec snapshots and delivery iteration worktrees, and
worktrees accumulated `.pytest_cache` and `__pycache__`. Retention was valuable
for this investigation, but normal runs need explicit cleanup and preservation
semantics.

### Acceptance direction

- Seed or adjudicate common generated Python cache paths deterministically.
- Define retention separately for successful, failed, blocked, and explicitly
  preserved runs.
- Keep enough evidence to reproduce failures without retaining every equivalent
  snapshot or disposable worktree indefinitely.

### Implemented cache-hygiene slice

Tracked Python caches no longer route to an LLM `leave` decision that blocks a
verified publish. Dirty adjudication deterministically removes tracked
`__pycache__`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, and `.pyc` entries,
adds their exact ignore paths, and commits the deletion. The real greenfield
`iter-0` branch removed the tracked bytecode and landed successfully. Run and
worktree retention policy remains open under EGR-159.

## EGR-160: Legacy Delivery Branches Cross Run Boundaries

**Priority:** P1
**Status:** fixed

Two verified reruns failed after verification because deterministic legacy
branch names referred to older build ancestry. Fresh `iter-0` first pushed a
branch based on stale mirror state; a later resume reused an old `iter-1` even
though the log named the current run's `iter-0` as its base.

Fresh iteration zero now fetches current target `main` into a ref that preserved
worktrees cannot own. Existing iteration branches are preserved only when their
intended current base is an ancestor; divergent branches are reset before
checkout. Landing independently fetches current target `main` and merges from a
detached landing worktree. A production call landed the verified greenfield
`iter-0` and synchronized the local target.

## EGR-161: Verified Publish Recovery Rebuilds

**Priority:** P2
**Status:** open

After `publish_failed`, `echelon delivery continue` recovered the preserved
verified commit but still dispatched another full build and fulfillment pass.
Recovery should retry adjudication, push, and merge directly when the preserved
commit still matches durable verification evidence. Re-entry to implementation
should require an explicit evidence mismatch.

## Recommended Order

1. EGR-153 product evidence boundary.
2. EGR-154 concrete fulfillment feedback and no-progress routing.
3. Repeat the same greenfield delivery through verification and landing.
4. Finish the remaining Spec-Kit removal audit.
5. EGR-156 documentation convergence.
6. EGR-155 CARTOGRAPHER proportionality benchmark.
7. EGR-157 through EGR-159 operational improvements.
