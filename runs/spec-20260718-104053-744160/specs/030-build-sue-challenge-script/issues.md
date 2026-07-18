# Issues — WHY1

## Summary
- **CRITICAL:** 0
- **HIGH:** 3
- **MEDIUM:** 4
- **LOW:** 3
- **Verdict:** PASS

Blocking analysis for the 3 HIGH issues (Blocking Rule 2): ISS-001 and ISS-002 share one root cause — unvalidated premises about external claude-CLI behavior — and both already carry concrete pre-HOW investigation plans (U-001/U-002 spikes). ISS-003 is independent and resolvable by a single AC decision at WHAT. None blocks WHAT from starting, and the discovery foundation itself accurately encodes all three rather than hiding them. They do not compound into a systemic problem, so this is PASS with warnings, not FAIL. If any of these arrive at WHY2 unaddressed in the spec, they escalate per the iteration-awareness rule.

## Issues

### ISS-001: Isolation contract premise is incomplete — user-scope claude context loads independently of cwd
- **Severity:** HIGH
- **Type:** contradiction
- **Description:** The design premises the isolation contract on cwd alone ("`claude -p` loads CLAUDE.md from cwd", IN-REQ-DDDD35B79FFA), but user-scope context (`~/.claude/CLAUDE.md`, global settings, MCP servers) loads regardless of cwd. Temp cwd guarantees repo-scope isolation only; the blind-reader intent behind the contract is not fully satisfiable by the designed mechanism. Failure mode is silent bias, not a crash. Rated CRITICAL by SYNTHESIZER/MODELER as a design contradiction; rated HIGH at this gate because it is fully encoded in the artifacts (A-002, U-002, V-1), has an investigation plan, and gates the HOW-phase subprocess-runner design rather than WHAT.
- **Affected artifact:** assumptions.md (A-002), boundaries.md (Trust Boundaries), design doc IN-REQ-DDDD35B79FFA
- **Affected section:** Isolation contract / Context isolation boundary
- **Evidence:** contradictions-and-gaps.md contradiction 1; reasoning-journal entry 5 (grade C, 0.75); MODELER alert V-1 ("the isolation invariant as designed is unsatisfiable")
- **Recommendation:** INVESTIGATOR runs the U-002 marker-instruction spike before HOW. CARTOGRAPHER writes the isolation FR as a testable outcome — repo-scope isolation guaranteed via temp cwd — plus either CLI suppression flags (if the spike finds them) or an explicitly documented user-scope residual limitation. Any deviation from the design's wording must be traceable (TRACKER RF-3), not silent.
- **Responsible agent:** WHAT (with INVESTIGATOR pre-work before HOW)

### ISS-002: Output contract is unproven — plain `claude -p` strict-JSON premise contradicted by repo prior art and by the design's own extraction step
- **Severity:** HIGH
- **Type:** contradiction
- **Description:** The design demands strict JSON from a bare `claude -p` call, but the repo's only working subprocess integration needed stream-json plus a dedicated backend layer to get parseable output; simultaneously the design lists "JSON extraction" among unit-tested parts, conceding output is not byte-pure. With a one-retry budget, systematically noisy output converts to exit 3 on every run — the tool would be unusable and acceptance would fail.
- **Affected artifact:** assumptions.md (A-001, A-009), boundaries.md (claude CLI external boundary)
- **Affected section:** Model invocation / JSON extraction & validation
- **Evidence:** contradictions-and-gaps.md contradictions 2 and 4; `src/harness/llm_provider.py` + `ai_cli_backend` prior art (journal entry 3, grade B); MODELER alert V-2
- **Recommendation:** INVESTIGATOR runs the U-001 spike (one real call; capture raw stdout, CLI version, flags; record spec/prompt sizes for A-005; observe launch-failure shapes for U-007) before ARCHITECT freezes the extraction design. CARTOGRAPHER defines the extraction contract explicitly in the spec: what wrapping/noise is tolerated, what constitutes a parse failure.
- **Responsible agent:** WHAT (with INVESTIGATOR pre-work before HOW)

