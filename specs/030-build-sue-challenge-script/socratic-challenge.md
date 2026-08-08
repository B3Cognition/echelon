# Socratic Challenge Report

- **Specification:** /Users/ladislavbihari/myWork/echelon/specs/030-build-sue-challenge-script/spec.md
- **Run date:** 2026-07-19
- **Questions:** 15
- **Findings:** 13

## Findings

### 1. [CONTRADICTED] ERR-004 states the script 'aborts with exit code 3, saving the raw output to the debug dump directory', while FR-034 states that if writing the debug dump fails after the model rounds the run exits with code 1 — on a double parse failure with an unwritable dump, which exit code and which NFR-005 failure-class diagnostic does the operator see?

- **Target:** FR-034
- **Evidence:**
  > line 237: - **ERR-004**: When model output stays unusable after exactly 1 corrective retry in either round, the challenge script aborts with exit code 3, saving the raw output to the debug dump directory (FR-030, AC-015).
  > line 189: - **FR-030**: On the second parse failure in the same round, the challenge script MUST exit with code 3 after saving the raw output of the failing calls into exactly 1 directory named `.sue-debug` beside the specification (ERR-004, AC-015). For a timed-out call, the saved raw output is whatever partial output was drained within the shutdown grace period, possibly empty.
  > line 202: - **FR-034**: When a run succeeds, the challenge script MUST write exactly 1 report file named `socratic-challenge.md` in the specification's directory, replacing any previous report while keeping 0 historical copies (FR-035, AC-003). If the report path resolves to the challenged specification file itself, the run MUST reject with exit code 1 before any model call — FR-042 takes precedence and the challenged file is never written. If writing the report or the debug dump fails after the model rounds, the run exits with code 1.
  > line 250: - **NFR-005**: When exiting with code 1, 2, or 3, the challenge script MUST print exactly 1 diagnostic line to the error stream naming the failure class (ERR-001, ERR-004).

ERR-004 and FR-030 state that a second parse failure ends the run 'with exit code 3 after saving the raw output' to the debug dump, while FR-034 states 'If writing the report or the debug dump fails after the model rounds, the run exits with code 1'. In the posed scenario both conditions hold simultaneously and the spec declares no precedence between them (unlike the FR-042 precedence it does declare for the report path), so the two rules assign conflicting exit codes; additionally, no ERR class is named for a post-round dump-write failure, so the NFR-005 diagnostic's failure class is undefined.

### 2. [UNANSWERABLE] FR-030 says a timed-out call's saved raw output is whatever was drained 'within the shutdown grace period' — what is the duration of this grace period, how is the subprocess ended, and does the grace period count inside NFR-001's wall-clock bound of 4 timeout budgets plus 60 seconds?

- **Target:** FR-030
- **Evidence:**
  > line 189: - **FR-030**: On the second parse failure in the same round, the challenge script MUST exit with code 3 after saving the raw output of the failing calls into exactly 1 directory named `.sue-debug` beside the specification (ERR-004, AC-015). For a timed-out call, the saved raw output is whatever partial output was drained within the shutdown grace period, possibly empty.
  > line 242: - **NFR-001**: When a challenge run terminates on any path, its wall-clock duration MUST be at most 4 timeout budgets (FR-004, FR-013) plus 60 seconds of local processing.

The text names a 'shutdown grace period' only once, in FR-030, and never defines its duration, never states how the subprocess is ended (signal, kill sequence, or otherwise), and never states whether the grace period is included in or additional to NFR-001's wall-clock bound of 4 timeout budgets plus 60 seconds.

### 3. [UNANSWERABLE] FR-002 explicitly rejects question-count values below 1 on the exit-code-1 argument path, but FR-004 states no validity floor for the timeout option — what happens when the operator passes a timeout of 0, a negative number, or a non-numeric value?

- **Target:** FR-004
- **Evidence:**
  > line 113: - **FR-002**: When invoked, the challenge script MUST accept a question-count option, defaulting to exactly 15, that caps round-1 questions (FR-015, FR-019). Values below 1 MUST be rejected on the exit-code-1 argument path.
  > line 117: - **FR-004**: When invoked, the challenge script MUST accept a timeout option, defaulting to exactly 300 seconds, that bounds each model call (FR-011, FR-013).

FR-002 explicitly rejects question-count values below 1 on the exit-code-1 argument path, but FR-004 states only the timeout's default of 300 seconds and what it bounds; no requirement defines validation, a floor, or the behavior for a timeout of 0, a negative number, or a non-numeric value.

### 4. [UNANSWERABLE] FR-024 requires each answer to carry 'a list of integer evidence line references' — may that list be empty, and if a CONTRADICTED or UNANSWERABLE finding cites zero lines, what does FR-039 render as the finding's evidence element required by FR-037?

