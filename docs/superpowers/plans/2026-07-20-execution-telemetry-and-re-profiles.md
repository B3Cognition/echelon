# Execution Telemetry and Bounded RE Profiles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add shared OpenTelemetry-aligned local execution telemetry, bounded fast/balanced/high RE profiles, a hidden RE analyzer with a reproducible legacy baseline, and optional run-analysis pages in the human wiki.

**Architecture:** A new `echelon.telemetry` package owns profile-independent span persistence and aggregation. RE lifecycle/controller code freezes a resolved profile into state, records active execution intervals and provider dispatches, and enforces budgets between dispatches. A workflow adapter analyzes RE state plus shared spans, while the wiki consumes the analyzer API rather than reading telemetry directly.

**Tech Stack:** Python 3.11+, dataclasses, JSON/JSONL, Typer, pytest, existing Echelon state and wiki services; no new runtime dependency.

## Global Constraints

- `balanced` is the default for new RE runs: 60-minute target, 180-minute hard active ceiling, 5,000,000-token hard ceiling, 3 domain repairs, 2 source cycles, and 2 source reanalyses.
- `fast`: 30-minute target, 60-minute hard active ceiling, 1,000,000 tokens, and 1/1/1 convergence limits.
- `high`: 180-minute target, 720-minute hard active ceiling, 15,000,000 tokens, and 5/5/5 convergence limits.
- Provider-reported input, output, reasoning, and cache tokens count toward the hard token ceiling; absent usage remains unknown and is never estimated.
- Budget checks happen only between provider dispatches; an in-flight dispatch finishes and checkpoints.
- Complete publication requires zero unresolved blocking findings; non-blocking findings may become explicit quality debt.
- Telemetry excludes raw prompts, responses, source, secrets, and arbitrary exception bodies.
- Existing active runs migrate to a frozen `legacy` profile without inventing missing time or token limits.
- Normal wiki builds exclude local runs; runtime pages require config or `--include-runs`.

---

### Task 1: Shared telemetry records and provider usage normalization

**Files:**
- Create: `src/echelon/telemetry/__init__.py`
- Create: `src/echelon/telemetry/model.py`
- Create: `src/echelon/telemetry/store.py`
- Modify: `src/harness/squad_provider.py`
- Test: `tests/unit/test_execution_telemetry.py`
- Test: `tests/unit/test_squad_provider.py`

**Interfaces:**
- Produces: `TokenUsage`, `ExecutionSpan`, `TelemetryManifest`, `TelemetryStore`, and `token_usage_from_provider_result(result) -> TokenUsage`.
- Produces: `SquadAgentResult.token_usage`, `token_usage_details`, `provider_name`, and `model_name` for downstream RE instrumentation.

- [ ] **Step 1: Write failing tests for normalized known and unknown token usage**

```python
def test_token_usage_preserves_known_components():
    usage = TokenUsage.from_mapping({"input_tokens": 10, "output_tokens": 4, "cache_read_input_tokens": 3})
    assert usage.total == 17
    assert usage.known is True

def test_missing_provider_usage_remains_unknown():
    assert TokenUsage.unknown().known is False
    assert TokenUsage.unknown().total is None
```

- [ ] **Step 2: Run the focused tests and confirm missing imports/fields fail**

Run: `.venv/bin/pytest tests/unit/test_execution_telemetry.py tests/unit/test_squad_provider.py -q`

Expected: failure because `echelon.telemetry` and new `SquadAgentResult` fields do not exist.

- [ ] **Step 3: Implement immutable telemetry models and provider normalization**

```python
@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_output_tokens: int | None = None
    cache_read_input_tokens: int | None = None
    cache_creation_input_tokens: int | None = None

    @property
    def known(self) -> bool: ...

    @property
    def total(self) -> int | None: ...
```

`ExecutionSpan` must serialize standard `trace_id`, `span_id`, `parent_span_id`, `start_time`, `end_time`, `duration_ms`, `status`, `attributes`, and normalized token fields. `SquadCliProvider.exec_agent` must copy token totals/details from `CliRunResult`, including any repair-result usage, into `SquadAgentResult`.

- [ ] **Step 4: Implement append-only manifest and JSONL persistence**

