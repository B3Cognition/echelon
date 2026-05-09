# echelon.codegen + echelon.codegenlight Workflow Externalization — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Thin `echelon.codegen.md` (650 lines) and `echelon.codegenlight.md` (630 lines) down to ~55-line wrappers by externalizing their pipeline phases to `workflow/phases/codegen-*.md` and `workflow/phases/codegenlight-*.md` files.

**Architecture:** Unlike `echelon.build.md` (COMMANDER-driven), codegen/codegenlight have their own ORCHESTRATOR role with SOAR-specific architectural invariants. Neither command references `commander.md` or `workflow/definition.yaml` — so **no changes to `definition.yaml`**. The thin wrappers keep invariants + invocation parsing inline (these are short, global, and SOAR-specific). Pipeline phases go to `workflow/phases/` files. Phases 2–6 (DECOMPOSE through TEST) are identical between the two commands and use **shared** files (`codegen-2-*.md` through `codegen-6-*.md`); phases that diverge (0, 1, 7, resume, error-handling) get per-command files.

**Tech Stack:** Markdown only. No application code, no YAML schema changes.

---

## Differences between codegen and codegenlight

| Section | `echelon.codegen.md` | `echelon.codegenlight.md` |
|---------|---------------------|--------------------------|
| Phase A preamble | ✅ Present (A.1–A.7: echelon feature validation, strategy registration, lessons) | ❌ Absent |
| Invocation forms | Simple: `001-feature-name` \| `--resume` | Rich: spec-glob \| brownfield target-path \| greenfield intent \| `--resume` \| `--benchmark` |
| Phase 0 Pre-Flight | WING from CLI arg; `HARNESS_STATE_FILE` set directly | WING from `echelon-config.yml`; harness env loaded from `.codegen-harness-env` |
| Phase 1 RE | Simple `codegen run` only | Step 1.1 (MemPalace) + Step 1.2 (brownfield GOLDDIGGER / greenfield research / stop-and-ask) |
| Phase 6b SECURITY | ✅ Present (security scan + license gate) | ❌ Absent |
| Phase 7 Terminal Summary | No `Mode` field | Includes `Mode` field |
| Resume Mode | Inline `write_state` redefinition | Loads `.codegen-harness-env` before redefining `write_state` |
| Error handling | Strict (SOAR failure = HARD STOP, impasse = halt) | Lenient (SOAR fallback to Model B; MemPalace unavailable = warn + continue) |
| SOAR Integration reference | ❌ Absent | ✅ Present at end |
| Phases 2–6 (DECOMPOSE → TEST) | **Identical** | **Identical** |

---

## File Map

### New files — codegen-specific
| Path | Responsibility |
|------|---------------|
| `workflow/phases/codegen-A-preamble.md` | echelon.codegen.md §Phase A (A.1–A.7) |
| `workflow/phases/codegen-0-preflight.md` | echelon.codegen.md §Phase 0 (0.1–0.5) |
| `workflow/phases/codegen-1-re.md` | echelon.codegen.md §Phase 1 (simple RE) |
| `workflow/phases/codegen-6b-security.md` | echelon.codegen.md §Phase 6b |
| `workflow/phases/codegen-7-deliver.md` | echelon.codegen.md §Phase 7 + Terminal Summary + Harness Integration |
| `workflow/phases/codegen-resume.md` | echelon.codegen.md §Resume Mode + Error Handling |

### New files — shared (codegen and codegenlight both reference these)
| Path | Responsibility |
|------|---------------|
| `workflow/phases/codegen-2-decompose.md` | §Phase 2 DECOMPOSE — identical in both |
| `workflow/phases/codegen-3-implement.md` | §Phase 3 IMPLEMENT loop — identical in both |
| `workflow/phases/codegen-4-gate.md` | §Phase 4 GATE — identical in both |
| `workflow/phases/codegen-5-impasse.md` | §Phase 5 Conflict Impasse — identical in both |
| `workflow/phases/codegen-6-test.md` | §Phase 6 TEST — identical in both |

### New files — codegenlight-specific
| Path | Responsibility |
|------|---------------|
| `workflow/phases/codegenlight-0-preflight.md` | echelon.codegenlight.md §Phase 0 (0.1–0.5) |
| `workflow/phases/codegenlight-1-re.md` | echelon.codegenlight.md §Phase 1 (RE + brownfield/greenfield) |
| `workflow/phases/codegenlight-7-deliver.md` | echelon.codegenlight.md §Phase 7 + Terminal Summary (with Mode field) + SOAR Integration Points |
| `workflow/phases/codegenlight-resume.md` | echelon.codegenlight.md §RESUME Mode + Error Handling |

### Modified files
| Path | Change |
|------|--------|
| `extension/commands/echelon.codegen.md` | Replace with ~55-line thin wrapper |
| `extension/commands/echelon.codegenlight.md` | Replace with ~55-line thin wrapper |

**Total: 17 new phase files + 2 modified command files. No changes to `workflow/definition.yaml`.**

---

## Phase file header format

Every phase file starts with this 4-line header:

```
# Phase: <phase-id>
# Source: <source-file> §<section> — <section name>
# [Shared: used by both echelon.codegen and echelon.codegenlight]   ← only for shared files
# Read by: ORCHESTRATOR before executing <phase>
```

