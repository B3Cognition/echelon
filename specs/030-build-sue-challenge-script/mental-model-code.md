# Mental Model Code

Status note: `scripts/sue_challenge.py` and `tests/unit/test_sue_challenge.py` do not exist yet (greenfield deliverable in a brownfield repo — confirmed by grep, timeline.md). Entities marked **PLANNED** are derived from the approved design (IN-REQ-35B242FAD892 … IN-REQ-C68D7D0CB17E) and SYNTHESIZER's unified model; entities marked **EXISTING** are verified in the repo at base commit ef2643c9. Invariant checks against planned code report UNKNOWN until IMPLEMENTER produces the files; contract-level inconsistencies already visible in the design are flagged now per Rule 1.

## Entity Graph

| Entity | Defined In | Depends On | Used By | Notes |
|--------|------------|------------|---------|-------|
| `sue_challenge.py` (script) | `scripts/sue_challenge.py` **PLANNED** | Python stdlib ONLY (argparse, subprocess, json, tempfile, pathlib) | operator CLI; `tests/unit/test_sue_challenge.py` | Standalone contract A-003: NEVER imports `harness.*`/`echelon.*`/`codegen.*`; shape mirrors `scripts/contradiction-scanner.py` |
| CLI / input validation | `sue_challenge.py` **PLANNED** | argparse; filesystem (spec read check) | orchestration flow (main) | Args: spec path, `--questions` (15), `--claude-cmd` (`claude`), `--timeout` (300); exit 1 fail-fast before any model call (IN-REQ-09CAF50DCD15) |
| Prompt assembly | `sue_challenge.py` **PLANNED** | spec text; round-1 questions (round 2 only); retry appendix | Subprocess runner | Owns round instructions, N cap, category taxonomy, schema demand; MUST NOT pass round-1 rationale into round 2 (IN-REQ-7906C2CCFEBC). U-001/U-003 land here |
| Subprocess runner (model invocation) | `sue_challenge.py` **PLANNED** | `--claude-cmd` value; neutral temp cwd; timeout | Prompt assembly (caller); JSON extraction (consumer of raw stdout) | Test seam (IN-REQ-B9724D0168AB); distinguishes exit 2 (command unavailable) from retry→exit 3 (output unusable); U-002/U-004 land here |
| JSON extraction & validation | `sue_challenge.py` **PLANNED** | raw model stdout; round schemas | Deterministic assembly; retry path | Round-1 schema (id/question/target/lines/category enum), round-2 schema (id/verdict enum/answer/evidence_lines), ID bijection (IN-REQ-D003F04C0FC3) |
| Deterministic assembly (filter + rank) | `sue_challenge.py` **PLANNED** | validated Answers | Report renderer; stdout summary | Findings = CONTRADICTED + UNANSWERABLE, contradictions first; ANSWERED → audit appendix; no model call (IN-REQ-97C434377BBE) |
| Report renderer | `sue_challenge.py` **PLANNED** | findings, audit entries, run metadata | operator; later workflow integrations (stable interface) | Writes `<spec-dir>/socratic-challenge.md` (overwrite) + `.sue-debug/` on exit-3 path; collapsed audit section (IN-REQ-2D4902546481) |
| `test_sue_challenge.py` | `tests/unit/test_sue_challenge.py` **PLANNED** | pytest; stub executable fixture; `sue_challenge.py` via subprocess/import | pytest collection | Collected by existing `pyproject.toml` testpaths=["tests"], pythonpath [".", "src"] |
| Stub executable (canned-JSON replayer) | `tests/fixtures/` **PLANNED** | canned round-1/round-2 JSON fixtures | `test_sue_challenge.py` via `--claude-cmd` | `tests/fixtures/` is norecursedirs — fixtures not collected as tests (correct home). Exact contract blocked on U-004 |
| claude CLI (`claude -p`) | external binary **EXISTING** | operator's claude session/auth | Subprocess runner (both rounds) | Hard external dependency; version-unpinned behavior surface (suspicious finding); output shape contested (U-001) |
| `pyproject.toml [tool.pytest.ini_options]` | repo root **EXISTING** | — | `test_sue_challenge.py` collection | Verified: testpaths, pythonpath, norecursedirs, `unit` marker all present |
| `tests/unit/conftest.py` | `tests/unit/` **EXISTING** | `tests/fixtures/` | new test file (FIXTURES_DIR convention) | Exposes `FIXTURES_DIR`; stub + canned JSON should follow this convention |
| `scripts/contradiction-scanner.py` | `scripts/` **EXISTING** | stdlib only | none (reference precedent, read-only) | Canonical standalone-script shape: usage-header docstring, argparse, own exit codes, "Dependencies: stdlib only" |
| `src/harness/llm_provider.py` (+ `ai_cli_backend`) | `src/harness/` **EXISTING** | stream-json, tool policy, repo cwd | harness only — **explicit NON-dependency of SUE** | Different contract; evidence that plain `claude -p` stdout may not be clean strict JSON (contradiction #2) |
| `specs/029-builder-spec-workbench/spec.md` | `specs/029-…` **EXISTING** | — | acceptance run only (read-only input) | Live, active spec — acceptance anchors (REQ-009/AC-010 contradiction, score-recording loop, active-run pointer) can drift (A-004 risk) |

## Contract Map

| Contract | Side A | Side B | Must Match | Verification |
|----------|--------|--------|------------|--------------|
| Round-1 JSON schema | Prompt assembly (schema demanded in round-1 prompt) | JSON validator (schema enforced on output) + stub fixture canned JSON | `{"questions":[{id, question, target: "REQ-nnn"\|"general", lines:[int], category: 5-enum}]}` (IN-REQ-1BB9602CB2BA/D67B2760CFF6) | Unit test: valid/invalid fixtures through validator; prompt text asserts same schema string |
| Round-2 JSON schema | Prompt assembly (round-2 prompt) | JSON validator + stub fixture | `{"answers":[{id, verdict: 3-enum, answer, evidence_lines:[int]}]}` (IN-REQ-FFF8B8176BC8/D003F04C0FC3) | Unit test with canned fixtures |
| ID bijection | Round-1 validated question ids | Round-2 validated answer ids | Every round-1 id exactly once; missing/duplicate/extra = parse failure → retry → exit 3 (IN-REQ-0F5AB554CF9C) | Unit tests: one fixture per violation class (missing, duplicate, extra) |
| Category enum | Round-1 prompt taxonomy wording | Validator enum constant | `ambiguity\|assumption\|contradiction\|undefined-term\|boundary` — one definition, two uses inside one file | Unit test + single shared constant in code (avoid the constants/bootstrap divergence failure mode) |
| Verdict enum + partition rule | Round-2 prompt wording + validator | Deterministic assembly partition | `ANSWERED\|UNANSWERABLE\|CONTRADICTED`; findings = exactly {CONTRADICTED, UNANSWERABLE}, contradictions ranked first | Unit test: mixed-verdict fixture → assert partition + order |
| `--claude-cmd` invocation seam | Subprocess runner (how the value is exec'd) | Stub executable (how tests provide a fake) | Token-vs-shell-split semantics — **UNDEFINED (U-004, must-resolve-before-WHAT)** | Blocked; once decided: stub records argv, test asserts invocation shape |
| Exit-code state machine | Script exit paths | Test assertions + operator documentation + ERR-CLI-MISSING pattern (spec 029) | 0 report written / 1 bad input before any model call / 2 claude unavailable / 3 unrecoverable parse failure; timeout ≡ parse failure (IN-REQ-E8F14EBD27A7/2189E42069FA/35B2A2BF9F9D) | Unit test per code; exit-2 boundary (binary present but crashing) undefined — U-007 |
| Isolation: subprocess cwd | Design premise "`claude -p` loads CLAUDE.md from cwd" (IN-REQ-DDDD35B79FFA) | Actual claude CLI context-loading behavior (user-scope `~/.claude/` loads regardless of cwd) | Neutral temp cwd ⇒ no repo/ambient context in the model's reading | **CONTESTED** — cwd is testable via stub-recorded cwd; full isolation is NOT achievable by cwd alone (A-002/U-002, CRITICAL contradiction) |
| Isolation: inter-round information | Round-1 output (questions + rationale) | Round-2 prompt content | Round-2 prompt contains spec text + question text/ids ONLY — no round-1 rationale, no conversational continuity | Unit test: stub records received prompt; assert absence of round-1 rationale markers |
| Output shape: "strict JSON" vs extraction | Design "Output: strict JSON" (IN-REQ-046E9F3A20C7) | Design lists "JSON extraction" as a unit-tested part (IN-REQ-BE91B88E2D80); harness prior art needed stream-json backend | Extraction contract (byte-pure vs fenced/noisy tolerated) — **UNDEFINED** (A-009/U-001) | Blocked on INVESTIGATOR spike; then noisy-output fixtures pin the contract |
| Report location & lifecycle | Report renderer | Operator + acceptance run + future integrations (stable interface, IN-REQ-128505B4CC53) | `<spec-dir>/socratic-challenge.md`, overwrite on rerun, `.sue-debug/` sibling on exit 3; header/findings/collapsed-audit sections | Unit test: render from canned findings, assert path, overwrite, sections incl. collapsed audit |
| pytest collection | `tests/unit/test_sue_challenge.py` + stub under `tests/fixtures/` | `pyproject.toml` (testpaths, norecursedirs, `unit` marker) | Test file collected; stub/fixtures NOT collected | `pytest tests/unit/test_sue_challenge.py` runs; verified config already supports this |
| Standalone (no-harness) rule | `sue_challenge.py` import list | Design non-goals (IN-REQ-D9CE68110258) + A-003 | Zero `harness.*`/`echelon.*`/`codegen.*` imports; stdlib only; no `echelon-config.yml` read | CODE REVIEWER gate + trivial import-scan check; tests run without installed venv |
| Acceptance anchors | Findings of one live run | Known issues in `specs/029-builder-spec-workbench/spec.md` (IN-REQ-A78CE7C82F30/D05A70A0F5B4) | Overlap with 3 named issues — **flaky by construction** vs nondeterministic model | CARTOGRAPHER must encode tolerance in the AC; re-verify/freeze 029 before the run |

## Data Flow

| Flow | Source | Path | Sink | Failure Points |
|------|--------|------|------|----------------|
| Happy path (challenge run) | spec file path (argv) | validate args + spec readability → read spec text once → assemble round-1 prompt → subprocess `claude -p` (temp cwd, timeout) → extract/validate round-1 JSON → assemble round-2 prompt (spec + bare questions) → subprocess `claude -p` (fresh, temp cwd) → extract/validate round-2 JSON + bijection → partition verdicts → rank (contradictions first) → render report → print summary (counts + top 3) | `<spec-dir>/socratic-challenge.md` + stdout; exit 0 | unreadable spec (exit 1); claude missing (exit 2); noisy/malformed output, bijection break, timeout (retry → exit 3); unwritable spec-dir (exit code UNDEFINED — U-005) |
| Corrective retry (per round) | parse failure or timeout in either round | same prompt + corrective appendix → one fresh subprocess → re-extract | validated JSON, or exit-3 path | retry content undefined for timeout case (no bad output to correct — U-003); systematic noise defeats the single-retry budget (suspicious finding) |
| Debug dump (exit-3 path) | raw stdout of failing call(s) | write raw output files | `<spec-dir>/.sue-debug/` | write failure semantics undefined; concurrent runs interleave writes (gap) |
| Spec content egress | challenged spec text | embedded in both prompts → claude CLI → model provider | external model provider | data-handling posture inherited from operator's claude session — confidential specs are an operator decision (must be stated in spec limitations) |
| Unit-test flow | canned JSON fixtures (`tests/fixtures/`) | pytest → script with `--claude-cmd <stub>` → stub replays fixtures, records cwd/argv/prompt | assertions on report, exit codes, isolation properties | stub contract blocked on U-004; extraction fixtures blocked on U-001 |

## Invariants

| Invariant | Evidence | Status | Check |
|-----------|----------|--------|-------|
| Every round-1 question id appears in round-2 answers exactly once (bijection); any violation is a parse failure | IN-REQ-D003F04C0FC3/0F5AB554CF9C; strongest machine-checkable rule (journal entry 6) | UNKNOWN (code not written) | Runtime validation in script; unit fixtures for missing/duplicate/extra id |
| `category` ∈ {ambiguity, assumption, contradiction, undefined-term, boundary}; `verdict` ∈ {ANSWERED, UNANSWERABLE, CONTRADICTED} | IN-REQ-D67B2760CFF6/FFF8B8176BC8 | UNKNOWN | Validator enum check; single shared constant used by both prompt text and validator |
| Findings = CONTRADICTED ∪ UNANSWERABLE only, contradictions ranked first; ANSWERED never appears in findings | IN-REQ-97C434377BBE/BEC67C964B9A | UNKNOWN | Unit test: mixed-verdict partition + ordering |
| Exit 1 occurs before any model call; exit codes limited to {0,1,2,3} | IN-REQ-09CAF50DCD15/E8F14EBD27A7 | UNKNOWN | Unit test: missing spec → exit 1 AND stub never invoked (call count 0) |
| At most 2 subprocess invocations per logical round (1 + 1 corrective retry); no cross-round retry | IN-REQ-5086BCDE7BCE; mental-model.md retry pattern | UNKNOWN | Stub call-counting in unit tests |
| Round-2 prompt contains no round-1 rationale; each round is a fresh subprocess (no conversational continuity) | IN-REQ-3709F66E4C4E/7906C2CCFEBC | UNKNOWN | Stub records received prompt; assert questions present, rationale absent |
| Every subprocess runs with cwd = neutral temp directory, never the repo | IN-REQ-2F84DF72B209 | UNKNOWN (and see V-1: even when PASS, this yields only partial isolation) | Stub records its cwd; assert temp path |
| `sue_challenge.py` imports stdlib only — no `harness.*`, `echelon.*`, `codegen.*`, no `echelon-config.yml` read | A-003; IN-REQ-D9CE68110258; scanner precedent | UNKNOWN | Import scan at code review; tests runnable without installed venv |
| The challenged spec file is never modified by a run | mental-model.md (Challenged Spec lifecycle) | UNKNOWN | Unit test: spec mtime/hash unchanged after run |
| Only writes are `<spec-dir>/socratic-challenge.md` (overwrite) and `<spec-dir>/.sue-debug/` (exit-3 only); temp dir holds nothing meaningful | IN-REQ-44BED4ECFE26/DAB2BB350DF1; boundaries.md | UNKNOWN | Unit test: enumerate spec-dir before/after |
| Report contains header (path, date, counts), findings section, and a **collapsed** audit appendix | IN-REQ-A06052CA8E2C/EBFAED130BFF/31A836647EEC/2D4902546481 | UNKNOWN — "collapsed" was dropped by every DISCOVER artifact (gap #1); must be carried into the FR | Unit test asserts collapse markup (e.g. `<details>`) once CARTOGRAPHER fixes rendering choice |
| Timeout is handled identically to a parse failure (retry once, then exit 3) | IN-REQ-35B2A2BF9F9D | UNKNOWN | Unit test: hanging stub + short `--timeout` |

## Invariant Violations

No code-level violations exist — there is no code yet. Two **contract-level inconsistencies in the approved design itself** are flagged per Rule 1 (invariant violations are model gaps even before tests exist). Phase contract: these are ALERT-level, non-blocking at this stage.

| Violation | Evidence | Impact | Alert |
|-----------|----------|--------|-------|
| V-1: Isolation contract as designed is unsatisfiable: the design premise "cwd controls CLAUDE.md loading" is contradicted by user-scope context loading (`~/.claude/CLAUDE.md`, global settings, MCP servers) that no cwd choice can suppress | IN-REQ-DDDD35B79FFA vs A-002/U-002; contradictions-and-gaps.md #1 (CRITICAL) | Silent correctness failure: both rounds read the spec under ambient user-scope influence — no crash, no signal; the grounding rule ("the text testifies") is quietly violated | TO ENGINEERING MANAGER: the "MUST NOT leak context" invariant cannot be verified or fully enforced via temp cwd alone. Require INVESTIGATOR marker-spike (U-002) before ARCHITECT freezes the runner design; spec must either add suppression flags (if the CLI offers them) or downgrade the invariant to "repo-scope isolation + documented user-scope limitation" |
| V-2: The two ends of the output contract disagree: prompt demands "strict JSON" while the tested surface includes "JSON extraction", and the only repo-proven `claude -p` integration needed stream-json + a backend layer to get parseable output | IN-REQ-046E9F3A20C7 vs IN-REQ-BE91B88E2D80 + `src/harness/llm_provider.py` prior art; contradictions #2/#4 | The validator's input contract is undefined — extraction fixtures, retry semantics, and exit-3 frequency all depend on it; with a single-retry budget, systematic noise makes the tool fail every run | TO ENGINEERING MANAGER: block HOW-phase finalization of the extraction module until U-001 spike pins the raw stdout shape and CARTOGRAPHER writes an explicit extraction contract (byte-pure vs fenced/noisy-tolerant) |

## Impact Traces

| Change Target | Direct Dependents | Indirect Dependents | Breakage Risk |
|---------------|-------------------|---------------------|---------------|
| Round-1/round-2 JSON schemas | prompt assembly, JSON validator, stub canned fixtures | deterministic assembly, report renderer, every unit test | HIGH — three-way contract; a schema edit that misses the fixtures silently green-tests wrong behavior |
| `--claude-cmd` semantics decision (U-004) | subprocess runner, exit-2 detection, stub executable design | entire unit-test suite (the seam), ERR-CLI-MISSING mirror | HIGH — must-resolve-before-WHAT; everything test-shaped hangs off it |
| JSON extraction contract (U-001 outcome) | extraction module, corrective-retry policy, noisy-output fixtures | exit-3 frequency, acceptance-run viability | HIGH |
| Prompt assembly (incl. retry appendix, U-003; line-numbering, U-006) | both model calls, isolation guarantees | question/answer quality, evidence verifiability (`lines`/`evidence_lines`) | MEDIUM — isolated seam per SYNTHESIZER's pattern: keep behind a narrow interface so late decisions don't ripple |
| Exit-code state machine (incl. U-005/U-007 resolutions) | main orchestration, all exit-code unit tests | operator docs, future workflow integration (stable interface) | MEDIUM |
| `specs/029-builder-spec-workbench/spec.md` (any amendment) | acceptance criterion anchors | run 030 FINALIZE acceptance | MEDIUM — external to the code but breaks the AC; freeze a fixture copy if 029 changes |
| claude CLI version drift | subprocess runner, extraction, isolation behavior | everything at runtime (unit tests immune via stub) | MEDIUM — record CLI version + validated flags from the spike so drift is detectable |
| `pyproject.toml` pytest config | test collection for `test_sue_challenge.py` | CI signal | LOW — stable, verified present |
| Report format (sections, collapse markup) | report renderer, rendering unit tests | downstream readers of `socratic-challenge.md` (stable-interface promise) | LOW-MEDIUM — format is the script's public output contract |
| `scripts/contradiction-scanner.py` | none (reference precedent only) | none | LOW — cited as shape convention, no runtime coupling |
