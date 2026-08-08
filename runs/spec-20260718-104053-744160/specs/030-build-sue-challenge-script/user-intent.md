# User Intent

## Metadata

- Spec: 030-build-sue-challenge-script
- Tracker: speckit-echelon-tracker (TRACKER)
- Date: 2026-07-18
- Source request: run `user_message` (state.json) + approved design document `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md` (status: approved, IN-REQ-7698BBDFCDF2), snapshotted as the sole requirement input

## Explicit Statements

Preserve user wording accurately, but quote only what is needed.

| ID | Statement | Source / Context | Priority |
|----|-----------|------------------|----------|
| UI-001 | "Build the SUE challenge script: a standalone Python script (scripts/sue_challenge.py)" — the deliverable is one self-contained script at exactly that path | user_message | high |
| UI-002 | "challenges a specification via Socratic question-answer dialogue using two isolated claude -p calls" — the mechanism (two rounds, isolation) is itself the requirement, not an implementation suggestion | user_message | high |
| UI-003 | "per the attached approved design document" — the design doc is the authority; the squad elaborates it, it does not redesign it | user_message; design doc status "approved (brainstorming session)" (IN-REQ-7698BBDFCDF2) | high |
| UI-004 | "Implement exactly the v1 scope: interface, JSON schemas, isolation contract, report format, error handling, and pytest unit tests as designed" — six enumerated areas; "exactly" cuts both ways: no expansion AND no silent trimming of designed details | user_message | high |
| UI-005 | v1 scope boundary: "question→answer dialogue tier only. No graphs, no convergence scoring, no workflow integration" | design doc (IN-REQ-8E578B6660BB, IN-REQ-032461DF1B5D) | high |
| UI-006 | Grounding rule: "the engine asks, the text testifies, the human decides" — findings are questions the spec text cannot answer; humans judge them | design doc (IN-REQ-BF81CFD48938, IN-REQ-7802BD15CC2F) | high |
| UI-007 | Interface: positional spec path; `--questions` (default 15), `--claude-cmd` (default `claude`, also the test seam), `--timeout` (default 300); exit codes 0/1/2/3 with defined meanings | design doc (IN-REQ-F7DA9407BAE0 … IN-REQ-2189E42069FA) | high |
| UI-008 | Isolation contract: both calls subprocess with neutral temp cwd (repo context must not leak); round 2 sees only the spec text and the questions, never round-1 reasoning | design doc (IN-REQ-2F84DF72B209 … IN-REQ-7906C2CCFEBC) | high |
| UI-009 | Report: `<spec-dir>/socratic-challenge.md` + stdout summary (finding counts, top 3); reruns overwrite, no history; sections = header, findings, and a **collapsed** audit section of ANSWERED questions | design doc (IN-REQ-44BED4ECFE26 … IN-REQ-31A836647EEC, IN-REQ-2D4902546481) | high |
| UI-010 | Error handling: exit 2 with install pointer on missing claude (ERR-CLI-MISSING mirror); one corrective retry on parse failure then exit 3 with raw output to `.sue-debug/`; timeout takes the parse-failure path; exit 1 before any model call on bad spec path | design doc (IN-REQ-49464B14EFA0 … IN-REQ-35B2A2BF9F9D) | high |
| UI-011 | Testing: pytest unit tests (`tests/unit/test_sue_challenge.py`) for the deterministic parts with model calls faked via `--claude-cmd` stub; acceptance = one manual live run against spec 029 with findings overlapping the three named known issues | design doc (IN-REQ-B97DBA8344BE … IN-REQ-D05A70A0F5B4) | high |
| UI-012 | Non-goals (v1): multi-reader consensus, interpretation graphs, convergence metrics, WHY3/workflow integration, encoding answers back into specs, `echelon` CLI verb; the CLI interface (spec path in, markdown report out) is stable under all later additions | design doc (IN-REQ-4E9070D640A5 … IN-REQ-C68D7D0CB17E) | high |

## Inferred Intent

| ID | Inference | Evidence | Confidence |
|----|-----------|----------|------------|
| II-001 | "Exactly as designed" means designed details must survive into the spec verbatim — including small ones like the *collapsed* rendering of the audit section, which DISCOVER outputs already dropped | UI-004 wording; drift already observed (contradictions-and-gaps.md gap 1; risks.md drift risk "Approved design doc vs squad spec") | 0.9 |
| II-002 | Where the design is silent (U-003 retry content, U-004 `--claude-cmd` splitting, U-005 degenerate outcomes, U-006 line provenance, U-007 exit-2 boundary), the user expects minimal, design-spirit resolutions that pin behavior for tests — not new features (no JSON output mode, no history, no locking, no config file) | UI-004 "exactly"; UI-012 non-goals; design's stable-interface promise (IN-REQ-128505B4CC53) | 0.85 |
| II-003 | The user's intent for isolation is the *outcome* (repo context must not bias the reading); the temp-cwd mechanism is the designed means. If the means proves insufficient (user-scope context, A-002/U-002), the user would want that surfaced and handled deliberately, not silently accepted or silently patched | UI-002 names "isolated" in the one-sentence summary — isolation is first-class to the user; design rationale wording "repo context must not leak" (IN-REQ-1A64043748C4) states an outcome | 0.8 |
| II-004 | The user wants a *working* tool, validated live — the acceptance run against spec 029 is part of the intent, not optional polish | UI-011; design doc dedicates its Testing section to it | 0.85 |
| II-005 | Standalone means the script must not import `src/harness`/`src/echelon` or read `echelon-config.yml`; `scripts/contradiction-scanner.py` is the intended shape precedent | UI-001 "standalone"; UI-012 excludes the echelon CLI verb; A-003 and boundaries.md NON-boundary | 0.9 |
| II-006 | This is v1 of a longer SUE roadmap; the user intends the CLI contract to be the stable seam future tiers build on, so interface changes are the most intent-sensitive edits of all | UI-012 (IN-REQ-128505B4CC53 "stable under all of these later additions") | 0.85 |

