# Semantic Reproducibility Report

- **Specification:** specs/030-build-sue-challenge-script/spec.md
- **Run date:** 2026-07-20
- **Readers:** 2 completed (1 dropped: R3(adversarial))
- **Measurement vector** (no single number tells this story):
  - semantic convergence: 0.461 — fractured
  - witness candidates (unverified): 0 · phrasing variants filtered: 21
  - assumption load (mean/req): 1.10
  - untrusted convergence (thin consensus): 0
  - evidence overlap (mean/requirement): 0.95
  - evidence coverage: 0.96
  - requirements measured: 83
- **Ungrounded edges dropped:** R1=0, R2=0
- **Failed extraction chunks (coverage gaps):** R2=1

## Per-requirement agreement (worst first)

| Requirement | Score | Readers | Mean edges | Assumption load | Near-misses |
|---|---|---|---|---|---|
| AC-017 | 0.00 | 2 | 5.0 | 1.0 | 5 |
| AC-021 | 0.00 | 2 | 3.5 | 1.0 | 2 |
| ERR-004 | 0.00 | 2 | 3.5 | 1.0 | 3 |
| FR-009 | 0.00 | 2 | 2.0 | 1.0 | 2 |
| FR-029 | 0.00 | 2 | 2.5 | 1.0 | 2 |
| FR-040 | 0.00 | 2 | 4.5 | 1.5 | 2 |
| NFR-005 | 0.00 | 2 | 2.5 | 1.0 | 2 |
| REQ-002 | 0.00 | 2 | 2.0 | 1.5 | 0 |
| REQ-009 | 0.00 | 2 | 2.0 | 1.5 | 1 |
| AC-002 | 0.09 | 2 | 6.0 | 1.0 | 1 |
| AC-001 | 0.10 | 2 | 5.5 | 1.0 | 1 |
| AC-008 | 0.10 | 2 | 5.5 | 1.0 | 2 |
| AC-007 | 0.12 | 2 | 4.5 | 0.5 | 3 |
| FR-008 | 0.12 | 2 | 4.5 | 1.0 | 3 |
| AC-003 | 0.14 | 2 | 4.0 | 1.0 | 1 |
| AC-005 | 0.14 | 2 | 4.0 | 1.0 | 3 |
| AC-006 | 0.14 | 2 | 4.0 | 1.0 | 1 |
| AC-018 | 0.14 | 2 | 4.0 | 1.0 | 3 |
| AC-022 | 0.14 | 2 | 4.0 | 1.0 | 3 |
| FR-044 | 0.14 | 2 | 4.0 | 1.5 | 2 |
| ERR-001 | 0.17 | 2 | 3.5 | 1.0 | 2 |
| ERR-002 | 0.17 | 2 | 3.5 | 1.0 | 2 |
| ERR-003 | 0.17 | 2 | 3.5 | 1.0 | 2 |
| FR-023 | 0.17 | 2 | 3.5 | 1.0 | 2 |
| AC-004 | 0.25 | 2 | 5.0 | 1.0 | 2 |
| AC-012 | 0.25 | 2 | 5.0 | 1.0 | 3 |
| FR-016 | 0.25 | 2 | 10.0 | 2.0 | 3 |
| FR-032 | 0.25 | 2 | 5.0 | 1.0 | 2 |
| FR-034 | 0.27 | 2 | 7.0 | 2.0 | 2 |
| ERR-005 | 0.29 | 2 | 4.5 | 1.0 | 1 |
| FR-030 | 0.29 | 2 | 11.0 | 2.5 | 2 |
| FR-024 | 0.30 | 2 | 6.5 | 1.0 | 3 |
| AC-010 | 0.33 | 2 | 4.0 | 0.5 | 1 |
| AC-013 | 0.33 | 2 | 4.0 | 1.0 | 1 |
| AC-015 | 0.33 | 2 | 4.0 | 1.0 | 1 |
| FR-018 | 0.33 | 2 | 4.0 | 1.0 | 2 |
| FR-025 | 0.33 | 2 | 4.0 | 1.0 | 2 |
| FR-036 | 0.33 | 2 | 6.0 | 2.5 | 1 |
| FR-038 | 0.33 | 2 | 2.0 | 1.0 | 0 |
| NFR-002 | 0.33 | 2 | 4.0 | 1.5 | 1 |
| AC-011 | 0.38 | 2 | 5.5 | 1.0 | 2 |
| FR-002 | 0.38 | 2 | 5.5 | 1.5 | 2 |
| AC-009 | 0.40 | 2 | 3.5 | 1.0 | 0 |
| AC-016 | 0.40 | 2 | 3.5 | 1.0 | 1 |
| FR-003 | 0.40 | 2 | 3.5 | 1.0 | 1 |
| FR-015 | 0.40 | 2 | 3.5 | 1.0 | 0 |
| AC-023 | 0.43 | 2 | 5.0 | 1.5 | 1 |
| FR-004 | 0.50 | 2 | 4.5 | 1.0 | 1 |
| FR-010 | 0.50 | 2 | 6.0 | 1.0 | 2 |
| FR-012 | 0.50 | 2 | 4.5 | 1.0 | 1 |
| FR-019 | 0.50 | 2 | 4.5 | 1.0 | 2 |
| FR-028 | 0.50 | 2 | 4.5 | 1.0 | 1 |
| FR-037 | 0.50 | 2 | 4.5 | 1.0 | 1 |
| FR-042 | 0.50 | 2 | 3.0 | 0.5 | 1 |
| FR-043 | 0.50 | 2 | 3.0 | 1.0 | 1 |
| FR-013 | 0.56 | 2 | 7.0 | 1.0 | 2 |
| FR-039 | 0.57 | 2 | 5.5 | 1.5 | 1 |
| AC-014 | 0.60 | 2 | 4.0 | 1.0 | 0 |
| AC-020 | 0.60 | 2 | 4.0 | 1.0 | 1 |
| FR-007 | 0.60 | 2 | 4.0 | 1.0 | 0 |
| FR-011 | 0.60 | 2 | 4.0 | 1.0 | 0 |
| FR-017 | 0.60 | 2 | 4.0 | 1.0 | 1 |
| FR-026 | 0.71 | 2 | 6.0 | 2.0 | 0 |
| AC-019 | 0.75 | 2 | 3.5 | 1.0 | 0 |
| FR-001 | 1.00 | 2 | 3.0 | 1.0 | 0 |
| FR-005 | 1.00 | 2 | 3.0 | 1.0 | 0 |
| FR-006 | 1.00 | 2 | 3.0 | 1.0 | 0 |
| FR-014 | 1.00 | 2 | 4.0 | 1.0 | 0 |
| FR-020 | 1.00 | 2 | 4.0 | 1.0 | 0 |
| FR-021 | 1.00 | 2 | 4.0 | 1.0 | 0 |
| FR-022 | 1.00 | 2 | 2.0 | 1.0 | 0 |
| FR-027 | 1.00 | 2 | 2.0 | 1.0 | 0 |
| FR-031 | 1.00 | 2 | 2.0 | 1.0 | 0 |
| FR-033 | 1.00 | 2 | 3.0 | 1.0 | 0 |
| FR-035 | 1.00 | 2 | 4.0 | 0.5 | 0 |
| FR-041 | 1.00 | 2 | 4.0 | 0.5 | 0 |
| FR-045 | 1.00 | 2 | 5.0 | 1.0 | 0 |
| NFR-001 | 1.00 | 2 | 2.0 | 1.5 | 0 |
| NFR-003 | 1.00 | 2 | 2.0 | 1.0 | 0 |
| NFR-004 | 1.00 | 2 | 2.0 | 1.5 | 0 |
| REQ-017 | 1.00 | 1 | 0.0 | 1.0 | 0 |
| REQ-019 | 1.00 | 1 | 0.0 | 1.0 | 0 |
| REQ-028 | 1.00 | 1 | 0.0 | 1.0 | 0 |