### ISS-003: Acceptance criterion is flaky by construction — one live run must rediscover three model-found issues
- **Severity:** HIGH
- **Type:** untestability
- **Description:** Acceptance requires findings from a nondeterministic model to overlap three specific known issues in spec 029 in "one manual live run". A correct implementation can miss one of three on any given run, producing a false FAIL or inviting post-hoc goalpost moving at FINALIZE. Additionally the target spec (029) is active and may drift before the run (A-004 mitigations exist).
- **Affected artifact:** assumptions.md (A-004), unknowns.md (Potential Unknown Unknowns — model nondeterminism), design doc IN-REQ-760CA37F3F8F…D05A70A0F5B4
- **Affected section:** Acceptance run
- **Evidence:** contradictions-and-gaps.md contradiction 3; reasoning-journal entry 8; TRACKER RF-4 ("acceptance-criterion tolerance must be an explicit clarification decision")
- **Recommendation:** CARTOGRAPHER encodes an explicit pass tolerance in the AC during WHAT — e.g. overlap with ≥1 of the 3 named issues on a single run, or up to K bounded reruns — as a traceable clarification decision, before any acceptance run happens. Re-verify/freeze spec 029 anchors immediately before the run.
- **Responsible agent:** WHAT

### ISS-004: `--claude-cmd` semantics undecided (single executable token vs shell-split command string)
- **Severity:** MEDIUM
- **Type:** ambiguity
- **Description:** U-004 is marked must-resolve-before-WHAT and gates subprocess construction, exit-2 detection, and the pytest stub-fixture design. "binary/command" (IN-REQ-D8FCFCDDC59E) supports both readings.
- **Affected artifact:** unknowns.md (U-004)
- **Affected section:** Known Unknowns
- **Evidence:** journal entry 7 ("two interface semantics are unresolved and gate FR writing")
- **Recommendation:** CARTOGRAPHER decides at WHAT entry and states the decision in the FR (recommend shlex-split command string: it subsumes the bare-token case and keeps the test seam trivial — but the decision, not the recommendation, is what matters).
- **Responsible agent:** WHAT

### ISS-005: Degenerate-outcome semantics undefined (zero questions, zero findings, unwritable report, over-cap output)
- **Severity:** MEDIUM
- **Type:** incompleteness
- **Description:** U-005 (must-resolve-before-WHAT) plus new U-008: exit codes exist for 0/1/2/3 but not for an empty round-1 question list, the all-ANSWERED "clean spec" case, a report write failure, model output exceeding the N cap, or duplicate round-1 ids. Unit tests cannot be enumerated until these are pinned.
- **Affected artifact:** unknowns.md (U-005, U-008), assumptions.md (A-006)
- **Affected section:** Known Unknowns
- **Evidence:** qa-test-strategy-inputs.md marks degenerate-outcome tests "Blocked on CARTOGRAPHER decision"
- **Recommendation:** CARTOGRAPHER assigns explicit behavior to each degenerate outcome in the FRs; SENTINEL then derives one unit test per assigned behavior.
- **Responsible agent:** WHAT

### ISS-006: Collapsed audit-section rendering dropped from base domain artifacts
- **Severity:** MEDIUM
- **Type:** incompleteness
- **Description:** The design requires the ANSWERED-questions audit section rendered *collapsed* (IN-REQ-2D4902546481). SYNTHESIZER caught the drop (gap 1) and TRACKER flagged it (RF-1), but the staging glossary.md and mental-model.md report definitions still omit it. This is exactly the fidelity-drift failure mode the user's "exactly as designed" instruction guards against — details lost from working artifacts tend to be lost from the spec.
- **Affected artifact:** glossary.md (Challenge report), mental-model.md (Challenge Report)
- **Affected section:** Report definition entries
- **Evidence:** contradictions-and-gaps.md gap 1; user-intent.md UI-009 (which preserves it)
- **Recommendation:** CARTOGRAPHER sources the report-format FR from the design doc IN-REQ units directly and includes the collapsed rendering; patch glossary.md/mental-model.md report definitions when next touched.
- **Responsible agent:** WHAT

### ISS-007: Line-number evidentiary basis undecided — the grounding rule's weakest joint
- **Severity:** MEDIUM
- **Type:** ambiguity
- **Description:** U-006: whether the prompt presents the spec with explicit line numbers (citations verifiable) or the model estimates them (citations approximate) determines how much trust the report's "evidence" deserves. Since the whole product promise is grounded findings, unverifiable line citations would quietly undermine it.
- **Affected artifact:** unknowns.md (U-006)
- **Affected section:** Known Unknowns
- **Evidence:** glossary.md Verdict definition ("answering lines quoted"); mental-model.md Challenged Spec attributes
- **Recommendation:** CARTOGRAPHER decides at WHAT (recommend numbering the spec text in the prompt — it makes `lines`/`evidence_lines` mechanically checkable and strengthens the report); if left model-estimated, the report format must label evidence as approximate.
- **Responsible agent:** WHAT

