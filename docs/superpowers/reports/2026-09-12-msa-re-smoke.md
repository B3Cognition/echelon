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

Observed conservative analysis charges were 2,307,328 tokens for the first
standard attempt and 3,970,077 for the second. Including the successful quick
analysis and synthesis, the smoke consumed 11,294,696 conservative tokens,
well below the approved 100,000,000-token aggregate ceiling.