## Divergence witness candidates (heuristic — behavioural verification is v4)

None — no materially divergent grounded then-clauses found.

## Fracture lines (attributed, not verified — v3.1 adds counterfactual check)

- **AC-001:**
  - (9×) > line 25: - **AC-001**: Given a readable specification with an available model command, when the operator runs the challenge script, then exactly 2 model calls occur (FR-008), the challenge report is written into the specification's directory (FR-034), with exit code 0.
- **AC-002:**
  - (10×) > line 26: - **AC-002**: Given a completed challenge run, when the operator opens the challenge report, then the report header states exactly 4 facts: the specification path, the run date, the question count, plus the finding count (FR-036, AC-001).
- **AC-003:**
  - (6×) > line 27: - **AC-003**: Given a challenge report exists from a previous run, when the operator reruns the challenge script, then exactly 1 report file remains (FR-034, AC-002), holding only the new run's content.
- **AC-004:**
  - (6×) > line 28: - **AC-004**: Given round 2 returned mixed verdicts, when the report is assembled, then the findings section holds exactly 2 verdict classes — CONTRADICTED plus UNANSWERABLE (FR-032) — ordered per the ranking rule FR-033.
- **AC-005:**
  - (6×) > line 29: - **AC-005**: Given a run completes with at least 1 finding, when the run finishes, then the terminal summary states the finding count per verdict class, listing the top 3 findings in rank order (FR-040, AC-001).
