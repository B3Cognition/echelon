# Terminal Handoff Summary Design

## Goal

Make every Phase A lifecycle exit produce one compact, useful terminal handoff.
The handoff must preserve authoritative controller state, surface provider limits
as a secondary operational cause, replace dry summary bullets with grounded
engineering prose, and avoid a separate duplicate `NEXT STEP` banner.

This extends the existing `Worked on` SUMMARIZER feature. It does not change
provider selection, recovery authority, or lifecycle exit codes.

## Terminal Contract

Phase A `run`, `continue`, and `resume` exits render exactly one lifecycle banner.
Its content is grouped in this order:

1. concise run identity and task;
2. completed work;
3. authoritative stop reason and any secondary provider-limit observation;
4. result metrics;
5. a paragraph-style `worked on` handoff;
6. an actionable `next` section when the run is unfinished or ready to advance.

Representative blocked output:

```text
╭─ ✈ echelon · SQUAD SUMMARY ──────────────────────────────────────────────────╮
│  ✗ BLOCKED                                                                   │
╰──────────────────────────────────────────────────────────────────────────────╯

  spec       912-prosaic-provider-owned-model
  mode       semi
  task       Implement provider-owned model selection in Prosaic.
  current    phase3-plan

  done
  ────
  22 phases completed

  stopped    controller_state_contract_validation_failed
  provider   You've hit your session limit · resets 5pm (Europe/Prague)

  result
  ──────
  blocked · 3h 27m · $45.0082 · 31,879,022 tokens

  worked on
  ─────────
  Produced the proportional implementation specification for provider-owned model selection.
  Defined resolution precedence, configurable mappings, and removal of the legacy capability field.
  Added explicit verification requirements for resolution, lossy handling, and generated artifacts.
  The run stopped when the provider session limit prevented phase3-plan from returning its result.
  The controller preserved the incomplete phase for retry.

  next
  ────
  echelon spec continue
  Wait for the provider reset, then retry the blocked phase without rewind.
```

The `task` value is the first non-empty cleaned line, truncated to 160 characters
with an ellipsis when necessary. The complete user request remains available in
run state and artifacts but is not repeated inside the terminal banner.

Commands that do not render a lifecycle summary may continue to use a standalone
`NEXT STEP` banner. Only duplicate next-step output following a Phase A lifecycle
summary is removed.

## Dual-Cause Provider Limits

A provider limit can prevent an agent from returning the required Echelon result.
In that case, result preparation must still fail closed under the authoritative
reason `controller_state_contract_validation_failed`. Echelon must also preserve
the provider adapter's bounded, extracted limit message as an operational
observation for the current dispatch.

The summary renders both facts:

```text
stopped    controller_state_contract_validation_failed
provider   You've hit your session limit · resets 5pm (Europe/Prague)
```

The provider observation does not replace the stop reason, alter the recovery
instruction, weaken result validation, or change the exit code. It is accepted
only from the canonical detached provider result, never inferred by scraping the
terminal during rendering.

Provider-limit state must be cleared when a later dispatch starts or completes
without a current limit. A historical message must never appear on an unrelated
failure or successful continuation.

## Evidence Model

`WorkedOnEvidence` remains a bounded, JSON-serializable packet. It is extended
with facts that can be obtained from durable run state or canonical result data:

- elapsed duration when known;
- meaningful decisions and outcomes;
- exact verification summaries and known failures;
- commits explicitly attributable to the run, when recorded;
- the authoritative blocker;
- a secondary provider-limit observation;
- the next command and recovery guidance.

Evidence collectors must not infer ownership of arbitrary repository commits or
working-tree changes. A commit is included only when lifecycle state or a
canonical result explicitly attributes it to the run. Missing evidence is omitted
rather than guessed.

The packet retains its byte bound. Lower-value repeated identifiers and artifact
inventories are trimmed before outcome, verification, blocker, provider-limit,
or next-action facts.

Attributed commits are represented as bounded `short SHA — subject` strings.
Verification facts retain recorded counts and command names when durable state
provides them; a generic passed/failed statement is used only when that is the
full available evidence.

## Grounded Narrative Candidates

Echelon deterministically converts the bounded evidence packet into four-to-eight
short narrative candidates. Each candidate has a stable opaque ID, rendered text,
and a priority. Candidate text is controller-owned and may contain only facts
copied from or deterministically derived from durable evidence.

The candidate builder produces outcome-first prose rather than raw inventory. It
may describe recorded progress, material outcomes or decisions, exact verification
facts, explicitly attributed commits, the authoritative blocker, a secondary
provider-limit observation, and the recorded next action. Sparse early failures
still receive four factual lines by describing the attempted command, absence of
recorded progress, stop condition, and recovery action. It does not invent filler.

