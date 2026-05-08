# Echelon Run Analysis — Full (Parts 1–3)

## What the run did correctly

- Reads `commander.md` and `definition.yaml` at startup — matches the contract
- `init` phase creates `state.json`, `reasoning-journal.jsonl`, `reasoning-journal-index.json`, `governance-trail.json` — correct structure
- Constitution detected as blank template → `constitution_status: pending` — correct
- Writes `confidence-thresholds.yaml` (Step 0.5, FR-FEP-001) — correct
- Pre-dispatch gate runs before SCOUT, SYNTHESIZER, CARTOGRAPHER, GATEKEEPER — correct
- Post-dispatch protocol: verifies staging artifacts, writes journal entries with sequential IDs — correct protocol execution
- `phase1-modeler` correctly skipped for greenfield — correct conditional
- State machine phase progression: `init → phase1-discover → phase1-synthesizer → phase1-tracker → phase1-why1 → phase1-constitution → phase1-what → phase1-why2 → phase2-decide → phase2-strategic-overview → phase2-tracker-alignment → phase3-how → phase3-specialists → phase3-sentinel → phase3-plan → phase3-consensus → phase4-document` — all phases executed in this order (specialists ordering deviation noted separately)
- SCOUT produces all 6 expected staging artifacts — correct
- SYNTHESIZER produces expected outputs plus extras — correct
- WHY1 PASS → `phase1-constitution` transition — correct gate logic
- `phase1-constitution` correctly identified as `commander_internal` — correct
- Git pre-hook `speckit-git-initialize` fires automatically — correct
- CARTOGRAPHER invokes `speckit.specify` itself — correct per §4.2
- Post-CARTOGRAPHER branch + directory verification runs — correct
- WHY2 FAIL correctly routes back to CARTOGRAPHER — correct gate logic
- EVOI analysis applied when delta convergence is not reachable — correct use of convergence mechanism
- checkpoint-assess auto-proceeds in banzai — correct
- COMMANDER reflection written before major phase transitions — correct (though not always logged as journal entry)
- GUARDIAN dispatched in phase3-specialists (even if ordering is wrong) — present
- ADVOCATE and BENCHMARK dispatched when conditions met — correct trigger evaluation
- Consensus (WHY3 + ASSESS2 + PLAN2) dispatched in parallel — correct
- checkpoint-plan auto-proceeds in banzai — correct

---

## Deviations from the spec

### INIT phase

**1. GUARDIAN never dispatched at initialization (critical omission)**

`commander.md` §"Run Initialization" step 1: *"Dispatch GUARDIAN (always-on by default) every run."* This mandatory init-time dispatch is separate from the phase3-specialists dispatch. Not shown during initialization.

**2. `reasoning-journal.jsonl` overwritten instead of appended**

Two separate `Write` operations target `reasoning-journal.jsonl`. The second write prints *"File created successfully"* — recreated, not appended. Index Writer Protocol: *"Append to .specify/squad/reasoning-journal.jsonl (single JSON line)"*. Overwriting destroys prior entries.

**3. `endocrine.sh` path bug**

Script constructs path `/tmp/a/.specify/extensions/.specify/squad/state.json` — wrong path. Fails on every run; fail-open silently skips endocrine injection.

**4. `detect-project.sh` not invoked**

`init.md` §1.1: script should run via frontmatter `scripts.sh`. `echelon.run.md` runs `startup-banner.sh` instead. Mode detection is heuristic.

**5. `validate-deploy.sh` hard-stop guard skipped**

`init.md` §1.0: *"bash validate-deploy.sh — HARD STOP if non-zero."* Not run.

**6. Config resolution not called**

`init.md` §1.6: `specify extension config resolve echelon --format env --prefix ECHELON_CFG_`. Not called; raw config read directly instead.

**7. KB learning outputs not read before cold-start write**

`commander.md` §0.1: read `calibration-profile.yaml`, `patterns.yaml`, `pitfalls.yaml`, `agent-scores.yaml` first, then log `init_knowledge_read` entry. Run writes `confidence-thresholds.yaml` without prior read attempts.

**8. Belief Freshness Gate not run**

`commander.md` FR-001: `belief-freshness-check.sh` after init_reads. Not shown.

**9. Run History Check skipped (marked mandatory)**

`init.md` §1.3: check `run-history.json` in spec_dir at init. Not shown.

