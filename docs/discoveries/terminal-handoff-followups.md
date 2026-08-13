# Terminal Handoff Follow-up Discoveries

## Why this document exists

The first implementation of human-readable Echelon run summaries explored a
much broader terminal-handoff architecture than the summary feature needs. The
experimental implementation is preserved on branch
`feat/worked-on-summary-agent` at commit `62424c8a` for comparison and future
reference. It must not be merged wholesale into the simplified summary work.

The simplified feature has one boundary: when a top-level Echelon spec or
delivery run returns control to the user, print one concise human-readable
summary. The following discoveries are deliberately deferred because they may
improve Echelon independently of that feature.

## 1. Structured provider failures

Provider adapters should eventually expose a small structured failure taxonomy,
for example `rate_limit`, `session_limit`, `authentication`, `context_limit`,
and `provider_unavailable`. Recovery logic, status output, and summaries could
then use the same authoritative information.

Do not implement this by correlating or reconstructing arbitrary stdout and
stderr streams. Classification belongs at the provider-adapter boundary, as
close as possible to the provider's canonical result.

## 2. Unified terminal handoffs

Run status, stop reason, result metrics, and next-step guidance are currently
assembled in several CLI paths. A future presentation refactor could introduce
a small deterministic `RunHandoff` value and one renderer used by spec and
delivery commands.

This should remain independent of AI summarization: the handoff remains useful
when no model is available, and the model supplies only the optional narrative.

## 3. Durable run outcomes

Echelon could benefit from a compact durable record of meaningful outcomes,
decisions, verification results, and commits explicitly attributed to a run.
That record could improve `status`, `resume`, auditability, and future UI
integrations.

It should be written by the controller from canonical lifecycle results. It
should not infer ownership from arbitrary repository files, Git history, or
natural-language validation.

## 4. Provider-output sanitation

Untrusted provider output should be cleaned at a shared display or adapter
boundary before it reaches a terminal. This is general terminal safety, not a
summary concern.

A future implementation should prefer a small established sanitizer or a
central, narrowly specified utility. It should not introduce a summary-specific
multi-stream terminal protocol unless a demonstrated provider contract requires
one.

## 5. Lifecycle conformance tests

The exploration exposed behavioral drift between `run`, `continue`, and
`resume`. A future test suite could parameterize the top-level lifecycle
contract: one final handoff, preserved exit status, correct recovery command,
and no duplicate next-step presentation.

These tests should exercise externally visible command behavior without
requiring every internal return path to know about terminal presentation.

## Ideas intentionally not preserved

The following belong to the discarded implementation approach rather than the
future-work backlog:

- closed candidate-ID selection for model output;
- natural-language grounding and claim validators;
- parsing verification commands from prose;
- reconstructing provider limits across stdout and stderr;
- summary-specific persisted provenance state;
- coupling summary generation to controller contract validation.

They solved risks created by an overly ambitious summary contract. The simpler
top-level summary should use bounded controller context, a clear prompt, and a
deterministic fallback instead.
