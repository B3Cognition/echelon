# Socratic Consensus Report

- **Specification:** specs/030-build-sue-challenge-script/spec.md
- **Run date:** 2026-07-20
- **Readers:** 3 completed
- **Per-reader findings:** R1(structural)=12, R2(behavioural)=14, R3(adversarial)=11
- **Stable findings:** 4 · sampling noise: 27
- **Elenchus:** 4 follow-up chain(s) completed

## Stable findings

### 1. [CONTRADICTED] (support 3) FR-036 requires the report header to state 'exactly 5 base facts' including a resolved model provider, but AC-002 requires the header to state 'exactly 4 facts' (spec path, run date, question count, finding count) with no provider fact at all. Which count governs the header's contents — 4 or 5?

- **Target:** FR-036
- **Category:** contradiction
- **Reader variants:**
  - R2: FR-036 mandates 5 base header facts including 'resolved model provider,' but AC-002 states the header holds exactly 4 facts and does not list a provider fact. Which is authoritative, and does the header actually carry 4 or 5 facts?
  - R3: AC-002 states the report header contains exactly 4 facts (path, date, question count, finding count), but FR-036 states the header carries exactly 5 base facts (adding resolved model provider). Which count governs, and is AC-002 missing an element or is FR-036 introducing an unreferenced addition?
- **Evidence:**
  > line 29: - **AC-002**: Given a completed challenge run, when the operator opens the challenge report, then the report header states exactly 4 facts (FR-036, AC-001):
  > line 30:   - (a) the specification path,
  > line 31:   - (b) the run date,
  > line 32:   - (c) the question count,
  > line 33:   - (d) the finding count.
  > line 218: - **FR-036**: The report header MUST state exactly 5 base facts — specification path, run date, resolved model provider, question count, finding count — plus the FR-019 truncation note when truncation occurred (AC-002). The run date is the ISO calendar date `YYYY-MM-DD` in the operator's local timezone, rendered as the single `**Run date:**` header bullet; NFR-004's byte-identical comparison excludes exactly that line. The provider fact keeps environment-resolved runs auditable (runtime provider selection, 2026-07-19); it is stable across reruns and participates in NFR-004's comparison.

AC-002 states the report header states exactly 4 facts — specification path, run date, question count, finding count — with no provider fact, while FR-036 (which AC-002 itself cites) states the header MUST state exactly 5 base facts — specification path, run date, resolved model provider, question count, finding count. The two cross-referencing requirements give different counts and different fact lists for the same header.

**Elenchus [CONTRADICTED]:** Since FR-036's 5-fact list (line 218) explicitly adds a provider fact that AC-002's 4-fact list (lines 29-33) omits entirely, is AC-002 the stale artifact that must be amended to add the provider bullet, or is FR-036's provider fact the erroneous addition that must be deleted to match AC-002 — which of the two is authoritative and which gets corrected?

  > line 29: - **AC-002**: Given a completed challenge run, when the operator opens the challenge report, then the report header states exactly 4 facts (FR-036, AC-001):
  > line 30:   - (a) the specification path,
  > line 31:   - (b) the run date,
  > line 32:   - (c) the question count,
  > line 33:   - (d) the finding count.
  > line 218: - **FR-036**: The report header MUST state exactly 5 base facts — specification path, run date, resolved model provider, question count, finding count — plus the FR-019 truncation note when truncation occurred (AC-002). The run date is the ISO calendar date `YYYY-MM-DD` in the operator's local timezone, rendered as the single `**Run date:**` header bullet; NFR-004's byte-identical comparison excludes exactly that line. The provider fact keeps environment-resolved runs auditable (runtime provider selection, 2026-07-19); it is stable across reruns and participates in NFR-004's comparison.

AC-002 states the report header states 'exactly 4 facts (FR-036, AC-001)' listing only specification path, run date, question count, and finding count — while explicitly citing FR-036 as its source. But FR-036 itself states the header 'MUST state exactly 5 base facts — specification path, run date, resolved model provider, question count, finding count'. AC-002's own citation of FR-036 is inconsistent with FR-036's actual content, and the text nowhere states which of the two is the stale artifact to be corrected — it simply contains both counts without resolving the discrepancy.

### 2. [UNANSWERABLE] (support 3) FR-036 introduces 'resolved model provider' as a header fact, but no requirement defines what a 'provider' is, how it is derived from an arbitrary FR-003 command line, or what value it takes when the command is a test stub rather than a real vendor CLI.

