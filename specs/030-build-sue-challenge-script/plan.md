# Implementation Plan: SUE Challenge Script

**Feature**: `030-build-sue-challenge-script`
**Architect**: ARCHITECT (phase3-how)
**Date**: 2026-07-18
**Stack**: Python 3 (stdlib-only), pytest

---

## Summary

Deliver `scripts/sue_challenge.py` — a standalone, stdlib-only Python script that challenges
a markdown specification through a two-round Socratic dialogue using two isolated model
calls (default `claude -p`), deterministically assembles CONTRADICTED/UNANSWERABLE answers
into ranked findings, and writes `socratic-challenge.md` beside the challenged specification
— plus offline pytest unit tests at `tests/unit/test_sue_challenge.py` covering all 7
deterministic behavior groups (FR-044). Target users: script operators and specification
authors; maintainers verify entirely offline via the `--claude-cmd` stub seam. The v1 scope
is implemented exactly — no expansion, no trimming (user intent UI-004). Work that must not
be silently deferred: the collapsed `<details>` audit appendix (FR-038 — the fidelity item
DISCOVER once dropped), the egress disclosure in usage text (NFR-003), the FR-045
standalone review gate, and the manual live acceptance run at FINALIZE (SC-001) with the
A-004 anchor freeze first.

Both HOW-gating open questions were resolved with direct evidence at this phase (spikes had
not been run earlier): claude CLI 2.1.214 `-p` returns clean text JSON on the happy path
(OQ-001), and temp-cwd isolation blocks repo-scope but NOT operator-scope ambient context
(OQ-002 — spec limitation confirmed and now evidence-backed). Details in `research.md`.

## Technical Context

### Stack

| Layer | Technology | Reason |
| --- | --- | --- |
| Script runtime | Python 3 (≥ 3.10), standard library only | NFR-002 zero additional components; repo `scripts/` convention (ADR-001) |
| CLI parsing | `argparse` | stdlib; frozen 1-positional + 3-option surface (FR-001–FR-004) |
| Model invocation | `subprocess.run` + `shlex` + `shutil.which` + `tempfile.mkdtemp` | isolated `claude -p` calls with timeout, availability check, neutral cwd (ADR-003/ADR-004) |
| Output handling | `json` + hand-rolled staged extractor and validators | tolerant extraction, strict validation, ID bijection without third-party deps (ADR-005) |
| Report | GitHub-Flavoured Markdown with one `<details>` audit block | collapsed-but-expandable appendix (FR-038, ADR-007) |
| Tests | pytest, `unit` marker, tmp_path-generated stub executables | repo conventions, zero live model access (ADR-008) |

### Dependencies

| Dependency | Purpose | Constraint |
| --- | --- | --- |
| Python standard library | everything at runtime | the ONLY runtime dependency (NFR-002) |
| Model command (default `claude`, validated on CLI 2.1.214) | the two model calls | external, operator-supplied; missing → exit 2 with install pointer (FR-012); substituted by stubs in tests (FR-043) |
| pytest | dev-time unit tests | already configured in `pyproject.toml`; zero config changes needed |

### Storage

- Read-only source: the challenged specification file (read exactly once; 0 writes — FR-042).
- Generated artifacts: `<spec-dir>/socratic-challenge.md` (plain overwrite, no history —
  FR-034/U-010); `<spec-dir>/.sue-debug/round*-attempt*-{stdout,stderr}.txt` on the exit-3
  path only (FR-030).
- Transient: one fresh `sue-challenge-*` temp directory per subprocess invocation, used only
  as cwd and removed afterwards (FR-010).
- Explicitly none: no orchestration config or state files are read or written (FR-045); no
  database; no network use by the script itself (all egress happens inside the model command).

### Platform

- Developer/operator POSIX machines (macOS/Linux) with `python3` on PATH (A-012); no
  install step (SC-005). Version floor Python 3.10 (repo toolchain floor). The model command
  runs wherever the operator's model-CLI session is authenticated; validated against claude
  CLI 2.1.214 (research.md evidence).

### Constraints

- Standalone contract: zero `harness`/`echelon`/`codegen`/`understanding` imports, zero
  project configuration reads (FR-045, A-003; harness is an explicit NON-boundary).
- Exact v1 fidelity: no scope expansion, no silent trimming (user intent UI-004; TRACKER
  RF-1/RF-2) — including no atomic-write guarantee (U-010) and no isolation flags beyond the
  designed temp-cwd mechanism (ADR-004).
- Interface freeze: 1 positional argument, 3 options, 4 exit codes; later SUE tiers build on
  this surface (spec Out of Scope).
