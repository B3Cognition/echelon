# QA Test Strategy Inputs

## Current Test State

| Area | Existing Tests | Evidence | Confidence |
|------|----------------|----------|------------|
| SUE challenge script | none (greenfield) | No `sue_challenge` matches in `tests/`, `scripts/`, `src/` | HIGH |
| Repo pytest infrastructure | extensive unit suite | `pyproject.toml [tool.pytest.ini_options]`: testpaths `tests`, pythonpath `.`/`src`, norecursedirs `tests/fixtures`, markers incl. `unit`; ~200 `tests/unit/test_*.py` files | HIGH |
| Fixture conventions | established | `tests/unit/conftest.py` exposes `FIXTURES_DIR = tests/fixtures` with path-returning fixtures | HIGH |
| Standalone-script testing precedent | established shape | `scripts/contradiction-scanner.py`: stdlib-only, argparse, own exit codes — the shape `test_sue_challenge.py` will drive | HIGH |

## Coverage and Gaps

| Gap | Evidence | Risk | Recommended Test |
|-----|----------|------|------------------|
| Round-2 ID bijection violations (missing id, duplicate id, extra id) | Strongest machine-checkable invariant (journal entry 6; IN-REQ-D003F04C0FC3/0F5AB554CF9C) | Findings misattributed or dropped silently | Unit: stub replays each violation class → assert parse-failure → retry → exit 3 |
| Verdict filtering and ranking | IN-REQ-97C434377BBE/BEC67C964B9A | Wrong findings order or ANSWERED leaking into findings | Unit: mixed-verdict canned answers → assert partition + contradictions-first order + audit appendix content |
| Exit-code state machine (0/1/2/3) | IN-REQ-E8F14EBD27A7/2189E42069FA; boundaries.md behavioral patterns | Misclassified failures (esp. exit 2 vs 3) | Unit: missing spec (1), absent command (2), double parse failure (3), happy path (0) |
| JSON extraction against noisy output | "strict JSON" vs extraction tension (A-009, U-001); one-retry budget | Systematic noise → constant exit 3 | Unit: fixtures with fenced JSON, leading noise, ANSI codes — pending U-001 spike to define the extraction contract |
| Degenerate outcomes (zero questions, zero findings, unwritable report) | U-005 unresolved — semantics undefined | Tests cannot be enumerated until decided | Blocked on CARTOGRAPHER decision; then unit-test each assigned behavior |
| Stub executable contract | `--claude-cmd` seam (IN-REQ-B9724D0168AB); U-004 (token vs command string) unresolved | Stub design depends on the U-004 decision | Fixture: stub under `tests/fixtures/` replaying canned round-1/round-2 JSON, call-counting for retry assertions |
| Isolation contract (temp cwd, no rationale to round 2) | IN-REQ-2F84DF72B209/7906C2CCFEBC | Silent correctness failure — untestable live | Unit: stub records its cwd + received prompt → assert temp cwd and absence of round-1 rationale; live leak check stays manual (U-002) |
| Acceptance run determinism | One live run vs three expected overlaps (journal entry 8) | Flaky acceptance | Manual acceptance with explicit tolerance encoded in AC; not a pytest concern |

## Frameworks and Tooling

| Tool | Purpose | Evidence | Notes |
|------|---------|----------|-------|
| pytest | unit test runner | `pyproject.toml` config; repo-wide convention | `tests/unit/test_sue_challenge.py`, marked `unit` (no external deps) |
| stub executable fixture | fake claude CLI via `--claude-cmd` | Design testing section (IN-REQ-B9724D0168AB/18F823464DCC) | Replays canned JSON; place under `tests/fixtures/` per conftest convention |
| tmp_path / temp dirs | isolated spec dirs for report-write assertions | Standard pytest fixture; matches script's own temp-cwd behavior | Verifies report co-location and `.sue-debug/` placement |
| No new dependencies | constraint | A-003; `scripts/` stdlib-only precedent; no lint config exists (CLAUDE.md) | Do not add jsonschema or similar — hand-rolled validation |
