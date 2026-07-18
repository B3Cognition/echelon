# Tasks: SUE Challenge Script

**Spec:** [spec.md](spec.md)
**Plan:** [plan.md](plan.md)

---

## Summary

| Metric | Value | Notes |
| --- | --- | --- |
| Total tasks | 15 | 14 build tasks + 1 manual acceptance gate (T-S01) |
| Parallelizable tasks | 0 | Single-file deliverable (`scripts/sue_challenge.py`) plus one test file; every task mutates the same files, so no two tasks are parallel-safe (see dependencies.md) |
| Critical path | 14 tasks, 10 h most-likely | Proportional decomposition of GATEKEEPER's estimate (estimates.md); ORCHESTRATOR added no new estimates |
| Effort range | 4–18 h (0.10–0.45 person-weeks) | GATEKEEPER consensus interval — pessimistic bound tightened at ASSESS2 (implementability-report.md), confidence medium |
| Phases | 5 | foundation → core → integration → polish → acceptance |

Test-First hard gate (constitution): every build task writes its named tests first and observes them fail before implementation. The **Test:** line of each task is the verification contract.

Consensus pass (PLAN2, 2026-07-18): ASSESS2 scored all 15 tasks READY — none needing clarification, none blocked; no task was split, added, or re-sequenced, and the dependency chain is unchanged. WHY3 feedback applied at task level: T-002 gains the non-positive `--questions`/`--timeout` rejection vectors (ISS-308) and the sub-second timeout parsing clarification (ISS-305). The remaining WHY3 fixes (ISS-301 state record, ISS-302/ISS-303 spec rewordings, ISS-304 mental-model patch) are owned by COMMANDER, CARTOGRAPHER, and DISCOVER respectively — they are squad-artifact repairs, not build tasks.

---

## Task Row Contract

Every executable task starts with one top-level canonical row:

```markdown
- [ ] T-001 complexity=standard phase=foundation req=FR-001 depends=none target=.
```

`target=.` is the single declared implementation target for this run. `T-S##` rows are operator-decision/manual-gate tasks.

---

## Phase: Foundation

- [x] T-001 complexity=standard phase=foundation req=FR-015,FR-023 depends=none target=.
  **Status:** DONE

  **Title:** Module skeleton — shared constants and dataclasses

  **Files:**
  - `scripts/sue_challenge.py` - new file: module docstring, shared constants, dataclasses (ADR-001/ADR-002)
  - `tests/unit/test_sue_challenge.py` - new file: importlib module loader, constant/dataclass tests

  **Description:**
  Create the single-file script skeleton per ADR-002: shared constants `CATEGORIES` (the 5 tokens `ambiguity`, `hidden-assumption`, `contradiction`, `undefined-term`, `missing-boundary` — FR-015), `VERDICTS` (`ANSWERED`, `UNANSWERABLE`, `CONTRADICTED` — FR-023), `QUESTION_ID_RE` (`^Q[1-9][0-9]*$`), `REPORT_FILENAME` (`socratic-challenge.md`), `DEBUG_DIR_NAME` (`.sue-debug`), exit-code constants (0/1/2/3), and prompt-template constants. Define the dataclasses from data-model.md: RunConfig, SpecDocument, SocraticQuestion, Answer, Finding, CallOutcome, ParseFailure. Create the test module that loads the script via importlib (ADR-008). Tests import the shared constants directly — they are the three-way contract anchor between prompts, validators, and stub fixtures (ISS-206).

  **Test:** pytest unit tests load the module via importlib with zero side effects and assert the exact constant values and dataclass field sets against data-model.md.

  **Acceptance Criteria:**
  - [x] Module imports without executing any pipeline code (import-safe, ADR-008)
  - [x] `CATEGORIES` has exactly 5 tokens plus `VERDICTS` exactly 3, matching contracts/model-command-contract.md
  - [x] All 7 data-model.md runtime entities exist as dataclasses with the documented fields

  **Test Tasks:**
  - [x] Constant-value assertions importing the module constants (contract-anchor tests)
  - [x] Dataclass instantiation tests for RunConfig, SocraticQuestion, Answer, CallOutcome, ParseFailure

