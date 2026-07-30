# Socratic Understanding open questions and experiments

Items here are unresolved. They are not permission to modify implementation
code.

## OQ-001 — Missing source transcript

**Question:** Where is the full ChatGPT conversation that preceded the excerpt
in `TRANSCRIPT.md`?

**Why it matters:** historical rationale or explicit decisions may be absent.

**Resolution:** append or replace the transcript only from an exported/pasted
source. Never reconstruct missing dialogue from the curated docs.

## OQ-002 — Does this package supersede older SUE design documents?

**Question:** Should conflicts with older files under `docs/superpowers/specs/`
and `docs/superpowers/plans/` be resolved in favor of this package, or should
this package remain an index plus decision overlay?

**Proposed default:** authoritative overlay. Keep older documents as historical
design/experiment records and surface conflicts.

## OQ-003 — What is the minimum decision-context schema?

**Question:** Which fields are required to decide whether a divergence is
material?

**Experiment:** annotate ten existing SUE findings with decision kind,
in-scope requirements, material behaviour, and severity. Reject fields that do
not change classification or auditability.

**Decision gate:** two independent reviewers can classify materiality from the
context package without extra oral information.

## OQ-004 — Can extraction meet A1?

**Question:** Can clean-spec typed-edge agreement reach mean `≥0.80` and minimum
`≥0.70` without erasing real semantic differences?

**Experiment:** paired two-pass, three-reader runs on two clean specs with and
without deterministic glossary-canonical alignment.

**Stop rule:** if A1 fails, do not run the full mutation corpus or integrate SUE
as a blocking gate. Improve extraction or record that absolute SR is not viable.

## OQ-005 — How should glossary alignment avoid false merges?

**Question:** Which article/plural/alias transformations are safe, and how are
conflicting glossary entries handled?

**Tests:** exact term, declared alias, plural/article variant, overlapping terms,
one label matching multiple terms, and unknown term. Ambiguous matches remain
unmatched.

## OQ-006 — Are stable witness candidates truly incompatible?

**Question:** Do different `then` strings describe behaviours that cannot both
hold, or merely different granularity/phrasing?

**Experiment:** intersect candidates across passes, then require one exhibited
situation, two incompatible outcomes, and citations to both source sides.

**Promotion rule:** only `incompatible` with both-side provenance can become
decision evidence; `equivalent` and `undetermined` remain diagnostics.

## OQ-007 — Does the justification graph pass blind H-D2 adjudication?

**Question:** Is the one-shot graph at least 80% as complete/auditable as the
dialectic trace, and can it recover known contradictions graph-only?

**Experiment:** use the pre-registered blind packages and human-primary,
cross-family adjudication in the existing closure plan.

**Failure outcome:** keep the graph as a diagnostic pilot and the dialectic as
manual/Forensic evidence.

## OQ-008 — How independent are the readers?

**Question:** Do multiple calls share training/model/common-prompt errors that
make support counts overconfident?

**Experiment:** balanced provider × framing matrix with identical unit coverage;
report within-provider, between-provider, and framing effects separately.

**Constraint:** provider diversity is not assumed to imply epistemic
independence.

## OQ-009 — What should block Phase 3?

**Question:** Which SUE evidence class can route back to WHAT?

**Proposed rule:** extraction instability never blocks. A stable grounded
contradiction or verified behavioural incompatibility may block only when
material to the decision context and above the approved severity threshold.

**Needed:** false-positive evidence from the bounded mutation smoke and a human
override/audit path.

## OQ-010 — New workflow node or consensus pre-hook?

**Options:**

1. New controller-owned `phase3-socratic-understanding` node.
2. Controller pre-hook inside `phase3-consensus`.
3. Continue as a manual sidecar.

**Recommendation:** option 1, because it keeps provider evidence, state,
retries, and cost visible and prevents SAGE context from contaminating readers.

**Approval needed:** yes.

## OQ-011 — Evidence lifecycle

**Question:** Where do immutable SUE reports live, how are they named, and when
may they be reused?

**Proposed invariant:** reuse only when spec digest, decision context, tool/schema
version, provider/model/framing matrix, and policy match. Otherwise write a new
evidence artifact.

## OQ-012 — Privacy and retention

**Question:** Which specs may be sent to which providers, and how long are raw
outputs/debug dumps retained?

**Needed:** project-level allowlist, confidentiality classification, redaction
policy, report retention, and explicit treatment of argv-based prompt exposure.

## OQ-013 — Full corpus scope and cost

**Question:** Is the 10–15 spec, M1–M5, K=5 corpus worth the projected calls?

**Gate:** first run the three-spec bounded smoke. Expand only when A1 holds,
cost is within 2× estimate, mutation sites pass human clean-site review, and the
signal shows incremental value.

## OQ-014 — Historical outcome labels

**Question:** Which downstream outcomes provide trustworthy labels for P3
incremental value?

