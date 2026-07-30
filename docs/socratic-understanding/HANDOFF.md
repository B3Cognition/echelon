# Socratic Understanding handoff

**Inspection date:** 2026-07-31
**Implementation baseline:** `b7ab289b9a372c059fa0754c760fe3dce3acb85a`
on `sue-source-codex-foundation`; the documentation-only commit that records
this inspection necessarily follows that implementation commit.
**Implementation authorization:** the approved zero-call source and Codex
foundation is implemented and documented below. The planned Codex smoke and
Luna/low A1 campaign remain unrun.

## Authority and transcript limitation

For this package, `SPECIFICATION.md` and `DECISIONS.md` are authoritative.
`TRANSCRIPT.md` is historical background only.

The original ChatGPT conversation was not available inside this Codex task.
`TRANSCRIPT.md` therefore preserves the complete excerpt transferred by the
user, not messages that remained in ChatGPT. This limitation is explicit so
future agents do not infer or invent missing decisions.

## Project in one paragraph

Socratic Understanding is a decision-relative quality layer for software
specifications. It asks whether independent, source-grounded reconstructions of
the same specification imply compatible behaviour for a stated decision. It
does not treat agreement as truth. It separates specification signal from
extractor/model variance, preserves provenance and disagreement, and may use a
bounded Socratic drill to localize an unresolved fracture. Its output is
evidence for a human or Echelon consensus decision; it never silently edits the
specification.

## Executive finding

The proposed subsystem is not greenfield. Echelon already has:

- a deterministic requirements-quality service and controller-owned
  Understanding gate;
- six standalone SUE scripts covering challenge, multi-reader consensus,
  semantic reproducibility, dialectic drilling, justification graphs, and
  orchestration;
- unit tests for all six scripts;
- checked-in reports from a real deep-profile run; and
- an experiment specification plus smoke-run record for the original Semantic
  Reproducibility Probe (SRP v0).

The material missing work is scientific validation and Echelon integration, not
basic scaffolding. The A1 clean-spec extraction-stability threshold has not been
met, the full mutation corpus has not run, several witness/graph rigor steps are
unfinished, and SUE evidence is not present in the Phase 3 workflow state or
journal contracts.

## Repository-grounded capability map

