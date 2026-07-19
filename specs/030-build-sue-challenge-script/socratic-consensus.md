# Socratic Consensus Report

- **Specification:** /Users/ladislavbihari/myWork/echelon/specs/030-build-sue-challenge-script/spec.md
- **Run date:** 2026-07-19
- **Readers:** 3 completed
- **Per-reader findings:** R1(structural)=13, R2(behavioural)=12, R3(adversarial)=15
- **Stable findings:** 8 · sampling noise: 22
- **Elenchus:** 8 follow-up chain(s) completed

## Stable findings

### 1. [CONTRADICTED] (support 2) FR-008 obliges every challenge run to perform exactly 2 logical model calls, yet FR-020 obliges a run with a valid empty question list to complete without round 2 — performing only 1. Which requirement governs, and what does 'exactly 2' mean on the zero-question path?

- **Target:** FR-008
- **Category:** contradiction
- **Reader variants:**
  - R3: FR-008 states a challenge run MUST perform 'exactly 2 logical model calls', and AC-001 asserts 'exactly 2 model calls occur' — yet FR-020 mandates completing a run with round 2 skipped when round 1 validly returns 0 questions, which yields exactly 1 logical model call at exit code 0. Which requirement yields when a zero-question run occurs: is FR-008's 'exactly 2' silently conditional, and if so, on what?
- **Evidence:**
  > line 30: - **AC-006**: Given round 1 returns a valid empty question list, when the run continues, then round 2 is skipped (FR-020), the report records exactly 0 questions with 0 findings (FR-036), with exit code 0.
  > line 130: - **FR-008**: When a challenge run executes, the challenge script MUST perform exactly 2 logical model calls: round-1 question generation (FR-014) plus round-2 answering (FR-021).
  > line 159: - **FR-020**: If valid round-1 output contains exactly 0 questions, the challenge script MUST complete the run without round 2, producing a report that records 0 questions (FR-036) plus exit code 0 (AC-006).

The text states both sides without reconciling them. FR-008: 'When a challenge run executes, the challenge script MUST perform exactly 2 logical model calls: round-1 question generation (FR-014) plus round-2 answering (FR-021).' Yet FR-020: 'If valid round-1 output contains exactly 0 questions, the challenge script MUST complete the run without round 2, producing a report that records 0 questions (FR-036) plus exit code 0 (AC-006)', and AC-006 confirms 'round 2 is skipped'. A zero-question run therefore performs exactly 1 logical model call while FR-008 unconditionally requires exactly 2; no requirement states which governs or redefines 'exactly 2' for the zero-question path.

**Elenchus [CONTRADICTED]:** Since FR-008 (line 130) unconditionally requires exactly 2 logical model calls while FR-020 (line 159) and AC-006 (line 30) require a zero-question run to finish with only 1, which single wording change resolves the conflict: is FR-008 to be amended to 'exactly 2 logical model calls, except exactly 1 when valid round-1 output contains 0 questions', or must the script instead issue a round-2 call even with an empty question list?

  > line 130: - **FR-008**: When a challenge run executes, the challenge script MUST perform exactly 2 logical model calls: round-1 question generation (FR-014) plus round-2 answering (FR-021).
  > line 159: - **FR-020**: If valid round-1 output contains exactly 0 questions, the challenge script MUST complete the run without round 2, producing a report that records 0 questions (FR-036) plus exit code 0 (AC-006).
  > line 30: - **AC-006**: Given round 1 returns a valid empty question list, when the run continues, then round 2 is skipped (FR-020), the report records exactly 0 questions with 0 findings (FR-036), with exit code 0.
  > line 92: - Round 1 returns a syntactically valid empty question list → success with a zero-question report (AC-006, FR-020), not a failure.

The text gives both sides without resolving them. FR-008 states unconditionally that a challenge run 'MUST perform exactly 2 logical model calls: round-1 question generation (FR-014) plus round-2 answering (FR-021)' (line 130). But FR-020 states that on valid round-1 output with exactly 0 questions the script 'MUST complete the run without round 2' with exit code 0 (line 159), AC-006 requires round 2 to be skipped (line 30), and the Edge Cases section confirms the empty list is 'success with a zero-question report... not a failure' (line 92). One run cannot both perform exactly 2 logical model calls and skip round 2; the specification never amends FR-008 with an exception, so it does not state which wording change is intended.