---

## Thin wrapper content

### `extension/commands/echelon.codegen.md` (exact replacement content)

```markdown
---
name: speckit.echelon.codegen
description: "SOAR-powered build pipeline for echelon — Phase A validation, MemPalace mining, strategy registration, then RE → DECOMPOSE → IMPLEMENT → GATE → TEST → DELIVER"
tools: Bash, Read, Write, Edit, Glob, Grep, Agent
---

## Role

You are ORCHESTRATOR executing the SOAR-powered codegen pipeline. Follow the
architectural invariants below exactly — they cannot be overridden by any phase,
advisory, or commercial pressure.

---

## User Input

$ARGUMENTS

---

## Architectural Invariants — Read Before Proceeding

These invariants are constitutionally mandated and CANNOT be overridden by any
phase, LLM advisory, or commercial pressure:

- **INV-001:** `chunk never` MUST be the first directive in every `.soar` config file. SOAR chunking is disabled in all production deployments.
- **INV-002:** Quality constraints MUST be enforced exclusively via SOAR CQ-ISC prohibit preferences. No LLM advisory output, guardrail, or IMPLEMENTER-level logic may substitute.
- **INV-003:** IMPLEMENTER outputs inject `best` preferences ONLY. IMPLEMENTER does NOT inject prohibit, require, or worst preferences.
- **INV-004:** Every SOAR phase transition MUST produce an EPMEM entry. EPMEM recording cannot be disabled.
- **INV-005:** Every CQ-ISC production rule MUST have `(build ^current-phase <phase>)` as its FIRST LHS condition.
- **INV-006:** SOAR owns the phase transition decision. IMPLEMENTER advises. IMPLEMENTER does NOT self-advance the pipeline.
- **INV-008:** Conflict impasse = correct behaviour, NOT a failure. Impasse triggers human escalation, not autonomous resolution.
- **INV-010:** Delivery is BLOCKED until all Tier 1 (unit) tests pass via Bash tool execution.

---

## Invocation Forms

```
speckit.echelon.codegen 001-feature-name    # run pipeline on echelon feature
speckit.echelon.codegen --resume            # resume interrupted pipeline
```

---

## Phase Execution

Before executing each phase, read the corresponding spec file in full.

On `--resume`: read `workflow/phases/codegen-resume.md` and jump to `current_phase` — skip all phases before it.

Otherwise execute in order:
1. `workflow/phases/codegen-A-preamble.md` — preamble, artifact validation, strategy registration, lessons
2. `workflow/phases/codegen-0-preflight.md` — WING derivation, MemPalace mining, env check, state init, SOAR bridge
3. `workflow/phases/codegen-1-re.md` — Phase 1: RE requirements lookup
4. `workflow/phases/codegen-2-decompose.md` — Phase 2: DECOMPOSE task decomposition
5. `workflow/phases/codegen-3-implement.md` — Phase 3: IMPLEMENT dispatch loop (repeat until task_queue.pending empty)
6. `workflow/phases/codegen-4-gate.md` — Phase 4: GATE CQ-ISC verification
7. `workflow/phases/codegen-5-impasse.md` — Phase 5: Conflict Impasse (fires on impasse only, not sequentially)
8. `workflow/phases/codegen-6-test.md` — Phase 6: TEST Tier 1 gate
9. `workflow/phases/codegen-6b-security.md` — Phase 6b: SECURITY scan + license gate
10. `workflow/phases/codegen-7-deliver.md` — Phase 7: DELIVER + terminal summary + harness integration

On any error condition: consult `workflow/phases/codegen-resume.md` §Error Handling.
```

### `extension/commands/echelon.codegenlight.md` (exact replacement content)

