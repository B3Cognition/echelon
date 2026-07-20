# Incremental RE Quality and Published-Baseline Refinement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce avoidable RE semantic repair churn and make new runs improve the current published RE snapshot using the selected execution profile.

**Architecture:** Add a versioned semantic-completeness contract shared by prompts, deterministic domain checks, repair routing, telemetry, and analysis. Extend RE planning with an `improve` action that copies usable published source artifacts into isolated run staging while preserving the existing publication generation guard. Profile policy decides semantic audit and repair depth; all budgets and counters remain run-local.

**Tech Stack:** Python 3.11+, dataclasses, JSON/JSONL, Markdown contracts, Typer, pytest, existing RE planner/materializer/controller/publication and telemetry packages; no new runtime dependencies.

## Global Constraints

- `re/index.json` is the only published-baseline locator; never search old run directories.
- Canonical published `re/` bytes remain unchanged until explicit publication.
- Every new run receives fresh token/time budgets, repair counters, intervals, and telemetry.
- `--no-reuse` disables baseline artifact use but preserves the real generation guard.
- Changed, absent, corrupt, or incompatible sources follow the existing refresh path.
- Deterministic checks may verify structure, evidence, and extracted symbol coverage; they must not claim semantic truth.
- The validator's owned-source evidence standard remains unchanged.
- `fast`: deterministic checks for every domain, no semantic dispatches, zero semantic repair rounds.
- `balanced`: semantic audit for every domain and at most one semantic repair/revalidation round per failed domain.
- `high`: semantic audit for every domain and up to five bounded semantic repair rounds.
- Raw prompts, model responses, and source content remain excluded from telemetry.
- The fixed pre-change benchmark is 17 audited domains, 14 first-pass repairs, and 26 findings.

---

### Task 1: Versioned semantic completeness contract and finding categories

**Files:**
- Create: `src/harness/re_semantic_contract.py`
- Modify: `src/harness/re_quality_gate.py`
- Test: `tests/unit/test_re_semantic_contract.py`
- Test: `tests/unit/test_re_quality_gate.py`

**Interfaces:**
- Produces: `SEMANTIC_COMPLETENESS_VERSION = 1`.
- Produces: `SemanticCategory` literal values `public-surface`, `configuration`, `error-recovery`, `boundary`, `operator-observable`, `test-demonstrated`, and `evidence-scope`.
- Produces: `classify_semantic_finding(text: str) -> str` and `stable_finding_id(category: str, text: str, evidence: tuple[str, ...]) -> str`.
- Extends: `ReSpecQualityFailure.semantic_finding_records` with normalized IDs/categories while preserving `semantic_findings` compatibility.

- [ ] **Step 1: Write failing category and stable-ID tests**

```python
def test_classifies_observed_md_distribution_findings():
    assert classify_semantic_finding("The read error propagates uncaught") == "error-recovery"
    assert classify_semantic_finding("The public remove operation is unspecified") == "public-surface"
    assert classify_semantic_finding("An invalid backupRetention value is omitted") == "configuration"


def test_stable_finding_id_ignores_whitespace_but_not_evidence():
    first = stable_finding_id("error-recovery", "Read  failure", ("`src/a.ts:3`",))
    second = stable_finding_id("error-recovery", "Read failure", ("`src/a.ts:3`",))
    changed = stable_finding_id("error-recovery", "Read failure", ("`src/a.ts:4`",))
    assert first == second
    assert first != changed
```

- [ ] **Step 2: Run the new tests and verify imports fail**

Run: `.venv/bin/pytest -q tests/unit/test_re_semantic_contract.py`

Expected: FAIL because `harness.re_semantic_contract` does not exist.

- [ ] **Step 3: Implement deterministic normalization and categorization**

```python
SEMANTIC_COMPLETENESS_VERSION = 1

CATEGORY_PATTERNS = (
    ("error-recovery", re.compile(r"\b(error|failure|uncaught|unhandled|recover|retry)\b", re.I)),
    ("configuration", re.compile(r"\b(config|option|constraint|invalid value|frontmatter)\b", re.I)),
    ("public-surface", re.compile(r"\b(public|operation|method|function|command|API)\b", re.I)),
    ("operator-observable", re.compile(r"\b(warning|exit|diagnostic|output|log)\b", re.I)),
    ("test-demonstrated", re.compile(r"\b(test|fixture|assert)\b", re.I)),
    ("boundary", re.compile(r"\b(edge|boundary|empty|partial|limit)\b", re.I)),
)
```

