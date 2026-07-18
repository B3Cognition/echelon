# Data Model — SUE Challenge Script

## Metadata

- Spec: 030-build-sue-challenge-script
- Architect: speckit-echelon-architect (ARCHITECT)
- Date: 2026-07-18

All entities are **in-memory Python values** (dataclasses / plain values) inside a single
process run — there is no database and no persisted state beyond two file artifacts
(Challenge Report, Debug Dump). Types below use Python notation. Field names in `code`
are the frozen JSON keys of the model I/O contract where applicable (see
`contracts/model-command-contract.md`).

## Entity Index

| Entity | Glossary Term | Lifecycle | Persistent | Notes |
|--------|---------------|-----------|------------|-------|
| RunConfig | Challenge Run (attributes) | yes | no | Validated CLI arguments |
| SpecDocument | Challenged spec | no | no (read-only source file) | Read exactly once; never written (FR-042) |
| SocraticQuestion | Socratic question | yes | no | Round-1 output unit |
| Answer | Answer / Verdict | yes | no | Round-2 output unit |
| Finding | Finding | no | via report | Derived view over Answers |
| ChallengeReport | Challenge report | yes | yes (`socratic-challenge.md`) | Overwritten on rerun (U-010) |
| CallOutcome | Model Call | yes | no | Typed result of one subprocess invocation |
| ParseFailure | Corrective retry (trigger) | no | no | Reason value feeding retry / exit 3 |
| DebugDump | Debug dump | yes | yes (`.sue-debug/`) | Exit-3 path only |

## Entity: RunConfig

- Description: The validated invocation of one Challenge Run — everything the operator
  controls (FR-001–FR-004, FR-007).
- Glossary reference: Challenge Run
- Persistence: none

| Field | Type | Required | Constraints | Description |
|-------|------|----------|-------------|-------------|
| `spec_path` | Path | yes | exists, is a readable file (else exit 1, FR-005) | The challenged specification |
| `max_questions` | int | yes | default 15; > 0 | Round-1 question cap N (FR-002) |
| `model_command` | str | yes | default `"claude"`; non-empty after `shlex.split` | Model command line; word 1 availability-checked (FR-003, FR-007) |
| `timeout_seconds` | int | yes | default 300; > 0 | Per-subprocess-call budget (FR-004) |

| Related Entity | Cardinality | FK Location | Cascade Rules |
|----------------|-------------|-------------|---------------|
| SpecDocument | 1:1 | `spec_path` | n/a |

### Validation Rules

- Pre-flight order (all before any model call): `spec_path` readable → `spec_path.parent`
  writable (`os.access(..., W_OK)`, else exit 1, FR-006) → `shutil.which(shlex.split(model_command)[0])`
  found (else exit 2, FR-012).
- `model_command` splits per shell quoting conventions; a value that splits to zero words is
  an argument error (exit 1 path, argparse).

### State Transitions

- None (immutable after parse).

### Indexes

| Name | Fields | Type | Justification |
|------|--------|------|---------------|
| (none) | | | in-memory value |

## Entity: SpecDocument

- Description: The challenged specification, read exactly once into an ordered list of
  lines; the sole evidence source for both rounds (FR-018, FR-045).
- Glossary reference: Challenged spec
- Persistence: pre-existing read-only file; the run performs exactly 0 writes to it (FR-042)

| Field | Type | Required | Constraints | Description |
|-------|------|----------|-------------|-------------|
| `path` | Path | yes | — | As given on the CLI (echoed in report header) |
| `lines` | list[str] | yes | order-preserving, newline-stripped | 1-based indexing: `lines[n-1]` is spec line n |

### Validation Rules

- Decoded as UTF-8 with `errors="replace"` so an odd byte never crashes a run (an unreadable
  *file* is exit 1; a decodable-with-replacement file proceeds — ISS-210 disposition at HOW).
- `numbered_text()` derives the prompt embedding: each line prefixed `N: ` starting at 1
  (FR-018), making every cited reference checkable (FR-039).

### State Transitions

- None (immutable after read-once).

### Indexes

| Name | Fields | Type | Justification |
|------|--------|------|---------------|
| line lookup | implicit list index | positional | O(1) quote-by-line-number at render (FR-039) |

## Entity: SocraticQuestion

- Description: One round-1 output unit after strict validation (FR-016).
- Glossary reference: Socratic question
- Persistence: none (echoed into the report via its Answer)

