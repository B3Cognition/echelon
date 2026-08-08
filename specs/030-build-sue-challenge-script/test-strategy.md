# Test Strategy — SUE Challenge Script

## Metadata

- Spec: 030-build-sue-challenge-script (runs/spec-20260718-104053-744160/specs/030-build-sue-challenge-script/spec.md)
- Sentinel: speckit-echelon-sentinel (SENTINEL)
- Date: 2026-07-18
- Inputs reviewed: spec.md, plan.md, data-model.md, contracts/cli-contract.md, contracts/internal-interfaces.md, contracts/model-command-contract.md, contracts/report-format.md, research.md (ADR-001..ADR-008), quality-gates.md (testability sub-metrics, behavioral transitions), belief register `sentinel.yaml` (SNT-001..SNT-009), product-input catalog + traceability

## Stack Detection

- is_browser_app: false
- Detected indicators: deliverable is a stdlib-only Python CLI script (`scripts/sue_challenge.py`, ADR-001); no web framework, no UI/rendering/user-interaction requirements, no static-hosting deployment; repo root has `pyproject.toml` and no `package.json`
- E2E framework: none required (no browser). The stub-seam end-to-end tests through `main(argv)` with real subprocess spawn are the E2E surface (plan.md Testing Strategy)
- Visual validation: not applicable (no UI); no VISUAL VALIDATOR task required
- requires_e2e_setup: false
- package_manager: pip

## Testability Deficiency

Two of three sub-metrics are ≥ 0.70; `negative_space_coverage` is 0.356 (< 0.50 — SNT-007 deficiency signal fires).

| Metric | Score | Weak Requirements | Amendment Recommendation |
|--------|-------|-------------------|--------------------------|
| hard_constraint_ratio | 0.9894 | none — near-total quantification ("exactly N" spec style) | none needed |
| constraint_density | 0.7778 | none — strong average constraint density | none needed |
| negative_space_coverage | 0.356 | Error/edge behavior is not spread across every requirement; it is deliberately concentrated in FR-005/006/011/012/017/025/027–031, ERR-001..ERR-005, and the Edge Cases section (quality-gates.md confirms this concentration is the cause of the low ratio, not an actual gap) | No specification amendment required. Strategy response instead: this plan derives the negative-test matrix primarily from the concentrated error blocks (exit-code state machine, retry loop, bijection violations) plus the 8 Edge Cases, and weights the pyramid toward error-path and boundary tests (~45% of enumerated cases are negative-path). If future WHY passes still score < 0.50 after ISS-201/ISS-203 rewordings, recommend per-requirement error clauses for FR-034 (write failure after model calls) — currently the only error path reachable but unassigned outside pre-flight |

**Weakest-dimension prioritization (FR-005 protocol):** negative space is the weak dimension → boundary value analysis and error-path testing are first-class in this strategy (see Boundary And Data Strategy; exit-code matrix SC-003 is a blocking gate). The 106/147 incomplete behavioral transitions warning in quality-gates.md is honoured: the test matrix is derived from AC-001..AC-023, ERR-001..ERR-005 + the exit-code state machine (ADR-006), and the FR "exactly N" constraints — the extracted transition table is corroborating evidence only.

## Test Pyramid

Architecture-adjusted from the SNT-001 default (70/20/10): a single-file CLI tool with a pure-function core (ADR-002) and one external boundary (the model subprocess). There is no browser tier; the "integration" tier is the stub-seam path mandated by FR-043/AC-021 — real subprocess spawn, real files, real exit codes. All tiers run offline under pytest (SC-002).

| Layer | Target Ratio | Components / Requirements | Rationale |
|-------|--------------|----------------------------|-----------|
| Unit (pure functions) | ~60% | extraction (FR-026/027), validation + bijection (FR-016/017/024/025), prompt builders (FR-014/015/018/021/022/023/028/029), partition/ranking (FR-032/033), rendering (FR-035–FR-041), argparse (FR-001–FR-004, FR-007, NFR-003) | The deterministic core is the product's trust anchor (grounding rule); pure functions test exhaustively with zero I/O; every negative fixture is cheap here |
| Integration (stub-seam, in-process `main(argv)` + real stub subprocess) | ~35% | pre-flight exits (FR-005/006/012), runner + isolation (FR-008–FR-013), retry loop (FR-028–FR-031), end-to-end report/summary (FR-034, FR-040, FR-042–FR-045), exit-code matrix (SC-003), NFR-001/NFR-005 | FR-043 requires the *command substitution* path exercised for real (ADR-008 rejects monkeypatching the seam); higher-than-default ratio because the error-path state machine (the weak negative-space dimension) lives here |
| E2E (live model) | 0% automated; 1 escalated gate | SC-001/AC-023 — the single manual live acceptance run at FINALIZE against `specs/029-builder-spec-workbench/spec.md` | Spec-mandated live-model criterion; cannot run in CI (SC-002 forbids live calls; model is nondeterministic). Carried as `escalate` with the decision already recorded in spec.md — see coverage-map.md Escalations |
| Contract | ~5% | three-way schema contract: prompt templates ↔ validators ↔ stub fixtures share the ADR-002 module constants (`CATEGORIES`, `VERDICTS`, `QUESTION_ID_RE`); stub replay contract rules 1–5 (model-command-contract.md) | Tests import the shared constants instead of re-declaring literals, so any enum/regex drift fails tests rather than green-testing wrong behavior (ISS-206 mitigation) |