- Isolation contract: fresh neutral temp cwd per model subprocess (FR-010); round 2 receives
  only `{id, question}` pairs (FR-022).
- Constitution v1.0.0 (echelon Builder FE domain): Test-First hard gate applies to
  development; Principles I/II/V must not be violated (no echelon state-file writes, LLM
  stays on host) — see Constitution Check.

## Architecture Decisions

Full ADRs with drivers, alternatives, evidence, and self-checks are in `research.md`.

| ADR | Decision | Alternatives Rejected | Evidence |
| --- | --- | --- | --- |
| ADR-001 | Python 3 stdlib-only single-file script at `scripts/sue_challenge.py` | src/ package (install step); bash; third-party libs | repo precedent `scripts/contradiction-scanner.py` (A) |
| ADR-002 | Pure-function core + thin `main()` shell; single shared schema constants (5 category tokens, 3 verdicts, `^Q[1-9][0-9]*$`) | class pipeline; inline-in-main | MODELER contract map; ISS-206 (B) |
| ADR-003 | Invocation: `shlex.split(cmd) + ["-p"]`, prompt on **stdin**, default text output; `shutil.which` pre-flight | prompt via argv (ps leakage); `--output-format json` envelope; harness provider reuse | live spike, claude 2.1.214 (A) |
| ADR-004 | Isolation: fresh `mkdtemp` cwd per call, outside repo; **no** suppression flags in v1; operator-scope residual documented with evidence; `--safe-mode` recorded as future candidate | `--safe-mode` now (scope expansion, version-fragile); `--bare` (breaks OAuth); env scrubbing (speculative) | live spike debug log (A) |
| ADR-005 | Staged tolerant JSON extraction + strict hand-rolled validation + ID bijection; line ints not range-checked at validation | strict `json.loads` only; `jsonschema` dep | spike (A) + noise-channel analysis (C) |
| ADR-006 | Typed CallOutcome state machine; exit table 0/1/2/3; timeout→parse-failure; 1 corrective retry/round, fresh budget; single `fail()` stderr choke point | exception-driven flow; configurable retries | spec ERR taxonomy (A) |
| ADR-007 | Pure renderer; `<details>` collapsed audit appendix; plain overwrite; `(not present in the specification)` marker for out-of-range citations | plain heading (violates FR-038); atomic write (violates U-010) | constitution GFM default (A); ISS-202 (B) |
| ADR-008 | Importable script (`main(argv)->int`); tmp_path-generated stub executables; pytest `unit` marker; behavior-group coverage map | committed stub fixtures; monkeypatching the seam | pyproject/conftest verified (A) |

## Project Structure

```text
echelon/                              (implementation target ".")
├── scripts/
│   └── sue_challenge.py              the deliverable — single file (ADR-001/ADR-002):
│                                     constants → dataclasses → pure core (prompts,
│                                     extraction, validation, assembly, rendering) →
│                                     imperative shell (preflight, runner, round loop, main)
└── tests/
    └── unit/
        └── test_sue_challenge.py     offline unit tests, @pytest.mark.unit (ADR-008);
                                      loads the script via importlib; writes stub
                                      executables into tmp_path
```

- `scripts/sue_challenge.py` owns: the whole v1 behavior. Must NOT own: any import from
  project packages, any config/state read, any write to the challenged spec.
- `tests/unit/test_sue_challenge.py` owns: all 7 behavior groups + seam tests + the FR-045
  import-scan test. Must NOT own: live model calls, network access (SC-002).
- No other files change. `tests/fixtures/` stays untouched (stubs are tmp_path-generated).

## Implementation Phases

### Phase 1: Skeleton — CLI, pre-flight, exit-code spine

**Goal:** Invocable script with the frozen interface and every no-model-call failure path.
**Owner:** speckit-echelon-implementer (IMPLEMENTER)

**Work:**
- Module constants (enums, templates, exit codes, filenames) per ADR-002.
- Dataclasses from `data-model.md` (RunConfig, SpecDocument, CallOutcome, ParseFailure…).
- `parse_args` (usage text incl. exactly 1 egress disclosure — NFR-003), `preflight`,
  `load_spec`, `fail()` choke point, `main()` returning int under `__main__` guard.
- Tests first (constitution Test-First gate): argument handling group + exit 1/2 pre-flight
  matrix (AC-013, AC-014, AC-019).

**Exit Criteria:**
- Exit codes 1 (unreadable spec / unwritable dir) and 2 (missing executable) reproduce with
  exactly 0 model calls and exactly 1 stderr diagnostic line each (SC-003 subset).
