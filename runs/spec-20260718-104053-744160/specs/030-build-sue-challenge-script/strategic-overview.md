# Strategic Overview

**Date:** 2026-07-18
**Feature:** 030-build-sue-challenge-script

## Risk-Weighted Component Map

Components are the six prioritization features (prioritization.md F1–F6). Effort percentages are each feature's share of the 0.28 person-week most-likely total from estimates.md. Business risk asks "what does the product lose if this is wrong"; technical risk asks "how likely is it to be wrong given current evidence".

| Component | Business Risk | Technical Risk | Combined | Effort | Verdict |
|-----------|---------------|----------------|----------|--------|---------|
| F3 Round schemas, extraction, validation & retry (FR-014–FR-031) | HIGH — a wrong FR-026 extraction contract converts systematic output noise into exit 3 on **every** run; the whole tool is dead, not degraded (feasibility.md risk 1) | HIGH — A-001 unvalidated; the only repo-proven `claude -p` integration needed stream-json plus a backend layer (journal 15) | CRITICAL | 29% | APPROPRIATE — largest allocation is correct, **conditional on the OQ-001 spike running before HOW freezes the contract** |
| F2 Model invocation & isolation (FR-008–FR-013) | HIGH — isolation is the blind-reader premise of the grounding rule, plus the data-egress trust boundary (risks.md); silent bias, not a crash, is the failure mode | MEDIUM — the literal repo-scope cwd contract is satisfiable and stub-testable (AC-012); the open part is the operator-scope residual (A-002/OQ-002), already downgraded to a stated limitation | HIGH | 18% | APPROPRIATE — conditional on the OQ-002 marker spike resolving the limitation wording traceably (TRACKER RF-3) |
| F4 Deterministic assembly & report (FR-032–FR-042) | MEDIUM — the report is the product's face and the grounding rule's evidence surface (FR-039 line quoting) | LOW — pure local computation, fully assigned behavior, NFR-004 determinism makes it exhaustively unit-testable | MEDIUM | 18% | APPROPRIATE |
| F5 Test seam & unit tests (FR-043–FR-045) | MEDIUM — the test seam is what keeps the deterministic core verifiable and the v1 interface stable for later SUE tiers | LOW — conventions validated (A-008); pyproject already supports the test file with zero changes (journal 17). Sequencing risk only: test enumeration is blocked until ISS-201/ISS-202/ISS-203 rewordings land | MEDIUM | 18% | APPROPRIATE — but gate SENTINEL on the spec rewordings |
| F1 Command interface & pre-flight validation (FR-001–FR-007) | LOW — standard argparse + pre-flight checks with a direct repo precedent (`scripts/contradiction-scanner.py`) | LOW — every behavior assigned, confidence 1.0 in prioritization.md | LOW | 11% | APPROPRIATE — do not gold-plate; ceiling, not floor |
| F6 Manual live acceptance run (SC-001, AC-023) | MEDIUM — the only live validation of v1; a false FAIL burns trust in the tool | MEDIUM — model nondeterminism, already tolerance-bounded (≥1 of 3 issues, ≤3 attempts); spec-029 anchor drift (A-004) | MEDIUM | 7% | APPROPRIATE — cheap; the only action is re-verifying/freezing anchors immediately before the run |

No component is materially over- or under-invested in **effort** terms. This project's misalignment risk is **sequencing**, not allocation: the two CRITICAL/HIGH cells are cheap to de-risk (two spikes, hours) but catastrophic to skip, because HOW freezes the extraction contract and subprocess runner against unvalidated external-CLI assumptions.

## Effort Allocation Recommendations

### Under-Invested (increase effort)

- **Pre-HOW spikes (OQ-001, OQ-002)** — not a feature row, which is exactly the problem: they de-risk the two highest-risk cells (F3 extraction, F2 isolation) at near-zero cost. Treat them as mandatory gate work, not optional research. Fold the A-005 size measurement into OQ-001 (issues.md ISS-209) so context-fit stops being validated only "at acceptance".
- **Spec rewordings ISS-201/ISS-202/ISS-203** — three one-line WHAT amendments that currently block correct test enumeration (a literal AC-011 test asserts the wrong prompt block count). Minutes of CARTOGRAPHER effort protecting 18% of the build (F5).