- [x] T-002 complexity=standard phase=foundation req=FR-001,FR-002,FR-003,FR-004,FR-007,NFR-003 depends=T-001 target=.
  **Status:** DONE

  **Title:** Argument parsing and usage text with egress disclosure

  **Files:**
  - `scripts/sue_challenge.py` - `parse_args(argv) -> RunConfig` with the frozen v1 surface
  - `tests/unit/test_sue_challenge.py` - argument-handling behavior group (FR-044 group 1)

  **Description:**
  Implement `parse_args` per contracts/cli-contract.md: exactly 1 positional argument (spec path, FR-001), `--questions` defaulting to 15 (FR-002), `--claude-cmd` defaulting to `claude` (FR-003), `--timeout` defaulting to 300 seconds (FR-004). Split the model command per shell quoting conventions with `shlex.split`, treating word 1 as the executable to availability-check (FR-007); a value splitting to zero words is an argument error on the exit-1 path. The usage/help text contains exactly 1 egress disclosure stating that challenged specification content is sent to the model provider via the model command (NFR-003). Argparse's native exit-2 convention is remapped so argument errors funnel to the exit-1 bad-input class (U-007). Both numeric options enforce the data-model.md RunConfig `> 0` bounds: non-positive `--questions` or `--timeout` values are argument errors on the exit-1 path (ISS-308). `--timeout` parses as a positive number of seconds and accepts sub-second values — the timeout test matrix (test-strategy.md) drives 0.2–0.5 s budgets; ISS-305 routes the matching data-model.md/cli-contract.md type-row change (int → float) to ARCHITECT, and this task implements the float-seconds parse it prescribes. Tests first.

  **Test:** pytest argv-vector tests assert defaults (15/`claude`/300), `shlex` splitting of quoted command lines, zero-word rejection, exactly 1 egress-disclosure occurrence in captured `--help` text, plus parametrized non-positive vectors (`--questions 0/-1`, `--timeout 0/-1` → exit-1 argument-error class, ISS-308) and a sub-second `--timeout 0.3` acceptance vector (ISS-305).

  **Acceptance Criteria:**
  - [x] Defaults are exactly 15, `claude`, 300 (FR-002/FR-003/FR-004)
  - [x] `--claude-cmd "claude --safe-mode"` splits to executable `claude` (FR-007)
  - [x] `--help` output contains exactly 1 egress disclosure (NFR-003)
  - [x] Argument errors never surface as exit code 2 (U-007 boundary)
  - [x] Non-positive `--questions`/`--timeout` values reject on the exit-1 path (ISS-308); sub-second positive `--timeout` values parse (ISS-305)

  **Test Tasks:**
  - [x] Argument-handling group: defaults, overrides, quoting, zero-word value, help-text disclosure count
  - [x] Bounds vectors: non-positive `--questions`/`--timeout` rejection plus sub-second `--timeout` acceptance (ISS-308/ISS-305)

- [x] T-003 complexity=standard phase=foundation req=FR-005,FR-006,FR-012,FR-042,NFR-005 depends=T-002 target=.
  **Status:** DONE

  **Title:** Pre-flight checks, spec loading, fail() choke point, main() exit-code spine

  **Files:**
  - `scripts/sue_challenge.py` - `preflight`, `load_spec`, `fail()`, `main(argv) -> int`, `__main__` guard
  - `tests/unit/test_sue_challenge.py` - exit 1/2 pre-flight matrix (AC-013, AC-014, AC-019)

  **Description:**
  Implement `preflight` in the frozen order: spec readable (else exit 1, FR-005/ERR-001) → spec directory writable via `os.access(dir, W_OK)` (else exit 1, FR-006/ERR-002) → `shutil.which` on the FR-007 executable (else exit 2 with exactly 1 installation pointer, FR-012/ERR-003). Implement `load_spec`: read the file exactly once, UTF-8 with `errors="replace"` (ISS-210), newline-stripped lines, never writing the spec (FR-042). Implement the single `fail()` stderr choke point printing exactly 1 diagnostic line naming the failure class on every non-zero return (NFR-005, ADR-006), and `main(argv) -> int` returning codes without calling `sys.exit` itself; only the `__main__` guard calls `sys.exit(main())`. Tests first.

  **Test:** pytest tmp_path matrix proves exit 1 (missing/unreadable spec; read-only directory) and exit 2 (missing executable, message contains 1 installation pointer) each with exactly 0 model subprocess launches and exactly 1 stderr line.

  **Acceptance Criteria:**
  - [x] AC-013: missing/unreadable spec → exit 1, 0 model calls
  - [x] AC-019: read-only spec directory → exit 1, 0 model calls
  - [x] AC-014: executable not found → exit 2, exactly 1 installation pointer, 0 reports written
  - [x] Every non-zero exit emits exactly 1 stderr diagnostic line (NFR-005)

  **Test Tasks:**
  - [x] Pre-flight ordering test (readable checked before writable before which)
  - [x] Exit-code subset of the SC-003 matrix for codes 1 plus 2

