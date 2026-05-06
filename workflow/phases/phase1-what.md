# Phase: phase1-what
# Source: echelon.run.md §4 — WHAT Phase (Requirements Definition)
# Agent: CARTOGRAPHER
# Read by: COMMANDER before dispatching CARTOGRAPHER

## 4. WHAT Phase (Requirements Definition)

> **Transition from UNDERSTAND to DECIDE:** This phase bridges understanding to decision-making. Constitution is now established. CARTOGRAPHER owns spec creation — it calls `speckit.specify` itself.

### 4.1 Context Pack Assembly

Read and include in the subagent prompt (all from `.specify/squad/staging/`):

- `glossary.md` + `mental-model.md` + `boundaries.md`
- `assumptions.md` + `unknowns.md`
- `reference-architectures.md` (if greenfield)
- `reasoning-journal.json` (filtered to DISCOVER + WHY1 entries)
- User input (original request)

### 4.2 Dispatch CARTOGRAPHER

CARTOGRAPHER calls `speckit.specify` itself (via Skill tool) — just like GOLDDIGGER calls revenge extension and SAGE calls Understanding via Skill tool. COMMANDER does NOT call `speckit.specify`.

Use the Agent tool to dispatch a subagent with:

- **prompt:**

  ```xml
  <context>
  [include glossary.md, mental-model.md, boundaries.md, assumptions.md, unknowns.md, reference-architectures.md if greenfield, reasoning-journal.json — all from .specify/squad/staging/, user input]
  </context>

  <instructions>
  You are CARTOGRAPHER. Read agents/exploration/cartographer.md for your complete protocol.
  You will call `speckit.specify` to create the feature branch and spec directory, then move staging artifacts, then enhance the spec with SCOUT's domain insights. Add user stories with acceptance criteria (Given/When/Then). Cross-reference the glossary and mental model. No implementation details — no languages, frameworks, or databases. Staging directory: `.specify/squad/staging/`. Append entries to `reasoning-journal.json`.
  </instructions>
  ```

- **description:** "CARTOGRAPHER: spec creation and requirements definition"

#### CARTOGRAPHER Fallback (if CARTOGRAPHER signals BLOCKED on speckit.specify)

If CARTOGRAPHER returns `CARTOGRAPHER BLOCKED — speckit.specify unavailable`:

1. COMMANDER calls `speckit.specify` directly (via Skill tool) with the same feature description CARTOGRAPHER would have used (derive from DISCOVER staging artifacts)
2. After the Skill returns (success or error):
   - **Success:** Update `state.json` with the returned `spec_id` and `spec_dir`, then re-dispatch CARTOGRAPHER with the spec directory already created (add `spec_dir` to the context pack prompt). Continue to 4.3 immediately — **do not stop**.
   - **Error:** Set `state.json.status = "blocked"`, set `blocked_reason = "speckit.specify unavailable"`, print the BLOCKED banner, stop.

This is the only case where COMMANDER calls `speckit.specify` directly. Do NOT use this path pre-emptively.

### 4.3 Post-CARTOGRAPHER

After CARTOGRAPHER completes, read its output to get the created `spec_id` and `spec_dir`.

#### Branch + Directory Verification (MANDATORY)

Before updating state.json, verify both invariants:

1. **Branch exists:**
   ```bash
   git branch --show-current
   ```
   The output must equal `{NNN}-{feature-name}` from CARTOGRAPHER's output.

2. **Spec directory exists:**
   ```bash
   ls "{spec_dir}/spec.md"
   ```

**If either check fails** (branch missing, directory missing, or spec.md missing):

1. If the branch is missing, create it now:
   ```bash
   git checkout -b {NNN}-{feature-name}
   ```
2. If `specs/{NNN}-{feature-name}/` is missing, create it and re-dispatch CARTOGRAPHER with `spec_dir` pre-set in the context pack — CARTOGRAPHER will skip `speckit.specify` and proceed directly to Step 2 (spec enhancement).
3. Log a `branch_recovery` entry to `journal.json`:
   ```json
   {
     "type": "branch_recovery",
     "phase": "phase1-what",
     "agent": "COMMANDER",
     "detail": "Feature branch was absent after CARTOGRAPHER completed — created manually",
     "timestamp": "{ISO-8601}"
   }
   ```

**If both checks pass**, proceed normally.

Update state.json:

```json
{
  "spec_id": "{NNN}",
  "spec_dir": "specs/{NNN}-{feature-name}",
  "updated_at": "{ISO-8601}"
}
```

**Spec Status Transition (mandatory):**
Update `state.json.spec_status` to `"planned"`.
Update `{spec_dir}/spec.md`: find the line `**Status**: Draft` and change it to `**Status**: Planned`.

### Expected Outputs

- `spec.md` (created by `speckit.specify`, enhanced by CARTOGRAPHER)
- `00-overview.md`

**Transition:** `phases[phase1-why2]` — see `workflow/definition.yaml`
