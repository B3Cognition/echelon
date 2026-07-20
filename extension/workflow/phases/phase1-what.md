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

  Validation Tool Contract:
  - For diagnostic scoring during authoring/amendment, use `understanding scan "{spec_dir}/spec.md" --enhanced --per-req --json --output /tmp/cartographer-understanding.json`; read JSON from the output file, not stdout.
  - The enhanced scan output file is a JSON list; normalize it before reading metrics: `payload=json.load(open("/tmp/cartographer-understanding.json")); report=payload[0] if isinstance(payload, list) and payload else payload`. Do not call `.keys()` or `.get("metrics")` on the root payload before this normalization.
  - Do NOT run `understanding validate` or guess module commands; SAGE owns the formal Understanding validation skill in WHY2/WHY3.
  - For Lexicon Gate validation, use `lexicon validate "{spec_dir}/{lexicon_path}" --type {artifact_type} --source-ref "{spec_dir}/{source_ref}" --glossary "{spec_dir}/{glossary_file}" --json`; the controller independently certifies the final `lexicon_pass` from the derived artifact on disk.

  Lexicon Repair Invariant:
  - When the Lexicon gate is enabled, an amendment pass MUST run that validator before writing any completion summary. An artifact inventory, a prior journal entry, or a prior `lexicon_attempts` value is not validation evidence.
  - If the validator returns findings, repair the current derived artifact and re-run it up to the configured repair budget. Fix `parse-error` before interpreting `source-id-missing`, because failed parsing can suppress all derived IDs.
  - `NFR-…` IDs are valid `REQ: NFR-…` blocks in the controlled grammar. Do not describe NFRs as an unsupported grammar feature.
  - If the current run state has `lexicon_attempts: 0`, its repair budget was reset by rewind; do not repeat an earlier exhaustion conclusion.
  - NEVER emit `lexicon_pass` yourself. The controller writes that Boolean only after it validates the derived artifact; a missing artifact is pending, never `lexicon_pass: false`.

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

### 4.3 Post-speckit-echelon-cartographer (CARTOGRAPHER)

After speckit-echelon-cartographer (CARTOGRAPHER) completes, read its output to verify
the already-reserved `spec_dir`. Phase A identity is controller-owned: CARTOGRAPHER
must not return or change `spec_id`, `spec_dir`, `published_spec_dir`, or the feature
branch. Use the supplied `spec_dir` exactly as provided for file checks and prompts.

#### Directory Verification (MANDATORY)

Before returning state updates, verify the supplied spec directory exists:

1. **Spec directory exists:**
   ```bash
   ls "{spec_dir}/spec.md"
   ```

**If the check fails** (directory missing or `spec.md` missing), return a
blocking result. Do not run Git commands and do not create a substitute
directory.

**If both checks pass**, verify speckit-echelon-cartographer (CARTOGRAPHER) ran the enhancement pass (Step 2 in `cartographer.md`) before updating state:

```bash
# spec.md must contain at least one WHEN/THEN acceptance criterion — proof of enhancement
grep -q "WHEN\|THEN\|Given\|When\|Then" "${spec_dir}/spec.md" \
  || { echo "WARN: spec.md has no WHEN/THEN criteria — speckit-echelon-cartographer (CARTOGRAPHER) may not have run Step 2 (enhancement pass)"; }
# 00-overview.md must exist
[ -f "${spec_dir}/00-overview.md" ] \
  || { echo "WARN: 00-overview.md missing — speckit-echelon-cartographer (CARTOGRAPHER) Step 2 may be incomplete"; }
```

If either warning fires: **re-dispatch speckit-echelon-cartographer (CARTOGRAPHER)** in enhancement-only mode using the prompt below. Additionally, run the constitution check below regardless of whether CARTOGRAPHER warnings fired.

**Constitution placeholder check** (run after every CARTOGRAPHER dispatch, regardless of outcome):

```bash
grep -E '\[CONSTITUTION_VERSION\]|\[RATIFICATION_DATE\]|\[LAST_AMENDED_DATE\]' \
  .specify/memory/constitution.md && echo "CONSTITUTION_PLACEHOLDERS_FOUND" || echo "CONSTITUTION_CLEAN"
```

If `CONSTITUTION_PLACEHOLDERS_FOUND`: the constitution is not usable governance output yet. Do not advance to Phase 2. Do not edit, patch, or shell-substitute `.specify/memory/constitution.md` here. Return to `phase1-constitution` so speckit-echelon-chief (CHIEF) can invoke `speckit.constitution` with concrete context.

Always resolve constitution placeholders through CHIEF before Phase 2. Do NOT proceed to Phase 2 with unfilled placeholders in constitution.md. A constitution with `[CONSTITUTION_VERSION]` in it is not a constitution — it is a template. A spec.md with zero acceptance criteria is not complete output.

**Enhancement-only re-dispatch prompt:**