## Checkpoint: Foundation Complete

**Verify before continuing:**
- [ ] All canonical task rows for `phase=foundation` are complete.
- [ ] Exit codes 1 plus 2 reproduce with 0 model calls, exactly 1 stderr line each (SC-003 subset); `--help` shows the egress disclosure; module imports without side effects.
- [ ] No blocker from this phase remains unresolved.

---

## Phase: Core

- [x] T-004 complexity=standard phase=core req=FR-014,FR-015,FR-018,FR-021,FR-022,FR-023 depends=T-003 target=.
  **Status:** DONE

  **Title:** Line numbering and round-1/round-2 prompt builders (pure)

  **Files:**
  - `scripts/sue_challenge.py` - `numbered_text`, `build_round1_prompt`, `build_round2_prompt`
  - `tests/unit/test_sue_challenge.py` - prompt-assembly behavior group (FR-044 group 2)

  **Description:**
  Implement `numbered_text`: every spec line prefixed `N: ` with 1-based numbering (FR-018), identical embedding for both rounds. Implement `build_round1_prompt`: numbered spec text plus the generation instruction requesting at most N questions across the 5 `CATEGORIES` tokens with the round-1 JSON schema demand (FR-014/FR-015). Implement `build_round2_prompt`: numbered spec text plus a `[{"id","question"}]` JSON array plus the answering instruction with the 3-verdict enum and the spec-text-only rule (FR-021/FR-023); the function signature receives only `(id, question)` pairs so round-1 categories, targets, line references, and reasoning are structurally absent — exactly 0 of these 4 elements appear (FR-022). All three are pure functions. Tests first, using the AC-011 counting convention pinned in contracts/model-command-contract.md: assert presence of the two data payloads and zero occurrences of round-1 category tokens/targets/line arrays/reasoning — not a literal block count.

  **Test:** pytest string assertions on built prompts: 1-based `N: ` numbering, question cap N and all 5 category tokens in round 1, `{id, question}`-only payload and zero round-1 leakage tokens in round 2.

  **Acceptance Criteria:**
  - [x] `numbered_text` starts at 1 and covers every line (FR-018)
  - [x] Round-1 prompt carries the numbered spec plus the FR-015 instruction (FR-014)
  - [x] Round-2 prompt contains 0 round-1 categories, targets, line references, or reasoning (FR-022, AC-011 convention)

  **Test Tasks:**
  - [x] Prompt-assembly group: numbering, round-1 content, round-2 leakage-absence matrix

