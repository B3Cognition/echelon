# Phase: phase1-what
# Source: echelon.run.md §4 — WHAT Phase (Requirements Definition)
# Agent: echelon.cartographer (CARTOGRAPHER)
# Read by: echelon.commander (COMMANDER) before dispatching echelon.cartographer (CARTOGRAPHER)

## 4. WHAT Phase (Requirements Definition)

> **Transition from UNDERSTAND to DECIDE:** This phase bridges understanding to decision-making. Constitution is now established. Echelon owns the Phase A branch and full spec identity; echelon.cartographer (CARTOGRAPHER) authors the specification only in the controller-provided run-local directory.

### 4.1 Context Pack Assembly

Read and include in the subagent prompt:

- `.echelon/constitution.md` (read-only governance source created by CHIEF)
- `${STAGING_DIR}/glossary.md` + `${STAGING_DIR}/mental-model.md` + `${STAGING_DIR}/boundaries.md`
- `${STAGING_DIR}/assumptions.md` + `${STAGING_DIR}/unknowns.md`
- `${STAGING_DIR}/reference-architectures.md` (if greenfield)
- `${STAGING_DIR}/user-clarifications.md` (if present; fresh control-plane input on every WHAT pass)
- `{spec_dir}/evidence-resolution.md` + `{spec_dir}/evidence-grades.md` (if Phase 1 INVESTIGATOR ran; treat recorded facts as authoritative evidence for this amendment)
- `reasoning-journal.jsonl` (filtered to DISCOVER + WHY1 entries)
- User input (original request)
- `agents/exploration/templates/cartographer-spec-template.md`
- `agents/exploration/templates/cartographer-overview-template.md`

### 4.2 Dispatch echelon.cartographer (CARTOGRAPHER)

Echelon has already created and selected the feature branch and reserved the
full run-local `{spec_dir}`. CARTOGRAPHER MUST author a first-pass `spec.md`
there from the supplied templates. It must never create, switch, rename, or
discover a branch or another spec directory.

Treat `spec_dir` as authoritative. NEVER prefix it with `${SQUAD_DIR}` or
replace it with a discovered or reconstructed spec path.

On resumed/amendment passes, reuse `{spec_dir}` when `{spec_dir}/spec.md`
exists. A reserved run-local directory without `spec.md` is a first WHAT pass:
write the specification in that exact directory.

The active runtime dispatches this role with the following request:

- **prompt:**

  ```xml
  <context>
  [include read-only .echelon/constitution.md, glossary.md, mental-model.md, boundaries.md, assumptions.md, unknowns.md, evidence-resolution.md and evidence-grades.md if present, reference-architectures.md if greenfield, cartographer output templates, reasoning-journal.jsonl — staging artifacts from ${STAGING_DIR}/, user input]
  </context>

  <instructions>
  You are CARTOGRAPHER. Read agents/exploration/cartographer.md for your complete protocol.
  Phase A identity is controller-owned. If this is a first WHAT pass with no existing `{spec_dir}/spec.md`, create it from the supplied template in `{spec_dir}`, move discovery artifacts there, then enhance it with echelon.scout (SCOUT)'s domain insights. If this is a resumed/amendment pass, enhance the existing file in place. Never create, switch, rename, or discover a branch or another spec directory.
  Treat `.echelon/constitution.md` as read-only governance context. Apply its principles while authoring `spec.md`; do not edit, patch, append to, or regenerate the constitution from this phase.
  If `evidence-resolution.md` is present, apply its observed facts and confidence limits to the amendment. Do not re-investigate the same source, discard evidence because it conflicts with the prior draft, or invent facts beyond its stated gaps.
  Evidence routing is controller-owned. ALWAYS return `evidence_resolution_status: not_required` after an ordinary WHAT pass. When a declared input or directly relevant primary source must establish a project-specific fact before requirements can be amended, ALWAYS return `FAIL` with `evidence_resolution_status: pending` and a complete `evidence_requests` object. NEVER return `BLOCKED` merely because the missing fact is investigable; `BLOCKED` bypasses workflow transitions and is reserved for controller-owned operational failures.
  When the Product Input Contract is present, read its requirement snapshot and cite every adopted or challenged `IN-REQ-*` unit. Return one `echelon_result.product_input_updates` entry per normative unit. This is a strict API contract: copy the catalog ID into `input_unit_id`; use exactly one of `included`, `excluded`, `duplicate`, `open_question`, or `conflict` for `disposition`; give an evidence-backed `rationale`; place mapped FR/AC IDs in `spec_ids`; and set `task_ids: []` and `targets: []` in this phase. Never use aliases such as `unit`, `adopted`, or `mapped`. Do not write the ledger file directly; COMMANDER validates and persists the structured updates. Example:
  ```yaml
  product_input_updates:
    - input_unit_id: IN-REQ-EXAMPLE
      disposition: included
      rationale: "Captured by the cited functional requirements and acceptance criteria."
      spec_ids: [FR-001, AC-001]
      task_ids: []
      targets: []
  ```
  Add user stories with acceptance criteria (Given/When/Then) using the provided templates. Cross-reference the glossary and mental model. No implementation details — no languages, frameworks, or databases. Staging directory: `${STAGING_DIR}/`. Return journal entries in `echelon_result.journal_entries`.

  Controller-Owned Validation Contract:
  - The harness owns formal Understanding analysis in `phase1-understanding` and `phase3-understanding`; do not calculate or report deterministic scores.
  - Leave formal validation and downstream phase transitions to the harness after your one completion payload.
  - Return exactly one final CARTOGRAPHER `echelon_result` using this phase's allowed `state_updates`. Never embed, quote, or forward another agent's result block.
  - After this phase, deterministic Understanding and SAGE WHY2 validate the current `spec.md`.
  - Do not create or repair the derived Lexicon artifact. A dedicated node runs only after spec quality passes.

  Always complete ALL of the following before returning. Do NOT return until they are true:
  1. `{spec_dir}/spec.md` exists and contains Given/When/Then acceptance criteria for every user story.
  2. `{spec_dir}/requirements-overview.md` exists (your 1-2 page Phase 1 requirements orientation; not the final delivery overview).
  3. All discovery artifacts have been moved from `${STAGING_DIR}/` to `{spec_dir}/`; run-control files (`user-clarifications.md`, `governance-trail.json`, `escalation-request.md`) remain in staging.
  Creating an initial draft alone is NOT sufficient — enhancement with squad context is mandatory before returning.
  </instructions>
  ```

