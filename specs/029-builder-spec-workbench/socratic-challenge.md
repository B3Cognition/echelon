# Socratic Challenge Report

- **Specification:** /Users/ladislavbihari/myWork/echelon/specs/029-builder-spec-workbench/spec.md
- **Run date:** 2026-07-19
- **Questions:** 15
- **Findings:** 13

## Findings

### 1. [CONTRADICTED] REQ-010 uses SHOULD for incremental journal loading, yet it carries a hard 2-second CONSTRAINT and AC-010 requires that the view 'does not read the whole file before first paint' — if the acceptance criterion fails whenever the recommendation is skipped, is the SHOULD actually a MUST, and which normative strength is intended?

- **Target:** REQ-010
- **Evidence:**
  > line 71: THEN: the workbench SHOULD load journal entries incrementally rather than reading the whole file at once
  > line 72: OUTPUT: a paginated decision-trail view that renders the most recent entries first
  > line 73: CONSTRAINT: initial decision-trail paint at most 2 seconds for journals up to 10000 entries
  > line 258: GIVEN: a reasoning journal with twelve thousand entries
  > line 259: WHEN: the builder opens the decision-trail view
  > line 260: THEN: the most recent entries render first and the view does not read the whole file before first paint

The normative strengths conflict. Line 71 makes incremental loading advisory: 'the workbench SHOULD load journal entries incrementally rather than reading the whole file at once'. But line 73 attaches a hard bound ('CONSTRAINT: initial decision-trail paint at most 2 seconds for journals up to 10000 entries') and AC-010 makes the behavior a pass/fail criterion: 'the most recent entries render first and the view does not read the whole file before first paint' (line 260). An implementation that skips the SHOULD fails the acceptance criterion, so the text simultaneously treats incremental loading as optional and as mandatory.

### 2. [UNANSWERABLE] REQ-023 blocks saves whenever the run state reports an in-progress dispatch, but REQ-029 concedes that the state file may be partially written or momentarily unavailable during exactly that window — what does the spec assume about the workbench's ability to reliably detect a dispatch from a file that may be unreadable at the moment of the save attempt, and does an unreadable state default to allowing or blocking the write?

- **Target:** REQ-023
- **Evidence:**
  > line 164: GIVEN: a spec run whose state reports an in-progress dispatch
  > line 166: THEN: the workbench MUST NOT write the staging artifact while that dispatch is in progress
  > line 206: GIVEN: a spec run whose state file is being written during an active dispatch
  > line 208: THEN: the workbench MUST tolerate a partially written or momentarily unavailable state file and keep the last consistent values on screen
  > line 209: OUTPUT: a run view that keeps presenting the last consistent state without error during a mid-dispatch write

Gap: the spec never states the default save behavior when the state file is unreadable at the moment of a save attempt. REQ-023 blocks saves when 'a spec run whose state reports an in-progress dispatch' (lines 164, 166), and REQ-029 concedes the state file may be 'partially written or momentarily unavailable' during exactly that window (lines 206, 208), but REQ-029 only prescribes display behavior ('keep the last consistent values on screen'). No requirement or error case says whether an unreadable state defaults to allowing or blocking the write, nor how a dispatch is reliably detected from an unreadable file.

### 3. [UNANSWERABLE] REQ-012 and REQ-017 require the workbench to present gate codes, line numbers, category scores, and pass-or-fail verdicts parsed from the lexicon and understanding commands — what output contract (format, schema, versioning) is being assumed of these external CLIs, and what happens when an installed version emits output the workbench cannot parse?

- **Target:** REQ-012
- **Evidence:**
  > line 86: THEN: the workbench MUST run the lexicon validator against the spec file and present every finding with its gate code, message, and source line number
  > line 87: OUTPUT: a findings list where each entry shows the gate code, the message, the source line number, and the overall pass-or-fail verdict
  > line 123: THEN: the workbench MUST run the understanding scan and present the overall score together with each category score and its pass-or-fail gate badge
  > line 124: OUTPUT: a quality panel showing the overall score and the seven category scores, each with a pass-or-fail badge against its threshold
  > line 357: ERROR: ERR-CLI-MISSING
  > line 358: WHEN: the builder requests validation or scoring but the required command is not installed on the path
  > line 359: THEN: the workbench reports that the command is unavailable and points the builder to install the substrate, leaving the current view usable

Gap: no output contract for the external CLIs is specified. The spec requires presenting gate codes, messages, and source line numbers from the lexicon validator (lines 86-87) and overall plus category scores from the understanding scan (lines 123-124), but nowhere defines the format, schema, or versioning of those commands' output. The only defined CLI failure mode is ERR-CLI-MISSING for a command 'not installed on the path' (lines 357-359); there is no defined behavior for an installed command that emits unparsable output.