### 2. [UNANSWERABLE] (support 3) A zero-byte or whitespace-only specification file is readable, so it passes the FR-005 pre-flight, yet FR-014 must then embed a line-numbered text with no lines. What behavior is specified for an empty specification — a normal challenge run, a distinct rejection, or something undefined?

- **Target:** FR-005
- **Category:** missing-boundary
- **Reader variants:**
  - R2: FR-005's pre-flight checks only that the specification path exists and is readable. A zero-byte file passes that check — what observable behavior is mandated when round 1 receives an empty line-numbered specification text, and is that a success path, a validation failure, or unspecified?
  - R3: FR-005 rejects a 'missing or unreadable' specification path, but nothing bounds what a readable specification must contain. What happens when the path is a directory, a zero-byte file, or a non-UTF-8 binary file — does the run proceed to spend two model calls interrogating an empty or undecodable line-numbered text, and with what outcome?
- **Evidence:**
  > line 119: - **FR-005**: If the specification path is missing or unreadable, the challenge script MUST exit with code 1 after launching exactly 0 model calls (ERR-001, AC-013).
  > line 147: - **FR-014**: When building the round-1 prompt, the challenge script MUST include exactly 2 elements: the full line-numbered specification text (FR-018) plus the question-generation instruction of FR-015.
  > line 340: - **Pre-flight check**: Validation performed before any model call: specification readability (FR-005) and report-destination writability (FR-006).

Gap: no behavior is specified for an empty specification. FR-005 rejects only a 'missing or unreadable' path, and the pre-flight check is defined as exactly 'specification readability (FR-005) and report-destination writability (FR-006)'. A readable zero-byte or whitespace-only file passes both, yet FR-014 must then embed 'the full line-numbered specification text'; no requirement or edge case addresses whether this yields a normal run, a distinct rejection, or anything else.

**Elenchus [UNANSWERABLE]:** Given that a readable zero-byte or whitespace-only specification passes the pre-flight of line 340 and FR-005 (line 119) yet leaves FR-014 (line 147) with no lines to embed, should the pre-flight be extended to reject an empty specification on the exit-code-1 path with 0 model calls, or is the intended behavior a normal challenge run whose round-1 prompt embeds an empty line-numbered text?

  > line 340: - **Pre-flight check**: Validation performed before any model call: specification readability (FR-005) and report-destination writability (FR-006).
  > line 119: - **FR-005**: If the specification path is missing or unreadable, the challenge script MUST exit with code 1 after launching exactly 0 model calls (ERR-001, AC-013).
  > line 147: - **FR-014**: When building the round-1 prompt, the challenge script MUST include exactly 2 elements: the full line-numbered specification text (FR-018) plus the question-generation instruction of FR-015.

Named gap: the specification defines pre-flight as only two checks — 'specification readability (FR-005) and report-destination writability (FR-006)' (line 340) — and FR-005 rejects only a 'missing or unreadable' path (line 119). No requirement, edge case, or assumption addresses a readable zero-byte or whitespace-only specification, so the text cannot say whether such a file is rejected pre-flight or proceeds to a round-1 prompt embedding empty line-numbered text under FR-014 (line 147).

### 3. [UNANSWERABLE] (support 3) AC-012 requires the recorded working directory to be 'outside the repository', yet FR-045 forbids the script from reading any project state that would tell it where the repository boundary is. What guarantees the system temporary location is not itself inside the repository (for example a TMPDIR set beneath the checkout), and how is the AC-012 assertion decided?

- **Target:** FR-010
- **Category:** hidden-assumption
- **Reader variants:**
  - R2: AC-012 requires the recorded working directory to be 'outside the repository', yet FR-010 itself never states this constraint, and a standalone script may run where no repository exists. What defines 'outside the repository' operationally, and what must happen when the system temporary location resides inside the repository tree?
  - R3: AC-012 requires the recorded working directory to be 'outside the repository', yet FR-045 forbids the script from reading any project orchestration configuration or state. How does the script know where 'the repository' is in order to guarantee the temporary directory lies outside it — and what does 'outside the repository' mean when the script is invoked on a specification that is not inside any repository, or when the system temp location itself resides under a repository root?
