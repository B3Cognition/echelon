# Phase: phase1-synthesizer
# Source: echelon.run.md §2b — echelon.synthesizer (SYNTHESIZER) Phase
# Agent: echelon.synthesizer (SYNTHESIZER)
# Read by: echelon.commander (COMMANDER) before dispatching echelon.synthesizer (SYNTHESIZER)

## 2b. echelon.synthesizer (SYNTHESIZER) Phase

echelon.synthesizer (SYNTHESIZER) fuses ALL DISCOVER outputs into a unified knowledge base. This is mandatory — WHY1 must receive synthesized output, not raw fragments.

### Context Pack Assembly

Read and include in the subagent prompt:

- ALL DISCOVER outputs (every .md file produced in step 2)
- reasoning-journal.jsonl (DISCOVER entries)
- `.echelon/runtime/templates/glossary-template.md`
- `.echelon/runtime/templates/mental-model-template.md`
- `.echelon/runtime/templates/boundaries-template.md`
- `.echelon/runtime/templates/assumptions-template.md`
- `.echelon/runtime/templates/unknowns-template.md`
- `.echelon/runtime/templates/contradictions-and-gaps-template.md`
- `.echelon/runtime/templates/risks-template.md`
- `.echelon/runtime/templates/people-and-teams-template.md`
- `.echelon/runtime/templates/timeline-template.md`
- `.echelon/runtime/templates/qa-test-strategy-inputs-template.md`

### Dispatch

The active runtime dispatches this role with the following request:

- **prompt:**

  ```xml
  <context>
  [include all DISCOVER outputs, synthesizer output templates, reasoning-journal.jsonl (DISCOVER entries)]
  </context>

  <instructions>
  You are SYNTHESIZER. Read agents/exploration/synthesizer.md for your complete protocol.
  Read ALL DISCOVER outputs and fuse them into a unified knowledge base. Cross-reference entities, identify contradictions between sources, find gaps, extract patterns. Produce unified outputs in `${STAGING_DIR}/` using the provided templates. Return journal entries in `echelon_result.journal_entries`.
  </instructions>
  ```

- **description:** "echelon.synthesizer (SYNTHESIZER): fuse discovery outputs into unified knowledge base"

### Expected Outputs

- `glossary.md` (unified, with conflicts flagged)
- `mental-model.md` (unified, with gaps flagged)
- `boundaries.md` (unified, with contradictions flagged)
- `assumptions.md` (unified, deduplicated)
- `unknowns.md` (unified, prioritized)
- `contradictions-and-gaps.md` (cross-source analysis)
- `risks.md` (synthesized risks)
- `people-and-teams.md` (if discoverable)
- `timeline.md` (if discoverable)
- `qa-test-strategy-inputs.md` (if discoverable)

### Post-Dispatch

Read `contradictions-and-gaps.md`. If CRITICAL contradictions found, log them — WHY1 will challenge these specifically.

**Transition:** `phases[phase1-modeler]` — see `workflow/definition.yaml`