Normalize Unicode whitespace and case only for ID generation. Hash category,
normalized text, and sorted normalized evidence with SHA-256; expose the first
16 hexadecimal characters prefixed by `ref-`.

- [ ] **Step 4: Convert validated REPAIR findings into structured records**

In `validate_semantic_quality_review`, pair each finding with its corresponding
validated evidence entry, assign a category and stable ID, and retain the
original finding tuple for current publication/report consumers.

- [ ] **Step 5: Run focused tests and commit**

Run: `.venv/bin/pytest -q tests/unit/test_re_semantic_contract.py tests/unit/test_re_quality_gate.py`

Expected: all tests pass.

Commit:

```bash
git add src/harness/re_semantic_contract.py src/harness/re_quality_gate.py tests/unit/test_re_semantic_contract.py tests/unit/test_re_quality_gate.py
git commit -m "feat: define RE semantic completeness contract"
```

---

### Task 2: Align specifier and validator prompts on one coverage protocol

**Files:**
- Modify: `extension/agents/re/specifier.md`
- Modify: `extension/agents/re/validator.md`
- Modify: `extension/workflow/phases/re-extract-2-specify.md`
- Modify: `extension/workflow/phases/re-extract-5-validate.md`
- Test: `tests/unit/test_re_prompt_output_contracts.py`

**Interfaces:**
- Consumes: semantic completeness contract version 1.
- Produces: required `## Behavior Coverage` table with columns `Category`, `Status`, `Observed Scope`, and `Source Evidence`.
- Produces: requirement-level `Evidence Scope: exhaustive` marker for universal claims.

- [ ] **Step 1: Write failing prompt-contract tests**

```python
def test_re_specifier_and_validator_share_behavior_coverage_contract():
    specifier = _agent("specifier")
    validator = _agent("validator")
    for text in (specifier, validator):
        assert "Behavior Coverage" in text
        assert "public operations" in text
        assert "configuration keys" in text
        assert "errors and recovery" in text
        assert "Evidence Scope: exhaustive" in text


def test_specifier_forbids_generalizing_one_case_to_a_universal_claim():
    specifier = _agent("specifier")
    assert "Never generalize one observed or tested case" in specifier
```

- [ ] **Step 2: Run prompt tests and verify missing-contract failures**

Run: `.venv/bin/pytest -q tests/unit/test_re_prompt_output_contracts.py`

Expected: FAIL on missing Behavior Coverage and evidence-scope language.

- [ ] **Step 3: Add the exact shared taxonomy to both agents**

Require all seven categories from Task 1. Tell the specifier to record
`not-observed` rather than inventing a requirement. Tell the validator to treat
the table as an audit index, not proof, and to cite source code/tests for every
REPAIR finding as before.

- [ ] **Step 4: Add bounded-language guidance to specification phase**

Add this enforceable rule:

```text
Use all/always/every/never only when the requirement includes
`Evidence Scope: exhaustive` and cites every relevant branch or a test that
establishes the invariant. Otherwise state only the observed scope.
Never generalize one observed or tested case into a system-wide guarantee.
```

- [ ] **Step 5: Run tests and commit**

Run: `.venv/bin/pytest -q tests/unit/test_re_prompt_output_contracts.py`

Expected: all tests pass.

Commit:

```bash
git add extension/agents/re/specifier.md extension/agents/re/validator.md extension/workflow/phases/re-extract-2-specify.md extension/workflow/phases/re-extract-5-validate.md tests/unit/test_re_prompt_output_contracts.py
git commit -m "feat: align RE specification and validation taxonomy"
```

---

### Task 3: Extend `check-domain` with deterministic semantic preflight

**Files:**
- Create: `src/harness/re_semantic_preflight.py`
- Modify: `src/harness/re_quality_gate.py`
- Modify: `src/echelon/cli.py`
- Test: `tests/unit/test_re_semantic_preflight.py`
- Test: `tests/unit/test_cli_re_check_domain.py`