```xml
<context>
[include same context pack as first dispatch, including read-only .specify/memory/constitution.md, plus current contents of {spec_dir}/spec.md]
spec_dir: {spec_dir}
</context>

<instructions>
You are CARTOGRAPHER in enhancement-only mode. The spec directory already exists at `{spec_dir}`. Enhance spec.md with Given/When/Then acceptance criteria and cross-references, then produce 00-overview.md. Do not create or switch branches or directories. Read cartographer.md §"Step 2: Enhance Spec with Squad Intelligence" for the full protocol.
Treat `.specify/memory/constitution.md` as read-only governance context. Do not edit, patch, append to, or regenerate it.

Always complete these outputs before returning. Do NOT return until:
1. `{spec_dir}/spec.md` contains Given/When/Then acceptance criteria for every user story.
2. `{spec_dir}/00-overview.md` exists.
</instructions>
```

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
3. **Verification (run after the harness applies state updates, before transitioning to phase1-why2):**

   ```bash
   grep -q '^\*\*Status\*\*: Planned' "${spec_dir}/spec.md" || { echo "ERROR: spec.md still shows Draft" >&2; exit 1; }
   python3 -c "import json; assert json.load(open('${SQUAD_DIR}/state.json'))['spec_status']=='planned'" || { echo "ERROR: state.json.spec_status not 'planned'" >&2; exit 1; }
   ```

   If either check fails, halt the phase and resolve before proceeding.

### Expected Outputs — BOTH REQUIRED

- `spec.md` (created and enhanced by speckit-echelon-cartographer (CARTOGRAPHER) in the controller-provided directory with GWT acceptance criteria and glossary cross-references)
- `00-overview.md` (speckit-echelon-cartographer (CARTOGRAPHER)-authored 1–2 page human summary: what the feature does, key design choices, primary constraints)

**Post-dispatch verification (run before Spec Status Transition):**

```bash
[ -f "${spec_dir}/spec.md" ]        || { echo "ERROR: spec.md missing" >&2; exit 1; }
[ -f "${spec_dir}/00-overview.md" ] || { echo "ERROR: 00-overview.md missing" >&2; exit 1; }
# Confirm staging was moved (at least glossary.md must be in spec_dir)
[ -f "${spec_dir}/glossary.md" ]    || echo "WARN: staging artifacts may not have been moved to spec_dir"
```

### 4.4 Lexicon Gate (when `lexicon_gate.enabled` in echelon-config.yml)

This subsection is INERT when `lexicon_gate.enabled` is false — the standard flow above is
unchanged. When it is true, the deterministic controlled-grammar gate applies to a derived
artifact. The canonical `{spec_dir}/spec.md` remains the rich spec-kit Markdown feature
specification.

**Dispatch additions.** Include in the CARTOGRAPHER prompt:
- `lexicon_gate.enabled: true`, plus `artifact_type`, `lexicon_path`, `source_ref`,
  `glossary_file`, and `max_repair_attempts` from `echelon-config.yml`.
- The controlled glossary (`{glossary_file}`, already in the context pack as `glossary.md`).
- Instruction: "Author in Lexicon Gate Mode — see `cartographer.md §Lexicon Gate Mode`. Keep
  `{spec_dir}/spec.md` as the rich Markdown feature specification, derive
  `{spec_dir}/requirements.lexicon.md` from it in the Lexicon grammar with `SOURCE` and
  `SOURCE_SHA256` metadata, self-validate and repair that derived artifact with
  `lexicon validate --source-ref`, and report its attempt count. The controller certifies
  the final Lexicon verdict from the on-disk artifact."

CARTOGRAPHER owns the in-dispatch repair loop (the "fix"). The controller independently
validates the derived artifact and owns `lexicon_evaluation` plus the Boolean verdict.
COMMANDER owns the re-dispatch decision on that controlled outcome (the "re-dispatch").

**Controlled-outcome routing.** After the dispatch, read the controller-certified
`state.json.lexicon_evaluation` and `state.json.lexicon_pass`:
- `lexicon_evaluation == pending` → re-dispatch `phase1-what` (`increment_iteration`).
  This means the derived artifact was absent or the controller validator could not execute;
  it is not a validation failure and never produces `lexicon_pass: false`.
- `lexicon_pass == true` → proceed to `phase1-why2` (soft `understanding`/SAGE scoring runs there,
  once, on rich `spec.md`, after the derived requirements artifact is structurally clean).
- `lexicon_evaluation == failed AND lexicon_attempts < max_repair_attempts AND iteration < max_iterations`
  → re-dispatch `phase1-what` (`increment_iteration`). This is the only condition that
  re-dispatches CARTOGRAPHER after a failed validation; the preceding `pending` condition
  handles an unevaluated artifact — see the transitions in `workflow/definition.yaml`.
- `lexicon_attempts >= max_repair_attempts` (or the secondary `iteration >= max_iterations` cap)
  → honor `lexicon_gate.on_exhausted`:
  `warn` → proceed to `phase1-why2` with a `lexicon_gate_exhausted` warning journal entry;
  `block` → set `spec_status: blocked`, `blocked_reason: "lexicon gate not satisfied"`, and stop.

**Agent state updates (added to the §4.3 block when the gate is enabled):**

```yaml
echelon_result:
  state_updates:
    lexicon_attempts: <int>   # repair rounds used
    lexicon_findings: <int>   # remaining findings when validation ran
```

The controller then writes `lexicon_evaluation: pending|passed|failed` and, only after its
deterministic validation runs, `lexicon_pass: true|false`.

> Ordering invariant: Lexicon is the FIRST, hard, deterministic gate; `understanding`/SAGE
> (phase1-why2) is the soft score that runs only AFTER `lexicon_pass`. The hard gate validates
> `requirements.lexicon.md`; the soft score still reads the canonical rich `spec.md`. Never let
> the soft score gate structure — that is the "score-quality-later" anti-pattern this gate
> replaces.

**Transition:** `phases[phase1-why2]` — see `workflow/definition.yaml`