### Over-Invested (reduce effort)

- **F1 Command interface** — standard argparse against a proven repo shape; implement the spec exactly, resist adding option validation or UX polish beyond FR-001–FR-007 (ISS-208 bounds are a WHAT clarification, not a build feature).
- **Speculative extraction robustness** — do not design extractor defenses against imagined noise before the OQ-001 spike returns observed stdout shapes; unit-test against captured fixtures, not invented ones (unknowns.md "output-noise channels").
- **GUARDIAN / BENCHMARK dispatches** — the trust boundaries are already documented (egress NFR-003, operator seam FR-043, prompt injection U-009 as stated limitation) and there is no performance dimension beyond NFR-001 timeout arithmetic. Skip or keep to a verification-only pass.

### Appropriate (maintain)

- **F3 / F2** — the 47% combined share matches where the risk lives, provided the spikes run first.
- **F4 / F5** — deterministic core plus its test surface; this is the maintainable heart of the tool and is fully enumerable once rewordings land.
- **F6** — tolerance already encoded; no further hedging needed.

## High-Blast-Radius Decisions

No ADRs exist yet (pre-HOW). The high-blast items are the contracts HOW is about to freeze.

| Decision | Blast Radius | Current Confidence | Recommendation |
|----------|--------------|-------------------|----------------|
| D-1 FR-026/FR-027 extraction contract (raw `claude -p` stdout shape, prompt delivery, output flags — OQ-001) | ~50% of tasks: extraction module, retry semantics, debug dump, stub replay fixtures, all round-ingestion tests | LOW (A-001 unvalidated; contrary prior art in repo) | **More research — run the OQ-001 spike before HOW**; also capture launch-failure shapes (U-007) and prompt sizes (A-005) in the same spike |
| D-2 FR-010 isolation mechanism & limitation wording (OQ-002) | ~15% of tasks: subprocess runner, AC-012 test, Limitations section, usage text | MEDIUM (repo-scope guaranteed; operator-scope residual open) | **More research — run the OQ-002 marker spike before HOW**; outcome is either suppression flags or final limitation wording, decided traceably |
| D-3 Single-source schema constants (verdict enum, category tokens, question-ID convention) shared by prompt text, validator, and stub fixtures | Silent-failure radius: a three-way contract edit missing one side green-tests wrong behavior (journal 16); category-token drift alone would burn the retry every run (ISS-206) | HIGH that the risk is real; LOW that it self-enforces | Proceed at HOW with one shared constants block inside the single-file script; make it an explicit review-gate item |
| D-4 Standalone contract (FR-045 — zero harness/echelon imports, zero orchestration reads) | Interface stability for all later SUE tiers plus the entire stub test seam | HIGH (explicit FRs + review gate planned) | Proceed; enforce via CODE REVIEWER/SPEC GUARD grep gate — the erosion pressure arrives mid-build, not at design time |

## Consequences Over Time

### D-1: Extraction contract frozen without the OQ-001 spike
- **T+0:** HOW freezes FR-026 against an assumed stdout shape; build proceeds normally, unit tests pass against invented fixtures.
- **T+3m:** First real runs hit systematic noise (progress lines, ANSI, update nags); with a 1-retry budget every run exits 3 — the tool is unusable and the failure looks like a model problem, not a design problem.
- **T+6m:** Extraction module redesigned against reality; stub fixtures and ingestion tests rewritten — the pessimistic estimate bound (0.60 pw) realized after shipping instead of before.
- **T+12m:** CLI version drift repeats the episode unless the spike also pinned CLI version and flags (unknowns.md "version drift").
- **Reversibility:** medium — MODELER's narrow-interface mitigation (journal 16) contains the rewrite to one module, but all fixtures churn.