```markdown
---
name: speckit.echelon.codegenlight
description: SOAR-powered software development agent — brownfield RE + greenfield build with inviolable quality gates (CQ-ISC prohibit preferences via SOAR 9.6.4)
tools: Bash, Read, Write, Edit, Glob, Grep, Agent
---

# /codegen — SOAR-Powered Software Development Agent

## Role

You are ORCHESTRATOR executing the lightweight SOAR codegen pipeline for
brownfield RE and greenfield builds with inviolable quality gates.

---

## User Input

$ARGUMENTS

---

## Architectural Invariants — Read Before Proceeding

These invariants are constitutionally mandated and CANNOT be overridden by any
phase, LLM advisory, or commercial pressure:

- **INV-001:** `chunk never` MUST be the first directive in every `.soar` config file. SOAR chunking is disabled in all production deployments. ISS-007 (Second-Order Chunking Contamination) is Grade A CONFIRMED SEVERE.
- **INV-002:** Quality constraints MUST be enforced exclusively via SOAR CQ-ISC prohibit preferences. No LLM advisory output, guardrail, or IMPLEMENTER-level logic may substitute for prohibit preferences.
- **INV-003:** IMPLEMENTER outputs inject `best` preferences ONLY. IMPLEMENTER does NOT inject prohibit, require, or worst preferences.
- **INV-004:** Every SOAR phase transition MUST produce an EPMEM entry. EPMEM recording cannot be disabled.
- **INV-005:** Every CQ-ISC production rule MUST have `(build ^current-phase <phase>)` as its FIRST LHS condition.
- **INV-006:** SOAR owns the phase transition decision. IMPLEMENTER advises. IMPLEMENTER does NOT self-advance the pipeline.
- **INV-008:** Conflict impasse = correct behaviour, NOT a failure. Impasse triggers human escalation, not autonomous resolution.
- **INV-010:** Delivery is BLOCKED until all Tier 1 (unit) tests pass via Bash tool execution.

---

## Invocation Forms

Parse `$ARGUMENTS` to determine mode:

```
/codegen <spec-glob> <intent>      # spec-driven: mine specs → RE lookup → build
/codegen <target-path> <intent>    # brownfield: RE existing codebase, then build
/codegen <intent>                  # greenfield: domain research, then build
/codegen --resume                  # resume interrupted pipeline from state.json
/codegen --benchmark               # run E2E benchmark vs LLM-only baseline
```

**Parsing rules (in order):**
1. If `$ARGUMENTS` starts with `--resume`: enter RESUME mode.
2. If `$ARGUMENTS` starts with `--benchmark`: enter BENCHMARK mode.
3. If the first token contains `*` or ends with `.md`/`.yaml`/`.yml` and matches files on disk: **spec-driven mode**.
4. If the first token is a filesystem path (`test -e <token>`): **brownfield mode**.
5. Otherwise: **greenfield mode**.

---

## Phase Execution

Before executing each phase, read the corresponding spec file in full.

On `--resume`: read `workflow/phases/codegenlight-resume.md` and jump to `current_phase`.

Otherwise execute in order:
1. `workflow/phases/codegenlight-0-preflight.md` — WING from config, spec detection/mining, env check, state init, SOAR bridge
2. `workflow/phases/codegenlight-1-re.md` — Phase 1: RE lookup + brownfield GOLDDIGGER / greenfield research
3. `workflow/phases/codegen-2-decompose.md` — Phase 2: DECOMPOSE (shared)
4. `workflow/phases/codegen-3-implement.md` — Phase 3: IMPLEMENT dispatch loop (shared, repeat until task_queue.pending empty)
5. `workflow/phases/codegen-4-gate.md` — Phase 4: GATE CQ-ISC verification (shared)
6. `workflow/phases/codegen-5-impasse.md` — Phase 5: Conflict Impasse (shared, fires on impasse only)
7. `workflow/phases/codegen-6-test.md` — Phase 6: TEST Tier 1 gate (shared)
8. `workflow/phases/codegenlight-7-deliver.md` — Phase 7: DELIVER + terminal summary (with Mode field) + SOAR integration reference

On any error condition: consult `workflow/phases/codegenlight-resume.md` §Error Handling.
```

---

## Task 1: Create codegen-A-preamble.md and codegen-0-preflight.md

**Files:**
- Create: `workflow/phases/codegen-A-preamble.md`
- Create: `workflow/phases/codegen-0-preflight.md`

Source: `extension/commands/echelon.codegen.md`

- [ ] **Step 1: Create codegen-A-preamble.md**

Read `extension/commands/echelon.codegen.md`. Extract everything from `## Phase A: Echelon Preamble` through the end of `### A.7 Load build lessons` (through the `fi` closing the SPA base path block). Copy verbatim.

File content:
```
# Phase: codegen-A-preamble
# Source: echelon.codegen.md §Phase A — Echelon Preamble
# Read by: ORCHESTRATOR before starting codegen pipeline (skip entirely on --resume)

---

[## Phase A: Echelon Preamble — full verbatim content: A.1 through A.7]
```

- [ ] **Step 2: Create codegen-0-preflight.md**

Extract `## Phase 0: Pre-Flight` through end of section `### 0.5 SOAR bridge initialization` (including the `[CODEGEN] SOAR Model A active` print line). Copy verbatim.

File content:
```
# Phase: codegen-0-preflight
# Source: echelon.codegen.md §Phase 0 — Pre-Flight Checks
# Read by: ORCHESTRATOR before Phase 1 RE

---

[## Phase 0: Pre-Flight — full verbatim content: 0.1 through 0.5]
```

- [ ] **Step 3: Verify section boundaries**

Confirm `codegen-A-preamble.md` ends with the `fi` that closes the SPA base path git commit block (the last line of §A.7), and does NOT include Phase 0 content.

Confirm `codegen-0-preflight.md` ends with `Print: [CODEGEN] SOAR Model A active. If RuntimeError appears, halt and print install hint.` and does NOT include Phase 1 content.

- [ ] **Step 4: Commit**

```bash
cd /Users/michalbachorik/work/evolution/echelon
git add workflow/phases/codegen-A-preamble.md workflow/phases/codegen-0-preflight.md
git commit -m "feat: add codegen-A-preamble and codegen-0-preflight phase spec files"
```

---

## Task 2: Create codegen-1-re.md

**Files:**
- Create: `workflow/phases/codegen-1-re.md`

Source: `extension/commands/echelon.codegen.md` §Phase 1

- [ ] **Step 1: Create the file**

Extract `## Phase 1: RE — Requirements Lookup` through the `write_state "codegen_decompose"` call and `[CODEGEN] Phase RE — COMPLETE ✓` print line. Stop before `## Phase 2`. Copy verbatim.

