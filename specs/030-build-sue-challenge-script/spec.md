---
status: In Progress
---
# Feature Specification: SUE Challenge Script

**Feature Branch**: `030-build-sue-challenge-script`
**Created**: 2026-07-18
**Status**: In Progress
**Input**: User description: "Build the SUE challenge script: a standalone Python script (scripts/sue_challenge.py) that challenges a specification via Socratic question-answer dialogue using two isolated claude -p calls, per the attached approved design document. Implement exactly the v1 scope: interface, JSON schemas, isolation contract, report format, error handling, and pytest unit tests as designed."

> The SUE challenge script interrogates a markdown specification through a two-round Socratic dialogue. Round 1 asks a challenge model to generate probing questions about the specification. Round 2 asks a fresh, isolated reading of the same model to answer each question using only the specification text. Questions the text cannot answer become findings in a report written beside the challenged specification. The mechanism operationalizes the grounding rule: the engine asks, the text testifies, the human decides. This specification implements the approved v1 design exactly: the question-to-answer dialogue tier only.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Challenge a specification and read findings (Priority: P1)

A script operator runs the challenge script against a markdown specification file. The script performs two isolated model calls, deterministically assembles the answers into ranked findings, writes the challenge report beside the challenged specification, and prints a summary so the operator sees the most important gaps immediately.

**Why this priority**: This is the whole product. Without the end-to-end challenge run there is nothing to review, audit, or diagnose.

**Independent Test**: Can be fully tested by running the script against a fixture specification with a stub model command and verifying the report content, ranking, summary, and exit code.

**Acceptance Scenarios**:

- **AC-001**: Given a readable specification with an available model command, when the operator runs the challenge script, then exactly 2 model calls occur (FR-008), the challenge report is written into the specification's directory (FR-034), with exit code 0.
- **AC-002**: Given a completed challenge run, when the operator opens the challenge report, then the report header states exactly 4 facts: the specification path, the run date, the question count, plus the finding count (FR-036, AC-001).
- **AC-003**: Given a challenge report exists from a previous run, when the operator reruns the challenge script, then exactly 1 report file remains (FR-034, AC-002), holding only the new run's content.
- **AC-004**: Given round 2 returned mixed verdicts, when the report is assembled, then the findings section holds exactly 2 verdict classes — CONTRADICTED plus UNANSWERABLE (FR-032) — ordered per the ranking rule FR-033.
- **AC-005**: Given a run completes with at least 1 finding, when the run finishes, then the terminal summary states the finding count per verdict class, listing the top 3 findings in rank order (FR-040, AC-001).
- **AC-006**: Given round 1 returns a valid empty question list, when the run continues, then round 2 is skipped (FR-020), the report records exactly 0 questions with 0 findings (FR-036), with exit code 0.
- **AC-007**: Given every round-2 verdict is ANSWERED, when the report is assembled, then the findings section states that exactly 0 findings were produced (FR-041), with the audit appendix holding every question (FR-038), with exit code 0.

---

### User Story 2 - Trust and audit the verdicts (Priority: P2)

A specification author receives a challenge report about their specification. They need every finding to be grounded in their actual text, and they need to review the filtering itself: which questions the specification answered, and where.

**Why this priority**: Findings are advisory; humans decide. If the evidence is not verifiable against the real text, the report has no authority and the grounding rule is violated.

**Independent Test**: Can be fully tested with a prompt-recording and directory-recording stub command plus canned round-2 answers, verifying report quotations against a fixture specification.

**Acceptance Scenarios**:

- **AC-008**: Given a question received an ANSWERED verdict, when the report is rendered, then that question appears in the audit appendix with its quoted answering lines, inside exactly 1 collapsed section the reader can expand (FR-038, FR-032).
- **AC-009**: Given a round-2 answer cites evidence line numbers, when the report renders that answer, then the report quotes exactly 1 line of text per cited number, as read from the specification file (FR-039, FR-018).
- **AC-010**: Given any challenge run, when the run finishes with any exit code, then the challenged specification file received exactly 0 writes, leaving its content unchanged (FR-042, FR-001).
- **AC-011**: Given a stub model command that records its prompt, when round 2 executes, then the recorded prompt holds exactly 2 content blocks — specification text plus question identifiers with texts (FR-021) — with exactly 0 round-1 categories, targets, line tags, or reasoning (FR-022).
- **AC-012**: Given a stub model command that records its working directory, when either round executes, then the recorded directory is exactly 1 newly created temporary directory outside the repository (FR-010, AC-011).

