# Assumption Review — WHY1

## Verdict: PASS

## Summary
The DISCOVER foundation is internally consistent and unusually honest: it surfaced its own load-bearing contradictions (isolation premise, output contract, acceptance flakiness) rather than hiding them, and every CRITICAL assumption is either validated with cited evidence or explicitly routed to an INVESTIGATOR spike. Three HIGH issues exist but do not compound into a systemic foundation defect — each has a concrete owner and a resolution path that does not require re-discovery. WHAT may proceed, conditional on CARTOGRAPHER resolving U-004/U-005 as explicit spec decisions and carrying the collapsed-audit rendering (IN-REQ-2D4902546481) into the spec.

## Assumption Analysis

### A-001: `claude -p` can be driven non-interactively with plain-text-out, prompt-in semantics
- **DISCOVER's classification:** Critical
- **WHY's classification:** Critical (agree)
- **Evidence strength:** moderate — but the strongest available evidence cuts *against* the premise: the repo's only working subprocess `claude -p` integration (`src/harness/llm_provider.py` + `ai_cli_backend`) needed stream-json plus a dedicated backend layer to obtain parseable output, while the design assumes plain strict JSON from a bare call.
- **Contradictions found:** SYNTHESIZER contradiction 2 (assumed vs demonstrated output shape); internal tension with A-009 ("strict JSON" demanded yet an extraction step is unit-tested — SYNTHESIZER contradiction 4).
- **Verdict:** needs-investigation
- **Action required:** SCIENTIST investigation — U-001 spike (one real call from a temp cwd; capture raw stdout across environments; record CLI version and flags) before ARCHITECT freezes the subprocess runner and extraction design. CARTOGRAPHER must define the extraction contract explicitly in the spec (see ISS-002).

### A-002: Neutral temp cwd is sufficient to keep repo context out of the model's reading
- **DISCOVER's classification:** Critical
- **WHY's classification:** Critical (agree)
- **Evidence strength:** weak — the sole basis is the design doc's own assertion (IN-REQ-DDDD35B79FFA); counter-evidence exists that user-scope context (`~/.claude/CLAUDE.md`, global settings, MCP servers) loads independently of cwd.
- **Contradictions found:** SYNTHESIZER contradiction 1 (design premise vs external-tool behavior), rated CRITICAL by SYNTHESIZER and MODELER (alert V-1: "the isolation invariant as designed is unsatisfiable").
- **Verdict:** needs-investigation
- **Action required:** SCIENTIST investigation — U-002 marker-instruction spike before HOW. Severity reasoning for the WHY1 gate: the design's *literal* contract is repo-scope isolation ("so repo CLAUDE.md context cannot leak", glossary Isolation contract), which temp cwd does satisfy; the unsatisfiable part is the broader blind-reader *intent* against user-scope context. That gap blocks the HOW-phase freeze of the subprocess runner, not WHAT. CARTOGRAPHER must write the isolation FR as an outcome (repo-scope guaranteed) plus either suppression flags or a documented user-scope residual limitation, traceably (TRACKER RF-3) — see ISS-001. This is why the finding is HIGH at this gate rather than CRITICAL: it is fully encoded, routed, and does not invalidate the foundation WHAT builds on.

### A-003: Standalone means standalone — no dependency on `src/harness` or echelon config
- **DISCOVER's classification:** Critical
- **WHY's classification:** Critical (agree)
- **Evidence strength:** strong — design scope + non-goals (IN-REQ-8E578B6660BB, IN-REQ-D9CE68110258), and repo precedent `scripts/contradiction-scanner.py` establishes the exact shape; CLAUDE.md documents `scripts/` as non-deployed host tooling.
- **Contradictions found:** none
- **Verdict:** validated (design-time; the residual is an enforcement gate, not an open question)
- **Action required:** none now — enforce at CODE REVIEWER gate (no `harness.*`/`echelon.*`/`codegen.*` imports; unit tests run without the installed venv).

### A-004: The spec 029 acceptance target retains its known issues
- **DISCOVER's classification:** Critical
- **WHY's classification:** Critical (agree)
- **Evidence strength:** strong — grep-verified anchors at base commit ef2643c9 (REQ-009 line 61, AC-010 lines 74/257, active-run pointer lines 13–16/218), journal entry 2, grade A.
- **Contradictions found:** none — but a live drift risk: spec 029 sits in the repo's most actively changed area (timeline.md velocity data).
- **Verdict:** validated
- **Action required:** none now; re-verify immediately before the acceptance run and freeze a fixture copy if 029 was amended (mitigation already recorded in risks.md).

