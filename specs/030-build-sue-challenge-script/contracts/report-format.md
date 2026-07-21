# Contract: Challenge Report & Debug Dump (filesystem write boundary)

## Metadata

- Spec: 030-build-sue-challenge-script
- Boundary: `sue_challenge.py` ↔ `<spec-dir>` filesystem (write side)
- Architect: speckit-echelon-architect (ARCHITECT)
- Date: 2026-07-18

## Contract: `socratic-challenge.md`

- Type: File artifact (GitHub-Flavoured Markdown)
- Provider: `render_report()` + shell write (ADR-007)
- Consumers: spec authors and reviewers (human); later SUE tiers treat "markdown report out"
  as the stable v1 interface
- Versioning: overwritten in place on rerun; 0 historical copies (FR-034, U-010 — plain
  `open(path, "w")`, no atomicity guarantee)
- Authentication / authorization: filesystem permissions; writability pre-flighted (FR-006)
- Rate limits: n/a

### Location and lifecycle

- Exactly 1 file named `socratic-challenge.md` in the challenged specification's directory
  (FR-034). Written only on the success path; exit codes 1/2/3 write 0 reports.
- The challenged specification itself receives exactly 0 writes on every path (FR-042).

### Structure — exactly 3 sections in order (FR-035)

```markdown
# Socratic Challenge Report

- **Specification:** <spec path as invoked>
- **Run date:** <YYYY-MM-DD>
- **Provider:** <claude | codex | copilot>
- **Questions:** <post-truncation count>
- **Findings:** <finding count>
- **Note:** round 1 returned M questions; truncated to the first N.   ← ONLY when truncated (FR-019)

## Findings

### 1. [CONTRADICTED] <question text>
- **Target:** <requirement identifier | general>
- **Evidence:**
  > line 12: <exact spec line 12 text>
  > line 47: <exact spec line 47 text>

<answer text — for CONTRADICTED: both sides; for UNANSWERABLE: the named gap (FR-039)>

### 2. [UNANSWERABLE] <question text>
…

## Audit appendix

<details>
<summary>Audit appendix — <K> ANSWERED question(s)</summary>

### Q2 — <question text>
- **Answer:** <answer text>
- **Answering lines:**
  > line 3: <exact spec line 3 text>

…one entry per ANSWERED question…

</details>
```

### Normative rules

| Rule | FR | Detail |
|------|----|--------|
| Header states exactly 5 base facts | FR-036, AC-002 | spec path, run date, resolved model provider, question count, finding count; truncation note is the only conditional addition |
| Findings ranked | FR-033, AC-004 | all CONTRADICTED before all UNANSWERABLE; round-1 question order within each class; dense 1-based rank numbers |
| Finding entry states exactly 4 elements | FR-037 | verdict, question, target, evidence |
| Evidence quoting | FR-039, FR-018, AC-009 | for each cited line number, exactly 1 quoted line read from the specification file (1-based); UNANSWERABLE findings state the named gap from the answer text |
| Out-of-range citation | ADR-007 (ISS-202) | `> line N: (not present in the specification)` — deterministic marker, never a validation failure |
| Zero findings | FR-041, AC-007 | Findings section states that exactly 0 findings were produced; audit appendix still holds every question |
| Zero questions | FR-020, AC-006 | header records 0 questions / 0 findings; findings section states 0 findings; audit appendix states 0 entries |
| Collapsed audit appendix | FR-038, AC-008 | exactly 1 `<details>` block (collapsed by default in GFM; reader-expandable); every ANSWERED question with its quoted answering lines |
| Determinism | NFR-004 | identical validated inputs → byte-identical bodies outside the run-date field |

### Terminal summary (companion stdout output, FR-040)

After the report write: finding count per verdict class (CONTRADICTED: X, UNANSWERABLE: Y)
plus the top 3 findings in rank order, then exit 0. Human-oriented; no machine-parsing
contract (A-011).

## Contract: `.sue-debug/` (exit-3 path only)

- Type: Directory of plain-text files
- Provider: the ADR-006 failure handler
- Consumers: operator diagnosing an unrecoverable parse failure offline (AC-015)
- Location: exactly 1 directory named `.sue-debug` beside the challenged specification
  (FR-030); created only when the second parse failure in a round occurs

| File | Content |
|------|---------|
| `round<R>-attempt<A>-stdout.txt` | raw stdout of that failing attempt (partial output for timeouts, prefixed by a `TIMEOUT after <T>s` line — ISS-207) |
| `round<R>-attempt<A>-stderr.txt` | raw stderr of that failing attempt |

Both failing attempts of the failing round are dumped (A ∈ {1, 2}); prior successful rounds
are not. Reruns overwrite files of the same name.

## Internal Interfaces

See `internal-interfaces.md`.