## Component Test Approach

| Component | Test Layer(s) | Primary Risks | Required Fixtures |
|-----------|---------------|---------------|-------------------|
| `parse_args` / usage text | unit | argparse exit-code remap (argparse's native exit 2 vs. spec's exit-2-only-for-missing-executable, U-007); missing egress disclosure (NFR-003) | argv vectors; captured `--help` text |
| `preflight` | integration (tmp_path files) | ordering (readable → writable → which); wrong exit class | unreadable path, chmod-0 read-only dir, PATH without stub |
| `numbered_text` / prompt builders | unit + integration (recording stub) | round-2 leakage of round-1 categories/targets/lines (FR-022); off-by-one numbering (FR-018) | small spec fixture with known lines; prompt-recording stub (AC-011) |
| `run_model_call` | integration | cwd not fresh/outside repo (FR-010); prompt on argv instead of stdin (contract); timeout not killing; partial-output loss | cwd/argv/stdin-recording stub; sleeping stub + sub-second `--timeout` |
| `extract_json_object` | unit | brace scanner breaking on strings/escapes; wrong object chosen among several | clean / fenced / prose-wrapped / multi-object / zero-object / escaped-brace-in-string fixtures |
| `validate_round1` / `validate_round2` | unit | any field violation passing; bijection edge (missing+duplicate+unknown combined); truncation off-by-one at exactly N and N+1 | per-violation JSON fixtures; id sets for bijection matrix |
| `execute_round` (retry loop) | integration (replay-sequence stub) | retry echoing prior output (FR-028); timeout retry appending corrective text (FR-029); round-1 re-run after round-2 failure (FR-031); dump naming drift | numbered replay directory (invalid→valid, invalid→invalid, sleep→sleep); `.sue-debug` name/content assertions |
| `partition_answers` / `rank_findings` | unit | verdict-class ordering broken; instability within class; rank not dense | mixed-verdict answer sets in shuffled round-1 order |
| `render_report` / `render_summary` | unit (golden) | section order (FR-035); conditional truncation note leaking; `<details>` count ≠ 1; out-of-range citation crash instead of marker | golden report strings; answers citing line 0 / line > count; ANSWERED-only and zero-question inputs |
| `main` pipeline | integration | report written on failure paths; spec file mutated; > 1 stderr diagnostic line | full stub run; sha256 of spec before/after; stderr line counting |

## Boundary And Data Strategy

Boundary value analysis is prioritized per the testability-deficiency response (negative_space_coverage 0.356).