### A-005: Both rounds fit within model context limits for realistic specs
- **DISCOVER's classification:** Critical
- **WHY's classification:** Critical (agree — a wrong A-005 produces *silent* truncation: answers citing lines the model never saw, which directly breaks the grounding rule and is not reliably detectable after the fact)
- **Evidence strength:** weak-to-moderate — analogy to harness behavior plus an informal "a few hundred lines" size estimate with no measurement.
- **Contradictions found:** none
- **Verdict:** needs-investigation
- **Action required:** fold into the U-001 spike at near-zero cost: record the actual character/token size of spec 029 plus both prompt templates during the spike, rather than deferring validation to the acceptance run (the currently proposed validation point, which is too late to influence design).

### A-006: Report co-location is writable
- **DISCOVER's classification:** Standard
- **WHY's classification:** Standard (agree)
- **Evidence strength:** moderate (normal developer workflow)
- **Contradictions found:** none, but the design assigns no exit code to a write failure — coupled to U-005.
- **Verdict:** needs-investigation (spec decision, not experiment)
- **Action required:** CARTOGRAPHER pins write-failure semantics at WHAT (ISS-005).

### A-007: Timeout is per subprocess invocation
- **DISCOVER's classification:** Standard
- **WHY's classification:** Standard (agree)
- **Evidence strength:** moderate ("per-call timeout" wording, IN-REQ-F124765D491A)
- **Contradictions found:** none; the retry-budget interaction is open in U-003 (a timeout has no output to "correct" — what does the corrective retry contain then?).
- **Verdict:** needs-investigation (spec decision)
- **Action required:** CARTOGRAPHER resolves U-003 alongside the retry-prompt definition.

### A-008: Unit tests follow repo pytest conventions
- **DISCOVER's classification:** Standard
- **WHY's classification:** Standard (agree)
- **Evidence strength:** strong — `pyproject.toml` pytest config and `tests/unit/conftest.py` fixture pattern verified (journal entry 4, grade A).
- **Contradictions found:** none
- **Verdict:** validated
- **Action required:** none (stub-fixture placement depends on the U-004 decision, tracked there).

### A-009: "Strict JSON" tolerates extraction
- **DISCOVER's classification:** Standard
- **WHY's classification:** Standard, but it is the visible half of the HIGH output-contract issue (ISS-002) — the design simultaneously demands strict JSON and unit-tests an extraction step.
- **Evidence strength:** moderate (both halves are in the design itself)
- **Contradictions found:** internal design tension (SYNTHESIZER contradiction 4, MEDIUM).
- **Verdict:** needs-investigation
- **Action required:** CARTOGRAPHER defines the extraction contract explicitly (what wrappers/noise are tolerated, what constitutes a parse failure), informed by U-001 spike evidence.

### A-010 / A-011 / A-012 (low-risk set)
- **DISCOVER's classification:** Low-Risk
- **WHY's classification:** Low-Risk (agree)
- **Evidence strength:** moderate (conventions and design-silence readings)
- **Contradictions found:** none
- **Verdict:** validated (as working defaults)
- **Action required:** one nuance — A-010's report-ordering default ("round-1 order within each verdict class") should be *stated* in the spec rather than left as an assumption, since deterministic ordering is what makes the report renderer unit-testable.

## Domain Model Issues

| ID | Finding | Severity | Affected Artifact | Section |
|----|---------|----------|-------------------|---------|
| DM-01 | "Collapsed" audit-section rendering (IN-REQ-2D4902546481) is absent from the Challenge Report definitions in glossary.md and mental-model.md; it survives only in mental-model-code.md and user-intent.md (UI-009). Fidelity-drift risk flagged by TRACKER RF-1 — "exactly as designed" cuts both ways. | MEDIUM | glossary.md, mental-model.md | Challenge report / Challenge Report entity |
| DM-02 | mental-model.md states the report is "written atomically at the end of a successful run" — the design does not specify atomic write semantics; this is an unverified embellishment that could mislead SENTINEL into testing behavior nobody decided. | LOW | mental-model.md | Challenge Report — Lifecycle |
| DM-03 | Round-1 schema validation as modeled (id, question, target, lines, category) contains no check that the model respected the `--questions` N cap, and round-1 id *uniqueness* is only implied (bijection is defined against round 2). Over-cap or duplicate-id round-1 output has undefined handling. | MEDIUM | mental-model.md, boundaries.md | JSON extraction & validation |
| DM-04 | Glossary completeness otherwise verified: all terms used across mental-model.md and boundaries.md (deterministic assembly, isolation contract, verdict, finding, debug dump, test seam, corrective retry, ID bijection, challenged spec, acceptance run) are defined, and the overloaded-terms table disambiguates spec/question/timeout/round/finding/challenge with context rules. No circular boundary dependencies. | — (pass) | glossary.md | Overloaded Terms |