### 4. [UNANSWERABLE] REQ-022 lets the builder save an edited spec whenever no dispatch is in progress — what is assumed about the orchestrator or another process never having modified the file on disk since the builder opened it, and is the intended behavior a silent last-writer-wins overwrite?

- **Target:** REQ-022
- **Evidence:**
  > line 157: GIVEN: a spec run that is not currently executing a squad dispatch
  > line 158: WHEN: the builder edits and saves the spec file in the workbench
  > line 159: THEN: the workbench MUST persist the edited spec file to the run staging directory and record the save time
  > line 160: OUTPUT: an updated spec file on disk plus a confirmation that names the save time
  > line 318: GIVEN: a run with no dispatch in progress and an open spec file
  > line 319: WHEN: the builder changes a requirement line and saves
  > line 320: THEN: the spec file on disk contains the change and the workbench presents the save time

Gap: the spec is silent on concurrent modification of the spec file between open and save. REQ-022 only conditions the save on 'a spec run that is not currently executing a squad dispatch' (line 157) and requires persisting the edit and recording the save time (lines 159-160); AC-022 likewise checks only that 'the spec file on disk contains the change' (line 320). Nothing addresses whether the orchestrator or another process may have changed the file since it was opened, so neither a conflict check nor a last-writer-wins overwrite is specified.

### 5. [UNANSWERABLE] REQ-013 triggers re-validation after 'a short settle interval', but the interval's duration is never fixed — how short is short, is it configurable, and what happens if the builder resumes typing while a triggered validation is still running?

- **Target:** REQ-013
- **Evidence:**
  > line 93: WHEN: the builder pauses editing for a short settle interval
  > line 94: THEN: the workbench MUST re-run the lexicon validator on the working spec and present the updated findings without a manual request
  > line 95: OUTPUT: a findings list that refreshes after each settle interval while the builder edits
  > line 96: CONSTRAINT: validation refresh presented at most 3 seconds after the builder pauses
  > line 274: WHEN: the builder pauses editing for the settle interval

Gap: the settle interval's duration is never defined. REQ-013 says only 'the builder pauses editing for a short settle interval' (line 93), and the CONSTRAINT bounds presentation at 3 seconds after the pause (line 96) without fixing the interval itself, stating whether it is configurable, or defining what happens if the builder resumes typing while a triggered validation is still running.

### 6. [UNANSWERABLE] REQ-021 requires presenting every bullet the workbench 'could not map' — by what criteria is a bullet judged unmappable, and could two conforming implementations legitimately disagree on which bullets land in the review list?

- **Target:** REQ-021
- **Evidence:**
  > line 150: GIVEN: a spec file detected as the legacy requirement-bullet form
  > line 151: WHEN: the builder requests conversion to the controlled-grammar form
  > line 152: THEN: the workbench MUST produce a controlled-grammar draft and present every bullet it could not map for builder review
  > line 153: OUTPUT: a controlled-grammar draft plus a list of unmapped bullets awaiting builder review
  > line 313: GIVEN: a legacy requirement-bullet spec with one bullet the workbench cannot map to a controlled-grammar block

Gap: no mappability criteria are given. REQ-021 requires presenting 'every bullet it could not map for builder review' (line 152) and AC-021 posits 'one bullet the workbench cannot map to a controlled-grammar block' (line 313), but the spec never defines what makes a bullet mappable or unmappable, so two conforming implementations could legitimately disagree on which bullets land in the review list.

### 7. [UNANSWERABLE] REQ-027 activates the build-handoff when 'Phase A artifacts have converged' — where is convergence defined, which artifact or state field asserts it, and who or what makes that determination?

- **Target:** REQ-027
- **Evidence:**
  > line 192: GIVEN: a spec run whose Phase A artifacts have converged
  > line 193: WHEN: the builder chooses to hand the spec off to the build phase
  > line 343: GIVEN: a run whose Phase A artifacts have converged

Gap: convergence is never defined. REQ-027's GIVEN and AC-027 both say 'a spec run whose Phase A artifacts have converged' (lines 192, 343), but no requirement, artifact, or state field is named as asserting convergence, and the spec does not say who or what makes that determination.

### 8. [UNANSWERABLE] REQ-016 requires every 'domain identifier' in the spec to be marked resolved or unresolved — what syntactic or semantic rule identifies a token as a domain identifier in the first place, as opposed to ordinary prose?

