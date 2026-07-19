# Socratic Consensus Report

- **Specification:** /Users/ladislavbihari/myWork/echelon/specs/030-build-sue-challenge-script/spec.md
- **Run date:** 2026-07-19
- **Readers:** 3 completed
- **Per-reader findings:** R1(structural)=11, R2(behavioural)=13, R3(adversarial)=8
- **Stable findings:** 6 · sampling noise: 20
- **Elenchus:** 6 follow-up chain(s) completed

## Stable findings

### 1. [UNANSWERABLE] (support 2) FR-002 rejects question-count values below 1 but states no upper bound — what governs a run invoked with a question count of 1,000,000, where the FR-015 instruction requests up to that many questions and NFR-001's fixed 60-second local-processing allowance must still cover validation, ranking, and rendering of the result?

- **Target:** FR-002
- **Category:** missing-boundary
- **Reader variants:**
  - R2: FR-002 rejects non-numeric, non-integer, and below-1 question-count values but states no upper bound. What behavior is mandated for an extreme value such as 1000000, which directly shapes the round-1 instruction, the size of both prompts, and the FR-019 truncation set?
- **Evidence:**
  > line 113: - **FR-002**: When invoked, the challenge script MUST accept a question-count option, defaulting to exactly 15, that caps round-1 questions (FR-015, FR-019). Non-numeric, non-integer, and below-1 values MUST be rejected on the exit-code-1 argument path, mirroring FR-004.
  > line 149: - **FR-015**: The round-1 instruction MUST request at most N Socratic challenge questions, where N is the FR-002 value, targeting exactly 5 weakness categories: ambiguity, hidden assumption, contradiction, undefined term, missing boundary (FR-016).
  > line 242: - **NFR-001**: When a challenge run terminates on any path, its wall-clock duration MUST be at most 4 timeout budgets (FR-004, FR-013) plus 60 seconds of local processing.
  > line 243:   - **Category:** Reliability | **Measurable Target:** wall-clock ≤ (4 × configured timeout) + 60 seconds on every terminating path

Gap: no upper bound on the question-count option is defined anywhere. FR-002 rejects only 'Non-numeric, non-integer, and below-1 values', FR-015 requests 'at most N' questions with N unbounded above, and NFR-001's allowance is a fixed '(4 × configured timeout) + 60 seconds' regardless of N. The text says nothing about what governs an extreme value such as 1,000,000 or whether the 60-second local-processing budget is expected to hold for it.

**Elenchus [UNANSWERABLE]:** Given FR-002 (line 113) rejects only non-numeric, non-integer, and below-1 values while NFR-001 (line 243) fixes local processing at 60 seconds regardless of N, what maximum question count must FR-002 enforce on the exit-code-1 argument path — or, if no maximum is imposed, which requirement is amended to state that the 60-second local-processing budget need not hold for arbitrarily large N?

  > line 113: - **FR-002**: When invoked, the challenge script MUST accept a question-count option, defaulting to exactly 15, that caps round-1 questions (FR-015, FR-019). Non-numeric, non-integer, and below-1 values MUST be rejected on the exit-code-1 argument path, mirroring FR-004.
  > line 242: - **NFR-001**: When a challenge run terminates on any path, its wall-clock duration MUST be at most 4 timeout budgets (FR-004, FR-013) plus 60 seconds of local processing.
  > line 243:   - **Category:** Reliability | **Measurable Target:** wall-clock ≤ (4 × configured timeout) + 60 seconds on every terminating path

The text imposes no maximum on the question-count option and records no amendment reconciling it with NFR-001. FR-002 rejects only 'Non-numeric, non-integer, and below-1 values' — no upper bound appears there or anywhere else — while NFR-001 fixes local processing at a flat '60 seconds' regardless of N. No requirement states a cap that FR-002 must enforce, and no requirement relaxes the 60-second budget for large N. The gap: the specification neither bounds N from above nor states that the local-processing budget scales with or is exempt from arbitrarily large question counts.