### D-2: Isolation resolved silently instead of traceably
- **T+0:** Temp-cwd runner ships; AC-012 passes; nothing visibly wrong.
- **T+3m:** Reports carry silent operator-scope bias (user-level CLAUDE.md, MCP servers); findings quietly reflect ambient context — the grounding rule is violated invisibly.
- **T+6m:** An author disputes a finding, discovers the leak; trust in every prior report is retroactively damaged — worse than a documented limitation would have been.
- **T+12m:** Later SUE tiers (multi-reader consensus) inherit and amplify the bias.
- **Reversibility:** easy technically (add flags or wording), hard reputationally once biased reports circulated.

### D-4: Standalone contract eroded during build
- **T+0:** Borrowing the harness stream-json backend "because it already works" saves an hour mid-build.
- **T+3m:** The stub-executable test seam breaks (stubs can't replay through the backend); SC-002's zero-network test guarantee quietly weakens.
- **T+6m:** Script can no longer run from a fresh checkout without the harness venv — NFR-002 violated; the tool stops being a host tool.
- **T+12m:** Later SUE tiers must either inherit the coupling or fund a decoupling rewrite of their stable v1 interface.
- **Reversibility:** hard — coupling compounds; the grep gate at review is the cheap moment to stop it.

## Top Recommendations

1. **Redirect effort to: the two pre-HOW spikes (OQ-001 + OQ-002)** — hours of INVESTIGATOR work de-risk the CRITICAL extraction contract and the HIGH isolation contract before HOW freezes both; every downstream design decision with LOW confidence becomes evidence-backed.
2. **Investigate before proceeding: D-1 extraction contract** — highest blast radius (~50% of tasks), lowest confidence, and repo prior art actively contradicts the plain-JSON assumption. Do not let ARCHITECT freeze FR-026 design or SENTINEL write extraction fixtures before spike stdout captures exist.
3. **Simplify or defer: GUARDIAN/BENCHMARK passes and F1 polish** — the security surface is already documented as stated limitations, there is no performance dimension, and the command interface is a solved repo pattern; spend the saved attention on the ISS-201/202/203 rewordings that unblock correct test enumeration.

## Specialist Allocation Advice

| Specialist | Recommended Focus | Why |
|------------|-------------------|-----|
| speckit-echelon-investigator (INVESTIGATOR) | OQ-001 spike (raw stdout shape, prompt delivery, flags, CLI version pin, launch-failure shapes, A-005 size measurement) then OQ-002 marker spike | Both sit on the two highest blast-radius decisions with the lowest current confidence; everything downstream of HOW depends on their outputs |
| speckit-echelon-cartographer (CARTOGRAPHER) | Three one-line rewordings: ISS-201 (FR-021/AC-011 element counting), ISS-202 (out-of-range evidence line behavior), ISS-203 (AC-002 header-fact scoping) | Cheapest possible protection of the F5 test surface — literal tests against the current wording assert wrong counts |
| speckit-echelon-sentinel (SENTINEL) | Center round-2 validation tests on the ID bijection (missing/duplicate/unknown id), the verdict partition/ranking, and the exit-code state machine; block extraction fixtures until spike captures exist | These are the strongest machine-checkable invariants (journal 6, 13); testing them covers most of the deterministic core |
| speckit-echelon-guardian (GUARDIAN) | Verification-only: confirm the four stated limitations (egress, operator seam, prompt injection, residual context) appear in spec + usage text; no new threat model | Trust boundaries already mapped in risks.md/boundaries.md; v1's backstop is the human reviewer by design |
| speckit-echelon-code-reviewer (CODE REVIEWER) / speckit-echelon-spec-guard (SPEC GUARD) | FR-045 grep gate (zero `harness.*`/`echelon.*` imports, zero orchestration config reads) plus D-3 single-source constants check | The standalone contract and the three-way schema contract both fail silently and are one grep away from enforceable |
| speckit-echelon-benchmark (BENCHMARK) | Skip for v1 | NFR-001 is closed-form timeout arithmetic (≤ 4 budgets + 60 s); no capacity or scaling dimension exists in a single-operator manual tool |
