# Requirement Product Inputs

## IN-REQ-35B242FAD892
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:1`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: # SUE Challenge Script — Design

## IN-REQ-DA5A2A3AEAB5
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:3`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: **Date:** 2026-07-18

## IN-REQ-7698BBDFCDF2
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:4`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: **Status:** approved (brainstorming session)

## IN-REQ-8E578B6660BB
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:5`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: **Scope:** v1 of the Socratic Understanding Engine as a standalone script — the

## IN-REQ-032461DF1B5D
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:6`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: question→answer dialogue tier only. No graphs, no convergence scoring, no workflow

## IN-REQ-9C4F8635A18F
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:7`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: integration.

## IN-REQ-F565489C0B76
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:9`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: ## Purpose

## IN-REQ-60DEBB978E62
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:11`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: Challenge a specification by generating Socratic questions and testing whether the

## IN-REQ-B0E70720E09A
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:12`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: specification itself can answer them. Questions the spec text cannot answer are the

## IN-REQ-BF81CFD48938
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:13`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: findings. This operationalizes the session's grounding rule: *the engine asks, the

## IN-REQ-7802BD15CC2F
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:14`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: text testifies, the human decides.*

## IN-REQ-AA478A158AB9
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:16`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: ## Interface

## IN-REQ-3EA7EE65BD18
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:18`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: ```

## IN-REQ-F7DA9407BAE0
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:19`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: python3 scripts/sue_challenge.py <path/to/spec.md> [--questions N] [--claude-cmd CMD] [--timeout SECS]

## IN-REQ-B41782F5561C
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:20`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: ```

## IN-REQ-75BC4F8B9974
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:22`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: - `--questions` — max questions generated in round 1 (default 15)

## IN-REQ-D8FCFCDDC59E
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:23`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: - `--claude-cmd` — the claude binary/command to invoke (default `claude`); also the test seam

## IN-REQ-F124765D491A
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:24`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: - `--timeout` — per-call timeout in seconds (default 300)

## IN-REQ-E8F14EBD27A7
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:26`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: Exit codes: 0 success (report written), 1 bad input (spec missing/unreadable),

## IN-REQ-2189E42069FA
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:27`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: 2 claude CLI unavailable, 3 unrecoverable model-output parse failure.

## IN-REQ-CF04C07BA415
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:29`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: ## Mechanism (two fresh `claude -p` calls)

## IN-REQ-FAF233549D79
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:31`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: 1. **Round 1 — question generation.** Input: the spec text plus an instruction to

## IN-REQ-1C338DB49929
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:32`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: produce up to N Socratic challenge questions targeting ambiguity, hidden

## IN-REQ-FFF3DC4D608F
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:33`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: assumptions, contradictions, undefined terms, and missing boundaries. Each

## IN-REQ-D50BEC5F92D0
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:34`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: question is tagged with its target requirement ID and source line references.

## IN-REQ-046E9F3A20C7
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:35`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: Output: strict JSON.

## IN-REQ-3709F66E4C4E
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:36`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: 2. **Round 2 — the Socratic test.** A fresh call that receives ONLY the spec text and

## IN-REQ-15BAE48979B6
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:37`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: the round-1 questions (not round-1 reasoning). For each question it must answer

## IN-REQ-8470DD94F1D6
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:38`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: using only the spec text and assign a verdict:

## IN-REQ-EED398D6F6E8
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:39`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: - `ANSWERED` — the spec answers it; quote the answering lines

## IN-REQ-D1279F33E7C9
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:40`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: - `UNANSWERABLE` — the spec is silent; state what is missing

## IN-REQ-3E606DDF0F98
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:41`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: - `CONTRADICTED` — the spec gives conflicting answers; quote both sides

## IN-REQ-97C434377BBE
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:42`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: 3. **Deterministic assembly (no third model call).** Findings = `CONTRADICTED` +

## IN-REQ-BEC67C964B9A
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:43`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: `UNANSWERABLE`, ranked contradictions first. `ANSWERED` questions are kept in a

## IN-REQ-2D4902546481
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:44`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: collapsed audit section so the filter itself can be reviewed.

## IN-REQ-242349C9B920
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:46`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: ## Isolation contract

## IN-REQ-2F84DF72B209
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:48`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: - Both calls run via `subprocess` with the working directory set to a neutral temp

## IN-REQ-DDDD35B79FFA
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:49`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: directory, because `claude -p` loads CLAUDE.md from cwd — repo context must not