```python
store = TelemetryStore(run_dir, workflow="re", run_id=run_dir.name, profile=resolved_profile)
store.ensure_manifest()
store.append_span(span)
spans, diagnostics = store.read_spans()
```

Use atomic manifest replacement and one compact JSON object per line. Ignore only a truncated final line; report malformed earlier lines through diagnostics. Never serialize prompt or response content.

- [ ] **Step 5: Run tests and commit the shared substrate**

Run: `.venv/bin/pytest tests/unit/test_execution_telemetry.py tests/unit/test_squad_provider.py -q`

Expected: all focused tests pass.

Commit: `git commit -am "feat: add shared execution telemetry substrate"` after adding the new files.

---

### Task 2: RE profile resolution and frozen lifecycle state

**Files:**
- Create: `src/harness/re_profiles.py`
- Modify: `src/kernel/re_state.py`
- Modify: `src/harness/re_lifecycle.py`
- Modify: `src/echelon/cli_app.py`
- Modify: `src/echelon/cli.py`
- Modify: `extension/config-template.yml`
- Modify: `extension/extension.yml`
- Test: `tests/unit/test_re_profiles.py`
- Test: `tests/kernel/test_re_state.py`
- Test: `tests/unit/test_re_lifecycle.py`
- Test: `tests/unit/test_cli_re_lifecycle.py`

**Interfaces:**
- Produces: `ReExecutionProfile`, `resolve_re_execution_profile(project_root, name, overrides)`, and `migrate_legacy_re_profile(state)`.
- Consumes: convergence values from profile resolution in `init_re_state`.

- [ ] **Step 1: Write failing exact-profile and CLI routing tests**

```python
@pytest.mark.parametrize(("name", "tokens", "minutes", "repairs"), [
    ("fast", 1_000_000, 60, 1),
    ("balanced", 5_000_000, 180, 3),
    ("high", 15_000_000, 720, 5),
])
def test_builtin_profiles(name, tokens, minutes, repairs):
    profile = builtin_re_profile(name)
    assert profile.hard_token_limit == tokens
    assert profile.hard_active_minutes == minutes
    assert profile.max_domain_repairs == repairs
```

Add a Typer test proving `re run --profile fast` reaches the legacy handler and that `re continue` exposes no profile reset option.

- [ ] **Step 2: Run the focused profile/lifecycle tests and confirm failure**

Run: `.venv/bin/pytest tests/unit/test_re_profiles.py tests/kernel/test_re_state.py tests/unit/test_re_lifecycle.py tests/unit/test_cli_re_lifecycle.py -q`

Expected: failures for missing profile APIs/options/state.

- [ ] **Step 3: Implement exact built-in profiles and override validation**

```python
BUILTIN_RE_PROFILES = {
    "fast": ReExecutionProfile("fast", 30, 60, 1_000_000, 1, 1, 1),
    "balanced": ReExecutionProfile("balanced", 60, 180, 5_000_000, 3, 2, 2),
    "high": ReExecutionProfile("high", 180, 720, 15_000_000, 5, 5, 5),
}
```

Reject non-positive limits and unknown names before creating a run. Resolve configuration once, default to `balanced`, and persist the full mapping in outer and inner state.

- [ ] **Step 4: Wire CLI and configuration defaults**

Add `--profile fast|balanced|high`, `--re-token-limit`, and `--re-time-limit-minutes` to `echelon re run`. Keep continuation frozen; existing `--re-max-inner` may only increase convergence limits. Add documented profile defaults beneath `re.profiles` and `re.default_profile`.

- [ ] **Step 5: Implement legacy migration without invented limits**

Legacy state receives `name: legacy`, stored convergence values, and `null` hard time/token ceilings. Migration must preserve counters and active phase.

- [ ] **Step 6: Run tests and commit profile state**

Run: `.venv/bin/pytest tests/unit/test_re_profiles.py tests/kernel/test_re_state.py tests/unit/test_re_lifecycle.py tests/unit/test_cli_re_lifecycle.py -q`

Expected: all focused tests pass.

Commit: `git commit -am "feat: add bounded RE execution profiles"`

---

### Task 3: Active-time accounting, dispatch telemetry, and hard budget enforcement

