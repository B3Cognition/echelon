# Polyrepo Squad Orchestration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Update cognitive-squad's GOLDDIGGER, SCOUT, and COMMANDER to support polyrepo extraction with adaptive depth, direct artifact consumption (no brownfield-index normalization), and repo-aware Mode 2 requests.

**Architecture:** GOLDDIGGER becomes a thin orchestrator — sets up per-repo depth config and invokes reverse-eng once. SCOUT reads reverse-eng artifacts directly via paths in `state.json.golddigger_artifacts`. COMMANDER's context packs point agents to artifact paths. Mode 2 requests gain repo context.

**Tech Stack:** Markdown (AI agent prompts), YAML (config)

**Spec:** [2026-03-29-polyrepo-squad-orchestration-design.md](../specs/2026-03-29-polyrepo-squad-orchestration-design.md)

**Note:** All changes in this plan are to markdown prompt files and YAML config — not executable code. There are no unit tests to write. Verification is done via structural checks (grep for expected patterns) and a live integration test.

---

## File Structure

### Modified Files

| File | Responsibility | Change |
|------|---------------|--------|
| `agents/exploration/golddigger.md` | GOLDDIGGER agent instructions | Replace brownfield-index normalization with polyrepo orchestration, adaptive depth, artifact paths in state.json |
| `agents/exploration/scout.md` | SCOUT agent instructions | Replace brownfield-index.md consumption with direct reverse-eng artifact reading |
| `commands/cognitive-squad.run.md` | COMMANDER state machine | Update context pack assembly, Mode 2 request format, cache paths, GOLDDIGGER dispatch prompt |
| `config-template.yml` | Squad configuration template | Add `polyrepo_full_depth_threshold` under `discovery` section |

### Unchanged Files

| File | Reason |
|------|--------|
| `agents.yaml` | Agent registry — no new agents |
| `scripts/bash/detect-project.sh` | Already counts files recursively under target dir |
| `scripts/bash/pre-dispatch-gate.sh` | Agent-level checks, not repo-level |
| All other agent files | Consume SCOUT's output, not GOLDDIGGER's |

---

## Task 1: Config Template — Add Polyrepo Threshold

**Files:**
- Modify: `config-template.yml:209-217` (discovery section)

- [ ] **Step 1: Add `polyrepo_full_depth_threshold` to config-template.yml**

In `config-template.yml`, after the existing `discovery` section entries (after `min_reference_architectures`), add:

```yaml
  # Polyrepo: repos with fewer source files than this threshold
  # are auto-promoted to full depth during GOLDDIGGER Mode 1 survey.
  # This saves Mode 2 roundtrips for small repos that are cheap to analyze fully.
  # Set to 0 to disable auto-promotion (all repos get signatures depth).
  # [range: 0-200] [default: 50]
  polyrepo_full_depth_threshold: 50
```

- [ ] **Step 2: Verify the addition**

```bash
grep -n "polyrepo_full_depth_threshold" config-template.yml
```

Expected: One line showing the new config entry.

- [ ] **Step 3: Commit**

```bash
git add config-template.yml
git commit -m "feat: add polyrepo_full_depth_threshold to discovery config"
```

---

## Task 2: Rewrite GOLDDIGGER — Polyrepo Orchestration

**Files:**
- Modify: `agents/exploration/golddigger.md` (full rewrite of Mode 1 section)

This is the largest change. GOLDDIGGER's Mode 1 section is replaced with polyrepo-aware orchestration. Mode 2 gains repo context. The brownfield-index normalization step is removed entirely.

- [ ] **Step 1: Read the current golddigger.md**

Read the full file at `agents/exploration/golddigger.md` to understand the current structure before modifying.

- [ ] **Step 2: Update the Role section**

Replace the opening paragraphs (lines 1-13) with:

```markdown
# GOLDDIGGER Agent

## Role

**Layer:** Exploration

You are GOLDDIGGER — a brownfield extraction driver who has surveyed 100+ legacy codebases. You know where the buried treasure is and where the landmines are. You are dispatched before SCOUT when a brownfield codebase is detected and the `spec-kit-reverse-eng` extension is available. Your job is to drive the reverse-eng extraction pipeline with the right configuration and write artifact paths to `state.json` so SCOUT and downstream agents can read them directly.

You are dispatched as a subagent by COMMANDER. You will receive: the target codebase path and the mode to run (Mode 1, Mode 1 Polyrepo, or Mode 2 with a specific domain and optional repo).
```

- [ ] **Step 3: Update NEVER Rules**

Replace rule 1 with the new contract:

```markdown
## NEVER Rules

1. **NEVER produce `brownfield-index.md`** — write artifact paths to `state.json.golddigger_artifacts` instead. SCOUT reads reverse-eng artifacts directly.
2. **NEVER run Mode 2 for a domain that is already in `golddigger_completed_domains`** — check `state.json` first.
3. **NEVER omit `golddigger_status` from `state.json`** — write it on every run, including failures.
4. **NEVER modify `golddigger_requests` or `golddigger_completed_domains`** — those fields are COMMANDER's responsibility.
5. **NEVER skip the Skill tool invocation for reverse-eng extraction.** Manual code analysis is NOT a substitute. The Skill tool must be invoked and must return (success OR error) before you may proceed. The only valid path to `golddigger_status: "failed"` or `"partial"` is through a Skill tool invocation that returned an error.
6. **NEVER use `print()` in python3 scripts that read or write JSON files.** A stray `print()` corrupts `state.json` when output is captured or redirected.
7. **NEVER write config to `.specify/squad/golddigger-mode*.yml`.** Use the spec-kit 4-layer config system: write to `.specify/extensions/reverse-eng/local-config.yml` (layer 2). Remove the file after extraction completes.
```

- [ ] **Step 4: Update Configuration Profiles**

Replace the existing "Configuration Profiles" section with three profiles:

```markdown
## Configuration Profiles

Do NOT let agents or users pass arbitrary reverse-eng config. Use exactly these named profiles, written to `.specify/extensions/reverse-eng/local-config.yml` (spec-kit config layer 2 — overrides project config and extension defaults, gitignored).

**Config lifecycle:** Write `local-config.yml` → invoke extract → remove `local-config.yml`. This ensures the override is temporary and does not persist to subsequent runs.

### Mode 1 — Survey (single-repo)

```yaml
# Write to .specify/extensions/reverse-eng/local-config.yml
depth:
  level: signatures
workflow:
  coverage_threshold: 60
  resolution_threshold: 60
  max_validate_iterations: 1
output:
  generate_spec: false
  generate_plan: false
  generate_tasks: false
```

### Mode 1 — Survey (polyrepo with adaptive depth)

```yaml
# Write to .specify/extensions/reverse-eng/local-config.yml
# Default depth for large repos (above threshold)
depth:
  level: signatures
workflow:
  coverage_threshold: 60
  resolution_threshold: 60
  max_validate_iterations: 1
output:
  generate_spec: false
  generate_plan: false
  generate_tasks: false
# Per-repo overrides for small repos (below threshold)
# GOLDDIGGER builds this section from repos-manifest.json
polyrepo:
  repos:
    small-repo-name:
      depth:
        level: full
      workflow:
        coverage_threshold: 95
        resolution_threshold: 95
        max_validate_iterations: 3
```

### Mode 2 — Deep Dive

```yaml
# Write to .specify/extensions/reverse-eng/local-config.yml
depth:
  level: full
workflow:
  coverage_threshold: 95
  resolution_threshold: 95
  max_validate_iterations: 3
output:
  generate_spec: true
  generate_plan: false
  generate_tasks: false
```
```

- [ ] **Step 5: Replace Mode 1 section with polyrepo-aware flow**

Replace the entire "Mode 1 — Survey Run" section (Steps 1-4) with:

```markdown
## Mode 1 — Survey Run

### Step 1: Detect polyrepo mode

Read the repos manifest to determine if this is a polyrepo:

```bash
MANIFEST=".specify/reverse-eng/repos-manifest.json"
if [ -f "$MANIFEST" ]; then
    MODE=$(jq -r '.mode' "$MANIFEST")
else
    MODE="single"
fi
echo "Detected mode: $MODE"
```

If `MODE` is `polyrepo`, proceed to Step 1b (polyrepo config). If `single`, proceed to Step 2 (write standard Mode 1 config).

### Step 1b: Build polyrepo config with adaptive depth

Read `squad-config.yml` for the threshold:

```bash
THRESHOLD=$(grep 'polyrepo_full_depth_threshold' squad-config.yml 2>/dev/null | awk '{print $2}' || echo 50)
```

Read each repo's source file count from the manifest and build per-repo overrides for repos below the threshold:

```bash
# WARNING: Do NOT add print() statements — they corrupt state.json
python3 -c "
import json, yaml

with open('.specify/reverse-eng/repos-manifest.json') as f:
    manifest = json.load(f)

threshold = int('$THRESHOLD')
overrides = {}
notes = []

for repo in manifest.get('repos', []):
    name = repo['name']
    count = repo.get('source_file_count', 0)
    if count <= threshold:
        overrides[name] = {
            'depth': {'level': 'full'},
            'workflow': {
                'coverage_threshold': 95,
                'resolution_threshold': 95,
                'max_validate_iterations': 3
            }
        }
        notes.append(f'{name} auto-promoted to full depth ({count} files <= {threshold} threshold)')

config = {
    'depth': {'level': 'signatures'},
    'workflow': {
        'coverage_threshold': 60,
        'resolution_threshold': 60,
        'max_validate_iterations': 1
    },
    'output': {
        'generate_spec': False,
        'generate_plan': False,
        'generate_tasks': False
    }
}

if overrides:
    config['polyrepo'] = {'repos': overrides}

with open('.specify/extensions/reverse-eng/local-config.yml', 'w') as f:
    yaml.dump(config, f, default_flow_style=False)

# Output notes for state.json (one per line)
for note in notes:
    import sys
    sys.stderr.write(note + '\n')
"
```

Capture the notes from stderr for use in Step 4 (state.json write).

Proceed to Step 2b (invoke extraction).

### Step 2: Write Mode 1 config (single-repo only)

Write the standard survey profile to reverse-eng's local config:

```bash
cat > .specify/extensions/reverse-eng/local-config.yml << 'EOF'
depth:
  level: signatures
workflow:
  coverage_threshold: 60
  resolution_threshold: 60
  max_validate_iterations: 1
output:
  generate_spec: false
  generate_plan: false
  generate_tasks: false
EOF
```

### Step 2b: Invoke reverse-eng extraction

**MANDATORY — This step is NOT optional.** If you find yourself proceeding to Step 3 without having invoked the Skill tool, STOP and invoke it now.

Use the Skill tool to invoke the reverse-eng extract command:

```
/speckit.reverse-eng.extract
```

When the command prompt loads, provide the target path from COMMANDER's context pack. reverse-eng will automatically read the local-config.yml overrides. In polyrepo mode, reverse-eng reads `repos-manifest.json` and handles the per-repo extraction loop internally.

**ONLY after the Skill tool returns (success OR error) do you proceed.**

> **OI-003 note:** If you encounter an error in the verify step related to `file_inventory.files`, this is a known latent bug in `verify.md`. Note it in `golddigger_notes` and proceed with whatever artifacts were produced.

### Step 3: Write artifact paths and status to state.json

**No brownfield-index.md normalization.** Instead, write artifact paths directly to `state.json`.

Remove the config override first:

```bash
rm -f .specify/extensions/reverse-eng/local-config.yml
```

**Polyrepo mode — write to state.json:**

```bash
# WARNING: Do NOT add print() statements — they corrupt state.json
python3 -c "
import json

with open('.specify/squad/state.json', 'r') as f:
    s = json.load(f)

with open('.specify/reverse-eng/repos-manifest.json') as f:
    manifest = json.load(f)