- **Evidence:**
  > line 49: - **AC-012**: Given a stub model command that records its working directory, when either round executes, then the recorded directory is exactly 1 newly created temporary directory outside the repository (FR-010, AC-011).
  > line 134: - **FR-010**: When launching any model subprocess, the challenge script MUST set the subprocess working directory to exactly 1 newly created neutral temporary directory, keeping repository-level ambient context away from the model (AC-012, OQ-002). Each model subprocess receives its own newly created directory, deleted on a best-effort basis when the call completes.
  > line 229: - **FR-045**: When executing, the challenge script MUST read exactly 2 kinds of input — its command-line arguments plus the challenged specification file — reading 0 project orchestration configuration or state files (FR-001, FR-003).

Gap: no requirement guarantees or verifies the 'outside the repository' property. FR-010 requires only 'exactly 1 newly created neutral temporary directory' per subprocess, and AC-012 asserts the recorded directory is 'outside the repository', but nothing defines how the temporary location is chosen, addresses an environment-set temporary path lying beneath the checkout, or explains how the script — which per FR-045 reads only its arguments and the specification file and therefore has no stated way to know the repository boundary — or the test decides 'outside the repository'.

**Elenchus [UNANSWERABLE]:** Since FR-045 (line 229) leaves the script with no stated way to locate the repository boundary that AC-012 (line 49) asserts against, should FR-010 (line 134) be amended to define the temporary-directory choice concretely (e.g. the platform default temporary root, with AC-012 weakened to 'a newly created temporary directory distinct from the repository working directory'), or must the script actively detect and refuse a TMPDIR that resolves beneath the specification's repository?

  > line 134: - **FR-010**: When launching any model subprocess, the challenge script MUST set the subprocess working directory to exactly 1 newly created neutral temporary directory, keeping repository-level ambient context away from the model (AC-012, OQ-002). Each model subprocess receives its own newly created directory, deleted on a best-effort basis when the call completes.
  > line 49: - **AC-012**: Given a stub model command that records its working directory, when either round executes, then the recorded directory is exactly 1 newly created temporary directory outside the repository (FR-010, AC-011).
  > line 229: - **FR-045**: When executing, the challenge script MUST read exactly 2 kinds of input — its command-line arguments plus the challenged specification file — reading 0 project orchestration configuration or state files (FR-001, FR-003).
  > line 305: | OQ-002 | Does a neutral temporary working directory fully satisfy the isolation intent, or does operator-level ambient context still load? | FR-010 limitation wording; possible suppression options | unknowns.md U-002 (should-resolve-before-HOW) |

Named gap: FR-010 requires only 'exactly 1 newly created neutral temporary directory' (line 134) and AC-012 asserts the recorded directory is 'outside the repository' (line 49), but no requirement defines how the repository boundary is located, which temporary root is used, or what happens if the temporary location resolves beneath the repository. FR-045 constrains the script to reading only its arguments and the specification file (line 229), and OQ-002 (line 305) concerns operator-level ambient context, not directory selection. The text therefore cannot decide between the two proposed amendments.

### 4. [UNANSWERABLE] (support 2) FR-034 explicitly keeps 0 historical report copies, but no requirement states the lifecycle of the `.sue-debug` directory: do dumps from successive failed runs accumulate, overwrite, or get cleared, and are the raw outputs of both failing attempts in a round saved or only the second?

- **Target:** FR-030
- **Category:** missing-boundary
- **Reader variants:**
  - R2: FR-034 mandates that reports keep 0 historical copies, but FR-030's `.sue-debug` dump has no stated retention rule. Across successive failing runs against the same specification, are prior debug dumps overwritten, appended to, or accumulated indefinitely?
- **Evidence:**
  > line 189: - **FR-030**: On the second parse failure in the same round, the challenge script MUST exit with code 3 after saving the raw output of the failing calls into exactly 1 directory named `.sue-debug` beside the specification (ERR-004, AC-015). For a timed-out call, the saved raw output is whatever partial output was drained within the shutdown grace period of exactly 5 seconds (subprocess ended by process-group kill; the up-to-4 grace periods are counted inside NFR-001's +60-second allowance), possibly empty. The debug dump itself is best-effort: if it cannot be written, the exit-3 outcome stands and its single diagnostic line names the failed dump (governs over ERR-004's save wording).
  > line 202: - **FR-034**: When a run succeeds, the challenge script MUST write exactly 1 report file named `socratic-challenge.md` in the specification's directory, replacing any previous report while keeping 0 historical copies (FR-035, AC-003). If the report path resolves to the challenged specification file itself, the run MUST reject with exit code 1 before any model call — FR-042 takes precedence and the challenged file is never written. If writing the report fails after a successful run, the run exits with code 1.
  > line 262: - **Debug Dump**: Raw model output saved under `.sue-debug` in the specification's directory on the unrecoverable parse-failure path only (FR-030).