**Files:**
- Create: `src/harness/re_budget.py`
- Modify: `src/harness/re_lifecycle.py`
- Modify: `src/harness/re_controller.py`
- Modify: `src/harness/squad_provider.py`
- Test: `tests/unit/test_re_budget.py`
- Test: `tests/unit/test_re_controller.py`
- Test: `tests/unit/test_re_lifecycle.py`

**Interfaces:**
- Produces: `evaluate_re_budget(state, now) -> ReBudgetDecision` and execution-interval helpers.
- Consumes: `TelemetryStore`, frozen profile, provider `SquadAgentResult` usage/duration.

- [ ] **Step 1: Write failing budget-boundary tests**

```python
def test_no_dispatch_starts_at_token_ceiling():
    decision = evaluate_re_budget(_state(tokens=5_000_000), now=NOW)
    assert decision.allowed is False
    assert decision.reason == "re_token_budget_exhausted"

def test_dispatch_may_cross_ceiling_once_and_checkpoint():
    # Start below ceiling, return usage that crosses it, then reconstruct controller.
    # Assert one call occurred and the reconstructed controller starts no second call.
```

Add tests proving stopped wall time does not count, continuation closes/opens execution intervals correctly, and unknown token dispatches remain explicitly counted.

- [ ] **Step 2: Run focused tests and confirm the controller still dispatches past limits**

Run: `.venv/bin/pytest tests/unit/test_re_budget.py tests/unit/test_re_controller.py tests/unit/test_re_lifecycle.py -q`

Expected: new boundary tests fail.

- [ ] **Step 3: Implement active invocation intervals and cumulative counters**

Outer state owns `execution_intervals`, `active_duration_ms`, `token_usage`, and `unknown_token_dispatches`. Opening an invocation records a UTC start; every lifecycle exit closes it in `finally`. Mirror the defensible cumulative counters into inner controller state before dispatch.

- [ ] **Step 4: Instrument every RE agent dispatch**

Before provider invocation, create span identity and append the completed span afterward with phase, agent, source/domain, attempt kind/number, verdict, duration, provider/model, standard token attributes, and blocking/non-blocking counts. Hash/size metadata may be recorded; raw prompt/output must not be included.

- [ ] **Step 5: Enforce budgets immediately before `write_last_dispatch`**

If denied, save a typed blocked reason. Blocking semantic findings prevent publication. Non-blocking findings are converted through the existing quality-debt report path. Preserve `last_dispatch` invariants and do not partially create a new sentinel.

- [ ] **Step 6: Run tests and commit enforcement**

Run: `.venv/bin/pytest tests/unit/test_re_budget.py tests/unit/test_re_controller.py tests/unit/test_re_lifecycle.py -q`

Expected: all focused tests pass, including existing granular-resume cases.

Commit: `git commit -am "feat: enforce RE time and token budgets"`

---

### Task 4: Shared analyzer core and RE legacy adapter

**Files:**
- Create: `src/echelon/telemetry/analyzer.py`
- Create: `src/echelon/telemetry/re_adapter.py`
- Create: `src/echelon/telemetry/render.py`
- Test: `tests/unit/test_run_analyzer.py`
- Test: `tests/fixtures/re-analysis/legacy-md-distribution/README.md`
- Test: `tests/fixtures/re-analysis/legacy-md-distribution/state.json`
- Test: `tests/fixtures/re-analysis/legacy-md-distribution/re/state.json`
- Test: `tests/fixtures/re-analysis/legacy-md-distribution/re/re-execution-plan.json`
- Test: `tests/fixtures/re-analysis/legacy-md-distribution/re/quality/sources/*.json`

**Interfaces:**
- Produces: `RunAnalysis`, `analyze_re_run(run_dir) -> RunAnalysis`, `analyze_re_runs(runs_dir) -> tuple[RunAnalysis, ...]`, `render_analysis_text`, and `analysis_to_json`.

- [ ] **Step 1: Create a minimized, non-source legacy fixture from the observed run**

Copy only state, execution-plan, quality-summary, and timestamp metadata needed to prove four sources, nineteen domains, fifty-five Prosaic repairs, and two partial-debt sources. Remove absolute paths and source content. Document provenance in the fixture README.

