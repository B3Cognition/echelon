# Contract: Model Command (external boundary + test seam)

## Metadata

- Spec: 030-build-sue-challenge-script
- Boundary: `sue_challenge.py` ↔ operator-supplied model command (default `claude`);
  identical contract binds the pytest stub executables (FR-043)
- Architect: speckit-echelon-architect (ARCHITECT)
- Date: 2026-07-18
- Evidence: claude CLI 2.1.214 spike, 2026-07-18 (research.md → OQ-001/OQ-002 Evidence)

## Contract: Model subprocess invocation

- Type: CLI (subprocess)
- Provider: the command named by `--claude-cmd` (word-split per shell quoting, FR-007)
- Consumers: `run_model_call()` in sue_challenge.py — the ONLY code path that spawns the command
- Versioning: validated against claude CLI 2.1.214; the tolerant extractor (ADR-005) is the
  drift buffer
- Authentication / authorization: inherited from the operator's model-CLI session; the
  script adds none
- Rate limits: none imposed; per-call timeout applies (FR-004)

### Frozen invocation shape (ADR-003 — the stub replay contract)

```
argv  = shlex.split(claude_cmd) + ["-p"]        # exactly one appended flag
stdin = <full prompt text, UTF-8>               # prompt is NEVER passed via argv
cwd   = <fresh tempfile.mkdtemp(prefix="sue-challenge-")>   # outside the repo (FR-010, AC-012)
env   = inherited unchanged
capture: stdout and stderr separately; timeout = --timeout value (fresh per attempt, FR-013)
```

- Exactly 2 logical calls per run (round 1, round 2 — FR-008); at most 4 subprocess
  invocations including corrective retries (FR-028); 0 calls after round 2 (FR-009).
- Prompt on stdin (not argv): confidential spec text must not appear in process listings,
  and argv size limits must not bind for large specs.
- The temp cwd is created per invocation and removed afterwards; nothing is written into it.

### Outcome classification (ADR-006)

| Observation | Classification | Path |
|-------------|----------------|------|
| executable not found (`shutil.which` pre-flight, or `FileNotFoundError` at exec) | launch_missing | exit 2 + install pointer (FR-012) |
| `subprocess.TimeoutExpired` | timeout → parse failure | retry with identical prompt, 0 appended text (FR-011, FR-029) |
| non-zero exit code, or empty stdout | parse failure | corrective retry path (U-007: exit 2 is ONLY not-found) |
| exit 0 with stdout | raw output → extraction | ADR-005 |

### Operations

| Operation | Request / Input | Response / Output | Errors | Idempotency |
|-----------|-----------------|-------------------|--------|-------------|
| Round 1 — question generation | round-1 prompt (below) | one extractable JSON object: round-1 schema | parse-failure → 1 corrective retry → exit 3 | non-idempotent (model nondeterminism) |
| Round 2 — Socratic test | round-2 prompt (below) | one extractable JSON object: round-2 schema | parse-failure → 1 corrective retry → exit 3; never re-runs round 1 (FR-031) | non-idempotent |

## Prompt contracts

Both prompts embed the specification with every line prefixed by its 1-based line number
(`N: <line text>`, FR-018). Prompt templates are module-level constants (ADR-002).

### Round-1 prompt (FR-014, FR-015)

Exactly 2 elements:

1. The full line-numbered specification text.
2. The question-generation instruction: request **at most N** Socratic challenge questions
   targeting the 5 weakness categories (exact tokens below); demand a single JSON object in
   the round-1 schema; require unique sequential ids `Q1..Qn`; state that `target` is a
   requirement identifier from the spec or `"general"`.

### Round-2 prompt (FR-021–FR-023)

Exactly 2 **content blocks** plus the answering instruction:

1. The full line-numbered specification text (identical numbering to round 1).
2. The round-1 question identifiers with their question texts — rendered as a JSON array of
   `{"id": ..., "question": ...}` objects and **nothing else**: 0 categories, 0 targets,
   0 line references, 0 round-1 reasoning (FR-022, AC-011).