```
# Phase: codegen-1-re
# Source: echelon.codegen.md §Phase 1 — RE Requirements Lookup
# Read by: ORCHESTRATOR before Phase 1 RE execution

---

[## Phase 1: RE — Requirements Lookup — full verbatim content]
```

- [ ] **Step 2: Verify content**

Confirm these are present:
- `[CODEGEN] Phase RE — Starting...` print line
- `codegen run --intent` bash command
- `write_state "codegen_decompose" "building" 0 null null` state checkpoint
- `[CODEGEN] Phase RE — COMPLETE ✓` print line

- [ ] **Step 3: Commit**

```bash
git add workflow/phases/codegen-1-re.md
git commit -m "feat: add codegen-1-re phase spec file"
```

---

## Task 3: Create shared phases 2 and 3 (DECOMPOSE and IMPLEMENT)

**Files:**
- Create: `workflow/phases/codegen-2-decompose.md`
- Create: `workflow/phases/codegen-3-implement.md`

Source: both come from `extension/commands/echelon.codegen.md` §Phase 2 and §Phase 3. These files are shared — codegenlight's phases 2 and 3 are identical.

- [ ] **Step 1: Create codegen-2-decompose.md**

Extract `## Phase 2: DECOMPOSE — Task Decomposition` through `[CODEGEN] Phase DECOMPOSE — COMPLETE ✓ (<N> tasks queued)`. Stop before `## Phase 3`. Copy verbatim.

```
# Phase: codegen-2-decompose
# Source: echelon.codegen.md §Phase 2 — DECOMPOSE Task Decomposition
# Shared: used by both echelon.codegen and echelon.codegenlight
# Read by: ORCHESTRATOR before Phase 2 DECOMPOSE execution

---

[## Phase 2: DECOMPOSE — full verbatim content]
```

- [ ] **Step 2: Create codegen-3-implement.md**

Extract `## Phase 3: IMPLEMENT — speckit-echelon-implementer (IMPLEMENTER) Dispatch Loop` through `[CODEGEN] Phase IMPLEMENT — COMPLETE ✓ (<done> done, <blocked> blocked)`. Stop before `## Phase 4`. Copy verbatim.

```
# Phase: codegen-3-implement
# Source: echelon.codegen.md §Phase 3 — IMPLEMENT Dispatch Loop
# Shared: used by both echelon.codegen and echelon.codegenlight
# Read by: ORCHESTRATOR before each IMPLEMENT loop iteration

---

[## Phase 3: IMPLEMENT — full verbatim content including 3.1, 3.2, 3.3, 3.4]
```

- [ ] **Step 3: Verify content**

`codegen-2-decompose.md` must contain:
- The Agent tool call block (DECOMPOSE prompt)
- `TOTAL_TASKS=$(jq` line
- `write_state "codegen_implement"` checkpoint

`codegen-3-implement.md` must contain:
- Subsections 3.1 (SOAR dispatches task), 3.2 (IMPLEMENTER agent block), 3.3 (static analysis bash), 3.4 (gate evaluation — exit 0/1/2 handling)
- The ESCALATE `write_state` block with `"escalated"` status
- `[CODEGEN] Phase IMPLEMENT — COMPLETE ✓` print line

- [ ] **Step 4: Commit**

```bash
git add workflow/phases/codegen-2-decompose.md workflow/phases/codegen-3-implement.md
git commit -m "feat: add codegen-2-decompose and codegen-3-implement shared phase spec files"
```

---

## Task 4: Create shared phases 4 and 5 (GATE and IMPASSE)

**Files:**
- Create: `workflow/phases/codegen-4-gate.md`
- Create: `workflow/phases/codegen-5-impasse.md`

Source: `extension/commands/echelon.codegen.md` §Phase 4 and §Phase 5. Shared files.

- [ ] **Step 1: Create codegen-4-gate.md**

Extract `## Phase 4: GATE — CQ-ISC Verification Pass` through `[CODEGEN] Phase GATE — COMPLETE ✓ (<violation_count> violations blocked)`. Stop before `## Phase 5`. Copy verbatim.

```
# Phase: codegen-4-gate
# Source: echelon.codegen.md §Phase 4 — GATE CQ-ISC Verification
# Shared: used by both echelon.codegen and echelon.codegenlight
# Read by: ORCHESTRATOR before Phase 4 GATE execution

---

[## Phase 4: GATE — full verbatim content]
```

- [ ] **Step 2: Create codegen-5-impasse.md**

Extract `## Phase 5: Conflict Impasse — Human Escalation` (the full section). Stop before `## Phase 6`. Copy verbatim.

```
# Phase: codegen-5-impasse
# Source: echelon.codegen.md §Phase 5 — Conflict Impasse Human Escalation
# Shared: used by both echelon.codegen and echelon.codegenlight
# Read by: ORCHESTRATOR when SOAR detects a conflict impasse (INV-008)

---

[## Phase 5: Conflict Impasse — full verbatim content]
```

- [ ] **Step 3: Verify content**

`codegen-4-gate.md` must contain:
- `codegen gate --phase GATE` bash command
- Violation print format `[CODEGEN GATE] CQ-ISC violation: <id>`
- Ψ ≥ 0.70 condition for ADVANCE
- `write_state "codegen_test"` checkpoint