---

### User Story 3 - Diagnose a failed run (Priority: P3)

A script operator hits a failure: a bad path, a missing model command, unusable model output, or a hung call. They need a distinct exit code and an actionable message for each failure class, and raw material to diagnose unrecoverable parse failures offline.

**Why this priority**: The tool drives an external model command it does not control. Predictable failure behavior is what makes the tool usable beyond its author's machine, but it only matters once the happy path and the grounding guarantees exist.

**Independent Test**: Every failure class can be triggered with fixture paths and stub commands that replay malformed output, sleep past the timeout, or are absent from the lookup path.

**Acceptance Scenarios**:

- **AC-013**: Given a specification path that does not exist or cannot be read, when the operator runs the challenge script, then the exit code is 1 with exactly 0 model calls launched (FR-005, ERR-001).
- **AC-014**: Given the model command's executable cannot be found, when the operator runs the challenge script, then the exit code is 2, the message includes exactly 1 installation pointer (FR-012, ERR-003), with 0 reports written.
- **AC-015**: Given a round's output fails validation on both the initial call plus the corrective retry, when the second failure occurs, then the exit code is 3, the raw output is saved into the debug dump directory (FR-030, ERR-004), with 0 reports written.
- **AC-016**: Given a round's first output is invalid while its retry output is valid, when the run continues, then exactly 2 subprocess invocations occurred for that round (FR-028, FR-013), with the run completing at exit code 0.
- **AC-017**: Given a model call exceeds its timeout budget of at most 300 seconds by default, when the timeout expires, then the call is classified as a parse failure (FR-011): exactly 1 retry is issued, with a second failure ending the run at exit code 3 (FR-030).
- **AC-018**: Given round-2 answers with a missing, duplicate, or unknown question identifier, when validation runs, then the output is classified as a parse failure (FR-025) consuming exactly 1 corrective retry per FR-028.
- **AC-019**: Given the specification's directory is not writable, when the operator runs the challenge script, then the exit code is 1 with exactly 0 model calls launched (FR-006, ERR-002).
- **AC-020**: Given valid round-1 output holding more than N questions, when validation runs, then exactly N questions remain — the first N in returned order (FR-019) — with the report header carrying 1 truncation note (FR-036).

---

### User Story 4 - Verify the tool without a live model (Priority: P4)

A developer maintaining the challenge script runs its automated unit tests. The tests exercise every deterministic behavior — argument handling, extraction, validation, filtering, ranking, rendering, exit codes — by substituting the model command with a stub executable that replays canned output.

**Why this priority**: The test seam is what keeps the tool maintainable and its deterministic core verifiable, but it serves the behaviors defined by the first three stories.

**Independent Test**: AC-021 and AC-022 run entirely offline; AC-023 is the single manual live validation of v1.

**Acceptance Scenarios**:

- **AC-021**: Given a stub executable configured as the model command, when a full challenge run executes, then the run completes end-to-end (FR-043, FR-003) using exactly 0 live model calls.
- **AC-022**: Given the repository's automated test suite, when the challenge script's unit tests run, then all tests pass with exactly 0 network calls plus exactly 0 live model commands installed (FR-044, SC-002).
- **AC-023**: Given exactly 1 manual live acceptance run against the designated acceptance target (`specs/029-builder-spec-workbench/spec.md`), when the run completes, then a report exists whose findings overlap at least 1 of the 3 named known issues — (1) the REQ-009 "time order" vs AC-010 "most recent first" ordering conflict, (2) the REQ-017/REQ-019/REQ-028 quality-score recording loop, (3) the undefined active-run pointer of REQ-002 — within at most 3 total attempts (SC-001, FR-034).

---

### Edge Cases

