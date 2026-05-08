# Phase: phase1-what
# Source: echelon.run.md §4 — WHAT Phase (Requirements Definition)
# Agent: speckit-echelon-cartographer (CARTOGRAPHER)
# Read by: speckit-echelon-commander (COMMANDER) before dispatching speckit-echelon-cartographer (CARTOGRAPHER)

## 4. WHAT Phase (Requirements Definition)

> **Transition from UNDERSTAND to DECIDE:** This phase bridges understanding to decision-making. Constitution is now established. speckit-echelon-cartographer (CARTOGRAPHER) owns spec creation — it calls `speckit.specify` itself.

### 4.1 Context Pack Assembly

Read and include in the subagent prompt (all from `.specify/squad/staging/`):

- `glossary.md` + `mental-model.md` + `boundaries.md`
- `assumptions.md` + `unknowns.md`
- `reference-architectures.md` (if greenfield)
- `reasoning-journal.json` (filtered to DISCOVER + WHY1 entries)
- User input (original request)

### 4.2 Dispatch speckit-echelon-cartographer (CARTOGRAPHER)

speckit-echelon-cartographer (CARTOGRAPHER) calls `speckit.specify` itself (via Skill tool) — just like speckit-echelon-golddigger (GOLDDIGGER) calls revenge extension and speckit-echelon-sage (SAGE) calls Understanding via Skill tool. speckit-echelon-commander (COMMANDER) does NOT call `speckit.specify`.

Use the Agent tool to dispatch a subagent with:

- **prompt:**

  ```xml
  <context>
  [include glossary.md, mental-model.md, boundaries.md, assumptions.md, unknowns.md, reference-architectures.md if greenfield, reasoning-journal.json — all from .specify/squad/staging/, user input]
  </context>

  <instructions>
  You are CARTOGRAPHER. Read agents/exploration/cartographer.md for your complete protocol.
  You will call `speckit.specify` to create the feature branch and spec directory, then move staging artifacts, then enhance the spec with speckit-echelon-scout (SCOUT)'s domain insights. Add user stories with acceptance criteria (Given/When/Then). Cross-reference the glossary and mental model. No implementation details — no languages, frameworks, or databases. Staging directory: `.specify/squad/staging/`. Append entries to `reasoning-journal.json`.
  </instructions>
  ```

- **description:** "speckit-echelon-cartographer (CARTOGRAPHER): spec creation and requirements definition"

#### speckit-echelon-cartographer (CARTOGRAPHER) Fallback (if speckit-echelon-cartographer (CARTOGRAPHER) signals BLOCKED on speckit.specify)

If speckit-echelon-cartographer (CARTOGRAPHER) returns `speckit-echelon-cartographer (CARTOGRAPHER) BLOCKED — speckit.specify unavailable`:

1. speckit-echelon-commander (COMMANDER) calls `speckit.specify` directly (via Skill tool) with the same feature description speckit-echelon-cartographer (CARTOGRAPHER) would have used (derive from DISCOVER staging artifacts)
2. After the Skill returns (success or error):
   - **Success:** Update `state.json` with the returned `spec_id` and `spec_dir`, then re-dispatch speckit-echelon-cartographer (CARTOGRAPHER) with the spec directory already created (add `spec_dir` to the context pack prompt). Continue to 4.3 immediately — **do not stop**.
   - **Error:** Set `state.json.status = "blocked"`, set `blocked_reason = "speckit.specify unavailable"`, print the BLOCKED banner, stop.

This is the only case where speckit-echelon-commander (COMMANDER) calls `speckit.specify` directly. Do NOT use this path pre-emptively.

### 4.3 Post-speckit-echelon-cartographer (CARTOGRAPHER)

After speckit-echelon-cartographer (CARTOGRAPHER) completes, read its output to get the created `spec_id` and `spec_dir`.

#### Branch + Directory Verification (MANDATORY)