Gap: the `.sue-debug` lifecycle is unspecified. FR-030 saves 'the raw output of the failing calls into exactly 1 directory named `.sue-debug`' (the plural 'failing calls' is the only signal about which attempts are saved), and the Debug Dump entity adds only that output is 'saved under `.sue-debug` ... on the unrecoverable parse-failure path only'. FR-034's keep-0-historical-copies rule applies solely to the report file; no requirement states whether dumps from successive failed runs accumulate, overwrite, or are cleared.

**Elenchus [UNANSWERABLE]:** For the `.sue-debug` directory that FR-030 (line 189) creates on the exit-3 path (line 262), what is the intended lifecycle decision: does each new unrecoverable parse failure clear or overwrite the directory so it holds only the latest run's dumps, or do dumps accumulate across runs — and does 'the raw output of the failing calls' mean both failed attempts in the round are saved as separate files?

  > line 189: - **FR-030**: On the second parse failure in the same round, the challenge script MUST exit with code 3 after saving the raw output of the failing calls into exactly 1 directory named `.sue-debug` beside the specification (ERR-004, AC-015). For a timed-out call, the saved raw output is whatever partial output was drained within the shutdown grace period of exactly 5 seconds (subprocess ended by process-group kill; the up-to-4 grace periods are counted inside NFR-001's +60-second allowance), possibly empty. The debug dump itself is best-effort: if it cannot be written, the exit-3 outcome stands and its single diagnostic line names the failed dump (governs over ERR-004's save wording).
  > line 262: - **Debug Dump**: Raw model output saved under `.sue-debug` in the specification's directory on the unrecoverable parse-failure path only (FR-030).
  > line 237: - **ERR-004**: When model output stays unusable after exactly 1 corrective retry in either round, the challenge script aborts with exit code 3, saving the raw output to the debug dump directory (FR-030, AC-015).
  > line 318: | U-010 report write semantics | Plain overwrite of the report file; no atomicity or concurrency guarantee claimed in v1 | FR-034 |

Named gap: FR-030 requires 'saving the raw output of the failing calls into exactly 1 directory named `.sue-debug` beside the specification' (line 189) and the Debug Dump entity restates this (line 262), but nothing states the directory's lifecycle across runs — clear, overwrite, or accumulate. The overwrite decision recorded in U-010 (line 318) covers only the report file, not the debug dump. The plural 'failing calls' suggests output from both failed attempts is saved, but the text never states whether they are separate files.

### 5. [UNANSWERABLE] (support 2) FR-004 explicitly rejects non-numeric and non-finite timeout values, but FR-002 only rejects question-count values 'below 1'. What observable behavior occurs when the question-count option receives a non-integer or non-numeric value — argument rejection at exit 1, or something unspecified?

- **Target:** FR-002
- **Category:** missing-boundary
- **Reader variants:**
  - R3: FR-002 rejects question-count values 'below 1' on the exit-code-1 path, and FR-004 explicitly enumerates non-numeric, non-finite, zero, and negative timeout values — but FR-002 never states what happens for a non-integer or non-numeric question count (e.g. '2.5' or 'ten'). Is a fractional count rejected, truncated, or rounded, and by what rule?
- **Evidence:**
  > line 113: - **FR-002**: When invoked, the challenge script MUST accept a question-count option, defaulting to exactly 15, that caps round-1 questions (FR-015, FR-019). Values below 1 MUST be rejected on the exit-code-1 argument path.
  > line 117: - **FR-004**: When invoked, the challenge script MUST accept a timeout option, defaulting to exactly 300 seconds, that bounds each model call (FR-011, FR-013). Non-numeric, non-finite, zero, or negative values MUST be rejected on the exit-code-1 argument path.

Gap: FR-002 only mandates rejection of question-count values 'below 1' on the exit-code-1 argument path, and unlike FR-004 — which explicitly rejects 'non-numeric, non-finite, zero, or negative' timeout values — no requirement, error class, or acceptance scenario specifies the observable behavior when the question-count option receives a non-integer or non-numeric value.