**Interfaces:**
- Produces: `SemanticPreflightFinding(code: str, message: str, references: tuple[str, ...])`.
- Produces: `check_semantic_preflight(spec_path: Path, analysis_path: Path | None) -> tuple[SemanticPreflightFinding, ...]`.
- Adds failure codes `behavior_coverage_missing`, `behavior_coverage_category_missing`, `behavior_coverage_evidence_invalid`, `unscoped_universal_claim`, and `public_surface_coverage_missing`.

- [ ] **Step 1: Write failing tests for coverage table and universal claims**

```python
def test_preflight_rejects_unscoped_universal_requirement(tmp_path):
    spec = _write_spec(tmp_path, "### NFR-001: Safety\nEvery read failure is recovered. `src/io.ts:4`\n")
    findings = check_semantic_preflight(spec, None)
    assert [item.code for item in findings] == ["behavior_coverage_missing", "unscoped_universal_claim"]


def test_preflight_accepts_exhaustively_scoped_claim(tmp_path):
    spec = _write_complete_coverage_spec(
        tmp_path,
        requirement="Every read failure is recovered. Evidence Scope: exhaustive. `src/io.ts:4-12`",
    )
    assert check_semantic_preflight(spec, None) == ()
```

- [ ] **Step 2: Write a failing public-symbol coverage test**

Use a fixture analysis payload with exported functions `load`, `validate`, and
`remove`; mention `load` and `validate` in the spec and assert a
`public_surface_coverage_missing` finding names `remove`. Add a second test where
the analysis has no supported symbol inventory and assert no failure is emitted.

- [ ] **Step 3: Run tests and verify the preflight module is missing**

Run: `.venv/bin/pytest -q tests/unit/test_re_semantic_preflight.py tests/unit/test_cli_re_check_domain.py`

Expected: FAIL because the new checks do not exist.

- [ ] **Step 4: Implement Markdown parsing and evidence validation**

Parse only headings, table rows, requirement blocks, and existing backticked
source references. Reuse `_validated_source_evidence` through a public helper in
`re_quality_gate.py`; do not duplicate path-boundary logic. Universal-term
matching must ignore fenced code and quoted source snippets.

- [ ] **Step 5: Implement conservative public-symbol extraction adapters**

Support only symbol lists already present in `analysis.json`/CodeGraph summaries
and explicitly recognized by schema. Return `availability="unavailable"` for an
unknown shape. Never infer public visibility from a function name alone.

- [ ] **Step 6: Merge preflight failures into domain quality output**

`validate_staged_re_domain_quality` must include preflight codes in its existing
JSON report, causing `echelon re check-domain` to exit 1. Preserve current fields
for older consumers.

- [ ] **Step 7: Run tests and commit**

Run: `.venv/bin/pytest -q tests/unit/test_re_semantic_preflight.py tests/unit/test_re_quality_gate.py tests/unit/test_cli_re_check_domain.py`

Expected: all tests pass.

Commit:

```bash
git add src/harness/re_semantic_preflight.py src/harness/re_quality_gate.py src/echelon/cli.py tests/unit/test_re_semantic_preflight.py tests/unit/test_re_quality_gate.py tests/unit/test_cli_re_check_domain.py
git commit -m "feat: add deterministic RE semantic preflight"
```

---

### Task 4: Route structured, narrow semantic repair packets

**Files:**
- Create: `src/harness/re_repair_packet.py`
- Modify: `src/harness/re_controller.py`
- Modify: `src/harness/re_quality_gate.py`
- Modify: `extension/agents/re/specifier.md`
- Test: `tests/unit/test_re_repair_packet.py`
- Test: `tests/unit/test_re_controller.py`

**Interfaces:**
- Produces: `ReRepairFinding` and `ReRepairPacket` dataclasses with `to_json_dict`/`from_json_dict`.
- Produces: `build_repair_packet(failure: ReSpecQualityFailure, spec_fingerprint: str, attempt: int) -> ReRepairPacket`.
- Persists: `re_active_repair_packet` and per-domain `re_repeated_finding_ids` in inner state.

