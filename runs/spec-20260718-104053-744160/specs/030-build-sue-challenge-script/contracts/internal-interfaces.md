# Contract: Internal Interfaces — `scripts/sue_challenge.py`

## Metadata

- Spec: 030-build-sue-challenge-script
- Boundary: internal module structure of the single-file script (ADR-001/ADR-002)
- Architect: speckit-echelon-architect (ARCHITECT)
- Date: 2026-07-18

These are the function-level contracts SENTINEL derives unit tests from and IMPLEMENTER
implements. All functions marked **pure** perform no I/O, no clock reads, no randomness.
Types reference `data-model.md` entities.

## Internal Interfaces

| Interface | Provider | Consumers | Operations | Stability |
|-----------|----------|-----------|------------|-----------|
| Shared constants | module level | prompt builders, validators, renderer, tests | `CATEGORIES`, `VERDICTS`, `QUESTION_ID_RE`, `REPORT_FILENAME`, `DEBUG_DIR_NAME`, prompt templates, exit-code constants | stable (the three-way contract anchor, ISS-206) |
| CLI & pre-flight | `parse_args`, `preflight` | `main` | argv → RunConfig; RunConfig → ok / (exit code, diagnostic) | stable |
| Spec loading | `load_spec`, `numbered_text` | `main`, prompt builders, renderer | path → SpecDocument; SpecDocument → line-numbered text | stable |
| Prompt assembly | `build_round1_prompt`, `build_round2_prompt`, `build_retry_prompt` | `main` | pure — see below | stable |
| Subprocess runner | `run_model_call` | `main` | (RunConfig, prompt) → CallOutcome; owns temp-cwd lifecycle | stable |
| Extraction & validation | `extract_json_object`, `validate_round1`, `validate_round2` | round loop | raw str / dict → typed values or ParseFailure | stable |
| Round loop | `execute_round` | `main` | ≤2 attempts, retry policy, debug dump on second failure | stable |
| Assembly | `partition_answers`, `rank_findings` | `main` | pure verdict partition + FR-033 ranking | stable |
| Rendering & output | `render_report`, `render_summary` | `main` | pure string builders | stable |
| Entry point | `main(argv) -> int` | `__main__` guard; pytest in-process tests | full pipeline; returns exit code, never calls `sys.exit` itself | stable |

## Operation contracts

### `parse_args(argv: list[str]) -> RunConfig`
Argparse over the frozen v1 surface (`cli-contract.md`). Usage/help text contains exactly 1
egress disclosure (NFR-003). Errors follow argparse convention (usage to stderr, exit 2 from
argparse is remapped — argument errors funnel to the exit-1 bad-input class before any model
call; only executable-not-found may yield exit 2, FR-012/U-007).

### `preflight(config: RunConfig) -> None | Failure`
Order: spec readable (ERR-001) → spec dir writable (`os.access(dir, W_OK)`, ERR-002) →
`shutil.which(shlex.split(model_command)[0])` (ERR-003). Guarantees 0 model calls on any
pre-flight failure (FR-005/FR-006/FR-012).

### `load_spec(path: Path) -> SpecDocument`
Reads the file exactly once, UTF-8 with `errors="replace"`, splits into newline-stripped
lines. Never writes (FR-042, FR-045).

### `numbered_text(spec: SpecDocument) -> str` — pure
`"1: <line>\n2: <line>…"` — 1-based numbering (FR-018); identical embedding for both rounds.

### `build_round1_prompt(spec, max_questions) -> str` — pure
Numbered spec + generation instruction (≤ N questions, 5 category tokens, round-1 schema
demand). FR-014/FR-015.

### `build_round2_prompt(spec, questions) -> str` — pure
Numbered spec + `[{"id","question"}]` JSON array + answering instruction (3-verdict enum,
spec-text-only rule, round-2 schema demand). Carries exactly 0 round-1 categories / targets /
lines / reasoning (FR-021/FR-022/FR-023) — enforced here structurally: the function's
signature only receives `(id, question)` pairs.

### `build_retry_prompt(original: str, failure: ParseFailure) -> str` — pure
`failure.is_timeout` → returns `original` unchanged (FR-029); otherwise `original` +
corrective instruction naming `failure.reason`, echoing 0 lines of prior output (FR-028).

### `run_model_call(config: RunConfig, prompt: str) -> CallOutcome`
One subprocess invocation per the frozen shape in `model-command-contract.md`: fresh
`mkdtemp` cwd (created and removed here — FR-010), prompt on stdin, timeout enforced with
kill, stdout/stderr captured (partial output preserved on `TimeoutExpired`).
`FileNotFoundError` → `launch_missing`. Never raises to callers.

### `extract_json_object(raw: str) -> dict | ParseFailure` — pure
Staged tolerant extraction (ADR-005): direct parse → fence strip → balanced-brace scan.
Returns the first parseable JSON **object**; zero candidates → ParseFailure (FR-026/FR-027).

### `validate_round1(obj: dict, max_questions: int) -> tuple[list[SocraticQuestion], bool] | ParseFailure` — pure
Strict schema + id uniqueness (FR-016/FR-017). Returns (questions, truncated) after applying
the first-N truncation rule (FR-019). Empty list is valid (FR-020).

### `validate_round2(obj: dict, questions: list[SocraticQuestion]) -> list[Answer] | ParseFailure` — pure
Strict schema (FR-024) + ID bijection against the post-truncation question ids (FR-025);
ParseFailure.reason names every offending id (AC-018).

### `execute_round(config, prompt, validator, round_no, spec_dir) -> Validated | ExitRequest`
At most 2 attempts (FR-028); fresh timeout per attempt (FR-013); timeout → plain re-issue
(FR-029); second failure → write `.sue-debug/` dumps for both attempts (FR-030, ISS-207) and
request exit 3. A round-2 failure never re-enters round 1 (FR-031) — rounds are sequential
calls in `main`, with no cross-round loop by construction.

### `partition_answers(questions, answers) -> tuple[list[Finding], list[AuditEntry]]` — pure
Exactly 2 groups (FR-032): findings (CONTRADICTED + UNANSWERABLE) and audit entries
(ANSWERED). 0 model calls at or after this point (FR-009).

### `rank_findings(findings) -> list[Finding]` — pure
All CONTRADICTED before all UNANSWERABLE; round-1 question order within each class; dense
1-based ranks (FR-033).

### `render_report(spec, run_date, questions, findings, audit, truncated) -> str` — pure
Produces the full `socratic-challenge.md` body per `report-format.md`. Run date injected
(NFR-004). Out-of-range citations render the `(not present in the specification)` marker.

### `render_summary(findings) -> str` — pure
Per-verdict-class counts + top 3 findings in rank order (FR-040).

### `main(argv: list[str] | None = None) -> int`
Pipeline: parse → preflight → load spec → round 1 (skip round 2 if 0 questions, FR-020) →
round 2 → partition/rank → write report (plain overwrite, FR-034) → print summary → 0.
Exactly 1 stderr diagnostic line on every non-zero return (NFR-005), emitted through a
single `fail()` choke point. Returns the exit code; only the `if __name__ == "__main__":`
guard calls `sys.exit(main())`, keeping the module import-safe for tests (ADR-008).

## Dependency direction (no cycles)

```
constants ← prompt assembly ← main
constants ← validation      ← round loop ← main
spec loading ← main;  runner ← round loop;  assembly/rendering ← main
```

Pure core (assembly, validation, extraction, rendering, prompt building) depends only on
constants and dataclasses; the imperative shell (`main`, runner, round loop, preflight)
depends on the pure core — never the reverse.