**10. State.json written in fragments (recurring pattern)**

Post-dispatch updates use 2–3 separate `Edit` calls instead of an atomic write. Creates window where `post_dispatch_complete` is false while other fields are partially updated — resumability hazard. Observed after SCOUT, SYNTHESIZER, WHY2, STRATEGIST, CARTOGRAPHER, and multiple other dispatches.

**11. TRACKER post-dispatch order inverted**

Transition to WHY1 announced before journal entry (RJ-014) and state.json update are written. Post-dispatch protocol requires `post_dispatch_complete: true` before any transition.

---

### Phase 1 — UNDERSTAND

**12. WHY1 context pack missing `calibration-profile.yaml`**

`phase1-why1.md` lists `calibration-profile.yaml` as required context. Not included; SAGE found "no kb dir in staging."

**13. `sage-decisions.yaml` written to inconsistent paths**

WHY1 writes to `staging/knowledge-base/sage-decisions.yaml`; WHY2 writes to `knowledge-base/sage-decisions.yaml` (project root). Same agent, different invocations, different directories. Downstream AUDITOR/INTERNALIZER reads break.

**14. Constitution created without UNDERSTAND context**

`phase1-constitution.md` §"Prepare Constitution Context": gather domain context from glossary.md, mental-model.md, boundaries.md, assumptions.md and pass to `speckit.constitution`. Run invokes skill directly with no extracted context. Constitution lacks domain-specific principles from SCOUT/SYNTHESIZER.

**15. `00-overview.md` never produced**

`phase1-what.md` §"Expected Outputs": both `spec.md` and `00-overview.md` required. Only `spec.md` produced.

**16. Staging artifacts not moved to spec directory**

`phase1-what.md` instructs CARTOGRAPHER to move staging artifacts. All staging files remain in `.specify/squad/staging/`; spec directory contains only newly created files.

**17. CARTOGRAPHER spec enhancement not executed**

CARTOGRAPHER should enhance the spec with SCOUT's domain insights, add Given/When/Then acceptance criteria, cross-reference glossary and mental model. After the double `speckit.specify` invocation CARTOGRAPHER returns immediately — no enhancement pass.

**18. Fallback path inverted**

`phase1-what.md` §4.2: if CARTOGRAPHER is BLOCKED, COMMANDER calls `speckit.specify` directly. Instead, CARTOGRAPHER itself re-invoked the skill after detecting the spec dir missing. CARTOGRAPHER ran `speckit.specify` twice.

**19. `spec_status` not updated to "planned"**

`phase1-what.md` §4.3 (mandatory): `state.json.spec_status = "planned"` and spec.md `Status: Draft` → `Status: Planned`. Neither done.

**20. `dependency_checks.understanding` not persisted**

`phase1-why2.md`: *"Persist state.json.dependency_checks.understanding with status, checked_at."* Not written.

**21. `quality_scores[]` not appended after WHY2 passes**

`phase1-why2.md` §"Gate Check" step 3: append all 8 score fields to `state.json.quality_scores[]`. Without this, the convergence delta check (step 4) cannot compare consecutive passes.

**22. `speckit-echelon-understanding-diagram` crashes with `disable-model-invocation` (recurring)**

SAGE attempts to call this skill via the Skill tool in WHY2 iter 1, 2, and 3. All fail with *"Skill cannot be used with Skill tool due to disable-model-invocation."* Bug in SAGE agent definition. Silently skipped each time.

**23. Graphviz `dot` not available — diagram generation fails**

In WHY2 iter 3, SAGE attempts to generate entity-relationship diagram via bash and gets *"Error: failed to execute PosixPath('dot')"*. Graphviz not installed in the environment.

**24. Pre-dispatch gate skipped for CARTOGRAPHER iter 3 and SAGE WHY2 iter 3**

First CARTOGRAPHER iteration shows pre-dispatch gate; iteration 3 shows no gate check before dispatch.

**25. EVOI forces convergence when delta criterion not mathematically met**

Bash computes `MAX absolute delta: 0.2096 — Convergence (max delta < 0.01)? NO`. COMMANDER overrides with EVOI reasoning ("negative EVOI → stop iterating"). The spec describes EVOI as a pre-iteration check; using it to force convergence mid-loop when the criteria explicitly say NO is a behavioral deviation. The outcome may be correct, but the mechanism diverges.

**26. COMMANDER write error on `quality-gates.md`**