- Round 1 returns a syntactically valid empty question list → success with a zero-question report (AC-006, FR-020), not a failure.
- Every question is ANSWERED → success with an explicit "0 findings" report (AC-007, FR-041): the clean-specification outcome.
- Round 1 returns more questions than the configured maximum → deterministic truncation with a report note (AC-020, FR-019).
- Round 1 returns duplicate question identifiers → validation failure, corrective retry path (FR-017).
- Model output arrives wrapped in code fences or surrounded by noise → extraction tolerates the wrapper (FR-026); validation of the extracted object stays strict (FR-024).
- A model call hangs → the per-call timeout converts it to the parse-failure path (AC-017, FR-011).
- The specification's directory is read-only → detected before any model call, exit code 1 (AC-019, FR-006).
- The challenged specification contains adversarial instructions aimed at steering verdicts → outside the tool's control; documented limitation, the human reviewer is the backstop (see Limitations).
- Two challenge runs execute concurrently against the same specification directory → unsupported; explicit non-goal for v1 (see Out of Scope).
- The challenged specification is too large for the model's context window → not guarded in v1; documented limitation observed during acceptance (A-005).

## Requirements *(mandatory)*

### Functional Requirements

#### Command Interface & Input Validation

The command surface is fixed by the approved design: 1 positional argument, 3 options, 4 exit codes. Input problems are rejected before any model call so a failed pre-flight costs nothing.

- **FR-001**: When invoked, the challenge script MUST accept exactly 1 positional argument: the path of the specification file to challenge (FR-005, FR-042).
  - **User Story:** Scenario 1 | **Priority:** MVP
- **FR-002**: When invoked, the challenge script MUST accept a question-count option, defaulting to exactly 15, that caps round-1 questions (FR-015, FR-019). Values below 1 MUST be rejected on the exit-code-1 argument path.
  - **User Story:** Scenario 1 | **Priority:** MVP
- **FR-003**: When invoked, the challenge script MUST accept a model-command option, defaulting to `claude`, that names exactly 1 challenge model command line (FR-007, FR-043).
  - **User Story:** Scenario 4 | **Priority:** MVP
- **FR-004**: When invoked, the challenge script MUST accept a timeout option, defaulting to exactly 300 seconds, that bounds each model call (FR-011, FR-013). Non-numeric, non-finite, zero, or negative values MUST be rejected on the exit-code-1 argument path.
  - **User Story:** Scenario 3 | **Priority:** MVP
- **FR-005**: If the specification path is missing or unreadable, the challenge script MUST exit with code 1 after launching exactly 0 model calls (ERR-001, AC-013).
  - **User Story:** Scenario 3 | **Priority:** MVP
- **FR-006**: If the specification's directory is not writable for the report, the challenge script MUST exit with code 1 after launching exactly 0 model calls (ERR-002, AC-019).
  - **User Story:** Scenario 3 | **Priority:** MVP
- **FR-007**: When parsing the model-command option, the challenge script MUST split the value into words per POSIX shell quoting conventions (`shlex` semantics, platform-independent), treating exactly 1 leading word as the executable checked by FR-012 (FR-003).
  - **User Story:** Scenario 4 | **Priority:** MVP

#### Model Invocation & Isolation

Two isolated model calls are the entire analytical mechanism. Isolation keeps the reading blind: no repository context, no carried-over reasoning.

- **FR-008**: When a challenge run executes, the challenge script MUST perform exactly 2 logical model calls: round-1 question generation (FR-014) plus round-2 answering (FR-021).
  - **User Story:** Scenario 1 | **Priority:** MVP
- **FR-009**: When filtering, ranking, or rendering after round 2, the challenge script MUST perform exactly 0 further model calls (FR-032, FR-040).
  - **User Story:** Scenario 1 | **Priority:** MVP
- **FR-010**: When launching any model subprocess, the challenge script MUST set the subprocess working directory to exactly 1 newly created neutral temporary directory, keeping repository-level ambient context away from the model (AC-012, OQ-002). Each model subprocess receives its own newly created directory, deleted on a best-effort basis when the call completes.
  - **User Story:** Scenario 2 | **Priority:** MVP
- **FR-011**: If a model subprocess exceeds its timeout budget (default 300 seconds, FR-004), the challenge script MUST end that call, classifying it as a parse failure routed to FR-028 (ERR-005).
  - **User Story:** Scenario 3 | **Priority:** MVP
- **FR-012**: If the model-command executable named by FR-007 cannot be found, the challenge script MUST exit with code 2, printing exactly 1 message that contains an installation pointer (ERR-003, AC-014).
  - **User Story:** Scenario 3 | **Priority:** MVP