- [ ] **Step 1: Write failing repair-packet round-trip and stability tests**

```python
def test_repair_packet_round_trip_preserves_exact_scope():
    packet = ReRepairPacket(
        source_id="api",
        domain_id="001-api",
        spec_fingerprint="abc",
        attempt=1,
        findings=(ReRepairFinding("ref-123", "error-recovery", "Missing retry exhaustion", ("`src/a.ts:9`",)),),
    )
    assert ReRepairPacket.from_json_dict(packet.to_json_dict()) == packet
```

- [ ] **Step 2: Write failing controller prompt/routing tests**

Assert a semantic REPAIR for `api/001-api` stores one packet, includes its exact
finding and evidence in the next specifier prompt, preserves sibling spec bytes,
and invalidates only `api/001-api`'s audit.

- [ ] **Step 3: Run focused tests and verify failure**

Run: `.venv/bin/pytest -q tests/unit/test_re_repair_packet.py tests/unit/test_re_controller.py -k 'repair_packet or semantic_repair'`

Expected: FAIL because repair packets are not persisted or rendered.

- [ ] **Step 4: Implement packet serialization and controller persistence**

Create packets from structured findings at semantic repair scheduling time.
Snapshot the target spec and non-target output exactly as existing repair guards
do. Increment only the target domain's attempt counter.

- [ ] **Step 5: Render exact packet context for the specifier**

Add a `Controller-Owned Semantic Repair Packet` section containing source,
domain, attempt, spec fingerprint, and each finding's ID/category/text/evidence.
Instruct the agent to modify only the target spec and preserve unrelated
requirements. The specifier still runs `check-domain` before returning.

- [ ] **Step 6: Detect repeated finding IDs after revalidation**

Compare new IDs with the previous packet. Store repeated IDs and increment a
per-domain repeated-finding counter. Repetition consumes the same repair round;
it does not create an extra hidden retry.

- [ ] **Step 7: Run tests and commit**

Run: `.venv/bin/pytest -q tests/unit/test_re_repair_packet.py tests/unit/test_re_controller.py tests/unit/test_re_quality_gate.py`

Expected: all tests pass.

Commit:

```bash
git add src/harness/re_repair_packet.py src/harness/re_controller.py src/harness/re_quality_gate.py extension/agents/re/specifier.md tests/unit/test_re_repair_packet.py tests/unit/test_re_controller.py
git commit -m "feat: route targeted RE semantic repairs"
```

---

### Task 5: Make semantic validation depth profile-aware

**Files:**
- Modify: `src/harness/re_profiles.py`
- Modify: `src/harness/re_controller.py`
- Modify: `src/kernel/re_state.py`
- Test: `tests/unit/test_re_profiles.py`
- Test: `tests/unit/test_re_controller.py`
- Test: `tests/kernel/test_re_state.py`

**Interfaces:**
- Extends: `ReExecutionProfile.semantic_audit_mode: Literal["none", "all"]`.
- Extends: `ReExecutionProfile.max_semantic_repair_rounds: int`.
- Persists: exact resolved policy inside `re_execution_profile` for continuation.

- [ ] **Step 1: Write failing exact-policy tests**

```python
@pytest.mark.parametrize(("name", "mode", "rounds"), [
    ("fast", "none", 0),
    ("balanced", "all", 1),
    ("high", "all", 5),
])
def test_profiles_define_semantic_policy(name, mode, rounds):
    profile = builtin_re_profile(name)
    assert profile.semantic_audit_mode == mode
    assert profile.max_semantic_repair_rounds == rounds
```

- [ ] **Step 2: Write controller dispatch-count tests**

Use three valid staged domains. Assert `fast` invokes no validator, `balanced`
invokes each once and a failed domain at most once more after repair, and `high`
continues only the failed domain until pass or five repairs. Assert deterministic
domain checks run for all profiles.

- [ ] **Step 3: Run tests and verify current uniform routing fails**

Run: `.venv/bin/pytest -q tests/unit/test_re_profiles.py tests/unit/test_re_controller.py -k 'semantic_policy or profile_validation'`

