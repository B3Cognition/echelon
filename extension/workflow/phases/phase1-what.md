# Phase: phase1-what
# Source: echelon.run.md §4 — WHAT Phase (Requirements Definition)
# Agent: speckit-echelon-cartographer (CARTOGRAPHER)
# Read by: speckit-echelon-commander (COMMANDER) before dispatching speckit-echelon-cartographer (CARTOGRAPHER)

## 4. WHAT Phase (Requirements Definition)

> **Transition from UNDERSTAND to DECIDE:** This phase bridges understanding to decision-making. Constitution is now established. Echelon owns the Phase A branch and full spec identity; speckit-echelon-cartographer (CARTOGRAPHER) authors the specification only in the controller-provided run-local directory.

### 4.1 Context Pack Assembly

Read and include in the subagent prompt:

- `.specify/memory/constitution.md` (read-only governance source created by CHIEF)
- `${STAGING_DIR}/glossary.md` + `${STAGING_DIR}/mental-model.md` + `${STAGING_DIR}/boundaries.md`
- `${STAGING_DIR}/assumptions.md` + `${STAGING_DIR}/unknowns.md`
- `${STAGING_DIR}/reference-architectures.md` (if greenfield)
- `${STAGING_DIR}/user-clarifications.md` (if present; fresh control-plane input on every WHAT pass)
- `reasoning-journal.jsonl` (filtered to DISCOVER + WHY1 entries)
- User input (original request)
- `agents/exploration/templates/cartographer-spec-template.md`
- `agents/exploration/templates/cartographer-overview-template.md`

### 4.2 Dispatch speckit-echelon-cartographer (CARTOGRAPHER)

Echelon has already created and selected the feature branch and reserved the
full run-local `{spec_dir}`. CARTOGRAPHER MUST author a first-pass `spec.md`
there from the supplied templates. It must never create, switch, rename, or
discover a branch or another spec directory.

Treat `spec_dir` as authoritative. NEVER prefix it with `${SQUAD_DIR}` or
replace it with a discovered or reconstructed spec path.

On resumed/amendment passes, reuse `{spec_dir}` when `{spec_dir}/spec.md`
exists. A reserved run-local directory without `spec.md` is a first WHAT pass:
write the specification in that exact directory.

Use the Agent tool to dispatch a subagent with:

- **prompt:**

  ```xml
  <context>
  [include read-only .specify/memory/constitution.md, glossary.md, mental-model.md, boundaries.md, assumptions.md, unknowns.md, reference-architectures.md if greenfield, cartographer output templates, reasoning-journal.jsonl — staging artifacts from ${STAGING_DIR}/, user input]
  </context>

  <instructions>
  You are CARTOGRAPHER. Read agents/exploration/cartographer.md for your complete protocol.
  Phase A identity is controller-owned. If this is a first WHAT pass with no existing `{spec_dir}/spec.md`, create it from the supplied template in `{spec_dir}`, move discovery artifacts there, then enhance it with speckit-echelon-scout (SCOUT)'s domain insights. If this is a resumed/amendment pass, enhance the existing file in place. Never create, switch, rename, or discover a branch or another spec directory.
  Treat `.specify/memory/constitution.md` as read-only governance context. Apply its principles while authoring `spec.md`; do not edit, patch, append to, or regenerate the constitution from this phase.
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
  - Read the injected `Controller Configuration` section and treat its `<controller_configuration>` values as authoritative. Do not discover or override configuration from project files.
  - When the spec Lexicon gate is enabled, author the configured derived artifact from the configured source and glossary. The provider-free `phase1-lexicon` node validates it after this dispatch.
  - On a repair pass, read the injected `Spec Lexicon Repair (Controller-Enforced)` report and repair each listed finding locally. Validation execution and verdict reporting are controller-owned.
  - The harness owns formal Understanding analysis in `phase1-understanding` and `phase3-understanding`; do not calculate or report deterministic scores.
  - Fix `parse-error` before treating `source-id-missing` as independently established, because failed parsing can suppress derived IDs.
  - `NFR-…` IDs are valid `REQ: NFR-…` blocks in the controlled grammar. Do not describe NFRs as an unsupported grammar feature.
  - Never emit `lexicon_evaluation`, `lexicon_pass`, `lexicon_attempts`, `lexicon_findings`, or `lexicon_report`; the controller owns them.

  Always complete ALL of the following before returning. Do NOT return until they are true:
  1. `{spec_dir}/spec.md` exists and contains Given/When/Then acceptance criteria for every user story.
  2. `{spec_dir}/00-overview.md` exists (your 1-2 page human-readable summary).
  3. All discovery artifacts have been moved from `${STAGING_DIR}/` to `{spec_dir}/`; run-control files (`user-clarifications.md`, `governance-trail.json`, `escalation-request.md`) remain in staging.
  Creating an initial draft alone is NOT sufficient — enhancement with squad context is mandatory before returning.
  </instructions>
  ```

- **description:** "speckit-echelon-cartographer (CARTOGRAPHER): spec creation and requirements definition"

#### CARTOGRAPHER fallback

If `{spec_dir}` is missing after Phase A bootstrap, return `status: blocked` and
`blocked_reason: "spec_dir missing after Phase A bootstrap"`. COMMANDER must
not create or select a branch; the deterministic Phase A bootstrap owns that
recovery.

