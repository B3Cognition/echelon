# SUE Portability and Evidence Design

**Date:** 2026-07-30
**Status:** proposed implementation contract; implementation begins after
explicit review approval
**Branch baseline:** `f648e7be` plus the Socratic Understanding handoff and
reassessment commits
**Scope:** source portability, Codex cold readers, evidence integrity, the A1
gate, and the Research enhancements that are consistent with the authoritative
SUE decisions

## 1. Outcome

SUE will accept deterministically normalized requirement bundles rather than
assuming one Echelon Markdown ID convention. It will preserve original-source
locators from input through each private interpretation graph and the
controller-owned divergence map. Codex will become a first-class cold-reader
provider with isolated, auditable execution.

The work remains a measurement program:

- the first live check is a non-confidential Codex V1 smoke with no more than
  two calls;
- the next scientific gate is A1 on one explicitly pinned provider, with no
  more than 24 calls for two one-chunk specifications;
- cross-provider work and additional format adapters proceed only if A1 passes;
  and
- workflow integration remains disabled until A1 and bounded mutation
  validation pass.

A failed experiment is a completed result. It produces `FIX_EXTRACTION`,
`HALT`, or `INCONCLUSIVE`; it does not weaken the gate.

## 2. Authority reconciliation

This design implements `SPECIFICATION.md` and `DECISIONS.md`. Older SUE plans
remain historical experiment records. They do not override the authority order
in `AGENTS.md`.

The user's approved ordering resolves these implementation choices:

1. keep the six existing SUE tools and add shared deterministic modules;
2. preserve the current standard-library-only execution contract for the
   standalone tools;
3. add Markdown/Lexicon and generic-manifest adapters first;
4. migrate V3 from regex-discovered identifiers to bundle units;
5. add a SUE-specific cold-reader runner rather than using the normal harness
   backend unchanged;
6. use Codex for the first bounded live smoke and as the explicitly selected
   provider for the initial A1 campaign; and
7. keep workflow integration behind the existing scientific gates.

Approval of this design does **not** promote SUE to a blocking quality gate.

## 3. Research disposition

### Implement in the pre-A1 slice

- cold, non-communicating reconstruction;
- immutable source snapshots and original-source provenance;
- separate source, interpretation, and divergence knowledge maps;
- requirement-local typed graphs and behavioural assertions;
- deterministic glossary aliases without forced merges;
- minority, unmatched, and failed-reader preservation;
- exact run/provider/model/framing/pass identity;
- prompt, schema, tool, CLI, input, and decision-context digests;
- explicit repeatability versus changed-condition metadata;
- disaggregated agreement, provenance, failure, and cost measurements;
- cross-pass stable-low and stable-witness calculation;
- stale-artifact rejection; and
- explicit `INCONCLUSIVE` states for unsupported or lossy inputs.

### Implement or run only after A1 passes

- Gherkin, OpenAPI, and ReqIF adapters;
- cross-provider parity and variance attribution;
- model-assisted witness verification;
- bounded mutation validation;
- extraction-validity calibration against human-adjudicated references;
- blind H-D2 justification-graph adjudication; and
- larger-corpus or historical-outcome studies.

### Keep gated until A1 and bounded mutation validation pass

- a controller-owned Phase 3 SUE node;
- workflow state and journal contracts;
- decision-material blocking classification; and
- SAGE consumption of immutable SUE evidence.

### Exclude

- philosopher personas as reader identities;
- majority agreement as truth;
- automatic requirement rewriting;
- a compensating weighted closure score, `QScore`, or Fracture Localization
  Index;
- embedding alignment in the next prototype;
- automatic CI blocking; and
- novelty, patent-scope, or freedom-to-operate conclusions.

## 4. Architecture

```text
source artifact(s)
        |
        v
deterministic adapter
        |
        v
SUESourceBundle / SourceKnowledgeMap
        |
        +----------------------------+
        |                            |
        v                            v
cold reader run A              cold reader run N
private InterpretationGraph    private InterpretationGraph
        |                            |
        +-------------+--------------+
                      |
                      v
          controller aggregation
          DivergenceMap + evidence package
```

