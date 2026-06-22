# Phase: phase2-tracker-alignment
# Source: echelon.run.md §6c — speckit-echelon-tracker (TRACKER) Intent Alignment Check
# Agent: speckit-echelon-tracker (TRACKER) (mode: alignment-check)
# Read by: speckit-echelon-commander (COMMANDER) before dispatching speckit-echelon-tracker (TRACKER) for alignment check

### 6c. speckit-echelon-tracker (TRACKER) — Intent Alignment Check

After speckit-echelon-gatekeeper (GATEKEEPER) passes, dispatch speckit-echelon-tracker (TRACKER) to verify intent alignment:

Use the Agent tool:

- **prompt:**

  ```xml
  <context>
  [include user-intent.md, feasibility.md, mvp-scope.md, extension/templates/intent-alignment-check-template.md, reasoning-journal.jsonl]
  </context>

  <instructions>
  You are TRACKER. Read agents/control/tracker.md for your complete protocol. Operate in **alignment-check mode**.
  Read `user-intent.md` and speckit-echelon-gatekeeper (GATEKEEPER)'s outputs (`feasibility.md`, `mvp-scope.md`). Check whether speckit-echelon-gatekeeper (GATEKEEPER)'s scoping decisions align with the user's stated intent. If MISALIGNED, emit an alignment alert with specific divergence points. Produce `intent-alignment-check.md` in `{spec_dir}/` using the provided template. Return journal entries in `echelon_result.journal_entries`.
  </instructions>
  ```

- **description:** "speckit-echelon-tracker (TRACKER): verify speckit-echelon-gatekeeper (GATEKEEPER) scope aligns with user intent"

If speckit-echelon-tracker (TRACKER) reports MISALIGNED:
- MANAGER prints the divergence to terminal
- In `guided` or `semi` mode: pause for human confirmation
- In `banzai` mode: log the divergence, proceed with speckit-echelon-gatekeeper (GATEKEEPER)'s scope

### Output Filename — MANDATORY

Always name the output file exactly `intent-alignment-check.md`. **NEVER** produce `alignment-report.md`, `alignment.md`, `tracker-alignment.md`, or any other variant — downstream phases (and any future automated checks) look up this file by exact name.

Verification before transitioning to phase3-specialists:

```bash
[ -f "specs/${SPEC_DIR}/intent-alignment-check.md" ] || { echo "ERROR: intent-alignment-check.md missing" >&2; exit 1; }
```

**Transition:** `phases[phase3-specialists]` — see `workflow/definition.yaml`

### Intent Alignment Check Structural Gate — Controlled-Outcome Routing

When `governance.enabled` and the artifact has `tier: structural`, TRACKER authors
`intent-alignment-check.md` in the STRUCTURAL grammar and runs the in-dispatch
`$LEXICON validate --type structural --artifact intent-alignment-check` repair loop
(see `agents/control/tracker.md §Structural Gate Mode`). COMMANDER owns the re-dispatch decision
on the controlled outcome and is the sole writer to `state.json`; COMMANDER does NOT run `lexicon` itself.

> **Fail-open note:** If the gate is enabled but TRACKER returns no
> `intent_alignment_check_structural_pass` flag, routing treats it as passed (fail-open, consistent
> with `on_exhausted: warn`).

**Controlled-outcome routing.** After the dispatch, COMMANDER persists TRACKER's
`echelon_result.state_updates` and reads `state.json.intent_alignment_check_structural_pass`:
- `intent_alignment_check_structural_pass == true` → proceed to `phase3-specialists` (normal forward flow).
- `intent_alignment_check_structural_pass == false AND iteration < max_iterations` → re-dispatch
  `phase2-tracker-alignment` (`increment_iteration`). This is the only condition that re-dispatches
  TRACKER on the structural outcome — see the transitions in `workflow/definition.yaml`.
- `iteration >= max_iterations` → honor `governance.on_exhausted`:
  `warn` → proceed to `phase3-specialists` with a `structural_gate_exhausted` warning journal entry;
  `block` → set `status: blocked`, `blocked_reason: "intent-alignment-check structural gate not satisfied"`, stop.

**State updates (added to the dispatch's `echelon_result` block when the gate is enabled):**

```yaml
echelon_result:
  state_updates:
    intent_alignment_check_structural_pass: true     # authoritative validator verdict for this pass (true|false)
    intent_alignment_check_structural_attempts: <int>
```

> Registration invariant: `intent_alignment_check_structural_pass` is an authoritative state key
> (declared in this node's `outputs:` and read here), exactly as `lexicon_pass` is for phase1-what.
> The re-dispatch guard in `definition.yaml` references only `governance.enabled` +
> `intent_alignment_check_structural_pass` so it stays deterministically evaluable — it must NOT
> reference unresolvable config paths.