- `--help` shows the egress disclosure; module imports without side effects.

### Phase 2: Model runner + isolation

**Goal:** The frozen subprocess contract of `contracts/model-command-contract.md`.
**Owner:** speckit-echelon-implementer (IMPLEMENTER)

**Work:**
- `run_model_call`: `shlex.split(cmd) + ["-p"]`, stdin prompt, fresh `mkdtemp` cwd
  (created/removed per call), timeout with partial-output capture, outcome classification.
- Prompt builders (`numbered_text`, round-1, round-2, retry) as pure functions.
- Tests first: cwd-recording stub (AC-012), prompt-recording stub (AC-011 — round-2 prompt
  carries only `{id, question}`), timeout stub with sub-second `--timeout`.

**Exit Criteria:**
- Recording stub proves: fresh `sue-challenge-*` cwd outside the repo per invocation; argv
  tail `-p`; prompt arrived on stdin; round-2 prompt contains 0 round-1
  categories/targets/lines/reasoning.

### Phase 3: Extraction, validation, retry loop

**Goal:** Untrusted-output handling: FR-016–FR-031 complete.
**Owner:** speckit-echelon-implementer (IMPLEMENTER)

**Work:**
- `extract_json_object` (staged: direct → fence strip → balanced-brace scan).
- `validate_round1` (schema, id uniqueness, truncation + note flag, empty-list success),
  `validate_round2` (schema, bijection with offender-naming messages).
- `execute_round`: ≤2 attempts, corrective vs timeout retry, `.sue-debug/` dump writer,
  exit-3 path; round-2 failure never re-runs round 1.
- Tests first: noisy-extraction fixtures; every field violation; bijection matrix
  (missing/duplicate/unknown id — AC-018); invalid-then-valid retry (AC-016); double-failure
  → exit 3 + dump (AC-015); timeout → retry → exit 3 (AC-017).

**Exit Criteria:**
- SC-003 matrix fully green for exit 3; dump files match `report-format.md` naming;
  extraction fixtures (clean, fenced, prose-wrapped, multi-object, zero-object) all pass.

### Phase 4: Deterministic assembly, report, summary

**Goal:** The product payload: FR-032–FR-042 complete; end-to-end stub run green.
**Owner:** speckit-echelon-implementer (IMPLEMENTER)

**Work:**
- `partition_answers`, `rank_findings` (contradictions first, stable within class).
- `render_report` per `contracts/report-format.md` (header facts, truncation note, findings
  entries, `<details>` audit appendix, zero-finding/zero-question wording, out-of-range
  marker), `render_summary`, report write (plain overwrite), wiring in `main`.
- Tests first: ranking (AC-004); header facts (AC-002) + truncation note (AC-020); rerun
  overwrite (AC-003); collapsed appendix (AC-008); evidence quoting (AC-009); clean-spec
  outcome (AC-007); zero-question outcome (AC-006); NFR-004 double-render byte-diff;
  spec-file-untouched (AC-010); full stubbed end-to-end (AC-021, AC-001, AC-005).

**Exit Criteria:**
- Full unit suite green offline (`pytest -m unit tests/unit/test_sue_challenge.py`) with 0
  network calls and no `claude` on PATH required (SC-002/AC-022).

### Phase 5: Hardening + standalone gate

**Goal:** Close the review gates and the remaining NFRs.
**Owner:** speckit-echelon-implementer (IMPLEMENTER) + speckit-echelon-code-reviewer (CODE REVIEWER)

**Work:**
- FR-045 import-scan test (no project-package imports; reads only argv + spec file).
- NFR-005 assertion across all non-zero exits; NFR-001 structural check (≤4 invocations ×
  timeout, argued + tested via call-counting stub); usage-text polish.
- CODE REVIEWER pass with the feasibility.md risk-5 gate: zero harness coupling.

**Exit Criteria:**
- All FR/AC/NFR rows in SENTINEL's coverage map point at passing tests or the named manual
  gate; review sign-off recorded.

### Final Phase: Manual live acceptance (FINALIZE gate — not a build phase)

**Goal:** SC-001 — the single live-model validation of v1.
**Owner:** operator at FINALIZE (per spec)

**Work:**
- Re-verify or freeze the three spec-029 known-issue anchors first (A-004, last validated at
  base commit ef2643c9).
- Run `scripts/sue_challenge.py specs/029-builder-spec-workbench/spec.md`; success =
  findings overlap ≥ 1 of the 3 named issues within ≤ 3 total attempts (AC-023 tolerance).
