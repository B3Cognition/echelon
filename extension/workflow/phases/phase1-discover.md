# Phase: phase1-discover
# Source: echelon.run.md §2 — DISCOVER Phase (UNDERSTAND)
# Agent: speckit-echelon-scout (SCOUT)
# Read by: speckit-echelon-commander (COMMANDER) before dispatching speckit-echelon-scout (SCOUT)

## 2. DISCOVER Phase (UNDERSTAND)

> **Note:** This is the UNDERSTAND phase. We don't yet know WHAT to build, so outputs go to the staging area. The spec directory is created later when `speckit.specify` runs.

### Context Pack Assembly

Read and include in the subagent prompt:

- User input (the `$ARGUMENTS` from above)
- `knowledge-base/calibration-profile.yaml`
- Previous run's `evolution-report.md` (if re-run)
- If `state.json.golddigger_artifacts` exists: include artifact paths so the agent knows where to read brownfield data
  - Polyrepo: include `repos-manifest.json` path, `cross-repo.json` path, per-repo directory paths
  - Single-repo: include `analysis.json` path
- If any `golddigger_completed_domains` have new entries since last dispatch: include the corresponding cache file paths

### Dispatch

Use the Agent tool to dispatch a subagent with:

- **prompt:**

  ```xml
  <context>
  [include user input, knowledge-base/calibration-profile.yaml, previous run's evolution-report.md if re-run, state.json.golddigger_artifacts paths if available]
  </context>

  <instructions>
  You are SCOUT. Read agents/exploration/scout.md for your complete protocol.
  Your mode is `{greenfield|brownfield}`. Produce all outputs in `${STAGING_DIR}/`. Append entries to `reasoning-journal.jsonl` for every significant insight, assumption, or decision.
  </instructions>
  ```

- **description:** "speckit-echelon-scout (SCOUT): reconnaissance and domain mapping ({mode})"

### Expected Outputs

Verify these files were created in `${STAGING_DIR}/`:

- `glossary.md`
- `mental-model.md`
- `boundaries.md`
- `assumptions.md`
- `unknowns.md`
- `reference-architectures.md` (greenfield only)

If any are missing, log a warning but continue — WHY1 will catch gaps.

### Post-Dispatch

Read DISCOVER's outputs to classify the domain. Store domain classification for specialist summoning later. Append routing decision to reasoning journal.

**Transition:** `phases[phase1-synthesizer]` — see `workflow/definition.yaml`