- **Target:** FR-024
- **Evidence:**
  > line 172: - **FR-024**: When round-2 output is received, the challenge script MUST validate that each answer carries exactly 1 question identifier, exactly 1 verdict from FR-023, exactly 1 answer text, plus a list of integer evidence line references (FR-025).
  > line 212: - **FR-039**: For each cited evidence line number, the report MUST quote exactly 1 line of text from the specification file, stating the named gap from the answer text for UNANSWERABLE findings (FR-018, AC-009). A cited line number outside the specification's line range MUST render as a deterministic `(not present in the specification)` marker rather than failing the run.
  > line 208: - **FR-037**: Each findings entry MUST state exactly 4 elements: the verdict, the question, the target requirement identifier, plus the evidence rendered per FR-039 (FR-033).

FR-024 requires only 'a list of integer evidence line references' without stating whether the list may be empty, and FR-039's rendering rule is phrased per cited line number ('For each cited evidence line number...'), so the text never states what FR-037's mandatory evidence element renders when a CONTRADICTED or UNANSWERABLE finding cites zero lines.

### 5. [UNANSWERABLE] FR-039 requires the report to state 'the named gap from the answer text' for UNANSWERABLE findings — what qualifies as a named gap, how is it located inside free-form answer text, and what is rendered when the answer text names no identifiable gap?

- **Target:** FR-039
- **Evidence:**
  > line 212: - **FR-039**: For each cited evidence line number, the report MUST quote exactly 1 line of text from the specification file, stating the named gap from the answer text for UNANSWERABLE findings (FR-018, AC-009). A cited line number outside the specification's line range MUST render as a deterministic `(not present in the specification)` marker rather than failing the run.

FR-039 requires 'stating the named gap from the answer text' for UNANSWERABLE findings, but the text never defines what qualifies as a named gap, gives no rule for locating it within free-form answer text, and specifies no fallback rendering when the answer text names no identifiable gap.

### 6. [UNANSWERABLE] FR-026's precedence is whole-output parse, first fenced block, first balanced-brace candidate — if an earlier candidate parses as valid JSON that is not an object (for example a bare array), does extraction fall through to the next candidate in precedence, or is the output classified as a parse failure under FR-027?

- **Target:** FR-026
- **Evidence:**
  > line 181: - **FR-026**: When raw model output is received, the challenge script MUST extract exactly 1 JSON object from it, tolerating surrounding non-JSON text plus code fences (FR-016, FR-024). When more than 1 candidate object is extractable, the first extractable object wins, in this precedence: whole-output parse, first fenced block, first balanced-brace candidate.
  > line 183: - **FR-027**: If exactly 0 JSON objects can be extracted from raw model output, the challenge script MUST classify that output as a parse failure routed to FR-028 (FR-026).

FR-026 defines the precedence (whole-output parse, first fenced block, first balanced-brace candidate) and speaks throughout of extracting a JSON 'object', but it never states what happens when an earlier candidate parses as valid JSON that is not an object, such as a bare array — whether extraction falls through to the next candidate or the output becomes a parse failure under FR-027 is unspecified.

### 7. [UNANSWERABLE] AC-012 requires the recorded working directory to be a temporary directory 'outside the repository', yet FR-010 never mentions a repository — what defines 'outside the repository' when the script challenges a specification on a path that belongs to no repository at all?

- **Target:** FR-010
- **Evidence:**
  > line 49: - **AC-012**: Given a stub model command that records its working directory, when either round executes, then the recorded directory is exactly 1 newly created temporary directory outside the repository (FR-010, AC-011).
  > line 134: - **FR-010**: When launching any model subprocess, the challenge script MUST set the subprocess working directory to exactly 1 newly created neutral temporary directory, keeping repository-level ambient context away from the model (AC-012, OQ-002). Each model subprocess receives its own newly created directory, deleted on a best-effort basis when the call completes.

AC-012 requires the recorded directory to be a temporary directory 'outside the repository', while FR-010 requires only a 'newly created neutral temporary directory' keeping 'repository-level ambient context' away; neither defines what repository is meant or what 'outside the repository' means when the challenged specification's path belongs to no repository at all.

### 8. [UNANSWERABLE] FR-016 validates round-1 line references only as a list of integers, and no requirement range-checks or renders them — what purpose do round-1 line references serve in the output, and why do they escape the out-of-range marker treatment that FR-039 mandates for round-2 evidence lines?