- **FR-013**: When a corrective retry launches under FR-028, the challenge script MUST grant that retry exactly 1 fresh timeout budget equal to the FR-004 value (NFR-001).
  - **User Story:** Scenario 3 | **Priority:** MVP

#### Round 1 — Question Generation

Round 1 turns the specification into at most N Socratic challenge questions. Its output is untrusted and is validated strictly before use.

- **FR-014**: When building the round-1 prompt, the challenge script MUST include exactly 2 elements: the full line-numbered specification text (FR-018) plus the question-generation instruction of FR-015.
  - **User Story:** Scenario 1 | **Priority:** MVP
- **FR-015**: The round-1 instruction MUST request at most N Socratic challenge questions, where N is the FR-002 value, targeting exactly 5 weakness categories: ambiguity, hidden assumption, contradiction, undefined term, missing boundary (FR-016).
  - **User Story:** Scenario 1 | **Priority:** MVP
- **FR-016**: When round-1 output is received, the challenge script MUST validate that each question carries exactly 1 unique identifier, exactly 1 question text, exactly 1 target — a requirement identifier or `general` — a list of integer line references, plus exactly 1 category from FR-015 (FR-017).
  - **User Story:** Scenario 1 | **Priority:** MVP
- **FR-017**: If round-1 validation fails, including on duplicate question identifiers, the challenge script MUST classify the output as a parse failure consuming 1 of the round's 2 permitted attempts (FR-016, FR-028).
  - **User Story:** Scenario 3 | **Priority:** MVP
- **FR-018**: When embedding the specification in either prompt, the challenge script MUST prefix every line with its line number, starting at exactly 1, making each cited reference checkable per FR-039 (FR-014, FR-021).
  - **User Story:** Scenario 2 | **Priority:** MVP
- **FR-019**: If valid round-1 output contains more than N questions (FR-002, default 15), the challenge script MUST keep only the first N questions in returned order, recording a truncation note in the report header (FR-036). The kept N questions define both the round-2 prompt and the FR-025 identifier set.
  - **User Story:** Scenario 3 | **Priority:** MVP
- **FR-020**: If valid round-1 output contains exactly 0 questions, the challenge script MUST complete the run without round 2, producing a report that records 0 questions (FR-036) plus exit code 0 (AC-006).
  - **User Story:** Scenario 1 | **Priority:** MVP

#### Round 2 — The Socratic Test

Round 2 is a blind reader: a fresh call that sees only the specification text and the bare questions, and testifies from the text alone.

- **FR-021**: When building the round-2 prompt, the challenge script MUST include exactly 2 content blocks: the line-numbered specification text (FR-018) plus the round-1 question identifiers with their question texts (FR-022).
  - **User Story:** Scenario 2 | **Priority:** MVP
- **FR-022**: The round-2 prompt MUST NOT contain round-1 categories, targets, line references, or round-1 reasoning — exactly 0 of these 4 elements may appear (FR-021, AC-011).
  - **User Story:** Scenario 2 | **Priority:** MVP
- **FR-023**: The round-2 instruction MUST direct the model to answer each question using only the specification text, assigning exactly 1 verdict per question from the 3-value set ANSWERED, UNANSWERABLE, CONTRADICTED (FR-024, FR-032).
  - **User Story:** Scenario 1 | **Priority:** MVP
- **FR-024**: When round-2 output is received, the challenge script MUST validate that each answer carries exactly 1 question identifier, exactly 1 verdict from FR-023, exactly 1 answer text, plus a list of integer evidence line references (FR-025).
  - **User Story:** Scenario 1 | **Priority:** MVP
- **FR-025**: If the round-2 answer identifiers are not exactly a bijection of the kept round-1 question identifiers — any kept identifier appearing 0 times or more than 1 time, or any answer carrying an identifier outside the kept set — the challenge script MUST classify the output as a parse failure routed to FR-028 (AC-018, FR-019).
  - **User Story:** Scenario 3 | **Priority:** MVP

#### Output Extraction & Retry

Model output is untrusted input. Extraction is tolerant; validation is strict; recovery is bounded to exactly 1 retry per round.