| Boundary / Entity | Boundary Values | Error Cases | Test Data Strategy |
|-------------------|-----------------|-------------|--------------------|
| `--questions` N vs. round-1 list length | list of exactly N (no truncation, no note); N+1 (truncate to N + note); 0 questions (valid — skip round 2); 1 question | duplicate ids at any position; id `Q0` / `Q01` / non-matching regex | generated question lists around N; parametrized pytest cases |
| Evidence line numbers | line 1 (min); last line (max); 0 and count+1 (out-of-range → marker, never failure); empty `evidence_lines` list | non-integer line values (validation failure) | small fixture spec with known numbered lines |
| ID bijection (FR-025) | exact match (pass) | one missing; one duplicated; one unknown; missing+unknown combined; answers for pre-truncation ids after truncation | id-set matrix, each case asserting the offender is named in `ParseFailure.reason` |
| Timeout budget | stub sleeping just past a sub-second `--timeout`; retry succeeding within its own fresh budget (FR-013) | both attempts sleeping → exit 3 with `TIMEOUT after <T>s` dump line (ISS-207) | sleep-mode stub; `--timeout` ≈ 0.2–0.5 s to keep suite fast (< 5 s worst case per test) |
| Model output envelope | clean JSON (spike-verified happy path); fenced; prose-wrapped; multiple objects; JSON array (not object) → failure; empty stdout → failure | non-zero stub exit code with output → parse failure, NOT exit 2 (U-007) | inline string fixtures in the test file |
| Spec file content | 1-line spec; spec with trailing newline vs. none; non-UTF-8 byte (decoded with `errors="replace"`, run proceeds — ISS-210) | missing file; unreadable file (chmod 000); path is a directory | tmp_path-generated spec fixtures |
| Report destination | writable dir (happy) | read-only dir (pre-flight exit 1, AC-019); rerun with existing report (exactly 1 file remains, AC-003) | tmp_path dirs with chmod; two consecutive `main()` runs |
| Test data isolation | every test uses its own `tmp_path`; stubs, specs, recording files, and reports never share state; no committed fixtures mutate (stubs are tmp_path-generated per ADR-008) | — | pytest `tmp_path` per test; recording location passed via env var per stub-contract rule 4 |
| Sensitive data | fixture specs are synthetic; no production or personal data in any fixture (org GDPR posture; the tool's own egress limitation is NFR-003-disclosed) | — | hand-written neutral markdown fixtures only |

## Automation Coverage Gate

Every requirement in spec.md is classified `automated` except two rows, both `escalate` with the decision **already recorded in the spec itself**: SC-001 and AC-023 define the single manual live acceptance run as a spec-mandated success criterion (plan.md Final Phase; A-004 anchor freeze first). No requirement is classified `deferred-automation`; zero rows are `manual`. Full per-requirement mapping in `coverage-map.md`.

## CI/CD Pipeline

The deliverable is a repo host tool — there is no deploy stage; "merge" is the terminal gate. All stages run with zero network and zero live model commands (SC-002).

| Stage | Commands / Gates | Target Duration | Blocks Merge / Deploy |
|-------|------------------|-----------------|-----------------------|
| Pre-commit | `pytest -m unit tests/unit/test_sue_challenge.py` (full new suite — it is all unit-marked and offline) | < 30 s (SNT-008; timeout tests use sub-second budgets to hold this) | blocks commit locally (advisory) |
| PR/Merge | `pytest` (whole repo suite incl. the new file); flakiness detection loop (5 consecutive runs of the new file — see Flakiness Management); FR-045 import-scan test green | < 5 min (SNT-009) | **blocks merge** |
| Post-merge | rerun full suite on main; no separate E2E tier exists (stub-seam tests are the E2E surface) | < 5 min | blocks release tagging |
| Pre-deploy | n/a — no deployment; the FINALIZE manual live acceptance gate (SC-001) sits here in the workflow sense: A-004 anchor re-verify/freeze, then ≤ 3 live attempts | operator-paced | blocks FINALIZE sign-off |
| Post-deploy | n/a | — | — |

Failure policy: any red test in Pre-commit/PR stages blocks merge. The SC-001 gate failing after 3 attempts blocks FINALIZE and routes to COMMANDER (not silently waived).

## Flakiness Management

The suite is designed deterministic: no network, no live model, injected run-date (NFR-004), per-test `tmp_path`. The only timing-sensitive tests are the timeout-path tests.

| Policy | Value |
|--------|-------|
| Repeat count for new tests | 5 consecutive full runs of `tests/unit/test_sue_challenge.py` before merge (pytest has no `--repeat-each`; a shell loop `for i in 1 2 3 4 5; do pytest -m unit tests/unit/test_sue_challenge.py || exit 1; done` is the equivalent, avoiding any plugin dependency per NFR-002's spirit). Any failure across the 5 runs blocks merge until investigated |
| Quarantine marker | `@pytest.mark.skip(reason="Flaky - Issue #NNN")` with a linked tracking issue; quarantined tests are blocking debt items, not exemptions |
| Root-cause taxonomy | expected classes here are **network-timing** analogues (subprocess timeout margins too tight — fix by widening the sleep/timeout gap, e.g. sleep 3× the budget) and **state-leak** (shared recording files — fix with per-test tmp_path); race-condition/animation-render/data-dependency are structurally absent |
| Flaky rate target | < 5% of suite (SNT-004); expected actual: 0 |
| Critical journey pass target | 100% — T-SEAM-01 (full stubbed run) and the SC-003 exit-code matrix must never be flaky |
| Review cadence | weekly; > 2 weeks quarantined without a fix attempt escalates to COMMANDER (SNT-005); fixed tests re-validated with 10 consecutive runs before unquarantining (SNT-006 adaptation) |

## Known Test-Enumeration Hazard (from plan.md Risks)

spec.md AC-011 says "exactly 2 content blocks" and related counting wordings (ISS-201/ISS-203) were flagged for CARTOGRAPHER rewording but are not yet amended. Tests MUST adopt the counting convention pinned normatively in `contracts/model-command-contract.md`: a *content block* is a data payload (spec text; question list) — instructions are not content blocks. Test assertions for AC-011 therefore check: round-2 recorded prompt contains the numbered spec text and the `[{"id","question"}]` array, and contains zero occurrences of round-1 category tokens, targets, line-reference arrays, or reasoning text — not a literal "block count". This keeps tests correct whether or not the one-line spec rewording lands. Not a blocker; flagged to COMMANDER as a journal entry.
