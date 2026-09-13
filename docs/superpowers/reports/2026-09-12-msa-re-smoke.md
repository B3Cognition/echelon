# MSA RE Quick Smoke Report

Date: 2026-09-12

## Scope

- Workspace: `/Users/michalbachorik/work/msa-re-smoke-jenkins`
- Source: `caic-msa-jenkins`
- Provider: configured Codex provider
- Requested depth: `quick`
- Aggregate authorization: 100,000,000 tokens

## Result

The fresh knowledge workflow completed end to end and published generation 1.

- Root request: `re-20260912-115811-486733`
- Reviewed analysis: `re-20260912-115811-486733-analysis`
- Workspace synthesis: `re-20260912-124851-951831`
- Analysis: 3/3 slices accepted and all reconciliations reviewed
- Synthesis: 6/6 artifacts generated and accepted
- Publication: complete, with source and workspace manifests plus consumer-facing Markdown
- Consumer attachment: passed; a downstream run attached all published source and workspace views
- Source repository: clean before and after the run, with zero stashes

## Resource Use

- Analysis conservative token charge: 3,444,427
- Synthesis conservative token charge: 1,572,864
- Combined conservative token charge: 5,017,291
- Analysis active time: 1,414,436 ms
- Synthesis active time: 229,242 ms
- Combined active time: 1,643,678 ms
- No reservation breach or exhausted budget dimension was recorded.

## Knowledge Acceptance

The published quick-depth knowledge is consistent with the repository's documented and implemented CI/CD flow. It identifies configuration ingestion and validation, the Jenkins/UvPipeline execution chain, container build and readiness checks, test and analysis stages, release gating, credential-wrapped external access, cleanup, and ECR publication. The source and workspace views do not claim nonexistent cross-repository relationships in this single-source workspace.

The output is intentionally high-level and somewhat repetitive at `quick` depth. It does not enumerate lower-level behavior such as parallel test execution, image-tag sanitization, or individual skip controls. Those omissions are consistent with quick-depth scope and are not publication failures.

## Defects Found and Repaired

The live run exposed three compatibility defects after reviewed analysis:

1. Mechanical provider results could omit controller-known slice identity fields or use the legacy rendered-markdown key.
2. Reconciliation replay applied the raw provider-output scanner to a controller-authored context.
3. Workspace synthesis accepted only the retired baseline executor catalog and rejected the configured-provider authority frozen by the new knowledge workflow.

The fixes were committed as `6791ef76`, `bc2c0d0b`, and `ac6003bc`. The final synthesis/workflow regression suite passed 191 tests before installation and resume.

## Conclusion

This smoke meets the functional acceptance target for one fresh, single-source, quick-depth Codex run: discovery, reviewed analysis, reconciliation, synthesis, publication, replay/resume, and downstream consumption all worked without modifying the source repository. It is evidence for the implementation, not a substitute for the separate multi-workspace and refresh trial gate.

## Standard-Depth Refresh Follow-up

A subsequent `echelon re refresh --depth standard` correctly planned the
depth change, created a fresh reviewed-analysis child, and expanded the source
plan from three to four slices. The first attempt accepted all four slices and
then exposed an exact-closure defect before synthesis: the refresh merge kept
both the superseded and replacement overview payload for the reanalyzed source,
while its catalog selected only the replacement. The refresh now prunes that
payload closure to exactly the catalog's selected object hashes and fails closed
if a selected payload is absent. The fixes were committed as `00ce2265` and
`5c42f775`; the focused refresh/CLI suite passed 127 tests after the repair.

The installed repair was exercised in a second immutable refresh attempt:

- Root request: `re-20260912-143733-805667`
- Reviewed analysis: `re-20260912-143733-805667-analysis`
- Analysis: 4/4 slices accepted, including two bounded verifier-driven repairs
- Terminal state: needs attention at reviewed source reconciliation
- Reason: `unchanged-reconciliation-outcome`
- Publication: unchanged at generation 1; no partial generation was published
- Source repository: clean after the run, with zero stashes

This stop is a genuine bounded semantic outcome, not a resource or transport
failure. Both reconciliation attempts independently retained failed
`contradictions` and `evidence-support` checks. The provider changed its
candidate, but could not resolve those checks from the frozen evidence. The
current reviewed protocol-2.8 workflow therefore stops safely instead of
looping or silently converting unresolved contradictions into debt.