- **FR-026**: When raw model output is received, the challenge script MUST extract exactly 1 JSON object from it, tolerating surrounding non-JSON text plus code fences (FR-016, FR-024). When more than 1 candidate object is extractable, the first extractable object wins, in this precedence: whole-output parse, first fenced block, first balanced-brace candidate. A candidate that parses to a non-object JSON value (for example a bare array) is a parse failure at that precedence level, not a fall-through.
  - **User Story:** Scenario 1 | **Priority:** MVP
- **FR-027**: If exactly 0 JSON objects can be extracted from raw model output, the challenge script MUST classify that output as a parse failure routed to FR-028 (FR-026).
  - **User Story:** Scenario 3 | **Priority:** MVP
- **FR-028**: On the first parse failure in a round, the challenge script MUST issue exactly 1 corrective retry: the same prompt plus an appended corrective instruction naming the validation failure, echoing 0 lines of the prior output (FR-013, FR-030).
  - **User Story:** Scenario 3 | **Priority:** MVP
- **FR-029**: When the first failure in a round was a timeout (FR-011), the corrective retry MUST re-issue the same prompt with exactly 0 appended corrective text (FR-028).
  - **User Story:** Scenario 3 | **Priority:** MVP
- **FR-030**: On the second parse failure in the same round, the challenge script MUST exit with code 3 after saving the raw output of the failing calls into exactly 1 directory named `.sue-debug` beside the specification (ERR-004, AC-015). For a timed-out call, the saved raw output is whatever partial output was drained within the shutdown grace period of exactly 5 seconds (subprocess ended by process-group kill; the up-to-4 grace periods are counted inside NFR-001's +60-second allowance), possibly empty. The debug dump itself is best-effort: if it cannot be written, the exit-3 outcome stands and its single diagnostic line names the failed dump (governs over ERR-004's save wording).
  - **User Story:** Scenario 3 | **Priority:** MVP
- **FR-031**: When a round-2 failure ends the run under FR-030, the challenge script MUST NOT re-run round 1 — exactly 0 additional round-1 calls occur (FR-008).
  - **User Story:** Scenario 3 | **Priority:** MVP

#### Deterministic Assembly & Report

Everything after round 2 is pure local computation, repeatable and fully unit-testable (FR-044).

- **FR-032**: When all answers are validated, the challenge script MUST partition them into exactly 2 groups: findings holding verdicts CONTRADICTED plus UNANSWERABLE (FR-033), audit entries holding verdict ANSWERED (FR-038).
  - **User Story:** Scenario 1 | **Priority:** MVP
- **FR-033**: When ranking findings, the challenge script MUST place all CONTRADICTED findings before all UNANSWERABLE findings, preserving round-1 question order within each of the 2 classes (FR-032, AC-004).
  - **User Story:** Scenario 1 | **Priority:** MVP
- **FR-034**: When a run succeeds, the challenge script MUST write exactly 1 report file named `socratic-challenge.md` in the specification's directory, replacing any previous report while keeping 0 historical copies (FR-035, AC-003). If the report path resolves to the challenged specification file itself, the run MUST reject with exit code 1 before any model call — FR-042 takes precedence and the challenged file is never written. If writing the report fails after a successful run, the run exits with code 1.
  - **User Story:** Scenario 1 | **Priority:** MVP
- **FR-035**: The challenge report MUST contain exactly 3 sections in order: header (FR-036), findings (FR-037), audit appendix (FR-038).
  - **User Story:** Scenario 2 | **Priority:** MVP
- **FR-036**: The report header MUST state exactly 4 base facts — specification path, run date, question count, finding count — plus the FR-019 truncation note when truncation occurred (AC-002).
  - **User Story:** Scenario 1 | **Priority:** MVP
- **FR-037**: Each findings entry MUST state exactly 4 elements: the verdict, the question, the target requirement identifier, plus the evidence rendered per FR-039 (FR-033).
  - **User Story:** Scenario 2 | **Priority:** MVP
- **FR-038**: The audit appendix MUST list every ANSWERED question with its answering lines, rendered as exactly 1 collapsed section the reader can expand (AC-008, FR-032).
  - **User Story:** Scenario 2 | **Priority:** MVP
- **FR-039**: For each cited evidence line number, the report MUST quote exactly 1 line of text from the specification file, stating the named gap from the answer text for UNANSWERABLE findings (FR-018, AC-009). A cited line number outside the specification's line range MUST render as a deterministic `(not present in the specification)` marker rather than failing the run.
  - **User Story:** Scenario 2 | **Priority:** MVP
