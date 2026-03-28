# Polyrepo Squad Orchestration — cognitive-squad (System 2 of 3)

**Date:** 2026-03-29
**Scope:** cognitive-squad only (System 2 — depends on System 1: spec-kit-reverse-eng polyrepo extraction)
**Approach:** Thin GOLDDIGGER orchestrator, no normalization layer, SCOUT reads reverse-eng artifacts directly

## Problem

cognitive-squad's GOLDDIGGER agent dispatches reverse-eng once for a single target path, normalizes output into a lossy `brownfield-index.md`, and SCOUT reads that summary. In a polyrepo layout (`top-dir/repo1/`, `top-dir/repo2/`, ...), this means:

- GOLDDIGGER runs one extraction that merges all repos together
- `brownfield-index.md` normalization discards repo boundaries, per-repo git history, and domain-level detail
- SCOUT has no awareness of which domains belong to which repos
- Mode 2 requests have no repo context — agents can't request deep dives on specific repo domains
- The normalization layer exists to decouple SCOUT from the brownfield tool, but reverse-eng is the only tool and will remain so

## Requirements

- GOLDDIGGER must orchestrate reverse-eng per-repo in polyrepo mode
- Small repos should be auto-promoted to full depth (adaptive, configurable threshold)
- SCOUT must read reverse-eng artifacts directly — no lossy normalization into `brownfield-index.md`
- Mode 2 requests must include repo context
- Full backward compatibility for single-repo runs
- All agents get full per-repo artifacts in context packs (no selective filtering)

## Design

### GOLDDIGGER Polyrepo Orchestration

GOLDDIGGER's Mode 1 becomes a polyrepo-aware orchestrator that runs reverse-eng per-repo with adaptive depth.

**Flow:**

