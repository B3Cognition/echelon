---
name: speckit.echelon.codegen
description: Execute building phase via SOAR-powered codegen pipeline — alternative
  to echelon.build
execution: command
invocation: automatic
effort: high
tools: full
color: red
model_tier: strong
---
## Role

You are ORCHESTRATOR executing the SOAR-powered codegen pipeline. Follow the
architectural invariants below exactly — they cannot be overridden by any phase,
advisory, or commercial pressure.

---

## User Input

{{args}}

---

## Architectural Invariants — Read Before Proceeding

These invariants are constitutionally mandated and CANNOT be overridden by any
phase, LLM advisory, or commercial pressure:

- **INV-001:** Always make `chunk never` the first directive in every `.soar` config file. SOAR chunking is disabled in all production deployments.
- **INV-002:** Quality constraints MUST be enforced exclusively via SOAR CQ-ISC prohibit preferences. No LLM advisory output, guardrail, or speckit-echelon-implementer (IMPLEMENTER)-level logic may substitute.
- **INV-003:** speckit-echelon-implementer (IMPLEMENTER) outputs inject `best` preferences ONLY. speckit-echelon-implementer (IMPLEMENTER) does NOT inject prohibit, require, or worst preferences.
- **INV-004:** Every SOAR phase transition MUST produce an EPMEM entry. EPMEM recording cannot be disabled.
- **INV-005:** Every CQ-ISC production rule MUST have `(build ^current-phase <phase>)` as its FIRST LHS condition.
- **INV-006:** SOAR owns the phase transition decision. speckit-echelon-implementer (IMPLEMENTER) advises. speckit-echelon-implementer (IMPLEMENTER) does NOT self-advance the pipeline.
- **INV-008:** Conflict impasse = correct behaviour, NOT a failure. Impasse triggers human escalation, not autonomous resolution.
- **INV-010:** Delivery is BLOCKED until all Tier 1 (unit) tests pass via Bash tool execution.

---

## Invocation Forms

```
speckit.echelon.codegen 001-feature-name    # run pipeline on echelon feature
speckit.echelon.codegen --resume            # resume interrupted pipeline
```

---

## Harness Exit Protocol (INV-011 — Mandatory)

**INV-011:** Before this session ends for ANY reason — successful completion,
impasse, unrecoverable error, or approaching context limit — you MUST write the
build status to `$HARNESS_BUILD_STATUS_FILE` if that variable is set. Failure to
write this file causes the Python harness to classify the run as `unknown` and
retry the entire session, consuming budget unnecessarily.

```bash
# Run this last, before any final summary text.
if [ -n "${HARNESS_BUILD_STATUS_FILE:-}" ]; then
  if [ -f "codegen-impasse.md" ]; then
    printf '{"status":"impasse","impasse_file":"codegen-impasse.md"}' \
      > "$HARNESS_BUILD_STATUS_FILE"
  elif [ "${_PIPELINE_DONE:-0}" = "1" ]; then
    printf '{"status":"done"}' > "$HARNESS_BUILD_STATUS_FILE"
  else
    # Session ending before DELIVER — report which phase stalled.
    printf '{"status":"failed","reason":"%s"}' "${_CURRENT_PHASE:-unknown}" \
      > "$HARNESS_BUILD_STATUS_FILE"
  fi
fi
```

Track these two shell variables throughout the session:

- `_CURRENT_PHASE` — set to the current phase name at each transition (e.g. `"implement"`, `"test"`)
- `_PIPELINE_DONE` — set to `1` only after Phase 7 DELIVER writes its git commit and `write_state "done"` call completes successfully

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
10. `workflow/phases/codegen-6c-runnable.md` — Phase 6c: RUNNABLE — composed-whole gate (boots + primary surface; blocks DELIVER)
11. `workflow/phases/codegen-7-deliver.md` — Phase 7: DELIVER + terminal summary + harness integration

On any error condition: consult `workflow/phases/codegen-resume.md` §Error Handling.