per_repo = ['.specify/reverse-eng/' + r['name'] + '/' for r in manifest.get('repos', [])]

s['golddigger_status'] = 'complete'
s['golddigger_mode'] = 'polyrepo-survey'
s['golddigger_artifacts'] = {
    'manifest': '.specify/reverse-eng/repos-manifest.json',
    'cross_repo': '.specify/reverse-eng/cross-repo.json',
    'per_repo': per_repo
}
s['golddigger_notes'] = []  # Add adaptive depth notes captured from Step 1b

with open('.specify/squad/state.json', 'w') as f:
    json.dump(s, f, indent=2)
"
```

Add any adaptive depth notes from Step 1b to `golddigger_notes`.

**Single-repo mode — write to state.json:**

```bash
# WARNING: Do NOT add print() statements — they corrupt state.json
python3 -c "
import json

with open('.specify/squad/state.json', 'r') as f:
    s = json.load(f)

s['golddigger_status'] = 'complete'
s['golddigger_mode'] = 'survey'
s['golddigger_artifacts'] = {
    'analysis': '.specify/reverse-eng/analysis.json',
    'specs': 'specs/'
}
s['golddigger_notes'] = []

with open('.specify/squad/state.json', 'w') as f:
    json.dump(s, f, indent=2)
"
```

If the pipeline exited early or any step failed, write `"golddigger_status": "partial"` or `"golddigger_status": "failed"` with a note explaining what happened.
```

- [ ] **Step 6: Update Mode 2 section for repo context**

Replace the Mode 2 section with repo-aware version. Key changes:
- Step 1 (cache check): check for `"{repo}--{domain}"` format in `golddigger_completed_domains`
- Step 4 (cache path): use `.specify/squad/golddigger-cache/{repo}--{domain}.md` in polyrepo, `.specify/squad/golddigger-cache/{domain}.md` in single-repo
- Step 5 (status): mode stays `"deep-dive"`

Replace the Mode 2 section:

```markdown
## Mode 2 — Deep Dive (single domain)

You will receive the domain name and optionally a repo name from COMMANDER's context pack.

> **Note on deduplication:** COMMANDER checks `golddigger_completed_domains` before dispatching you (defense in depth). You also check it as a NEVER rule. Both checks are intentional.

### Step 1: Check cache

```bash
# Check if already completed (defensive check)
# WARNING: Do NOT add print() statements — they corrupt state.json
python3 -c "
import json
with open('.specify/squad/state.json', 'r') as f:
    s = json.load(f)
domains = s.get('golddigger_completed_domains', [])
print(json.dumps(domains))
"
```

Determine the cache key:
- If `repo` is provided (polyrepo): cache key is `"{repo}--{domain}"`
- If `repo` is null or absent (single-repo): cache key is `"{domain}"`

If the cache key is already in `golddigger_completed_domains`, output the cache path and stop:
```
GOLDDIGGER MODE 2 — CACHE HIT
Domain: <domain>
Repo: <repo or "N/A">
Cached at: .specify/squad/golddigger-cache/<cache-key>.md
```

### Step 2: Write Mode 2 config

```bash
cat > .specify/extensions/reverse-eng/local-config.yml << 'EOF'
depth:
  level: full
workflow:
  coverage_threshold: 95
  resolution_threshold: 95
  max_validate_iterations: 3
output:
  generate_spec: true
  generate_plan: false
  generate_tasks: false
EOF
```

### Step 3: Invoke reverse-eng for this domain

**MANDATORY — This step is NOT optional.**

```
/speckit.reverse-eng.extract
```

Scope the extraction to the specific domain. In polyrepo mode, provide the repo subdirectory path: `{target_path}/{repo}`.

### Step 4: Copy output to cache

Determine the cache path:
- If `repo` is provided: `.specify/squad/golddigger-cache/{repo}--{domain}.md`
- If `repo` is null: `.specify/squad/golddigger-cache/{domain}.md`

Copy the generated domain spec to the cache path.

### Step 4b: Clean up config override

```bash
rm -f .specify/extensions/reverse-eng/local-config.yml
```

### Step 5: Write completion status to state.json

```bash
# WARNING: Do NOT add print() statements — they corrupt state.json
python3 -c "
import json
with open('.specify/squad/state.json', 'r') as f:
    s = json.load(f)