- **Target:** FR-016
- **Evidence:**
  > line 151: - **FR-016**: When round-1 output is received, the challenge script MUST validate that each question carries exactly 1 unique identifier, exactly 1 question text, exactly 1 target — a requirement identifier or `general` — a list of integer line references, plus exactly 1 category from FR-015 (FR-017).
  > line 168: - **FR-022**: The round-2 prompt MUST NOT contain round-1 categories, targets, line references, or round-1 reasoning — exactly 0 of these 4 elements may appear (FR-021, AC-011).
  > line 212: - **FR-039**: For each cited evidence line number, the report MUST quote exactly 1 line of text from the specification file, stating the named gap from the answer text for UNANSWERABLE findings (FR-018, AC-009). A cited line number outside the specification's line range MUST render as a deterministic `(not present in the specification)` marker rather than failing the run.

FR-016 validates round-1 line references as 'a list of integer line references' and FR-022 forbids them from the round-2 prompt, but no requirement range-checks, renders, or otherwise consumes them — the text never states what purpose round-1 line references serve or why they are exempt from the out-of-range '(not present in the specification)' marker that FR-039 mandates for round-2 evidence lines.

### 9. [UNANSWERABLE] FR-015 says the round-1 instruction requests questions 'targeting exactly 5 weakness categories' — does this oblige the instruction to demand coverage of all 5 categories across the question set, or only that each individual question use one of the 5, and is a valid response drawing from a single category acceptable?

- **Target:** FR-015
- **Evidence:**
  > line 149: - **FR-015**: The round-1 instruction MUST request at most N Socratic challenge questions, where N is the FR-002 value, targeting exactly 5 weakness categories: ambiguity, hidden assumption, contradiction, undefined term, missing boundary (FR-016).
  > line 151: - **FR-016**: When round-1 output is received, the challenge script MUST validate that each question carries exactly 1 unique identifier, exactly 1 question text, exactly 1 target — a requirement identifier or `general` — a list of integer line references, plus exactly 1 category from FR-015 (FR-017).

FR-015 says the instruction requests questions 'targeting exactly 5 weakness categories', and FR-016 validates only that each question carries 'exactly 1 category from FR-015'; the text never states whether the instruction must demand coverage of all 5 categories across the question set or merely restrict each question to one of the 5, and never says whether a valid response drawing from a single category is acceptable.

### 10. [UNANSWERABLE] NFR-002 and A-012 permit exactly 0 installations beyond 'the standard runtime' — which runtime, and which minimum version of it, counts as standard, given that the portability target is unverifiable without naming one?

- **Target:** NFR-002
- **Evidence:**
  > line 244: - **NFR-002**: When run from a fresh repository checkout, the challenge script plus its unit tests MUST execute with exactly 0 additional installed components beyond the standard runtime plus the model command itself (FR-044, FR-045).
  > line 335: | A-012 | The standard runtime is available on developer machines | adopted | NFR-002 |
  > line 9: **Input**: User description: "Build the SUE challenge script: a standalone Python script (scripts/sue_challenge.py) that challenges a specification via Socratic question-answer dialogue using two isolated claude -p calls, per the attached approved design document. Implement exactly the v1 scope: interface, JSON schemas, isolation contract, report format, error handling, and pytest unit tests as designed."

NFR-002 permits '0 additional installed components beyond the standard runtime plus the model command itself' and A-012 assumes 'the standard runtime is available', but the text never names which runtime is standard or any minimum version — the input description calls the deliverable 'a standalone Python script', yet no requirement ties NFR-002's 'standard runtime' to a named runtime or version, leaving the portability target unverifiable.

### 11. [UNANSWERABLE] FR-005 rejects a missing or unreadable specification path, but what happens when the file is readable yet degenerate — zero bytes, zero lines, or non-text content: does FR-018's 1-based line numbering proceed into round 1, or is this a pre-flight rejection, and under which exit code?

- **Target:** FR-018
- **Evidence:**
  > line 119: - **FR-005**: If the specification path is missing or unreadable, the challenge script MUST exit with code 1 after launching exactly 0 model calls (ERR-001, AC-013).
  > line 155: - **FR-018**: When embedding the specification in either prompt, the challenge script MUST prefix every line with its line number, starting at exactly 1, making each cited reference checkable per FR-039 (FR-014, FR-021).

FR-005 rejects only a 'missing or unreadable' specification path, and FR-018 mandates line numbering 'starting at exactly 1'; the text never states the behavior for a readable but degenerate file — zero bytes, zero lines, or non-text content — neither whether it proceeds into round 1 nor whether it is a pre-flight rejection, nor under which exit code.

### 12. [UNANSWERABLE] FR-023 names the verdict set ANSWERED, UNANSWERABLE, CONTRADICTED, but the specification never states the criteria the round-2 instruction must convey for choosing between them — for a question the text answers only partially, which verdict is correct, and where is that boundary defined without reaching outside this document to glossary.md?

