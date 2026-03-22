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
**Dispatched by:** COMMANDER, always, as the first agent of every run
**Responsibility:** Discover installed spec-kit extensions, reason about relevance to the current run, write capability manifest.

**What it does:**
1. Scans known spec-kit extension locations for `extension.yml` files
2. For each found extension: reads ID, version, available commands, required spec-kit version
3. Reasons about which extensions are relevant (brownfield/greenfield signal, target path, task type)
4. Writes `.specify/squad/extension-capabilities.json`

**Output format:**
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

**Available tools:** Read, Glob, Bash, WebFetch (for version checks)

COMMANDER reads `extension-capabilities.json` immediately after PROSPECTOR completes and includes a summary in every subsequent agent's context pack.

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

Results are cached. If a second agent requests the same domain, COMMANDER reads from cache without re-dispatching GOLDDIGGER.

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

Two additions to dispatch logic:

1. **PROSPECTOR at init:** Add PROSPECTOR as the first dispatch in every run, before mode detection. Block on completion before proceeding.

2. **GOLDDIGGER in brownfield path:** After brownfield mode is confirmed, check `extension-capabilities.json`. If `reverse-eng` is available and relevant, dispatch GOLDDIGGER (Mode 1) before SCOUT. Block SCOUT dispatch on GOLDDIGGER completion.

3. **GOLDDIGGER Mode 2 queue:** After each Phase 1 agent completes, check `state.json` for pending `golddigger_requests`. If any exist, dispatch GOLDDIGGER (Mode 2) for each queued domain before the next agent runs. Notify the requesting agent in its next context pack.

### 4.3 `extension.yml` — Fix misleading binary claim

Remove the implication that `spec-kit-reverse-eng` is invoked as a CLI binary. Document that integration occurs via PROSPECTOR (discovery) and GOLDDIGGER (invocation via Skill tool).

### 4.4 `agents.yaml` — Register new agents

Add PROSPECTOR and GOLDDIGGER to the central registry with layer, phase, dispatch conditions, and available tools.

---

## 5. Source Fix: python → python3

All RADAR invocations across the codebase use `python` which fails on macOS where only `python3` is in PATH. This affects:

- `commands/squad.run.md` — 5 invocations
- `commands/squad.build.md` — 2 invocations
- `radar/emitter.py` — any internal subprocess calls
- `radar/server.py` — any internal subprocess calls

All occurrences updated to `python3`.

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
| OI-001 | Where exactly are spec-kit extensions installed? Confirm scan paths for PROSPECTOR. | PROSPECTOR implementation |
| OI-002 | Expose `golddigger` config block in `squad-config.yml` for user-tunable thresholds (post-MVP). | Future |
| OI-003 | Latent bug in reverse-eng: `verify.md` reads `analysis["file_inventory"]["files"]` but extract produces only `file_counts`. Confirm whether Mode 1 (signatures level) hits this code path. If yes, flag to spec-kit-reverse-eng maintainer. | GOLDDIGGER implementation |

---

## 10. Files to Create / Modify

| Action | Path |
|---|---|
| Create | `agents/exploration/prospector.md` |
| Create | `agents/exploration/golddigger.md` |
| Modify | `agents/exploration/scout.md` — remove binary check, add brownfield-index.md consumption |
| Modify | `agents/control/commander.md` — PROSPECTOR init dispatch + GOLDDIGGER brownfield dispatch + Mode 2 queue handling |
| Modify | `agents.yaml` — register PROSPECTOR and GOLDDIGGER |
| Modify | `extension.yml` — fix binary invocation claim |
| Modify | `commands/squad.run.md` — python → python3 |
| Modify | `commands/squad.build.md` — python → python3 |
| Modify | `radar/emitter.py` — python → python3 (if applicable) |
| Modify | `radar/server.py` — python → python3 (if applicable) |