- **Target:** REQ-016
- **Evidence:**
  > line 114: GIVEN: a controlled-grammar spec validated against a controlled-vocabulary glossary
  > line 116: THEN: the workbench MUST present every domain identifier in the spec marked as resolved against the glossary or unresolved
  > line 117: OUTPUT: a term-resolution view listing each domain identifier with a resolved or unresolved marker against the glossary
  > line 288: GIVEN: a controlled-grammar spec containing one domain identifier present in the glossary and one absent from it

Gap: 'domain identifier' is never defined. REQ-016 requires presenting 'every domain identifier in the spec' as resolved or unresolved against the glossary (lines 116-117), and AC-016 assumes identifiers present or absent from the glossary (line 288), but no syntactic or semantic rule is given for distinguishing a domain identifier from ordinary prose.

### 9. [UNANSWERABLE] REQ-017's output names 'the seven category scores' each badged against 'its threshold' — where are the seven categories enumerated, where do the per-category and overall threshold values come from, and can they differ between runs?

- **Target:** REQ-017
- **Evidence:**
  > line 123: THEN: the workbench MUST run the understanding scan and present the overall score together with each category score and its pass-or-fail gate badge
  > line 124: OUTPUT: a quality panel showing the overall score and the seven category scores, each with a pass-or-fail badge against its threshold
  > line 125: CONSTRAINT: quality scan result presented at most 10 seconds after the request
  > line 293: GIVEN: a spec file whose overall quality score is below the overall threshold
  > line 295: THEN: the quality panel presents the overall score with a failing badge and the seven category badges
  > line 298: GIVEN: a per-requirement scan in which one requirement scores below the testability threshold

Gap: the seven categories and threshold sources are never specified. REQ-017's OUTPUT names 'the seven category scores, each with a pass-or-fail badge against its threshold' (line 124), AC-017 references 'the overall threshold' and 'the seven category badges' (lines 293, 295), and AC-018 names only one category, testability (line 298). Nowhere are the seven categories enumerated, nor is it stated where the per-category or overall threshold values come from or whether they can differ between runs.

### 10. [UNANSWERABLE] REQ-028 permits run changes only through 'sanctioned commands' — which commands are sanctioned, where is that list maintained, and how does the workbench (or a tester of AC-028) determine whether a given command is on it?

- **Target:** REQ-028
- **Evidence:**
  > line 202: OUTPUT: run changes that occur only through sanctioned commands, leaving the run state file and the journal written by the orchestrator alone
  > line 173: THEN: the workbench MUST invoke the echelon run command with the provided description and autonomy mode and register the resulting run in the run list
  > line 180: THEN: the workbench MUST forward the answers through the resume command and then reflect the resulting status change
  > line 187: THEN: the workbench MUST record the approval through the continue command and let the run proceed to the next phase
  > line 347: AC: AC-028
  > line 350: THEN: the run state file and the reasoning journal are written by the orchestrator and not by the workbench

Gap: the sanctioned-commands list is never defined. REQ-028's OUTPUT requires 'run changes that occur only through sanctioned commands' (line 202), and the spec names individual commands the workbench invokes — the echelon run command (line 173), the resume command (line 180), and the continue command (line 187) — but it never states that these constitute the sanctioned set, where such a list is maintained, or how the workbench or a tester of AC-028 determines whether a given command is on it.

### 11. [UNANSWERABLE] REQ-001 bounds first paint at 2 seconds only 'for up to 200 runs' — what behavior is required at 201 or 2000 runs: degraded performance, pagination, truncation, or is the requirement simply silent there?

- **Target:** REQ-001
- **Evidence:**
  > line 7: THEN: the workbench MUST list every discovered spec run with its run identifier, status, current phase, and accumulated cost
  > line 8: OUTPUT: a run list where each row shows the run identifier, status, current phase, cost, and last-updated time
  > line 9: CONSTRAINT: run list first paint at most 2 seconds for up to 200 runs

Gap: the spec is silent beyond 200 runs. The CONSTRAINT reads 'run list first paint at most 2 seconds for up to 200 runs' (line 9), and no requirement specifies any behavior — degraded performance, pagination, or truncation — for 201 or more runs.

### 12. [UNANSWERABLE] REQ-029 requires keeping 'the last consistent values' on screen during a mid-dispatch write — what should be displayed when the very first read of a run's state is inconsistent and no prior consistent values exist, and how does that case differ from ERR-RUN-UNREADABLE?

- **Target:** REQ-029
- **Evidence:**
  > line 206: GIVEN: a spec run whose state file is being written during an active dispatch
  > line 208: THEN: the workbench MUST tolerate a partially written or momentarily unavailable state file and keep the last consistent values on screen
  > line 209: OUTPUT: a run view that keeps presenting the last consistent state without error during a mid-dispatch write
  > line 353: GIVEN: a run whose state file is mid-write during an active dispatch
  > line 355: THEN: the run view keeps presenting the last consistent values and raises no error
  > line 363: WHEN: a selected run directory has a missing or unparsable state file
  > line 364: THEN: the workbench marks that run as unreadable and keeps the rest of the run list usable