- [x] T-005 complexity=complex phase=core req=FR-010,FR-011,FR-043 depends=T-004 target=.
  **Status:** DONE

  **Title:** Isolated subprocess runner with timeout and outcome classification

  **Files:**
  - `scripts/sue_challenge.py` - `run_model_call(config, prompt) -> CallOutcome`
  - `tests/unit/test_sue_challenge.py` - recording-stub and timeout tests (AC-011, AC-012)

  **Description:**
  Implement `run_model_call` per contracts/model-command-contract.md: argv is `shlex.split(model_command) + ["-p"]` (ADR-003), prompt delivered on stdin, subprocess cwd set to a fresh `tempfile.mkdtemp` neutral directory outside the repository, created and removed per call (FR-010, ADR-004). Enforce the per-call timeout with kill and partial stdout/stderr capture on `TimeoutExpired` (FR-011 — timeout classifies as parse failure downstream). Classify outcomes into the CallOutcome kinds `ok`/`timeout`/`launch_missing`/`failed` (ADR-006); `FileNotFoundError` at launch maps to `launch_missing` only. The function executes any operator-supplied command line, which is the stub test seam (FR-043) — the seam is exercised with real tmp_path-generated stub executables, never monkeypatched (ADR-008). Tests first.

  **Test:** pytest with tmp_path-generated recording stubs proves: fresh `sue-challenge-*` cwd outside the repo per invocation (AC-012), argv tail `-p`, prompt arrived on stdin read to EOF; a sleeping stub with a sub-second `--timeout` yields kind `timeout` with partial output preserved.

  **Acceptance Criteria:**
  - [x] AC-012: recorded cwd is exactly 1 newly created temp directory outside the repository per call (FR-010)
  - [x] Temp cwd is removed after each call, success or failure
  - [x] Timeout kills the subprocess, preserving partial output (FR-011)
  - [x] Stub executable substitution works end-to-end through the real subprocess spawn (FR-043)

  **Test Tasks:**
  - [x] cwd/argv/stdin-recording stub tests
  - [x] Sleeping-stub timeout test with sub-second budget (suite stays under the 30 s pre-commit target)

- [x] T-006 complexity=standard phase=core req=FR-026,FR-027 depends=T-005 target=.
  **Status:** DONE

  **Title:** Staged tolerant JSON extraction

  **Files:**
  - `scripts/sue_challenge.py` - `extract_json_object(raw) -> dict | ParseFailure`
  - `tests/unit/test_sue_challenge.py` - extraction behavior group (FR-044 group 3)

  **Description:**
  Implement the staged tolerant extractor (ADR-005): direct `json.loads` → code-fence strip → balanced-brace scan honoring string literals and escapes. Return the first parseable JSON object, tolerating surrounding non-JSON text and code fences (FR-026); zero extractable objects → ParseFailure with a naming reason (FR-027). A JSON array at top level is not an object and fails extraction. Pure function. Tests first.

  **Test:** pytest fixture matrix — clean JSON, fenced, prose-wrapped, multiple objects (first wins), zero objects, escaped-brace-in-string, top-level array — asserts the extracted dict or the ParseFailure reason.

  **Acceptance Criteria:**
  - [x] All 6 envelope fixture classes from test-strategy.md pass
  - [x] Zero-candidate input returns ParseFailure, never raises (FR-027)

  **Test Tasks:**
  - [x] Extraction fixture matrix as inline string fixtures

- [x] T-007 complexity=standard phase=core req=FR-016,FR-017,FR-019,FR-020 depends=T-006 target=.
  **Status:** DONE

  **Title:** Round-1 validation with truncation and empty-list success

  **Files:**
  - `scripts/sue_challenge.py` - `validate_round1(obj, max_questions) -> (questions, truncated) | ParseFailure`
  - `tests/unit/test_sue_challenge.py` - round-1 validation cases (FR-044 group 4, part 1)

  **Description:**
  Implement strict round-1 validation (FR-016): each question carries exactly 1 unique id matching `QUESTION_ID_RE`, exactly 1 non-empty question text, exactly 1 target (requirement identifier or `general`), a list of integer line references (range not checked at validation — ADR-005), and exactly 1 category from `CATEGORIES`. Any violation — including duplicate ids — returns ParseFailure naming the violation (FR-017). Apply first-N truncation in returned order with a truncation flag when the valid list exceeds `max_questions` (FR-019). An empty list is valid: the caller completes the run without round 2 (FR-020). Pure function. Tests first.

  **Test:** pytest per-violation JSON fixtures (bad id, duplicate id, missing field, empty text, unknown category, non-integer line) each yield a ParseFailure naming the offender; boundary cases at exactly N (no flag) and N+1 (flag set, first N kept); empty list returns a valid empty result.

  **Acceptance Criteria:**
  - [x] Every field violation of FR-016 is rejected with a naming reason
  - [x] Duplicate ids are a parse failure (FR-017)
  - [x] Truncation keeps the first N in returned order, setting the flag only above N (FR-019)
  - [x] Empty question list validates successfully (FR-020)

  **Test Tasks:**
  - [x] Per-violation fixture set plus N/N+1 truncation boundary tests

