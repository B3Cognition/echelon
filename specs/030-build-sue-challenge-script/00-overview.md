# SUE Challenge Script — Domain Overview

## Summary

The SUE challenge script is a standalone developer tool that stress-tests a markdown specification by interrogating it. It runs a two-round Socratic dialogue against a challenge model: round 1 generates up to 15 probing questions targeting five weakness categories (ambiguity, hidden assumption, contradiction, undefined term, missing boundary); round 2 is a fresh, isolated reading that must answer each question using only the specification text, assigning each a verdict — ANSWERED, UNANSWERABLE, or CONTRADICTED. Everything after round 2 is pure local computation: CONTRADICTED and UNANSWERABLE answers become findings (contradictions ranked first), ANSWERED questions are preserved in a collapsed audit appendix so the filtering itself can be reviewed, and the whole result is written as `socratic-challenge.md` beside the challenged specification.

The design principle is the grounding rule: *the engine asks, the text testifies, the human decides.* The tool never judges a specification by opinion — a finding exists only because the specification's own text failed to answer a question. Two isolation guarantees protect that property: every model call runs from a neutral temporary working directory so repository-level ambient context cannot color the reading, and round 2 receives only the bare questions — never round 1's reasoning — so the answering pass stays a blind reader. Model output crosses a trust boundary and is validated strictly: schemas per round, an identifier bijection check (every question answered exactly once), one corrective retry per round, and a debug dump plus exit code 3 when output stays unusable.

This is v1 of the Socratic Understanding Engine: the question-to-answer dialogue tier only, implemented exactly per the approved 2026-07-18 design. It is deliberately standalone — no orchestration imports, no project configuration reads, no workflow integration — and its interface (specification path in, markdown report out) is the stable contract that later tiers (multi-reader consensus, interpretation graphs, convergence scoring) will build on without rework.

## Dependency Graph

CLI & input validation → prompt assembly → model invocation (round 1) → extraction & validation → model invocation (round 2) → extraction & bijection check → deterministic assembly → report rendering & terminal summary

Every stage can short-circuit to a defined exit code: 1 (bad input, before any model call), 2 (model command unavailable), 3 (output unusable after one corrective retry).

## Stakeholders

| Role | Interests | Key Scenarios |
|------|-----------|---------------|
| Script operator | Trustworthy findings, clear failure behavior, no silent contamination of the reading | Story 1 (run & read), Story 3 (diagnose) |
| Specification author | Findings grounded in their actual text; auditable filtering; report never overstates authority | Story 2 (trust & audit) |
| Maintainer / designer | Exact fidelity to the approved v1 design; stable interface for later SUE tiers; fully testable deterministic core | Story 4 (verify offline) |

## Domain Areas

| Area | Description | Complexity | MVP? |
|------|-------------|------------|------|
| Command interface & input validation | Argument surface, pre-flight checks, fail-fast exit 1 | Low | Yes |
| Model invocation & isolation | Two isolated subprocess calls, temp-directory working dir, timeout, availability check | Medium | Yes |
| Round schemas & validation | Strict JSON schemas, extraction tolerance, identifier bijection, corrective retry | Medium | Yes |
| Deterministic assembly & report | Verdict partition, contradictions-first ranking, report with collapsed audit appendix, terminal summary | Low | Yes |
| Test seam & unit tests | Stub command substitution; offline unit coverage of every deterministic behavior | Low | Yes |

## Key Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Model output never cleanly extractable from the command's raw output (A-001/OQ-001) | Medium | High — retry budget exhausts, tool unusable | Extraction contract fixed in FR-017; OQ-001 spike before the HOW phase pins invocation flags and stub replay contract |
| Operator-level ambient context leaks into the reading despite the temporary working directory (A-002/OQ-002) | Medium | Medium — silent bias, no crash | Repo-scope isolation guaranteed by FR-006; residual exposure documented as a limitation; OQ-002 marker spike before HOW |
| Acceptance run flaky against a nondeterministic model | Medium | Medium — false FAIL or goalpost moving | Tolerance encoded in AC-023/SC-001: overlap ≥1 of 3 named issues, ≤3 attempts; re-verify or freeze the acceptance target first (A-004) |
| Challenged specification content egresses to the model provider | Certain (by design) | Depends on content | Disclosure required by NFR-003; operators decide per-specification suitability |
| Oversized specification silently truncated in the model's context | Low for realistic specs | Medium — evidence cites unseen lines | Documented limitation (A-005); size measured during the acceptance run |