- [ ] **Step 2: Write failing analyzer tests for telemetry and legacy runs**

```python
def test_md_distribution_legacy_baseline(fixture_dir):
    report = analyze_re_run(fixture_dir)
    assert report.source_count == 4
    assert report.domain_count == 19
    assert report.domain_repairs_by_source["prosaic"] == 55
    assert report.partial_debt_source_count == 2
    assert report.tokens.known is False
    assert report.active_duration_ms is None
```

Also test malformed earlier JSONL lines, a truncated final line, profile compliance, group-by phase/source/domain, and stable JSON serialization.

- [ ] **Step 3: Run analyzer tests and confirm failure**

Run: `.venv/bin/pytest tests/unit/test_run_analyzer.py -q`

Expected: failures because analyzer APIs do not exist.

- [ ] **Step 4: Implement shared aggregation and RE-specific extraction**

All derived fields must carry `provenance` and `confidence`. Legacy filesystem timestamps may populate approximate wall-clock bounds but never active duration. Unknown usage yields indeterminate token compliance, not pass or zero.

- [ ] **Step 5: Implement stable text and versioned JSON output**

Text leads with outcome/profile compliance and then cost hotspots, repair effectiveness, repeated findings, debt, and limitations. JSON uses `schema_version: 1` and sorted stable collections.

- [ ] **Step 6: Run tests and commit analyzer core**

Run: `.venv/bin/pytest tests/unit/test_run_analyzer.py -q`

Expected: all analyzer tests pass.

Commit: `git commit -am "feat: analyze RE execution cost and quality"`

---

### Task 5: Hidden analyzer and diagnostic command catalog

**Files:**
- Modify: `src/echelon/cli_app.py`
- Modify: `src/echelon/cli.py`
- Test: `tests/unit/test_cli_re_analyze.py`
- Test: `tests/unit/test_cli_typer_app.py`

**Interfaces:**
- Consumes: `analyze_re_run(s)` and renderers.
- Produces: hidden `echelon re analyze` and hidden `echelon admin commands` surfaces.

- [ ] **Step 1: Write failing visibility and output tests**

```python
def test_re_analyze_is_callable_but_hidden_from_re_help(runner, fixture):
    assert "analyze" not in runner.invoke(app, ["re", "--help"]).output
    result = runner.invoke(app, ["re", "analyze", str(fixture), "--format", "json"])
    assert result.exit_code == 0
    assert json.loads(result.output)["schema_version"] == 1
```

Test that `admin commands` lists `echelon re analyze` while root help hides `admin`.

- [ ] **Step 2: Run tests and confirm command absence**

Run: `.venv/bin/pytest tests/unit/test_cli_re_analyze.py tests/unit/test_cli_typer_app.py -q`

Expected: new command tests fail.

- [ ] **Step 3: Implement hidden Typer commands**

Support `RUNS_DIR`, `--run-id`, and `--format text|json`. Reject unsafe run IDs and incompatible option combinations with exit code 2. Analysis remains read-only.

- [ ] **Step 4: Run tests and commit CLI surface**

Run: `.venv/bin/pytest tests/unit/test_cli_re_analyze.py tests/unit/test_cli_typer_app.py -q`

Expected: all focused tests pass.

Commit: `git commit -am "feat: expose hidden RE run analyzer"`

---

### Task 6: Optional wiki operations projection

**Files:**
- Create: `src/echelon/wiki/operations.py`
- Modify: `src/echelon/wiki/model.py`
- Modify: `src/echelon/wiki/service.py`
- Modify: `src/echelon/wiki/render.py`
- Modify: `src/echelon/cli_app.py`
- Test: `tests/unit/test_wiki_operations.py`
- Test: `tests/unit/test_wiki_service.py`
- Test: `tests/unit/test_cli_wiki.py`
- Test: `tests/unit/test_wiki_render.py`

**Interfaces:**
- Consumes: `analyze_re_runs` only; never reads spans directly.
- Produces: optional operation models/pages plus separately hashed operational manifest inputs.

- [ ] **Step 1: Write failing opt-in, rendering, and staleness tests**

