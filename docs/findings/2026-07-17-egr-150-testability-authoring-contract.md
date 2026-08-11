# EGR-150 Testability Authoring And Analyzer Compatibility Contract

**Review date:** 2026-07-17
**Priority:** P1
**Status:** fixed
**Source incident:** OptaSearch `002-video-clips-playlists`

## Summary

CARTOGRAPHER's rich-spec authoring protocol says requirements must be testable,
but it does not state the concrete syntax that Understanding's testability
metrics recognize. A live amendment pass therefore added dozens of grounded
`Constraint:` clauses written with prose such as `equals 0`, then discovered
through repeated scans and throwaway-copy probes that `constraint_density`
recognized symbolic comparators such as `= 0` but not that grammatically valid
form. The same spec contained no explicit `MUST NOT` requirements, leaving
`negative_space_coverage` weak until the agent diagnosed the metric separately.

The authoring contract and analyzer should meet in the middle:

- CARTOGRAPHER should emit one canonical, machine-friendly form for new specs.
- Understanding should remain tolerant of grammatically correct natural-language
  equality in existing and human-authored specs.
- Both paths must prohibit invented thresholds or exclusions added only to raise
  a quality score.

## Incident Evidence

Live output from:

- workspace: `/Users/michalbachorik/work/optasearch`
- run: `runs/spec-20260716-230146-659005`
- spec: `specs/002-video-clips-playlists/spec.md`

The amendment started with a weighted testability score of approximately
`0.6469`, below the configured `0.70` gate. The agent identified
`constraint_density = 0.3617` and `negative_space_coverage = 0.4197` as the
largest available grounded levers.

Observed repair sequence:

1. The agent added 76 grounded `Constraint:` clauses to functional
   requirements, taking the total constraint labels to 95.
2. `constraint_density` moved only from `0.3617` to `0.4037`; testability
   remained failing at approximately `0.6673`.
3. A throwaway-copy probe with six `MUST NOT` bullets raised
   `negative_space_coverage`, but testability still reached only `0.6809`.
4. A second probe normalized prose equality such as `equals 0` to symbolic
   comparison such as `= 0`.
5. `constraint_density` then moved from `0.4037` to `0.7571`, and testability
   moved from `0.6673` to `0.7985`.

The useful requirement facts were already present. The extra turns were spent
discovering an undocumented syntax contract.

## Grounded Source Findings

### CARTOGRAPHER protocol is underspecified

The then-current CARTOGRAPHER protocol (now
`prosaic/subagents/echelon.cartographer.md`):

- requires every requirement to be independently testable;
- tells amendment mode to add numeric thresholds, units, and measurable hard
  constraints;
- shows `<metric comparator value unit>` only inside the derived Lexicon grammar;
- explains that a negated requirement needs a canonical numeric ID, but does not
  proactively require grounded negative/error boundaries in rich `spec.md`.

It does not tell rich-spec authors to use symbolic `<`, `<=`, `=`, `>=`, or `>`
comparators, or that testability evidence must appear on the canonical
ID-bearing requirement line.

### The rich-spec template does not demonstrate either signal

The rich-spec template (now
`prosaic/agents/exploration/templates/cartographer-spec-template.md`) showed
generic positive FR placeholders. It has no example of:

- a quantitative constraint on the requirement line; or
- an atomic `MUST NOT` / `SHALL NOT` requirement for a grounded invalid or
  prohibited outcome.

### Rich-spec extraction is line-scoped

`src/understanding/markdown_parser.py` gives structured FR/REQ/NFR ID lines
priority over other Markdown content. Consequently, a nested rich-spec metadata
bullet such as `Constraint: ...` is not folded into the extracted requirement
text. Lexicon `CONSTRAINT:` lines are folded explicitly, but rich `spec.md`
constraint text must remain on the canonical ID-bearing line to affect
per-requirement testability metrics.

### Equality grammar is unnecessarily narrow

`src/understanding/constraint_metrics.py` recognizes symbolic equality (`= 0`)
and the phrase `equal to 0`, but not the grammatically valid verb form
`equals 0`. It should accept `equals <numeric value>` as compatibility syntax
without changing the canonical authoring form.

## Required Fix

### 1. Add a paired CARTOGRAPHER authoring invariant

Add an ALWAYS / NEVER pair to the invariant protocol:

```markdown
### Rule 13 - Machine-Recognizable Testability

ALWAYS express every evidence-backed quantitative boundary using the canonical
form `<metric> <comparator> <value> [unit]`, with one of `<`, `<=`, `=`, `>=`,
or `>`; encode grounded prohibited behavior and invalid outcomes with uppercase
`MUST NOT` or `SHALL NOT`.

NEVER express a quantitative comparison only in prose (`equals 0`, `no more
than 50`), rely on implicit absence or out-of-scope prose for negative behavior,
or invent thresholds and prohibitions solely to increase a quality score.
```

The NEVER rule governs CARTOGRAPHER's canonical output. It does not make
natural-language equality invalid input for Understanding.

### 2. Document the metric-visible rich-spec form

Under CARTOGRAPHER's `Spec Format Invariants`, state that measurable constraints
and negative behavior must appear on an ID-bearing requirement line. Include
valid examples such as:

```markdown
- **FR-021**: The system MUST return an empty result when no records match. Constraint: `result_count = 0`.
- **FR-022**: The system MUST limit each page. Constraint: `page_size <= 50 items`.
- **FR-023**: The system MUST NOT expose records outside the requesting user's authorized scope.
```

Also state that agents must preserve an unknown rather than inventing a value or
prohibition unsupported by user input, verified evidence, domain rules, or
established boundaries.

### 3. Make first-pass and amendment guidance actionable

Update CARTOGRAPHER's functional-requirement and amendment instructions to:

- use symbolic comparator syntax on the requirement line;
- model grounded prohibited behavior, invalid outcomes, and error boundaries as
  atomic `MUST NOT` or `SHALL NOT` requirements;
- preserve passing requirements during targeted amendment;
- avoid metric-only bulk additions without requirement evidence; and
- use the documented forms rather than empirical throwaway-copy probing when
  these testability sub-metrics fail.

The original proposal asked CARTOGRAPHER to run a bounded diagnostic scan. That
became obsolete when Echelon introduced the provider-free
`phase1-understanding` node after every CARTOGRAPHER dispatch. The agent must not
execute or locate validators; the controller runs the deterministic check and
routes any focused amendment. SAGE remains the owner of the qualitative
WHY2/WHY3 verdict.

Do not duplicate this invariant workflow logic into
`runtime/workflow/phases/phase1-what.md`; under the repository's
dispatcher/protocol split it belongs to the CARTOGRAPHER agent protocol.

### 4. Align the rich-spec template

Update `cartographer-spec-template.md` so its FR examples demonstrate:

- a positive observable requirement with an inline symbolic constraint; and
- a grounded atomic negative requirement using uppercase `MUST NOT`.

Template prose must make the evidence-grounding rule explicit so the example is
not interpreted as a quota requiring fabricated negative requirements.

### 5. Accept grammatically valid equality in Understanding

Extend `ConstraintAnalyzer.HARD_CONSTRAINT_PATTERNS` to count
`equals <numeric value>` as a hard constraint. The compatibility form should
support at least integer and decimal digit forms while retaining the existing
symbolic and `equal to` patterns.

This is defense in depth for existing and human-authored specs. CARTOGRAPHER
should still prefer the canonical symbolic form for deterministic output.

### 6. Add regression coverage

Add focused tests proving:

- `result_count = 0` is counted as a hard constraint;
- `result count equals 0` is also counted as a hard constraint;
- the equality compatibility form does not create a soft constraint;
- explicit `MUST NOT` requirement text contributes negative-space evidence;
- CARTOGRAPHER contains the paired canonical-syntax and no-invention contract;
- the rich-spec template contains both inline symbolic-constraint and grounded
  negative-requirement examples; and
- controller-owned post-dispatch Understanding remains the only deterministic
  preflight and CARTOGRAPHER does not claim the formal SAGE verdict; and
- the phase dispatcher does not become a second copy of the invariant protocol.

## Resolution

The canonical Prosaic CARTOGRAPHER protocol now defines symbolic inline
comparators, atomic grounded negative requirements, line-scoped metric
visibility, targeted amendment, and explicit no-invention rules. Its rich-spec
template demonstrates the same forms as non-quota examples. Understanding now
accepts both `equals <integer-or-decimal>` and
`equal to <integer-or-decimal>` as compatibility input while CARTOGRAPHER emits
the symbolic canonical form.

The runtime dispatcher remains unchanged. Existing controller-owned
Understanding and SAGE routing supersedes the finding's earlier model-executed
diagnostic proposal.

## Candidate Files

- `prosaic/subagents/echelon.cartographer.md`
- `prosaic/agents/exploration/templates/cartographer-spec-template.md`
- `src/understanding/constraint_metrics.py`
- `tests/unit/test_constraint_metrics.py` or the existing focused Understanding
  constraint-metric test module
- `tests/unit/test_cartographer_templates.py`
- optionally `tests/contract/static_contracts.py` if the prompt invariant should
  be enforced through the shared static-contract suite

## Acceptance Criteria

- First-pass CARTOGRAPHER output uses symbolic comparator syntax for every
  grounded quantitative boundary it expresses.
- Quantitative and negative-space evidence intended for rich-spec scoring is on
  canonical ID-bearing requirement lines.
- Grounded prohibited behavior and invalid outcomes are explicit atomic
  `MUST NOT` or `SHALL NOT` requirements instead of implicit omissions.
- CARTOGRAPHER does not invent thresholds, units, error cases, or prohibitions to
  satisfy a metric.
- The controller runs Understanding after CARTOGRAPHER returns; CARTOGRAPHER
  does not execute validators or claim the formal gate.
- Understanding counts both `result_count = 0` and `result count equals 0` as
  hard constraints.
- Existing symbolic, `equal to`, range, unit, and negative-space recognition
  remains compatible.
- Focused prompt/template and constraint-analyzer regression tests pass.
- The implementation includes an `[Unreleased]` changelog entry and updates the
  EGR register when EGR-150 is marked fixed.
