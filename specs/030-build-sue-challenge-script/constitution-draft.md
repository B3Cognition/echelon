<!--
SYNC IMPACT REPORT
==================
Version change: 1.0.0 (echelon-builder-fe — superseded stale artifact) → 1.0.0 (sue-challenge-script)
Bump rationale: Re-ratification under a new project domain. The prior file at
.specify/memory/constitution.md belonged to an unrelated squad run (echelon Builder FE,
spec 029 era; that file had itself replaced url-shortener, which had replaced
word-frequency-cli). Following this workspace's established supersession pattern, it is
replaced in full. This is the initial ratification of the SUE Challenge Script constitution
(MAJOR baseline, 1.0.0) for spec 030-build-sue-challenge-script.

NOTE ON PLACEMENT: this dispatch's Write/Edit tool permissions were not granted (headless
run without approved permission bypass), so the canonical write to
.specify/memory/constitution.md could not be performed by CHIEF. This file is the complete,
validated constitution authored via the speckit.constitution skill flow, staged for
promotion. Promotion = copy this file verbatim to .specify/memory/constitution.md
(whole-file replacement of the stale Builder FE constitution) and remove this NOTE block.

Principles defined:
  I.   Standalone Means Standalone (NON-NEGOTIABLE)
  II.  The Isolation Contract (NON-NEGOTIABLE)
  III. Model Output Is Untrusted Input (NON-NEGOTIABLE)
  IV.  Grounded Findings via Deterministic Assembly
  V.   Stable CLI Contract & Design Fidelity (NON-NEGOTIABLE)

Added sections:
  - Domain Semantics, Defaults & Deferred Decisions
  - Development Workflow & Quality Gates
  - Governance

Removed sections: none (whole-file replacement of an unrelated prior constitution)