s['golddigger_status'] = 'complete'
s['golddigger_mode'] = 'deep-dive'

with open('.specify/squad/state.json', 'w') as f:
    json.dump(s, f, indent=2)
"
```
```

- [ ] **Step 7: Update Completion Signal section**

Replace the Completion Signal section:

```markdown
## Completion Signal

**Mode 1 (single-repo):**
```
GOLDDIGGER SURVEY COMPLETE
Status: <complete|partial|failed>
Artifacts: .specify/reverse-eng/analysis.json
```

**Mode 1 (polyrepo):**
```
GOLDDIGGER POLYREPO SURVEY COMPLETE
Status: <complete|partial|failed>
Repos: <count>
Manifest: .specify/reverse-eng/repos-manifest.json
Cross-repo: .specify/reverse-eng/cross-repo.json
Auto-promoted to full depth: <list or "none">
```

**Mode 2:**
```
GOLDDIGGER DEEP DIVE COMPLETE
Domain: <domain>
Repo: <repo or "N/A">
Status: <complete|partial|failed>
Cached at: .specify/squad/golddigger-cache/<cache-key>.md
```
```

- [ ] **Step 8: Update Failure Handling section**

Update the failure fallback reference — SCOUT no longer checks for brownfield-index.md:

Replace:
```
SCOUT will detect the absent or partial `brownfield-index.md` and fall back to manual structural analysis.
```

With:
```
SCOUT will detect `golddigger_status: "failed"` in state.json and fall back to manual structural analysis. The run continues in degraded-brownfield mode.
```

- [ ] **Step 9: Verify and commit**

```bash
# Verify key patterns exist in the updated file
grep -c "brownfield-index" agents/exploration/golddigger.md  # Should be 0
grep -c "golddigger_artifacts" agents/exploration/golddigger.md  # Should be >= 2
grep -c "polyrepo" agents/exploration/golddigger.md  # Should be >= 3
grep -c "repos-manifest" agents/exploration/golddigger.md  # Should be >= 2
```

```bash
git add agents/exploration/golddigger.md
git commit -m "feat: rewrite GOLDDIGGER for polyrepo orchestration, drop brownfield-index"
```

---

## Task 3: Update SCOUT — Read Reverse-Eng Artifacts Directly

**Files:**
- Modify: `agents/exploration/scout.md` (Brownfield Mode, Step 1)

- [ ] **Step 1: Read the current scout.md**

Read the full file at `agents/exploration/scout.md`.

- [ ] **Step 2: Replace Step 1 (brownfield-index check) with artifact reading**

Replace the current "Step 1: Check for GOLDDIGGER brownfield context" section (lines 47-64) with:

```markdown
### Step 1: Check for GOLDDIGGER extraction artifacts

Read `state.json` to check if GOLDDIGGER produced artifacts:

```bash
# WARNING: Do NOT add print() statements — they corrupt state.json
python3 -c "
import json
with open('.specify/squad/state.json', 'r') as f:
    s = json.load(f)