- **FR-040**: After writing the report, the challenge script MUST print a terminal summary stating the finding count per verdict class plus the top 3 findings in rank order, then exit with code 0 (AC-005, FR-034).
  - **User Story:** Scenario 1 | **Priority:** MVP
- **FR-041**: When every verdict is ANSWERED, the report's findings section MUST state that exactly 0 findings were produced, with the audit appendix holding all questions plus exit code 0 (AC-007, FR-038).
  - **User Story:** Scenario 1 | **Priority:** MVP
- **FR-042**: Across every outcome, the challenge script MUST NOT modify the challenged specification file — exactly 0 writes to it occur (AC-010, FR-001).
  - **User Story:** Scenario 2 | **Priority:** MVP

#### Standalone Operation & Test Seam

The model-command option doubles as the test seam, and the script stays free of any orchestration coupling so its interface remains stable for later SUE tiers.

- **FR-043**: When the model-command option names any operator-supplied command line, the challenge script MUST execute that command in place of the default, enabling stubbed runs with exactly 0 live model calls (AC-021, FR-003).
  - **User Story:** Scenario 4 | **Priority:** MVP
- **FR-044**: The deliverable MUST include automated unit tests covering all 7 deterministic behavior groups — argument handling, prompt assembly, extraction, validation with identifier bijection, filtering plus ranking, report rendering, exit codes — runnable with exactly 0 live model access (AC-022, FR-043).
  - **User Story:** Scenario 4 | **Priority:** MVP
- **FR-045**: When executing, the challenge script MUST read exactly 2 kinds of input — its command-line arguments plus the challenged specification file — reading 0 project orchestration configuration or state files (FR-001, FR-003).
  - **User Story:** Scenario 4 | **Priority:** MVP

### Error Handling Summary

- **ERR-001**: When the specification path is missing or unreadable, the challenge script rejects the run with exit code 1, launching exactly 0 model calls (FR-005, AC-013).
- **ERR-002**: When the specification's directory is not writable, the challenge script rejects the run with exit code 1, launching exactly 0 model calls (FR-006, AC-019).
- **ERR-003**: When the model-command executable is not found, the challenge script rejects the run with exit code 2, printing exactly 1 installation pointer (FR-012, AC-014).
- **ERR-004**: When model output stays unusable after exactly 1 corrective retry in either round, the challenge script aborts with exit code 3, saving the raw output to the debug dump directory (FR-030, AC-015).
- **ERR-005**: When a model call exceeds its timeout, the challenge script recovers through the parse-failure path: exactly 1 retry, then exit code 3 on a second failure (FR-011, AC-017).

### Non-Functional Requirements

- **NFR-001**: When a challenge run terminates on any path, its wall-clock duration MUST be at most 4 timeout budgets (FR-004, FR-013) plus 60 seconds of local processing.
  - **Category:** Reliability | **Measurable Target:** wall-clock ≤ (4 × configured timeout) + 60 seconds on every terminating path
- **NFR-002**: When run from a fresh repository checkout, the challenge script plus its unit tests MUST execute with exactly 0 additional installed components beyond the standard runtime plus the model command itself (FR-044, FR-045).
  - **Category:** Portability | **Measurable Target:** 0 additional installations on a fresh checkout (model command excluded)
- **NFR-003**: The script's usage text MUST contain exactly 1 disclosure stating that challenged specification content is sent to the model provider via the model command (FR-003, FR-043).
  - **Category:** Privacy | **Measurable Target:** 1 egress disclosure statement present in the usage text
- **NFR-004**: When identical validated answers are assembled twice, the challenge script MUST produce 2 report bodies identical outside the run-date field (FR-032, FR-036).
  - **Category:** Reliability | **Measurable Target:** byte-identical report bodies across 2 assembly passes, run-date field excluded
- **NFR-005**: When exiting with code 1, 2, or 3, the challenge script MUST print exactly 1 diagnostic line to the error stream naming the failure class (ERR-001, ERR-004).
  - **Category:** Usability | **Measurable Target:** exactly 1 identifying diagnostic line per non-zero exit

### Key Entities