Before updating state.json, verify both invariants:

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
2. If `specs/{NNN}-{feature-name}/` is missing, create it and re-dispatch speckit-echelon-cartographer (CARTOGRAPHER) with `spec_dir` pre-set in the context pack — speckit-echelon-cartographer (CARTOGRAPHER) will skip `speckit.specify` and proceed directly to Step 2 (spec enhancement).
3. Log a `branch_recovery` entry to `journal.json`:
   ```json
   {
     "type": "branch_recovery",
     "phase": "phase1-what",
     "agent": "speckit-echelon-commander (COMMANDER)",
     "detail": "Feature branch was absent after speckit-echelon-cartographer (CARTOGRAPHER) completed — created manually",
     "timestamp": "{ISO-8601}"
   }
   ```

**If both checks pass**, verify CARTOGRAPHER ran the enhancement pass (Step 2 in `cartographer.md`) before updating state:

```bash
# spec.md must contain at least one WHEN/THEN acceptance criterion — proof of enhancement
grep -q "WHEN\|THEN\|Given\|When\|Then" "${spec_dir}/spec.md" \
  || { echo "WARN: spec.md has no WHEN/THEN criteria — CARTOGRAPHER may not have run Step 2 (enhancement pass)"; }
# 00-overview.md must exist
[ -f "${spec_dir}/00-overview.md" ] \
  || { echo "WARN: 00-overview.md missing — CARTOGRAPHER Step 2 may be incomplete"; }
```

If either warning fires: **re-dispatch CARTOGRAPHER** in enhancement-only mode with `spec_dir` pre-set in the context pack. CARTOGRAPHER will skip `speckit.specify` and go directly to Step 2. A spec.md with zero acceptance criteria is not complete output.

Update state.json:

```json
{
  "spec_id": "{NNN}",
  "spec_dir": "specs/{NNN}-{feature-name}",
  "updated_at": "{ISO-8601}"
}
```

### Spec Status Transition — MANDATORY

This step runs immediately after the state.json `spec_id`/`spec_dir` update above. Skipping it leaves downstream phases reading a stale `Status: Draft` flag.

1. Update `state.json.spec_status` to `"planned"` (in the same Edit operation as `spec_id`/`spec_dir` per the atomic-write discipline in [commander.md](../../agents/control/commander.md) Post-Dispatch Protocol).
2. Update `{spec_dir}/spec.md`: replace the line `**Status**: Draft` with `**Status**: Planned`.
3. **Verification (run before transitioning to phase1-why2):**

   ```bash
   grep -q '^\*\*Status\*\*: Planned' "${spec_dir}/spec.md" || { echo "ERROR: spec.md still shows Draft" >&2; exit 1; }
   python3 -c "import json; assert json.load(open('.specify/squad/state.json'))['spec_status']=='planned'" || { echo "ERROR: state.json.spec_status not 'planned'" >&2; exit 1; }
   ```

   If either check fails, halt the phase and resolve before proceeding.

### Expected Outputs — BOTH REQUIRED

- `spec.md` (created by `speckit.specify`, enhanced by CARTOGRAPHER with GWT acceptance criteria and glossary cross-references)
- `00-overview.md` (CARTOGRAPHER-authored 1–2 page human summary: what the feature does, key design choices, primary constraints)

**Post-dispatch verification (run before Spec Status Transition):**

```bash
[ -f "${spec_dir}/spec.md" ]        || { echo "ERROR: spec.md missing" >&2; exit 1; }
[ -f "${spec_dir}/00-overview.md" ] || { echo "ERROR: 00-overview.md missing" >&2; exit 1; }
# Confirm staging was moved (at least glossary.md must be in spec_dir)
[ -f "${spec_dir}/glossary.md" ]    || echo "WARN: staging artifacts may not have been moved to spec_dir"
```

**Transition:** `phases[phase1-why2]` — see `workflow/definition.yaml`