- **Target:** FR-036
- **Category:** undefined-term
- **Reader variants:**
  - R2: FR-036's 'resolved model provider' fact assumes a provider can be resolved from what FR-003/FR-007 define only as an arbitrary shell command line. What observable string is written into the header when the model-command option is a stub test script rather than a recognizable provider binary?
  - R3: FR-036 introduces 'resolved model provider' as a header fact, but no requirement defines how a provider is derived from the FR-003 model-command string (e.g. from executable name, from output content, from a lookup table). What are the possible provider values and the resolution algorithm?
- **Evidence:**
  > line 218: - **FR-036**: The report header MUST state exactly 5 base facts — specification path, run date, resolved model provider, question count, finding count — plus the FR-019 truncation note when truncation occurred (AC-002). The run date is the ISO calendar date `YYYY-MM-DD` in the operator's local timezone, rendered as the single `**Run date:**` header bullet; NFR-004's byte-identical comparison excludes exactly that line. The provider fact keeps environment-resolved runs auditable (runtime provider selection, 2026-07-19); it is stable across reruns and participates in NFR-004's comparison.

FR-036 only says the provider fact 'keeps environment-resolved runs auditable (runtime provider selection, 2026-07-19); it is stable across reruns and participates in NFR-004's comparison.' No requirement defines what constitutes a 'provider,' how it is derived from an arbitrary FR-003/FR-007 command line, or what value is recorded when the command is a test stub.

**Elenchus [UNANSWERABLE]:** Is 'resolved model provider' an operator-supplied configuration value independent of the FR-003 command line, or must the challenge script derive it by parsing the command string itself — and in the latter case, what literal value does line 218's provider fact take when that command is a test stub with no real vendor identity?

  > line 218: - **FR-036**: The report header MUST state exactly 5 base facts — specification path, run date, resolved model provider, question count, finding count — plus the FR-019 truncation note when truncation occurred (AC-002). The run date is the ISO calendar date `YYYY-MM-DD` in the operator's local timezone, rendered as the single `**Run date:**` header bullet; NFR-004's byte-identical comparison excludes exactly that line. The provider fact keeps environment-resolved runs auditable (runtime provider selection, 2026-07-19); it is stable across reruns and participates in NFR-004's comparison.

The only mention of 'resolved model provider' is FR-036's line stating the header must include it and that 'The provider fact keeps environment-resolved runs auditable (runtime provider selection, 2026-07-19); it is stable across reruns and participates in NFR-004's comparison.' Nothing in the specification defines whether this value is operator-supplied, parsed from the FR-003 model-command string, or resolved some other way, nor what literal value it takes when the command is a test stub with no real vendor identity.

### 3. [UNANSWERABLE] (support 2) A-001 states as an unvalidated assumption that 'the model command can be driven non-interactively with prompt in, extractable JSON out,' yet FR-008 and FR-026 are written as if this always holds. If the designated acceptance run's real model command turns out not to satisfy A-001, which requirement governs the resulting behavior rather than leaving it as an open spike outcome?

- **Target:** FR-008
- **Category:** hidden-assumption
- **Reader variants:**
  - R3: The entire two-call mechanism (FR-008) depends on A-001 — that the model command supports non-interactive prompt-in/JSON-out — yet A-001 is explicitly marked unvalidated pending an OQ-001 spike. Should any FR be treated as settled before this foundational assumption is confirmed?
- **Evidence:**
  > line 338: | A-001 | The model command can be driven non-interactively with prompt in, extractable JSON out | unvalidated (OQ-001 spike before HOW) | FR-008, FR-026 |
  > line 142: - **FR-008**: When a challenge run executes, the challenge script MUST perform exactly 2 logical model calls: round-1 question generation (FR-014) plus round-2 answering (FR-021) — except exactly 1 when valid round-1 output contains 0 questions, in which case FR-020 governs and round 2 never launches.
  > line 193: - **FR-026**: When raw model output is received, the challenge script MUST extract exactly 1 JSON object from it, tolerating surrounding non-JSON text plus code fences (FR-016, FR-024). When more than 1 candidate object is extractable, the first extractable object wins, in this precedence: whole-output parse, first fenced block, first balanced-brace candidate. A candidate that parses to a non-object JSON value (for example a bare array) is a parse failure at that precedence level, not a fall-through. A fenced block is any triple-backtick fence regardless of language tag; the balanced-brace scan is string-literal-aware (brace characters inside JSON string literals never affect the balance count).

A-001 lists 'the model command can be driven non-interactively with prompt in, extractable JSON out' as an unvalidated assumption tied to spike OQ-001, but FR-008 and FR-026 are written unconditionally. No requirement specifies which behavior governs if the real acceptance model command fails to satisfy A-001.