- [x] T-008 complexity=standard phase=core req=FR-024,FR-025 depends=T-007 target=.
  **Status:** DONE

  **Title:** Round-2 validation with identifier bijection

  **Files:**
  - `scripts/sue_challenge.py` - `validate_round2(obj, questions) -> list[Answer] | ParseFailure`
  - `tests/unit/test_sue_challenge.py` - bijection matrix (FR-044 group 4, part 2; AC-018)

  **Description:**
  Implement strict round-2 validation (FR-024): each answer carries exactly 1 question id, exactly 1 verdict from `VERDICTS`, exactly 1 non-empty answer text, and a list of integer evidence line references (range checked at render, not here — ADR-007). Enforce the identifier bijection against the post-truncation question ids: any id appearing 0 times or more than once, and any unknown id, is a ParseFailure whose reason names every offending id (FR-025, AC-018). Pure function. Tests first.

  **Test:** pytest bijection matrix — one missing, one duplicated, one unknown, missing+unknown combined, answers for pre-truncation ids after truncation — asserts ParseFailure with every offender named; exact-match set passes.

  **Acceptance Criteria:**
  - [x] AC-018: missing, duplicate, plus unknown ids each classify as parse failure (FR-025)
  - [x] ParseFailure.reason names every offending id
  - [x] Verdicts outside the 3-value set are rejected (FR-024)

  **Test Tasks:**
  - [x] Bijection id-set matrix with offender-naming assertions

- [x] T-009 complexity=complex phase=core req=FR-013,FR-028,FR-029,FR-030,FR-031 depends=T-008 target=.
  **Status:** DONE

  **Title:** Round execution loop — corrective retry, debug dump, exit-3 path

  **Files:**
  - `scripts/sue_challenge.py` - `build_retry_prompt`, `execute_round(config, prompt, validator, round_no, spec_dir)`
  - `tests/unit/test_sue_challenge.py` - retry-loop and dump tests (AC-015, AC-016, AC-017)

  **Description:**
  Implement `build_retry_prompt` (pure): on a non-timeout ParseFailure return the original prompt plus a corrective instruction naming `failure.reason`, echoing 0 lines of prior output (FR-028); on timeout return the original prompt unchanged — 0 appended corrective text (FR-029). Implement `execute_round`: at most 2 attempts per round, each attempt with a fresh full timeout budget (FR-013); first parse failure (including timeout) triggers exactly 1 corrective retry; second failure writes `.sue-debug/round{R}-attempt{A}-stdout.txt` and `-stderr.txt` for both failing attempts beside the spec — timeout attempts prefixed with a first line reading TIMEOUT after the configured budget in seconds (ISS-207) — and requests exit 3 (FR-030, ERR-004). Rounds are sequential calls in `main` with no cross-round loop, so a round-2 failure never re-runs round 1 — exactly 0 additional round-1 calls (FR-031). Tests first with numbered replay-sequence stubs.

  **Test:** pytest replay-sequence stubs prove: invalid→valid completes at exit 0 with exactly 2 invocations for that round (AC-016); invalid→invalid exits 3 with 4 dump files named per contract (AC-015); sleep→sleep exits 3 with TIMEOUT-prefixed dump lines (AC-017); a round-2 double failure leaves the round-1 invocation count at its prior value (FR-031).

  **Acceptance Criteria:**
  - [x] Corrective retry names the validation failure, echoing 0 prior-output lines (FR-028)
  - [x] Timeout retry re-issues the identical prompt (FR-029)
  - [x] Retry gets a fresh timeout budget equal to the configured value (FR-013)
  - [x] Second failure: exit 3, dumps for both attempts under `.sue-debug` (FR-030)
  - [x] Round-2 failure adds 0 round-1 calls (FR-031)

  **Test Tasks:**
  - [x] Replay-directory stub scenarios: invalid→valid, invalid→invalid, sleep→sleep
  - [x] Dump file naming plus TIMEOUT-line content assertions

## Checkpoint: Core Complete

**Verify before continuing:**
- [ ] All canonical task rows for `phase=core` are complete.
- [ ] SC-003 exit-3 matrix green; extraction fixtures all pass; recording stubs prove the isolation contract (fresh temp cwd, stdin prompt, round-2 leakage absence).
- [ ] No blocker from this phase remains unresolved.

