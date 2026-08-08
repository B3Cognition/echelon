# Recovery Checklist

Use this after fallback or degraded recovery before continuing normal workflow.

- Confirm the latest valid `state.json` loads and contains the expected phase, run id, and squad status.
- Confirm `reasoning-journal.jsonl` is append-only, valid JSONL, and includes recovery/degraded entries.
- Confirm pending journal or KB writes were replayed or explicitly queued.
- Confirm generated artifacts referenced by state exist on disk.
- Confirm degraded decisions include owner, impact, and follow-up action.
- Run the narrowest relevant verification command before resuming the next phase.

If any item fails, keep `recovery_mode=true`, record the blocker, and continue only through the documented degraded path.