- **description:** "echelon.cartographer (CARTOGRAPHER): spec creation and requirements definition"

#### CARTOGRAPHER fallback

If `{spec_dir}` is missing after Phase A bootstrap, return `status: blocked` and
`blocked_reason: "spec_dir missing after Phase A bootstrap"`. COMMANDER must
not create or select a branch; the deterministic Phase A bootstrap owns that
recovery.

### 4.3 Controller-Owned Post-Dispatch Boundary

After CARTOGRAPHER completes, the harness checks the already-reserved `spec_dir`. The result
contract cannot change `spec_id`, `spec_dir`, `published_spec_dir`, or the feature branch.

The executor requires both `{spec_dir}/spec.md` and `{spec_dir}/requirements-overview.md`. A missing required
artifact blocks the phase with `missing_phase_outputs`; the model must not create a substitute
directory. The controller's constitution provenance guard independently rejects a missing or
template constitution before this phase or any later governed phase can run.

Specification quality is evaluated immediately by the deterministic
`phase1-understanding` node and SAGE WHY2. A draft with missing or weak acceptance criteria therefore
returns through the ordinary WHY2 repair route rather than relying on model-executed probes.

## Completion Payload (Mandatory)

Every `DONE` result from this phase MUST include:

```yaml
state_updates:
  evidence_resolution_status: not_required
```

Do not return an empty `state_updates` object. The controller rejects it as a
contract failure even when `spec.md` was successfully updated.

After the required WHAT artifacts exist, the controller always advances to the visible,
provider-free `phase1-understanding` node. Only a quality-certified specification advances to
the dedicated Lexicon derivation and validation nodes.

For an ordinary completed WHAT pass, return these state updates; the harness
preserves the controller-owned Phase A identity in `state.json`:

```yaml
echelon_result:
  verdict: DONE
  state_updates:
    spec_status: planned
    evidence_resolution_status: not_required
```

### Evidence Resolution Route — MANDATORY WHEN NEEDED

If evidence from a declared reference must be collected before the specification
can be amended, return this executable route instead of prose such as “route to
INVESTIGATOR”:

```yaml
echelon_result:
  verdict: FAIL
  state_updates:
    evidence_resolution_status: pending
    evidence_requests:
      requests:
        - id: ER-001
          question: "<project-specific fact to establish>"
          affected_requirements: [FR-001]
          evidence_needed: "<minimum authoritative evidence required>"
          supplied_reference_ids: [IN-REF-...]
```

Every request must name the affected requirement, the minimum evidence, and a
declared reference ID. Do not set `spec_status: blocked`, `status: blocked`, or
`blocked_reason` for this route. The graph sends this result to INVESTIGATOR.

### Spec Status Transition — MANDATORY

This step is part of the `echelon_result.state_updates` block above. Skipping it leaves downstream phases reading a stale `Status: Draft` flag.

1. Return `spec_status: planned` in `echelon_result.state_updates`.
2. Update `{spec_dir}/spec.md`: replace the line `**Status**: Draft` with `**Status**: Planned`.
3. Return the strict result block. The harness validates and persists `spec_status`; do not read or
   modify `state.json` directly.

### Expected Outputs — BOTH REQUIRED

- `spec.md` (created and enhanced by echelon.cartographer (CARTOGRAPHER) in the controller-provided directory with GWT acceptance criteria and glossary cross-references)
- `requirements-overview.md` (echelon.cartographer (CARTOGRAPHER)-authored 1–2 page Phase 1 requirements orientation: what the feature does, key requirements choices, primary constraints. This is not the final PM/developer brief; finalization generates `00-overview.md` after plan/task conformance.)

### 4.4 Quality-Certified Transition

The successful transition is `phase1-what -> phase1-understanding ->
phase1-why2`. A WHY2 failure returns to this phase for a canonical amendment.
After an amendment, the full quality sequence repeats. Lexicon derivation is
downstream of a passing WHY2 result and is owned by
`phase1-lexicon-derive`.