### 2. [UNANSWERABLE] (support 2) FR-040 mandates exit code 0 after any successfully written report, so a run producing 15 CONTRADICTED findings and a clean-specification run are indistinguishable by exit code — is the absence of a findings-present exit signal a deliberate boundary of the v1 interface (which later SUE tiers must keep stable), and if so, why is it not recorded under Out of Scope or Limitations?

- **Target:** FR-040
- **Category:** missing-boundary
- **Reader variants:**
  - R2: FR-040 mandates the terminal summary list 'the top 3 findings in rank order', and AC-005 only tests the case of at least 1 finding. What exactly must the summary print when 0, 1, or 2 findings exist — and in the FR-020 zero-question path, does the FR-040 summary print at all?
- **Evidence:**
  > line 214: - **FR-040**: After writing the report, the challenge script MUST print a terminal summary stating the finding count per verdict class plus the top 3 findings in rank order, then exit with code 0 (AC-005, FR-034).
  > line 29: - **AC-005**: Given a run completes with at least 1 finding, when the run finishes, then the terminal summary states the finding count per verdict class, listing the top 3 findings in rank order (FR-040, AC-001).
  > line 31: - **AC-007**: Given every round-2 verdict is ANSWERED, when the report is assembled, then the findings section states that exactly 0 findings were produced (FR-041), with the audit appendix holding every question (FR-038), with exit code 0.
  > line 284: ### Explicitly Out of Scope
  > line 293: ## Limitations (stated, not silent)

Gap: the text mandates the behavior but never addresses its rationale or records it as a boundary. FR-040 requires exit code 0 after any written report, and AC-005/AC-007 confirm exit 0 for both findings-present and clean-specification runs, but neither Out of Scope nor Limitations mentions the absence of a findings-present exit signal, and no line states whether that absence is a deliberate stable-interface decision for later SUE tiers.

**Elenchus [UNANSWERABLE]:** Since FR-040 (line 214) makes exit code 0 cover both findings-present and clean runs and neither Out of Scope (line 284) nor Limitations (line 293) records this, must the specification either reserve a distinct nonzero exit code for findings-present completions or add an explicit entry declaring exit-code-0-on-any-written-report a stable v1 interface guarantee — and which of those two amendments is chosen?

  > line 109: The command surface is fixed by the approved design: 1 positional argument, 3 options, 4 exit codes. Input problems are rejected before any model call so a failed pre-flight costs nothing.
  > line 214: - **FR-040**: After writing the report, the challenge script MUST print a terminal summary stating the finding count per verdict class plus the top 3 findings in rank order, then exit with code 0 (AC-005, FR-034).
  > line 216: - **FR-041**: When every verdict is ANSWERED, the report's findings section MUST state that exactly 0 findings were produced, with the audit appendix holding all questions plus exit code 0 (AC-007, FR-038).
  > line 286: - Multi-reader consensus, interpretation graphs, and convergence scoring — later SUE tiers; the v1 interface (specification path in, markdown report out) is stable under all of them.