The source map contains only facts deterministically declared by the source or
adapter. It never contains an aggregate interpretation. Each reader receives
the same permitted source view and cannot see another run, prior output,
repository instructions, squad state, or reasoning journal.

### 4.1 Shared modules

Two standard-library modules are added beside the current tools:

- `scripts/sue_source.py` — source schema, adapters, canonical serialization,
  digests, prompt rendering, and locator validation;
- `scripts/sue_runner.py` — provider resolution, cold invocation, structured
  output capture, execution identity, and call accounting.

The six existing entry points remain:

- `sue_challenge.py`
- `sue_consensus.py`
- `sue_reproducibility.py`
- `sue_dialectic.py`
- `sue_jgraph.py`
- `sue_auto.py`

They dynamically load the shared modules using the existing standalone pattern.
No Echelon CLI or installed-extension dependency is introduced in the first
slice.

## 5. Source contract

### 5.1 Canonical bundle

`SUESourceBundle` is an immutable dataclass graph with canonical JSON
serialization:

```yaml
schema_version: 1
bundle_id: string
snapshot_digest: sha256
adapter:
  id: markdown-lexicon | manifest
  version: string
documents:
  - id: string
    source_uri: string
    media_type: string
    digest: sha256
units:
  - id: string
    kind: requirement | acceptance-criterion | constraint | rule
    text: verbatim source text
    normative_level: must | should | may | unspecified
    source_refs:
      - document_id: string
        locator_kind: line-range | json-pointer | xml-id | page-paragraph
        locator: string
    declared_relations: []
    situation:
      given: string
      when: string
      then: string
glossary:
  - canonical: string
    aliases: [string]
    source_refs: []
```

`situation` is nullable. `declared_relations` contains only relations explicitly
encoded by the source format, such as a manifest dependency or an OpenAPI
operation/schema reference. Inferred relations belong only in an
`InterpretationGraph`.

The `snapshot_digest` is SHA-256 over canonical JSON excluding the digest field
itself. Document digests cover the exact source bytes. Unit text remains
verbatim; adapters may normalize structure but may not paraphrase normative
content.

### 5.2 Unit identity

- Existing explicit IDs remain unchanged.
- Acceptance criteria nested under an identified requirement use their
  explicit ID when present.
- A structured Markdown item without an explicit ID receives
  `<document-id>:L<start>-L<end>`.
- Unstructured prose is not silently promoted to a requirement. The adapter
  returns `INCONCLUSIVE_INPUT` with actionable diagnostics unless the operator
  supplies a generic manifest.
- Duplicate IDs, overlapping ambiguous definitions, unresolved source
  references, or locator loss are hard input errors before any model call.

Synthetic IDs identify a source location, not a semantic interpretation.

### 5.3 Markdown/Lexicon adapter

The first adapter recognizes the existing SUE definition shapes plus:

- Markdown headings with requirement IDs;
- ID-prefixed paragraphs and list items;
- Lexicon `REQ` and `AC` blocks;
- normative list items containing `MUST`, `SHALL`, `SHOULD`, or `MAY`; and
- Lexicon `GIVEN` / `WHEN` / `THEN` situations.

Glossary terms and aliases are accepted only when explicitly declared.
Conflicting or one-to-many aliases remain ambiguous and never canonicalize.

### 5.4 Generic manifest adapter

The generic manifest is JSON matching the bundle fields above, except that the
adapter computes and verifies all digests. It is the escape hatch for custom,
proprietary, generated, or already-parsed formats.

Every source reference must resolve to a listed document. Embedded document
text is allowed only when its bytes and digest are present in the manifest.
External URLs are recorded as identifiers but are never fetched implicitly.

“Any specification” therefore means “any source that can produce a valid,
provenance-preserving bundle,” not “silently parse every file format.”

## 6. Interpretation and divergence maps

### 6.1 InterpretationGraph

V3 validates model output against bundle unit IDs. Each edge, assumption, and
assertion carries:

- `unit_id`;
- one or more original `source_refs`;
- reader run ID;
- provider and model;
- framing and pass;
- grounding status; and
- the existing typed edge or behavioural assertion fields.

For backward-compatible Markdown reports, a single line-range locator may still
render as `line N`. JSON evidence always stores the full source reference.