**Elenchus [UNANSWERABLE]:** Should FR-002 (line 113) be amended to mirror FR-004's explicit rejection list (line 117) so that non-numeric and non-integer question-count values are rejected on the exit-code-1 argument path, or is some other observable behavior (e.g. truncation to an integer) intended for such inputs?

  > line 113: - **FR-002**: When invoked, the challenge script MUST accept a question-count option, defaulting to exactly 15, that caps round-1 questions (FR-015, FR-019). Values below 1 MUST be rejected on the exit-code-1 argument path.
  > line 117: - **FR-004**: When invoked, the challenge script MUST accept a timeout option, defaulting to exactly 300 seconds, that bounds each model call (FR-011, FR-013). Non-numeric, non-finite, zero, or negative values MUST be rejected on the exit-code-1 argument path.

Named gap: FR-002 specifies only that 'Values below 1 MUST be rejected on the exit-code-1 argument path' (line 113), while FR-004 explicitly rejects 'Non-numeric, non-finite, zero, or negative values' for the timeout option (line 117). The specification is silent on the observable behavior for non-numeric or non-integer question-count values — neither rejection nor truncation is stated — so the intended behavior cannot be determined from the text.

### 6. [UNANSWERABLE] (support 2) FR-039 requires the report to state 'the named gap from the answer text' for UNANSWERABLE findings, but the FR-024 answer schema defines only a free-form answer text with no gap field. By what deterministic rule is 'the named gap' extracted or rendered from arbitrary answer text?

- **Target:** FR-039
- **Category:** undefined-term
- **Reader variants:**
  - R3: FR-039 requires the report to state 'the named gap from the answer text' for UNANSWERABLE findings — but FR-024's answer schema defines only an identifier, a verdict, an answer text, and evidence lines, with no structured 'gap' field, and the round-2 instruction in FR-023 never directs the model to name a gap. What exactly is extracted as the 'named gap', and what renders when the answer text names none?
- **Evidence:**
  > line 172: - **FR-024**: When round-2 output is received, the challenge script MUST validate that each answer carries exactly 1 question identifier, exactly 1 verdict from FR-023, exactly 1 answer text, plus a list of integer evidence line references (FR-025).
  > line 212: - **FR-039**: For each cited evidence line number, the report MUST quote exactly 1 line of text from the specification file, stating the named gap from the answer text for UNANSWERABLE findings (FR-018, AC-009). A cited line number outside the specification's line range MUST render as a deterministic `(not present in the specification)` marker rather than failing the run.

Gap: FR-039 requires 'stating the named gap from the answer text for UNANSWERABLE findings', but the FR-024 answer schema defines only 'exactly 1 answer text' as a free-form field with no separate gap element, and no requirement defines a deterministic rule for extracting or rendering 'the named gap' from arbitrary answer text.

**Elenchus [ANSWERED]:** Given that the FR-024 answer schema (line 172) carries only a single free-form answer text with no gap field, should FR-039 (line 212) be satisfied by quoting the answer text verbatim as 'the named gap' for UNANSWERABLE findings, or must the round-2 answer schema gain a distinct machine-readable gap field that the report renders?

  > line 172: - **FR-024**: When round-2 output is received, the challenge script MUST validate that each answer carries exactly 1 question identifier, exactly 1 verdict from FR-023, exactly 1 answer text, plus a list of integer evidence line references (FR-025).
  > line 212: - **FR-039**: For each cited evidence line number, the report MUST quote exactly 1 line of text from the specification file, stating the named gap from the answer text for UNANSWERABLE findings (FR-018, AC-009). A cited line number outside the specification's line range MUST render as a deterministic `(not present in the specification)` marker rather than failing the run.
  > line 258: - **Answer**: A round-2 output unit: question identifier, verdict (ANSWERED, UNANSWERABLE, or CONTRADICTED), answer text, evidence line references. Exactly 1 per question (identifier bijection, FR-025).

The answer schema is fixed by FR-024 as 'exactly 1 question identifier, exactly 1 verdict from FR-023, exactly 1 answer text, plus a list of integer evidence line references' (line 172) — no distinct gap field exists — and FR-039 requires the report to state 'the named gap from the answer text for UNANSWERABLE findings' (line 212). The Answer entity confirms the same four-element schema (line 258). The text therefore answers the disjunction: no machine-readable gap field is added; the named gap is drawn from the free-form answer text itself.

### 7. [UNANSWERABLE] (support 2) NFR-002 measures against 'the standard runtime' and A-012 assumes it is available, but no requirement defines which runtime, which minimum version, or whether 'standard' means standard-library-only. Against what concrete runtime definition is the 0-additional-installations target verified?