After WHY2 iter 3, COMMANDER attempts `Write: quality-gates.md` → error *"File has not been read yet."* Recovers by reading then editing. Minor resilience issue showing COMMANDER attempts writes on files it hasn't read.

---

### Phase 2 — DECIDE

**27. `phase-timing.sh` never called at any phase boundary (systematic)**

`phase2-decide.md`, `phase2-strategic-overview.md`, `phase3-specialists.md`, `phase3-sentinel.md`, `phase3-plan.md`, and `phase3-consensus.md` all specify calls to `scripts/bash/phase-timing.sh start_phase` / `end_phase` before or after dispatch. None appear anywhere in the run. Phase timing infrastructure is completely absent.

**28. GATEKEEPER context pack missing `calibration-profile.yaml` and `glossary.md`**

`phase2-decide.md` requires: `spec.md + glossary.md + assumptions.md + issues.md + calibration-profile.yaml + estimates-log.yaml`. GATEKEEPER reads spec.md, assumptions.md, user-intent.md, issues.md, reasoning-journal.json, constitution.md. Missing: `glossary.md`, `calibration-profile.yaml`, `estimates-log.yaml`.

**29. TRACKER alignment output filename wrong**

`phase2-tracker-alignment.md`: *"Produce `intent-alignment-check.md` in `specs/{NNN}-{feature}/`."* Run produces `alignment-report.md`.

---

### Phase 3 — DESIGN

**30. Specialists (phase3-specialists) run AFTER ARCHITECT instead of before (major ordering violation)**

`phase3-specialists.md` transition is `phases[phase3-how]` — specialists complete first, then ARCHITECT uses their outputs. COMMANDER's reflection explicitly states "GUARDIAN will run in phase3-specialists immediately after ARCHITECT." This reverses the dependency. ARCHITECT made technology and architecture decisions without GUARDIAN's security findings, ADVOCATE's 5 new accessibility requirements (FR-032–035), or BENCHMARK's performance model. These were added retroactively.

**31. Specialists dispatched in parallel (should be sequential)**

`phase3-specialists.md`: *"dispatch sequentially (unless they are independent — INVESTIGATOR investigations can run in parallel with domain specialists)."* GUARDIAN, ADVOCATE, and BENCHMARK dispatched simultaneously in a single parallel batch. The spec only permits INVESTIGATOR to run in parallel with others.

**32. INNOVATE not dispatched despite meeting trigger #3**

`phase3-specialists.md` trigger: *"WHY rejects spec 2+ times → INNOVATE reframes the problem."* WHY2 failed 3 consecutive times. COMMANDER's specialist evaluation lists INVESTIGATOR, ADVOCATE, BENCHMARK — no mention of INNOVATE.

**33. ARCHITECT expected outputs missing: `plan.md` and `contracts/`**

`phase3-how.md` §"Expected Outputs": `plan.md`, `research.md`, `data-model.md`, `contracts/`, `constitution.md`. ARCHITECT produces: `ADR-001–003.md`, `architecture.md`, `data-model.md`, `research.md`. `plan.md` and `contracts/` directory not created. Downstream SENTINEL and ORCHESTRATOR cannot read `plan.md`.

**34. SENTINEL missing expected output: `test-architecture.md`**

`phase3-sentinel.md` §"Expected Outputs": `test-strategy.md`, `test-architecture.md`, `coverage-map.md`. Only `test-strategy.md` and `coverage-map.md` produced.

**35. SENTINEL context pack uses `architecture.md` as proxy for missing `plan.md`**

SENTINEL is supposed to receive `plan.md + data-model.md + spec.md + contracts/`. `plan.md` and `contracts/` don't exist (consequence of #33). SENTINEL reads `architecture.md` instead.

**36. ORCHESTRATOR missing `risk-matrix.md`; `dependency-graph.md` ≠ `dependencies.md`**

`phase3-plan.md` §"Expected Outputs": `tasks.md`, `critical-path.md`, `risk-matrix.md`, `dependencies.md`. Run produces `tasks.md`, `critical-path.md`, `dependency-graph.md`. `risk-matrix.md` absent; filename `dependency-graph.md` doesn't match the expected `dependencies.md`.

**37. ORCHESTRATOR edits `spec.md` — outside its mandate**