- **AC-006:**
  - (6×) > line 30: - **AC-006**: Given round 1 returns a valid empty question list, when the run continues, then round 2 is skipped (FR-020), the report records exactly 0 questions with 0 findings (FR-036), with exit code 0.
- **AC-007:**
  - (7×) > line 31: - **AC-007**: Given every round-2 verdict is ANSWERED, when the report is assembled, then the findings section states that exactly 0 findings were produced (FR-041), with the audit appendix holding every question (FR-038), with exit code 0.
- **AC-008:**
  - (9×) > line 45: - **AC-008**: Given a question received an ANSWERED verdict, when the report is rendered, then that question appears in the audit appendix with its quoted answering lines, inside exactly 1 collapsed section the reader can expand (FR-038, FR-032).
- **AC-009:**
  - (3×) > line 46: - **AC-009**: Given a round-2 answer cites evidence line numbers, when the report renders that answer, then the report quotes exactly 1 line of text per cited number, as read from the specification file (FR-039, FR-018).
- **AC-010:**
  - (4×) > line 47: - **AC-010**: Given any challenge run, when the run finishes with any exit code, then the challenged specification file received exactly 0 writes, leaving its content unchanged (FR-042, FR-001).
- **AC-011:**
  - (5×) > line 48: - **AC-011**: Given a stub model command that records its prompt, when round 2 executes, then the recorded prompt holds exactly 2 content blocks — specification text plus question identifiers with texts (FR-021) — with exactly 0 round-1 categories, targets, line tags, or reasoning (FR-022).
- **AC-012:**
  - (6×) > line 49: - **AC-012**: Given a stub model command that records its working directory, when either round executes, then the recorded directory is exactly 1 newly created temporary directory under the platform's default temporary root, distinct from the specification's directory and from the invoking working directory (FR-010, AC-011).
- **AC-013:**
  - (4×) > line 63: - **AC-013**: Given a specification path that does not exist or cannot be read, when the operator runs the challenge script, then the exit code is 1 with exactly 0 model calls launched (FR-005, ERR-001).
- **AC-015:**
  - (4×) > line 65: - **AC-015**: Given a round's output fails validation on both the initial call plus the corrective retry, when the second failure occurs, then the exit code is 3, the raw output is saved into the debug dump directory (FR-030, ERR-004), with 0 reports written.
- **AC-016:**
  - (3×) > line 66: - **AC-016**: Given a round's first output is invalid while its retry output is valid, when the run continues, then exactly 2 subprocess invocations occurred for that round (FR-028, FR-013), with the run completing at exit code 0.
- **AC-017:**
  - (10×) > line 67: - **AC-017**: Given a model call exceeds its timeout budget of at most 300 seconds by default, when the timeout expires, then the call is classified as a parse failure (FR-011): exactly 1 retry is issued, with a second failure ending the run at exit code 3 (FR-030).
- **AC-018:**
  - (6×) > line 68: - **AC-018**: Given round-2 answers with a missing, duplicate, or unknown question identifier, when validation runs, then the output is classified as a parse failure (FR-025) consuming exactly 1 corrective retry per FR-028.
- **AC-021:**
  - (7×) > line 84: - **AC-021**: Given a stub executable configured as the model command, when a full challenge run executes, then the run completes end-to-end (FR-043, FR-003) using exactly 0 live model calls.
- **AC-022:**
  - (6×) > line 85: - **AC-022**: Given the repository's automated test suite, when the challenge script's unit tests run, then all tests pass with exactly 0 network calls plus exactly 0 live model commands installed (FR-044, SC-002).
