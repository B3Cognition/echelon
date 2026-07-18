# Domain Glossary

## Terms

### SUE (Socratic Understanding Engine)
- **Definition:** The overall engine concept for challenging specifications through Socratic dialogue. v1 delivers only its question→answer dialogue tier as a standalone script; graphs, convergence scoring, and workflow integration are explicitly out of scope (IN-REQ-8E578B6660BB, IN-REQ-032461DF1B5D).
- **Context:** Names the product; the v1 deliverable is the "SUE challenge script" at `scripts/sue_challenge.py`.
- **Disambiguation:** SUE (this engine) is distinct from the `understanding` CLI (the repo's 34-metric deterministic requirements-quality tool). Both assess specs; SUE is dialogic and model-driven, `understanding` is rule-based and deterministic.
- **Source:** user (design doc, IN-REQ-35B242FAD892)

### Socratic question
- **Definition:** A challenge question generated in round 1 that targets one of five weakness categories in the spec: ambiguity, hidden assumption, contradiction, undefined term, or missing boundary (IN-REQ-1C338DB49929, IN-REQ-FFF3DC4D608F).
- **Context:** Round-1 output; round-2 input. Each carries an id (`Q1`…), a target requirement ID (`REQ-nnn` or `general`), source line references, and a category.
- **Disambiguation:** Not the same as `speckit-clarify` clarification questions, which are answered by the human and encoded back into the spec. SUE questions are answered by the spec text itself, never by the human.
- **Source:** user (design doc)

### Round 1 (question generation)
- **Definition:** The first of two isolated `claude -p` calls. Input: spec text plus an instruction to produce up to N Socratic challenge questions. Output: strict JSON conforming to the round-1 schema (IN-REQ-FAF233549D79 … IN-REQ-046E9F3A20C7).
- **Context:** First model call of a challenge run. N defaults to 15 (`--questions`).
- **Source:** user (design doc)

### Round 2 (the Socratic test)
- **Definition:** The second isolated `claude -p` call. It receives ONLY the spec text and the round-1 questions — never round-1 reasoning — and must answer each question using only the spec text, assigning a verdict per question (IN-REQ-3709F66E4C4E, IN-REQ-7906C2CCFEBC).
- **Context:** Second model call; produces the answers that become findings.
- **Disambiguation:** "Fresh call" means a new subprocess with no conversational continuity from round 1. The isolation is the point: round 2 is a blind reader.
- **Source:** user (design doc)

### Verdict
- **Definition:** The round-2 classification of one question: `ANSWERED` (spec answers it; answering lines quoted), `UNANSWERABLE` (spec is silent; the gap is named), or `CONTRADICTED` (spec gives conflicting answers; both sides quoted) (IN-REQ-EED398D6F6E8 … IN-REQ-3E606DDF0F98).
- **Context:** Drives deterministic assembly: which answers become findings and how they rank.
- **Source:** user (design doc)

### Finding
- **Definition:** A `CONTRADICTED` or `UNANSWERABLE` answer. Findings are the report's payload, ranked with contradictions first (IN-REQ-97C434377BBE, IN-REQ-BEC67C964B9A).
- **Context:** Report section 2 and the stdout summary (counts + top 3).
- **Disambiguation:** `ANSWERED` questions are not findings — they are retained in the audit appendix so the filtering itself can be reviewed.
- **Source:** user (design doc)

### Deterministic assembly
- **Definition:** The third stage of the mechanism: pure local computation (no third model call) that filters answers into findings, ranks them, and renders the report (IN-REQ-97C434377BBE).
- **Context:** Everything after round 2. This is also the entire surface targeted by unit tests.
- **Source:** user (design doc)

### Isolation contract
- **Definition:** Two rules: (1) both `claude -p` subprocesses run with the working directory set to a neutral temp directory so repo CLAUDE.md context cannot leak into the reading; (2) round 2 must not see round-1 rationale, only the questions and the spec (IN-REQ-2F84DF72B209 … IN-REQ-7906C2CCFEBC).
- **Context:** The core correctness property distinguishing SUE from an ordinary in-repo model call.
- **Source:** user (design doc)

### Grounding rule
- **Definition:** "The engine asks, the text testifies, the human decides" — the engine generates questions, only the spec text supplies answers, and humans judge the findings (IN-REQ-BF81CFD48938, IN-REQ-7802BD15CC2F).
- **Context:** The design principle the whole mechanism operationalizes.
- **Source:** user (design doc)

### Challenge report (`socratic-challenge.md`)
- **Definition:** Markdown output written to `<spec-dir>/socratic-challenge.md`, next to the challenged spec. Sections: (1) header — spec path, run date, question/finding counts; (2) findings — verdict, question, target REQ, evidence; (3) audit appendix — answered-and-discarded questions with their answering lines. Reruns overwrite; v1 keeps no history (IN-REQ-44BED4ECFE26 … IN-REQ-31A836647EEC).
- **Context:** The primary artifact of a run; exit code 0 means it was written.
- **Source:** user (design doc)

### Test seam (`--claude-cmd`)
- **Definition:** The CLI flag naming the claude binary/command to invoke (default `claude`). Doubles as the unit-test injection point: tests point it at a stub executable that replays canned JSON (IN-REQ-D8FCFCDDC59E, IN-REQ-B9724D0168AB).
- **Context:** Interface and testing sections of the design.
- **Source:** user (design doc)

### Corrective retry
- **Definition:** On a JSON parse/validation failure of model output, one retry is made with a corrective instruction appended to the same prompt; a second failure exits 3 with raw output saved for diagnosis (IN-REQ-5086BCDE7BCE, IN-REQ-DAB2BB350DF1). Per-call timeouts take the same path (IN-REQ-35B2A2BF9F9D).
- **Context:** Error handling; the only recovery mechanism in v1.
- **Source:** user (design doc)

### Debug dump (`.sue-debug/`)
- **Definition:** Directory under `<spec-dir>` receiving raw model output after an unrecoverable parse failure, for offline diagnosis (IN-REQ-DAB2BB350DF1).
- **Context:** Exit-3 path only.
- **Source:** user (design doc)

### ID bijection rule
- **Definition:** Every round-1 question id must appear exactly once in the round-2 answers; missing or extra ids are a parse failure that takes the retry path (IN-REQ-D003F04C0FC3, IN-REQ-0F5AB554CF9C).
- **Context:** Round-2 JSON validation; the strongest structural check on model output.
- **Source:** user (design doc)

### ERR-CLI-MISSING pattern
- **Definition:** The established repo pattern (spec 029 builder-spec-workbench) for a missing external CLI binary: report unavailability with an install pointer and degrade rather than crash opaquely. SUE mirrors it as exit 2 with an install pointer when `claude` is not found (IN-REQ-49464B14EFA0, IN-REQ-CE9317854005; verified at `specs/029-builder-spec-workbench/boundaries.md:42`).
- **Context:** Error handling for the claude CLI dependency.
- **Source:** code + user (design doc)

### Challenged spec
- **Definition:** The markdown specification file passed as the script's positional argument — the object under interrogation. Missing/unreadable path exits 1 before any model call (IN-REQ-F7DA9407BAE0, IN-REQ-09CAF50DCD15).
- **Context:** Sole required input.
- **Source:** user (design doc)

### Acceptance run
- **Definition:** One manual live run against `specs/029-builder-spec-workbench/spec.md`; success = report generated and findings overlap the spec's known issues: the REQ-009/AC-010 ordering contradiction, the score-recording loop, and the undefined active-run pointer (IN-REQ-760CA37F3F8F … IN-REQ-D05A70A0F5B4; issue anchors verified present in `specs/029-builder-spec-workbench/spec.md`).
- **Context:** Testing section; the only live-model validation in v1.
- **Source:** user (design doc) + code (spec 029 verified)

## Overloaded Terms

| Term | Context A | Meaning A | Context B | Meaning B |
|------|-----------|-----------|-----------|-----------|
| spec | SUE script input | Any markdown specification file being challenged (arbitrary path) | Echelon workflow | A `specs/{NNN-slug}/spec.md` artifact produced by Phase A — SUE must not assume this layout beyond "report goes next to the file" |
| question | SUE round 1 | Model-generated Socratic challenge answered by the spec text | speckit-clarify | Clarification question answered by the human and encoded back into the spec |
| timeout | SUE `--timeout` | Per-model-call subprocess timeout in seconds (default 300) | harness config | `llm.timeout_ms` consumed by `ClaudeCliProvider` — unrelated configuration surface |
| `claude -p` | SUE mechanism | Isolated one-shot call from a neutral temp cwd, plain strict-JSON contract | echelon harness | `ClaudeCliProvider`/`ai_cli_backend` invocation with stream-json, tool policy, and repo cwd — deliberately NOT reused by SUE |
| round | SUE mechanism | One of the two model calls (generation / test) | echelon review loop | A PR review-fix iteration (`review-fix-{n}`) — unrelated |
| finding | SUE report | An UNANSWERABLE or CONTRADICTED answer | understanding CLI / code review | A metric violation or review issue — different producers, same word |
| challenge | SUE | The whole interrogation run against a spec | WHY phases (SAGE) | Adversarial assumption challenge inside the squad workflow |
