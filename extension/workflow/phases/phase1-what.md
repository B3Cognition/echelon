# Phase: phase1-what
# Source: echelon.run.md §4 — WHAT Phase (Requirements Definition)
# Agent: speckit-echelon-cartographer (CARTOGRAPHER)
# Read by: speckit-echelon-commander (COMMANDER) before dispatching speckit-echelon-cartographer (CARTOGRAPHER)

## 4. WHAT Phase (Requirements Definition)

> **Transition from UNDERSTAND to DECIDE:** This phase bridges understanding to decision-making. Constitution is now established. speckit-echelon-cartographer (CARTOGRAPHER) owns spec creation — it calls `speckit.specify` itself.

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

speckit-echelon-cartographer (CARTOGRAPHER) calls `speckit.specify` itself (via Skill tool) on the first WHAT pass, just as speckit-echelon-sage (SAGE) calls Understanding via Skill tool. speckit-echelon-commander (COMMANDER) does NOT call `speckit.specify`.

On resumed/amendment passes, reuse the existing spec directory only when
`{spec_dir}/spec.md` exists. `cartographer_resume_existing_spec: true` is
advisory and never overrides this file check. A Phase A bootstrap may reserve a
run-local `spec_dir` before WHAT, so a directory without `spec.md` is a **first
WHAT pass**: CARTOGRAPHER MUST invoke `speckit.specify` rather than treating it
as an amendment.

Use the Agent tool to dispatch a subagent with:

- **prompt:**

  ```xml
  <context>
  [include read-only .specify/memory/constitution.md, glossary.md, mental-model.md, boundaries.md, assumptions.md, unknowns.md, reference-architectures.md if greenfield, cartographer output templates, reasoning-journal.jsonl — staging artifacts from ${STAGING_DIR}/, user input]
  </context>

  <instructions>
  You are CARTOGRAPHER. Read agents/exploration/cartographer.md for your complete protocol.
  If this is a first WHAT pass with no existing `{spec_dir}/spec.md`, call `speckit.specify` to create the feature branch and spec directory, then move discovery artifacts, then enhance the spec with speckit-echelon-scout (SCOUT)'s domain insights. A reserved directory by itself is not an existing spec.
  If this is a resumed/amendment pass and `{spec_dir}/spec.md` exists, skip `speckit.specify` and enhance that existing spec in place. Always keep the existing branch and spec directory; do not create or switch to a new numbered branch.
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
  - For Lexicon Gate validation, use `lexicon validate "{spec_dir}/{lexicon_path}" --type {artifact_type} --source-ref "{spec_dir}/{source_ref}" --glossary "{spec_dir}/{glossary_file}" --json` and treat that result as authoritative for `lexicon_pass`.

  Always complete ALL of the following before returning. Do NOT return until they are true:
  1. `{spec_dir}/spec.md` exists and contains Given/When/Then acceptance criteria for every user story.
  2. `{spec_dir}/00-overview.md` exists (your 1-2 page human-readable summary).
  3. All discovery artifacts have been moved from `${STAGING_DIR}/` to `{spec_dir}/`; run-control files (`user-clarifications.md`, `governance-trail.json`, `escalation-request.md`) remain in staging.
  Calling `speckit.specify` alone is NOT sufficient — Step 2 (spec enhancement) is mandatory before returning.
  </instructions>
  ```

- **description:** "speckit-echelon-cartographer (CARTOGRAPHER): spec creation and requirements definition"

#### speckit-echelon-cartographer (CARTOGRAPHER) Fallback (if speckit-echelon-cartographer (CARTOGRAPHER) signals BLOCKED on speckit.specify)

If speckit-echelon-cartographer (CARTOGRAPHER) returns `speckit-echelon-cartographer (CARTOGRAPHER) BLOCKED — speckit.specify unavailable`:

1. speckit-echelon-commander (COMMANDER) calls `speckit.specify` directly (via Skill tool) with the same feature description speckit-echelon-cartographer (CARTOGRAPHER) would have used (derive from DISCOVER staging artifacts)
2. After the Skill returns (success or error):
   - **Success:** Return the returned `spec_id` and `spec_dir` in `echelon_result.state_updates`, then re-dispatch speckit-echelon-cartographer (CARTOGRAPHER) with the spec directory already created (add `spec_dir` to the context pack prompt). Always continue to 4.3 immediately — **do not stop**.
   - **Error:** Return `status: blocked` and `blocked_reason: "speckit.specify unavailable"` in `echelon_result.state_updates`, return a blocking journal entry, and stop.

This is the only case where speckit-echelon-commander (COMMANDER) calls `speckit.specify` directly. Always reserve this path for the explicit BLOCKED fallback. Do NOT use it pre-emptively.

### 4.3 Post-speckit-echelon-cartographer (CARTOGRAPHER)

After speckit-echelon-cartographer (CARTOGRAPHER) completes, read its output to get the created `spec_id` and `spec_dir`.

Treat `spec_dir` as authoritative. It may be an absolute path or a repository-relative path returned by the Skill/harness. Use it exactly as returned for file checks and prompts; NEVER prefix it with `${SQUAD_DIR}`, `${STAGING_DIR}`, or another `specs/` segment.

#### Branch + Directory Verification (MANDATORY)

Before returning state updates, verify both invariants:

1. **Branch exists:**
   ```bash
   git branch --show-current
   ```
   The output must equal `{NNN}-{feature-name}` from speckit-echelon-cartographer (CARTOGRAPHER)'s output.

