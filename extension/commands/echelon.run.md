---
name: speckit.echelon.run
description: "Full autonomous cognitive squad run — drives pre-code phases via deterministic harness"
scripts:
  sh: ../../scripts/bash/startup-banner.sh
---

## Launch

```bash
echelon run "$@"
```

This command delegates entirely to the Python squad harness (`src/harness/squad.py`).
Phase routing is deterministic — COMMANDER is dispatched only for judgment calls
(escalation, contradictions, human gates in guided mode).

Monitor: `.specify/squad/state.json` · `.specify/squad/reasoning-journal.jsonl`