ORCHESTRATOR makes two `Edit` calls to `spec.md`. ORCHESTRATOR's role is task breakdown; spec.md is owned by CARTOGRAPHER. Per constitution authority rules, agents may not modify artifacts outside their domain.

**38. WHY3 + ASSESS2 + PLAN2 all dispatched simultaneously; PLAN2 should wait for ASSESS2**

`phase3-consensus.md`: *"Dispatch WHY3 and ASSESS2 in parallel… After WHY3 and ASSESS2 complete, dispatch PLAN2."* PLAN2 needs `implementability-report.md` from ASSESS2. All three dispatched at once; PLAN2 runs without ASSESS2's output.

---

### Phase 4 — FINALIZE (phase4-document)

The entire learning and calibration sequence is skipped. `phase4-document.md` specifies 12 steps:

**39. REALIST not dispatched (step 12.1)**

Expected outputs: `reality-check.md`, `cost-analysis.md`, `benchmark-data.md`. Not present in artifact listing.

**40. MIRROR not dispatched (step 12.2)**

Expected: extract patterns/pitfalls, update `knowledge-base/patterns.yaml` and `pitfalls.yaml`. Not shown.

**41. AUDITOR not dispatched (step 12.4)**

Expected: update `calibration-profile.yaml`, produce `confidence-flags.md`. Not shown. Cross-run calibration data is never written.

**42. SCOREKEEPER not dispatched (step 12.7)**

Scorecard not produced. Agent scoring is tracked in state.json entries but final scorecard is absent.

**43. `run-history.json` not written (step 12.8, mandatory)**

*"Read or create {spec_dir}/run-history.json. Append to runs array."* Marked mandatory. Not done. Prevents future runs from detecting Phase A is complete and skipping to Phase B.

**44. Staging not archived and not cleaned (step 12.10)**

`archive/${RUN_ID}/` not created. Staging not wiped. Institutional memory from this run is not preserved.

**45. Git not returned to default branch (step 12.11)**

Run ends on `001-fancy-hello-world` branch. Next harness invocation will encounter a "branch already checked out" conflict.

**46. Timing summary never written (phase3-consensus.md end-of-run requirement)**

`end_phase phase4-build` not called. No `timing_summary` journal entries written per phase.

**47. Prescribed terminal summary format not printed (step 12.9)**

The mandatory ECHELON RUN COMPLETE banner (with quality scores, specialists summoned, agent scorecard, warnings, risks accepted, human actions required) is never printed. The run ends with state.json updates and a single journal entry.

**48. Completion Signal format not printed (commander.md)**

The SQUAD COMPLETE banner (with INTERNALIZATION SUMMARY, DIAGNOSTIC MATRIX, CALIBRATION DASHBOARD) from commander.md §"Completion Signal" is also absent.

---

## Master Summary Table

✅ = fixed in commit `be1241c` (2026-05-08, low-risk batch)
✅M1 = fixed in commits `fbb0de1` + `ba6ff2d` (2026-05-08, M1 medium doc batch + understanding-diagram fix)
✅SM = fixed in commits `76cbc22` + `b3fd5b8` (2026-05-08, state-machine externalisation + definition.yaml sync)
✅M2 = fixed in commit `02808ca` (2026-05-08, M2 script/code batch)
✅H = fixed in H batch (see below)