## Scope Preferences

| Preference | Evidence | Constraint / Risk |
|------------|----------|-------------------|
| Full fidelity to v1 design — all six enumerated areas (interface, schemas, isolation, report, errors, tests), none subsetted | UI-004 "Implement exactly the v1 scope" | Do NOT apply MVP-style prioritization to trim any of the six areas; that is the exact failure mode TRACKER exists to catch |
| No scope expansion beyond v1 | UI-005, UI-012 non-goals list | Resolving unknowns (U-001…U-007) must not smuggle in v2 features; contradiction/gap fixes should be the smallest decision that pins behavior |
| Standalone script, repo `scripts/` conventions | UI-001; scanner precedent (A-003) | No harness/echelon imports; unit tests runnable without the installed venv |
| Design-doc authority over agent reasoning | UI-003 | Where DISCOVER analysis disagrees with the design (e.g. strict-JSON feasibility, isolation sufficiency), the squad may *challenge and surface* but must not *silently override*; material deviations from designed behavior need explicit traceable decisions |

## Intent vs Spec Alignment

Originally assessed pre-CARTOGRAPHER against the staging knowledge base; rows updated 2026-07-18 at the phase2 alignment gate now that spec.md and GATEKEEPER's scope exist (see intent-alignment-check.md).

| User Intent | Spec Says (staging artifacts) | Aligned? |
|-------------|-------------------------------|----------|
| UI-001/UI-005/UI-012 scope boundary (v1 tier only, standalone, non-goals excluded) | glossary.md, boundaries.md (explicit NON-boundary), assumptions.md A-003 all preserve the boundary faithfully | yes |
| UI-007 interface + exit codes | mental-model.md exit-code state machine and Challenge Run entity match the design exactly | yes |
| UI-008 isolation contract | Captured faithfully, AND correctly challenged: A-002/U-002 record that temp cwd may not fully deliver the isolation outcome — a challenge to the premise, not an override of intent | yes |
| UI-009 report format incl. collapsed audit section | RF-1 closed: spec.md FR-038 and AC-008 restore the collapsed rendering; mvp-scope.md F4 carries it forward | yes |
| UI-010 error handling | Captured faithfully; U-003/U-005/U-007 record genuine design silences for resolution, not deviations | yes |
| UI-011 testing + acceptance | RF-4 substantially closed: tolerance encoded openly in AC-023/SC-001 with rationale in mvp-scope.md F6 — surfaced, not silent. Low-severity residual: the amendment is missing from spec.md's "Resolved During WHAT" table (intent-alignment-check.md DIV-001, CARTOGRAPHER at next spec touch) | yes |

## Red Flags

| Intent Divergence | Evidence | Required Attention |
|-------------------|----------|--------------------|
| RF-1: "Collapsed" audit-section rendering silently dropped from all DISCOVER outputs — first observed drift from "exactly as designed" | IN-REQ-2D4902546481 vs glossary/mental-model/boundaries; contradictions-and-gaps.md gap 1 | CARTOGRAPHER must carry "collapsed" into the report-format FR (or record an explicit, traceable decision to render otherwise) |
| RF-2: Unknown-resolution scope creep — U-001…U-007 decisions could accrete features (output modes, history, locking, retry sophistication) beyond v1 | II-002; UI-012 non-goals | GATEKEEPER/SAGE: each unknown resolution should be the minimal behavior-pinning decision; anything feature-shaped is out of v1 |
| RF-3: Isolation mechanism vs outcome — if the U-002 spike shows temp cwd is insufficient, both silent acceptance (leak) and silent strengthening (extra CLI flags nobody approved) deviate from "exactly as designed" | A-002/U-002; MODELER ALERT V-1 (journal id 14) | Surface as an explicit spec decision: either add suppression flags as a documented, traceable design amendment, or document the user-scope leak as a v1 limitation. In banzai autonomy: decide traceably; do not stop the run for this |
| RF-4: Acceptance-criterion tolerance — SCOUT/SYNTHESIZER propose relaxing "one manual run overlapping three known issues" (flaky by construction). Sensible, but it edits an approved acceptance criterion | contradictions-and-gaps.md contradiction 3; risks.md "Flaky acceptance criterion" | CARTOGRAPHER: encode tolerance as an explicit clarification decision with rationale in the spec, never as a silent rewording of the design's AC |

## Verdict Rationale

Intent clarity is unusually high for this run: the request binds to an approved design document and says "implement exactly the v1 scope." The dominant intent risk is not under-delivery of an ambiguous wish but **fidelity erosion** — small designed details (RF-1) or approved criteria (RF-4) drifting during formalization, and unknown-resolution creep (RF-2). All four red flags are trackable through normal phase gates; none blocks progress or requires user input now. Verdict: **ALIGNED**.