`codegen-5-impasse.md` must contain:
- `codegen-impasse.md` write instruction
- EPMEM record: `^source soar ^operator ESCALATE ^resolution pending`
- "Halt. Wait for human response." instruction

- [ ] **Step 4: Commit**

```bash
git add workflow/phases/codegen-4-gate.md workflow/phases/codegen-5-impasse.md
git commit -m "feat: add codegen-4-gate and codegen-5-impasse shared phase spec files"
```

---

## Task 5: Create shared Phase 6 (TEST) and codegen-only Phase 6b (SECURITY)

**Files:**
- Create: `workflow/phases/codegen-6-test.md` (shared)
- Create: `workflow/phases/codegen-6b-security.md` (codegen only)

Source: `extension/commands/echelon.codegen.md` §Phase 6 and §Phase 6b.

- [ ] **Step 1: Create codegen-6-test.md**

Extract `## Phase 6: TEST — Tier 1 Gate` through `[CODEGEN] Phase TEST — COMPLETE ✓ (Tier 1 gate PASSED)`. Stop before `## Phase 6b`. Copy verbatim.

```
# Phase: codegen-6-test
# Source: echelon.codegen.md §Phase 6 — TEST Tier 1 Gate
# Shared: used by both echelon.codegen and echelon.codegenlight
# Read by: ORCHESTRATOR before Phase 6 TEST execution

---

[## Phase 6: TEST — full verbatim content]
```

- [ ] **Step 2: Create codegen-6b-security.md**

Extract `## Phase 6b: SECURITY — Security Scan and License Gate` through `[CODEGEN] Phase SECURITY — COMPLETE ✓ (security gate PASSED)`. Stop before `## Phase 7`. Copy verbatim.

```
# Phase: codegen-6b-security
# Source: echelon.codegen.md §Phase 6b — SECURITY Scan and License Gate
# Read by: ORCHESTRATOR before Phase 6b SECURITY execution (echelon.codegen only)

---

[## Phase 6b: SECURITY — full verbatim content]
```

- [ ] **Step 3: Verify content**

`codegen-6-test.md` must contain:
- All 4 test runner bash blocks (pytest, vitest, go test, mvn)
- `write_state "codegen_deliver"` checkpoint
- `[CODEGEN] Phase TEST — COMPLETE ✓` print line

`codegen-6b-security.md` must contain:
- Security scan table (5 ecosystems: Node.js, Python, Go, Rust, Ruby)
- License check table (5 ecosystems)
- `security_gate: "pass"` / `"fail"` / `"license_fail"` outcomes
- HALT + escalate rule for failures
- `write_state "codegen_deliver"` checkpoint

- [ ] **Step 4: Commit**

```bash
git add workflow/phases/codegen-6-test.md workflow/phases/codegen-6b-security.md
git commit -m "feat: add codegen-6-test (shared) and codegen-6b-security phase spec files"
```

---

## Task 6: Create codegen-7-deliver.md and codegen-resume.md

**Files:**
- Create: `workflow/phases/codegen-7-deliver.md`
- Create: `workflow/phases/codegen-resume.md`

Source: `extension/commands/echelon.codegen.md` §Phase 7, §Terminal Summary, §Resume Mode, §Error Handling, §Harness Integration.

- [ ] **Step 1: Create codegen-7-deliver.md**

Extract `## Phase 7: DELIVER` through `## Harness Integration: Report Build Status` including the harness bash block at the end of the file. Stop before `## Resume Mode`. Copy verbatim.

Sections to include:
- `## Phase 7: DELIVER`
- `## Terminal Summary`
- `## Harness Integration: Report Build Status`

```
# Phase: codegen-7-deliver
# Source: echelon.codegen.md §Phase 7 + Terminal Summary + Harness Integration
# Read by: ORCHESTRATOR after TEST (and SECURITY) gates pass

---

[## Phase 7: DELIVER — full verbatim content]
[## Terminal Summary — full verbatim content]
[## Harness Integration: Report Build Status — full verbatim content]
```

- [ ] **Step 2: Create codegen-resume.md**

Extract `## Resume Mode` and `## Error Handling` sections. Copy verbatim.

```
# Phase: codegen-resume
# Source: echelon.codegen.md §Resume Mode + §Error Handling
# Read by: ORCHESTRATOR when invoked with --resume, or on any error condition

---

[## Resume Mode — full verbatim content]

---

[## Error Handling — full verbatim content]
```

- [ ] **Step 3: Verify content**

`codegen-7-deliver.md` must contain:
- `codegen gate --phase DELIVER` bash command
- Git operations user-approval block (`Approve? (yes/no):`)
- `rm -f .codegen-active` sentinel removal
- `write_state "done" "build_done"` final state write
- Terminal Summary ASCII box (the `╔══` box)
- `HARNESS_BUILD_STATUS_FILE` bash block with done + impasse cases

`codegen-resume.md` must contain:
- `codegen-state.json` existence check
- `RESUME_PHASE`, `RESUME_COMPLETED`, `TOTAL_TASKS` variable derivations
- `write_state` redefinition for resume context
- `[CODEGEN RESUME]` display block
- Error Handling table (7 rows: Missing Phase A artifact through Filesystem write)

- [ ] **Step 4: Commit**

```bash
git add workflow/phases/codegen-7-deliver.md workflow/phases/codegen-resume.md
git commit -m "feat: add codegen-7-deliver and codegen-resume phase spec files"
```