Expected: FAIL because all profiles currently share semantic routing.

- [ ] **Step 4: Extend frozen profiles and legacy migration**

Legacy runs retain their existing `max_validate_iterations` behavior. New runs
store exact semantic mode/rounds so `continue` never changes policy because the
workspace default changed.

- [ ] **Step 5: Gate controller phase transitions by resolved policy**

After deterministic quality passes, `fast` writes semantic coverage
`not_evaluated` and advances. `balanced` and `high` use granular audits and the
profile-specific repair counter. Remaining findings after exhaustion become
typed blocking quality debt.

- [ ] **Step 6: Run tests and commit**

Run: `.venv/bin/pytest -q tests/unit/test_re_profiles.py tests/unit/test_re_controller.py tests/kernel/test_re_state.py tests/unit/test_re_lifecycle.py`

Expected: all tests pass.

Commit:

```bash
git add src/harness/re_profiles.py src/harness/re_controller.py src/kernel/re_state.py tests/unit/test_re_profiles.py tests/unit/test_re_controller.py tests/kernel/test_re_state.py
git commit -m "feat: make RE validation profile-aware"
```

---

### Task 6: Add published-source `improve` planning and `--no-reuse`

**Files:**
- Modify: `src/harness/re_planner.py`
- Modify: `src/harness/re_lifecycle.py`
- Modify: `src/echelon/cli_app.py`
- Modify: `src/echelon/cli.py`
- Test: `tests/unit/test_re_planner.py`
- Test: `tests/unit/test_re_lifecycle.py`
- Test: `tests/unit/test_cli_re_lifecycle.py`

**Interfaces:**
- Extends: `RePlanAction` with `improve`.
- Extends: `build_re_execution_plan(*, project_root: Path, manifest: WorkspaceManifest, target_source: str, requested_policy: str, profile: ReFingerprintProfile, published_index: PublishedReIndex | None = None, cache_root: Path | None = None, reuse_published: bool = True) -> ReExecutionPlan`.
- Extends: `ReLifecycleController.run(*, policy: str = "", re_max_inner: int | None = None, reset: bool = False, profile_name: str | None = None, hard_token_limit: int | None = None, hard_active_minutes: int | None = None, reuse_published: bool = True) -> ReLifecycleResult`.
- Adds CLI flag: `echelon re run --no-reuse`.

- [ ] **Step 1: Write failing planner tests for all baseline decisions**

```python
def test_unchanged_usable_published_source_is_improved():
    plan = build_plan_with_published_source(current=True, reuse_published=True)
    assert plan.sources[0].action == "improve"
    assert plan.analysis_required is False
    assert plan.workspace_synthesis_required is True


def test_no_reuse_forces_refresh_but_retains_generation_guard():
    result = start_run_with_published_source(reuse_published=False)
    assert result.plan.sources[0].action == "refresh"
    assert result.outer_state["expected_generation"] == 7
```

Also cover no published index, changed fingerprint, corrupt manifest, and
`cached-only`; retain existing semantics for commands that are not explicit
improvement runs.

- [ ] **Step 2: Run planner/lifecycle tests and verify `improve` is rejected**

Run: `.venv/bin/pytest -q tests/unit/test_re_planner.py tests/unit/test_re_lifecycle.py tests/unit/test_cli_re_lifecycle.py`

Expected: FAIL because `improve` and `--no-reuse` do not exist.

- [ ] **Step 3: Extend plan serialization and derived flags**

An `improve` source is selected, needs staged synthesis/publication, does not
require static analysis, and participates in domain quality/validation. Update
JSON round-trip validation and classification derivation without changing plan
schema version unless old readers cannot safely reject the new action.

- [ ] **Step 4: Separate baseline use from publication concurrency**

Always load the real published index to set `expected_generation`. Pass it to
planning/materialization only when `reuse_published` is true. Store
`reuse_published`, `baseline_generation`, and baseline index digest in outer and
inner state.

- [ ] **Step 5: Wire `--no-reuse` through Typer and legacy CLI parsing**

The default remains reuse enabled. `continue` and `resume` expose no reuse flag
because the baseline decision is frozen at run creation.

- [ ] **Step 6: Run tests and commit**

