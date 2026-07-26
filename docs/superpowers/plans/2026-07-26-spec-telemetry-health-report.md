# Spec Telemetry Health Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an observe-only `echelon spec analyze --health` report that deterministically identifies Spec workflow reliability, convergence, performance, and telemetry-quality exceptions without reading raw run files.

**Architecture:** Extend the existing Spec adapter with generic lifecycle aggregates, then pass only normalized `RunAnalysis` values into a new health aggregation module. Add stable text/JSON renderers and an opt-in CLI flag; do not touch controller, routing, checkpoint, rewind, provider, or telemetry storage behavior.

**Tech Stack:** Python 3.11+, frozen dataclasses, Typer, pytest, existing `TelemetryStore` and `RunAnalysis` APIs.

## Global Constraints

- Health reporting is read-only and exits zero whenever a report is generated successfully.
- Existing `echelon spec analyze` behavior and JSON schema remain unchanged without `--health`.
- Health aggregation consumes `RunAnalysis`; it must not parse telemetry files directly.
- Phase handling is data-driven and must not hardcode WHY, WHAT, PLAN, Lexicon, or future nodes.
- Unknown usage remains unknown and is never converted to zero.
- No synthetic numeric health score.
- No new runtime dependency.

---

### Task 1: Normalize Generic Spec Lifecycle Facts

**Files:**
- Modify: `tests/unit/test_spec_run_analyzer.py`
- Modify: `src/echelon/telemetry/spec_adapter.py`

**Interfaces:**
- Consumes: dispatch and blocker lifecycle records already loaded by `analyze_spec_run(run_dir: Path)`.
- Produces: `workflow_metrics["dispatches"]`,
  `workflow_metrics["blockers_by_phase"]`,
  `workflow_metrics["phase_order"]`, and
  `workflow_metrics["recency"]`, all JSON-safe values; also adds
  `dimensions["by_provider"]`.

- [ ] **Step 1: Write failing lifecycle-normalization tests**

Add assertions proving that the adapter reports every phase generically and does
not treat an initial dispatch as a repair:

```python
dispatches = report.workflow_metrics["dispatches"]
assert dispatches["total"] == 6
assert dispatches["by_reason"] == {"initial": 6}
assert dispatches["by_phase"]["phase1-what"] == {
    "total": 1,
    "by_reason": {"initial": 1},
    "max_attempt": 3,
    "errors": 0,
}
assert report.workflow_metrics["blockers_by_phase"] == {
    "phase1-why1": {"traceability": 2}
}
assert report.workflow_metrics["phase_order"] == [
    "phase1-why1",
    "phase1-why2",
    "phase1-what",
    "phase3-plan",
]
assert report.dimensions["by_provider"]["codex"]["dispatches"] == 2
```

Add a dedicated event using `phase1-lexicon` and
`reason="deterministic_repair"`; assert it appears without adapter changes
specific to Lexicon. Add recency tests proving `state.created_at` wins, then
`telemetry/manifest.json.created_at`, then run-directory modification time;
assert the selected source is recorded beside the sortable value.

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
pytest -q tests/unit/test_spec_run_analyzer.py
```

Expected: failure because `dispatches` and `blockers_by_phase` are absent.

- [ ] **Step 3: Implement minimal normalization**

Add focused helpers:

```python
def _dispatch_summary(
    events: Iterable[Mapping[str, object]],
) -> dict[str, object]:
    ...

def _blockers_by_phase(
    events: Iterable[Mapping[str, object]],
) -> dict[str, dict[str, int]]:
    ...
```

Each phase bucket contains `total`, sorted `by_reason`, `max_attempt`, and
`errors`. Build blocker buckets from blocker lifecycle events and sort phase and
reason keys. Preserve first encounter order in `phase_order`. Add
`_run_recency()` without mutating the directory, and add
`gen_ai.provider.name` through the existing `_dimension()` helper. Preserve the
existing compatibility metrics.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:

```bash
pytest -q tests/unit/test_spec_run_analyzer.py
```

Expected: all tests pass.

- [ ] **Step 5: Commit normalized lifecycle facts**

```bash
git add src/echelon/telemetry/spec_adapter.py tests/unit/test_spec_run_analyzer.py
git commit -m "feat: normalize spec telemetry lifecycle facts"
```

---

### Task 2: Add Deterministic Health Aggregation

**Files:**
- Create: `src/echelon/telemetry/health.py`
- Create: `tests/unit/test_spec_telemetry_health.py`

**Interfaces:**
- Consumes: `Iterable[RunAnalysis]`.
- Produces:

```python
@dataclass(frozen=True)
class HealthFinding:
    code: str
    severity: str
    scope: str
    subject: str
    affected_runs: int
    eligible_runs: int
    evidence: str
    observed: object | None = None
    comparison: object | None = None

