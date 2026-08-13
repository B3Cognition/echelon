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

## 6. Proportional-spec loop budgets

A live Hello World workspace correctly selected the proportional
CARTOGRAPHER, but the shared quality loop still ran seven repair dispatches,
took roughly an hour, and expanded the tiny specification substantially. Role
selection alone does not make specification effort proportional.

A future improvement should make validation thresholds, repair budgets, and
escalation behavior proportional to the requested scope. This is a controller
and quality-policy concern, independent of terminal summaries.

## 7. Linked-worktree installation correctness

Running `scripts/install.sh` from a linked worktree produced an editable Python
path that targeted the repository's main checkout instead of the invoked
worktree. That makes live branch testing ambiguous and can silently execute the
wrong source tree.

The installer should resolve and verify the current checkout path explicitly,
with a regression test that installs from a linked worktree. Until then, live
worktree checks should set `PYTHONPATH` explicitly or inspect the generated
editable-install path before drawing conclusions.

## 8. Provider-neutral execution profiles

Prosaic's `model_tier` and `effort` metadata are not enforced uniformly by all
provider adapters. Claude and Codex map neutral model tiers, while reasoning
effort and provider-specific fast-model selection have different levels of CLI
support. The summarizer uses the existing policy rather than creating its own
provider matrix.

A future provider-runtime change should define supported neutral mappings,
apply them consistently where each provider exposes controls, and report the
effective model and effort. This belongs to all Echelon agents, not only the
terminal summary.

## 9. Auxiliary model-call telemetry

The final summary is an auxiliary model call, so existing phase and delivery
token totals do not include its usage or latency. Future telemetry could record
auxiliary calls separately, keeping primary run budgets understandable while
still exposing the small additional cost and fallback rate.

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