Run: `.venv/bin/pytest -q tests/unit/test_re_planner.py tests/unit/test_re_lifecycle.py tests/unit/test_cli_re_lifecycle.py`

Expected: all tests pass.

Commit:

```bash
git add src/harness/re_planner.py src/harness/re_lifecycle.py src/echelon/cli_app.py src/echelon/cli.py tests/unit/test_re_planner.py tests/unit/test_re_lifecycle.py tests/unit/test_cli_re_lifecycle.py
git commit -m "feat: plan RE improvements from published artifacts"
```

---

### Task 7: Seed immutable published baselines into editable run staging

**Files:**
- Modify: `src/harness/re_materializer.py`
- Modify: `src/harness/re_controller.py`
- Modify: `src/harness/re_publication.py`
- Test: `tests/unit/test_re_materializer.py`
- Test: `tests/unit/test_re_controller.py`
- Test: `tests/unit/test_re_publication.py`

**Interfaces:**
- Produces: `materialize_published_source_baseline(project_root: Path, run_re_dir: Path, source: RePlanSource, published_index: PublishedReIndex) -> dict[str, object]`.
- Produces run-local `re-baseline.json` with generation, index digest, source artifact hashes, and actions.

- [ ] **Step 1: Write failing byte-preservation and staging-copy tests**

Create a published source with manifest, overview, two specs, and checklist. Start
an `improve` run and assert all durable files are copied beneath
`runs/<id>/re/sources/<source-id>/`, canonical hashes remain unchanged, and
run-local writes do not affect canonical files.

- [ ] **Step 2: Write failing controller bootstrap tests**

Assert improved domains begin at deterministic quality/semantic validation,
not static analysis or initial specification. Assert a changed source still
starts at analysis and receives canonical paths only as comparison context.

- [ ] **Step 3: Run tests and verify current materializer does not stage reuse**

Run: `.venv/bin/pytest -q tests/unit/test_re_materializer.py tests/unit/test_re_controller.py -k 'baseline or improve'`

Expected: FAIL because current sources use canonical paths directly and no
editable staged baseline exists.

- [ ] **Step 4: Implement allowlisted durable copy and integrity manifest**

Copy only files declared by the published source manifest. Reject symlinks,
paths outside canonical `re/`, missing required specs, and hash changes during
copy. Use temporary directories plus atomic rename into the run source path.

- [ ] **Step 5: Initialize controller targets from staged baseline**

Generate domain manifests from staged/published metadata, mark initial
specification complete for `improve` domains, run the new deterministic
preflight, and enter profile-aware semantic routing. Never import prior audit
records or repair counters.

- [ ] **Step 6: Preserve atomic publication and provenance validation**

Publication must verify baseline generation/digest, current staged artifacts,
and the existing source fingerprints. It may replace canonical artifacts only
after all selected-profile gates pass.

- [ ] **Step 7: Run tests and commit**

Run: `.venv/bin/pytest -q tests/unit/test_re_materializer.py tests/unit/test_re_controller.py tests/unit/test_re_publication.py`

Expected: all tests pass.

Commit:

```bash
git add src/harness/re_materializer.py src/harness/re_controller.py src/harness/re_publication.py tests/unit/test_re_materializer.py tests/unit/test_re_controller.py tests/unit/test_re_publication.py
git commit -m "feat: stage published RE baselines for refinement"
```

---

### Task 8: Publish profile-relative quality metadata

**Files:**
- Modify: `src/harness/re_registry.py`
- Modify: `src/harness/re_publication.py`
- Modify: `src/harness/re_quality_contract.py`
- Test: `tests/unit/test_re_registry.py`
- Test: `tests/unit/test_re_publication.py`

**Interfaces:**
- Extends published index/source manifests with `quality_profile`, `semantic_coverage`, `semantic_audited_domains`, `unresolved_finding_count`, and `semantic_contract_version`.
- Valid values for semantic coverage: `not_evaluated`, `complete`, and `debt`.

- [ ] **Step 1: Write failing publication metadata tests**

Assert fast publication records `not_evaluated` and zero audited domains without
claiming semantic PASS. Assert balanced/high records audited counts and blocks
complete publication when unresolved blocking findings remain.