- **AC-023:**
  - (4×) > line 86: - **AC-023**: Given exactly 1 manual live acceptance run against the designated acceptance target (`specs/029-builder-spec-workbench/spec.md`), when the run completes, then a report exists whose findings overlap at least 1 of the 3 named known issues — (1) the REQ-009 "time order" vs AC-010 "most recent first" ordering conflict, (2) the REQ-017/REQ-019/REQ-028 quality-score recording loop, (3) the undefined active-run pointer of REQ-002 — within at most 3 total attempts (SC-001, FR-034).
- **ERR-001:**
  - (5×) > line 234: - **ERR-001**: When the specification path is missing or unreadable, the challenge script rejects the run with exit code 1, launching exactly 0 model calls (FR-005, AC-013).
- **ERR-002:**
  - (5×) > line 235: - **ERR-002**: When the specification's directory is not writable, the challenge script rejects the run with exit code 1, launching exactly 0 model calls (FR-006, AC-019).
- **ERR-003:**
  - (5×) > line 236: - **ERR-003**: When the model-command executable is not found, the challenge script rejects the run with exit code 2, printing exactly 1 installation pointer (FR-012, AC-014).
- **ERR-004:**
  - (7×) > line 237: - **ERR-004**: When model output stays unusable after exactly 1 corrective retry in either round, the challenge script aborts with exit code 3, saving the raw output to the debug dump directory (FR-030, AC-015).
- **ERR-005:**
  - (5×) > line 238: - **ERR-005**: When a model call exceeds its timeout, the challenge script recovers through the parse-failure path: exactly 1 retry, then exit code 3 on a second failure (FR-011, AC-017).
- **FR-002:**
  - (5×) > line 113: - **FR-002**: When invoked, the challenge script MUST accept a question-count option, defaulting to exactly 15, that caps round-1 questions (FR-015, FR-019). Non-numeric, non-integer, and below-1 values MUST be rejected on the exit-code-1 argument path, mirroring FR-004. No upper bound is enforced: the requested maximum passes to the round-1 instruction as-is, and the effective question count is bounded by the model's returned output, to which FR-019 truncation and NFR-001's local-processing allowance apply.
- **FR-003:**
  - (3×) > line 115: - **FR-003**: When invoked, the challenge script MUST accept a model-command option, defaulting to `claude`, that names exactly 1 challenge model command line (FR-007, FR-043).
- **FR-008:**
  - (7×) > line 130: - **FR-008**: When a challenge run executes, the challenge script MUST perform exactly 2 logical model calls: round-1 question generation (FR-014) plus round-2 answering (FR-021) — except exactly 1 when valid round-1 output contains 0 questions, in which case FR-020 governs and round 2 never launches.
- **FR-009:**
  - (4×) > line 132: - **FR-009**: When filtering, ranking, or rendering after round 2, the challenge script MUST perform exactly 0 further model calls (FR-032, FR-040).
- **FR-015:**
  - (3×) > line 149: - **FR-015**: The round-1 instruction MUST request at most N Socratic challenge questions, where N is the FR-002 value, targeting exactly 5 weakness categories: ambiguity, hidden assumption, contradiction, undefined term, missing boundary (FR-016).
- **FR-016:**
  - (12×) > line 151: - **FR-016**: When round-1 output is received, the challenge script MUST validate that each question carries exactly 1 unique identifier, exactly 1 question text, exactly 1 target — a requirement identifier or `general` — a list of integer line references, plus exactly 1 category from FR-015 (FR-017). Round-1 line references are accepted as any integers, are not range-checked, and carry no downstream normative role in v1 (they are stripped from the round-2 prompt and never rendered); they are retained in the schema for later tiers.
- **FR-018:**
  - (4×) > line 155: - **FR-018**: When embedding the specification in either prompt, the challenge script MUST prefix every line with its line number, starting at exactly 1, making each cited reference checkable per FR-039 (FR-014, FR-021).
- **FR-023:**
  - (5×) > line 170: - **FR-023**: The round-2 instruction MUST direct the model to answer each question using only the specification text, assigning exactly 1 verdict per question from the 3-value set ANSWERED, UNANSWERABLE, CONTRADICTED (FR-024, FR-032).
- **FR-024:**
  - (7×) > line 172: - **FR-024**: When round-2 output is received, the challenge script MUST validate that each answer carries exactly 1 question identifier, exactly 1 verdict from FR-023, exactly 1 answer text, plus a list of integer evidence line references (FR-025).