### 4.3 Controller-Owned Post-Dispatch Boundary

After CARTOGRAPHER completes, the harness checks the already-reserved `spec_dir`. The result
contract cannot change `spec_id`, `spec_dir`, `published_spec_dir`, or the feature branch.

The executor requires both `{spec_dir}/spec.md` and `{spec_dir}/00-overview.md`. A missing required
artifact blocks the phase with `missing_phase_outputs`; the model must not create a substitute
directory. The controller's constitution provenance guard independently rejects a missing or
template constitution before this phase or any later governed phase can run.

Specification quality is evaluated after the hard Lexicon boundary by the deterministic
`phase1-understanding` node and SAGE. A draft with missing or weak acceptance criteria therefore
returns through the ordinary WHY2 repair route rather than relying on model-executed probes.

After the required WHAT artifacts exist, the controller always advances to the visible,
provider-free `phase1-lexicon` node. CARTOGRAPHER does not certify or route around that node.

Return only this state update in `echelon_result`; the harness preserves the
controller-owned Phase A identity in `state.json`:

```yaml
echelon_result:
  state_updates:
    spec_status: planned
```

### Spec Status Transition — MANDATORY

This step is part of the `echelon_result.state_updates` block above. Skipping it leaves downstream phases reading a stale `Status: Draft` flag.

1. Return `spec_status: planned` in `echelon_result.state_updates`.
2. Update `{spec_dir}/spec.md`: replace the line `**Status**: Draft` with `**Status**: Planned`.
3. Return the strict result block. The harness validates and persists `spec_status`; do not read or
   modify `state.json` directly.

### Expected Outputs — BOTH REQUIRED

- `spec.md` (created and enhanced by speckit-echelon-cartographer (CARTOGRAPHER) in the controller-provided directory with GWT acceptance criteria and glossary cross-references)
- `00-overview.md` (speckit-echelon-cartographer (CARTOGRAPHER)-authored 1–2 page human summary: what the feature does, key design choices, primary constraints)

### 4.4 Lexicon Gate (when `lexicon_gate.enabled` in echelon-config.yml)

This subsection is INERT when `lexicon_gate.enabled` is false — the standard flow above is
unchanged. When it is true, the deterministic controlled-grammar gate applies to a derived
artifact. The canonical `{spec_dir}/spec.md` remains the rich spec-kit Markdown feature
specification.

**Controller Configuration.** The harness injects one authoritative
`<controller_configuration>` block containing effective activation, paths, artifact type, mode,
and repair limit. CARTOGRAPHER must not discover these values from files.

CARTOGRAPHER authors the configured derived artifact. The `phase1-lexicon` node independently
validates it, writes `spec-lexicon-report.json`, owns all validation fields and attempt accounting,
and applies the configured re-dispatch or exhaustion policy without invoking a provider.

**Spec Lexicon Repair.** When validation fails, the next WHAT prompt includes a
`Spec Lexicon Repair (Controller-Enforced)` section naming the report and attempt. CARTOGRAPHER
repairs the listed spans without executing validation; the controller revalidates after dispatch.

**Controlled-outcome routing.** After `phase1-lexicon` executes, read the controller-certified
`state.json.lexicon_evaluation` and `state.json.lexicon_pass`:
- `lexicon_evaluation == pending` → re-dispatch `phase1-what` (`increment_iteration`).
  This means the derived artifact was absent or the controller validator could not execute.
  A missing artifact is pending, never `lexicon_pass: false`.
- `lexicon_pass == true` → proceed to `phase1-understanding` (controller-certified Understanding analysis runs there,
  once, on rich `spec.md`, after the derived requirements artifact is structurally clean).
- `lexicon_evaluation == failed AND lexicon_attempts < max_repair_attempts AND iteration < max_iterations`
  → re-dispatch `phase1-what` (`increment_iteration`). This is the only condition that
  re-dispatches CARTOGRAPHER after a failed validation; the preceding `pending` condition
  handles an unevaluated artifact — see the transitions in `workflow/definition.yaml`.
- `lexicon_attempts >= max_repair_attempts` (or the secondary `iteration >= max_iterations` cap)
  → honor `lexicon_gate.on_exhausted`:
  `warn` → proceed to `phase1-understanding` with a `lexicon_gate_exhausted` warning journal entry;
  `block` → set `spec_status: blocked`, `blocked_reason: "lexicon gate not satisfied"`, and stop.

The controller writes `lexicon_evaluation`, `lexicon_pass`, `lexicon_attempts`,
`lexicon_findings`, and `lexicon_report`. These fields must never appear in the agent's
`echelon_result.state_updates`.

> Ordering invariant: Lexicon is the FIRST, hard, deterministic gate; `understanding`/SAGE
> (`phase1-understanding`) runs only AFTER `lexicon_pass`. The hard gate validates
> `requirements.lexicon.md`; the soft score still reads the canonical rich `spec.md`. Never let
> the soft score gate structure — that is the "score-quality-later" anti-pattern this gate
> replaces.

**Transition:** `phases[phase1-lexicon]` — see `workflow/definition.yaml`
