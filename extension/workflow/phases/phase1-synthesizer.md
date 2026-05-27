# Phase: phase1-synthesizer
# Source: echelon.run.md §2b — speckit-echelon-synthesizer (SYNTHESIZER) Phase
# Agent: speckit-echelon-synthesizer (SYNTHESIZER)
# Read by: speckit-echelon-commander (COMMANDER) before dispatching speckit-echelon-synthesizer (SYNTHESIZER)

## 2b. speckit-echelon-synthesizer (SYNTHESIZER) Phase

speckit-echelon-synthesizer (SYNTHESIZER) fuses ALL DISCOVER outputs into a unified knowledge base. This is mandatory — WHY1 must receive synthesized output, not raw fragments.

### Context Pack Assembly

Read and include in the subagent prompt:

- ALL DISCOVER outputs (every .md file produced in step 2)
- reasoning-journal.jsonl (DISCOVER entries)

### Dispatch

Use the Agent tool to dispatch a subagent with:

- **prompt:**

  ```xml
  <context>
  [include all DISCOVER outputs, reasoning-journal.jsonl (DISCOVER entries)]
  </context>

  <instructions>
  You are SYNTHESIZER. Read agents/exploration/synthesizer.md for your complete protocol.
  Read ALL DISCOVER outputs and fuse them into a unified knowledge base. Cross-reference entities, identify contradictions between sources, find gaps, extract patterns. Produce unified outputs in `${STAGING_DIR}/`. Append entries to `reasoning-journal.jsonl`.
  </instructions>
  ```

- **description:** "speckit-echelon-synthesizer (SYNTHESIZER): fuse discovery outputs into unified knowledge base"

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