The prompt contains a deterministic source view:

1. bundle identity and allowed unit IDs;
2. verbatim unit text with stable locator labels;
3. explicitly declared glossary terms;
4. declared source relations needed by the selected units; and
5. the framing-specific extraction instruction.

It never contains another interpretation or divergence result.

### 6.2 Deterministic alignment

Alignment order is:

1. exact unit and controlled-vocabulary identifier;
2. current deterministic normalization;
3. unambiguous declared glossary canonical/alias match;
4. type-constrained structural match;
5. unmatched.

Every aligned record retains both original labels and the alignment rule used.
No ambiguous stage selects a winner. No embedding or model call participates in
alignment.

### 6.3 DivergenceMap

Aggregation emits disaggregated channels:

- exact and canonicalized typed-edge agreement;
- vocabulary divergence;
- extraction instability across same-condition passes;
- changed-condition/provider variance;
- stable-low units;
- minority and unmatched interpretations;
- stable witness candidates;
- provenance/ungrounded rates;
- reader and chunk failures; and
- calls, duration, token usage when reported, and incomplete cost data.

The report never collapses these channels into one compensating quality score.

Witness candidates are intersected across passes by unit, normalized situation,
normalized outcomes, witness kind, and source anchors. They remain
`UNVERIFIED_CANDIDATE` before the post-A1 witness-verification gate.

## 7. Cold-reader provider contract

### 7.1 Request and result

`ColdReaderRequest` contains:

```yaml
run_id: uuid
provider: claude | codex | copilot
model_command: explicit command
prompt: string
prompt_digest: sha256
output_schema_path: path-or-null
output_schema_digest: sha256-or-null
timeout_seconds: number
experiment_id: string-or-null
condition_id: string-or-null
```

`ColdReaderResult` contains:

```yaml
run_id: uuid
status: success | timeout | transport_error | unusable_output
provider: string
model_requested: string-or-unknown
model_reported: string-or-unknown
cli_version: string-or-unknown
protocol: string
argv_redacted: [string]
cwd_policy: neutral-temporary-directory
session_policy: ephemeral
configuration_policy: ignored-user-config | provider-equivalent
started_at: rfc3339
duration_ms: integer
exit_code: integer-or-null
stdout_digest: sha256
stderr_digest: sha256
raw_output_ref: string
final_output_ref: string
token_usage: object-or-null
```

Raw output and final structured output are stored inside the immutable
experiment package, not beside or inside the challenged source.

### 7.2 Codex invocation

Codex uses a fresh neutral temporary working directory:

```text
codex exec
  --ephemeral
  --skip-git-repo-check
  --sandbox read-only
  --ignore-user-config
  --output-schema <schema-file>
  --json
  --output-last-message <final-file>
  -
```

The prompt is supplied on stdin. The runner does not expose the repository,
MCP tools, AGENTS instructions, prior sessions, or another reader's files. The
exact Codex CLI version and the requested/reported model identity are evidence.

If the installed CLI cannot combine the required isolation and structured
output flags, the smoke stops before the second call.

### 7.3 Provider policy

- Scientific commands require an explicit provider-prefixed command.
- The economical Codex profile is `gpt-5.6-luna` with `low` reasoning. SUE
  exposes both values as explicit arguments, writes both into the invocation
  and evidence, and never relies on Codex's ambient model selection.
- Ordinary Codex runs may select that economical profile by an explicit SUE
  default shown in the preflight summary; operators may override it.
- `sue_auto` ordinary use resolves the ambient/default provider through the
  shared runner and records that it is non-scientific.
- Scientific A1 runs reject ambient provider or model selection.
- A provider transport may differ operationally, but its differences are
  recorded as experiment conditions.
- The current Sonnet dialogue default is retained only as a compatibility alias
  during deprecation; it is not silently used for a Codex-selected run.

## 8. Evidence package

Each experiment writes to a newly created output directory:

```text
sue-evidence/<experiment-id>/
  experiment.json
  source-bundle.json
  source-documents.json
  prompts/
  raw/
  interpretations/
  aggregate.json
  report.md
  checksums.json
```

`experiment.json` records:

- repository commit and dirty-state flag;
- source, decision-context, tool, prompt, and schema digests;
- provider/model/framing/pass matrix;
- exact same-condition and changed-condition labels;
- thresholds locked before calls;
- call, timeout, wall-clock, and privacy policy;
- per-call outcomes, including failures;
- final gate result; and
- stop reason.

The evidence package is append-only while running and sealed by
`checksums.json` at completion. A specification, decision context, tool/schema,
provider/model/framing policy, or prompt mismatch makes an old package stale.
Historical packages remain readable but cannot supply current findings.

Standalone Markdown reports remain available for compatibility. Their headers
link to the evidence package and identify whether they are current,
historical/stale, or incomplete.

## 9. Decision context

The exact decision-context schema remains experimental. This slice may accept
the proposed schema as an optional, validated input and record its digest:

```yaml
id: string
kind: implementation-readiness | architecture-choice | test-design | change-impact
question: string
in_scope_requirements: [string]
material_behaviours: [string]
severity_policy_ref: string
```

Before workflow integration, it is used only to filter/report scope and support
human review. It does not automatically promote a finding to blocking severity.
Materiality automation remains gated on OQ-003 and bounded mutation evidence.

## 10. Implementation subprojects

### A. Deterministic source and transport foundation — zero calls

1. Add `sue_source.py` and source-schema tests.
2. Add Markdown/Lexicon and generic-manifest adapters.
3. Add `sue_runner.py` and fake provider/Codex runners.
4. Move provider resolution and cold execution behind compatibility wrappers in
   `sue_challenge.py`.
5. Fix the ambient-provider test by passing an explicit empty environment.
6. Add evidence identity, redaction, and digest tests.

Acceptance:

- all focused tests pass with and without Codex runtime markers;
- identical inputs produce byte-identical canonical bundles;
- every unit locator resolves to exact original text;
- fake Codex argv and stdin meet the cold-runner contract; and
- zero live model calls occur.

### B. V3 bundle migration and trustworthy pre-A1 evidence — zero calls

1. Replace `scan_requirement_ids` as V3's source of truth with bundle units.
2. Keep the regex scanner only as a compatibility helper inside the
   Markdown/Lexicon adapter.
3. Validate all model records against bundle units and source references.
4. Implement deterministic glossary canonicalization with ambiguous matches
   left unmatched.
5. aggregate all passes rather than using the last pass for rich evidence.
6. Intersect stable witness candidates across passes.
7. Write sealed evidence packages and stale-artifact diagnostics.
8. Keep old CLI/report behavior where it does not weaken provenance.

Acceptance:

- original V3 fixtures retain equivalent scores and report meaning;
- a manifest unit with a non-Echelon ID is analyzed;
- unknown or cross-document-invalid references fail before a model call;
- vocabulary divergence is distinguishable from extraction instability;
- witnesses absent from one pass are not stable; and
- no unverified witness becomes blocking evidence.

### C. Codex smoke and A1

The smoke uses one checked-in, non-confidential fixture and at most two Codex
calls. It stops on the first isolation, transport, schema, provenance, timeout,
or evidence-sealing failure.

A1 then uses:

- `codex` with explicitly selected `gpt-5.6-luna` and `low` reasoning for the
  first preregistered campaign;
- two approved, non-confidential, one-chunk clean specifications;
- with-glossary and without-glossary conditions;
- three readers;
- two passes;
- a maximum of 24 calls;
- mean agreement `>= 0.80`;
- minimum per-spec agreement `>= 0.70`; and
- recorded component metrics, failures, durations, and token usage.

No threshold is changed after results are observed. The result is one of:

- `PASS`;
- `FIX_EXTRACTION`;
- `HALT`;
- `INCONCLUSIVE_TRANSPORT`;
- `INCONCLUSIVE_INPUT`; or
- `INCONCLUSIVE_BUDGET`.

Any non-`PASS` result stops the sequence before cross-provider work, additional
adapters, mutation calls, or workflow integration.

### D. Post-A1 portability and validation

Only after A1 `PASS`:

1. add Gherkin, OpenAPI, and ReqIF adapters with paired provenance fixtures;
2. run provider parity under an explicit provider/model matrix, with no more
   than 48 calls unless separately approved;