---

## Phase: Integration

- [x] T-010 complexity=standard phase=integration req=FR-009,FR-032,FR-033 depends=T-009 target=.
  **Status:** DONE

  **Title:** Deterministic partition and ranking (pure)

  **Files:**
  - `scripts/sue_challenge.py` - `partition_answers`, `rank_findings`
  - `tests/unit/test_sue_challenge.py` - filtering/ranking behavior group (FR-044 group 5)

  **Description:**
  Implement `partition_answers`: exactly 2 groups — findings (verdicts CONTRADICTED plus UNANSWERABLE) and audit entries (ANSWERED) (FR-032). Implement `rank_findings`: all CONTRADICTED before all UNANSWERABLE, round-1 question order preserved within each class, dense 1-based ranks (FR-033). Both pure; exactly 0 model calls occur at or after this stage (FR-009) — enforced structurally because neither function can reach the runner. Tests first.

  **Test:** pytest mixed-verdict answer sets in shuffled round-1 order assert the two-class partition, contradictions-first ordering, within-class stability, and dense ranks (AC-004).

  **Acceptance Criteria:**
  - [x] AC-004: findings hold exactly the 2 verdict classes in FR-033 order
  - [x] Ranking is stable within class, dense from 1
  - [x] ANSWERED answers land only in audit entries (FR-032)

  **Test Tasks:**
  - [x] Partition/ranking property tests over shuffled inputs

- [x] T-011 complexity=standard phase=integration req=FR-035,FR-036,FR-037,FR-038,FR-039,FR-041,NFR-004 depends=T-010 target=.
  **Status:** DONE

  **Title:** Report and summary renderers (pure, golden-tested)

  **Files:**
  - `scripts/sue_challenge.py` - `render_report`, `render_summary`
  - `tests/unit/test_sue_challenge.py` - rendering behavior group (FR-044 group 6)

  **Description:**
  Implement `render_report` per contracts/report-format.md: exactly 3 sections in order — header, findings, audit appendix (FR-035). Header states exactly 4 base facts (spec path, run date, question count, finding count) plus the truncation note only when the flag is set (FR-036). Each findings entry states exactly 4 elements: verdict, question, target, evidence (FR-037), quoting exactly 1 spec line per cited number and stating the named gap for UNANSWERABLE findings (FR-039); out-of-range citations render the `(not present in the specification)` marker (ADR-007, ISS-202). The audit appendix lists every ANSWERED question with its answering lines inside exactly 1 collapsed HTML details block (FR-038). Zero findings renders the explicit "0 findings" statement (FR-041). Run date is injected, never read inside the renderer, so identical inputs give byte-identical bodies outside the run-date field (NFR-004). Implement `render_summary`: per-verdict-class counts plus the top 3 findings in rank order. Tests first with golden strings.

  **Test:** pytest golden-string tests cover section order, the 4 header facts, conditional truncation note, per-line evidence quoting against a known fixture spec, exactly 1 collapsed HTML details block, zero-finding and zero-question wording, out-of-range marker, and an NFR-004 double-render byte-diff.

  **Acceptance Criteria:**
  - [x] AC-002: header states exactly the 4 facts (FR-036)
  - [x] AC-008: audit appendix is exactly 1 collapsed expandable section (FR-038)
  - [x] AC-009: exactly 1 quoted spec line per cited evidence number (FR-039)
  - [x] AC-007 wording path: explicit 0-findings statement with full audit appendix (FR-041)
  - [x] Double render is byte-identical outside run date (NFR-004)

  **Test Tasks:**
  - [x] Golden report fixtures incl. line-0 plus beyond-range citations
  - [x] Summary top-3 plus per-class count tests