- **Target:** FR-023
- **Evidence:**
  > line 170: - **FR-023**: The round-2 instruction MUST direct the model to answer each question using only the specification text, assigning exactly 1 verdict per question from the 3-value set ANSWERED, UNANSWERABLE, CONTRADICTED (FR-024, FR-032).
  > line 343: All other terms are used exactly as defined in `glossary.md` (SUE, Socratic question, Round 1, Round 2, Verdict, Finding, Deterministic assembly, Isolation contract, Grounding rule, Challenge report, Test seam, Corrective retry, Debug dump, ID bijection rule, ERR-CLI-MISSING pattern, Challenged spec, Acceptance run).

FR-023 names the 3-value verdict set ANSWERED, UNANSWERABLE, CONTRADICTED, but the specification states no criteria the round-2 instruction must convey for choosing between them; the boundary for a partially answered question is defined nowhere in this document — verdict terms are deferred to glossary.md, which is outside this text.

### 13. [UNANSWERABLE] AC-023 and SC-001 allow success 'within at most 3 total attempts' — what constitutes one attempt (any invocation, or only a run producing a report?), and who adjudicates, by what rule, that a generated finding 'overlaps' one of the 3 named known issues?

- **Target:** SC-001
- **Evidence:**
  > line 86: - **AC-023**: Given exactly 1 manual live acceptance run against the designated acceptance target (`specs/029-builder-spec-workbench/spec.md`), when the run completes, then a report exists whose findings overlap at least 1 of the 3 named known issues — (1) the REQ-009 "time order" vs AC-010 "most recent first" ordering conflict, (2) the REQ-017/REQ-019/REQ-028 quality-score recording loop, (3) the undefined active-run pointer of REQ-002 — within at most 3 total attempts (SC-001, FR-034).
  > line 268: - **SC-001**: When the manual live acceptance run executes against the designated acceptance target, a report is generated whose findings overlap at least 1 of the 3 named known issues, within at most 3 total attempts (AC-023, FR-034).

AC-023 and SC-001 permit success 'within at most 3 total attempts' and require that findings 'overlap at least 1 of the 3 named known issues', but the text never defines what constitutes one attempt (any invocation versus only a report-producing run), who adjudicates overlap, or by what rule overlap between a generated finding and a named known issue is judged.

## Audit appendix

<details>
<summary>Audit appendix — 2 ANSWERED question(s)</summary>

### Q1 — AC-002 requires the report header to state 'exactly 4 facts', yet FR-036 requires 4 base facts plus a truncation note whenever truncation occurred — when a truncated run's report is checked against AC-002, which count is authoritative?

- **Answer:** FR-036 is the governing count: the header states exactly 4 base facts — specification path, run date, question count, finding count — 'plus the FR-019 truncation note when truncation occurred'. The glossary defines the truncation note as a 'report-header remark', not a fifth fact, so AC-002's 'exactly 4 facts' remains satisfied on a truncated run: 4 facts always, with the note as an additional remark.
- **Answering lines:**
  > line 206: - **FR-036**: The report header MUST state exactly 4 base facts — specification path, run date, question count, finding count — plus the FR-019 truncation note when truncation occurred (AC-002).
  > line 26: - **AC-002**: Given a completed challenge run, when the operator opens the challenge report, then the report header states exactly 4 facts: the specification path, the run date, the question count, plus the finding count (FR-036, AC-001).
  > line 341: - **Truncation note**: The report-header remark recorded when round 1 returned more questions than the configured maximum and the list was cut to the first N (FR-019).
  > line 70: - **AC-020**: Given valid round-1 output holding more than N questions, when validation runs, then exactly N questions remain — the first N in returned order (FR-019) — with the report header carrying 1 truncation note (FR-036).

### Q9 — U-007 reserves exit 2 for executable-not-found and routes 'every other launch or output failure' to the parse-failure path — when the executable exists but cannot be launched (for example permission denied), is spending FR-028's single corrective retry on a command that can never launch, then exiting 3 instead of 2, the intended behavior?

- **Answer:** Yes — the resolved decision U-007 states 'Exit 2 only for executable-not-found; every other launch or output failure takes the parse-failure path', encoded in FR-012 and FR-030. A permission-denied launch is therefore a launch failure other than executable-not-found, so it consumes the FR-028 corrective retry and ends at exit code 3 on the second failure by design.
- **Answering lines:**
  > line 315: | U-007 exit-2 boundary | Exit 2 only for executable-not-found; every other launch or output failure takes the parse-failure path | FR-012, FR-030 |
  > line 138: - **FR-012**: If the model-command executable named by FR-007 cannot be found, the challenge script MUST exit with code 2, printing exactly 1 message that contains an installation pointer (ERR-003, AC-014).
  > line 189: - **FR-030**: On the second parse failure in the same round, the challenge script MUST exit with code 3 after saving the raw output of the failing calls into exactly 1 directory named `.sue-debug` beside the specification (ERR-004, AC-015). For a timed-out call, the saved raw output is whatever partial output was drained within the shutdown grace period, possibly empty.

</details>