| Field | Type | Required | Constraints | Description |
|-------|------|----------|-------------|-------------|
| `id` | str | yes | matches `^Q[1-9][0-9]*$`; unique within the round (dup = parse failure, FR-017) | Question identifier (A-010) |
| `question` | str | yes | non-empty | The Socratic challenge text |
| `target` | str | yes | non-empty; requirement identifier or `"general"` | What the question interrogates |
| `lines` | list[int] | yes | integers (range not validated — ADR-005) | Round-1 cited spec lines |
| `category` | str | yes | ∈ {`ambiguity`, `hidden-assumption`, `contradiction`, `undefined-term`, `missing-boundary`} | Weakness category (FR-015; shared constant, ISS-206) |

| Related Entity | Cardinality | FK Location | Cascade Rules |
|----------------|-------------|-------------|---------------|
| Answer | 1:1 | `Answer.id` | bijection enforced (FR-025); violation = parse failure |

### Validation Rules

- List-level: if the validated list holds more than `max_questions`, keep the first N in
  returned order and set the truncation flag (FR-019). An empty list is valid — the run
  completes without round 2 (FR-020).

### State Transitions

- generated (round 1) → carried into round 2 as `{id, question}` only (FR-021/FR-022) →
  classified by its Answer's verdict → rendered as Finding or audit entry.

### Indexes

| Name | Fields | Type | Justification |
|------|--------|------|---------------|
| id order | list position | positional | Round-1 order is the rank tiebreaker (FR-033) and bijection reference (FR-025) |

## Entity: Answer

- Description: One round-2 output unit after strict validation (FR-024).
- Glossary reference: Answer / Verdict
- Persistence: none (rendered into the report)

| Field | Type | Required | Constraints | Description |
|-------|------|----------|-------------|-------------|
| `id` | str | yes | must appear exactly once and match a round-1 question id (FR-025) | Question identifier |
| `verdict` | str | yes | ∈ {`ANSWERED`, `UNANSWERABLE`, `CONTRADICTED`} (FR-023) | The Socratic test result |
| `answer` | str | yes | non-empty | Answer text / named gap / both contradictory sides |
| `evidence_lines` | list[int] | yes | integers (range checked at render — ADR-007) | Cited spec lines |

| Related Entity | Cardinality | FK Location | Cascade Rules |
|----------------|-------------|-------------|---------------|
| SocraticQuestion | 1:1 | `id` | bijection (FR-025) |
| Finding | 0..1 : 1 | derived | verdict ∈ {CONTRADICTED, UNANSWERABLE} (FR-032) |

### Validation Rules

- Bijection: multiset of Answer ids == set of (post-truncation) question ids; missing,
  duplicate, or unknown ids are a parse failure naming the offenders (FR-025, AC-018).

### State Transitions

- validated → partitioned into finding | audit entry (FR-032). Terminal.

### Indexes

| Name | Fields | Type | Justification |
|------|--------|------|---------------|
| by id | dict[str, Answer] | hash | O(1) bijection check and question join |

## Entity: Finding

- Description: An Answer whose verdict is CONTRADICTED or UNANSWERABLE, joined to its
  question, with a rank (FR-032, FR-033). The report's payload; top 3 echoed to stdout.
- Glossary reference: Finding
- Persistence: via ChallengeReport only

| Field | Type | Required | Constraints | Description |
|-------|------|----------|-------------|-------------|
| `rank` | int | yes | 1-based, dense | All CONTRADICTED before all UNANSWERABLE; round-1 order within class (FR-033) |
| `question` | SocraticQuestion | yes | — | Joined round-1 unit (supplies question text + target for FR-037) |
| `answer` | Answer | yes | verdict ≠ ANSWERED | Supplies verdict, gap text, evidence lines |

### Validation Rules

- Derived deterministically; no model call may occur during derivation (FR-009).

### State Transitions

- None (derived, immutable).

### Indexes

| Name | Fields | Type | Justification |
|------|--------|------|---------------|
| rank order | list position | positional | Report order and top-3 summary (FR-040) |

## Entity: ChallengeReport

- Description: The rendered markdown artifact written to
  `<spec-dir>/socratic-challenge.md` (FR-034); exactly 3 sections in order (FR-035).
- Glossary reference: Challenge report
- Persistence: yes — single file, plain overwrite, 0 historical copies (U-010)