The follow-up also identifies a remaining product gap: `echelon re resume`
supports immutable L3 guidance successors, but does not yet support a blocked
reviewed protocol-2.8 knowledge-analysis run. Its current L3-only error is
accurate at the protocol boundary but does not provide a continuation for this
ordinary refresh workflow. A reviewed-analysis guidance/debt successor needs a
separate explicit authority design; it must not reopen this immutable run or
downgrade contradictory evidence into dependency debt.

That diagnosis was subsequently narrowed against the approved simple-workflow
contract. A new protocol-specific resume/debt successor is neither necessary nor
desirable for ordinary reviewed refresh: repeating the same `echelon re refresh`
action is the specified immutable recovery path. The implementation now reports
that exact copyable action for exhausted reviewed refresh reconciliation. New
reconciler contracts also receive a controller-authored repair protocol requiring
unsupported conclusions to be removed or narrowed and evidenced disagreement to
remain an explicit conflict or unknown. It does not authorize a false PASS or
convert repeated contradiction into debt. The capability is frozen-contract
gated, so historical runs reconstruct their original context byte-for-byte.

The focused reconciliation, status, role, refresh, and end-to-end suite passed 53
tests after this repair. The stopped MSA run replays under the checkout reader and
now recommends `echelon re refresh --source caic-msa-jenkins --depth standard`.

That exact command was then exercised as a third immutable standard-depth attempt:

- Root request: `re-20260912-164205-941436`
- Reviewed analysis: `re-20260912-164205-941436-analysis`
- Workspace synthesis: `re-20260912-170955-181039`
- Analysis: 4/4 slices accepted, including two bounded verifier-driven repairs
- Reconciliation: passed; the prior contradiction/evidence-support exhaustion did
  not recur
- Synthesis: 6/6 artifacts generated with no failed attempts
- Publication: generation 2, complete and available for full-quality consumption
- Source repository: clean after publication, with zero stashes

One malformed producer response was rejected and retried within the bounded
contract before the analysis completed. The live refresh also exposed two status
projection defects: active reviewed work was mislabeled as `synthesizing`, and a
valid synthesis child authenticated through refresh-merge authority was rejected
as rebound when status was requested from its reviewed-analysis parent. Status now
keeps nonterminal reviewed work in `analyzing` and accepts either direct parentage
or an already-authenticated refresh authority that points exactly to the analysis
run and manifest. The completed analysis now replays as `complete` with its
generation-2 publication reported as `published_complete`.

Observed conservative analysis charges were 2,307,328 tokens for the first
standard attempt, 3,970,077 for the second, and 4,100,361 for the successful
third attempt. Generation-2 synthesis charged 1,572,864 tokens. Including the
successful quick analysis and synthesis, the smoke consumed 16,967,921
conservative tokens, well below the approved 100,000,000-token aggregate ceiling.

## Deep-Depth Refresh Follow-up

The completed standard publication was then refreshed at `deep` depth through
the ordinary one-command workflow:

- Root request: `re-20260912-184814-508101`
- Reviewed analysis: `re-20260912-184814-508101-analysis`
- First workspace synthesis: `re-20260912-191023-681252`
- Successful workspace synthesis: `re-20260912-191448-936055`
- Analysis: 5/5 slices accepted, with one bounded verifier-driven repair
- Synthesis: 6/6 artifacts complete; two compatible artifacts adopted and four
  generated
- Publication: generation 3, complete and available for full-quality
  consumption
- Source repository: clean after publication, with zero stashes

The ordinary refresh initially froze the shipped balanced ceiling of 5,000,000
tokens. Analysis charged 3,586,581 tokens, leaving too little authorization for
the final synthesis reservation. The first synthesis stopped safely after 4/6
artifacts and preserved generation 2. A bounded synthesis retry with a
1,572,864-token ceiling then completed and atomically published generation 3.
The complete deep follow-up charged 5,945,877 conservative tokens. Together
with the preceding quick and standard trials, this fixture consumed 22,913,798
tokens under the approved aggregate test allowance.

That stop exposed a CLI authorization defect rather than a reason to increase
the balanced default: ordinary `echelon re run` and `echelon re refresh` parsed
their hidden compatibility flags but otherwise hardcoded the shipped balanced
limits, bypassing the workspace's configured `re.default_profile` and custom
profile values. The repaired commands now resolve the existing workspace RE
profile before freezing a request, preserve an explicit CLI ceiling as the
highest-precedence override, require both resolved ceilings to remain finite,
and print the effective aggregate token/time limits before provider dispatch.
Depth still does not silently multiply authorization.

This deep run demonstrates a complete single-source refresh and full-quality
publication. It remains one fixture trial, not the complete multi-workspace M4
release gate.