- **Challenge Run**: One end-to-end execution against a single challenged specification. Attributes: specification path, maximum question count, challenge model command, per-call timeout, exit code, run date. Performs 2 logical model calls (2–4 subprocess invocations including retries); produces exactly 1 challenge report on success or 1 debug dump on unrecoverable parse failure.
- **Challenged Specification**: The markdown file under interrogation. Read once; its line-numbered text is the sole evidence source for both rounds; never modified; its directory receives the report and the debug dump.
- **Socratic Question**: A round-1 output unit: identifier, question text, target (requirement identifier or `general`), line references, and 1 of 5 categories. Matched by exactly 1 Answer.
- **Answer**: A round-2 output unit: question identifier, verdict (ANSWERED, UNANSWERABLE, or CONTRADICTED), answer text, evidence line references. Exactly 1 per question (identifier bijection, FR-025).
- **Finding**: An Answer whose verdict is CONTRADICTED or UNANSWERABLE, plus its rank (FR-033). The report's payload; top 3 echoed to the terminal summary.
- **Challenge Report**: The markdown artifact `socratic-challenge.md` beside the challenged specification: header, findings section, collapsed audit appendix (FR-035). Overwritten on rerun; regenerable, never a record.
- **Model Call**: One isolated subprocess invocation of the challenge model command from a neutral temporary working directory (FR-010), bounded by the per-call timeout, returning raw output for extraction.
- **Debug Dump**: Raw model output saved under `.sue-debug` in the specification's directory on the unrecoverable parse-failure path only (FR-030).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: When the manual live acceptance run executes against the designated acceptance target, a report is generated whose findings overlap at least 1 of the 3 named known issues, within at most 3 total attempts (AC-023, FR-034).
- **SC-002**: When the challenge script's unit tests run in the repository's test runner, all tests pass with exactly 0 network calls plus exactly 0 live model invocations (FR-044, AC-022).
- **SC-003**: When each failure class is deliberately triggered, it reproduces its assigned exit code — 1, 2, or 3 — plus exactly 1 diagnostic line (NFR-005, ERR-001).
- **SC-004**: When any challenge run terminates, its wall-clock time is at most 4 timeout budgets plus 60 seconds (NFR-001, FR-011).
- **SC-005**: When an operator on a fresh repository checkout runs a stubbed challenge, the run completes with exactly 1 command invocation plus 0 additional installed components (NFR-002, FR-043).

## Scope

### In Scope (MVP)

- The standalone challenge script at `scripts/sue_challenge.py` with the full command interface and pre-flight validation (FR-001 to FR-007).
- Two-round isolated model dialogue with schema validation, identifier bijection, corrective retry, and timeout handling (FR-008 to FR-031).
- Deterministic assembly, the challenge report with collapsed audit appendix, and the terminal summary (FR-032 to FR-042).
- The stub-command test seam and unit tests at `tests/unit/test_sue_challenge.py` (FR-043 to FR-045).
- One manual live acceptance run against `specs/029-builder-spec-workbench/spec.md` (SC-001, AC-023).

### Explicitly Out of Scope

- Multi-reader consensus, interpretation graphs, and convergence scoring — later SUE tiers; the v1 interface (specification path in, markdown report out) is stable under all of them.
- Workflow integration, including any orchestration CLI verb — the script stays a host tool.
- Encoding answers back into challenged specifications — findings are advisory only.
- Report history or versioning — reruns overwrite; the report is regenerable.
- Concurrent-run protection for a shared specification directory — single-operator manual tool.
- Guarding against oversized specifications exceeding the model's context window — observed at acceptance, not guarded (A-005).

## Limitations (stated, not silent)

- **Residual context exposure**: The neutral temporary working directory guarantees that repository-level ambient context cannot reach the model (FR-010). Operator-level ambient configuration outside any working directory may still load; whether it does, and which suppression options exist, is under investigation (OQ-002). Until resolved, this residual exposure is a documented limitation, not a satisfied guarantee.
- **Prompt exposure of challenged text**: The challenged specification is embedded verbatim in both prompts. A specification containing adversarial instructions could steer verdicts; the human reviewer of the report is the backstop (U-009).
- **Data egress**: Challenged specification content leaves the local machine via the challenge model command and inherits the operator's model-session data-handling posture (NFR-003). Do not challenge specifications containing confidential or personal data unless that posture permits it.
- **Operator-trust seam**: The challenge model command option executes an arbitrary operator-supplied command line (FR-043). It is a local developer seam and must never be sourced from configuration files or the network.

