# Contradictions and Gaps

Sources cross-referenced:
- Source 1: `staging/glossary.md`, `staging/mental-model.md`, `staging/boundaries.md`, `staging/assumptions.md`, `staging/unknowns.md` (SCOUT discovery sweep)
- Source 2: design doc snapshot (normative input, IN-REQ-35B242FAD892 … IN-REQ-C68D7D0CB17E via `inputs/requirement-context.md`)
- Source 3: repo evidence (git history, `pyproject.toml`, `tests/unit/`, `scripts/contradiction-scanner.py`, `specs/029-builder-spec-workbench/`, `src/harness/llm_provider.py` prior art as recorded by SCOUT)
- Source 4: reasoning-journal.jsonl (DISCOVER entries 1–8)

## Contradictions

| Finding | Source A | Source B | Conflict Type | Severity | Route |
|---------|----------|----------|---------------|----------|-------|
| Isolation premise: design asserts "`claude -p` loads CLAUDE.md from cwd" and therefore a neutral temp cwd satisfies the isolation contract | design doc (IN-REQ-DDDD35B79FFA, IN-REQ-2F84DF72B209) | SCOUT evidence: user-scope context (`~/.claude/CLAUDE.md`, global settings, MCP servers) loads independently of cwd — cwd alone yields only partial isolation (assumptions.md A-002, unknowns.md U-002, journal entry 5, grade C) | CONTRADICTION (design premise vs external-tool behavior) | CRITICAL | WHY1 + INVESTIGATOR (marker-instruction spike) |
| Output contract: design demands "Output: strict JSON" from a plain `claude -p` call | design doc (IN-REQ-046E9F3A20C7) | Repo prior art: the only working subprocess `claude -p` integration (`src/harness/llm_provider.py` + `ai_cli_backend`) required stream-json and a dedicated backend layer to get parseable output (boundaries.md, journal entry 3, grade B) | CONTRADICTION (assumed vs demonstrated output shape) | HIGH | INVESTIGATOR (U-001 spike: one real call, inspect raw stdout) |
| Acceptance testability: success requires findings from a nondeterministic model to overlap three specific known issues in "one manual live run" | design doc (IN-REQ-760CA37F3F8F … IN-REQ-D05A70A0F5B4) | SCOUT analysis: a correct implementation can miss one of three issues on any given run — flaky-by-construction acceptance (unknowns.md "Model nondeterminism", journal entry 8) | CONTRADICTION (criterion vs mechanism determinism) | HIGH | WHY1 → CARTOGRAPHER (fix pass tolerance in the AC before the run) |
| Strictness vs extraction: design says output is "strict JSON" yet lists "JSON extraction" among the unit-tested deterministic parts, implying wrapped/noisy output is tolerated | design doc (IN-REQ-046E9F3A20C7) | design doc (IN-REQ-BE91B88E2D80); SCOUT encoded the tension as assumption A-009 | CONTRADICTION (internal design tension — byte-pure vs extract-from-wrapper) | MEDIUM | WHY1 → CARTOGRAPHER (define the extraction contract explicitly) |

## Gaps