- **FR-025:**
  - (4×) > line 174: - **FR-025**: If the round-2 answer identifiers are not exactly a bijection of the kept round-1 question identifiers — any kept identifier appearing 0 times or more than 1 time, or any answer carrying an identifier outside the kept set — the challenge script MUST classify the output as a parse failure routed to FR-028 (AC-018, FR-019).
- **FR-029:**
  - (5×) > line 187: - **FR-029**: When the first failure in a round was a timeout (FR-011), the corrective retry MUST re-issue the same prompt with exactly 0 appended corrective text (FR-028).
- **FR-030:**
  - (12×) > line 189: - **FR-030**: On the second parse failure in the same round, the challenge script MUST exit with code 3 after saving the raw output of the failing calls into exactly 1 directory named `.sue-debug` beside the specification (ERR-004, AC-015). For a timed-out call, the saved raw output is whatever partial output was drained within the shutdown grace period of exactly 5 seconds (subprocess ended by process-group kill; the up-to-4 grace periods are counted inside NFR-001's +60-second allowance), possibly empty. The debug dump itself is best-effort: if it cannot be written, the exit-3 outcome stands and its single diagnostic line names the failed dump (governs over ERR-004's save wording). Dump lifecycle: both failing attempts of the round are saved as separate files (`round{N}-attempt{1,2}-stdout/stderr`); successive failing runs overwrite files of the same names and the directory is never cleared by the script.
- **FR-032:**
  - (6×) > line 198: - **FR-032**: When all answers are validated, the challenge script MUST partition them into exactly 2 groups: findings holding verdicts CONTRADICTED plus UNANSWERABLE (FR-033), audit entries holding verdict ANSWERED (FR-038).
- **FR-034:**
  - (8×) > line 202: - **FR-034**: When a run succeeds, the challenge script MUST write exactly 1 report file named `socratic-challenge.md` in the specification's directory, replacing any previous report while keeping 0 historical copies (FR-035, AC-003). If the report path resolves to the challenged specification file itself, the run MUST reject with exit code 1 before any model call — FR-042 takes precedence and the challenged file is never written. If writing the report fails after a successful run, the run exits with code 1.
- **FR-036:**
  - (6×) > line 206: - **FR-036**: The report header MUST state exactly 5 base facts — specification path, run date, resolved model provider, question count, finding count — plus the FR-019 truncation note when truncation occurred (AC-002). The run date is the ISO calendar date `YYYY-MM-DD` in the operator's local timezone, rendered as the single `**Run date:**` header bullet; NFR-004's byte-identical comparison excludes exactly that line. The provider fact keeps environment-resolved runs auditable (runtime provider selection, 2026-07-19); it is stable across reruns and participates in NFR-004's comparison.
- **FR-038:**
  - (2×) > line 210: - **FR-038**: The audit appendix MUST list every ANSWERED question with its answering lines, rendered as exactly 1 collapsed section the reader can expand (AC-008, FR-032).
- **FR-040:**
  - (9×) > line 214: - **FR-040**: After writing the report, the challenge script MUST print a terminal summary stating the finding count per verdict class plus the top 3 findings in rank order, then exit with code 0 (AC-005, FR-034). Exit code 0 signals run success only, never the specification's verdict — a deliberate interface boundary recorded under Limitations.
- **FR-044:**
  - (6×) > line 227: - **FR-044**: The deliverable MUST include automated unit tests covering all 7 deterministic behavior groups — argument handling, prompt assembly, extraction, validation with identifier bijection, filtering plus ranking, report rendering, exit codes — runnable with exactly 0 live model access (AC-022, FR-043).
- **NFR-002:**
  - (4×) > line 244: - **NFR-002**: When run from a fresh repository checkout, the challenge script plus its unit tests MUST execute with exactly 0 additional installed components beyond the standard runtime plus the model command itself (FR-044, FR-045). The standard runtime is CPython ≥ 3.11 with its standard library only; the unit tests may additionally import pytest and nothing else.
- **NFR-005:**
  - (5×) > line 250: - **NFR-005**: When exiting with code 1, 2, or 3, the challenge script MUST print exactly 1 diagnostic line to the error stream naming the failure class (ERR-001, ERR-004).