The text makes exit code 0 cover both findings-present runs (FR-040: print summary of findings 'then exit with code 0') and clean runs (FR-041, AC-007), and line 109 fixes the surface at '4 exit codes' — but it never chooses either amendment the question poses. No requirement reserves a distinct nonzero exit code for findings-present completions, and no Out of Scope, Limitations, or interface-stability entry explicitly declares exit-code-0-on-any-written-report a stable v1 guarantee (line 286's stability claim covers only 'specification path in, markdown report out'). The gap: the specification is silent on which of the two amendments is chosen, or that a decision between them was ever made.

### 3. [UNANSWERABLE] (support 2) What format, precision, and timezone define the 'run date' header fact, and how is the run-date field delimited within the report so that NFR-004's byte-identical comparison can exclude exactly that field deterministically?

- **Target:** NFR-004
- **Category:** undefined-term
- **Reader variants:**
  - R3: NFR-004 demands byte-identical report bodies 'run-date field excluded', yet no requirement defines the run date's format, timezone, or delimitation in the header — how is the excluded field located for a byte comparison when its shape is nowhere specified?
- **Evidence:**
  > line 206: - **FR-036**: The report header MUST state exactly 4 base facts — specification path, run date, question count, finding count — plus the FR-019 truncation note when truncation occurred (AC-002).
  > line 248: - **NFR-004**: When identical validated answers are assembled twice, the challenge script MUST produce 2 report bodies identical outside the run-date field (FR-032, FR-036).
  > line 249:   - **Category:** Reliability | **Measurable Target:** byte-identical report bodies across 2 assembly passes, run-date field excluded
  > line 255: - **Challenge Run**: One end-to-end execution against a single challenged specification. Attributes: specification path, maximum question count, challenge model command, per-call timeout, exit code, run date. Performs 2 logical model calls (2–4 subprocess invocations including retries); produces exactly 1 challenge report on success or 1 debug dump on unrecoverable parse failure.

Gap: the 'run date' appears as a header fact (FR-036) and Challenge Run attribute, and NFR-004 excludes 'the run-date field' from its byte-identical comparison, but no line defines the date's format, precision, or timezone, nor how the field is delimited within the report so the exclusion can be applied deterministically.

**Elenchus [UNANSWERABLE]:** For the run-date fact required by FR-036 (line 206) and excluded by NFR-004's byte-identical comparison (line 249), what exact serialization is mandated — calendar format, time precision, and timezone (e.g., ISO 8601 date in UTC) — and what structural rule (such as a fixed labeled header line) delimits the field so the comparison can strip exactly that line and nothing else?

  > line 206: - **FR-036**: The report header MUST state exactly 4 base facts — specification path, run date, question count, finding count — plus the FR-019 truncation note when truncation occurred (AC-002).
  > line 248: - **NFR-004**: When identical validated answers are assembled twice, the challenge script MUST produce 2 report bodies identical outside the run-date field (FR-032, FR-036).
  > line 249:   - **Category:** Reliability | **Measurable Target:** byte-identical report bodies across 2 assembly passes, run-date field excluded

No serialization is mandated for the run-date fact. FR-036 requires only that the header 'state exactly 4 base facts — specification path, run date, question count, finding count', and NFR-004 requires report bodies 'identical outside the run-date field' / 'byte-identical report bodies across 2 assembly passes, run-date field excluded' — but the text nowhere specifies calendar format, time precision, timezone, or any structural rule (such as a fixed labeled header line) delimiting the run-date field so the comparison can strip exactly that line. The gap: neither the run-date format nor the field-delimiting rule for the NFR-004 exclusion is defined anywhere in the specification.

### 4. [UNANSWERABLE] (support 2) In FR-026's extraction precedence, what qualifies as a 'fenced block' — any triple-backtick fence or only json-tagged ones — and is the 'balanced-brace candidate' scan JSON-string-aware, so that a brace character inside a string literal does not corrupt the balance count?

- **Target:** FR-026
- **Category:** undefined-term
- **Reader variants:**
  - R3: FR-026 extracts JSON from 'raw model output' — is that stdout alone, stderr alone, or both combined, given FR-030 dumps stdout and stderr as separate files yet no requirement names the stream extraction reads from?
- **Evidence:**
  > line 181: - **FR-026**: When raw model output is received, the challenge script MUST extract exactly 1 JSON object from it, tolerating surrounding non-JSON text plus code fences (FR-016, FR-024). When more than 1 candidate object is extractable, the first extractable object wins, in this precedence: whole-output parse, first fenced block, first balanced-brace candidate. A candidate that parses to a non-object JSON value (for example a bare array) is a parse failure at that precedence level, not a fall-through.

Gap: FR-026 names the precedence 'whole-output parse, first fenced block, first balanced-brace candidate' and defines the non-object fall-through rule, but never defines what qualifies as a 'fenced block' (any triple-backtick fence versus json-tagged only) nor whether the balanced-brace scan is JSON-string-aware such that braces inside string literals do not corrupt the balance count.

**Elenchus [UNANSWERABLE]:** Within FR-026's precedence (line 181), does 'first fenced block' mean the first triple-backtick fence of any language tag or only a json-tagged fence, and must the 'balanced-brace candidate' scanner skip brace characters occurring inside JSON string literals (including escaped quotes) when counting balance — what are the two rulings?

  > line 181: - **FR-026**: When raw model output is received, the challenge script MUST extract exactly 1 JSON object from it, tolerating surrounding non-JSON text plus code fences (FR-016, FR-024). When more than 1 candidate object is extractable, the first extractable object wins, in this precedence: whole-output parse, first fenced block, first balanced-brace candidate. A candidate that parses to a non-object JSON value (for example a bare array) is a parse failure at that precedence level, not a fall-through.
  > line 304: | OQ-001 | How exactly is the prompt delivered to the model command, and with which output flags? Decides extraction design details and the stub replay contract. | FR-026, FR-028 implementation freeze; stub fixture design | unknowns.md U-001 (should-resolve-before-HOW) |

Neither ruling is given. FR-026 states the precedence — 'whole-output parse, first fenced block, first balanced-brace candidate' — but never defines whether 'first fenced block' means a fence of any language tag or only a json-tagged fence, and never states whether the balanced-brace scanner must skip brace characters inside JSON string literals (including escaped quotes). OQ-001 confirms these details are unresolved: 'How exactly is the prompt delivered to the model command, and with which output flags? Decides extraction design details'. The gap: the fence-tag rule and the string-literal-aware brace-counting rule are both undefined.

### 5. [UNANSWERABLE] (support 2) FR-016 validates round-1 line references only as integers — are references outside the specification's actual line range (or negative, or zero) accepted as valid, and given that FR-039's out-of-range marker governs only round-2 evidence rendering, what purpose do round-1 line references serve anywhere downstream, since FR-022 strips them from the round-2 prompt and FR-037 renders only answer evidence?

- **Target:** FR-016
- **Category:** missing-boundary
- **Reader variants:**
  - R3: FR-016 requires each round-1 question to carry 'a list of integer line references' — may that list be empty, may its values exceed the specification's line count, and where is any bound stated given those references are never rendered or re-checked downstream?
- **Evidence:**
  > line 151: - **FR-016**: When round-1 output is received, the challenge script MUST validate that each question carries exactly 1 unique identifier, exactly 1 question text, exactly 1 target — a requirement identifier or `general` — a list of integer line references, plus exactly 1 category from FR-015 (FR-017).
  > line 168: - **FR-022**: The round-2 prompt MUST NOT contain round-1 categories, targets, line references, or round-1 reasoning — exactly 0 of these 4 elements may appear (FR-021, AC-011).
  > line 208: - **FR-037**: Each findings entry MUST state exactly 4 elements: the verdict, the question, the target requirement identifier, plus the evidence rendered per FR-039 (FR-033).
  > line 212: - **FR-039**: For each cited evidence line number, the report MUST quote exactly 1 line of text from the specification file, stating the named gap from the answer text for UNANSWERABLE findings — satisfied by rendering the FR-024 answer text verbatim; no separate gap field exists in the answer schema (FR-018, AC-009). A cited line number outside the specification's line range MUST render as a deterministic `(not present in the specification)` marker rather than failing the run.

Gap: round-1 line references have no defined range validation and no defined downstream consumer. FR-016 validates only 'a list of integer line references' — nothing about negative, zero, or out-of-range values. FR-039's '(not present in the specification)' marker governs cited evidence rendering, FR-022 forbids round-1 'line references' in the round-2 prompt, and FR-037 renders only the answer's evidence per FR-039. No requirement states any use of round-1 line references after validation.

**Elenchus [UNANSWERABLE]:** Given FR-016 (line 151) type-checks round-1 line references as integers, FR-022 (line 168) strips them from the round-2 prompt, and FR-039 (line 212) applies its out-of-range marker only to answer evidence, is the decision that round-1 line references are accepted at any integer value (negative, zero, or beyond the file's line range) and consumed by nothing downstream — and if so, are they removed from the round-1 schema or assigned a defined consumer such as the audit appendix?

  > line 151: - **FR-016**: When round-1 output is received, the challenge script MUST validate that each question carries exactly 1 unique identifier, exactly 1 question text, exactly 1 target — a requirement identifier or `general` — a list of integer line references, plus exactly 1 category from FR-015 (FR-017).
  > line 168: - **FR-022**: The round-2 prompt MUST NOT contain round-1 categories, targets, line references, or round-1 reasoning — exactly 0 of these 4 elements may appear (FR-021, AC-011).
  > line 208: - **FR-037**: Each findings entry MUST state exactly 4 elements: the verdict, the question, the target requirement identifier, plus the evidence rendered per FR-039 (FR-033).
  > line 210: - **FR-038**: The audit appendix MUST list every ANSWERED question with its answering lines, rendered as exactly 1 collapsed section the reader can expand (AC-008, FR-032).
  > line 212: - **FR-039**: For each cited evidence line number, the report MUST quote exactly 1 line of text from the specification file, stating the named gap from the answer text for UNANSWERABLE findings — satisfied by rendering the FR-024 answer text verbatim; no separate gap field exists in the answer schema (FR-018, AC-009). A cited line number outside the specification's line range MUST render as a deterministic `(not present in the specification)` marker rather than failing the run.

The text validates round-1 line references only as 'a list of integer line references' (FR-016), excludes them from the round-2 prompt (FR-022: 'exactly 0 of these 4 elements may appear'), and applies the out-of-range marker only to cited evidence in answers (FR-039); findings entries render only verdict, question, target, and FR-039 evidence (FR-037), and the audit appendix lists ANSWERED questions 'with its answering lines' from round-2 answers (FR-038). But the text never decides the question posed: it neither confirms that round-1 line references are accepted at any integer value and consumed by nothing downstream, nor removes them from the round-1 schema, nor assigns them a defined consumer. The gap: no requirement states any range check on, or downstream consumer of, round-1 line references.

### 6. [UNANSWERABLE] (support 2) The U-007 decision routes 'every other launch or output failure' to the parse-failure path — when the model command launches, exits with a non-zero status, yet emits perfectly extractable and valid JSON on stdout, does the run treat that output as usable or classify the call as failed, and which requirement states how the subprocess exit status participates in validation at all?

- **Target:** FR-026
- **Category:** missing-boundary
- **Reader variants:**
  - R3: If a model subprocess exits with a non-zero return code but its output still yields one extractable, schema-valid JSON object, is that call a success or a failure — and where does the specification assign meaning to the subprocess exit status at all?
- **Evidence:**
  > line 315: | U-007 exit-2 boundary | Exit 2 only for executable-not-found; every other launch or output failure takes the parse-failure path | FR-012, FR-030 |
  > line 181: - **FR-026**: When raw model output is received, the challenge script MUST extract exactly 1 JSON object from it, tolerating surrounding non-JSON text plus code fences (FR-016, FR-024). When more than 1 candidate object is extractable, the first extractable object wins, in this precedence: whole-output parse, first fenced block, first balanced-brace candidate. A candidate that parses to a non-object JSON value (for example a bare array) is a parse failure at that precedence level, not a fall-through.
  > line 138: - **FR-012**: If the model-command executable named by FR-007 cannot be found, the challenge script MUST exit with code 2, printing exactly 1 message that contains an installation pointer — defined testably as exactly 1 URL occurrence in the message (ERR-003, AC-014).

Gap: no requirement mentions the subprocess exit status at all. The U-007 decision says 'Exit 2 only for executable-not-found; every other launch or output failure takes the parse-failure path', and FR-026 operates on 'raw model output', but the text never states whether a launched command that exits non-zero while emitting extractable, valid JSON is treated as usable output or as a failure, nor how (or whether) exit status participates in validation.

**Elenchus [UNANSWERABLE]:** Under the U-007 ruling (line 315) that every non-launch failure takes the parse-failure path, when the model command exits non-zero but stdout yields a JSON object that FR-026 (line 181) extracts and validates successfully, is that output accepted as the call's result or does the non-zero status force the retry/parse-failure path — i.e., is subprocess exit status declared authoritative, advisory, or ignored in output validation?

  > line 136: - **FR-011**: If a model subprocess exceeds its timeout budget (default 300 seconds, FR-004), the challenge script MUST end that call, classifying it as a parse failure routed to FR-028 (ERR-005).
  > line 183: - **FR-027**: If exactly 0 JSON objects can be extracted from raw model output, the challenge script MUST classify that output as a parse failure routed to FR-028 (FR-026).
  > line 315: | U-007 exit-2 boundary | Exit 2 only for executable-not-found; every other launch or output failure takes the parse-failure path | FR-012, FR-030 |

The text never mentions subprocess exit status in output handling. Failure classification is defined solely by extraction (FR-027: '0 JSON objects can be extracted'), schema validation (FR-016, FR-024, FR-025), and timeout (FR-011); U-007 rules that 'Exit 2 only for executable-not-found; every other launch or output failure takes the parse-failure path', but does not say whether a non-zero command exit accompanied by successfully extracted and validated JSON counts as an 'output failure' at all. The gap: the specification nowhere declares subprocess exit status authoritative, advisory, or ignored when the extracted output validates successfully.

## Sampling appendix (support below threshold)

- [CONTRADICTED] (R2, FR-021) FR-021 mandates the round-2 prompt contain exactly 2 content blocks — the line-numbered specification plus the question identifiers with texts — yet FR-023 mandates a round-2 instruction directing the model to answer from the text alone and assign verdicts. Where does that instruction physically live in the prompt without making a third content block that AC-011's recorded-prompt test would count as a violation?
- [CONTRADICTED] (R3, NFR-002) NFR-002 demands the script plus its unit tests execute with 'exactly 0 additional installed components' beyond CPython and the model command, while the same requirement permits the tests to import pytest — a component that must be installed; how can both clauses hold on a fresh checkout?
- [UNANSWERABLE] (R1, FR-018) FR-018 numbers 'every line' starting at 1 and FR-039 quotes 'exactly 1 line of text' per cited number — what definition of a line governs when the specification uses CRLF endings, lacks a trailing newline, or contains a final empty line, and what guarantees the script's line segmentation matches the segmentation the model inferred from the numbered prompt?
- [UNANSWERABLE] (R2, FR-027) What behavior is mandated when the model subprocess terminates with a nonzero exit status but writes extractable, schema-valid JSON to stdout — is the exit status consulted at all, and conversely, is a zero-status call with empty stdout distinguishable from any other parse failure?
- [UNANSWERABLE] (R2, FR-006) What testable procedure defines 'not writable' in the FR-006 pre-flight — a permission-bit inspection, an actual probe write, or something else — and what outcome is mandated when the check passes but the directory becomes unwritable by the time FR-034 writes the report?
- [UNANSWERABLE] (R2, FR-012) FR-012 requires the exit-2 message to contain exactly 1 URL as an installation pointer, but FR-043 permits any arbitrary operator-supplied command line. What URL does the script print when the missing executable is a private stub or in-house wrapper with no public installation source, and is a single hardcoded URL assumed to apply to every possible command?
- [UNANSWERABLE] (R2, FR-039) FR-039 requires quoting 'exactly 1 line of text per cited number'. When an answer's evidence list cites the same line number twice, is that line quoted twice, deduplicated, or treated as a validation failure — and does FR-024's 'list of integer evidence line references' permit duplicates at all?
- [UNANSWERABLE] (R2, NFR-005) NFR-005 mandates exactly 1 diagnostic line naming the failure class, FR-012 mandates a message containing an installation pointer, and FR-030 mandates that the diagnostic additionally name a failed debug dump. Can all of this mandated content coexist within 'exactly 1' line, and what counts as one line — one newline-terminated write to stderr, or something else?
- [UNANSWERABLE] (R2, FR-010) FR-010 isolates only the subprocess working directory, yet the Limitations section claims repository-level ambient context 'cannot reach the model'. Does the model subprocess inherit the parent's environment variables, and on what basis is cwd assumed to be the sole channel through which repository-level context can reach the model command?
- [UNANSWERABLE] (R1, FR-024) FR-024 validates that each answer carries 'a list of integer evidence line references' without a minimum length, yet FR-037 requires every findings entry to render evidence per FR-039 — what does a findings entry contain when a CONTRADICTED or UNANSWERABLE answer cites exactly 0 evidence lines, and is such an answer valid or a parse failure?
- [UNANSWERABLE] (R2, FR-001) FR-001 mandates accepting exactly 1 positional argument, but no requirement states the behavior for 0 positional arguments, 2 or more positional arguments, or an unrecognized option. Is that the exit-code-1 argument path referenced by FR-002 and FR-004, and must it emit the NFR-005 diagnostic line?
- [UNANSWERABLE] (R2, FR-018) FR-018 mandates prefixing every line with its number but defines no prefix format, and neither FR-018 nor FR-039 states how CRLF line endings, a missing trailing newline, or a final blank line are counted as lines. What exact line-numbering contract must the prompts, the FR-039 quoter, and the stub fixtures all share?
- [UNANSWERABLE] (R3, FR-012) When a single invocation simultaneously has an unreadable specification path (exit 1, FR-005) and a missing model-command executable (exit 2, FR-012), which check runs first and which exit code is emitted, given no pre-flight ordering is specified?
- [UNANSWERABLE] (R3, FR-006) FR-006 requires detecting that the specification's directory is 'not writable' before any model call — what does the pre-flight probe rest on that guarantees a later report write will succeed, given permission checks can diverge from actual write outcomes and FR-034 separately admits report-write failure after a successful run?
- [UNANSWERABLE] (R3, FR-040) FR-040 triggers the terminal summary 'after writing the report' — does it also fire on the zero-question run of FR-020 and the zero-finding run of FR-041, and what does 'the top 3 findings in rank order' print when only 1 or 2 findings exist?
- [UNANSWERABLE] (R1, FR-026) FR-026 distinguishes a candidate that 'parses to a non-object JSON value' (a parse failure at that precedence level, no fall-through) from levels that yield no candidate — when the whole output fails to parse and the first fenced block contains malformed (unparseable) JSON rather than a non-object value, does extraction fall through to balanced-brace scanning or stop as a parse failure, and does 'first fenced block' mean first in document order regardless of fence language tag?
- [UNANSWERABLE] (R1, FR-030) FR-030 fixes dump file names (`round{N}-attempt{1,2}-stdout/stderr`), states successive failing runs overwrite same-named files, and forbids the script from ever clearing `.sue-debug` — after a later successful run writes a fresh report beside a surviving stale dump, how does an operator determine that the dump does not describe the current report, given no timestamp, run identifier, or cleanup obligation exists?
- [UNANSWERABLE] (R1, SC-001) SC-001 gates v1 acceptance on a nondeterministic live model overlapping at least 1 of 3 known issues 'within at most 3 total attempts' — what counts as an attempt (does a run ending at exit code 3 consume one?), what determines overlap between a free-text finding and a named issue, and what is the disposition of the deliverable if all 3 attempts fail while A-004's target-freshness assumption sits unverified since commit ef2643c9?
- [UNANSWERABLE] (R1, FR-012) FR-012 triggers exit code 2 when the executable named by FR-007's leading word 'cannot be found' — found by what procedure: PATH lookup only, or also resolution of relative and absolute paths like `./stub.sh`, and does a file that is found but lacks execute permission take the exit-2 path or U-007's parse-failure launch path?
- [UNANSWERABLE] (R1, FR-036) FR-036 requires the header to state the 'run date' and NFR-004 requires byte-identical report bodies 'outside the run-date field' — where is the run date's granularity (date vs. timestamp), timezone, and format defined, and how is the field delimited such that NFR-004's exclusion is mechanically checkable rather than a matter of judgement?

_Audit: 13 question(s) across all readers were ANSWERED by the specification text and discarded; see per-reader runs for detail._