**Elenchus [UNANSWERABLE]:** If the real acceptance-run model command fails to satisfy A-001 (line 338) — e.g., every call yields output with no extractable JSON — does that failure get handled as an ordinary failed call through FR-013's parse-failure/retry path feeding FR-026 (lines 142, 193), or does it instead block the acceptance run entirely as a spike go/no-go failure before FR-008 ever applies?

  > line 338: | A-001 | The model command can be driven non-interactively with prompt in, extractable JSON out | unvalidated (OQ-001 spike before HOW) | FR-008, FR-026 |
  > line 318: | OQ-001 | How exactly is the prompt delivered to the model command, and with which output flags? Decides extraction design details and the stub replay contract. | FR-026, FR-028 implementation freeze; stub fixture design | unknowns.md U-001 (should-resolve-before-HOW) |
  > line 142: - **FR-008**: When a challenge run executes, the challenge script MUST perform exactly 2 logical model calls: round-1 question generation (FR-014) plus round-2 answering (FR-021) — except exactly 1 when valid round-1 output contains 0 questions, in which case FR-020 governs and round 2 never launches.
  > line 152: - **FR-013**: When a corrective retry launches under FR-028, the challenge script MUST grant that retry exactly 1 fresh timeout budget equal to the FR-004 value (NFR-001). A model call that exits with non-zero status, or produces empty stdout, is classified as a failed call on the parse-failure path before any extraction — its output is never consumed even when it would parse (U-007).
  > line 193: - **FR-026**: When raw model output is received, the challenge script MUST extract exactly 1 JSON object from it, tolerating surrounding non-JSON text plus code fences (FR-016, FR-024). When more than 1 candidate object is extractable, the first extractable object wins, in this precedence: whole-output parse, first fenced block, first balanced-brace candidate. A candidate that parses to a non-object JSON value (for example a bare array) is a parse failure at that precedence level, not a fall-through. A fenced block is any triple-backtick fence regardless of language tag; the balanced-brace scan is string-literal-aware (brace characters inside JSON string literals never affect the balance count).

A-001 is listed as 'unvalidated (OQ-001 spike before HOW)' and OQ-001 asks how the prompt is delivered and notes it affects 'FR-026, FR-028 implementation freeze; stub fixture design' — both framed as pre-implementation resolution items, not as a runtime gating mechanism for the acceptance run. The specification never describes what happens if the real acceptance-run model command fails to satisfy A-001 during the actual run: it does not state whether such a failure is handled via the ordinary FR-013/FR-026 parse-failure path or instead blocks the acceptance run as a separate spike go/no-go failure.

### 4. [UNANSWERABLE] (support 2) FR-013 classifies empty stdout as an automatic failed call. Does stdout consisting only of whitespace or newlines count as 'empty' and skip extraction, or does it proceed to FR-026/FR-027 extraction and fail there instead?

- **Target:** FR-013
- **Category:** missing-boundary
- **Reader variants:**
  - R3: FR-013 classifies a call as failed only on non-zero exit status or empty stdout. What happens to a call that exits 0 with non-empty stdout that is entirely unparseable noise mixed with stderr content, or a process terminated by signal rather than a normal exit code — do these route through FR-013 or fall through to FR-027 extraction failure?
- **Evidence:**
  > line 152: - **FR-013**: When a corrective retry launches under FR-028, the challenge script MUST grant that retry exactly 1 fresh timeout budget equal to the FR-004 value (NFR-001). A model call that exits with non-zero status, or produces empty stdout, is classified as a failed call on the parse-failure path before any extraction — its output is never consumed even when it would parse (U-007).

FR-013 only states that a call producing 'empty stdout' is classified as a failed call before any extraction. The text never defines whether whitespace-only or newline-only stdout qualifies as 'empty' versus being passed on to FR-026/FR-027 extraction.

**Elenchus [UNANSWERABLE]:** Should FR-013's 'empty stdout' check (line 152) be a strict zero-byte test — so whitespace/newline-only output instead falls through to FR-026/FR-027 extraction and fails there — or should it be a trimmed/whitespace-stripped test that classifies whitespace-only output as an automatic failed call under FR-013 itself?

  > line 152: - **FR-013**: When a corrective retry launches under FR-028, the challenge script MUST grant that retry exactly 1 fresh timeout budget equal to the FR-004 value (NFR-001). A model call that exits with non-zero status, or produces empty stdout, is classified as a failed call on the parse-failure path before any extraction — its output is never consumed even when it would parse (U-007).
  > line 131: - **FR-005**: If the specification path is missing, unreadable, or contains 0 non-whitespace characters (an empty specification is unchallengeable), the challenge script MUST exit with code 1 after launching exactly 0 model calls (ERR-001, AC-013).