@dataclass(frozen=True)
class HealthReport:
    schema_version: int
    workflow: str
    state: str
    cohort: dict[str, object]
    summary: dict[str, object]
    phase_observations: dict[str, dict[str, object]]
    findings: tuple[HealthFinding, ...]
    excluded_runs: dict[str, int]
    diagnostics: tuple[str, ...]

def analyze_spec_health(reports: Iterable[RunAnalysis]) -> HealthReport:
    ...
```

- [ ] **Step 1: Write failing tests for health states and findings**

Construct `RunAnalysis` fixtures in memory and assert:

```python
health = analyze_spec_health((report,))
assert health.state == "INSUFFICIENT_DATA"
assert health.findings[0].code == "telemetry.dispatches_unavailable"
```

For a blocked run with usable dispatch facts:

```python
assert health.state == "DEGRADED"
assert any(
    finding.code == "reliability.blocked_runs"
    and finding.severity == "critical"
    for finding in health.findings
)
```

For repeated deterministic repair and manual rerun events:

```python
assert health.phase_observations["phase1-lexicon"]["repairs"] == 2
assert health.phase_observations["phase1-lexicon"]["manual_reruns"] == 1
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
pytest -q tests/unit/test_spec_telemetry_health.py
```

Expected: collection error because `echelon.telemetry.health` does not exist.

- [ ] **Step 3: Implement dataclasses, cohort identity, and reliability aggregation**

Use only `RunAnalysis`. Derive cohort identity from schema, profile name,
profile/autonomy data, and sorted sets of every known provider and model
dimension. Select the latest run by `workflow_metrics["recency"]["value"]`,
using run ID only as a deterministic tie-breaker. Explicitly exclude
incompatible reports and record reasons.

Generate deterministic reliability, repair, rerun, provider-error, and
telemetry-coverage findings. Sort findings by severity rank, affected run count,
subject, and code.

- [ ] **Step 4: Run health tests and verify GREEN**

Run:

```bash
pytest -q tests/unit/test_spec_telemetry_health.py
```

Expected: health-state, reliability, phase, and ordering tests pass.

- [ ] **Step 5: Write failing tests for performance comparison**

Create four eligible historical reports plus one latest report. Assert that:

```python
assert not any(
    finding.code.startswith("performance.")
    for finding in four_run_health.findings
)
assert any(
    finding.code == "performance.active_duration_regression"
    for finding in five_run_health.findings
)
```

Use a latest duration that is more than 50% above the preceding-run median and
above the nearest-rank p95. Add the same test for tokens. Assert stable output
ordering when input is repeated.

- [ ] **Step 6: Run the new tests and verify RED**

Run:

```bash
pytest -q tests/unit/test_spec_telemetry_health.py
```

Expected: performance-regression assertions fail.

- [ ] **Step 7: Implement dependency-free percentile comparison**

Add private median and nearest-rank percentile helpers. Compare the latest run
against preceding compatible runs. Require five total eligible observations;
performance findings use `info` severity and never determine `DEGRADED`.

- [ ] **Step 8: Run focused tests and verify GREEN**

Run:

```bash
pytest -q tests/unit/test_spec_telemetry_health.py
```

Expected: all health aggregation tests pass.

- [ ] **Step 9: Commit the health model**

```bash
git add src/echelon/telemetry/health.py tests/unit/test_spec_telemetry_health.py
git commit -m "feat: aggregate spec telemetry health"
```

---

### Task 3: Add Stable Health Renderers

**Files:**
- Modify: `src/echelon/telemetry/render.py`
- Modify: `tests/unit/test_spec_telemetry_health.py`

**Interfaces:**
- Consumes: `HealthReport`.
- Produces:

```python
def health_to_json(report: HealthReport) -> str:
    ...

def render_health_text(report: HealthReport) -> str:
    ...
```

- [ ] **Step 1: Write failing renderer tests**

Assert JSON is schema-versioned, findings retain analyzer ordering, and text
contains the same state, finding codes/evidence, cohort coverage, phase
observations, and diagnostics:

```python
payload = json.loads(health_to_json(health))
assert payload["schema_version"] == 1
assert payload["state"] == health.state
assert [item["code"] for item in payload["findings"]] == [
    item.code for item in health.findings
]