- **Target:** NFR-002
- **Category:** undefined-term
- **Reader variants:**
  - R3: NFR-002 measures portability against 'the standard runtime', and A-012 merely assumes that runtime is 'available on developer machines' — but 'standard runtime' is never defined: which language runtime, which minimum version, and does 'standard' exclude commonly-absent modules? Against what concrete baseline is 'exactly 0 additional installed components' verified?
- **Evidence:**
  > line 9: **Input**: User description: "Build the SUE challenge script: a standalone Python script (scripts/sue_challenge.py) that challenges a specification via Socratic question-answer dialogue using two isolated claude -p calls, per the attached approved design document. Implement exactly the v1 scope: interface, JSON schemas, isolation contract, report format, error handling, and pytest unit tests as designed."
  > line 244: - **NFR-002**: When run from a fresh repository checkout, the challenge script plus its unit tests MUST execute with exactly 0 additional installed components beyond the standard runtime plus the model command itself (FR-044, FR-045).
  > line 245:   - **Category:** Portability | **Measurable Target:** 0 additional installations on a fresh checkout (model command excluded)
  > line 335: | A-012 | The standard runtime is available on developer machines | adopted | NFR-002 |

Gap: 'the standard runtime' is never concretely defined. NFR-002 targets '0 additional installations on a fresh checkout (model command excluded)' measured against 'the standard runtime', and A-012 merely assumes 'The standard runtime is available on developer machines'. The input description names 'a standalone Python script', but no requirement specifies which runtime, a minimum version, or whether 'standard' means standard-library-only, so no concrete verification baseline is stated.

**Elenchus [UNANSWERABLE]:** Since the input description (line 9) names a standalone Python script but NFR-002 (line 244) measures against an undefined 'standard runtime', what concrete baseline is adopted for verification: which minimum Python version, and does 'standard runtime' mean standard-library-only (i.e. the script and its pytest-based tests may import nothing outside the standard library except pytest itself)?

  > line 9: **Input**: User description: "Build the SUE challenge script: a standalone Python script (scripts/sue_challenge.py) that challenges a specification via Socratic question-answer dialogue using two isolated claude -p calls, per the attached approved design document. Implement exactly the v1 scope: interface, JSON schemas, isolation contract, report format, error handling, and pytest unit tests as designed."
  > line 244: - **NFR-002**: When run from a fresh repository checkout, the challenge script plus its unit tests MUST execute with exactly 0 additional installed components beyond the standard runtime plus the model command itself (FR-044, FR-045).
  > line 335: | A-012 | The standard runtime is available on developer machines | adopted | NFR-002 |

Named gap: the input description names 'a standalone Python script' (line 9), NFR-002 measures 'exactly 0 additional installed components beyond the standard runtime plus the model command itself' (line 244), and A-012 merely adopts 'The standard runtime is available on developer machines' (line 335) — but no line defines 'standard runtime', names a minimum Python version, or states whether standard-library-only applies to the script and its tests (or whether pytest counts inside or outside the baseline). The concrete verification baseline cannot be derived from the text.

### 8. [UNANSWERABLE] (support 2) FR-012 and ERR-003 require the exit-2 message to contain 'exactly 1 installation pointer', but no requirement defines what qualifies as an installation pointer — a URL, a package name, a shell command? By what criterion does a test decide the message contains exactly one?

- **Target:** FR-012
- **Category:** undefined-term
- **Reader variants:**
  - R2: Exit 2 is reserved for the executable that 'cannot be found' (FR-012), while 'every other launch or output failure takes the parse-failure path' (U-007). What operationally distinguishes not-found from other launch failures — for example, a file present on the lookup path but lacking execute permission — and which exit code does that case produce?
- **Evidence:**
  > line 138: - **FR-012**: If the model-command executable named by FR-007 cannot be found, the challenge script MUST exit with code 2, printing exactly 1 message that contains an installation pointer (ERR-003, AC-014).
  > line 236: - **ERR-003**: When the model-command executable is not found, the challenge script rejects the run with exit code 2, printing exactly 1 installation pointer (FR-012, AC-014).

Gap: 'installation pointer' is undefined. FR-012 requires 'exactly 1 message that contains an installation pointer' and ERR-003 requires 'printing exactly 1 installation pointer', but no requirement or glossary entry defines what qualifies as an installation pointer (URL, package name, shell command, or otherwise), so the text supplies no criterion by which a test could count exactly one.