The instruction directs the model to answer each question **using only the specification
text**, assigning exactly 1 verdict per question from {ANSWERED, UNANSWERABLE, CONTRADICTED},
quoting answering lines for ANSWERED, naming the gap for UNANSWERABLE, and citing both sides
for CONTRADICTED — returning a single JSON object in the round-2 schema.

> Counting convention (resolves WHY2 ISS-201 for test enumeration): a **content block** is a
> data payload (spec text; question list). Instructions are not content blocks — in both
> rounds the prompt is: content block(s) + one instruction. AC-011's "exactly 2 content
> blocks" counts payloads only. Flagged for CARTOGRAPHER's FR-021/AC-011 wording alignment.

### Corrective retry prompt (FR-028, FR-029)

- Validation/extraction failure: `<same prompt>` + appended corrective instruction that
  names the specific validation failure (from `ParseFailure.reason`, e.g. "your previous
  reply omitted an answer for Q4 and answered Q2 twice") and repeats the schema demand.
  Echoes **0 lines** of the prior output.
- Timeout: the identical prompt, 0 appended text.

## JSON schemas (round I/O — the three-way contract, single source: ADR-002 constants)

### Round 1

```json
{
  "questions": [
    {
      "id": "Q1",
      "question": "<Socratic challenge question text>",
      "target": "<requirement identifier | general>",
      "lines": [12, 47],
      "category": "ambiguity | hidden-assumption | contradiction | undefined-term | missing-boundary"
    }
  ]
}
```

Validation (strict, FR-016/FR-017): `questions` list required (empty list is VALID →
zero-question success, FR-020); per item: `id` matches `^Q[1-9][0-9]*$` and is unique
(duplicate = parse failure); `question` non-empty string; `target` non-empty string;
`lines` list of integers; `category` in the 5-token enum. Unknown extra keys are ignored.
More than N valid questions → keep first N, set truncation note (FR-019) — not a failure.

### Round 2

```json
{
  "answers": [
    {
      "id": "Q1",
      "verdict": "ANSWERED | UNANSWERABLE | CONTRADICTED",
      "answer": "<answer text | named gap | both contradictory sides>",
      "evidence_lines": [12, 13]
    }
  ]
}
```

Validation (strict, FR-024/FR-025): per item: `id` string, `verdict` in the 3-token enum,
`answer` non-empty string, `evidence_lines` list of integers. Bijection: the answers' ids
must equal the (post-truncation) question ids exactly — each appearing exactly once; any
missing, duplicate, or unknown id is a parse failure naming the offending ids (AC-018).
Integer line values are NOT range-checked here; out-of-range values render as an explicit
marker at report time (ADR-007, ISS-202).

### Extraction envelope (FR-026/FR-027)

Raw stdout is untrusted. Exactly 1 JSON object is extracted, tolerating surrounding
non-JSON text and Markdown code fences (staged extractor, ADR-005). Zero extractable
objects = parse failure. Spike evidence: claude 2.1.214 `-p` returned byte-clean JSON on
the happy path — the tolerance is insurance, not the expected path.

## Stub replay contract (FR-043 — binding for pytest stubs)

A stub substituting for the model command MUST:

1. Accept and ignore the appended trailing `-p` argument (and any argv the test itself put
   in the command string).
2. **Read stdin to EOF before exiting** (prevents broken-pipe errors on large prompts).
3. Print its canned reply to stdout and exit 0 for replay cases; sleep past the configured
   timeout for timeout cases; exit non-zero / print garbage for failure cases.
4. For recording assertions (AC-011, AC-012): persist the received prompt, argv, and
   `os.getcwd()` to a location passed out-of-band (environment variable set by the test) —
   the script guarantees cwd is a fresh `sue-challenge-*` temp directory outside the repo.
5. For multi-call sequences (AC-016): replay file N on the Nth invocation (a counter file in
   the stub's recording directory).

## Internal Interfaces

See `internal-interfaces.md`.