- [ ] **Step 2: Write backward-compatibility tests**

Load a schema-1 published index without quality metadata and expose its semantic
coverage as `unknown`. Such an index remains usable as a baseline if its current
integrity rules pass.

- [ ] **Step 3: Run tests and verify metadata is absent**

Run: `.venv/bin/pytest -q tests/unit/test_re_registry.py tests/unit/test_re_publication.py`

Expected: FAIL on missing quality fields.

- [ ] **Step 4: Implement profile-relative metadata and validation**

Derive values from frozen execution profile, granular audits, deterministic
gate output, and quality debt. Agents cannot write these fields. Reject
internally contradictory combinations such as `complete` with unresolved
blocking findings.

- [ ] **Step 5: Run tests and commit**

Run: `.venv/bin/pytest -q tests/unit/test_re_registry.py tests/unit/test_re_publication.py tests/unit/test_re_lifecycle.py`

Expected: all tests pass.

Commit:

```bash
git add src/harness/re_registry.py src/harness/re_publication.py src/harness/re_quality_contract.py tests/unit/test_re_registry.py tests/unit/test_re_publication.py
git commit -m "feat: publish RE quality profile metadata"
```

---

### Task 9: Extend telemetry, analyzer, and wiki convergence views

**Files:**
- Modify: `src/harness/re_controller.py`
- Modify: `src/echelon/telemetry/analyzer.py`
- Modify: `src/echelon/telemetry/re_adapter.py`
- Modify: `src/echelon/telemetry/render.py`
- Modify: `src/echelon/wiki/operations.py`
- Test: `tests/unit/test_re_controller.py`
- Test: `tests/unit/test_run_analyzer.py`
- Test: `tests/unit/test_wiki_operations.py`

**Interfaces:**
- Adds span attributes `echelon.attempt.kind`, `echelon.attempt.number`, `echelon.finding.id`, `echelon.finding.category`, `echelon.baseline.generation`, and `echelon.baseline.action`.
- Extends `RunAnalysis` with first-pass repair rate, validator dispatches per accepted domain, repeated finding IDs, tokens per accepted domain, improved/refreshed counts, semantic coverage, and unresolved blocking findings.

- [ ] **Step 1: Write failing span-attribute tests**

Drive one improved-domain audit and repair. Assert initial audit and repair spans
carry correct attempt/baseline attributes and model/provider fields, without raw
finding text or source content.

- [ ] **Step 2: Write failing analyzer metric tests**

Use a compact ledger with three domains, one initial repair, one successful
revalidation, and known tokens. Assert repair rate `1/3`, validator dispatches
per accepted domain `4/3`, no repeated finding IDs, and exact tokens/domain.

- [ ] **Step 3: Run tests and verify new metrics are missing**

Run: `.venv/bin/pytest -q tests/unit/test_re_controller.py tests/unit/test_run_analyzer.py tests/unit/test_wiki_operations.py -k 'convergence or baseline or finding'`

Expected: FAIL on missing attributes and analysis fields.

- [ ] **Step 4: Instrument controller attempts and aggregate metrics**

Use stable IDs/categories only; keep full finding text in controller-owned state
and quality artifacts. Derive active duration from spans when legacy state lacks
an active-duration counter, marking provenance as span-derived.

- [ ] **Step 5: Render text, JSON, and wiki views**

Show baseline generation/action, profile quality coverage, repair-rate funnel,
tokens per accepted domain, repeated findings, and blocking debt. Preserve JSON
schema compatibility by increasing the analysis schema version and accepting
schema 1 in readers.

- [ ] **Step 6: Run tests and commit**

Run: `.venv/bin/pytest -q tests/unit/test_re_controller.py tests/unit/test_run_analyzer.py tests/unit/test_wiki_operations.py tests/unit/test_execution_telemetry.py`

Expected: all tests pass.

Commit:

```bash
git add src/harness/re_controller.py src/echelon/telemetry/analyzer.py src/echelon/telemetry/re_adapter.py src/echelon/telemetry/render.py src/echelon/wiki/operations.py tests/unit/test_re_controller.py tests/unit/test_run_analyzer.py tests/unit/test_wiki_operations.py
git commit -m "feat: report RE refinement convergence metrics"
```