Templates requiring updates:
  ✅ .specify/templates/plan-template.md   — generic Constitution Check; aligns, no edit required
  ✅ .specify/templates/spec-template.md   — no mandatory section added/removed by this constitution
  ✅ .specify/templates/tasks-template.md  — tests-first / unit-test categories already compatible
  ✅ .specify/templates/commands/*.md      — directory absent; no agent-specific references to update

Follow-up TODOs: none. All placeholders resolved with concrete values. Genuinely open
design silences (U-001…U-007 class) are recorded as explicit Deferred Decisions, not as
unresolved placeholders.
-->

# SUE Challenge Script Constitution

This constitution governs **SUE v1 — the Socratic Understanding Engine challenge script**: a
standalone Python script at `scripts/sue_challenge.py` that challenges a markdown specification
via a two-round Socratic question→answer dialogue using two isolated `claude -p` calls, and
renders the result as `socratic-challenge.md` beside the challenged spec. It is binding on every
plan, spec, task, and pull request for this project. The project implements an **approved design
document** exactly at v1 scope; these principles exist to keep the implementation faithful to
that design, isolated from ambient context, and safe against untrusted model output.

## Core Principles

### I. Standalone Means Standalone (NON-NEGOTIABLE)

The script is a self-contained developer tool in the repo's `scripts/` directory, in the shape
of the existing precedent `scripts/contradiction-scanner.py`: stdlib-only, argparse, own exit
codes.

- The script MUST use only the Python standard library; it MUST NOT import anything from
  `src/harness` or `src/echelon`, and MUST NOT read `echelon-config.yml`.
- The echelon harness's `claude -p` machinery (`ClaudeCliProvider`, `ai_cli_backend`,
  stream-json output, tool policy, repo cwd) serves a different contract and MUST NOT be
  reused, wrapped, or imported.
- The script is host tooling: it is NOT deployed by the extension and MUST NOT acquire an
  `echelon` CLI verb or workflow integration in v1.
- Unit tests MUST run from the repo checkout without a live model and without the installed
  `~/.echelon/venv`.

**Rationale:** "Standalone" is an explicit user requirement, not an implementation preference.
Coupling to harness internals would contradict the design's stable-interface promise, break the
pytest stub seam, and entangle SUE's plain strict-JSON contract with a stream-json/tool-policy
contract built for a different purpose.

### II. The Isolation Contract (NON-NEGOTIABLE)

SUE's analytical value depends on the model reading the spec blind — uncontaminated by repo
context and by its own earlier reasoning.

- Both `claude -p` subprocesses MUST run with the working directory pinned to a neutral
  temporary directory, so the repo's CLAUDE.md (and any cwd-scoped context) cannot leak into
  the model's reading.
- Round 2 MUST receive ONLY the spec text and the bare round-1 questions (question text + ids).
  Round-1 rationale, categories-as-argument, or any other round-1 reasoning MUST NOT be passed
  forward. Prompt assembly is the enforcement point for this data-flow rule.
- A silent isolation failure is a **correctness failure**, not a crash. If the designed
  mechanism (temp cwd) proves insufficient — e.g. user-scope configuration such as
  `~/.claude/CLAUDE.md` still influences the reading — the gap MUST be surfaced and resolved as
  an explicit, traceable decision (documented limitation or documented amendment), NEVER
  silently accepted and NEVER silently patched with unapproved mechanisms.

**Rationale:** The user named "isolated" in the one-sentence summary of the request; isolation
is first-class intent. The mechanism (temp cwd) is the designed means; the outcome (repo context
must not bias the reading) is the requirement. Conflating the two in either direction deviates
from "exactly as designed".

### III. Model Output Is Untrusted Input (NON-NEGOTIABLE)

Everything returned by `claude -p` crosses a trust boundary and MUST be validated before use.

- Model output MUST pass strict JSON extraction and schema validation: round 1 (questions:
  `id`, `question`, `target`, `lines`, `category` ∈ {ambiguity, assumption, contradiction,
  undefined-term, boundary}) and round 2 (answers: `id`, `verdict` ∈ {ANSWERED, UNANSWERABLE,
  CONTRADICTED}, `answer`, `evidence_lines`).
- The ID bijection rule MUST be enforced: every round-1 question id appears exactly once in the
  round-2 answers; missing or extra ids are parse failures.
- Validation violations MUST NEVER crash the script. They route to exactly one corrective retry
  per round (corrective instruction appended to the same prompt, fresh timeout budget); a
  second failure exits 3 with raw output saved to `<spec-dir>/.sue-debug/`. A per-call timeout
  takes the same path. There is no cross-round retry: a round-2 failure MUST NOT re-run round 1.
- The exit-code contract is fixed and evaluated in order: exit 1 — spec path missing/unreadable,
  before any model call; exit 2 — claude command unavailable, with an install pointer
  (ERR-CLI-MISSING pattern, mirroring spec 029); exit 3 — output unusable after retry; exit 0 —
  only after the report is written.

**Rationale:** The model is the script's entire analytical capability and its least reliable
component. Typed, ordered failure paths are what make a two-model-call tool usable and
diagnosable; ad-hoc crash behaviour would make every malformed response a support incident.

### IV. Grounded Findings via Deterministic Assembly

"The engine asks, the text testifies, the human decides."

- Only the spec text supplies answers: questions are answered by the text itself, never by the
  human and never by model knowledge presented as spec content. Verdicts MUST carry evidence —
  answering lines quoted for ANSWERED, the named gap for UNANSWERABLE, both conflicting sides
  quoted for CONTRADICTED.
- Everything after round 2 MUST be pure local computation — no third model call. Deterministic
  assembly filters CONTRADICTED + UNANSWERABLE answers into findings, ranks contradictions
  first, and renders the report.
- ANSWERED questions are not findings but MUST be retained in the report's audit appendix
  (rendered **collapsed**) so the filtering itself can be reviewed by the human.
- The challenged spec is read-only: a run MUST NEVER mutate it. The report
  `<spec-dir>/socratic-challenge.md` is regenerable, not a record: reruns overwrite; v1 keeps
  no history.

**Rationale:** The grounding rule is the design's supreme correctness property — it is what
distinguishes SUE findings (gaps the text demonstrably cannot answer) from generic model
opinions about a spec. Deterministic assembly keeps the judgment surface auditable and fully
unit-testable.

### V. Stable CLI Contract & Design Fidelity (NON-NEGOTIABLE)

The approved design document is the authority; the CLI interface is the stable seam all future
SUE tiers build on.

- The interface is: positional spec path; `--questions` (default 15); `--claude-cmd` (default
  `claude`, doubling as the test seam); `--timeout` (default 300, per subprocess invocation);
  exit codes 0/1/2/3 with the meanings fixed in Principle III; markdown report out. This is the
  most change-sensitive surface of the project; any change to it is a constitutional amendment.
- "Implement exactly the v1 scope" cuts both ways: no silent trimming of designed details (the
  collapsed audit rendering is the canonical example — it MUST survive into spec and code), and
  no expansion beyond v1. The v1 non-goals are binding scope walls: no interpretation graphs,
  no convergence scoring, no multi-reader consensus, no workflow or `echelon` CLI integration,
  no encoding answers back into specs, no report history, no machine-readable output modes.
- Where the design is silent, resolutions MUST be the minimal decision that pins behaviour for
  tests — never a new feature. Each such resolution MUST be recorded as an explicit, traceable
  decision in the spec.
- The squad MAY challenge the design (and MUST surface material concerns) but MUST NOT silently
  override it. Any material deviation from designed behaviour — including relaxing an approved
  acceptance criterion — requires an explicit, written, traceable decision.

**Rationale:** The dominant risk of this project is fidelity erosion: small designed details or
approved criteria drifting during formalization, and design-silence resolutions accreting into
unapproved features. This principle makes drift detectable and deliberate deviation cheap to
audit.

## Domain Semantics, Defaults & Deferred Decisions

These are the canonical defaults for SUE v1; any change is an amendment to this constitution.

**Settled defaults:**

- **Deliverable:** exactly one script, `scripts/sue_challenge.py`, plus its unit tests at
  `tests/unit/test_sue_challenge.py`.
- **Run shape:** validate input → check claude availability → round 1 → validate → round 2 →
  validate + bijection → deterministic assembly → write report + stdout summary → exit 0. Two
  logical model calls; 2–4 subprocess invocations including retries.
- **Report:** `<spec-dir>/socratic-challenge.md` with (1) header — spec path, run date,
  question/finding counts; (2) findings — verdict, question, target REQ, evidence,
  contradictions ranked first; (3) audit appendix of ANSWERED questions with their answering
  lines, rendered collapsed. Stdout summary prints finding counts and the top 3 findings; it is
  human-oriented with no machine-parsing contract in v1.
- **Question ids:** `Q1`…`Qn`; within each verdict class, report ordering follows round-1 order.
- **Data egress posture:** challenged-spec content is sent to the model provider via the
  operator's claude CLI session; the `--claude-cmd` seam executes an operator-supplied command.
  This is accepted developer-tool trust: a single trusted local operator, no auth surface.
  Specs containing sensitive material inherit the operator's claude CLI data-handling posture —
  this MUST be stated in user-facing documentation, not hidden.

**Deferred decisions (explicitly OPEN — MUST be resolved as minimal, traceable,
behaviour-pinning decisions during specification/planning; silent assumptions are prohibited):**

- **U-001 — `claude -p` invocation semantics:** prompt via argv vs stdin, and the exact raw
  stdout form from which strict JSON is extracted. Resolve by spiking one real call from a temp
  cwd before freezing prompt-assembly and extraction design.
- **U-002 — isolation sufficiency:** whether temp cwd alone excludes user-scope context
  (`~/.claude/CLAUDE.md`, global settings, MCP servers). Resolve per Principle II: documented
  limitation or documented suppression mechanism — an explicit decision either way.
- **U-003 — corrective-retry wording:** the exact corrective instruction appended on retry.
- **U-004 — `--claude-cmd` parsing:** whether the value is split shell-style or treated as a
  single executable name.
- **U-005 — degenerate outcomes:** behaviour when round 1 yields zero questions, and the exit
  code when `<spec-dir>` is unwritable for the report.
- **U-006 — line provenance:** how spec line numbers are presented to the model so `lines` /
  `evidence_lines` are meaningful.
- **U-007 — exit-2 boundary:** the precise "command unavailable" detection (missing binary vs
  non-zero exit on probe).

## Development Workflow & Quality Gates

- **Test-First (hard gate):** Development follows TDD — tests are written first, observed to
  fail, then implemented to pass (Red-Green-Refactor). No behaviour is claimed complete without
  a passing test exercising it.
- **Full deterministic coverage via the stub seam:** every deterministic part — argument
  parsing and input validation, prompt assembly (including the round-2 information restriction),
  JSON extraction and schema validation, the ID bijection check, verdict filtering and ranking,
  report rendering, exit-code selection — MUST be unit-tested with model calls faked via a stub
  executable injected through `--claude-cmd`. Tests follow repo pytest conventions
  (`tests/unit/test_sue_challenge.py`, collected by the existing `pyproject.toml` config).
- **Acceptance (live validation):** one manual live run against
  `specs/029-builder-spec-workbench/spec.md`; success means the report is generated and the
  findings overlap the spec's three known issues (the REQ-009/AC-010 ordering contradiction,
  the score-recording loop, the undefined active-run pointer) — verified present at base commit
  ef2643c9. Spec 029 MUST be re-checked immediately before the acceptance run; if it has been
  amended, the current version MUST be snapshotted as the acceptance fixture. Any tolerance
  added to this criterion is a material AC edit and MUST be recorded as an explicit
  clarification decision with rationale — never a silent rewording.
- **Standalone review gate:** a reviewer MUST reject any code path that imports
  `harness.*`/`echelon.*`, reads `echelon-config.yml`, or requires the installed venv to run
  the unit tests (Principle I).
- A Deferred Decision MUST be resolved (recorded in the spec or as an amendment) before any
  code path relies on a specific answer to it.

## Governance

This constitution supersedes other development practices for this project. All plans, reviews,
and pull requests MUST verify compliance with the principles above; any deviation MUST be
justified in writing and approved before merge.

Amendments require: (1) a written description of the change and its rationale, (2) a version
bump per the policy below, and (3) propagation to dependent artifacts (plan, spec, and task
templates) in the same change.

Versioning policy (semantic):
- **MAJOR** — backward-incompatible governance change or removal/redefinition of a principle.
- **MINOR** — a new principle or section, or materially expanded guidance.
- **PATCH** — clarifications, wording, or non-semantic refinements.

Compliance is reviewed at each phase gate of the squad workflow; the NON-NEGOTIABLE principles
(I, II, III, and V) are hard gates and MUST NOT be waived. Because this project implements an
approved design document, any amendment that alters designed behaviour MUST cite the design
point it changes and the reason the deviation is necessary.

**Version**: 1.0.0 | **Ratified**: 2026-07-18 | **Last Amended**: 2026-07-18