---

## Task 7: Create codegenlight-0-preflight.md

**Files:**
- Create: `workflow/phases/codegenlight-0-preflight.md`

Source: `extension/commands/echelon.codegenlight.md` §Phase 0

- [ ] **Step 1: Create the file**

Extract `## Phase 0: Pre-Flight Checks` through the end of `### 0.5 — SOAR bridge initialization` (the print line `[CODEGEN] SOAR Model A active`). Stop before `## Phase 1`. Copy verbatim.

```
# Phase: codegenlight-0-preflight
# Source: echelon.codegenlight.md §Phase 0 — Pre-Flight Checks
# Read by: ORCHESTRATOR before Phase 1 RE

---

[## Phase 0: Pre-Flight Checks — full verbatim content including 0.1 through 0.5]
```

- [ ] **Step 2: Verify content**

Must contain:
- `### 0.1 — Parse arguments and derive WING` with `python3 -c "import sys, yaml"` block reading from `echelon-config.yml`
- `### 0.2 — Spec detection and mining` with both explicit-glob and auto-discover bash blocks + mining loop
- `### 0.3 — Build environment verification` with 4-stack detection (python/typescript/go/java)
- `### 0.4 — Initialize pipeline state` with `PIPELINE_ID=$(uuidgen)`
- `### 0.4.1 — Initialize harness-compatible state` with `.codegen-harness-env` source + `write_state` function that checks `HARNESS_STATE_FILE` before writing
- `### 0.5 — SOAR bridge initialization` with `CODEGEN_REQUIRE_MODEL_A=1` and Model A check

- [ ] **Step 3: Commit**

```bash
git add workflow/phases/codegenlight-0-preflight.md
git commit -m "feat: add codegenlight-0-preflight phase spec file"
```

---

## Task 8: Create codegenlight-1-re.md

**Files:**
- Create: `workflow/phases/codegenlight-1-re.md`

Source: `extension/commands/echelon.codegenlight.md` §Phase 1

- [ ] **Step 1: Create the file**

Extract `## Phase 1: RE — Requirements Lookup + Domain Research` through `[CODEGEN] Phase RE — COMPLETE ✓`. Stop before `## Phase 2`. Copy verbatim.

```
# Phase: codegenlight-1-re
# Source: echelon.codegenlight.md §Phase 1 — RE Requirements Lookup + Domain Research
# Read by: ORCHESTRATOR before Phase 1 RE execution

---

[## Phase 1: RE — Requirements Lookup + Domain Research — full verbatim content]
```

- [ ] **Step 2: Verify content**

Must contain:
- `### Step 1.1 — MemPalace requirements retrieval` with `codegen run --intent` bash command
- `### Step 1.2 — Additional RE (if brownfield target provided)` with:
  - GOLDDIGGER Agent block for brownfield
  - "skip domain research" rule for spec-driven
  - Greenfield Agent block for domain research
  - "STOP and ask user" rule when no acceptance criteria
- `write_state "codegen_decompose"` checkpoint
- `[CODEGEN] Phase RE — COMPLETE ✓` print line

- [ ] **Step 3: Commit**

```bash
git add workflow/phases/codegenlight-1-re.md
git commit -m "feat: add codegenlight-1-re phase spec file"
```

---

## Task 9: Create codegenlight-7-deliver.md and codegenlight-resume.md

**Files:**
- Create: `workflow/phases/codegenlight-7-deliver.md`
- Create: `workflow/phases/codegenlight-resume.md`

Source: `extension/commands/echelon.codegenlight.md` §Phase 7, §Terminal Summary, §RESUME Mode, §Error Handling, §SOAR Integration Points.

- [ ] **Step 1: Create codegenlight-7-deliver.md**

Extract `## Phase 7: DELIVER — Final Delivery Package` through the Terminal Summary section. Also include `## SOAR Integration Points` (the bash reference block at the end of the file — this is codegenlight-specific). Copy verbatim.

Sections to include in this order:
- `## Phase 7: DELIVER — Final Delivery Package`
- `## Terminal Summary (FR-CMD-003)` (the version with Mode field)
- `## SOAR Integration Points`

```
# Phase: codegenlight-7-deliver
# Source: echelon.codegenlight.md §Phase 7 + Terminal Summary + SOAR Integration Points
# Read by: ORCHESTRATOR after TEST gate passes

---

[## Phase 7: DELIVER — Final Delivery Package — full verbatim content]
[## Terminal Summary (FR-CMD-003) — full verbatim content including Mode field]
[## SOAR Integration Points — full verbatim content]
```

- [ ] **Step 2: Create codegenlight-resume.md**

Extract `## RESUME Mode` and `## Error Handling` sections. Copy verbatim.

```
# Phase: codegenlight-resume
# Source: echelon.codegenlight.md §RESUME Mode + §Error Handling
# Read by: ORCHESTRATOR when invoked with --resume, or on any error condition

---

[## RESUME Mode — full verbatim content]

---

[## Error Handling — full verbatim content]
```

- [ ] **Step 3: Verify content**