status = s.get('golddigger_status', 'absent')
artifacts = s.get('golddigger_artifacts', {})
print(json.dumps({'status': status, 'artifacts': artifacts}))
"
```

**If `golddigger_status` is `complete` or `partial`:**

Read the artifacts directly — no intermediate normalization layer.

**Polyrepo mode** (if `golddigger_artifacts.manifest` exists):

1. Read `.specify/reverse-eng/repos-manifest.json` for repo list
2. Read `.specify/reverse-eng/cross-repo.json` for dependency links and shared tech
3. For each repo: read `.specify/reverse-eng/{repo}/analysis.json` for structure, dependencies, git history, hotspots
4. If domain specs exist (from auto-promoted full-depth repos): read `specs/NNN-re-{repo}-{domain}/spec.md`

Use the data to seed your output artifacts:
- `repos-manifest.json` → seeds **boundaries** (each repo is a top-level boundary)
- `cross-repo.json` → seeds **dependencies** between boundaries and **integration points**
- Per-repo `analysis.json` → seeds **glossary** (tech stack, entry points), **mental-model** (domain inventory, hotspots)
- Per-repo domain specs (if exist) → seeds **assumptions** and **unknowns** with evidence

**Single-repo mode** (if `golddigger_artifacts.analysis` exists):

1. Read `.specify/reverse-eng/analysis.json` for structure, dependencies, git history, hotspots
2. If domain specs exist: read `specs/NNN-re-{domain}/spec.md`

Use the data to seed your output artifacts:
- `analysis.json` → seeds **glossary**, **mental-model**, **boundaries**
- Domain specs (if exist) → seeds **assumptions** and **unknowns**

**If `golddigger_status` is `failed` or absent:** Proceed with manual analysis (Steps 2-4). Log in your reasoning journal: "GOLDDIGGER artifacts not available — proceeding with manual structural analysis."

Treat extraction artifacts as a validated head-start, not as a complete answer. Enrich, validate, and extend every section — do not copy blindly.
```

- [ ] **Step 3: Update Step 6 (Mode 2 request format) for repo context**

Replace the Mode 2 request python snippet (around line 117-134) with:

```markdown
### Step 6: Evaluate Domain Depth for Deep Dive Requests (brownfield only)

If GOLDDIGGER artifacts were present, evaluate whether any domain needs deeper analysis via GOLDDIGGER Mode 2.

For each domain, assess whether the survey-level data was sufficient:

- **Boundary ambiguity:** Are the domain's boundaries unclear from signatures alone?
- **Unresolvable entry points:** Could you not trace call graphs from signatures?
- **Hotspot complexity:** Is this domain a high-churn hotspot?
- **Integration opacity:** Are external integrations partially mapped?

If any domain needs deeper analysis, write a Mode 2 request to `state.json`:

```bash
# WARNING: Do NOT add print() statements — they corrupt state.json
python3 -c "
import json
with open('.specify/squad/state.json', 'r') as f:
    s = json.load(f)

s.setdefault('golddigger_requests', []).append({
    'domain': '<domain-name>',
    'repo': '<repo-name-or-null>',
    'requested_by': 'SCOUT',
    'reason': '<specific reason>'
})

with open('.specify/squad/state.json', 'w') as f:
    json.dump(s, f, indent=2)
"
```

In polyrepo mode, always include the `repo` field so COMMANDER can dispatch GOLDDIGGER to the correct repo subdirectory. In single-repo mode, set `repo` to `null`.

COMMANDER will process the queue after your dispatch completes. Deep-dive results will be available in `.specify/squad/golddigger-cache/{repo}--{domain}.md` (polyrepo) or `.specify/squad/golddigger-cache/{domain}.md` (single-repo).

**Do NOT request Mode 2 for every domain.** Only request it when survey-level data is genuinely insufficient for your outputs.
```

- [ ] **Step 4: Verify and commit**

```bash
# Verify key patterns
grep -c "brownfield-index" agents/exploration/scout.md  # Should be 0
grep -c "golddigger_artifacts" agents/exploration/scout.md  # Should be >= 2
grep -c "repos-manifest" agents/exploration/scout.md  # Should be >= 1
grep -c "'repo'" agents/exploration/scout.md  # Should be >= 1 (Mode 2 request)
```

```bash
git add agents/exploration/scout.md
git commit -m "feat: SCOUT reads reverse-eng artifacts directly, repo-aware Mode 2 requests"
```

---

## Task 4: Update COMMANDER — Context Packs, Mode 2 Format, Cache Paths

**Files:**
- Modify: `commands/cognitive-squad.run.md` (sections 1.8 and 2)

- [ ] **Step 1: Read relevant sections of cognitive-squad.run.md**