- [x] T-012 complexity=complex phase=integration req=FR-008,FR-020,FR-034,FR-040,FR-042 depends=T-011 target=.
  **Status:** DONE

  **Title:** Wire the main pipeline — end-to-end stubbed run green

  **Files:**
  - `scripts/sue_challenge.py` - `main` pipeline wiring (parse → preflight → load → rounds → assemble → write → summarize)
  - `tests/unit/test_sue_challenge.py` - end-to-end stub-seam tests (AC-001, AC-003, AC-005, AC-006, AC-010, AC-021)

  **Description:**
  Wire `main`: parse args → preflight → load spec → round 1 → skip round 2 when the valid question list is empty (FR-020, AC-006) → round 2 → partition/rank → write exactly 1 report file `socratic-challenge.md` in the spec's directory as a plain overwrite keeping 0 historical copies (FR-034, U-010) → print the terminal summary with per-class counts and top 3 findings → return 0 (FR-040). A full run performs exactly 2 logical model calls (FR-008) and never writes the challenged spec (FR-042). Tests first through in-process `main(argv)` with real stub subprocesses.

  **Test:** pytest end-to-end stub run asserts exit 0, exactly 2 stub invocations, report present with correct content (AC-001/AC-021); rerun leaves exactly 1 report file holding only new content (AC-003); zero-question run skips round 2 and reports 0 questions (AC-006); sha256 of the spec file is unchanged across every outcome (AC-010); stdout summary lists per-class counts and top 3 (AC-005).

  **Acceptance Criteria:**
  - [x] AC-001: exactly 2 model calls, report written beside the spec, exit 0
  - [x] AC-003: rerun overwrites — exactly 1 report file remains
  - [x] AC-006: valid empty round-1 list skips round 2, exit 0
  - [x] AC-010: challenged spec byte-identical after every run outcome (FR-042)
  - [x] AC-005: summary states counts per verdict class plus top 3 in rank order (FR-040)

  **Test Tasks:**
  - [x] Full stubbed end-to-end run (critical journey T-SEAM-01 — must never be flaky)
  - [x] Rerun-overwrite, zero-question, plus spec-hash invariance tests

## Checkpoint: Integration Complete

**Verify before continuing:**
- [ ] All canonical task rows for `phase=integration` are complete.
- [ ] `pytest -m unit tests/unit/test_sue_challenge.py` fully green offline with 0 network calls, no `claude` on PATH (SC-002 subset).
- [ ] No blocker from this phase remains unresolved.

---

## Phase: Polish

- [x] T-013 complexity=standard phase=polish req=FR-045,NFR-002 depends=T-012 target=.
  **Status:** DONE

  **Title:** Standalone-contract gate — import scan and zero-install verification

  **Files:**
  - `tests/unit/test_sue_challenge.py` - FR-045 import-scan test and NFR-002 dependency assertions

  **Description:**
  Add the standalone gate: a test that scans the script's import statements and asserts zero imports from `harness`, `echelon`, `codegen`, `understanding`, or any non-stdlib package, and that the script reads exactly 2 kinds of input — argv and the challenged spec file — touching 0 orchestration configuration or state files (FR-045, A-003). Assert the runtime dependency set is the standard library only, so a fresh checkout needs 0 additional installed components beyond the runtime and the model command (NFR-002, SC-005). This is the feasibility.md risk-5 anti-coupling gate the CODE REVIEWER pass re-checks.

  **Test:** pytest import-scan test parses `scripts/sue_challenge.py` with `ast` and fails on any non-stdlib or project-package import; a stubbed run under a clean environment completes with 0 additional installs.

  **Acceptance Criteria:**
  - [x] Import scan proves 0 project-package plus 0 third-party runtime imports (FR-045)
  - [x] Stubbed run succeeds on a fresh checkout with 0 additional installed components (NFR-002)

  **Test Tasks:**
  - [x] AST-based import-scan test
  - [x] Clean-environment stub run assertion