| Proposed capability | Current status | Exact evidence |
|---|---|---|
| Deterministic portable source bundle and source knowledge map | Implemented foundation; not yet the V3 source of truth | [`SUESourceBundle`](../../scripts/sue_source.py#L120), [`SourceKnowledgeMap`](../../scripts/sue_source.py#L131), and [`build_source_knowledge_map`](../../scripts/sue_source.py#L190) provide immutable, declared-only records and indexes. [`load_markdown_lexicon`](../../scripts/sue_source.py#L629) preserves complete multiline requirement-heading sections; [`load_generic_manifest`](../../scripts/sue_source.py#L842) enforces schema V1 and resolvable scalar JSON Pointers. `xml-id` and `page-paragraph` are explicitly unsupported until their post-A1 adapters exist. |
| Isolated, auditable V1 Codex cold-runner transport | Implemented; no live run claimed | [`ColdReaderRequest`](../../scripts/sue_runner.py#L95), [`build_subprocess_environment`](../../scripts/sue_runner.py#L192), [`build_model_invocation`](../../scripts/sue_runner.py#L224), and [`run_cold_reader`](../../scripts/sue_runner.py#L408) enforce an allowlisted environment, neutral temporary cwd, ephemeral/no-rules/no-user-config strict execution, disabled model-facing tools, no MCP/web/shell inheritance, and auditable result metadata. This is not a universal OS-level filesystem-secrecy guarantee. |
| Per-attempt V1 Codex evidence | Implemented for success, retry, and terminal failure | [`run_model_call`](../../scripts/sue_challenge.py#L700) copies runner results; [`_persist_call_evidence`](../../scripts/sue_challenge.py#L1193) exclusively writes metadata, raw JSONL, final output, and stderr for every attempt. Reports and terminal-failure sidecars retain references and the complete runner metadata. Non-V1 Codex SUE tools remain on legacy transport pending separate migration. |
| Deterministic requirements-quality baseline | Implemented | [`analyze_spec_bundle`](../../src/understanding/service.py#L260) parses requirements, computes per-requirement diagnostics, evaluates gates, and can generate diagrams. |
| Immutable, controller-owned quality evidence | Implemented | [`run_understanding_gate`](../../src/harness/understanding_gate.py#L69) writes digest-addressed evidence; [`UnderstandingGateResult.state_updates`](../../src/harness/understanding_gate.py#L32) owns `quality_scores` and `understanding_evidence`. |
| Workflow placement before qualitative WHY checks | Implemented for deterministic Understanding | [`phase3-understanding`](../../extension/workflow/definition.yaml#L1087) transitions to `phase3-consensus`. |
| Quick Socratic question → spec-only answer filter | Implemented | [`ROUND1_PROMPT_TEMPLATE`](../../scripts/sue_challenge.py#L183), [`ROUND2_PROMPT_TEMPLATE`](../../scripts/sue_challenge.py#L217), strict validators, and [`main`](../../scripts/sue_challenge.py#L1543). |
| Provider-specific compatibility transport | Implemented | [`build_model_invocation`](../../scripts/sue_challenge.py#L656) and [`run_model_call`](../../scripts/sue_challenge.py#L700) preserve legacy provider behavior while routing only schema-bearing V1 Codex calls through the hardened cold runner. |
| Independent multi-reader reconstruction with stable/noise split | Implemented | [`run_reader`](../../scripts/sue_consensus.py#L373), [`cluster_findings`](../../scripts/sue_consensus.py#L111), and [`split_stable`](../../scripts/sue_consensus.py#L146). |
| Typed interpretation graphs with behavioural assertions | Implemented | [`Edge`](../../scripts/sue_reproducibility.py#L87), [`Assertion`](../../scripts/sue_reproducibility.py#L100), [`ReqInterpretation`](../../scripts/sue_reproducibility.py#L112), and [`ReaderGraph`](../../scripts/sue_reproducibility.py#L119); extraction contract in [`build_extraction_prompt`](../../scripts/sue_reproducibility.py#L355). |
| Cross-run noise floor and stable-low fractures | Implemented | [`aggregate_passes`](../../scripts/sue_reproducibility.py#L511) computes SR mean/stdev, per-requirement variance, extraction-noise floor, and the all-passes `stable_low` intersection. |
| Behavioural divergence candidates | Partially implemented | [`Witness`](../../scripts/sue_reproducibility.py#L157) and [`find_witnesses`](../../scripts/sue_reproducibility.py#L613) produce heuristic candidates; the current report explicitly labels them unverified. |
| Bounded adaptive Socratic drill | Implemented as a manual/Forensic instrument | [`LENSES`](../../scripts/sue_dialectic.py#L132), [`next_step`](../../scripts/sue_dialectic.py#L306), and [`run_dialogue`](../../scripts/sue_dialectic.py#L411) implement deterministic operators, a one-revision budget, retention flags, and aporia terminal states. |
| Justification graph with claims, evidence, assumptions, conflicts | Implemented as an instrumented pilot | [`Claim`](../../scripts/sue_jgraph.py#L42), [`consensus_conflicts`](../../scripts/sue_jgraph.py#L140), and [`convergence_metrics`](../../scripts/sue_jgraph.py#L192). |
| One-command tier orchestration | Implemented | [`PROFILES`](../../scripts/sue_auto.py#L59), [`select_drills`](../../scripts/sue_auto.py#L116), and [`main`](../../scripts/sue_auto.py#L334). |
| Diagnose-only and no silent spec rewrite | Implemented | The orchestrator states the boundary in [`sue_auto.py`](../../scripts/sue_auto.py#L1); the challenged file is read through [`SpecDocument`](../../scripts/sue_challenge.py#L325), and [`sue_auto.main`](../../scripts/sue_auto.py#L334) applies report collision guards. |
| Live evidence that the pipeline runs | Present | The checked-in [`sue-dossier.md`](../../specs/030-build-sue-challenge-script/sue-dossier.md#L1) records successful v2, v3, and drill tiers and concrete aporias/stable findings. |
| Full SRP experimental validation | Not complete | The historical smoke run reports A1 agreement `0.346` against a `≥0.80` target and calls the result inconclusive in [`2026-07-18-srp-v0-smoke-run.md`](../superpowers/plans/2026-07-18-srp-v0-smoke-run.md#L30). The full corpus remains an unchecked, A1-gated task in [`2026-07-20-sue-100-percent-closure.md`](../superpowers/plans/2026-07-20-sue-100-percent-closure.md#L418). No live run has tested the new Luna/low profile. |
| Glossary-canonical graph alignment | Planned, not present at the inspected commit | The closure plan defines `parse_glossary_terms` and `canonicalize` under Task 1, but those symbols are absent from `scripts/sue_reproducibility.py`; see [`Task 1`](../superpowers/plans/2026-07-20-sue-100-percent-closure.md#L69). |
| Cross-pass stable witness intersection | Planned, not present | The current [`last-pass rich-evidence seam`](../../scripts/sue_reproducibility.py#L1107) uses the last pass for witnesses while aggregating only scores. Task 3 names the missing `stable_witness_keys` seam. |
| Exhibited incompatibility for behavioural witnesses | Planned, not present | Task 5 specifies `--verify-witnesses` and `validate_witness_verdict`; neither exists at the inspected commit. See [`Task 5`](../superpowers/plans/2026-07-20-sue-100-percent-closure.md#L282). |
| Blind H-D2 justification-graph adjudication | Instrumentation implemented; rigor experiment not run | The remaining blinded protocol and decision rule are recorded in [`Task 4`](../superpowers/plans/2026-07-20-sue-100-percent-closure.md#L248). |
| SUE evidence in Echelon Phase 3 | Not implemented | [`phase3-consensus`](../../extension/workflow/definition.yaml#L1098) has no SUE context/state, the phase contract reads only [`Certified Understanding Evidence`](../../extension/workflow/phases/phase3-consensus.md#L21), and the journal registry contains no SUE entry type. |

## Verification performed for this handoff

The source and runner foundation is covered by the eight focused SUE suites,
including [`test_sue_source.py`](../../tests/unit/test_sue_source.py) and
[`test_sue_runner.py`](../../tests/unit/test_sue_runner.py). The suite must pass
both in the ambient environment and with the provider markers
`CODEX_THREAD_ID`, `CODEX_CI`, and `ECHELON_LLM` cleared while retaining the
rest of `os.environ`. The provider-default test clears those three markers, so
ambient Codex detection remains runtime behaviour rather than test input.
At the implementation baseline, all 459 tests passed in each environment.
These zero-call tests do not constitute a Codex smoke or A1 result.

## Where SUE should integrate

The clean architectural seam is between the existing controller-owned
`phase3-understanding` node and the qualitative `phase3-consensus` dispatch.

Recommended shape, pending approval:

1. `phase3-understanding` continues to produce deterministic, provider-free
   certified evidence.
2. A new controller-owned `phase3-socratic-understanding` node snapshots the
   same `spec.md`, launches cold readers outside squad dispatch, aggregates
   immutable evidence, and records a digest.
3. `phase3-consensus` receives the deterministic report and the SUE report as
   distinct evidence channels.
4. SAGE interprets both but cannot recalculate them.
5. Extraction instability alone is diagnostic and non-blocking. A blocking
   issue requires a stable, source-grounded contradiction or an exhibited
   decision-relevant behavioural incompatibility.

This placement preserves the current controller/agent ownership boundary in
[`UnderstandingGateResult.state_updates`](../../src/harness/understanding_gate.py#L32)
and the staged consensus contract in
[`phase3-consensus.md`](../../extension/workflow/phases/phase3-consensus.md#L53).
It also avoids contaminating cold readers with `reasoning-journal.jsonl`, which
the consensus agents intentionally receive.

## Smallest falsifiable next prototype

Do not rebuild SRP v0. The smallest next prototype is an
**Extraction-Stability Gate Slice**:

1. Add deterministic glossary-canonical alignment at comparison time, without
   weakening source-label grounding.
2. Run paired with-glossary/without-glossary measurements on two clean specs,
   with three readers and at least two passes.
3. Pre-register the existing A1 threshold: mean clean-spec typed-edge agreement
   `≥0.80` and minimum per spec `≥0.70`.
4. Record cost, cross-pass noise, stable-low units, and all raw sidecars.
5. If A1 fails, stop: improve extraction or falsify absolute SR. Do not integrate
   SUE as a gate and do not launch the mutation corpus.
6. If A1 passes, run a bounded three-spec mutation smoke before considering the
   full corpus.

This is smaller and more falsifiable than workflow integration because it tests
the load-bearing assumption identified by the original smoke run.

## Proposed implementation plan — awaiting approval

No implementation work should begin until the user approves this plan.

### P0 — Reconcile and freeze the experimental baseline

- Record the inspected commit and SUE tool/schema versions in every experiment.
- Keep the provider-default unit test independent by clearing the three
  provider markers while retaining the rest of `os.environ`.
- Decide whether this handoff supersedes or indexes the older SUE design docs.
- Acceptance: all focused tests pass both with ambient markers and with the
  three provider markers cleared; no model calls.

### P1 — Extraction-Stability Gate Slice

- Implement and test glossary-canonical alignment in
  `scripts/sue_reproducibility.py`.
- Run the paired A1 experiment described above.
- Produce a result memo for PASS, FIX-EXTRACTION, or HALT.
- Stop condition: A1 not met.

### P2 — Trustworthy incompatibility evidence

- Intersect witness candidates across passes.
- Verify stable candidates by exhibiting one concrete incompatible situation
  with citations to both interpretations, or classify them equivalent or
  underdetermined.
- Run the pre-registered blind H-D2 pilot for justification graphs.
- Acceptance: no heuristic candidate is promoted to blocking evidence without
  exhibited consequences and provenance.

### P3 — Bounded mutation validation

- Human-approve clean sites and M1–M5 mutants for three specs.
- Measure detection by the operator-specific primary channel, localization,
  false positives, and cost.
- Compare against deterministic Understanding and raw-text baselines.
- Review cost and evidence before expanding to the 10–15 spec corpus.

### P4 — Controller-owned workflow integration

- Only after the experiment decision is `proceed`, add the new workflow node,
  immutable evidence writer, controller state schema, journal entry type, and
  SAGE context contract.
- Keep extraction instability separate and non-blocking.
- Add workflow validation, state-contract, stale-evidence, digest, rerun, and
  routing tests.
- Run `bash scripts/bash/dry-run.sh` plus focused Python tests.

### P5 — Operational hardening

- Version report schemas and record provider/model/framing/call budgets.
- Define retention and privacy policy for spec content, debug dumps, and
  sidecars.
- Verify supported provider adapters live.
- Document cost profiles and failure recovery without claiming truth from
  consensus.

## Bootstrap instruction for a future Codex task

```text
Read AGENTS.md and every file under
docs/socratic-understanding/.

Treat SPECIFICATION.md and DECISIONS.md as authoritative.
Treat TRANSCRIPT.md as historical background only.

Inspect the current Echelon repository and compare it with the inspection
baseline recorded in HANDOFF.md.

First produce a repository-grounded delta analysis for the next unapproved
plan phase. Cite exact files and symbols for every architectural claim.
Do not modify implementation code until I approve the plan.
```