2. **Spec directory exists:**
   ```bash
   ls "{spec_dir}/spec.md"
   ```

**If either check fails** (branch missing, directory missing, or spec.md missing):

1. If the branch is missing, create it now:
   ```bash
   git checkout -b {NNN}-{feature-name}
   ```
2. If `{spec_dir}/` is missing, create it and re-dispatch speckit-echelon-cartographer (CARTOGRAPHER) with `spec_dir` pre-set in the context pack — speckit-echelon-cartographer (CARTOGRAPHER) will skip `speckit.specify` and proceed directly to Step 2 (spec enhancement).
3. Return a `branch_recovery` entry in `echelon_result.journal_entries`; the harness writes it to `reasoning-journal.jsonl`.

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

Always resolve constitution placeholders through CHIEF before Phase 2. Do NOT proceed to Phase 2 with unfilled placeholders in constitution.md. A constitution with `[CONSTITUTION_VERSION]` in it is not a constitution — it is a template. speckit-echelon-cartographer (CARTOGRAPHER) will skip `speckit.specify` and go directly to Step 2. A spec.md with zero acceptance criteria is not complete output.

**Enhancement-only re-dispatch prompt:**

```xml
<context>
[include same context pack as first dispatch, including read-only .specify/memory/constitution.md, plus current contents of {spec_dir}/spec.md]
spec_dir: {spec_dir}
</context>

<instructions>
You are CARTOGRAPHER in enhancement-only mode. The spec directory already exists at `{spec_dir}`. Always go directly to Step 2: enhance spec.md with Given/When/Then acceptance criteria and cross-references, then produce 00-overview.md. Skip Step 1 (do NOT call speckit.specify again). Read cartographer.md §"Step 2: Enhance Spec with Squad Intelligence" for the full protocol.
Treat `.specify/memory/constitution.md` as read-only governance context. Do not edit, patch, append to, or regenerate it.

Always complete these outputs before returning. Do NOT return until:
1. `{spec_dir}/spec.md` contains Given/When/Then acceptance criteria for every user story.
2. `{spec_dir}/00-overview.md` exists.
</instructions>
```

Return these state updates in `echelon_result`; the harness applies them to `state.json`:

```yaml
echelon_result:
  state_updates:
    spec_id: "{NNN}"
    spec_dir: "specs/{NNN}-{feature-name}"
    spec_status: planned
    updated_at: "{ISO-8601}"
```

### Spec Status Transition — MANDATORY

This step is part of the `echelon_result.state_updates` block above. Skipping it leaves downstream phases reading a stale `Status: Draft` flag.

1. Return `spec_status: planned` in the same `echelon_result.state_updates` block as `spec_id` and `spec_dir`.
2. Update `{spec_dir}/spec.md`: replace the line `**Status**: Draft` with `**Status**: Planned`.
3. **Verification (run after the harness applies state updates, before transitioning to phase1-why2):**

   ```bash
   grep -q '^\*\*Status\*\*: Planned' "${spec_dir}/spec.md" || { echo "ERROR: spec.md still shows Draft" >&2; exit 1; }
   python3 -c "import json; assert json.load(open('${SQUAD_DIR}/state.json'))['spec_status']=='planned'" || { echo "ERROR: state.json.spec_status not 'planned'" >&2; exit 1; }
   ```

   If either check fails, halt the phase and resolve before proceeding.

### Expected Outputs — BOTH REQUIRED

- `spec.md` (created by `speckit.specify`, enhanced by speckit-echelon-cartographer (CARTOGRAPHER) with GWT acceptance criteria and glossary cross-references)
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
  `lexicon validate --source-ref`, and return `lexicon_pass`."

CARTOGRAPHER owns the in-dispatch repair loop (the "fix"). COMMANDER owns the re-dispatch
decision on the controlled outcome (the "re-dispatch"). COMMANDER does NOT run `lexicon` itself.

**Controlled-outcome routing.** After the dispatch, read `state.json.lexicon_pass`:
- `lexicon_pass == true` → proceed to `phase1-why2` (soft `understanding`/SAGE scoring runs there,
  once, on rich `spec.md`, after the derived requirements artifact is structurally clean).
- `lexicon_pass == false AND iteration < max_iterations` → re-dispatch `phase1-what`
  (`increment_iteration`). This is the only condition that re-dispatches CARTOGRAPHER on the
  Lexicon outcome — see the transitions in `workflow/definition.yaml`.
- `iteration >= max_iterations` → honor `lexicon_gate.on_exhausted`:
  `warn` → proceed to `phase1-why2` with a `lexicon_gate_exhausted` warning journal entry;
  `block` → set `spec_status: blocked`, `blocked_reason: "lexicon gate not satisfied"`, and stop.

**State updates (added to the §4.3 block when the gate is enabled):**

```yaml
echelon_result:
  state_updates:
    lexicon_pass: true        # authoritative validator verdict for this pass
    lexicon_attempts: <int>
    lexicon_findings: <int>
```

> Ordering invariant: Lexicon is the FIRST, hard, deterministic gate; `understanding`/SAGE
> (phase1-why2) is the soft score that runs only AFTER `lexicon_pass`. The hard gate validates
> `requirements.lexicon.md`; the soft score still reads the canonical rich `spec.md`. Never let
> the soft score gate structure — that is the "score-quality-later" anti-pattern this gate
> replaces.

**Transition:** `phases[phase1-why2]` — see `workflow/definition.yaml`