Candidates containing commands preserve the exact cleaned durable command as an
opaque value. Echelon does not parse shell quoting or attempt semantic validation
of generated shell prose because the model never authors command text.

## SUMMARIZER Contract

SUMMARIZER remains a separate `fast` model with `low` effort and normal provider
tool availability. Its task is evidence synthesis, not repository discovery.
The prompt instructs it to use the supplied bounded evidence as the source of
truth and not to inspect unrelated workspace state.

SUMMARIZER receives candidate IDs with their controller-owned narrative text and
returns exactly one JSON object with one `line_ids` key. Its value contains four
to-eight unique candidate IDs in the preferred reading order. It cannot author or
rewrite terminal prose. Unknown IDs, duplicate IDs, too few or too many IDs, or a
response that omits a mandatory blocker, provider-limit, or next-action candidate
is invalid. The terminal renders only text looked up from the controller-owned
candidate map; no model-authored string reaches the banner.

Content priority is:

1. the meaningful outcome;
2. material implementation or specification changes;
3. verification and explicitly attributed commits;
4. the authoritative blocker and secondary provider cause;
5. readiness or remaining work.

The selected prose therefore cannot claim success for blocked work, turn phase
names or file inventories into the main narrative, invent verification, alter
shell quoting, or omit a supplied provider limit when it materially explains the
stop. These properties are enforced by candidate construction and required IDs,
not heuristic natural-language validation.

## Deterministic Fallback

Provider unavailability, timeout, malformed output, or unsupported output falls
back silently to deterministic candidate ordering. The fallback follows the same
unbulleted four-to-eight-line format and uses the same evidence priorities.

The fallback must explicitly mention a current provider-limit observation and
must remain useful even when only status, blocker, completed-phase count, and the
next command are available.

## Next-Step Integration

Next-step analysis is separated from presentation. A pure planner returns the
subtitle-independent guidance fields currently used by `_print_next_steps`.
Lifecycle renderers append the relevant guidance as a `next` section inside their
existing banner. Standalone status surfaces may pass those fields to the existing
`NEXT STEP` banner renderer.

This preserves specialized guidance for human decisions, safe rewinds, manual
recovery, build readiness, delivery, and provider resets while preventing a
second banner after `SQUAD SUMMARY` or the corresponding continue/resume handoff.

Nested resume-to-continue execution must still emit only one final lifecycle
summary. Existing emit-once scope behavior remains the authority for suppressing
duplicate `worked on` sections.

## Error Handling and Safety

- Result-contract validation remains fail-closed.
- Provider messages remain cleaned, bounded, and treated as untrusted text.
- SUMMARIZER output is validated only as a closed selection of candidate IDs.
- Terminal prose is always looked up from controller-owned candidate text.
- SUMMARIZER errors and progress output remain quiet.
- Raw model JSON never reaches the terminal.
- Missing optional evidence never blocks lifecycle completion or recovery output.
- Existing exit codes and retry commands remain unchanged.

## Testing

Test-first implementation covers:

1. a provider limit plus missing Echelon result retains the contract failure as
   the authoritative stop reason;
2. the same exit renders one explicit provider-limit line;
3. later non-provider failures and successful continuations do not render stale
   provider-limit messages;
4. long multi-line task prompts render as one bounded task line;
5. valid SUMMARIZER output selects four-to-eight unique known candidate IDs;
6. unknown, duplicate, undersized, oversized, timed-out, and failed SUMMARIZER
   calls use the paragraph-style deterministic fallback;
7. mandatory blocker, provider-limit, and next-action candidates cannot disappear
   from selected or fallback blocked handoffs;
8. exact verification and explicitly attributed commits appear when present and
   are omitted when absent;
9. Phase A run, continue, and resume exits each emit one lifecycle banner, one
   `worked on` section, and no following `NEXT STEP` banner;
10. nested resume-to-continue execution still emits once;
11. standalone status and recovery commands retain actionable next-step output;
12. lifecycle exit status and recovery commands are unchanged.

Focused tests cover the evidence model, SUMMARIZER response validation, Phase A
CLI rendering, controller preparation failure, provider-state cleanup, and
next-step planning. The bundle checks and the broader relevant CLI/controller
suite run before completion.

## Out of Scope

- Allowing SUMMARIZER to discover work by scanning arbitrary repository state.
- Passing raw provider transcripts into the summary prompt.
- Changing controller authority, recovery policy, or lifecycle exit codes.
- Removing standalone `NEXT STEP` banners from commands without an enclosing
  lifecycle summary.
- Claiming commits, tests, or implementation outcomes that are not explicitly
  represented by durable evidence.
- Rendering any free-form model-authored prose in the terminal handoff.
