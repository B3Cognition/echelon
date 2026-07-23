# Phase: phase1-discover
# Source: echelon.run.md §2 — DISCOVER Phase (UNDERSTAND)
# Agent: speckit-echelon-scout (SCOUT)
# Read by: speckit-echelon-commander (COMMANDER) before dispatching speckit-echelon-scout (SCOUT)

## 2. DISCOVER Phase (UNDERSTAND)

> **Note:** This is the UNDERSTAND phase. We don't yet know WHAT to build, so
> outputs go to the staging area. Echelon's Phase A bootstrap has already
> reserved the full run-local spec directory; CARTOGRAPHER moves product
> artifacts there during WHAT.

### Context Pack Assembly

Read and include in the subagent prompt:

- User input (the `$ARGUMENTS` from above)
- `knowledge-base/calibration-profile.yaml`
- Previous run's `evolution-report.md` (if re-run)
- `extension/templates/glossary-template.md`
- `extension/templates/mental-model-template.md`
- `extension/templates/boundaries-template.md`
- `extension/templates/assumptions-template.md`
- `extension/templates/unknowns-template.md`
- `extension/templates/reference-architectures-template.md`
- `state.json.published_re_context` and its immutable snapshot artifact paths

### Dispatch

Use the Agent tool to dispatch a subagent with:

- **prompt:**

  ```xml
  <context>
  [include user input, knowledge-base/calibration-profile.yaml, scout output templates, previous run's evolution-report.md if re-run, and state.json.published_re_context]
  </context>

  <instructions>
  You are SCOUT. Read agents/exploration/scout.md for your complete protocol.
  Your mode is `{greenfield|brownfield}`. Produce all outputs in `${STAGING_DIR}/` using the provided templates. Return journal entries in `echelon_result.journal_entries` for every significant insight, assumption, or decision.
  Product inputs are discovery evidence only in this phase. Never return `product_input_updates` from DISCOVER.
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