Read lines 485-530 (GOLDDIGGER dispatch and Mode 2 queue sections).

- [ ] **Step 2: Update GOLDDIGGER Mode 1 dispatch and status check (section 1.8)**

Replace the "GOLDDIGGER Mode 1 dispatch" subsection (lines 485-497) with:

```markdown
**GOLDDIGGER Mode 1 dispatch (brownfield path only):**

If `detected_mode` is `brownfield` AND `extension-capabilities.json` lists an extension with `id: "reverse-eng"` and `relevant: true`:

1. Dispatch GOLDDIGGER in Mode 1 (Survey) before DISCOVER:
   - Use the Agent tool
   - **prompt:** Read the file `agents/exploration/golddigger.md` for your complete instructions. You are the GOLDDIGGER agent. Run **Mode 1 (Survey)** for target path `{target_path}`. Your context: run_id is `{run_id}`, mode is brownfield.
2. Block until GOLDDIGGER completes.
3. Read `state.json.golddigger_status`:
   - `complete`: proceed — SCOUT will read artifact paths from `state.json.golddigger_artifacts`
   - `partial` or `failed`: log degraded-brownfield warning; proceed (SCOUT falls back to manual structural analysis)

If `reverse-eng` is not listed or `extensions` is empty: skip GOLDDIGGER, proceed directly to DISCOVER.
```

- [ ] **Step 3: Update Mode 2 Queue section for repo-aware requests**

Replace the "GOLDDIGGER Mode 2 Queue" subsection (lines 499-509) with:

```markdown
**GOLDDIGGER Mode 2 Queue (Phase 1 agents):**

After each Phase 1 agent (DISCOVER/SCOUT, SYNTHESIZER, WHY1/SAGE, CARTOGRAPHER, MODELER) completes, before dispatching the next agent:

1. Read `state.json.golddigger_requests` — if empty or absent, continue
2. For each pending request entry (format: `{domain, repo, requested_by, reason}`):
   a. Determine cache key:
      - If `repo` is non-null: `"{repo}--{domain}"`
      - If `repo` is null: `"{domain}"`
   b. Check `state.json.golddigger_completed_domains` — if the cache key is already listed, skip (cache hit; data is in `.specify/squad/golddigger-cache/{cache-key}.md`). Notify the requesting agent in its next context pack.
   c. Otherwise: dispatch GOLDDIGGER in Mode 2 (Deep Dive):
      - **prompt:** Read the file `agents/exploration/golddigger.md` for your complete instructions. You are the GOLDDIGGER agent. Run **Mode 2 (Deep Dive)** for domain `{domain}` in repo `{repo}` at target path `{target_path}`. If repo is null, target path is `{target_path}` (single-repo mode).
   d. After GOLDDIGGER completes: remove the entry from `state.json.golddigger_requests`, add the cache key to `state.json.golddigger_completed_domains`, include `.specify/squad/golddigger-cache/{cache-key}.md` in the requesting agent's next context pack.
3. Continue to next Phase 1 agent dispatch.

**Backward compatibility:** If a `golddigger_requests` entry is a plain string (old format), treat it as `{domain: string, repo: null, requested_by: "unknown"}`.
```

- [ ] **Step 4: Update Context Pack Assembly (section 2)**

In the "Context Pack Assembly" section (around line 519-526), add artifact paths:

After the existing context pack items, add:

```markdown
- If `state.json.golddigger_artifacts` exists: include artifact paths so the agent knows where to read brownfield data
  - Polyrepo: include `repos-manifest.json` path, `cross-repo.json` path, per-repo directory paths
  - Single-repo: include `analysis.json` path
- If any `golddigger_completed_domains` have new entries since last dispatch: include the corresponding cache file paths
```

- [ ] **Step 5: Update state.json initialization (section 1.3)**

In the state.json initialization template (around line 263-290), add the new field:

After `"golddigger_notes": null,` add:

```json
  "golddigger_artifacts": null,
```

- [ ] **Step 6: Verify and commit**

