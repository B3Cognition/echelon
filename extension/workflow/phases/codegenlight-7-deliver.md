# Phase: codegenlight-7-deliver
# Source: echelon.codegenlight.md §Phase 7 + Terminal Summary + SOAR Integration Points
# Read by: speckit-echelon-orchestrator (ORCHESTRATOR) after TEST gate passes

**Print:** `[CODEGEN] Phase DELIVER — Assembling delivery package...`

SOAR selects DELIVER only when:
- All Tier 1 tests pass
- Ψ ≥ 0.70
- Zero confirmed CQ-ISC violations

When SOAR selects DELIVER:

1. Write `./codegen-report.md` — human-readable summary including requirement citations per delivered feature.
2. Export EPMEM:
   ```bash
   codegen gate --phase DELIVER --language <language> --files <files> --state-file codegen-state.json
   ```
3. Update `codegen-state.json`: `wall_clock_end = now`.

**Git operations (FR-CMD-006):** Present for user approval:
```
[CODEGEN] Proposed git operations:
  git add <generated files>
  git commit -m "codegen: <intent summary>"
Approve? (yes/no):
```
Always wait for approval. Do NOT execute without approval.

**Write state checkpoint:** `current_phase: "DONE"`

Remove gate sentinel:
```bash
rm -f .codegen-active
```

```bash
write_state "done" "build_done" $TOTAL_TASKS null '"PASS"'
```

---

## Terminal Summary (FR-CMD-003)

```
╔══════════════════════════════════════════════════════╗
║         CODEGEN — Pipeline Summary                   ║
╠══════════════════════════════════════════════════════╣
║ Pipeline ID : <pipeline_id>                          ║
║ Wing        : <wing>                                 ║
║ Mode        : <brownfield|greenfield|spec-driven>    ║
║ Final phase : <DELIVER|BLOCKED|ESCALATED>            ║
╠══════════════════════════════════════════════════════╣
║ Requirements: <N> retrieved from MemPalace           ║
║ Ψ score     : <score> (threshold 0.70)               ║
║ Tier 1 gate : <PASS|FAIL|UNAVAILABLE>                ║
║ CQ-ISC violations blocked : <count>                  ║
║ Impasse escalations       : <count>                  ║
║ Wall-clock time           : <HH:MM:SS>               ║
╠══════════════════════════════════════════════════════╣
║ Tasks: <done> done / <blocked> blocked / <total> total║
╚══════════════════════════════════════════════════════╝
```

---

## SOAR Integration Points

```bash
# Gate a phase
codegen gate --phase <PHASE> --language <lang> --files <files> --state-file codegen-state.json

# Check pipeline state
codegen status --state-file codegen-state.json

# Search mined requirements
codegen requirements search "<query>" --wing <wing>

# Mine additional specs mid-run
codegen requirements mine <file> --wing <wing>

# Repair memory if corrupted
codegen memory repair --store epmem
```
