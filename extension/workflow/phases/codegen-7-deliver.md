# Phase: codegen-7-deliver
# Source: echelon.codegen.md §Phase 7 + Terminal Summary + Harness Integration
# Read by: echelon-orchestrator (ORCHESTRATOR) after TEST (and SECURITY) gates pass

## Phase 7: DELIVER

**Print:** `[CODEGEN] Phase DELIVER — Assembling delivery package...`

SOAR selects DELIVER only when: all Tier 1 tests pass, Ψ ≥ 0.70, zero CQ-ISC violations.

**RUNNABLE precondition (hard):** DELIVER MUST refuse to package unless
`codegen-state.json` has `runnable_gate == "pass"`. If it is absent or `"fail"`,
HALT and route back to RUNNABLE — a static-hollow app whose entry point does not
compose real feature components is never shippable, regardless of Ψ or unit-test
status. A passing RUNNABLE gate is still a static composition claim, not runtime
boot/render proof.

1. Write `./codegen-report.md` — human-readable summary with requirement citations per delivered feature.
1b. **Write `./codegen-verification.md` — the honest verification-boundary manifest, and print its terminal summary.** Every gate is a proxy; this states what each did NOT bind so the green checks are not mistaken for a working system. Lead the human with the gaps, not the verdict:
   ```bash
   python3 - <<'PY'
   import json
   from codegen.delivery.verification_manifest import build_manifest, render_markdown, terminal_summary
   state = json.load(open("codegen-state.json"))
   m = build_manifest(state)
   open("codegen-verification.md", "w").write(render_markdown(m))
   print(terminal_summary(m))
   PY
   ```
   ALWAYS emit `codegen-verification.md` and surface its "NOT verified" set at DELIVER.
   NEVER report the build as "complete" or "verified" — DELIVER produces a *claim*; only a human observing the running artifact converts it to a fact.
2. Export EPMEM:
   ```bash
   codegen gate --phase DELIVER --language <language> --files <files> --state-file codegen-state.json
   ```
3. Update `codegen-state.json`: `wall_clock_end = now`.

**Git operations:**

If `$HARNESS_BUILD_STATUS_FILE` is set (running under harness) — execute automatically without prompting:
```bash
git add <generated files>
git commit -m "codegen: <intent summary>"
```

If `$HARNESS_BUILD_STATUS_FILE` is NOT set (standalone `echelon codegen` invocation) — present for user approval before executing:

```
[CODEGEN] Proposed git operations:
  git add <generated files>
  git commit -m "codegen: <intent summary>"
Approve? (yes/no):
```

```bash
rm -f .codegen-active
write_state "done" "build_done" $TOTAL_TASKS null '"PASS"'
```

---

## Terminal Summary

Print the verification terminal summary (step 1b) FIRST — the unverified
boundaries lead, before the green banner — so the reader sees the gaps before the
checkmarks. The banner below reports *claims*, not a verdict of correctness.

```
╔══════════════════════════════════════════════════════╗
║         CODEGEN — Pipeline Summary (claims)          ║
╠══════════════════════════════════════════════════════╣
║ Pipeline ID : <pipeline_id>                          ║
║ Wing        : <wing>                                 ║
║ Feature     : <feature_path>                         ║
║ Outcome     : <DELIVERED|BLOCKED|ESCALATED>          ║
║ Verified by human: NO — required before trusting     ║
║ Boundaries not gated: see codegen-verification.md    ║
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

## Harness Integration: Report Build Status

If `$HARNESS_BUILD_STATUS_FILE` is set, write the outcome after the skill completes so the Python harness can detect success or impasse:

```bash
if [ -n "$HARNESS_BUILD_STATUS_FILE" ]; then
  if [ -f "codegen-impasse.md" ]; then
    printf '{"status":"impasse","impasse_file":"codegen-impasse.md"}' > "$HARNESS_BUILD_STATUS_FILE"
  else
    printf '{"status":"done"}' > "$HARNESS_BUILD_STATUS_FILE"
  fi
fi
```

If `$HARNESS_BUILD_STATUS_FILE` is not set (standalone invocation), skip this step entirely.
