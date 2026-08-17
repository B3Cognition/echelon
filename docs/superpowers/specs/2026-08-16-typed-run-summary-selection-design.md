# Typed Run-Summary Selection Design

## Status and relationship to the earlier design

This design replaces the free-form agent response contract in
`2026-08-12-worked-on-summary-agent-design.md`. It retains that design's user
experience, emit-once boundary, separate fast/low SUMMARIZER agent, deterministic
fallback, and single-banner presentation. It replaces only the unsafe division
of responsibility in which SUMMARIZER authored prose and Echelon attempted to
infer whether that prose was truthful.

The implementation must remove the free-form compatibility path. There must not
be a hidden adapter that accepts model-authored sentences and converts them into
typed facts.

## Goal

End every valid Echelon spec or delivery lifecycle command with a concise,
human-readable account of what was accomplished, verified, or left unfinished.
The separate inexpensive agent decides which supported facts matter most and in
which order to present them. Echelon owns every rendered claim.

This converts summary validation from open-ended natural-language
classification into strict schema and set-membership validation.

## Trust boundary

Echelon owns:

- the fact catalog and the exact human-readable text of each fact;
- terminal status, result, provider-limit, quality-debt, and next-step truth;
- catalog and output bounds;
- response validation, deterministic fallback selection, and rendering; and
- the command exit code and all durable run state.

SUMMARIZER owns only:

- selection of the most useful eligible fact IDs; and
- the order of those selected IDs.

SUMMARIZER cannot create, paraphrase, combine, negate, or qualify a claim. The
renderer copies exact text from the controller-owned catalog. Model output is
never displayed directly.

## Typed fact catalog

### Fact type

The shared summary module introduces an immutable `SummaryFact` value with four
fields:

```python
@dataclass(frozen=True)
class SummaryFact:
    category: SummaryFactCategory
    importance: SummaryFactImportance
    text: str
    source_order: int
```

`SummaryFactCategory` has the following closed values:

- `outcome`: a bounded description of what the invocation accomplished;
- `work`: a material implementation, specification, repair, or publication
  event;
- `verification`: an authoritative check result;
- `blocker`: the reason useful work could not continue; and
- `handoff`: durable state prepared for a subsequent action, excluding the
  literal next command.

`SummaryFactImportance` has the closed values `critical`, `high`, and `normal`.
It controls packet truncation and deterministic fallback, not factual
authority. `source_order` records the producer's original order and provides a
stable final tie-breaker.

Fact producers must supply complete, display-ready sentences. They must describe
semantic events Echelon already understands, rather than infer work from a list
of changed files. Paths and artifact names may appear only when the artifact is
itself a meaningful outcome.

### Catalog construction

`RunSummaryContext.facts` changes from `tuple[str, ...]` to
`tuple[SummaryFact, ...]`. All internal exit-path producers migrate to the typed
interface. No string-fact overload remains.

The catalog builder:

1. admits only typed facts with valid enum values, non-empty text, one complete
   sentence, no terminal controls, and at most 280 UTF-8 bytes; invalid producer
   facts are excluded rather than exposed to the agent;
2. adds a deterministic controller-authored outcome fact when the producer did
   not provide one;
3. orders facts by importance and then `source_order` for packet admission;
4. assigns invocation-local IDs `f0001`, `f0002`, and so on after admission;
5. retains the existing 12 KiB serialized packet ceiling; and
6. returns an immutable ID-to-fact mapping used by both validation and
   rendering.

IDs are stable for one summary invocation and deterministic for identical
context. They are not persisted and carry no authority outside that invocation.
An untyped string is never admitted. If producer input is missing or invalid,
the bounded deterministic outcome fact still guarantees a human-readable
fallback.

Controller templates may include normalized task titles, labels, or paths from
run state. Existing terminal sanitization and byte limits still apply to those
values before catalog admission.

## Selector protocol

### Evidence packet

SUMMARIZER receives schema version 2 with bounded command and task context plus
the eligible catalog:

```json
{
  "schema_version": 2,
  "command": "echelon delivery run 014",
  "task": "Implement the approved greeting utility",
  "status": "done",
  "facts": [
    {
      "id": "f0001",
      "category": "work",
      "importance": "high",
      "text": "Implemented the approved greeting utility."
    },
    {
      "id": "f0002",
      "category": "verification",
      "importance": "high",
      "text": "The focused verification passed."
    }
  ]
}
```

The packet no longer contains inspected file contents. Such contents cannot
authorize a fact, and providing them would invite the agent to reason about
claims it has no permission to write. Provider-limit, accepted-debt, result,
and next-step values remain controller-owned presentation data and are not
selectable facts.

### Agent response

SUMMARIZER returns exactly one strict JSON object:

```json
{"selected_fact_ids":["f0001","f0002"]}
```

Validation requires:

- the root value is an object with the sole key `selected_fact_ids`;
- the value is an array of strings;
- every ID is an exact member of the invocation's admitted catalog;
- IDs are unique;
- when at least two facts are available, the response contains two through four
  IDs and never more IDs than are available;
- when exactly one fact is available, the sole valid response contains that one
  ID; and
- when no fact survives validation, the selector is not invoked and the
  deterministic outcome fallback is rendered.

One unknown, repeated, malformed, missing, or excessive ID invalidates the
whole response. Echelon does not partially accept model output or retry the
agent. A selection that would exceed the existing seven-line or 1,200-byte
`Worked on` presentation bound after mandatory rows are included is also
invalid. The prompt tells the selector to prefer two facts when provider-limit
or debt rows are present, minimizing avoidable fallback.

