# Controlled delivery prompt ownership audit

Audited implementation: `b6bfceda`, in the isolated delivery-controller worktree.
This is a read-only behavior audit plus findings record, not a code correction
or acceptance of the entire delivery pipeline.

## Scope

The user excluded legacy `echelon build`, its native command and recipe from
convergence. This audit follows the enabled `delivery_gate_controller` route:
initial implementation, source repair, documentation repair, and the immediately
connected fulfillment and PR-triage prompt boundaries. It does not change
feature-off behavior, provider configuration, modes, defaults or identity scope.

## Findings

### Confirmed: dedicated delivery roles have the intended ownership

`coordinator.py:get_build_prompt` passes controller context rather than loading
the legacy build command when controlled delivery is enabled. The internal
`echelon build` strategy label is not a legacy CLI invocation.

`DeliverySliceRunner` loads four `echelon.delivery-*` profiles with Prosaic and
renders each with its exact assignment and JSON result contract. It does not use
the generic COMMANDER preamble. `DeliveryDocumentationRunner` does the same for
TECH WRITER and DOCS VERIFIER with a returned report value. All six current role
files have zero recognized companion references, so no hidden phase recipe is
inlined through their companions. Their provider metadata remains neutral.

This confirms the six profiles and their direct rendering boundary, not that
every other model call in delivery has the same ownership contract.

### Important: legacy completion instructions reach controlled source repairs

`ralph.py:_make_feedback_prompt` says to stop after writing the harness status
marker. `_exec_feedback` replaces this prose with structured failure evidence
only for documentation-only failures. Source/mixed repairs retain the generated
text, and `_exec_controlled_slice` persists it as operation feedback before
`DeliverySliceRunner._render_prompt` appends it to every assigned role.

Consequently the same provider request both forbids completion markers and tells
the model to write one. Calling that section data rather than routing authority
does not remove the conflicting instruction. The JSON validator still rejects
marker-only success; the demonstrated defect is contradictory provider input,
not a demonstrated gate bypass.

The shared feedback formatter also emits only failure category, ID and error.
Generic `FailureEntry.details` and `verification_evidence` are not included
there; the coverage-specific helper preserves a selected subset separately.
The probe's source location stored in `details` did not reach any role.

One-off consuming probes used the existing temporary project, real Ralph and
slice runner, Prosaic inspection stand-in, and scripted external role results.
An initial accepted task established the actual repair pointer. For each route:

| Route | Actual dispatched steps | Marker instruction + prohibition | Generic source detail delivered |
| --- | --- | --- | --- |
| Inner source feedback | IMPLEMENTER, SPEC GUARD, CODE REVIEWER, TEST GUARDIAN | Both in all four prompts | No |
| `run_downstream_feedback`, visual | Same four steps | Both in all four prompts | No |
| `run_downstream_feedback`, review | Same four steps | Both in all four prompts | No |

Each operation passed with the scripted JSON results. That is not evidence that
a live model obeys contradictory instructions. The first diagnostic invocation
completed the inner probe, then used the wrong downstream method name and raised
AttributeError. The corrected invocation ran the remaining two routes and the
six-role companion inventory successfully; this was a probe typo, not a product
failure. No production file or permanent test was changed.

### Ownership guidance is stale

Root `AGENTS.md` and `CLAUDE.md` describe command wrappers as COMMANDER-owned,
make COMMANDER the universal state/journal writer, and require every new agent
to emit `echelon_result`. Those statements conflict with the controlled delivery
JSON assignments, Python journal owner and controller-published documentation.
They need an explicit controlled-delivery exception, not a blanket claim that
all Echelon workflows have already migrated.

### Separate remaining boundaries: fulfillment and PR triage

`FulfillmentRunner._build_verify_spec_prompt` still loads `echelon.verify-spec`
with COMMANDER framing and embeds `verify-spec-*.md`. The mapping/judgment phases
instruct the model to invoke deterministic helpers, dispatch mapper/guard roles
and advance phases. Python owns admission, run initialization and validation,
but it does not independently dispatch every semantic step in this path.