### ISS-008: mental-model.md asserts atomic report writes the design never specified
- **Severity:** LOW
- **Type:** inconsistency
- **Description:** "written atomically at the end of a successful run" (Challenge Report lifecycle) is an embellishment with no IN-REQ basis; it could mislead SENTINEL into testing undecided behavior (new U-010).
- **Affected artifact:** mental-model.md
- **Affected section:** Challenge Report — Lifecycle
- **Evidence:** No atomicity requirement appears in any IN-REQ unit or design section cited across the artifacts.
- **Recommendation:** CARTOGRAPHER either specifies write semantics in the FR or drops the atomicity claim from the model.
- **Responsible agent:** WHAT

### ISS-009: Prompt-injection resilience of challenged spec content is unexamined
- **Severity:** LOW
- **Type:** incompleteness
- **Description:** New U-009: spec text is embedded verbatim in both prompts; adversarial instructions inside a challenged spec could steer questions or verdicts. Acceptable for a v1 developer tool, but it should be a stated limitation next to the existing egress note, not a silence.
- **Affected artifact:** boundaries.md (Trust Boundaries), risks.md
- **Affected section:** Trust boundaries
- **Evidence:** Trust-boundary section covers model-output trust, egress, and --claude-cmd execution, but not spec-content-as-prompt-input.
- **Recommendation:** CARTOGRAPHER adds a one-line limitation to the spec ("findings for specs containing adversarial instructions are unreliable; the human decides" backstop).
- **Responsible agent:** WHAT

### ISS-010: A-005 (context fit) validation is deferred to the acceptance run — too late to influence design
- **Severity:** LOW
- **Type:** incompleteness
- **Description:** The only validation planned for a CRITICAL assumption is post-build observation, and its size basis is an informal "a few hundred lines" estimate with no measurement command. A silent-truncation failure would not be reliably observable even then.
- **Affected artifact:** assumptions.md (A-005)
- **Affected section:** Critical Assumptions
- **Evidence:** A-005 validation method: "Acceptance run observation"
- **Recommendation:** Fold size measurement (chars/tokens of spec 029 + both prompt templates) into the U-001 spike at near-zero cost.
- **Responsible agent:** WHAT (spike scoping)

## Pre-Mortem Findings

| Risk | Likelihood | Impact | Affected Requirements |
|------|-----------|--------|----------------------|
| Plain `claude -p` stdout is never clean strict JSON in some environments; single retry makes noise fatal | HIGH | Tool unusable (exit 3 loop); acceptance fails | IN-REQ-046E9F3A20C7, IN-REQ-BE91B88E2D80, IN-REQ-5086BCDE7BCE |
| User-scope context silently biases both rounds despite temp cwd | MEDIUM | Grounding rule violated with no signal | IN-REQ-2F84DF72B209, IN-REQ-DDDD35B79FFA |
| Model-estimated line citations are approximate/fabricated | MEDIUM | Report evidence misleads the deciding human | IN-REQ-EED398D6F6E8 (quoted lines), U-006 |
| Acceptance run misses 1 of 3 named issues | MEDIUM | False FAIL or goalpost moving at FINALIZE | IN-REQ-760CA37F3F8F…D05A70A0F5B4 |
| Unauthenticated CLI lands in exit-3 path instead of exit 2 | MEDIUM | ERR-CLI-MISSING mirror breaks for first-time users | IN-REQ-49464B14EFA0, IN-REQ-CE9317854005, U-007 |

## Cross-Artifact Consistency

| Check | Status | Notes |
|-------|--------|-------|
| Entities in spec match mental-model | N/A | WHY1 — no spec.md exists yet; checked mental-model.md vs mental-model-code.md instead: consistent (PLANNED entities align with design IN-REQ units) |
| Dependencies in spec match boundaries | N/A | WHY1 — checked boundaries.md vs mental-model.md instead: all external deps (claude CLI, fs read/write, temp dir, pytest) present in both; no cycles |
| Terms match glossary | PASS | All terms used in mental-model.md/boundaries.md are defined; overloaded-terms table disambiguates 7 collision-prone terms with context rules |
| Scope aligns with boundaries | PASS | Non-goals (no harness import, no echelon verb, no workflow integration) consistently stated as an explicit NON-boundary |
| Assumptions match assumptions.md | PASS | A-001…A-012 consistently referenced from unknowns.md, boundaries.md, and journal; statuses coherent (A-004/A-008 validated, rest unvalidated) |
| Open questions reference unknowns.md | PASS | U-001…U-007 cross-linked to assumptions; contradictions-and-gaps.md routes each; WHY1 adds U-008/U-009/U-010 |
