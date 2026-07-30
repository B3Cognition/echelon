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