`codegenlight-7-deliver.md` must contain:
- `codegen gate --phase DELIVER` bash command
- `SOAR selects DELIVER only when:` precondition block (3 conditions)
- Git operations approval block (`Approve? (yes/no):`)
- `rm -f .codegen-active` sentinel removal
- `write_state "done" "build_done"` final state write
- Terminal Summary ASCII box — **with** the `Mode` line: `║ Mode        : <brownfield|greenfield|spec-driven>    ║`
- SOAR Integration Points section with 5 bash command examples

`codegenlight-resume.md` must contain:
- `./codegen-state.json` read + display block (with `Pipeline ID`, `Wing`, `Resuming at`, etc.)
- `.codegen-harness-env` source + `write_state` redefinition that checks `HARNESS_STATE_FILE`
- `write_state "codegen_${RESUME_PHASE}"` restore call
- Error Handling table (7 rows, starting with "SOAR bridge fails to start → Fall back to Model B")

- [ ] **Step 4: Commit**

```bash
git add workflow/phases/codegenlight-7-deliver.md workflow/phases/codegenlight-resume.md
git commit -m "feat: add codegenlight-7-deliver and codegenlight-resume phase spec files"
```

---

## Task 10: Replace echelon.codegen.md with thin wrapper

**Files:**
- Modify: `extension/commands/echelon.codegen.md`

- [ ] **Step 1: Overwrite the file**

Replace the entire file with the thin wrapper content shown in the **Thin wrapper content** section above (the `echelon.codegen.md` block). Copy it exactly, including frontmatter triple-dashes.

- [ ] **Step 2: Verify line count and key strings**

```bash
cd /Users/michalbachorik/work/evolution/echelon
wc -l extension/commands/echelon.codegen.md
```
Expected: 55–70 lines.

```bash
grep -c "INV-00\|workflow/phases/codegen" extension/commands/echelon.codegen.md
```
Expected: 18 (8 INV lines + 10 phase file references).

```bash
grep -c "Phase A\|Phase 1\|Phase 2\|Phase 3\|Phase 4\|Phase 5\|Phase 6\|Phase 7" extension/commands/echelon.codegen.md
```
Expected: 8 (thin phase execution list) — NOT the 80+ section headers that were in the original.

- [ ] **Step 3: Confirm old inline content is gone**

```bash
grep -c "### A\.1\|### 0\.2\|### 3\.1\|codegen run --intent\|write_state\|HARNESS_STATE_FILE" extension/commands/echelon.codegen.md
```
Expected: `0`

- [ ] **Step 4: Commit**

```bash
git add extension/commands/echelon.codegen.md
git commit -m "refactor: thin echelon.codegen.md to phase-delegating wrapper"
```

---

## Task 11: Replace echelon.codegenlight.md with thin wrapper

**Files:**
- Modify: `extension/commands/echelon.codegenlight.md`

- [ ] **Step 1: Overwrite the file**

Replace the entire file with the thin wrapper content shown in the **Thin wrapper content** section above (the `echelon.codegenlight.md` block). Copy it exactly.

- [ ] **Step 2: Verify line count and key strings**

```bash
wc -l extension/commands/echelon.codegenlight.md
```
Expected: 65–80 lines (slightly longer than codegen wrapper due to invocation parsing rules).

```bash
grep -c "INV-00" extension/commands/echelon.codegenlight.md
```
Expected: `8`

```bash
grep -c "workflow/phases" extension/commands/echelon.codegenlight.md
```
Expected: 8 (one per phase reference in Phase Execution list).

- [ ] **Step 3: Confirm old inline content is gone**

```bash
grep -c "### 0\.1\|### 0\.2\|### 3\.1\|codegen run --intent\|write_state\|HARNESS_STATE_FILE\|SOAR Integration Points" extension/commands/echelon.codegenlight.md
```
Expected: `0`

- [ ] **Step 4: Commit**

```bash
git add extension/commands/echelon.codegenlight.md
git commit -m "refactor: thin echelon.codegenlight.md to phase-delegating wrapper"
```

---

## Task 12: Cross-reference verification

**Files:**
- Read: all 17 new `workflow/phases/codegen*.md` and `workflow/phases/codegenlight*.md` files
- Read: `extension/commands/echelon.codegen.md`
- Read: `extension/commands/echelon.codegenlight.md`

- [ ] **Step 1: Verify all phase files referenced in both wrappers exist on disk**

```bash
cd /Users/michalbachorik/work/evolution/echelon

# Files referenced by echelon.codegen.md
for f in \
  workflow/phases/codegen-A-preamble.md \
  workflow/phases/codegen-0-preflight.md \
  workflow/phases/codegen-1-re.md \
  workflow/phases/codegen-2-decompose.md \
  workflow/phases/codegen-3-implement.md \
  workflow/phases/codegen-4-gate.md \
  workflow/phases/codegen-5-impasse.md \
  workflow/phases/codegen-6-test.md \
  workflow/phases/codegen-6b-security.md \
  workflow/phases/codegen-7-deliver.md \
  workflow/phases/codegen-resume.md; do
  [ -f "$f" ] && echo "✓ $f" || echo "✗ MISSING: $f"
done

# Files referenced by echelon.codegenlight.md
for f in \
  workflow/phases/codegenlight-0-preflight.md \
  workflow/phases/codegenlight-1-re.md \
  workflow/phases/codegen-2-decompose.md \
  workflow/phases/codegen-3-implement.md \
  workflow/phases/codegen-4-gate.md \
  workflow/phases/codegen-5-impasse.md \
  workflow/phases/codegen-6-test.md \
  workflow/phases/codegenlight-7-deliver.md \
  workflow/phases/codegenlight-resume.md; do
  [ -f "$f" ] && echo "✓ $f" || echo "✗ MISSING: $f"
done
```