```python
def test_default_wiki_excludes_runs(workspace):
    result = build_wiki(workspace)
    assert not (result.output_dir / "Operations").exists()

def test_include_runs_renders_analysis_without_raw_spans(workspace):
    result = build_wiki(workspace, include_runs=True)
    assert (result.output_dir / "Operations/RE Runs/re-1.md").is_file()
    assert not any(result.output_dir.rglob("spans.jsonl"))
```

Test config/flag precedence and that telemetry changes produce operational—not canonical—staleness.

- [ ] **Step 2: Run focused wiki tests and confirm missing behavior**

Run: `.venv/bin/pytest tests/unit/test_wiki_operations.py tests/unit/test_wiki_service.py tests/unit/test_cli_wiki.py tests/unit/test_wiki_render.py -q`

Expected: new opt-in tests fail.

- [ ] **Step 3: Extend the wiki model and service composition**

Resolve `include_runs` as explicit flag over `wiki.include_run_analysis`, default false. Discover canonical content from `WikiCatalogSource`, but analyze runtime runs from the caller root. Store `canonical_inputs` and `operational_inputs` separately in the manifest while accepting old manifests during migration.

- [ ] **Step 4: Render operations and aggregate views**

Render `Operations/Index.md`, one safe page per RE run, and populated `Views/Performance.md`, `Views/Token Usage.md`, `Views/Repeated Findings.md`, and `Views/Quality Debt.md`. Omit empty future lifecycle directories. Label every operations page local/ephemeral and show analysis limitations.

- [ ] **Step 5: Wire CLI boolean override and status reporting**

Use a tri-state Typer option so `--include-runs` and `--no-include-runs` override configuration. `wiki status` reports canonical and operational staleness distinctly.

- [ ] **Step 6: Run tests and commit wiki projection**

Run: `.venv/bin/pytest tests/unit/test_wiki_operations.py tests/unit/test_wiki_service.py tests/unit/test_cli_wiki.py tests/unit/test_wiki_render.py -q`

Expected: all focused wiki tests pass.

Commit: `git commit -am "feat: render run analysis in human wiki"`

---

### Task 7: Documentation, regression suite, and real-corpus baseline

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `tests/README.md`
- Test: `tests/unit/test_readme_recovery_contracts.py`
- Test: `tests/performance/test_wiki_build_performance.py`

**Interfaces:**
- Documents the public profile flags, hidden diagnostics discovery, telemetry privacy, baseline meaning, and optional Obsidian projection.

- [ ] **Step 1: Update user and contributor documentation**

Document `fast`, `balanced`, and `high`; 5M/180 balanced hard ceilings; active-time semantics; unknown provider usage; `echelon admin commands`; and `wiki build --include-runs`. State that the 60-minute balanced value is an optimization target, not its hard ceiling.

- [ ] **Step 2: Run the real legacy analyzer**

Run:

```bash
.venv/bin/python -m echelon.cli_app re analyze \
  /Users/michalbachorik/work/md_distribution/runs \
  --run-id re-20260718-063615-364321 --format json
```

Expected: four sources, nineteen domains, fifty-five Prosaic repairs, at least the observed partial-debt sources, unknown token usage, unknown active duration, and no false balanced-compliance claim.

- [ ] **Step 3: Run focused regression suites**

Run:

```bash
.venv/bin/pytest \
  tests/unit/test_execution_telemetry.py \
  tests/unit/test_re_profiles.py \
  tests/unit/test_re_budget.py \
  tests/unit/test_run_analyzer.py \
  tests/unit/test_cli_re_analyze.py \
  tests/unit/test_re_controller.py \
  tests/unit/test_re_lifecycle.py \
  tests/unit/test_cli_re_lifecycle.py \
  tests/unit/test_wiki_operations.py \
  tests/unit/test_wiki_service.py \
  tests/unit/test_cli_wiki.py -q
```

Expected: zero failures.

- [ ] **Step 4: Run full verification**

Run: `.venv/bin/pytest -q`

Expected: zero failures.

Run: `bash scripts/bash/dry-run.sh`

Expected: exit 0 with extension wiring valid.

Run: `git diff --check`

Expected: no output and exit 0.

- [ ] **Step 5: Commit documentation and verification fixtures**

Commit: `git commit -am "docs: document RE telemetry and profiles"` after adding any new fixture files.