## Open Questions

| ID | Question | Impact | Source |
|----|----------|--------|--------|
| OQ-001 | How exactly is the prompt delivered to the model command, and with which output flags? Decides extraction design details and the stub replay contract. | FR-026, FR-028 implementation freeze; stub fixture design | unknowns.md U-001 (should-resolve-before-HOW) |
| OQ-002 | Does a neutral temporary working directory fully satisfy the isolation intent, or does operator-level ambient context still load? | FR-010 limitation wording; possible suppression options | unknowns.md U-002 (should-resolve-before-HOW) |

### Resolved During WHAT (spec decisions)

| Unknown | Decision | Encoded In |
|---------|----------|-----------|
| U-003 retry prompt content | Corrective instruction names the validation failure, prior output not echoed; timeout retry is a plain re-issue | FR-028, FR-029 |
| U-004 model command semantics | Command line split by shell quoting conventions; word 1 is the availability-checked executable | FR-007 |
| U-005 degenerate outcomes | Empty question list → zero-question report, exit 0; all ANSWERED → clean report, exit 0; unwritable directory → pre-flight exit 1 | FR-006, FR-020, FR-041 |
| U-006 line-number provenance | Specification presented with explicit 1-based line numbers; report quotes actual file lines by number | FR-018, FR-039 |
| U-007 exit-2 boundary | Exit 2 only for executable-not-found; every other launch or output failure takes the parse-failure path | FR-012, FR-030 |
| U-008 over-cap and duplicates | Over-cap → deterministic truncation with report note; duplicate round-1 identifiers → parse failure | FR-019, FR-017 |
| U-009 adversarial specification text | Stated limitation; human reviewer is the backstop | Limitations |
| U-010 report write semantics | Plain overwrite of the report file; no atomicity or concurrency guarantee claimed in v1 | FR-034 |

## Assumptions in Effect

| ID | Assumption | Status | Requirements Affected |
|----|-----------|--------|----------------------|
| A-001 | The model command can be driven non-interactively with prompt in, extractable JSON out | unvalidated (OQ-001 spike before HOW) | FR-008, FR-026 |
| A-002 | Neutral temporary working directory suffices for the isolation intent | unvalidated (OQ-002 spike before HOW); residual limitation documented | FR-010, Limitations |
| A-003 | Standalone means standalone: no orchestration imports or configuration reads | unvalidated (review gate) | FR-045 |
| A-004 | The acceptance target retains its three named known issues | validated at base commit ef2643c9; re-verify or freeze before the run | SC-001, AC-023 |
| A-005 | Both rounds fit model context limits for realistic specifications | unvalidated; observed at acceptance | Limitations |
| A-006 | The specification's directory is writable | converted into a pre-flight check | FR-006 |
| A-007 | Timeout applies per subprocess invocation with a fresh budget on retry | adopted as specified behavior | FR-011, FR-013 |
| A-008 | Unit tests follow existing repository test conventions | validated (conventions exist) | FR-044 |
| A-009 | Strict JSON tolerates extraction from wrapped output | adopted as the extraction contract | FR-026 |
| A-010 | Question identifiers follow the Q1..Qn convention; report order follows round-1 order within verdict class | adopted | FR-033 |
| A-011 | The terminal summary is human-oriented with no machine-parsing contract | adopted | FR-040 |
| A-012 | The standard runtime is available on developer machines | adopted | NFR-002 |

## Glossary Additions

- **Clean-specification outcome**: A run in which every question receives an ANSWERED verdict — 0 findings, full audit appendix, exit code 0 (FR-041).
- **Pre-flight check**: Validation performed before any model call: specification readability (FR-005) and report-destination writability (FR-006).
- **Truncation note**: The report-header remark recorded when round 1 returned more questions than the configured maximum and the list was cut to the first N (FR-019).

All other terms are used exactly as defined in `glossary.md` (SUE, Socratic question, Round 1, Round 2, Verdict, Finding, Deterministic assembly, Isolation contract, Grounding rule, Challenge report, Test seam, Corrective retry, Debug dump, ID bijection rule, ERR-CLI-MISSING pattern, Challenged spec, Acceptance run).