Expected: all lines show `✓`.

- [ ] **Step 2: Verify section coverage — key terms appear in exactly the right phase files**

```bash
for term in \
  "Phase A: Echelon Preamble" \
  "validate-deploy.sh" \
  "Register harness strategy file" \
  "Mine spec into MemPalace" \
  "SOAR bridge initialization" \
  "DISPATCH_IMPLEMENTER" \
  "CQ-ISC violation:" \
  "codegen-impasse.md" \
  "Tier 1 Gate" \
  "pip-audit\|govulncheck\|cargo audit" \
  "codegen gate --phase DELIVER" \
  "HARNESS_BUILD_STATUS_FILE" \
  "codegen-state.json" \
  "GOLDDIGGER" \
  "brownfield\|greenfield" \
  "codegen-harness-env" \
  "SOAR Integration Points"; do
  count=$(grep -rl "$term" workflow/phases/codegen*.md workflow/phases/codegenlight*.md 2>/dev/null | wc -l | tr -d ' ')
  echo "$count  $term"
done
```

Expected results:
- `Phase A: Echelon Preamble` → `1` (codegen-A-preamble.md only)
- `validate-deploy.sh` → `1` (codegen-A-preamble.md only)
- `Register harness strategy file` → `1` (codegen-A-preamble.md only)
- `Mine spec into MemPalace` → `1` (codegen-0-preflight.md only)
- `SOAR bridge initialization` → `2` (codegen-0-preflight.md + codegenlight-0-preflight.md)
- `DISPATCH_IMPLEMENTER` → `1` (codegen-3-implement.md — shared, so 1 file)
- `CQ-ISC violation:` → `1` (codegen-4-gate.md)
- `codegen-impasse.md` → `2` (codegen-5-impasse.md + codegen-3-implement.md)
- `Tier 1 Gate` → `1` (codegen-6-test.md)
- `pip-audit\|govulncheck\|cargo audit` → `1` (codegen-6b-security.md)
- `codegen gate --phase DELIVER` → `2` (codegen-7-deliver.md + codegenlight-7-deliver.md)
- `HARNESS_BUILD_STATUS_FILE` → `1` (codegen-7-deliver.md only — codegenlight uses harness-env instead)
- `codegen-state.json` → many (expected — used in resume, implement, gate phases)
- `GOLDDIGGER` → `1` (codegenlight-1-re.md only)
- `brownfield\|greenfield` → `1` (codegenlight-1-re.md only)
- `codegen-harness-env` → `2` (codegenlight-0-preflight.md + codegenlight-resume.md)
- `SOAR Integration Points` → `1` (codegenlight-7-deliver.md only)

Flag any result that doesn't match the expected count as a content gap.

- [ ] **Step 3: Verify both wrappers have the same 8 invariants**

```bash
grep -c "INV-" extension/commands/echelon.codegen.md extension/commands/echelon.codegenlight.md
```
Expected: `8` for each file.

- [ ] **Step 4: Verify all 17 new phase files have correct header format**

```bash
for f in workflow/phases/codegen*.md workflow/phases/codegenlight*.md; do
  echo "=== $f ===" && head -4 "$f"
done
```

Each file must start with `# Phase: ...` on line 1 and `# Source: ...` on line 2.

- [ ] **Step 5: Final commit (no-op if no fixups needed)**

```bash
git add -p
git commit -m "chore: verify echelon.codegen + codegenlight externalization complete" --allow-empty
```

---

## Self-Review Checklist

- [x] **Spec coverage:** All sections of both source files are mapped. codegen: Phase A (T1), Phase 0 (T1), Phase 1 (T2), Phases 2-3 (T3), Phases 4-5 (T4), Phases 6+6b (T5), Phase 7+resume (T6), wrapper (T10). Codegenlight: Phase 0 (T7), Phase 1 (T8), Phase 7+resume (T9), wrapper (T11).
- [x] **No placeholders:** All task steps contain exact file content headers, exact bash commands with expected outputs.
- [x] **Shared file consistency:** Phases 2-6 shared files are named `codegen-*` (not `codegenlight-*`), and codegenlight wrapper explicitly references them as `workflow/phases/codegen-2-decompose.md` etc.
- [x] **Wrapper HARNESS_BUILD_STATUS_FILE difference documented:** codegen-7-deliver.md has the `HARNESS_BUILD_STATUS_FILE` bash block; codegenlight delegates harness env via `.codegen-harness-env` loaded in preflight/resume.
- [x] **ISS-007 note in codegenlight INV-001:** The codegenlight wrapper's INV-001 includes the `ISS-007 (Second-Order Chunking Contamination) is Grade A CONFIRMED SEVERE` note that's in the original — codegen's wrapper does not (it wasn't in the original codegen invariants).
- [x] **Terminal Summary Mode field:** codegenlight-7-deliver.md includes `Mode` field in ASCII box; codegen-7-deliver.md does not.