`ReviewLoopController._invoke_staged_review_skill` invokes `echelon.review` with
COMMANDER framing. That prompt instructs the model to sequence DEBUGGER,
SENTINEL and SPEC GUARD. The controller validates/publishes the staged batch,
but these diagnostic calls remain model-sequenced. `_read_review_agent` also
reads `.claude/agents/echelon-*.md` rather than neutral Prosaic subagents.

These are existing active boundary limitations, not regressions introduced by
the documentation checkpoint. They were inspected at their callers and declared
prompt contracts, not live-executed or fully behaviorally validated in this audit.
Do not relabel them Python-owned in project guidance. Migrating them requires
separate bounded designs/acceptance; no such migration is implemented or silently
authorized by this report. They remain visible in convergence tracking.

## CLAUDE.md quality report

Files found: one repository `CLAUDE.md`; no nested or local Claude instruction
files found by the scoped repository search. `AGENTS.md` has matching ownership
text and is included in the proposed correction. Personal/global files are out
of scope. Overall assessment: **70/100 (B)**; one Claude file needs an update.
This is an editorial assessment, not execution verification of all listed
commands. The audit targets currency of delivery ownership.

| Criterion | Score | Notes |
| --- | --- | --- |
| Commands/workflows | 15/20 | Test and delivery entries are present; controlled opt-in distinctions are missing. |
| Architecture clarity | 15/20 | Useful module map, but no controlled slice/documentation owner description. |
| Non-obvious patterns | 15/15 | Target resolution, installed bundles and shared ownership cautions are documented. |
| Conciseness | 10/15 | Dense guidance, with repeated legacy-wide claims. |
| Currency | 5/15 | COMMANDER/state/result claims conflict with current controlled delivery. |
| Actionability | 10/15 | Concrete commands, but applying the universal output/writer instructions to delivery is wrong. |

## Proposed guidance edit, pending approval

Add the following narrow section to both root instruction files and qualify the
existing universal COMMANDER/journal guidance as legacy/command-specific. Leave
unrelated sections and legacy command behavior unchanged. This prevents future
work from reintroducing a second owner or the wrong result format.

```diff
+ ## Controlled delivery ownership
+
+ With `llm.features.delivery_gate_controller: true`, `echelon delivery run`
+ bypasses the legacy build prompt. Ralph and its Python helpers own task
+ selection, gate sequencing, bounded repairs, durable operation journals,
+ progress, authoritative verification and documentation report publication.
+ Prosaic supplies the six neutral `echelon.delivery-*` role bodies and metadata;
+ provider-specific permissions remain in the provider adapters.
+
+ Delivery roles return their assignment-bound JSON, not `echelon_result` or
+ harness completion markers. They never dispatch another agent or write
+ controller state. Successful slice review is not final delivery acceptance.
+
+ These ownership rules apply to the controlled slice/documentation path, not
+ every fulfillment or PR-triage model call. Those retain separate contracts.
+ Legacy `echelon build` and feature-off behavior remain outside this migration;
+ do not alias, remove or rewrite them as part of controlled convergence.
```

## Recommended next bounded correction

Correct controlled source-repair feedback at Ralph's producer boundary, using
structured failure/context data as documentation repair already does. Preserve
the actual failure details, verification/coverage evidence, downstream phase and
evidence references, and relevant user/strategy context. Keep execution restrictions
in the applicable role/controller contract, not mixed into legacy completion
recipes. Preserve the existing operation snapshot, journal/retry/budget semantics
and conservative recovery of old records; do not rewrite a pending journal.

Acceptance should capture actual role requests through inner and downstream
repair, prove one output contract and retained evidence, and preserve legacy,
documentation, both-provider and all-mode behavior. This is a bounded correction
to existing feedback construction, not a new flow/controller. Apply the narrow
guidance edit alongside it after approval. Fulfillment/PR migration, bundle/live
acceptance, defaults and identity activation remain separate.
