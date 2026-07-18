# Mental Model

## Core Entities

### Challenge Run
- **Description:** One end-to-end execution of the SUE challenge script against a single challenged spec.
- **Key attributes:** spec path (positional arg), max questions N (default 15), claude command (default `claude`), per-call timeout (default 300s), exit code (0/1/2/3), run date.
- **Relationships:** consumes exactly one Challenged Spec; performs exactly two logical Model Calls (each with at most one corrective retry, so 2–4 subprocess invocations); produces exactly one Challenge Report on success, or one Debug Dump on unrecoverable parse failure.
- **Lifecycle:** validate input → check claude availability → round 1 → validate round-1 JSON → round 2 → validate round-2 JSON + ID bijection → deterministic assembly → write report + stdout summary → exit 0. Any stage can short-circuit to a non-zero exit.

### Challenged Spec
- **Description:** The markdown specification file under interrogation. Read once; its text is the sole evidence source for both rounds.
- **Key attributes:** path, readability, text content, line numbers (questions and answers reference spec lines), containing directory (`<spec-dir>` — where the report and `.sue-debug/` land).
- **Relationships:** one spec per run; its text is embedded in both round-1 and round-2 prompts; its directory receives the report.
- **Lifecycle:** exists before the run; never modified by the run.

### Socratic Question
- **Description:** One round-1 output unit: a challenge aimed at a specific weakness in the spec.
- **Key attributes:** `id` ("Q1"…), `question` (text), `target` (`REQ-nnn` or `"general"`), `lines` (list of spec line ints), `category` (one of `ambiguity` | `assumption` | `contradiction` | `undefined-term` | `boundary`).
- **Relationships:** belongs to one run; must be matched by exactly one Answer in round 2 (ID bijection).
- **Lifecycle:** created in round 1 → carried (question text + id only, no rationale) into round 2 → classified by its Answer → rendered either as Finding or as audit-appendix entry.

### Answer
- **Description:** One round-2 output unit: the spec-text-only response to one question, with a verdict.
- **Key attributes:** `id` (matching a question id), `verdict` (`ANSWERED` | `UNANSWERABLE` | `CONTRADICTED`), `answer` (text: the answer, the named gap, or both contradictory sides), `evidence_lines` (list of spec line ints).
- **Relationships:** exactly one per Socratic Question (bijection on ids; violations are parse failures).
- **Lifecycle:** created in round 2 → filtered by verdict in deterministic assembly.

### Finding
- **Description:** An Answer whose verdict is `CONTRADICTED` or `UNANSWERABLE` — a question the spec could not cleanly answer.
- **Key attributes:** everything from the Answer plus rank (contradictions first).
- **Relationships:** subset of Answers; 0..N per run; top 3 echoed to stdout.
- **Lifecycle:** derived deterministically; persisted in report section 2.

### Challenge Report
- **Description:** The markdown artifact `socratic-challenge.md` written next to the challenged spec.
- **Key attributes:** header (spec path, run date, question/finding counts), findings section, audit appendix (ANSWERED questions with their answering lines). Overwritten on rerun — no history in v1.
- **Relationships:** exactly one per successful run; derived from all Answers.
- **Lifecycle:** written atomically at the end of a successful run; regenerable at will.

### Model Call
- **Description:** One isolated `claude -p` subprocess invocation from a neutral temp working directory.
- **Key attributes:** prompt (spec text + round instruction; retry appends corrective text), timeout, raw stdout, parse result (strict JSON expected).
- **Relationships:** two logical calls per run (round 1, round 2); each may spawn one retry subprocess; the command executed is the `--claude-cmd` value (test seam).
- **Lifecycle:** spawn in temp cwd → wait (bounded by timeout) → extract/validate JSON → on failure: one corrective retry → on second failure: dump raw output, exit 3.

### Debug Dump
- **Description:** Raw model output saved to `<spec-dir>/.sue-debug/` when parsing fails unrecoverably.
- **Key attributes:** raw stdout of the failing call(s).
- **Relationships:** produced only on the exit-3 path; aids offline diagnosis.

### Stub Executable (test-only)
- **Description:** A fake claude command used by pytest unit tests via `--claude-cmd`; replays canned JSON so the deterministic parts are testable without a model.
- **Relationships:** substitutes for the claude CLI in every unit-test Model Call.

## Relationships

| Entity A | Relationship | Entity B | Cardinality | Notes |
|----------|--------------|----------|-------------|-------|
| Challenge Run | consumes | Challenged Spec | one-to-one | Read-only; exit 1 if missing/unreadable, before any model call |
| Challenge Run | performs | Model Call | one-to-many | Exactly 2 logical calls; 2–4 subprocesses including retries |
| Model Call (round 1) | produces | Socratic Question | one-to-many | 1..N, N capped by `--questions` (default 15) |
| Socratic Question | answered by | Answer | one-to-one | ID bijection enforced; missing/extra ids = parse failure |
| Answer | may become | Finding | one-to-one (conditional) | Only verdicts CONTRADICTED / UNANSWERABLE |
| Challenge Run | writes | Challenge Report | one-to-one | On success only; rerun overwrites |
| Challenge Run | writes | Debug Dump | one-to-one (conditional) | Only on unrecoverable parse failure (exit 3) |
| Socratic Question | targets | requirement ID in spec | many-to-one | `REQ-nnn` or `general`; SUE does not verify the ID exists in the spec (open question) |
| Challenge Report | lives beside | Challenged Spec | one-to-one | Same directory (`<spec-dir>`) |

## Concept Map

```
                       (grounding rule: engine asks, text testifies, human decides)

 Challenged Spec ──text──────────────┬──────────────────────────┐
        │                            v                          v
        │                    [Round 1: claude -p]       [Round 2: claude -p]
        │                    temp cwd, strict JSON      temp cwd, strict JSON
        │                            │                          ▲   │
        │                            └── questions only ────────┘   │  answers
        │                                (no rationale)             v
        │                                              [Deterministic assembly]
        │                                               filter + rank (no model)
        │                                                        │
        v                                                        v
   <spec-dir>/  ◄──────────── socratic-challenge.md ── findings + audit appendix
                └── .sue-debug/   (only on exit-3 parse failure)
```

## Behavioral Patterns

**Happy path:** read spec → round-1 call → parse strict JSON (questions) → round-2 call with spec + bare questions → parse strict JSON (answers) + bijection check → filter verdicts into findings (contradictions ranked first) → render report → print stdout summary (finding counts + top 3) → exit 0.

**Exit-code state machine (evaluated in order):**
- spec path missing/unreadable → exit 1 (no model call made)
- claude command unavailable → exit 2 (install pointer; ERR-CLI-MISSING pattern)
- model output unparseable after one corrective retry, in either round → exit 3 (raw output to `.sue-debug/`)
- per-call timeout → treated exactly as a parse failure (retry once, then exit 3)
- report written → exit 0

**Retry pattern:** single corrective retry per round, appending a correction instruction to the same prompt. There is no cross-round retry: a round-2 failure does not re-run round 1.

**Isolation pattern:** every subprocess uses a neutral temp directory as cwd so `claude -p` cannot pick up the repo's CLAUDE.md; information flow between rounds is restricted to question text + ids.

**Idempotence pattern:** reruns overwrite `socratic-challenge.md`; the report is treated as regenerable, never as a record.