---

### Task 10: Freeze the benchmark, document behavior, and verify end to end

**Files:**
- Create: `tests/fixtures/re-analysis/md-distribution-semantic-baseline/README.md`
- Create: `tests/fixtures/re-analysis/md-distribution-semantic-baseline/summary.json`
- Create: `tests/integration/test_re_incremental_refinement.py`
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `tests/README.md`

**Interfaces:**
- Produces a content-free benchmark fixture containing aggregate counts and categorized finding IDs only.
- Documents default reuse, `--no-reuse`, profile-relative validation, and analyzer metrics.

- [ ] **Step 1: Add the minimized benchmark fixture and regression test**

Store exactly 17 audited domains, 14 first-pass repairs, 26 finding records, and
the observed per-source/category counts. Exclude source code, prompts, response
text, absolute user paths, and provider credentials. Assert the analyzer reads
the fixture as the pre-change baseline.

- [ ] **Step 2: Add an end-to-end published-baseline refinement test**

The test must:

1. create and publish a valid fast snapshot;
2. start balanced with unchanged source fingerprints;
3. assert the plan uses `improve` and copies canonical specs to staging;
4. simulate one semantic repair and successful revalidation;
5. assert fresh counters and telemetry;
6. assert canonical bytes remain unchanged before publication;
7. publish and assert the generation increments atomically;
8. start high with `--no-reuse` and assert a clean refresh plan.

- [ ] **Step 3: Run the integration test and correct only implementation defects**

Run: `.venv/bin/pytest -q tests/integration/test_re_incremental_refinement.py`

Expected: PASS.

- [ ] **Step 4: Document commands and honest quality semantics**

Document:

```bash
echelon re run --profile fast
echelon re run --profile balanced
echelon re run --profile high
echelon re run --profile balanced --no-reuse
echelon re analyze runs/<run-id>
```

Explain that published artifacts are reused automatically, `fast` has no
semantic PASS claim, and only explicit publication replaces canonical `re/`.

- [ ] **Step 5: Run focused and full verification**

Run:

```bash
.venv/bin/pytest -q tests/unit/test_re_semantic_contract.py tests/unit/test_re_semantic_preflight.py tests/unit/test_re_quality_gate.py tests/unit/test_re_profiles.py tests/unit/test_re_planner.py tests/unit/test_re_materializer.py tests/unit/test_re_controller.py tests/unit/test_re_lifecycle.py tests/unit/test_re_publication.py tests/unit/test_run_analyzer.py tests/unit/test_wiki_operations.py tests/integration/test_re_incremental_refinement.py
.venv/bin/pytest -q
bash scripts/bash/dry-run.sh
git diff --check
```

Expected: all focused tests and dry-run checks pass. The full suite must show no
new failures relative to its recorded pre-change baseline; do not hide or relabel
existing failures.

- [ ] **Step 6: Install and smoke-test the CLI**

Run:

```bash
bash scripts/install.sh
/Users/michalbachorik/.echelon/venv/bin/echelon re run --help
/Users/michalbachorik/.echelon/venv/bin/echelon re analyze --help
```

Expected: `--no-reuse` appears on `re run`; analyzer remains callable and hidden
from ordinary `re --help`.

- [ ] **Step 7: Commit documentation and benchmark**

```bash
git add tests/fixtures/re-analysis/md-distribution-semantic-baseline tests/integration/test_re_incremental_refinement.py README.md CHANGELOG.md tests/README.md
git commit -m "docs: document incremental RE refinement"
```

- [ ] **Step 8: Run the live A/B benchmark after operator approval**

Run a new `md_distribution` balanced refinement from the published snapshot and
record first-pass repair rate, validator dispatches/domain, repeated findings,
tokens/accepted-domain, elapsed time, and blocking debt. Success targets are:

- first-pass repair rate below 30%;
- mean validator dispatches per domain below 1.4;
- zero repeated findings after repair;
- zero unresolved blocking findings;
- total tokens and elapsed time within the frozen balanced ceilings.

Do not claim these targets before the live run completes.
