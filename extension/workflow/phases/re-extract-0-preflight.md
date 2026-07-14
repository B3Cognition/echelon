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
CONFIGURED_OUTPUT_DIR=$(bash .specify/extensions/echelon/scripts/bash/echelon-config-get.sh re.output.directory 2>/dev/null || echo ".specify/echelon/re")
if [ "$CONFIGURED_OUTPUT_DIR" = ".specify/echelon/re" ] && [ -f runs/.current ]; then
  RUN_ID=$(cat runs/.current)
  if [ -n "$RUN_ID" ] && [ -d "runs/$RUN_ID" ]; then
    OUTPUT_DIR="runs/$RUN_ID/re"
  else
    OUTPUT_DIR="$CONFIGURED_OUTPUT_DIR"
  fi
else
  OUTPUT_DIR="$CONFIGURED_OUTPUT_DIR"
fi
export OUTPUT_DIR
mkdir -p "$OUTPUT_DIR"
```

### 3. Source inventory warning

Use Glob tool to count source files matching `**/*.{ts,js,py,go,rs,java,kt,cs,rb,cpp,c,swift}`.
If count < 5: warn "Fewer than 5 source files found - analysis may be sparse" but continue. An empty declared workspace is valid and must not hard-stop preflight.

### 4. Read thresholds from echelon-config.yml

```bash
COVERAGE_THRESHOLD=$(bash .specify/extensions/echelon/scripts/bash/echelon-config-get.sh re.workflow.coverage_threshold 2>/dev/null || echo "99")
RESOLUTION_THRESHOLD=$(bash .specify/extensions/echelon/scripts/bash/echelon-config-get.sh re.workflow.resolution_threshold 2>/dev/null || echo "99")
MAX_VALIDATE=$(bash .specify/extensions/echelon/scripts/bash/echelon-config-get.sh re.workflow.max_validate_iterations 2>/dev/null || echo "5")
MAX_VERIFY_EXPAND=$(bash .specify/extensions/echelon/scripts/bash/echelon-config-get.sh re.workflow.max_verify_expand_iterations 2>/dev/null || echo "5")
MAX_SOURCE_CYCLES=$(bash .specify/extensions/echelon/scripts/bash/echelon-config-get.sh re.workflow.max_source_cycles 2>/dev/null || echo "5")
MAX_DOMAIN_REPAIRS=$(bash .specify/extensions/echelon/scripts/bash/echelon-config-get.sh re.workflow.max_domain_repairs 2>/dev/null || echo "5")
MAX_SOURCE_REANALYSIS=$(bash .specify/extensions/echelon/scripts/bash/echelon-config-get.sh re.workflow.max_source_reanalysis 2>/dev/null || echo "5")
export COVERAGE_THRESHOLD RESOLUTION_THRESHOLD MAX_VALIDATE MAX_VERIFY_EXPAND MAX_SOURCE_CYCLES MAX_DOMAIN_REPAIRS MAX_SOURCE_REANALYSIS
```

### 5. Initialize RE `state.json`

If the file does not exist, create it:

```python
import json, sys, os
from pathlib import Path
output_dir = os.environ.get('OUTPUT_DIR', '.specify/echelon/re')
if output_dir == '.specify/echelon/re':
    current = Path('runs/.current')
    if current.exists():
        run_id = current.read_text().strip()
        if run_id and Path('runs', run_id).exists():
            output_dir = f'runs/{run_id}/re'  # rendered as runs/{run_id}/re in docs
Path(output_dir).mkdir(parents=True, exist_ok=True)
state_path = Path(output_dir) / 'state.json'
if not state_path.exists():
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    state = {
        'run_id': f're-{ts}', 'status': 'in_progress',
        'phase': 're-extract-0-preflight',
        'last_dispatch': {'phase_id': None, 'agent': None, 'post_dispatch_complete': False, 'dispatched_at': None},
        'mode': 'workspace', 'output_dir': output_dir,
        'domains': [], 'coverage_pct': 0,
        'coverage_threshold': int(os.environ.get('COVERAGE_THRESHOLD', 99)),
        'verify_expand_iterations': 0,
        'max_verify_expand_iterations': int(os.environ.get('MAX_VERIFY_EXPAND', 5)),
        're_convergence_schema_version': 1,
        're_source_budgets': {
            'max_source_cycles': int(os.environ.get('MAX_SOURCE_CYCLES', 5)),
            'max_domain_repairs': int(os.environ.get('MAX_DOMAIN_REPAIRS', 5)),
            'max_source_reanalysis': int(os.environ.get('MAX_SOURCE_REANALYSIS', 5)),
        },
        're_source_states': {},
        'artifacts': {'analysis_json': f'{output_dir}/analysis.json',
                      'analysis_manifest': f'{output_dir}/re-analysis-manifest.json',
                      'workspace_manifest': f'{output_dir}/workspace-manifest.json',
                      'source_index': f'{output_dir}/re-source-index.json',
                      'workspace_inputs': f'{output_dir}/re-workspace-inputs.json',
                      'cross_repo': f'{output_dir}/cross-repo.json',
                      'codegraph_analysis': f'{output_dir}/codegraph-analysis.json',
                      'codegraph_summary': f'{output_dir}/codegraph-summary.json',
                      'sources_root': f'{output_dir}/sources',
                      'workspace_root': f'{output_dir}/workspace',
                      'quality_root': f'{output_dir}/quality'},
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
