# Brownfield Extension Integration: PROSPECTOR + GOLDDIGGER

**Date:** 2026-03-22
**Status:** Approved
**Scope:** cognitive-squad + spec-kit-reverse-eng integration

---

## 1. Problem Statement

cognitive-squad claims brownfield support via `spec-kit-reverse-eng`, but the wiring is structurally broken in three ways:

**C-001 — Mechanism mismatch:** SCOUT's brownfield mode runs `which reverse-eng` looking for an OS binary. `spec-kit-reverse-eng` is a spec-kit extension providing slash-commands only. No binary exists. SCOUT always falls back to manual analysis.

**C-003 — Format mismatch:** reverse-eng domain specs contain implementation details by design (source paths, function names, legacy tech). SAGE's quality gates explicitly reject implementation details in specs. Feeding reverse-eng output to CARTOGRAPHER/SAGE would trigger quality violations.

**C-004 — Cardinality mismatch:** reverse-eng produces N domain specs per project. cognitive-squad expects a single project-level artifact flow from SCOUT.

**Missing layer:** No mechanism exists for agents to discover what spec-kit extensions are installed and how to invoke them. Agents look for OS binaries; extensions are AI-prompt packages. These two worlds have never been bridged.

---

## 2. Design Goals

- Agents can discover and use spec-kit extensions without knowing implementation details (binary vs slash-command)
- SCOUT's output format is stable regardless of whether brownfield context came from reverse-eng, a future tool, or manual analysis
- Context window pressure is managed — large codebases (10+ domains) do not dump full domain specs into SCOUT's context upfront
- The spec-kit ecosystem advantage is preserved — no reimplementing extraction logic inside cognitive-squad
- One named evolution path is captured for future generalization

---

## 3. New Components

### 3.1 PROSPECTOR (SURVEY)

**Layer:** Control (init phase, before all others)

PROSPECTOR belongs in the Control layer — not Exploration — because it produces routing data for COMMANDER (which extensions to activate, which agents to dispatch) rather than domain knowledge artifacts. It is the only Control-layer agent that writes a file artifact, but its output informs orchestration decisions, not domain understanding.

**Expected `agents.yaml` layer totals after implementation:** Control: 6, Exploration: 6 (SCOUT, SYNTHESIZER, SAGE, CARTOGRAPHER, MODELER + GOLDDIGGER).

**Dispatched by:** COMMANDER, always, as the first agent of every run
**Responsibility:** Discover installed spec-kit extensions, reason about relevance to the current run, write capability manifest.

**What it does:**
1. Scans known spec-kit extension locations for `extension.yml` files. Starting hypothesis for scan paths: `~/.specify/extensions/` (user-global) and `.specify/extensions/` (project-local). OI-001 tracks confirmation of these paths.
2. For each found extension: reads ID, version, available commands, required spec-kit version
3. Reasons about which extensions are relevant (brownfield/greenfield signal, target path, task type)
4. Writes `.specify/squad/extension-capabilities.json`

**Output format — extensions found:**
```json
{
  "generated_at": "<iso-timestamp>",
  "extensions": [
    {
      "id": "reverse-eng",
      "version": "1.1.0",
      "commands": ["speckit.reverse-eng.analyze", "speckit.reverse-eng.extract", "..."],
      "invocation": "skill",
      "relevant": true,
      "reason": "brownfield codebase detected at target path"
    }
  ]
}
```

**Output format — no extensions found (valid state):**
```json
{
  "generated_at": "<iso-timestamp>",
  "extensions": []
}
```

An empty `extensions` array is a valid, expected output when no spec-kit extensions are installed. COMMANDER treats an absent or empty `extensions` array identically: skip GOLDDIGGER dispatch, proceed to SCOUT directly.

**Available tools:** Read, Glob, Bash, WebFetch (for version checks)

COMMANDER reads `extension-capabilities.json` immediately after PROSPECTOR completes and includes a summary in every subsequent agent's context pack.

**PROSPECTOR failure mode:** If PROSPECTOR crashes, times out, or writes malformed JSON, COMMANDER treats the result identically to an empty-extensions response: skip GOLDDIGGER dispatch, proceed to SCOUT directly. COMMANDER logs `prospector_status: failed` as a warning in `state.json`. The run continues in degraded mode — brownfield analysis falls back to SCOUT's manual structural analysis. This mirrors the GOLDDIGGER degraded-run pattern and is the safest default: a PROSPECTOR failure should never block a run.

---

### 3.2 GOLDDIGGER

**Layer:** Exploration (brownfield path only, dispatched before SCOUT)
**Dispatched by:** COMMANDER when: brownfield codebase detected AND `extension-capabilities.json` lists `reverse-eng` as available and relevant
**Responsibility:** Drive reverse-eng with the right configuration for each mode; normalize all output into a stable format that SCOUT and downstream agents consume.

SCOUT never knows or cares whether brownfield context came from reverse-eng, a future tool, or any other source. `brownfield-index.md` is the stable contract.

#### Mode 1 — Survey (always runs first)

Drives the full reverse-eng Phase 1 pipeline with lightweight configuration:

| Setting | Value |
|---|---|
| `level` | `signatures` |
| `coverage_threshold` | `60` |
| `resolution_threshold` | `60` |
| `max_validate_iterations` | `1` |
| `generate_spec` | `false` |
| `generate_plan` | `false` |
| `generate_tasks` | `false` |

Fast. Gives structural understanding across all domains without deep logic extraction.

**Output:** GOLDDIGGER normalizes the result into:
- `.specify/squad/brownfield-index.md` — compact structured summary (~1-2KB) containing:
  - Domain inventory (names, file count per domain)
  - Tech stack summary (languages, key frameworks, top dependencies)
  - Entry points list
  - Top 10 hotspots (high-churn files by git history)
  - External integration signals (CI/CD, infra, external service configs)
- `.specify/squad/golddigger-cache/survey.md` — raw survey artifacts for reference

#### Mode 2 — Deep Dive (on demand, per domain)

Triggered when any Phase 1 agent queues a domain expansion request in `state.json` under `golddigger_requests`:

```json
{
  "golddigger_requests": [
    { "domain": "auth", "requester": "SCOUT", "reason": "boundary ambiguity — cannot infer external auth provider topology from index alone" }
  ]
}
```

COMMANDER detects queue entries and re-dispatches GOLDDIGGER with the specific domain scope and strict configuration:

| Setting | Value |
|---|---|
| `level` | `full` |
| `coverage_threshold` | `95` |
| `resolution_threshold` | `95` |
| `max_validate_iterations` | `3` |
| `generate_spec` | `true` |
| `generate_plan` | `false` |
| `generate_tasks` | `false` |

**Output:** `.specify/squad/golddigger-cache/{domain}.md`

**Queue lifecycle (critical):** After GOLDDIGGER Mode 2 completes for a domain, COMMANDER must:
1. Remove that domain's entry from `golddigger_requests` in `state.json`
2. Add the domain to `golddigger_completed_domains` list in `state.json`
3. Notify the requesting agent in its next context pack

Cache deduplication check: before dispatching GOLDDIGGER Mode 2 for a requested domain, COMMANDER checks `golddigger_completed_domains`. If the domain is already listed, read from `.specify/squad/golddigger-cache/{domain}.md` and skip dispatch entirely.

**GOLDDIGGER status reporting:** GOLDDIGGER writes a `golddigger_status` field to `state.json` on every run:
- `complete` — Mode 1 or Mode 2 ran to successful completion
- `partial` — pipeline exited early; `brownfield-index.md` may be incomplete
- `failed` — pipeline did not produce usable output

COMMANDER logs `partial` or `failed` status as a degraded-brownfield run warning. SCOUT proceeds with whatever `brownfield-index.md` is present (or falls back to manual analysis if absent).

**Available tools:** Skill (for reverse-eng invocation), Read, Bash, Glob

---

## 4. Modified Components

### 4.1 SCOUT (DISCOVER) — Minor update

SCOUT's brownfield detection block is updated:

- **Remove:** `which reverse-eng || npx reverse-eng --version` check
- **Add:** Check for `.specify/squad/brownfield-index.md` at the start of brownfield analysis
- **If present:** Read `brownfield-index.md` as enriched starting point. Use it to seed glossary entries, mental model topology, boundary signals, and initial unknowns. Validate and enrich rather than derive from scratch.
- **If absent:** Proceed with existing manual structural analysis (unchanged fallback)

SCOUT still produces all standard output artifacts (glossary, mental-model, boundaries, assumptions, unknowns) — the source of its head-start data is invisible to downstream agents.

### 4.2 COMMANDER (MANAGER) — Dispatch additions

Three additions to dispatch logic:

1. **PROSPECTOR at init:** Add PROSPECTOR as the first dispatch in every run, before mode detection. Block on completion before proceeding.

2. **GOLDDIGGER in brownfield path:** After brownfield mode is confirmed, check `extension-capabilities.json`. If `reverse-eng` is available and relevant, dispatch GOLDDIGGER (Mode 1) before SCOUT. Block SCOUT dispatch on GOLDDIGGER completion.

3. **GOLDDIGGER Mode 2 queue:** After each Phase 1 agent completes, check `state.json` for pending `golddigger_requests`. If any exist, for each entry: check `golddigger_completed_domains` first (cache hit → read from cache, skip dispatch); otherwise dispatch GOLDDIGGER (Mode 2). After completion, remove the entry from `golddigger_requests`, add to `golddigger_completed_domains`, and notify the requesting agent in its next context pack.

### 4.3 `extension.yml` — Fix misleading binary claim

Remove the implication that `spec-kit-reverse-eng` is invoked as a CLI binary. Document that integration occurs via PROSPECTOR (discovery) and GOLDDIGGER (invocation via Skill tool).

### 4.4 `agents.yaml` — Register new agents

Add PROSPECTOR and GOLDDIGGER to the central registry with layer, phase, dispatch conditions, and available tools.

---

## 5. Source Fix: python → python3

All RADAR invocations in the command files use `python` which fails on macOS where only `python3` is in PATH. This affects:

- `commands/cognitive-squad.run.md` — 5 invocations (already applied in current diff)
- `commands/cognitive-squad.build.md` — 2 invocations (already applied in current diff)
- `radar/emitter.py` — no subprocess calls to python; no change needed
- `radar/server.py` — no subprocess calls to python; no change needed

---

## 6. Dispatch Sequence (full picture)

```
Run start (always)
  └─ PROSPECTOR (SURVEY)
       output: .specify/squad/extension-capabilities.json

Mode detection (detect-project.sh — unchanged)

Brownfield path (source files found AND reverse-eng available):
  └─ GOLDDIGGER (Mode 1 — Survey)
       config: signatures / 60% thresholds / no specs
       output: .specify/squad/brownfield-index.md
               .specify/squad/golddigger-cache/survey.md
  └─ SCOUT (DISCOVER)
       reads: brownfield-index.md as head start
       output: glossary.md, mental-model.md, boundaries.md,
               assumptions.md, unknowns.md
       may queue: golddigger_requests in state.json
  └─ [GOLDDIGGER (Mode 2) — per domain, on demand]
       config: full / 95% thresholds / generate_spec: true
       output: .specify/squad/golddigger-cache/{domain}.md
               (cached; COMMANDER notifies requesting agent)
  └─ SYNTHESIZER → SAGE (WHY1) → CARTOGRAPHER → ...
       [any Phase 1 agent may queue GOLDDIGGER Mode 2 requests]

Greenfield path (or reverse-eng unavailable):
  └─ SCOUT — runs normally, no brownfield-index.md
  └─ SYNTHESIZER → SAGE (WHY1) → CARTOGRAPHER → ... (unchanged)
```

---

## 7. What Is Not Changing

- SCOUT's output artifact format (glossary, mental-model, boundaries, assumptions, unknowns)
- All downstream agents (SYNTHESIZER, SAGE, CARTOGRAPHER, ARCHITECT, etc.)
- Phase 2, 3, 4 pipeline
- reverse-eng extension itself (no changes to spec-kit-reverse-eng)
- SAGE quality gates (implementation details still rejected — now correctly never reach SAGE)

---

## 8. Evolution Path

### EVOLUTION-001 — Generic Extension Registry

**Trigger:** A second spec-kit extension needs agent integration.

PROSPECTOR currently handles discovery for a known extension set. The next evolution is a formal registry — a schema for extension invocation contracts, input/output types, agent authorization rules, and composition patterns. This allows any agent to discover and invoke any spec-kit extension without bespoke wiring. GOLDDIGGER becomes one instance of a general extension-agent pattern.

**What changes:** PROSPECTOR gains a registry schema; a generic `extension-agent` base pattern is defined; GOLDDIGGER is refactored as an instance of it.

**What stays the same:** `brownfield-index.md` contract, SCOUT behavior, all downstream agents.

---

## 9. Open Items

| ID | Item | Owner |
|---|---|---|
| OI-001 | Confirm scan paths for PROSPECTOR. Starting hypothesis: `~/.specify/extensions/` (user-global) and `.specify/extensions/` (project-local). Verify against actual spec-kit installation behavior. | PROSPECTOR implementation |
| OI-002 | Expose `golddigger` config block in `squad-config.yml` for user-tunable thresholds (post-MVP). | Future |
| OI-003 | Latent bug in reverse-eng: `verify.md` reads `analysis["file_inventory"]["files"]` but extract produces only `file_counts`. Confirm whether Mode 1 (signatures level) hits this code path. If yes, flag to spec-kit-reverse-eng maintainer. | GOLDDIGGER implementation |

---

## 10. Files to Create / Modify

| Action | Path |
|---|---|
| Create | `agents/control/prospector.md` |
| Create | `agents/exploration/golddigger.md` |
| Modify | `agents/exploration/scout.md` — remove binary check, add brownfield-index.md consumption |
| Modify | `agents/control/commander.md` — PROSPECTOR init dispatch + GOLDDIGGER brownfield dispatch + Mode 2 queue handling |
| Modify | `agents.yaml` — register PROSPECTOR and GOLDDIGGER |
| Modify | `extension.yml` — fix binary invocation claim |
| Modify | `commands/cognitive-squad.run.md` — (1) python → python3 (5 occurrences); (2) Section 15 error table: replace the `spec-kit-reverse-eng` row from "DISCOVER falls back to greenfield mode..." to: `\| spec-kit-reverse-eng \| PROSPECTOR fails or reverse-eng not installed \| COMMANDER treats as empty-extensions; SCOUT proceeds without brownfield-index.md using manual structural analysis. Run flagged as degraded-brownfield in state.json. \|`; (3) line ~619 advisory text: replace "Option A: If `spec-kit-reverse-eng` is available, suggest running it first to derive principles from existing code patterns" with "Option A: If GOLDDIGGER ran and brownfield-index.md is present, derive principles from the domain inventory and hotspot analysis already captured there." |
| Modify | `commands/cognitive-squad.build.md` — python → python3 (2 occurrences) |