| Field | Type | Required | Constraints | Description |
|-------|------|----------|-------------|-------------|
| `spec_path` | str | yes | header fact 1 (FR-036) | Path as invoked |
| `run_date` | str | yes | ISO 8601 date; injected, not read inside the renderer (NFR-004) | header fact 2 |
| `question_count` | int | yes | post-truncation count | header fact 3 |
| `finding_count` | int | yes | == len(findings) | header fact 4 |
| `truncated` | bool | yes | adds the truncation note line only when true (FR-019/FR-036) | header conditional |
| `findings` | list[Finding] | yes | may be empty → explicit "0 findings" statement (FR-041) | section 2 |
| `audit_entries` | list[(SocraticQuestion, Answer)] | yes | verdict == ANSWERED | section 3, one `<details>` block (FR-038) |

### Validation Rules

- Rendering is a pure function of the fields above plus `SpecDocument.lines` (for evidence
  quotes, FR-039); byte-identical bodies for identical inputs outside `run_date` (NFR-004).
- Out-of-range cited line → `(not present in the specification)` marker (ADR-007, ISS-202).

### State Transitions

- rendered → written (overwrite) → summarized to stdout → exit 0 (FR-040). Regenerable,
  never a record.

### Indexes

| Name | Fields | Type | Justification |
|------|--------|------|---------------|
| (none) | | | file artifact |

## Entity: CallOutcome

- Description: The typed result of exactly one model subprocess invocation (one Model Call
  attempt) from a neutral temp cwd (FR-010).
- Glossary reference: Model Call
- Persistence: none (raw text may flow into a DebugDump)

| Field | Type | Required | Constraints | Description |
|-------|------|----------|-------------|-------------|
| `kind` | enum | yes | `ok` \| `timeout` \| `launch_missing` \| `failed` | Drives the ADR-006 state machine |
| `stdout` | str | yes | may be partial on timeout | Raw output for extraction / dump |
| `stderr` | str | yes | — | Kept for the dump only |
| `duration_seconds` | float | yes | ≤ timeout + epsilon | Diagnostics |

### Validation Rules

- `launch_missing` occurs only on executable-not-found (exit 2, FR-012); every other launch
  or output problem is `failed`/`timeout` → parse-failure path (U-007 decision).

### State Transitions

- attempt 1 `ok` → extraction/validation; on ParseFailure → attempt 2 (corrective retry,
  FR-028/FR-029, fresh budget FR-013) → `ok` continue | anything else → exit 3 (FR-030).

### Indexes

| Name | Fields | Type | Justification |
|------|--------|------|---------------|
| (none) | | | transient value |

## Entity: ParseFailure

- Description: The reason value produced when extraction or validation rejects model output;
  its message is embedded in the corrective retry instruction (FR-028).
- Glossary reference: Corrective retry
- Persistence: none

| Field | Type | Required | Constraints | Description |
|-------|------|----------|-------------|-------------|
| `reason` | str | yes | names the specific violation (e.g. "duplicate question id Q3"; "no JSON object found"; "timeout") | Retry corrective text; echoes 0 lines of prior output (FR-028) |
| `is_timeout` | bool | yes | timeout retries append 0 corrective text (FR-029) | Retry mode selector |

## Entity: DebugDump

- Description: Raw output of the failing round saved under `<spec-dir>/.sue-debug/` on the
  unrecoverable path only (FR-030, AC-015).
- Glossary reference: Debug dump
- Persistence: yes — directory of plain-text files

| Field | Type | Required | Constraints | Description |
|-------|------|----------|-------------|-------------|
| directory | Path | yes | exactly 1 directory named `.sue-debug` beside the spec | Created (exist_ok) only on exit-3 |
| files | files | yes | `round{R}-attempt{A}-stdout.txt`, `round{R}-attempt{A}-stderr.txt` for both failing attempts of the failing round | Timeout attempts include partial output plus a `TIMEOUT after <T>s` first line (ISS-207) |

## Explicit Exclusions

| Mental Model Entity | Reason Excluded | Where Represented Instead |
|---------------------|-----------------|---------------------------|
| Stub Executable (test-only) | Test infrastructure, not a runtime entity; exists only inside the pytest seam | ADR-008 (research.md) and `contracts/model-command-contract.md` stub replay contract |
| Challenge Run (as a stored record) | v1 keeps no run history; the run exists only as the process itself | Decomposed into RunConfig (inputs) + exit code + ChallengeReport/DebugDump (outputs) |

All other mental-model.md entities (Challenged Spec, Socratic Question, Answer, Finding,
Challenge Report, Model Call, Debug Dump) map 1:1 onto the entities above. The
mental-model.md "written atomically" lifecycle claim is superseded by the U-010 spec
decision (plain overwrite) — this model follows the spec (SAGE ISS-204).