- **REQ-002:**
  - (4×) > line 86: - **AC-023**: Given exactly 1 manual live acceptance run against the designated acceptance target (`specs/029-builder-spec-workbench/spec.md`), when the run completes, then a report exists whose findings overlap at least 1 of the 3 named known issues — (1) the REQ-009 "time order" vs AC-010 "most recent first" ordering conflict, (2) the REQ-017/REQ-019/REQ-028 quality-score recording loop, (3) the undefined active-run pointer of REQ-002 — within at most 3 total attempts (SC-001, FR-034).
- **REQ-009:**
  - (4×) > line 86: - **AC-023**: Given exactly 1 manual live acceptance run against the designated acceptance target (`specs/029-builder-spec-workbench/spec.md`), when the run completes, then a report exists whose findings overlap at least 1 of the 3 named known issues — (1) the REQ-009 "time order" vs AC-010 "most recent first" ordering conflict, (2) the REQ-017/REQ-019/REQ-028 quality-score recording loop, (3) the undefined active-run pointer of REQ-002 — within at most 3 total attempts (SC-001, FR-034).


## Cross-pass stability (2 passes — trustworthy scores)

- **SR mean:** 0.453 ± 0.008 (across passes: [0.4448, 0.4609])
- **Extraction-noise floor:** 0.143 (mean per-requirement score wobble between identical runs — differences below this are noise, not signal)
- **Stable-low requirements (34):** AC-001, AC-002, AC-003, AC-004, AC-008, AC-010, AC-011, AC-012, AC-013, AC-015, AC-016, AC-017, AC-021, AC-022, AC-023, ERR-001, ERR-002, ERR-003, ERR-004, FR-002, FR-003, FR-008, FR-009, FR-016, FR-024, FR-025, FR-029, FR-030, FR-032, FR-034, FR-040, NFR-002, REQ-002, REQ-009 — low in EVERY pass; the real fracture set

