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