text = render_health_text(health)
assert "SPEC TELEMETRY HEALTH" in text
assert f"State: {health.state}" in text
assert health.findings[0].code in text
```

Call both functions twice and assert byte-identical output.

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```bash
pytest -q tests/unit/test_spec_telemetry_health.py
```

Expected: import failure for missing renderer functions.

- [ ] **Step 3: Implement renderers**

Serialize dataclasses through stable `to_json_dict()` methods and
`json.dumps(..., indent=2, sort_keys=True)`. Render exception-first text without
timestamps. Do not modify `render_analysis_text()` or `analysis_to_json()`.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:

```bash
pytest -q tests/unit/test_spec_telemetry_health.py
```

Expected: all tests pass.

- [ ] **Step 5: Commit renderers**

```bash
git add src/echelon/telemetry/render.py tests/unit/test_spec_telemetry_health.py
git commit -m "feat: render spec telemetry health reports"
```

---

### Task 4: Wire the Opt-in CLI Contract

**Files:**
- Modify: `src/echelon/cli_app.py`
- Modify: `tests/unit/test_cli_spec_analyze.py`

**Interfaces:**
- Adds: `--health` boolean option to `echelon spec analyze`.
- Reuses: existing path resolution and `analyze_spec_run(s)` discovery.

- [ ] **Step 1: Write failing CLI tests**

Create run fixtures with telemetry dispatches and assert:

```python
result = CliRunner().invoke(
    app,
    ["spec", "analyze", str(runs), "--health", "--format", "json"],
)
assert result.exit_code == 0
payload = json.loads(result.output)
assert payload["workflow"] == "spec"
assert payload["state"] in {"HEALTHY", "DEGRADED", "INSUFFICIENT_DATA"}
```

Add text-mode coverage, single-run coverage, an empty-directory check, and an
input-hash assertion proving run files are unchanged. Retain the existing
non-health JSON test byte contract.

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
pytest -q tests/unit/test_cli_spec_analyze.py
```

Expected: failure because `--health` is not accepted.

- [ ] **Step 3: Implement CLI delegation**

Add:

```python
health: bool = typer.Option(
    False,
    "--health",
    help="Render an observe-only reliability and telemetry exception report.",
)
```

After existing discovery and empty-run handling:

```python
if health:
    report = analyze_spec_health(reports)
    typer.echo(
        health_to_json(report)
        if output_format == "json"
        else render_health_text(report),
        nl=False,
    )
    return
```

Do not change the existing non-health branch.

- [ ] **Step 4: Run CLI and analyzer tests**

Run:

```bash
pytest -q \
  tests/unit/test_cli_spec_analyze.py \
  tests/unit/test_spec_run_analyzer.py \
  tests/unit/test_spec_telemetry_health.py
```

Expected: all tests pass.

- [ ] **Step 5: Commit CLI wiring**

```bash
git add src/echelon/cli_app.py tests/unit/test_cli_spec_analyze.py
git commit -m "feat: expose spec telemetry health analysis"
```

---

### Task 5: Regression and Read-only Verification

**Files:**
- Modify only if a failing in-scope test exposes a defect.

**Interfaces:**
- Verifies all preceding public and internal contracts.

- [ ] **Step 1: Run telemetry and wiki regression tests**

Run:

```bash
pytest -q \
  tests/unit/test_execution_telemetry.py \
  tests/unit/test_spec_telemetry_provider.py \
  tests/unit/test_spec_run_analyzer.py \
  tests/unit/test_run_analyzer.py \
  tests/unit/test_cli_spec_analyze.py \
  tests/unit/test_wiki_operations.py \
  tests/unit/test_spec_telemetry_health.py
```

Expected: all tests pass.

- [ ] **Step 2: Run the full test suite**

Run:

```bash
pytest -q
```

Expected: all tests pass.

- [ ] **Step 3: Verify repository integrity**

Run:

```bash
git diff --check
git status --short --branch
```

Expected: no whitespace errors and only intentional changes, if any.

- [ ] **Step 4: Review scope**

Confirm no modifications under controller, routing, checkpoint, rewind,
provider, telemetry storage, or workflow definition paths. Confirm health
analysis writes no files.

- [ ] **Step 5: Commit any verification-only correction**

If and only if Step 1 or Step 2 required an in-scope correction:

```bash
git add <exact corrected files>
git commit -m "fix: harden spec telemetry health analysis"
```