| Requirement | mean | ±stdev | min–max | stable-low |
|---|---|---|---|---|
| REQ-009 | 0.07 | 0.07 | 0.00–0.13 | ✓ |
| AC-021 | 0.08 | 0.08 | 0.00–0.17 | ✓ |
| AC-022 | 0.10 | 0.04 | 0.06–0.14 | ✓ |
| AC-001 | 0.11 | 0.01 | 0.10–0.12 | ✓ |
| REQ-002 | 0.11 | 0.11 | 0.00–0.22 | ✓ |
| FR-040 | 0.13 | 0.13 | 0.00–0.26 | ✓ |
| AC-003 | 0.15 | 0.01 | 0.14–0.17 | ✓ |
| FR-008 | 0.16 | 0.03 | 0.12–0.19 | ✓ |
| AC-010 | 0.17 | 0.17 | 0.00–0.33 | ✓ |
| FR-009 | 0.17 | 0.17 | 0.00–0.33 | ✓ |
| FR-029 | 0.17 | 0.17 | 0.00–0.33 | ✓ |
| AC-008 | 0.17 | 0.07 | 0.10–0.25 | ✓ |
| AC-002 | 0.17 | 0.08 | 0.09–0.26 | ✓ |
| FR-016 | 0.18 | 0.07 | 0.10–0.25 | ✓ |
| FR-024 | 0.19 | 0.11 | 0.07–0.30 | ✓ |
| FR-025 | 0.19 | 0.14 | 0.05–0.33 | ✓ |
| AC-013 | 0.19 | 0.14 | 0.06–0.33 | ✓ |
| AC-017 | 0.21 | 0.21 | 0.00–0.43 | ✓ |
| FR-032 | 0.21 | 0.04 | 0.18–0.25 | ✓ |
| ERR-004 | 0.23 | 0.23 | 0.00–0.47 | ✓ |
| FR-034 | 0.24 | 0.03 | 0.21–0.27 | ✓ |
| AC-012 | 0.25 | 0.00 | 0.25–0.25 | ✓ |
| FR-003 | 0.26 | 0.14 | 0.12–0.40 | ✓ |
| FR-030 | 0.29 | 0.00 | 0.29–0.29 | ✓ |
| ERR-001 | 0.31 | 0.14 | 0.17–0.44 | ✓ |
| ERR-002 | 0.31 | 0.14 | 0.17–0.44 | ✓ |
| ERR-003 | 0.31 | 0.14 | 0.17–0.44 | ✓ |
| NFR-002 | 0.31 | 0.02 | 0.29–0.33 | ✓ |
| AC-016 | 0.32 | 0.08 | 0.23–0.40 | ✓ |
| AC-023 | 0.32 | 0.11 | 0.21–0.43 | ✓ |
| AC-004 | 0.32 | 0.07 | 0.25–0.39 | ✓ |
| FR-002 | 0.32 | 0.05 | 0.27–0.38 | ✓ |
| AC-014 | 0.32 | 0.28 | 0.04–0.60 |  |
| AC-018 | 0.33 | 0.18 | 0.14–0.51 |  |
| FR-010 | 0.33 | 0.17 | 0.16–0.50 |  |
| FR-044 | 0.34 | 0.20 | 0.14–0.53 |  |
| AC-015 | 0.35 | 0.01 | 0.33–0.36 | ✓ |
| AC-006 | 0.35 | 0.21 | 0.14–0.56 |  |
| FR-023 | 0.38 | 0.22 | 0.17–0.60 |  |
| FR-004 | 0.40 | 0.10 | 0.30–0.50 |  |
| ERR-005 | 0.40 | 0.12 | 0.29–0.52 |  |
| AC-019 | 0.41 | 0.34 | 0.07–0.75 |  |
| FR-038 | 0.42 | 0.08 | 0.33–0.50 |  |
| FR-018 | 0.42 | 0.09 | 0.33–0.51 |  |
| AC-011 | 0.42 | 0.05 | 0.38–0.47 | ✓ |
| FR-012 | 0.43 | 0.07 | 0.35–0.50 |  |
| FR-036 | 0.44 | 0.11 | 0.33–0.55 |  |
| FR-028 | 0.45 | 0.05 | 0.40–0.50 |  |
| FR-039 | 0.47 | 0.11 | 0.36–0.57 |  |
| FR-007 | 0.48 | 0.12 | 0.36–0.60 |  |
| AC-005 | 0.49 | 0.35 | 0.14–0.83 |  |
| FR-015 | 0.49 | 0.09 | 0.40–0.58 |  |
| NFR-001 | 0.50 | 0.50 | 0.00–1.00 |  |
| NFR-005 | 0.50 | 0.50 | 0.00–1.00 |  |
| FR-037 | 0.54 | 0.04 | 0.50–0.58 |  |
| FR-022 | 0.54 | 0.46 | 0.08–1.00 |  |
| FR-042 | 0.55 | 0.05 | 0.50–0.60 |  |
| FR-027 | 0.56 | 0.44 | 0.11–1.00 |  |
| AC-007 | 0.56 | 0.44 | 0.12–1.00 |  |
| FR-013 | 0.58 | 0.03 | 0.56–0.61 |  |
| FR-019 | 0.58 | 0.08 | 0.50–0.67 |  |
| FR-026 | 0.63 | 0.09 | 0.54–0.71 |  |
| FR-031 | 0.67 | 0.33 | 0.33–1.00 |  |
| REQ-017 | 0.67 | 0.33 | 0.33–1.00 |  |
| REQ-019 | 0.67 | 0.33 | 0.33–1.00 |  |
| REQ-028 | 0.67 | 0.33 | 0.33–1.00 |  |
| AC-020 | 0.67 | 0.07 | 0.60–0.73 |  |
| FR-011 | 0.67 | 0.07 | 0.60–0.73 |  |
| AC-009 | 0.70 | 0.30 | 0.40–1.00 |  |
| FR-043 | 0.75 | 0.25 | 0.50–1.00 |  |
| NFR-003 | 0.78 | 0.22 | 0.56–1.00 |  |
| FR-017 | 0.80 | 0.20 | 0.60–1.00 |  |
| NFR-004 | 0.81 | 0.19 | 0.61–1.00 |  |
| FR-045 | 0.81 | 0.19 | 0.62–1.00 |  |
| FR-001 | 0.83 | 0.17 | 0.67–1.00 |  |
| FR-035 | 0.87 | 0.13 | 0.73–1.00 |  |
| FR-041 | 0.87 | 0.13 | 0.73–1.00 |  |
| FR-005 | 1.00 | 0.00 | 1.00–1.00 |  |
| FR-006 | 1.00 | 0.00 | 1.00–1.00 |  |
| FR-014 | 1.00 | 0.00 | 1.00–1.00 |  |
| FR-020 | 1.00 | 0.00 | 1.00–1.00 |  |
| FR-021 | 1.00 | 0.00 | 1.00–1.00 |  |
| FR-033 | 1.00 | 0.00 | 1.00–1.00 |  |
