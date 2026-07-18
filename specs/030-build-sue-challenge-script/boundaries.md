# System Boundaries

## Internal Boundaries

### Input validation & CLI surface
- **Responsibility:** Argument parsing (`spec path`, `--questions`, `--claude-cmd`, `--timeout`), spec readability check, fail-fast exit 1 before any model call.
- **Interfaces:** Process argv in; validated run configuration out to the orchestration flow.
- **Data ownership:** Run configuration (paths, N, command, timeout).

### Prompt assembly
- **Responsibility:** Building the round-1 prompt (spec text + question-generation instruction, N cap, category taxonomy, schema demand) and the round-2 prompt (spec text + bare questions + verdict instruction + schema demand); building the corrective-retry appendix.
- **Interfaces:** Takes spec text and (for round 2) parsed questions; emits prompt strings. Explicitly must NOT pass round-1 rationale into round 2 (isolation contract).
- **Data ownership:** Prompt templates and the round instructions.

### Model invocation (subprocess runner)
- **Responsibility:** Spawning the claude command with the prompt, cwd pinned to a neutral temp directory, enforcing the per-call timeout, capturing raw output, distinguishing "command unavailable" (exit 2) from "output unusable" (retry → exit 3).
- **Interfaces:** Prompt string in; raw output or a typed failure out. The command executed is the `--claude-cmd` value — this boundary is the test seam.
- **Data ownership:** Subprocess lifecycle, temp working directory, raw outputs.

### JSON extraction & validation
- **Responsibility:** Extracting strict JSON from model output; validating round-1 schema (questions: id, question, target, lines, category enum) and round-2 schema (answers: id, verdict enum, answer, evidence_lines); enforcing the ID bijection rule (every round-1 id exactly once); classifying violations as parse failures feeding the retry path.
- **Interfaces:** Raw output in; typed question/answer collections or a parse-failure signal out.
- **Data ownership:** Schema definitions and validation rules.

### Verdict filtering & ranking (deterministic assembly)
- **Responsibility:** Partitioning answers into findings (CONTRADICTED + UNANSWERABLE, contradictions first) and audit entries (ANSWERED); no model call.
- **Interfaces:** Validated answers in; ordered findings + audit list out.
- **Data ownership:** Ranking policy.

### Report rendering & summary
- **Responsibility:** Rendering `socratic-challenge.md` (header / findings / audit appendix), overwriting any prior report, writing the `.sue-debug/` dump on the exit-3 path, printing the stdout summary (finding counts + top 3).
- **Interfaces:** Findings + audit entries + run metadata in; files and stdout out.
- **Data ownership:** Report format; `<spec-dir>/socratic-challenge.md` and `<spec-dir>/.sue-debug/`.

## External Boundaries

### claude CLI (`claude -p`)
- **Type:** external CLI / AI model gateway
- **Dependency strength:** hard — the script's entire analytical capability
- **Data flow:** outbound: spec text + instructions (twice); inbound: model-generated JSON. Note: spec content leaves the local process and is sent to the model provider via the CLI.
- **Failure impact:** command missing → exit 2 with install pointer (ERR-CLI-MISSING pattern, mirrors spec 029); hung call → per-call timeout → parse-failure path; malformed output → one corrective retry then exit 3.

### Filesystem — challenged spec (read side)
- **Type:** infrastructure
- **Dependency strength:** hard
- **Data flow:** inbound spec text only; the run never mutates the spec.
- **Failure impact:** missing/unreadable → exit 1 before any model call.

### Filesystem — `<spec-dir>` (write side)
- **Type:** infrastructure
- **Dependency strength:** hard for success (exit 0 requires the report written)
- **Data flow:** outbound: `socratic-challenge.md` (overwrite), `.sue-debug/` raw dumps on failure.
- **Failure impact:** unwritable spec-dir prevents success; design is silent on the exact exit code for a write failure (tracked as an unknown).

### Neutral temp directory
- **Type:** infrastructure (isolation mechanism)
- **Dependency strength:** hard — carries the isolation contract
- **Data flow:** used only as subprocess cwd so `claude -p` does not load the repo's CLAUDE.md; nothing meaningful is written there.
- **Failure impact:** if cwd isolation is skipped or ineffective, repo context contaminates the model's reading — silent correctness failure, not a crash.

### pytest / stub executable (development boundary)
- **Type:** test infrastructure
- **Dependency strength:** soft (dev-time only)
- **Data flow:** unit tests in `tests/unit/test_sue_challenge.py` drive the script with `--claude-cmd` pointing at a stub that replays canned JSON; repo pytest config collects `tests/` with `src`/`.` on pythonpath.
- **Failure impact:** none at runtime.

### Echelon harness / extension (explicit NON-boundary)
- **Type:** neighbouring system, deliberately not integrated
- **Dependency strength:** none — v1 non-goals exclude the `echelon` CLI verb and workflow integration; the script must not import `src/harness` (whose `ClaudeCliProvider`/`ai_cli_backend` serve a different contract: stream-json, tool policy, repo cwd).
- **Data flow:** none. The stable contract for later integration is exactly the CLI interface: spec path in, markdown report out.
- **Failure impact:** n/a — but accidental coupling here would violate the standalone design.

## Trust Boundaries

- **Model output is untrusted input.** Everything returned by `claude -p` crosses a trust boundary and is validated as strict JSON against the round schemas, including the enum values and the round-2 ID bijection. Failures never crash the script; they route to retry/exit-3.
- **Context isolation boundary.** The neutral temp cwd is a deliberate barrier preventing ambient repo instructions (CLAUDE.md) from influencing the model's reading. Residual risk: user-level configuration (e.g. `~/.claude/CLAUDE.md`, global settings) is outside cwd control — see A-002/U-002.
- **Inter-round information boundary.** Round 2 may see only the spec text and the bare questions; round-1 reasoning is stripped. This is a data-flow rule enforced by prompt assembly, not by the model.
- **Local trust.** The spec file and CLI arguments are trusted local input from the operator; no authentication/authorization surface exists. The `--claude-cmd` seam executes an arbitrary operator-supplied command — acceptable for a developer tool, but it is an execution trust boundary worth stating.
- **Data egress.** Challenged spec content is sent to the model provider through the claude CLI; specs containing sensitive material inherit whatever data-handling posture the operator's claude CLI session has.