The deployed SUMMARIZER prompt is rewritten as an evidence-ranking prompt. It
must not ask the model to author or improve prose. The agent remains
`model_tier: fast` and `effort: low`, runs in the empty temporary directory, and
uses normal tool availability for the configured provider. Tools have no role
in satisfying the ID-only response contract.

## Selection and fallback

For a valid response, the selected ID order is the rendered narrative order.

For provider errors, timeouts, missing prompts, malformed responses, or any
schema violation, deterministic selection operates on the same immutable
catalog:

1. sort by importance and then `source_order`;
2. select the first fact;
3. add the earliest remaining fact from each not-yet-represented category;
4. fill remaining positions in sorted order; and
5. stop at three facts, or earlier when the catalog is exhausted or the
   seven-line/1,200-byte presentation bound would be exceeded.

This favors material facts and category diversity while remaining concise and
fully reproducible. Summary failure never changes the original command's exit
code, state, routing, or recovery instruction.

## Rendering and visible output

The renderer resolves selected IDs against the immutable catalog and copies the
stored `text` values exactly. Length and terminal-safety enforcement occurs at
catalog admission, so selected fact text is neither clipped nor semantically
interpreted during rendering.

The existing emit-once command boundary remains responsible for producing one
terminal banner on every valid spec run, spec continue, spec resume, delivery
run, delivery continue, and delivery resume exit, including controller and
coordinator exceptions after a run has been identified.

The banner has one `Worked on` section. Result and Next remain ordinary rows,
not nested banners. Provider-limit and accepted-quality-debt details are
mandatory deterministic rows and cannot be omitted by SUMMARIZER:

```text
Worked on
  Implemented the requested Hello World program.
  The focused verification passed.

Result
  Specification completed.

Next
  echelon delivery run 014
```

When a provider limit and accepted quality debt both apply, both rows are
shown. Neither is sacrificed to narrative line limits or deduplicated against
selected facts.

## Component boundaries

The summary subsystem has five isolated responsibilities:

1. **Fact producers** translate authoritative run events into `SummaryFact`
   values at spec, delivery, and exception exit paths.
2. **Catalog builder** validates facts, applies bounds, assigns IDs, and returns
   the immutable mapping.
3. **Selector adapter** constructs the schema-v2 packet, invokes SUMMARIZER, and
   validates the closed selection contract: JSON shape, count, uniqueness,
   presentation bounds, and exact ID membership.
4. **Deterministic selector** chooses diverse high-importance facts without a
   provider.
5. **Renderer** resolves selected facts and combines them with mandatory banner
   rows.

The current free-form bullet validator, claim segmentation, semantic-verdict
regular expressions, contradiction classifier, prose deduplication, and raw
inspection-content packet are deleted. Exact deterministic rows do not require
semantic deduplication because their content is excluded from the selectable
catalog.

## Testing

### Unit tests

Unit coverage must prove:

- typed fact validation and rejection of untyped strings;
- deterministic ID assignment, priority admission, value bounds, and the 12 KiB
  bound;
- exact schema-v2 prompt construction with no inspected file contents;
- valid ordering plus rejection of unknown, repeated, excessive, missing, and
  malformed IDs;
- exact catalog-text rendering with no model prose path;
- deterministic fallback priority, category diversity, and one-fact behavior;
- provider error and timeout fallback without retry;
- mandatory result, Next, provider-limit, and debt rendering; and
- removal of the semantic regex classifier and its adversarial prose matrix.

### Command and integration tests

Command-level tests cover all supported verbs, delegated resume/continue paths,
successful and unfinished states, and controller/coordinator exceptions. They
assert exactly one summary banner and preservation of the original exit code.

Integration tests use fake providers and durable run state to prove that fact
producers run only after the relevant state transition is authoritative. The
provider matrix confirms the separate fast/low agent and normal tool
availability across configured providers.

### Safety tests

Task text and fact text remain untrusted prompt values. Prompt-injection-shaped
values may influence which admitted IDs the model selects, but cannot create a
new rendered claim. Tests prove that instruction-like values, Unicode controls,
ANSI/OSC sequences, and attempted JSON delimiter injection either remain inert
encoded data or are rejected before catalog admission. Tool use, provider
progress, stderr, and any text outside the strict JSON object never reach the
banner.

### Acceptance and regression verification

After focused tests pass, verification includes:

- the summary, CLI, skill, provider, and orchestrator suites;
- proportional-repair, quality-debt, completion-outbox, and Git-first recovery
  regressions;
- package/deployment and canonical bundle checks;
- the documented repository test runner and full pytest comparison against
  explicitly recorded baseline failures; and
- a fresh initialized workspace running the proportional Hello World scenario,
  confirming the real model-selected ID path, exactly one terminal banner, and
  no fallback or provider-progress leakage.

The live smoke test evaluates summary behavior at the actual CLI exit. A later
unrelated downstream failure does not invalidate evidence that the proportional
specification stage and typed selector behaved correctly, but it must be
reported separately and truthfully.

## Performance and deployment

The selector keeps the 30-second upper timeout, bounded packet, one invocation,
and fast/low execution profile. Its output is smaller than the former prose
response, and failure requires no repair loop or second call.

The neutral Prosaic prompt and all deployed copies are updated through the
existing deployment path. No configuration switch is introduced. The feature
remains always enabled for covered lifecycle commands and safe when the
provider is unavailable.

## Non-goals

- Allowing SUMMARIZER to author or paraphrase prose.
- Inferring implementation or verification from repository contents.
- Replacing deterministic result, provider-limit, quality-debt, cost, blocker,
  or next-step fields.
- Persisting narrative selection or prose into canonical run state.
- Changing proportional-repair, Git-first restore, routing, or delivery
  semantics.
- Fixing the separately recorded Tasks Lexicon recovery-command or publication
  defects as part of this summary redesign.
