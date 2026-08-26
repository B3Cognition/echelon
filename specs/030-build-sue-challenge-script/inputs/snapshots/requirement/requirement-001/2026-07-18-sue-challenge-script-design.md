# SUE Challenge Script — Design

**Date:** 2026-07-18
**Status:** approved (brainstorming session)
**Scope:** v1 of the Socratic Understanding Engine as a standalone script — the
question→answer dialogue tier only. No graphs, no convergence scoring, no workflow
integration.

## Purpose

Challenge a specification by generating Socratic questions and testing whether the
specification itself can answer them. Questions the spec text cannot answer are the
findings. This operationalizes the session's grounding rule: *the engine asks, the
text testifies, the human decides.*

## Interface

```
python3 scripts/sue_challenge.py <path/to/spec.md> [--questions N] [--claude-cmd CMD] [--timeout SECS]
```

- `--questions` — max questions generated in round 1 (default 15)
- `--claude-cmd` — the claude binary/command to invoke (default `claude`); also the test seam
- `--timeout` — per-call timeout in seconds (default 300)

Exit codes: 0 success (report written), 1 bad input (spec missing/unreadable),
2 claude CLI unavailable, 3 unrecoverable model-output parse failure.

## Mechanism (two fresh `claude -p` calls)

1. **Round 1 — question generation.** Input: the spec text plus an instruction to
   produce up to N Socratic challenge questions targeting ambiguity, hidden
   assumptions, contradictions, undefined terms, and missing boundaries. Each
   question is tagged with its target requirement ID and source line references.
   Output: strict JSON.
2. **Round 2 — the Socratic test.** A fresh call that receives ONLY the spec text and
   the round-1 questions (not round-1 reasoning). For each question it must answer
   using only the spec text and assign a verdict:
   - `ANSWERED` — the spec answers it; quote the answering lines
   - `UNANSWERABLE` — the spec is silent; state what is missing
   - `CONTRADICTED` — the spec gives conflicting answers; quote both sides
3. **Deterministic assembly (no third model call).** Findings = `CONTRADICTED` +
   `UNANSWERABLE`, ranked contradictions first. `ANSWERED` questions are kept in a
   collapsed audit section so the filter itself can be reviewed.

## Isolation contract

- Both calls run via `subprocess` with the working directory set to a neutral temp
  directory, because `claude -p` loads CLAUDE.md from cwd — repo context must not
  leak into the reading.
- Round 2 must not see round-1 rationale, only the questions and the spec.

## Round JSON schemas

Round 1: `{"questions": [{"id": "Q1", "question": str, "target": "REQ-nnn"|"general",
"lines": [int], "category": "ambiguity"|"assumption"|"contradiction"|"undefined-term"|"boundary"}]}`

Round 2: `{"answers": [{"id": "Q1", "verdict": "ANSWERED"|"UNANSWERABLE"|"CONTRADICTED",
"answer": str, "evidence_lines": [int]}]}` — every round-1 id must appear exactly once;
missing/extra ids are a parse failure (retry path).

## Output

`<spec-dir>/socratic-challenge.md` next to the challenged spec, plus a stdout summary
(finding counts and top 3). Reruns overwrite the previous report (v1 keeps no history —
the file is regenerable). Report sections:

1. Header: spec path, run date, question/finding counts
2. Findings: verdict, question, target REQ, evidence (quoted lines or the named gap)
3. Audit appendix: answered-and-discarded questions with their answering lines

## Error handling

- `claude` not found → exit 2 with an install pointer (mirrors the workbench spec's
  ERR-CLI-MISSING pattern)
- Model output fails JSON parsing → one corrective retry appended to the same prompt;
  second failure → exit 3, raw output saved to `<spec-dir>/.sue-debug/` for diagnosis
- Spec path missing/unreadable → exit 1 before any model call
- Per-call timeout (default 300s) → treated as parse failure path (retry once, then exit 3)

## Testing

- Unit tests (pytest, `tests/unit/test_sue_challenge.py`) for the deterministic parts:
  prompt assembly, JSON extraction/validation, verdict filtering and ranking, report
  rendering, exit codes. Model calls faked via `--claude-cmd` pointing at a stub
  executable that replays canned JSON.
- Acceptance: one manual live run against `specs/029-builder-spec-workbench/spec.md`;
  success = report generated and findings overlap the known issues (REQ-009/AC-010
  ordering contradiction; score-recording loop; undefined active-run pointer).

## Non-goals (v1)

Multi-reader consensus, interpretation graphs, convergence metrics, WHY3/workflow
integration, encoding answers back into specs, `echelon` CLI verb. The script's
interface (spec path in, markdown report out) is stable under all of these later
additions.