1. COMMANDER dispatches GOLDDIGGER with `target_path` (the polyrepo top-dir)
2. GOLDDIGGER reads `.specify/reverse-eng/repos-manifest.json` (produced by System 1's `discover-repos.sh` via `reanalyze.md`)
3. If manifest doesn't exist or `mode: single` → current single-repo behavior (run `/speckit.reverse-eng.extract` once), but skip `brownfield-index.md` normalization — write artifact paths to `state.json` instead
4. If `mode: polyrepo`:
   - Read each repo's `source_file_count` from manifest
   - **Small repo threshold** (configurable via `squad-config.yml`, default: 50 source files)
   - Write `local-config.yml` with per-repo depth overrides using the `polyrepo.repos` config section from System 1. For repos below the threshold, add an override entry with `depth: full` and `thresholds: 95%`. For repos above, use default `depth: signatures` and `thresholds: 60%`.
   - Invoke `/speckit.reverse-eng.extract` **once** — reverse-eng reads `repos-manifest.json` and handles the per-repo loop internally (System 1's polyrepo mode). The per-repo overrides in `local-config.yml` control depth per repo.
5. After extraction completes: verify artifacts exist, write status and artifact paths to `state.json`, remove `local-config.yml`

**Important:** GOLDDIGGER does NOT loop over repos itself. It sets up config and invokes reverse-eng once. reverse-eng's polyrepo mode (System 1) handles the per-repo extraction loop internally.

**No `brownfield-index.md` produced.** GOLDDIGGER writes to `state.json`:

```json
{
  "golddigger_status": "complete",
  "golddigger_mode": "polyrepo-survey",
  "golddigger_artifacts": {
    "manifest": ".specify/reverse-eng/repos-manifest.json",
    "cross_repo": ".specify/reverse-eng/cross-repo.json",
    "per_repo": [".specify/reverse-eng/repo-a/", ".specify/reverse-eng/repo-b/"]
  },
  "golddigger_notes": ["repo-c auto-promoted to full depth (12 files < 50 threshold)"]
}
```

**Single-repo `state.json` (also updated — drops brownfield-index):**

```json
{
  "golddigger_status": "complete",
  "golddigger_mode": "survey",
  "golddigger_artifacts": {
    "analysis": ".specify/reverse-eng/analysis.json",
    "specs": "specs/"
  },
  "golddigger_notes": []
}
```

**Adaptive depth logic:**

GOLDDIGGER builds a single `local-config.yml` before invoking reverse-eng:

```
# Read manifest and threshold
threshold = squad-config.yml discovery.polyrepo_full_depth_threshold (default: 50)

# Build per-repo overrides
polyrepo_repos_overrides = {}
for each repo in repos-manifest.json:
  if repo.source_file_count <= threshold:
    polyrepo_repos_overrides[repo.name] = {depth: {level: full}, workflow: {coverage_threshold: 95, resolution_threshold: 95}}
    note: "{repo.name} auto-promoted to full depth ({repo.source_file_count} files < {threshold} threshold)"

# Write single local-config.yml with overrides
write local-config.yml:
  depth:
    level: signatures  # default for large repos
  workflow:
    coverage_threshold: 60
    resolution_threshold: 60
    max_validate_iterations: 1
  output:
    generate_spec: false
  polyrepo:
    repos: polyrepo_repos_overrides  # per-repo depth overrides

# Invoke reverse-eng ONCE — it handles the per-repo loop
invoke /speckit.reverse-eng.extract

# Clean up
remove local-config.yml
```

**Note:** This requires System 1's reverse-eng to support per-repo depth overrides from the `polyrepo.repos` config section during its internal per-repo loop. This is a minor enhancement to `run-analysis.sh` — when processing each repo, check if `polyrepo.repos.{repo-name}.depth` exists and use it instead of the top-level `depth` setting.

### SCOUT Changes — Read Reverse-Eng Artifacts Directly

SCOUT stops looking for `brownfield-index.md` and reads reverse-eng artifacts directly.

**New SCOUT brownfield flow:**

1. Read `state.json.golddigger_artifacts` to get artifact paths
2. If `golddigger_status` is `complete` or `partial`:
   - If `golddigger_artifacts.manifest` exists (polyrepo):
     - Read `repos-manifest.json` for repo list
     - Read `cross-repo.json` for dependency links and shared tech
     - For each repo: read `{repo}/analysis.json` for structure, dependencies, git history, hotspots
     - If domain specs exist (`specs/NNN-re-{repo}-{domain}/spec.md`): read them for pre-mapped domains
   - If `golddigger_artifacts.analysis` exists (single-repo):
     - Read `analysis.json` for structure, dependencies, git history, hotspots
     - If domain specs exist (`specs/NNN-re-{domain}/spec.md`): read them
3. If `golddigger_status` is `failed` or absent: fall back to manual structural analysis (unchanged)

**What SCOUT does with the data:**

- `repos-manifest.json` → seeds **boundaries** (each repo is a top-level boundary)
- `cross-repo.json` → seeds **dependencies** between boundaries and **integration points**
- Per-repo `analysis.json` → seeds **glossary** (tech stack, entry points), **mental-model** (domain inventory, hotspots)
- Per-repo domain specs (if exist from full-depth repos) → seeds **assumptions** and **unknowns** with evidence

**Fallback is identical to today** — if GOLDDIGGER didn't run or failed, SCOUT does its own analysis.

### COMMANDER Orchestration Changes

**Initialization (Step 1.8 — GOLDDIGGER dispatch):**

Unchanged — COMMANDER dispatches GOLDDIGGER once with `target_path`. GOLDDIGGER internally handles polyrepo loop. COMMANDER doesn't need to know about individual repos.

**Context packs for Phase 1 agents:**

COMMANDER includes artifact paths from `state.json.golddigger_artifacts`. Each Phase 1 agent gets:
- `repos-manifest.json` path (if polyrepo)
- `cross-repo.json` path (if polyrepo)
- Per-repo artifact directory paths
- Any completed Mode 2 cache paths

Agents read the files themselves — COMMANDER points, agents read.

**Mode 2 request format change:**

Current format (string):
```json
{"golddigger_requests": ["core-engine", "api-layer"]}
```

New format (object with repo context):
```json
{
  "golddigger_requests": [
    {"domain": "core-engine", "repo": "repo-b", "requested_by": "CARTOGRAPHER"},
    {"domain": "api-layer", "repo": "repo-a", "requested_by": "SCOUT"}
  ]
}
```

For single-repo mode: `"repo": null` — backward compatible, GOLDDIGGER treats it as current behavior.

**Mode 2 cache paths:**

- Polyrepo: `.specify/squad/golddigger-cache/{repo}--{domain}.md` (double-dash separator to avoid ambiguity with hyphenated names)
- Single-repo: `.specify/squad/golddigger-cache/{domain}.md` (unchanged)

**Mode 2 dispatch prompt update:**

```
Read the file agents/exploration/golddigger.md for your complete instructions.
You are the GOLDDIGGER agent. Run Mode 2 (Deep Dive) for domain "{domain}"
in repo "{repo}" at target path "{target_path}/{repo}".
```

### State Schema Changes

**New fields (additive — no existing fields removed):**

```json
{
  "golddigger_artifacts": {
    "manifest": ".specify/reverse-eng/repos-manifest.json",
    "cross_repo": ".specify/reverse-eng/cross-repo.json",
    "per_repo": [".specify/reverse-eng/repo-a/", ".specify/reverse-eng/repo-b/"]
  }
}
```

**Existing fields with extended semantics:**

| Field | Single-repo | Polyrepo |
|-------|-------------|----------|
| `golddigger_mode` | `"survey"` or `"deep-dive"` | `"polyrepo-survey"` or `"deep-dive"` |
| `golddigger_requests[]` | String domain names (backward compat) | Objects: `{domain, repo, requested_by}` |
| `golddigger_completed_domains[]` | `"{domain}"` | `"{repo}--{domain}"` |

### Config Changes

Added to `squad-config.yml` under existing `discovery` section:

```yaml
discovery:
  # existing fields...
  polyrepo_full_depth_threshold: 50  # source files — repos below this get full depth in Mode 1
```

Added to `config-template.yml` with documentation:

```yaml
discovery:
  # Polyrepo: repos with fewer source files than this threshold
  # are auto-promoted to full depth during GOLDDIGGER Mode 1 survey.
  # This saves Mode 2 roundtrips for small repos that are cheap to analyze fully.
  # Set to 0 to disable auto-promotion (all repos get signatures depth).
  polyrepo_full_depth_threshold: 50
```

## Backward Compatibility

| Scenario | Behavior |
|----------|----------|
| Single-repo, no manifest | Identical to today except no `brownfield-index.md` — artifacts written to `state.json` |
| Single-repo, manifest says `single` | Same as above |
| Polyrepo, manifest says `polyrepo` | New flow — per-repo extraction, adaptive depth |
| GOLDDIGGER fails | Same — SCOUT falls back to manual analysis |
| No reverse-eng extension | Same — GOLDDIGGER is skipped entirely |
| Old-format Mode 2 requests (strings) | GOLDDIGGER treats string entries as `{domain: str, repo: null}` — single-repo behavior |

**Breaking change:** `brownfield-index.md` is no longer produced. SCOUT must be updated simultaneously. Any external tooling reading `brownfield-index.md` will break. This is acceptable — `brownfield-index.md` was an internal contract, not a user-facing artifact.

## Files Changed Summary

| Component | Change Type | Description |
|-----------|------------|-------------|
| `agents/exploration/golddigger.md` | **Modified** | Polyrepo orchestration, adaptive depth, artifact paths in state.json, no brownfield-index |
| `agents/exploration/scout.md` | **Modified** | Read reverse-eng artifacts directly from state.json paths |
| `commands/cognitive-squad.run.md` | **Modified** | Context pack assembly with artifact paths, Mode 2 request format, cache path convention |
| `config-template.yml` | **Modified** | Add `polyrepo_full_depth_threshold` under `discovery` |

**Unchanged:**
- `agents.yaml` — agent registry
- All other agents (SYNTHESIZER, CARTOGRAPHER, SAGE, etc.) — consume SCOUT's output
- `scripts/bash/detect-project.sh` — already works for polyrepo (counts all files under target)
- `scripts/bash/pre-dispatch-gate.sh`, `post-execution-audit.sh` — unchanged
- RADAR monitoring — agent-level, not repo-level

## Testing Strategy

Since cognitive-squad changes are primarily AI agent prompts (markdown), testing is:

1. **Bash script tests:** `detect-project.sh` already handles polyrepo — verify with test fixtures
2. **Schema validation:** Validate `state.json` against expected schema after GOLDDIGGER completes
3. **Integration test:** Run `/speckit.squad.run` against the actual polyrepo (cpp/fet-frontend-libs/video-player) and verify:
   - GOLDDIGGER discovers all repos
   - Small repos get auto-promoted to full depth
   - SCOUT produces per-repo boundaries in its output
   - Mode 2 requests include repo context
   - Cross-repo dependencies appear in SCOUT's mental-model

## Future Work (Out of Scope)

- **System 3: spec-kit polyrepo extension/preset** — packaging and distribution
- **Selective context filtering** — COMMANDER sends only relevant repos to agents (if context overflow becomes a real problem)
- **Nested repo discovery** — `discovery: recursive` mode
- **RADAR repo-level monitoring** — per-repo progress tracking in the dashboard