- [x] T-014 complexity=standard phase=polish req=FR-043,FR-044,FR-045,NFR-001,NFR-005 depends=T-013 target=.
  **Status:** DONE

  **Title:** Coverage completion, exit-code matrix, NFR hardening, flakiness gate

  **Files:**
  - `tests/unit/test_sue_challenge.py` - SC-003 matrix, NFR-001/NFR-005 assertions, behavior-group coverage sweep
  - `scripts/sue_challenge.py` - usage-text polish and any gaps the sweep exposes

  **Description:**
  Close FR-044: verify all 7 deterministic behavior groups — argument handling, prompt assembly, extraction, validation with identifier bijection, filtering plus ranking, report rendering, exit codes — have passing offline tests, and that the stub seam covers a full run with exactly 0 live model calls (FR-043, AC-021/AC-022). Complete the SC-003 exit-code matrix: every failure class reproduces its assigned code 1/2/3 with exactly 1 stderr diagnostic line (NFR-005). Add the NFR-001 structural check: a call-counting stub proves at most 4 subprocess invocations per run, bounding wall-clock at 4 timeout budgets plus local processing. Run the flakiness gate from test-strategy.md: 5 consecutive full runs of the suite, all green, before merge.

  **Test:** pytest SC-003 matrix plus call-count bound plus stderr-line-count assertions all pass; `for i in 1 2 3 4 5; do pytest -m unit tests/unit/test_sue_challenge.py || exit 1; done` completes green.

  **Acceptance Criteria:**
  - [x] AC-022: whole suite passes offline with 0 network calls plus 0 live model commands installed (FR-044)
  - [x] SC-003: exit codes 1/2/3 each reproduce with exactly 1 diagnostic line (NFR-005)
  - [x] Call-counting stub proves ≤ 4 subprocess invocations per run (NFR-001 structural bound)
  - [x] 5 consecutive suite runs green (flakiness gate)

  **Test Tasks:**
  - [x] Behavior-group coverage sweep against SENTINEL's coverage-map.md
  - [x] SC-003 exit-code matrix plus 5-run flakiness loop

## Checkpoint: Polish Complete

**Verify before continuing:**
- [ ] All canonical task rows for `phase=polish` are complete.
- [ ] Every FR/AC/NFR row in coverage-map.md points at a passing test or the named manual gate; CODE REVIEWER sign-off on the zero-coupling gate recorded.
- [ ] No blocker from this phase remains unresolved.

---

## Phase: Acceptance

- [ ] T-S01 complexity=standard phase=acceptance req=FR-034 depends=T-014 target=.

  **Title:** Manual live acceptance run against spec 029 (FINALIZE gate)

  **Files:**
  - `specs/029-builder-spec-workbench/socratic-challenge.md` - generated live report (run output, not authored)

  **Description:**
  Operator-executed FINALIZE gate (SC-001, AC-023) — the single live-model validation of v1; not an automated build task. Step 1: re-verify or freeze the three spec-029 known-issue anchors (A-004, last validated at base commit ef2643c9). Step 2: run `python3 scripts/sue_challenge.py specs/029-builder-spec-workbench/spec.md`. Success: a report exists whose findings overlap at least 1 of the 3 named known issues, within at most 3 total attempts. Step 3: record observed spec/prompt sizes for the A-005 context-window limitation (ISS-209 measurement). Failure after 3 attempts blocks FINALIZE and routes to COMMANDER — not silently waived.

  **Test:** Manual gate — report generated by the live run; finding overlap with ≥ 1 of the 3 named spec-029 issues verified by the operator within ≤ 3 attempts; sizes recorded in the run notes.

  **Acceptance Criteria:**
  - [ ] A-004 anchors re-verified or frozen before the first attempt
  - [ ] AC-023: finding overlap ≥ 1 of 3 named issues within ≤ 3 attempts (SC-001)
  - [ ] Spec/prompt sizes recorded (A-005/ISS-209)

  **Test Tasks:**
  - [ ] Operator checklist execution with result recording at FINALIZE

## Checkpoint: Acceptance Complete

**Verify before continuing:**
- [ ] All canonical task rows for `phase=acceptance` are complete.
- [ ] SC-001 overlap criterion met within the attempt budget; measurements recorded.
- [ ] No blocker from this phase remains unresolved.

---

## Summary Table

| Phase | Tasks | Notes |
| --- | ---: | --- |
| foundation | 3 | CLI surface, pre-flight, exit-code spine (plan Phase 1) |
| core | 6 | runner + isolation, extraction, validation, retry loop (plan Phases 2–3) |
| integration | 3 | assembly, rendering, end-to-end wiring (plan Phase 4) |
| polish | 2 | standalone gate, coverage completion, NFR hardening (plan Phase 5) |
| acceptance | 1 | manual live acceptance run (plan Final Phase) |