- Record spec/prompt sizes observed (A-005 / ISS-209 measurement).

**Exit Criteria:**
- Report exists; overlap criterion met within the attempt budget; sizes recorded.

## Testing Strategy

| Scope | Tool/Method | Pass Condition |
| --- | --- | --- |
| Unit | pytest `-m unit`, pure-function tests importing shared constants; stub-seam tests via tmp_path-generated executables (ADR-008) | all 7 FR-044 behavior groups covered; suite passes with 0 network calls and 0 live model commands installed (SC-002) |
| Integration | (none as a separate tier) — the stub-seam end-to-end tests ARE the integration surface: real subprocess spawn, real files, real exit codes | AC-001/AC-021 end-to-end stub run green |
| E2E/Manual | one manual live acceptance run at FINALIZE against spec 029 (SC-001) | report generated; findings overlap ≥1 of 3 named issues within ≤3 attempts |

Deferred / manually-gated verification: exactly one item — the live acceptance run (spec-
mandated manual criterion, not an automation gap). TDD ordering per constitution: each
phase writes its tests before implementation and observes them fail first.

## Risks

| Risk | Impact | Mitigation | Owner |
| --- | --- | --- | --- |
| claude CLI version drift changes `-p` stdout shape (validated on 2.1.214 only) | extraction retries burn; worst case exit-3 loop | staged tolerant extractor (ADR-005); version + flags pinned in research.md so drift is diagnosable; `.sue-debug/` gives the raw evidence | IMPLEMENTER / operator |
| Operator-scope ambient context biases the reading (OQ-002 residual — now evidence-confirmed) | silent bias, no crash | documented limitation with Grade A evidence; usage/README note offers `--claude-cmd "claude --safe-mode"` as operator opt-in; human reviewer is the backstop | ARCHITECT (documented) / operator |
| ISS-201/ISS-203 counting wordings still unfixed in spec.md when SENTINEL enumerates tests | literal tests assert wrong counts (e.g. AC-011 block count) | counting convention pinned in `contracts/model-command-contract.md` (content block = data payload); COMMANDER should route the one-line rewordings to CARTOGRAPHER before phase3-sentinel | COMMANDER → CARTOGRAPHER |
| Standalone-contract erosion under pressure (harness stream-json reuse) | breaks FR-045 + stub seam | FR-045 import-scan unit test (Phase 5) + CODE REVIEWER gate | CODE REVIEWER |
| Acceptance-run flakiness vs nondeterministic model | false FAIL / goalpost moving | tolerance already encoded (AC-023: ≥1 of 3, ≤3 attempts); A-004 anchor freeze step is Final-Phase work item 1 | FINALIZE operator |
| Stub not reading stdin on large prompts | broken-pipe flakiness in tests | stub replay contract rule 2 (read stdin to EOF) is normative in the contract | SENTINEL / IMPLEMENTER |

## Constitution Check

Constitution: `.specify/memory/constitution.md` v1.0.0 (echelon Builder FE domain; CHIEF
verified this run as non-conflicting — journal entry 32). Read-only governance context; no
amendment proposed (rationale in research.md → Proposed Technical Principles).

| Principle | Compliance |
| --- | --- |
| I. CLI + Filesystem Is the Only Integration Contract (NON-NEGOTIABLE) | Compliant: the script never writes `state.json` / `reasoning-journal.jsonl` / any echelon-owned state; it assumes no API. It is itself a plain CLI + filesystem tool — the exact contract shape the constitution mandates. |
| II. Resilient Poll-and-Tolerate Observation (NON-NEGOTIABLE) | Not implicated: the script observes no echelon run state. It performs no reads of `state.json` or the journal at all (FR-045). |
| III. Specification-Workflow Primacy | Aligned: the tool serves spec quality directly (challenging specifications); it adds no competing build/verify surface. |
| IV. Supervised Long-Running, Interactive Processes | Aligned in spirit: model subprocesses are timeout-bounded (FR-004/FR-011) and non-interactive by construction (`-p`); the script never launches interactive echelon CLIs. |
| V. Honour Trust Boundaries & Local-Operator Blast Radius (NON-NEGOTIABLE) | Compliant: LLM calls stay on the host (no sandbox routing); no MemPalace access; no permission-bypass flags are passed to the model command; the `--claude-cmd` execution seam is documented as operator-trust-only and never sourced from config or network (spec Limitations). |
| Development Workflow — Test-First (hard gate) | Compliant: every implementation phase writes tests first (Red-Green-Refactor); FR-044's behavior groups define the test surface before code exists. |
