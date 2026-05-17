# Phase: re-extract-0-preflight
# Read by: speckit-echelon-commander (COMMANDER) — brownfield extraction preflight
# Type: commander_internal — COMMANDER executes these steps directly, no agent dispatch

**Execution Continuity:** After each step, immediately proceed to the next without pausing.

## Preflight checks — ANY failure is a HARD STOP

### 1. jq availability

```bash
command -v jq
```

If exit code non-zero: report error "jq is required for brownfield extraction. Install via: `brew install jq` (macOS) or `apt-get install jq` (Linux)". HARD STOP.

### 2. Output directory

```bash
mkdir -p .specify/echelon/re
```

### 3. Codebase non-empty

Use Glob tool to count source files matching `**/*.{ts,js,py,go,rs,java,kt,cs,rb,cpp,c,swift}`.
If count < 5: warn "Fewer than 5 source files found — analysis may be sparse" but continue.

### 4. Read thresholds from echelon-config.yml

```bash
COVERAGE_THRESHOLD=$(bash .specify/extensions/echelon/scripts/bash/echelon-config-get.sh re.workflow.coverage_threshold 2>/dev/null || echo "80")
RESOLUTION_THRESHOLD=$(bash .specify/extensions/echelon/scripts/bash/echelon-config-get.sh re.workflow.resolution_threshold 2>/dev/null || echo "80")
MAX_VALIDATE=$(bash .specify/extensions/echelon/scripts/bash/echelon-config-get.sh re.workflow.max_validate_iterations 2>/dev/null || echo "3")
OUTPUT_DIR=$(bash .specify/extensions/echelon/scripts/bash/echelon-config-get.sh re.output.directory 2>/dev/null || echo ".specify/echelon/re")
```

### 5. Initialize `.specify/echelon/re/state.json`

If the file does not exist, create it:

```python
import json, sys, os
from pathlib import Path
state_path = Path('.specify/echelon/re/state.json')
if not state_path.exists():
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    state = {
        'run_id': f're-{ts}', 'status': 'in_progress',
        'phase': 're-extract-0-preflight',
        'last_dispatch': {'phase_id': None, 'agent': None, 'post_dispatch_complete': False, 'dispatched_at': None},
        'mode': 'single', 'output_dir': os.environ.get('OUTPUT_DIR', '.specify/echelon/re'),
        'domains': [], 'coverage_pct': 0,
        'coverage_threshold': int(os.environ.get('COVERAGE_THRESHOLD', 80)),
        'verify_expand_iterations': 0, 'resolution_pct': 0,
        'resolution_threshold': int(os.environ.get('RESOLUTION_THRESHOLD', 80)),
        'validate_iterations': 0,
        'max_validate_iterations': int(os.environ.get('MAX_VALIDATE', 3)),
        'artifacts': {'analysis_json': '.specify/echelon/re/analysis.json',
                      'repos_manifest': '.specify/echelon/re/repos-manifest.json', 'cross_repo': None},
        'issues_log': []
    }
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with open(state_path, 'w') as f:
        json.dump(state, f, indent=2)
    sys.stdout.write('Initialized re/state.json\n')
else:
    sys.stdout.write('Re-using existing re/state.json (resumption mode)\n')
```

Preflight complete. Advance to `re-extract-1-analyze`.