```bash
# Verify key patterns
grep -c "golddigger_artifacts" commands/cognitive-squad.run.md  # Should be >= 2
grep -c "repo.*null" commands/cognitive-squad.run.md  # Should be >= 1 (backward compat)
grep -c "cache.key" commands/cognitive-squad.run.md  # Should be >= 2
grep -c "repo}--{domain}" commands/cognitive-squad.run.md  # Should be >= 1
```

```bash
git add commands/cognitive-squad.run.md
git commit -m "feat: COMMANDER polyrepo context packs, repo-aware Mode 2 queue"
```

---

## Task 5: Verification — Structural Checks and Integration Readiness

**Files:**
- None (verification only)

- [ ] **Step 1: Verify brownfield-index.md is fully removed**

```bash
echo "=== brownfield-index references remaining ==="
grep -rn "brownfield-index" agents/ commands/ --include="*.md" | grep -v "docs/" || echo "CLEAN: no references"
```

Expected: `CLEAN: no references` — all mentions of `brownfield-index.md` should be gone from agent and command files.

- [ ] **Step 2: Verify golddigger_artifacts is consistently referenced**

```bash
echo "=== golddigger_artifacts references ==="
grep -rn "golddigger_artifacts" agents/ commands/ --include="*.md" | wc -l
```

Expected: >= 5 references across golddigger.md, scout.md, and cognitive-squad.run.md.

- [ ] **Step 3: Verify Mode 2 repo context is consistent**

```bash
echo "=== repo field in Mode 2 ==="
grep -n "'repo'" agents/exploration/golddigger.md agents/exploration/scout.md
grep -n '"repo"' commands/cognitive-squad.run.md
```

Expected: `repo` field appears in GOLDDIGGER (cache key), SCOUT (Mode 2 request), and COMMANDER (dispatch + cache key).

- [ ] **Step 4: Verify config entry exists**

```bash
grep -n "polyrepo_full_depth_threshold" config-template.yml
```

Expected: One entry with value 50.

- [ ] **Step 5: Review git log**

```bash
git log --oneline -5
```

Expected: 4 commits from Tasks 1-4, clean history.

- [ ] **Step 6: Create integration test checklist**

Create a file `docs/superpowers/plans/polyrepo-integration-test-checklist.md`:

```markdown
# Polyrepo Integration Test Checklist

Run `/speckit.squad.run` against your polyrepo (top-dir with cpp/, fet-frontend-libs/, video-player/).

## Pre-flight
- [ ] spec-kit initialized in top-dir (`specify init --here`)
- [ ] reverse-eng extension installed
- [ ] cognitive-squad extension installed
- [ ] System 1 changes deployed (polyrepo extraction in reverse-eng)

## During Squad Run — Verify
- [ ] GOLDDIGGER detects polyrepo mode (check state.json for `golddigger_mode: "polyrepo-survey"`)
- [ ] GOLDDIGGER writes `golddigger_artifacts` to state.json (not brownfield-index.md)
- [ ] Small repos auto-promoted to full depth (check `golddigger_notes`)
- [ ] Per-repo analysis.json files exist in `.specify/reverse-eng/{repo}/`
- [ ] cross-repo.json exists and has dependency links
- [ ] SCOUT reads artifact paths from state.json (check reasoning journal)
- [ ] SCOUT produces per-repo boundaries in boundaries.md
- [ ] Cross-repo dependencies appear in mental-model.md or boundaries.md
- [ ] No `brownfield-index.md` file is produced anywhere

## Mode 2 (if triggered)
- [ ] Mode 2 requests include `repo` field
- [ ] Cache path uses `{repo}--{domain}.md` format
- [ ] Requesting agent receives cache file in next context pack

## Regression
- [ ] Single-repo squad run still works (run against any single repo)
- [ ] GOLDDIGGER failure → SCOUT falls back to manual analysis
```

```bash
git add -f docs/superpowers/plans/polyrepo-integration-test-checklist.md
git commit -m "docs: add polyrepo integration test checklist"
```