**Elenchus [UNANSWERABLE]:** For the exit-2 message of FR-012 (line 138) and ERR-003 (line 236), what testable criterion defines 'exactly 1 installation pointer' — is a specific literal (e.g. an exact URL or install command string) mandated to appear exactly once in the message, or does any one URL, package name, or shell command qualify, and how would a test count occurrences?

  > line 138: - **FR-012**: If the model-command executable named by FR-007 cannot be found, the challenge script MUST exit with code 2, printing exactly 1 message that contains an installation pointer (ERR-003, AC-014).
  > line 236: - **ERR-003**: When the model-command executable is not found, the challenge script rejects the run with exit code 2, printing exactly 1 installation pointer (FR-012, AC-014).

Named gap: FR-012 requires 'exactly 1 message that contains an installation pointer' (line 138) and ERR-003 restates 'printing exactly 1 installation pointer' (line 236), but the specification never defines what qualifies as an installation pointer — no mandated literal, URL, package name, or command string — nor how a test would count occurrences of one within the message. The testable criterion is undefined.

## Sampling appendix (support below threshold)

- [UNANSWERABLE] (R1, NFR-004) NFR-004 demands byte-identical report bodies 'run-date field excluded', yet no requirement defines the run-date field's format, timezone, or delimitation within the header. How is the excluded byte range identified deterministically for the byte-identity comparison?
- [UNANSWERABLE] (R1, FR-039) FR-024 permits an answer's evidence line list to be empty, and FR-037 makes evidence a mandatory element of every findings entry. For an UNANSWERABLE finding citing 0 evidence lines, what renders in the mandatory evidence slot, given FR-039 only defines rendering per cited line number?
- [UNANSWERABLE] (R2, FR-040) FR-040 requires the terminal summary to list 'the top 3 findings in rank order'. When a run produces exactly 1 or 2 findings, what must the summary list — all available findings, and is that outcome anywhere specified as passing AC-005?
- [UNANSWERABLE] (R2, FR-028) FR-028 requires the corrective instruction to 'name the validation failure' while 'echoing 0 lines of the prior output'. Naming a duplicate-identifier failure precisely (e.g., which identifier duplicated) requires reproducing content drawn from the prior output — how can both constraints be satisfied simultaneously, and where is the boundary between 'naming' and 'echoing'?
- [UNANSWERABLE] (R2, FR-016) FR-016 validates round-1 questions as carrying 'a list of integer line references' with no range constraint, while FR-039 only handles out-of-range numbers at render time for round-2 evidence. Are zero, negative, or beyond-end-of-file integers valid in round-1 line references, and what observable behavior follows from each?
- [UNANSWERABLE] (R2, general) AC-011 asserts the recorded round-2 prompt holds 'exactly 2 content blocks', yet OQ-001 leaves the prompt-delivery mechanism and output flags unresolved. On what assumed delivery contract can a stub record the prompt and a test count its content blocks before OQ-001 is answered?
- [UNANSWERABLE] (R1, FR-030) FR-030 budgets 'up-to-4 grace periods' inside NFR-001's 60-second allowance, but its own termination rule ends the run after a round's second failure, making at most 3 timeout-killed subprocesses reachable on any path. Is a 4-timeout path actually possible, and if not, which accounting is authoritative?
- [UNANSWERABLE] (R2, FR-040) FR-040 mandates exit code 0 after any successful report, whether the run produced 0 findings or 15 CONTRADICTED findings. Is it assumed that no consumer (operator script, CI gate) needs to distinguish a clean specification from a heavily-contradicted one via exit code, and where is that assumption recorded?
- [UNANSWERABLE] (R2, general) SC-001 and AC-023 bound the live acceptance run to 'at most 3 total attempts', but what counts as one attempt — does a run aborting at exit 3 consume an attempt — and what is the specified verdict on the deliverable if all 3 attempts fail to overlap a known issue?
- [UNANSWERABLE] (R3, FR-012) The glossary defines the pre-flight check as only FR-005 readability plus FR-006 writability, while FR-012's executable-not-found check has no stated timing. If the specification path is missing AND the model executable is absent, which exit code wins — 1 or 2? At what point in the run is the FR-012 lookup performed, and what happens if the executable exists at check time but vanishes before the subprocess launch?
- [UNANSWERABLE] (R3, FR-034) The interface section promises 'a failed pre-flight costs nothing' and ERR-001/ERR-002 both bind exit code 1 to 'exactly 0 model calls launched' — but FR-034's final sentence assigns exit code 1 to a report-write failure occurring after a successful run, i.e. after 2 logical model calls. Doesn't this create an exit-1 path that violates the Error Handling Summary's own characterization of exit 1, and which diagnostic 'failure class' does NFR-005 name for it?
- [UNANSWERABLE] (R3, SC-001) AC-023 and SC-001 require that findings 'overlap at least 1 of the 3 named known issues' — but 'overlap' is never defined. Who judges overlap, and by what criterion: an exact requirement-identifier match in the finding's target, a line-range intersection, or a human's semantic judgment that a question 'is about' the known issue?
- [UNANSWERABLE] (R3, AC-023) AC-023 bounds the live validation to 'at most 3 total attempts' — but what counts as one attempt? Does a run that ends at exit code 3 (unrecoverable parse failure) or exit code 2 consume an attempt, or only runs that produce a report? If the third attempt produces a report with zero overlapping findings, is the acceptance criterion failed permanently or renegotiated?
- [UNANSWERABLE] (R3, FR-006) FR-006 assumes directory writability can be 'detected before any model call' — but by what method? A permission-bit or access check can pass on a read-only filesystem, under ACLs, or on network mounts, and the directory may become unwritable between pre-flight and the FR-034 write. Is the check a probe write, and if not, what does the pre-flight guarantee actually guarantee?
- [UNANSWERABLE] (R3, FR-024) FR-024 permits an answer's evidence line references to be any 'list of integer' values, including empty — yet FR-038 and AC-008 require every ANSWERED question to appear in the audit appendix 'with its quoted answering lines'. Is an ANSWERED verdict with zero evidence lines valid input, and if so, what does the audit appendix render for a question the model claims is answered but cannot locate?
- [UNANSWERABLE] (R3, FR-007) FR-007 mandates POSIX shell quoting semantics 'platform-independent' for splitting the model command — but POSIX quoting mishandles native Windows paths (backslashes become escapes) and PATH lookup semantics differ per platform. What does the specification assume about the platforms on which 'platform-independent' POSIX splitting produces a correct executable word, and where is that assumption recorded?
- [UNANSWERABLE] (R3, FR-040) FR-040 requires the terminal summary to list 'the top 3 findings in rank order', and AC-005 is triggered by 'at least 1 finding'. When exactly 1 or 2 findings exist, is listing fewer than 3 compliant with 'the top 3', and when more than 3 findings tie across the two verdict classes, is 'top 3' fully determined by FR-033's ordering alone?
- [UNANSWERABLE] (R3, FR-026) FR-026's third precedence level accepts the 'first balanced-brace candidate' — but balanced by what tokenizer? Braces occurring inside JSON string literals (e.g. an answer text containing '}') would break naive brace counting; does 'balanced' mean string-aware scanning, and where does the candidate end when multiple balanced regions overlap or nest within surrounding prose?
- [UNANSWERABLE] (R1, FR-030) FR-030 specifies subprocess termination 'by process-group kill', a POSIX mechanism, while FR-007 declares the command-splitting contract 'platform-independent'. Is the script assumed to run only on POSIX platforms, and if so, where is that platform boundary stated?
- [UNANSWERABLE] (R1, FR-016) FR-016 obliges validation of each round-1 question's list of integer line references, FR-022 then forbids those references from reaching round 2, and no report requirement (FR-036 to FR-039) renders them. What downstream obligation consumes round-1 line references, or is their collection and validation assumed useful without any consumer?
- [UNANSWERABLE] (R1, FR-028) FR-028 requires the corrective instruction to 'name the validation failure' while 'echoing 0 lines of the prior output'. When the failure is a duplicate or unknown identifier, naming it requires reproducing a value that came from the prior output — where is the boundary between naming the failure and echoing the output?
- [UNANSWERABLE] (R1, FR-037) FR-037 requires each findings entry to state 'the target requirement identifier', but a Socratic Question's target may be the literal value 'general' rather than a requirement identifier. How does a finding whose question targets 'general' satisfy the 4-element obligation, and what renders in that slot?

_Audit: 5 question(s) across all readers were ANSWERED by the specification text and discarded; see per-reader runs for detail._