**Candidates:** review-fix task count, build rework, escaped defects, and human
clarification events.

**Risk:** these are confounded by feature size, team, provider, and workflow
version. Pre-register covariates and avoid causal claims from simple
correlation.

## OQ-015 — Test isolation under Codex markers

**Question:** Should provider-default tests explicitly pass an empty environment
to `resolve_model_command`?

**Evidence:** the focused suite passes 353/353 without `CODEX_THREAD_ID` and
`CODEX_CI`, but one default-provider assertion fails inside this Codex task.

**Proposed fix:** make the test explicit; do not change runtime marker
resolution.

## OQ-016 — Transcript and evidence redaction

**Question:** May the raw transcript contain confidential product context,
personal data, provider prompts, or credentials?

**Rule pending approval:** review/redact before commit while preserving a
separate secure original if required. Never copy secrets into the repository.

## OQ-017 — Is the extraction instrument valid, not merely consistent?

**Question:** Against a human-adjudicated reference, does the extractor recover
the correct typed relations, assumptions, and behavioural assertions?

**Risk:** A1 measures agreement. Multiple readers can agree on the same false
edge, while semantically equivalent edges can look different after extraction.

**Experiment:** dual human annotation plus adjudication on a stratified
three-to-five-spec calibration corpus. Report per-type precision/recall,
missing/ungrounded rate, human agreement, and run agreement with confidence
intervals.

**Stop rule:** do not treat SR or closure as a measurement of the specification
until the extraction instrument demonstrates acceptable validity and
reliability.

## OQ-018 — Which conditions are repeatability versus reproducibility?

**Question:** How much variation is attributable to stochastic repeats,
presentation order, prompt family, sampling parameters, model/provider, and
time?

**Risk:** changing several axes inside the same `K=5` batch confounds them and
does not support the stated variance decomposition.

**Experiment:** a crossed, replicated design with explicit same-condition
repeats and one controlled perturbation at a time. State all changed and
unchanged conditions in the report.

## OQ-019 — Are the A1–A6 thresholds calibrated?

**Question:** What loss, risk tolerance, or empirical distribution justifies
each cutoff?

**Current status:** the thresholds are provisional engineering targets, not
validated scientific constants.

**Experiment:** tune only on a named calibration set, lock the policy, then
report uncertainty and sensitivity on a separate validation set. Preserve
component-level failures rather than allowing a weighted score to compensate
for them.

## OQ-020 — Can A5 be evaluated without leakage and severe overfitting?

**Question:** Is there enough independent historical data to estimate the
incremental value of semantic features over 34 deterministic metrics?

**Risk:** ten to fifteen source specs cannot support the proposed feature set,
coefficient-significance rule, confounders, and validation. Mutants derived from
the same source spec are not independent.

**Proposed split:** evaluate mutant detection as an instrument study first.
Defer historical rework prediction until the sample-size and label audit
supports a pre-registered model, with whole specifications held out.

## OQ-021 — What authority do the two supplied research PDFs have?

**Question:** Should any proposed mechanisms from the English or Czech
AI-generated research memo be promoted into the authoritative specification?

**Second-pass default:** no. Keep the PDFs as research inputs. `QScore`,
Semantic Closure Score, Fracture Localization Index, philosopher personas,
automatic rewriting, and CI enforcement remain unapproved hypotheses where
they do not already conflict with accepted decisions.

## OQ-022 — Does close prior art change the intended IP strategy?

**Question:** Is the goal publication, patentability review, trade-secret
protection, defensive publication, or simply good engineering?

**Evidence:** ClarifyGPT, SpecFix, structured uncertainty clarification,
pragmatic-ambiguity comparison, and patent publications including
`CN121918799A` disclose overlapping individual mechanisms and make broad
novelty assertions unsafe. This preliminary review does not establish how any
specific claim is affected; professional, jurisdiction-specific assessment is
required.

**Constraint:** this repository review is non-legal and non-exhaustive. Do not
draft or file claims, or make freedom-to-operate conclusions, without qualified
patent counsel and a professional search.

## OQ-023 — How are stale SUE artifacts invalidated?

**Question:** What immutable identity must bind a SUE report to its exact input
and execution conditions?

**Evidence:** the checked-in `semantic-reproducibility.json` predates a later
specification correction, stores no input digest, and still reports the
resolved four-versus-five-header-facts contradiction.

**Proposed invariant:** every evidence package records the specification
digest and commit, run/pass identity, provider/model, prompt/schema/tool
versions, decision context, and raw-output references. Any mismatch marks the
artifact historical/stale and prevents it from supplying current findings.

**Experiment:** attempt the no-new-call reconstruction audit described in
`RESEARCH.md`. If exact inputs and complete pass outputs cannot be recovered,
record that as an evidence-lifecycle failure rather than regenerating a
plausible history.