| # | Status | Severity | Issue | Phase |
|---|--------|----------|-------|-------|
| 1 | ✅H | High | GUARDIAN not dispatched at init (mandatory always-on) | init |
| 2 | ✅H | High | `reasoning-journal.jsonl` overwritten not appended | init |
| 30 | ✅H | High | Specialists run AFTER ARCHITECT instead of before — ordering inversion | phase3 |
| 17 | ✅H | High | CARTOGRAPHER spec enhancement not executed | phase1-what |
| 38 | ✅H | High | PLAN2 dispatched without ASSESS2's implementability-report.md | phase3-consensus |
| 3 | ✅M2 | Medium | `endocrine.sh` wrong path — silent fail every run | pre-dispatch |
| 4 | ✅M2 | Medium | `detect-project.sh` not invoked — mode detection is ad hoc | init |
| 5 | ✅M2 | Medium | `validate-deploy.sh` hard-stop guard skipped | init |
| 6 | ✅M2 | Medium | Config resolution not called | init |
| 14 | ✅M1 | Medium | Constitution created without UNDERSTAND context | phase1-constitution |
| 15 | ✅M1 | Medium | `00-overview.md` never produced | phase1-what |
| 16 | ✅M1 | Medium | Staging artifacts not moved to spec directory | phase1-what |
| 18 | ✅M1 | Medium | Fallback path inverted — CARTOGRAPHER handles COMMANDER's role | phase1-what |
| 22 | ✅M1 | Medium | `understanding-diagram` crashes with disable-model-invocation (× 3) | phase1-why2 |
| 27 | ✅M1 | Medium | `phase-timing.sh` never called at any phase boundary (systematic) | all phases |
| 31 | ✅SM | Medium | Specialists dispatched in parallel (should be sequential) | phase3-specialists |
| 32 | ✅SM | Medium | INNOVATE not dispatched despite WHY2 failing 3× (trigger met) | phase3-specialists |
| 33 | ✅M1 | Medium | ARCHITECT missing `plan.md` and `contracts/` | phase3-how |
| 39–42 | ✅M1 | Medium | REALIST, MIRROR, AUDITOR, SCOREKEEPER all skipped | phase4-document |
| 43 | ✅M1 | Medium | `run-history.json` not written (mandatory) | phase4-document |
| 44 | ✅M1 | Medium | Staging not archived or cleaned | phase4-document |
| 45 | ✅M1 | Medium | Git not returned to default branch | phase4-document |
| 47 | ✅M1 | Medium | ECHELON RUN COMPLETE banner not printed — mandatory HUMAN ACTIONS REQUIRED section absent | phase4-document |
| 50 | ✅M1 | Medium | `calibration-dashboard.md` never written; INTERNALIZER never dispatched | phase4-document |
| 7 | ✅ fixed | Low | KB learning outputs not read before cold-start write | init |
| 8 | ✅ fixed | Low | Belief Freshness Gate not run | init |
| 9 | ✅ fixed | Low | Run History Check skipped (mandatory) | init |
| 10 | ✅ fixed | Low | State.json written in fragments (recurring, all phases) | all |
| 11 | ✅ fixed | Low | TRACKER post-dispatch order inverted | phase1-tracker |
| 12 | ✅ fixed | Low | WHY1 context pack missing `calibration-profile.yaml` | phase1-why1 |
| 13 | ✅ fixed | Low | `sage-decisions.yaml` in inconsistent paths (WHY1 vs WHY2) | phase1-why1/2 |
| 19 | ✅ fixed | Low | `spec_status` not updated to "planned" | phase1-what |
| 20 | ✅ fixed | Low | `dependency_checks.understanding` not persisted | phase1-why2 |
| 21 | ✅ fixed | Low | `quality_scores[]` not appended — convergence check broken | phase1-why2 |
| 23 | ✅ fixed | Low | Graphviz not installed — diagram generation fails silently | phase1-why2 |
| 24 | ✅ fixed | Low | Pre-dispatch gate skipped for CARTOGRAPHER iter 3 / SAGE WHY2 iter 3 | phase1-why2 |
| 25 | ✅ fixed | Low | EVOI forces convergence when delta criterion mathematically says NO | phase1-why2 |
| 26 | ✅ fixed | Low | COMMANDER write error on `quality-gates.md` (unread file) | phase1-why2 |
| 28 | ✅ fixed | Low | GATEKEEPER context pack missing `glossary.md` and `calibration-profile.yaml` | phase2-decide |
| 29 | ✅ fixed | Low | TRACKER alignment output filename wrong (`alignment-report.md` vs `intent-alignment-check.md`) | phase2-tracker-alignment |
| 34 | ✅ fixed | Low | SENTINEL missing `test-architecture.md` | phase3-sentinel |
| 35 | ✅ fixed | Low | SENTINEL uses `architecture.md` as proxy for missing `plan.md` | phase3-sentinel |
| 36 | ✅ fixed | Low | ORCHESTRATOR: `risk-matrix.md` absent; wrong filename `dependency-graph.md` | phase3-plan |
| 37 | ✅ fixed | Low | ORCHESTRATOR edits `spec.md` outside its mandate | phase3-plan |
| 46 | ✅ fixed | Low | Phase timing summary never written | phase4-document |
| 48 | ✅ fixed | Low | SQUAD COMPLETE signal format deviations (see Part 4 detail) | phase4-document |
| 49 | ✅ fixed | Low | `reasoning-journal-index.json` full overwrite instead of incremental update | phase4-document |
