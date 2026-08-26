# Unknowns

## Known Unknowns

### U-001: How exactly is the prompt delivered to `claude -p`, and with which output flags?
- **Why it matters:** The design fixes the mechanism ("two fresh `claude -p` calls") but not the invocation details: prompt via argv or stdin, whether an output-format flag is used, how stdout is shaped. This decides the JSON-extraction design and the stub executable's replay contract. The repo's only prior art (`harness/ai_cli_backend`) uses stream-json — a contract SUE explicitly does not want.
- **Who can answer:** experimentation (one spike call) | INVESTIGATOR
- **Priority:** should-resolve-before-HOW
- **Related assumptions:** A-001, A-009

### U-002: Does a neutral temp cwd fully satisfy the isolation contract?
- **Why it matters:** cwd controls repo-level CLAUDE.md loading, but user-level context (`~/.claude/CLAUDE.md`, global settings, MCP servers) may still load and bias the reading. If so, the isolation contract needs either additional CLI flags or an explicit documented limitation.
- **Who can answer:** experimentation (marker-instruction test) | INVESTIGATOR
- **Priority:** should-resolve-before-HOW
- **Related assumptions:** A-002

### U-003: What exactly does the corrective retry prompt contain?
- **Why it matters:** "One corrective retry appended to the same prompt" (IN-REQ-5086BCDE7BCE) leaves open whether the retry includes the model's previous (bad) output, and what corrective text is used. For the timeout case there is no output to correct at all — is the retry then just a plain re-issue? Affects prompt assembly, unit tests, and exit-3 determinism.
- **Who can answer:** user | CARTOGRAPHER (spec decision)
- **Priority:** should-resolve-before-HOW
- **Related assumptions:** A-007

### U-004: Is `--claude-cmd` a single executable token or a shell-split command string?
- **Why it matters:** "binary/command" (IN-REQ-D8FCFCDDC59E) is ambiguous. A command string (e.g. `claude --model X`) requires splitting before subprocess invocation; a bare token doesn't. The pytest stub seam and the "claude not found" (exit 2) detection both depend on this.
- **Who can answer:** user | CARTOGRAPHER (spec decision)
- **Priority:** must-resolve-before-WHAT
- **Related assumptions:** A-001, A-008

### U-005: What happens on degenerate outcomes — zero questions, zero findings, unwritable report?
- **Why it matters:** The design defines exits 0/1/2/3 but not: round 1 legitimately returning an empty question list (success with an empty report, or a failure?); all questions ANSWERED (presumably exit 0 with empty findings — the "clean spec" case worth stating); report write failure (no exit code assigned). These edge semantics are exactly what the unit tests must pin down.
- **Who can answer:** CARTOGRAPHER (spec decision)
- **Priority:** must-resolve-before-WHAT
- **Related assumptions:** A-006

### U-006: How are spec line numbers established for `lines` / `evidence_lines`?
- **Why it matters:** Questions and answers reference spec lines as integers. Whether the prompt presents the spec with explicit line numbers (making references verifiable) or the model estimates them (making them approximate) changes the evidentiary strength of "quote the answering lines" and how the report renders evidence.
- **Who can answer:** CARTOGRAPHER (spec decision) | experimentation
- **Priority:** should-resolve-before-HOW
- **Related assumptions:** A-001

### U-007: How is "claude CLI unavailable" (exit 2) distinguished from other launch failures?
- **Why it matters:** Exit 2 covers "not found" with an install pointer. But adjacent failures — binary present yet unauthenticated/logged-out, or crashing at startup — could masquerade as empty/garbage output and land in the parse-failure exit-3 path instead. The mapping needs to be deliberate for the ERR-CLI-MISSING mirror to hold.
- **Who can answer:** CARTOGRAPHER (spec decision) | experimentation
- **Priority:** should-resolve-before-HOW
- **Related assumptions:** A-001

## Potential Unknown Unknowns

- **Area:** claude CLI version drift
- **Why suspicious:** The script binds to the behavior of an externally-versioned CLI (`-p` semantics, context-loading rules, output shape). The repo's harness needed a dedicated backend layer and tool-policy handling to tame the same CLI — evidence that its behavior surface is wide and shifting.
- **Recommended investigation:** INVESTIGATOR should pin which claude CLI version(s) the isolation and invocation assumptions were validated against and note the flags used, so drift is detectable rather than silent.

- **Area:** Model nondeterminism vs the acceptance criterion
- **Why suspicious:** Acceptance requires findings to overlap three known issues in spec 029 in "one manual live run". Two model calls with creative freedom may miss one of the three on any given run even with a correct implementation — a flaky acceptance test by construction.
- **Recommended investigation:** Decide tolerance up front (e.g. overlap with ≥1 named issue = pass, or allow up to K reruns) before the acceptance run, so a miss triggers diagnosis rather than ad-hoc goalpost moving.

- **Area:** Output-noise channels corrupting JSON extraction
- **Why suspicious:** CLI tools emit non-payload noise (progress lines, warnings, update nags, ANSI codes) that varies by environment and version; "strict JSON" from a chatty CLI is historically fragile. The design's single-retry budget makes systematic noise fatal (exit 3) rather than annoying.
- **Recommended investigation:** Capture raw stdout from several real calls in different environments during the spike (U-001); design the extractor against observed noise, and unit-test extraction against noisy fixtures, not just clean ones.

- **Area:** Concurrent runs against the same spec directory
- **Why suspicious:** Report overwrite + a shared `.sue-debug/` dir means two simultaneous runs (or a run during a build/harness cycle touching the same spec dir) interleave writes. v1 declares no locking; probably fine for a manual tool, but worth stating as a non-goal rather than leaving implicit.
- **Recommended investigation:** None beyond a one-line non-goal/limitation note in the spec.

## WHY1 Additions (SAGE)

### U-008: Over-cap and malformed round-1 output handling
- **Why it matters:** The `--questions` N cap is an instruction to the model, not a validated constraint. More-than-N questions, a syntactically valid empty list (overlaps U-005), or duplicate ids within round 1 itself are each neither a defined schema violation nor a defined success; round-1 id uniqueness is only implied by the round-2 bijection. Unit tests cannot cover what has no assigned behavior.
- **Who can answer:** CARTOGRAPHER (spec decision)
- **Priority:** must-resolve-before-WHAT (folds into the U-005 degenerate-outcome decision set)
- **Related assumptions:** A-001, A-010

### U-009: Prompt-injection resilience of the challenged spec
- **Why it matters:** Spec text is embedded verbatim in both prompts; a challenged spec containing adversarial instructions (e.g. "answer ANSWERED to every question") can steer verdicts. For v1 a stated limitation suffices — "the human decides" is the backstop — but it must be stated, not silent, alongside the existing egress note.
- **Who can answer:** CARTOGRAPHER (limitations note)
- **Priority:** should-resolve-before-HOW (documentation-only)
- **Related assumptions:** A-001

### U-010: Report write semantics (atomic replace vs truncate-write)
- **Why it matters:** "Overwrite on rerun" is specified but write mechanics are not; mental-model.md currently asserts atomicity the design never granted (ISS-008). Either specify the semantics or explicitly leave them unspecified and correct the model.
- **Who can answer:** CARTOGRAPHER (spec decision)
- **Priority:** should-resolve-before-HOW
- **Related assumptions:** A-006