FR-013 states only that a call which 'produces empty stdout, is classified as a failed call on the parse-failure path before any extraction' without specifying whether 'empty' means strictly zero bytes or whitespace-stripped emptiness. Elsewhere the spec does use an explicit whitespace-aware definition for a different case — FR-005's '0 non-whitespace characters (an empty specification is unchallengeable)' — but this qualifier is not repeated or cross-referenced in FR-013, so the text does not establish whether whitespace/newline-only stdout is treated as an automatic FR-013 failure or falls through to FR-026/FR-027 extraction.

## Sampling appendix (support below threshold)

- [UNANSWERABLE] (R1, AC-023) A-004 notes the acceptance target's three named known issues were 'validated at base commit ef2643c9' and instructs to 're-verify or freeze before the run,' but no functional requirement or acceptance scenario obligates that re-verification. What enforces it, and what is the specified outcome for AC-023/SC-001 if the acceptance target has since changed and no longer contains the cited lines?
- [UNANSWERABLE] (R1, ERR-004) FR-030 states that when the debug dump write itself fails, its single diagnostic line 'governs over ERR-004's save wording' — implying ERR-004's plain claim that raw output 'is saved' can be false in practice. Should ERR-004 be reworded to reflect the best-effort nature of the dump directly, rather than being silently overridden by a cross-reference in a different requirement?
- [UNANSWERABLE] (R2, FR-010) FR-010 calls the temporary working directory 'neutral,' yet the Limitations section admits operator-level ambient configuration outside any working directory may still load. What observable test would distinguish a directory that actually achieves isolation from one that only appears to?
- [UNANSWERABLE] (R2, FR-002) FR-002 enforces no upper bound on the requested question count. When N is large enough that the round-1 prompt exceeds the model's context window (per A-005), what observable outcome occurs — a parse failure, a hang converted by timeout, or an undefined behavior?
- [UNANSWERABLE] (R2, FR-025) FR-025's identifier bijection check compares round-2 answer identifiers against the kept round-1 identifiers. Is this comparison exact-string, or is any normalization (case-folding, whitespace trimming) applied before a mismatch is classified as a parse failure?
- [UNANSWERABLE] (R2, FR-034) FR-034 introduces an exit code 1 for report-write failure occurring after a successful model run, but the Error Handling Summary's only exit-1 entries (ERR-001, ERR-002) are pre-flight, zero-model-call conditions. Under which ERR class does NFR-005's required single diagnostic line get attributed for this post-run exit-1 case?
- [UNANSWERABLE] (R2, FR-030) FR-030's 5-second shutdown grace period, repeated up to 4 times, already consumes up to 20 of NFR-001's 60-second local-processing allowance in the worst case. What minimum time is actually guaranteed to remain for report assembly and debug-dump writing on that path?
- [UNANSWERABLE] (R2, FR-018) FR-018's line-numbering scheme assumes the model faithfully echoes back the same line numbers it was shown in FR-039-cited evidence, rather than inventing or shifting numbers. What observable mechanism verifies a cited evidence line number actually reflects what the model was given, versus a hallucinated one?
- [UNANSWERABLE] (R2, AC-023) AC-023/SC-001 caps the manual acceptance run at 3 total attempts. What observable outcome or exit state is mandated if all 3 attempts fail to produce a finding overlapping any of the 3 named known issues?
- [UNANSWERABLE] (R2, FR-042) FR-042 requires exactly 0 writes to the challenged specification across every outcome, and FR-034 guards against the report path resolving onto the specification file — but does the FR-030 debug-dump write into `.sue-debug` carry any equivalent guard if that directory path resolves onto the specification file itself (e.g., via a symlink or unusual naming)?
- [UNANSWERABLE] (R2, FR-012) FR-012/ERR-003 define an 'installation pointer' testably as exactly 1 URL occurrence in the message. What observable rule distinguishes a genuine URL occurrence from a bare domain name or a package-manager install command that names no URL?
- [UNANSWERABLE] (R2, FR-028) FR-028 requires the corrective retry to append 'an appended corrective instruction naming the validation failure.' For an FR-025 bijection failure specifically, what content must that instruction observably name — the specific missing/duplicate/unknown identifiers, or just a generic description of 'a validation failure'?
- [UNANSWERABLE] (R2, NFR-002) NFR-002 restricts the script's runtime to CPython >= 3.11 stdlib only. What observable behavior occurs if the operator's installed Python is older than 3.11 — is there a version pre-flight check with a defined exit code, or does the script fail with an unspecified error at an unspecified point of execution?
- [UNANSWERABLE] (R3, FR-007) FR-007 specifies splitting the model-command option via POSIX shell quoting conventions but does not state what happens when the value contains malformed quoting (e.g. an unbalanced quote). Does that fail the exit-code-1 argument path, or is it undefined behavior?
- [UNANSWERABLE] (R3, FR-034) FR-034 requires rejecting with exit code 1 before any model call when the report path resolves to the challenged specification file itself, but this case is not assigned to ERR-001 through ERR-005 nor to any AC. What diagnostic message and error class does NFR-005 require here?
- [UNANSWERABLE] (R3, FR-016) FR-016 requires each question to carry exactly 1 target that is 'a requirement identifier or general,' but no requirement defines the accepted format for a requirement identifier during validation. Is any non-empty string accepted, or must it match a pattern like FR-\d{3}?
- [UNANSWERABLE] (R3, SC-001) AC-023/SC-001 caps the live acceptance run at 'at most 3 total attempts.' Does an 'attempt' mean one full script invocation (across which internal FR-028 corrective retries don't count separately), or does every corrective retry inside a single run also consume one of the 3 attempts?
- [UNANSWERABLE] (R3, NFR-004) NFR-004 requires byte-identical report bodies across two assembly passes with only the run-date field excluded, and FR-036 says the provider fact 'participates in' that comparison. If provider resolution depends on runtime environment state that could vary between passes, how is byte-identical reproducibility guaranteed?
- [UNANSWERABLE] (R1, general) The Key Entities description of 'Challenge Run' lists its attributes as specification path, maximum question count, challenge model command, per-call timeout, exit code, and run date — omitting the resolved model provider that FR-036 requires in every report header. Is the provider a run attribute the entity model simply forgot, or is it computed some other way that bypasses the run's own state?
- [UNANSWERABLE] (R3, FR-018) FR-018 assumes prefixing every specification line with its line number preserves enough fidelity for the model to reliably cite correct line numbers back in FR-039 evidence. Is there any guidance for how this interacts with very long lines or lines containing embedded newlike characters that could confuse the model's counting?
- [UNANSWERABLE] (R3, NFR-002) NFR-002 requires 'exactly 0 additional installed components beyond the standard runtime plus the model command itself' on a fresh checkout, yet permits pytest as an additional import for tests. Does 'installed' mean present at test-run time (a pre-existing virtualenv is fine) or does it forbid any environment where pytest had to be installed as part of setup?
- [UNANSWERABLE] (R1, FR-016) FR-016 and FR-037 both require a question/finding 'target' that is 'a requirement identifier or general,' but no requirement specifies the valid identifier syntax (FR-###, AC-###, NFR-###, ERR-###, SC-###, a free-text label?) or how round-1 validation would reject a malformed or nonexistent identifier the model invents.
- [UNANSWERABLE] (R1, FR-007) FR-007 calls its shlex-based, POSIX-quoting split of the model-command option 'platform-independent,' yet POSIX shell-quoting rules do not correctly parse native Windows path syntax (backslashes, drive letters). Does the spec assume the script is never invoked with a Windows-style command line, or is 'platform-independent' only a claim about parsing consistency rather than correctness on every OS?
- [UNANSWERABLE] (R1, FR-002) FR-002 removes any upper bound on the requested question count and passes it straight into the round-1 instruction, while A-005 admits the model's context window is unguarded in v1. What actually happens — under which existing failure path, if any — when an operator-supplied N is large enough to blow the round-1 or round-2 context budget?
- [UNANSWERABLE] (R1, FR-005) FR-005 treats a specification as invalid when it is 'missing, unreadable, or contains 0 non-whitespace characters,' but never states whether a file that exists and is permission-readable yet fails to decode as text (binary content, invalid encoding) counts as 'unreadable' or falls into unhandled behavior.
- [UNANSWERABLE] (R1, NFR-001) NFR-001/SC-004 bound wall-clock time at '4 timeout budgets plus 60 seconds,' but the timeout itself is an unbounded, operator-configured value (FR-004). Since the bound scales automatically with whatever the operator sets, is this success criterion falsifiable at all, or is it true by construction regardless of what actually causes a run to be slow?
- [UNANSWERABLE] (R1, FR-030) FR-030 references 'the up-to-4 grace periods' as if it were an established constant, but no requirement derives why 4 is the right count, nor addresses what that count becomes when round 2 never launches under FR-020 (leaving at most 2 possible timed-out attempts, not 4) for that run.

_Audit: 7 question(s) across all readers were ANSWERED by the specification text and discarded; see per-reader runs for detail._
