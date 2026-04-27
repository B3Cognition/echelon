# B4 Audit Log

Records B4 pipeline compatibility verification for each agent.
Previously these notes were embedded as `# B4-INVISIBLE` inline comments in agent prompts,
where the model would read and potentially echo them. Moved here 2026-04-27.

---

## Verified agents

| Agent | Verified | Condition | Notes |
|-------|----------|-----------|-------|
| code-reviewer | 2026-04-05 | always | Re-audit if B4 gains frequency-assertion plugins |
| progress-tracker | 2026-04-05 | always | Re-audit if B4 gains frequency-assertion plugins |
| spec-guard | 2026-04-05 | always | Re-audit if B4 gains frequency-assertion plugins |
| test-guardian | 2026-04-05 | always | Re-audit if B4 gains frequency-assertion plugins |
| realist | 2026-04-05 | always | Re-audit if B4 gains frequency-assertion plugins |
| validator | 2026-04-05 | always | Re-audit if B4 gains frequency-assertion plugins |

## Unregistered agents

| Agent | Status | Action required |
|-------|--------|-----------------|
| consolidator | Tier 3A — not yet in `b4-config.yaml` | Add to `b4-config.yaml` to activate B4 Tier 1 coverage |
