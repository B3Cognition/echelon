# Brownfield Config Reference (`re:` key)

All brownfield extraction (re-* commands) configuration lives under the `re:` top-level key in your project's `echelon-config.yml`.

## Key settings

### Analysis scope
- `re.analysis.include_patterns` — glob patterns to include (default: `["**/*"]`)
- `re.analysis.exclude_patterns` — globs to exclude (default: node_modules, dist, .git, vendor, etc.)
- `re.analysis.max_file_size_kb` — skip files larger than this (default: 500)

### Coverage thresholds
- `re.workflow.coverage_threshold` — minimum spec coverage before verify→expand loop exits (default: 80)
- `re.workflow.resolution_threshold` — minimum ambiguity resolution before validate loop exits (default: 80)
- `re.workflow.max_validate_iterations` — max validate iterations (default: 3)

### Output
- `re.output.directory` — where standalone analysis artifacts land (default: `.specify/echelon/re`). During an active `echelon spec run`, the default is redirected to `runs/<run-id>/re` so run-local artifacts stay with the run.
- `re.output.generate_spec` / `generate_plan` / `generate_tasks` — toggle artifact generation (all default: true)

### Sources
- `re.sources.git_history` — include git history in analysis (default: true)
- `re.sources.git_history_limit` — max commits to analyze (default: 100)
- `re.sources.ci_cd` / `deployment` / `integrations` — toggle additional extraction

### Depth
- `re.depth.level` — `metadata` | `signatures` | `logic` | `full` (default: `signatures`)
- `re.depth.max_lines_per_file` — max lines read per file (default: 500)
- `re.depth.context_management` — `progressive` | `hold_all` (default: `progressive`)

### Polyrepo
- `re.polyrepo.enabled` — `auto` | `true` | `false` (default: `auto`)
- `re.polyrepo.discovery` — `flat` (scan immediate subdirs, default)
- `re.polyrepo.exclude` / `include` — repo name filters

`re.polyrepo.*` controls source-root discovery inside the workspace. It does not decide whether the workspace root itself is implementation code; that comes from the workspace manifest. New reverse-engineering tooling should prefer `workspace-manifest.json` and use `repos-manifest.json` only as a compatibility fallback.

## Layer-2 overrides (GOLDDIGGER)

When echelon's GOLDDIGGER agent runs brownfield extraction, it writes a temporary layer-2 override to `.specify/extensions/echelon/local-config.yml` under the `re:` key. This file is automatically removed after extraction completes. Do not manually create or modify this file during a GOLDDIGGER run.

## Environment variable overrides

| Variable | Config key |
|----------|-----------|
| `ECHELON_CFG_RE_ANALYSIS_MAX_FILE_SIZE_KB` | `re.analysis.max_file_size_kb` |
| `ECHELON_CFG_RE_SOURCES_GIT_HISTORY_LIMIT` | `re.sources.git_history_limit` |
| `ECHELON_CFG_RE_OUTPUT_DIRECTORY` | `re.output.directory` |