## IN-REQ-1A64043748C4
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:50`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: leak into the reading.

## IN-REQ-7906C2CCFEBC
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:51`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: - Round 2 must not see round-1 rationale, only the questions and the spec.

## IN-REQ-E431AE277766
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:53`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: ## Round JSON schemas

## IN-REQ-1BB9602CB2BA
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:55`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: Round 1: `{"questions": [{"id": "Q1", "question": str, "target": "REQ-nnn"|"general",

## IN-REQ-D67B2760CFF6
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:56`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: "lines": [int], "category": "ambiguity"|"assumption"|"contradiction"|"undefined-term"|"boundary"}]}`

## IN-REQ-FFF8B8176BC8
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:58`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: Round 2: `{"answers": [{"id": "Q1", "verdict": "ANSWERED"|"UNANSWERABLE"|"CONTRADICTED",

## IN-REQ-D003F04C0FC3
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:59`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: "answer": str, "evidence_lines": [int]}]}` — every round-1 id must appear exactly once;

## IN-REQ-0F5AB554CF9C
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:60`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: missing/extra ids are a parse failure (retry path).

## IN-REQ-C03A6B2ECF2B
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:62`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: ## Output

## IN-REQ-44BED4ECFE26
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:64`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: `<spec-dir>/socratic-challenge.md` next to the challenged spec, plus a stdout summary

## IN-REQ-AF7AFAF68FBD
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:65`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: (finding counts and top 3). Reruns overwrite the previous report (v1 keeps no history —

## IN-REQ-D305BB37F9EB
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:66`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: the file is regenerable). Report sections:

## IN-REQ-A06052CA8E2C
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:68`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: 1. Header: spec path, run date, question/finding counts

## IN-REQ-EBFAED130BFF
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:69`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: 2. Findings: verdict, question, target REQ, evidence (quoted lines or the named gap)

## IN-REQ-31A836647EEC
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:70`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: 3. Audit appendix: answered-and-discarded questions with their answering lines

## IN-REQ-276774A45535
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:72`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: ## Error handling

## IN-REQ-49464B14EFA0
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:74`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: - `claude` not found → exit 2 with an install pointer (mirrors the workbench spec's

## IN-REQ-CE9317854005
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:75`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: ERR-CLI-MISSING pattern)

## IN-REQ-5086BCDE7BCE
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:76`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: - Model output fails JSON parsing → one corrective retry appended to the same prompt;

## IN-REQ-DAB2BB350DF1
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:77`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: second failure → exit 3, raw output saved to `<spec-dir>/.sue-debug/` for diagnosis

## IN-REQ-09CAF50DCD15
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:78`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: - Spec path missing/unreadable → exit 1 before any model call

## IN-REQ-35B2A2BF9F9D
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:79`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: - Per-call timeout (default 300s) → treated as parse failure path (retry once, then exit 3)

## IN-REQ-C806E13967B4
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:81`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: ## Testing

## IN-REQ-B97DBA8344BE
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:83`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: - Unit tests (pytest, `tests/unit/test_sue_challenge.py`) for the deterministic parts:

## IN-REQ-BE91B88E2D80
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:84`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: prompt assembly, JSON extraction/validation, verdict filtering and ranking, report

## IN-REQ-B9724D0168AB
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:85`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: rendering, exit codes. Model calls faked via `--claude-cmd` pointing at a stub

## IN-REQ-18F823464DCC
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:86`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: executable that replays canned JSON.

## IN-REQ-760CA37F3F8F
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:87`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: - Acceptance: one manual live run against `specs/029-builder-spec-workbench/spec.md`;

## IN-REQ-A78CE7C82F30
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:88`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: success = report generated and findings overlap the known issues (REQ-009/AC-010

## IN-REQ-D05A70A0F5B4
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:89`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: ordering contradiction; score-recording loop; undefined active-run pointer).

## IN-REQ-64F3FEA20D8C
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:91`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: ## Non-goals (v1)

## IN-REQ-4E9070D640A5
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:93`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: Multi-reader consensus, interpretation graphs, convergence metrics, WHY3/workflow

## IN-REQ-D9CE68110258
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:94`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: integration, encoding answers back into specs, `echelon` CLI verb. The script's

## IN-REQ-128505B4CC53
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:95`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: interface (spec path in, markdown report out) is stable under all of these later

## IN-REQ-C68D7D0CB17E
- Source: `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md:line:96`
- Snapshot: `snapshots/requirement/requirement-001/2026-07-18-sue-challenge-script-design.md`
- Evidence: additions.