| Gap | Present In | Missing From | Impact | Follow-up |
|-----|------------|--------------|--------|-----------|
| "Collapsed audit section" — the design specifies the ANSWERED-questions audit section is *collapsed* (IN-REQ-2D4902546481) | design doc line 44 | ALL DISCOVER outputs (glossary "Challenge report", mental-model "Challenge Report", boundaries "Report rendering" describe an audit appendix but drop the collapsed-rendering requirement) | Report-format FR could omit the collapse behavior (e.g. `<details>` block); silent spec drift from the approved design | CARTOGRAPHER: carry "collapsed" into the report-format FR or explicitly decide plain-heading rendering |
| Degenerate-outcome semantics: zero questions from round 1, zero findings ("clean spec"), report write failure — no exit codes or behavior assigned | unknowns.md U-005 (question raised) | design doc (defines only exits 0/1/2/3) | Unit tests cannot be enumerated; implementers guess edge semantics | CARTOGRAPHER: must-resolve-before-WHAT |
| `--claude-cmd` semantics: bare executable token vs shell-split command string | unknowns.md U-004 (question raised) | design doc (IN-REQ-D8FCFCDDC59E says only "binary/command") | Subprocess construction, exit-2 detection, and the pytest stub contract all depend on it | CARTOGRAPHER: must-resolve-before-WHAT |
| Corrective-retry content: whether the retry includes the model's bad output, and what happens on timeout where there is no output to correct | unknowns.md U-003 (question raised) | design doc (IN-REQ-5086BCDE7BCE says only "appended to the same prompt") | Prompt assembly and exit-3 determinism underspecified | CARTOGRAPHER / user decision |
| Line-number provenance for `lines` / `evidence_lines`: numbered spec text in prompt vs model-estimated numbers | unknowns.md U-006 (question raised) | design doc (schemas require ints, mechanism silent) | Evidentiary strength of "quote the answering lines" varies from verifiable to approximate | CARTOGRAPHER decision, optionally INVESTIGATOR spike |
| Exit-2 boundary: binary present but unauthenticated / crashing at startup — is that exit 2 (unavailable) or exit 3 (parse failure)? | unknowns.md U-007 (question raised) | design doc (IN-REQ-49464B14EFA0 covers only "not found") | ERR-CLI-MISSING mirror is incomplete; misclassified failures confuse operators | CARTOGRAPHER decision, INVESTIGATOR can characterize failure modes |
| Concurrency posture: simultaneous runs against the same spec dir interleave report/`.sue-debug/` writes | unknowns.md (potential unknown unknowns) | design doc (no locking, no non-goal statement) | Low practical risk for a manual tool, but implicit | CARTOGRAPHER: one-line non-goal/limitation note |

## Suspicious Findings

| Finding | Evidence | Why Suspicious | Follow-up |
|---------|----------|----------------|-----------|
| claude CLI behavior surface is wide and version-shifting | The repo's harness needed a dedicated backend layer (`ai_cli_backend`) plus tool-policy handling to tame the same CLI (boundaries.md, journal entry 3) | SUE binds to `-p` semantics, context-loading rules, and output shape of an externally versioned tool with no pinning mechanism | INVESTIGATOR: record CLI version + flags the spike validated against, so drift is detectable |
| Acceptance target `specs/029-builder-spec-workbench/spec.md` is a live, active spec | Anchors verified present at base commit ef2643c9 (assumptions.md A-004, journal entry 2, grade A); spec 029 is status-active in prior-spec context | The acceptance criterion depends on known defects *remaining* in an active spec; any 029 amendment before the acceptance run invalidates the criterion | Re-check 029 immediately before acceptance; freeze the current version as a fixture if amended |
| Single corrective retry budget vs systematic output noise | unknowns.md "Output-noise channels"; A-009 | If noise (progress lines, update nags, ANSI) is systematic rather than transient, one retry converts a formatting nuisance into a hard exit 3 every run | INVESTIGATOR spike captures raw stdout in several environments; SENTINEL tests extraction against noisy fixtures |

## Emergent Patterns

| Pattern | Sources | Implication |
|---------|---------|-------------|
| The entire deterministic test surface reduces to three machine-checkable rules: round-2 ID bijection, verdict filter/ranking, and the exit-code state machine | mental-model.md (relationships, behavioral patterns); journal entry 6; design schemas (IN-REQ-D003F04C0FC3, IN-REQ-97C434377BBE, IN-REQ-E8F14EBD27A7) | CARTOGRAPHER should express each as an explicit FR (not schema prose); SENTINEL should center unit tests on bijection violations, verdict partitioning, and the exit matrix |
| Every unresolved unknown (U-001…U-007) lands in exactly two internal boundaries: prompt assembly and the subprocess runner | unknowns.md × boundaries.md cross-reference | ARCHITECT should isolate those two seams behind narrow interfaces so late decisions don't ripple; the rest of the script is decision-stable now |
| The repo now hosts two spec-assessment tools with overlapping vocabulary: `understanding` (deterministic, 34 metrics) and SUE (dialogic, model-driven) — plus overloaded terms (finding, challenge, question, timeout) | glossary.md (disambiguations + overloaded-terms table); CLAUDE.md | Spec and report wording must disambiguate consistently; docs should position SUE relative to `understanding` to prevent operator confusion |
| Standalone-script precedent is strong and consistent: `scripts/contradiction-scanner.py` (stdlib-only, argparse, own exit codes, documented usage header) matches SUE's target shape exactly | assumptions.md A-003; repo evidence (scanner header verified); journal entry 4 (grade A) | Conventions need no invention — CARTOGRAPHER/ARCHITECT can cite the scanner as the canonical shape; review gate: no `harness.*`/`echelon.*` imports |