## Pre-Mortem Findings

| Risk Area | Most Likely Failure | Confidence | Mitigation |
|-----------|-------------------|------------|------------|
| Output shape of plain `claude -p` | Stdout is never clean strict JSON in some environments (noise, wrappers, version drift); single-retry budget converts systematic noise into exit 3 on every run — tool unusable, acceptance fails | 0.75 | U-001 spike before HOW; extractor designed against *observed* noise; noisy-output unit fixtures (already in qa-test-strategy-inputs.md) |
| Isolation completeness | User-scope claude context biases both rounds despite temp cwd; no crash, no signal — grounding rule silently violated | 0.7 | U-002 marker spike; isolation FR written as outcome + documented residual or suppression flags |
| Line-number evidence | Model-estimated `lines`/`evidence_lines` are approximate or fabricated; report "evidence" misleads the human who is supposed to decide — the grounding rule's weakest joint | 0.6 | CARTOGRAPHER decides U-006 at WHAT (numbered spec text in prompt makes citations verifiable; unnumbered makes them estimates and the report must say so) |
| Acceptance criterion | A correct implementation misses 1 of 3 named spec-029 issues in the single live run; result is either a false FAIL or ad-hoc goalpost moving at FINALIZE | 0.6 | CARTOGRAPHER encodes explicit tolerance in the AC before any run (ISS-003) |
| Exit-code mapping | An installed-but-unauthenticated claude CLI produces garbage/empty output and lands in exit 3 ("parse failure") instead of an operator-actionable exit 2 — ERR-CLI-MISSING mirror breaks exactly when a new user first runs the tool | 0.55 | Resolve U-007 (fold observation into U-001 spike; CARTOGRAPHER assigns the mapping deliberately) |

## SCIENTIST Referrals

| Unknown | Question for SCIENTIST | Priority | Justification |
|---------|----------------------|----------|---------------|
| U-001 | Invoke the real `claude -p` once from a neutral temp cwd with the intended flags: how is the prompt delivered (argv/stdin), what does raw stdout look like, which CLI version/flags were used? Also record prompt+spec sizes (feeds A-005) and startup-failure behavior (feeds U-007). | must-resolve-before-HOW | Decides the JSON-extraction design, the stub replay contract, and whether the plain-call premise (A-001) holds; the only repo prior art contradicts it |
| U-002 | With a marker instruction planted in user-scope config (`~/.claude/CLAUDE.md`), does a temp-cwd `claude -p` call show marker influence? Are there flags to suppress user-scope context? | must-resolve-before-HOW | Determines whether the isolation FR can promise more than repo-scope isolation; MODELER V-1 blocks the subprocess-runner freeze on this |
| U-007 | (Fold into U-001 spike observation) How do "binary missing", "binary present but unauthenticated", and "crash at startup" each manifest — exit code, stderr, stdout? | should-resolve-before-HOW | The exit-2 vs exit-3 mapping must be deliberate for the ERR-CLI-MISSING mirror to hold |

U-003, U-004, U-005, U-006 are **spec decisions**, not experiments — they route to CARTOGRAPHER at WHAT (U-004 and U-005 gate FR writing; DISCOVER already marked them must-resolve-before-WHAT).

## Missing Unknowns

- **U-008 (new): Over-cap and malformed round-1 output handling.** The N cap (`--questions`) is an instruction to the model, not a validated constraint: what happens when round 1 returns more than N questions, zero questions with a syntactically valid empty list (overlaps U-005), or duplicate ids within round 1 itself? Each is currently neither a defined schema violation nor a defined success. Owner: CARTOGRAPHER (spec decision).
- **U-009 (new): Prompt-injection resilience of the challenged spec.** The spec text is embedded verbatim in both prompts; a spec containing adversarial instructions (e.g. "answer ANSWERED to every question") can steer verdicts. For a v1 developer tool a one-line documented limitation suffices ("the human decides" is the backstop), but it should be a *stated* limitation, not an unexamined silence. Owner: CARTOGRAPHER (limitations section).
- **U-010 (new): Report write semantics.** "Overwrite" is specified but write mechanics (atomic replace vs in-place truncate-write) are not — mental-model.md currently asserts atomicity the design never granted (DM-02). Owner: CARTOGRAPHER — either specify or explicitly leave unspecified and drop the claim from the model.