3. implement and validate exhibited witness verdicts
   (`INCOMPATIBLE`, `EQUIVALENT`, `UNDERDETERMINED`);
4. run the bounded, human-approved mutation smoke;
5. run extraction-validity and H-D2 studies as separate experiments; and
6. propose the controller-owned workflow integration as a new reviewed design.

PDF/DOCX remains a converter boundary. Only conversions that preserve
page/paragraph locators may enter a bundle; OCR or locator-losing conversion is
`INCONCLUSIVE_INPUT`.

## 11. Testing strategy

All implementation follows test-first development.

### Source and provenance

- canonical serialization and digest stability;
- explicit and synthetic unit IDs;
- duplicate and ambiguous IDs;
- exact line-range resolution;
- manifest JSON-pointer resolution;
- glossary exact/alias/plural/article/ambiguous/unknown cases;
- multi-document relations;
- unsupported/lossy input; and
- source mutation invalidates evidence.

### Cold runners

- Codex argv, stdin, neutral cwd, ephemeral session, ignored config, read-only
  sandbox, output schema, JSONL, and final-message capture;
- CLI/model identity and token usage;
- timeout/process cleanup;
- raw/final output digests;
- redacted diagnostics;
- partial failure preservation; and
- call-budget enforcement before launch.

### Interpretation and aggregation

- non-Echelon bundle unit IDs;
- source-ref grounding;
- no forced merge;
- same-condition repeatability labels;
- changed-condition/provider labels;
- stable-low intersection;
- stable witness intersection;
- minority/unmatched preservation;
- partial-reader degradation;
- zero successful readers;
- no weighted quality score; and
- no blocking classification from unverified evidence.

### Evidence lifecycle

- unique output directory;
- source remains unchanged;
- package sealing;
- corrupt/missing checksum;
- stale tool/schema/prompt/model/context/source identities;
- incomplete runs; and
- historical report rendering.

## 12. Call, privacy, and stop contract

| Stage | Maximum live calls | Proceed rule |
|---|---:|---|
| Source, runner, and V3 implementation | 0 | all focused tests green |
| Codex V1 smoke | 2 | transport, isolation, schema, provenance, and sealing pass |
| Single-provider A1 | 24 | both A1 thresholds pass |
| Cross-provider parity | 48 total | separately reported; no automatic truth claim |
| Bounded mutation validation | separately approved budget | preregistered A2–A4 gates pass |
| Workflow integration | 0 during implementation tests | A1 and mutation validation already passed |

Only checked-in, non-confidential fixtures may be sent during the bounded smoke
and A1. The command must disclose the provider before calls. Raw model output
may contain source text and is retained only inside the named evidence package.
Secrets, private specs, and ignored local investigation files are excluded.

Every campaign stops when:

- its call limit would be exceeded;
- wall clock exceeds twice the preregistered estimate;
- source traceability is incomplete;
- reader isolation cannot be demonstrated;
- output schema or evidence sealing fails;
- a required provider/model identity is ambient or unknown for a scientific
  run; or
- the current gate fails.

## 13. Documentation and compatibility

- README examples gain bundle/manifest and explicit provider examples only
  after the zero-call tests pass.
- Old raw Markdown CLI invocations continue to work through the default
  Markdown/Lexicon adapter.
- Existing report filenames remain compatibility views; immutable experiment
  packages are the authoritative new evidence.
- Reports clearly distinguish measured findings from hypotheses and historical
  artifacts.
- The six SUE tools remain diagnose-only and never edit source requirements.

## 14. Design review decisions

Approving this document approves:

1. the bundle, knowledge-map, source-reference, runner, and evidence-package
   contracts above;
2. the optional non-blocking decision-context input;
3. the provider-neutral ordinary-run policy and explicit scientific-run policy;
4. deterministic glossary alignment semantics;
5. the two-call Codex smoke and 24-call Codex A1 ceiling using only approved
   non-confidential fixtures; and
6. the staged stop rules.

It does not approve a mutation-call budget, workflow integration, blocking
severity, model-generated rewriting, or any legal novelty claim.