Gap: the first-read case is undefined. REQ-029 prescribes keeping 'the last consistent values on screen' during a mid-dispatch write (lines 208-209), which presupposes prior consistent values exist; ERR-RUN-UNREADABLE separately handles 'a missing or unparsable state file' by marking the run unreadable (lines 363-364). The spec never says what to display when the very first read of a run's state is inconsistent and no prior values exist, nor how to decide whether that moment falls under REQ-029's tolerate-without-error behavior or the ERR-RUN-UNREADABLE marking.

### 13. [UNANSWERABLE] REQ-002's output demands that 'exactly one row carries the current-run marker' — what must the run list show when the active-run pointer is absent, names a deleted run, or names a run marked unreadable, none of which can satisfy the exactly-one condition?

- **Target:** REQ-002
- **Evidence:**
  > line 13: GIVEN: a run list in which one run is named by the active-run pointer
  > line 15: THEN: the workbench MUST mark the run named by the active-run pointer as the current run
  > line 16: OUTPUT: a run list in which exactly one row carries the current-run marker read from the active-run pointer
  > line 218: GIVEN: the active-run pointer names the second of three runs
  > line 219: WHEN: the builder opens the run list
  > line 220: THEN: the second row carries the current-run marker and the other two rows do not

Gap: the degenerate pointer cases are unspecified. REQ-002 is conditioned on 'a run list in which one run is named by the active-run pointer' (line 13) and requires 'exactly one row carries the current-run marker' (line 16), and AC-002 only tests the happy path where the pointer names an existing run (lines 218-220). No requirement states what the run list must show when the active-run pointer is absent, names a deleted run, or names a run marked unreadable.

## Audit appendix

<details>
<summary>Audit appendix — 2 ANSWERED question(s)</summary>

### Q1 — REQ-012 allows the lexicon validator up to 5 seconds to present results, yet REQ-013 requires the same validator's refreshed findings within 3 seconds of the builder pausing — how can the auto-refresh meet a tighter deadline than the validator itself is granted, and which bound governs when they conflict?

- **Answer:** The two bounds never govern the same event, so no reconciliation is needed: REQ-012's 5-second bound is scoped to the explicit trigger 'the builder requests structural validation or saves the spec' (lines 85, 88), while REQ-013's 3-second bound is scoped to the automatic trigger 'the builder pauses editing for a short settle interval' (lines 93, 96). The spec never grants the validator itself a 5-second runtime; each CONSTRAINT bounds when results must be presented for its own WHEN condition, so the manual-request path is governed by 5 seconds and the settle-interval auto-refresh path by 3 seconds.
- **Answering lines:**
  > line 85: WHEN: the builder requests structural validation or saves the spec
  > line 86: THEN: the workbench MUST run the lexicon validator against the spec file and present every finding with its gate code, message, and source line number
  > line 88: CONSTRAINT: validation result presented at most 5 seconds after the request
  > line 93: WHEN: the builder pauses editing for a short settle interval
  > line 94: THEN: the workbench MUST re-run the lexicon validator on the working spec and present the updated findings without a manual request
  > line 96: CONSTRAINT: validation refresh presented at most 3 seconds after the builder pauses

### Q3 — REQ-028 states that run changes occur only through sanctioned commands, yet REQ-022 has the workbench persist the edited spec file directly to the run staging directory — is a staging artifact 'run data', and if so, how is a direct disk write by the workbench reconciled with the sanctioned-commands-only rule?

- **Answer:** The sanctioned-commands rule is scoped to two specific files, not to all run data: REQ-028's GIVEN names 'a run state file and a reasoning journal that only the orchestrator may write' (line 199) and its THEN prohibits writing only 'the run state file or the reasoning journal directly' (line 201), with the OUTPUT clarifying the goal is 'leaving the run state file and the journal written by the orchestrator alone' (line 202). Staging artifacts are outside that scope: REQ-022 explicitly requires the workbench to 'persist the edited spec file to the run staging directory' (line 159). So a staging artifact is not orchestrator-only run data, and the direct disk write is consistent with REQ-028.
- **Answering lines:**
  > line 159: THEN: the workbench MUST persist the edited spec file to the run staging directory and record the save time
  > line 199: GIVEN: a run state file and a reasoning journal that only the orchestrator may write
  > line 201: THEN: the workbench MUST NOT write the run state file or the reasoning journal directly
  > line 202: OUTPUT: run changes that occur only through sanctioned commands, leaving the run state file and the journal written by the orchestrator alone

</details>
